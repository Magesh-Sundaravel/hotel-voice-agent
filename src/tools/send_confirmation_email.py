"""send_confirmation_email tool: email the booking with a calendar invite.

The tool only checks that there is something to send, then answers. A background
job does the rest: mark the booking (so it is sent once), read it again (so a
modify made meanwhile is what gets mailed), build the email and send it. Any
failure in the job clears the mark, so a later call can retry.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.db.bookings import BookingRepository
from src.email.compose import confirmation_message
from src.email.sender import EmailSender, EmailSendError
from src.tools.stay import LAST_NAME_DESCRIPTION, REFERENCE_DESCRIPTION, clean_reference

logger = logging.getLogger(__name__)

Spawn = Callable[[Coroutine[Any, Any, None]], None]

# Background sends still running; held so the event loop does not drop them.
_running: set[asyncio.Task[None]] = set()


def run_in_background(job: Coroutine[Any, Any, None]) -> None:
    """Start a job after the tool has answered, keeping a reference until it ends."""
    task = asyncio.create_task(job)
    _running.add(task)
    task.add_done_callback(_running.discard)


async def drain_background(timeout_s: float) -> None:
    """Wait for queued sends at shutdown, before their HTTP client and pool close.

    Args:
        timeout_s: Longest wait; sends still running after it are abandoned.
    """
    if _running:
        await asyncio.wait(set(_running), timeout=timeout_s)


class SendConfirmationEmailInput(BaseModel):
    """Arguments the agent passes."""

    reference: str = Field(description=REFERENCE_DESCRIPTION)
    last_name: str = Field(description=LAST_NAME_DESCRIPTION)
    language: Literal["it", "en"] = Field(
        description="The language the caller is speaking now: 'it' or 'en'."
    )


class SendConfirmationEmailOk(BaseModel):
    """The email is on its way (or was already sent)."""

    ok: bool = True


class SendConfirmationEmailError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str


async def _deliver(
    bookings: BookingRepository,
    sender: EmailSender,
    inp: SendConfirmationEmailInput,
    reference: str,
    guest_id: str,
    now: datetime,
) -> None:
    """Claim, re-read, build and send; on any failure log and release the claim."""
    if not await bookings.claim_confirmation(reference, now):
        return  # already sent for this version of the booking
    try:
        target = await bookings.get_confirmation_target(reference, inp.last_name)
        if target is None or target.email is None:
            raise LookupError("booking or email gone since the tool answered")
        if target.booking.status == "cancelled":
            raise LookupError("booking cancelled since the tool answered")
        message = confirmation_message(
            target.booking,
            to=target.email,
            sender=sender.address,
            language=inp.language,
            now=now,
        )
        await sender.send(message)
    except Exception as error:  # noqa: BLE001 - a stuck claim would block the email for good
        # Text only from our own errors, which never carry PII; type for the rest.
        detail = str(error) if isinstance(error, EmailSendError | LookupError) else ""
        logger.warning(
            "confirmation email failed for guest %s: %s %s",
            guest_id,
            type(error).__name__,
            detail,
        )
        try:
            await bookings.release_confirmation(reference, now)
        except Exception as release_error:  # noqa: BLE001 - nothing left to raise to
            logger.warning(
                "confirmation claim not released for guest %s: %s",
                guest_id,
                type(release_error).__name__,
            )


async def send_confirmation_email(
    bookings: BookingRepository,
    sender: EmailSender,
    inp: SendConfirmationEmailInput,
    now: datetime,
    spawn: Spawn = run_in_background,
) -> SendConfirmationEmailOk | SendConfirmationEmailError:
    """Queue the confirmation email for a booking, at most once per version of it.

    Args:
        bookings: Guest and reservation access.
        sender: Sends from the hotel's address.
        inp: Reference, last name and the language of the call.
        now: Current time, for the claim and the invite.
        spawn: Runs the send after the tool has answered.

    Returns:
        ok once the send is queued (a repeat sends nothing); otherwise not_found,
        cancelled or no_email_on_file.
    """
    reference = clean_reference(inp.reference)
    target = await bookings.get_confirmation_target(reference, inp.last_name)
    if target is None:
        return SendConfirmationEmailError(reason="not_found")
    if target.booking.status == "cancelled":
        return SendConfirmationEmailError(reason="cancelled")
    if target.email is None:
        return SendConfirmationEmailError(reason="no_email_on_file")
    # Spawning is the last step and does not await, so a tool timeout cannot
    # leave a claim behind without a job to send or release it.
    spawn(_deliver(bookings, sender, inp, reference, target.guest_id, now))
    return SendConfirmationEmailOk()
