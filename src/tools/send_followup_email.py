"""send_followup_email tool: after a tool keeps failing, invite the caller to email.

The tool finds an address (the one spelled by the caller, else the one on file for
the caller ID), then answers; a background job sends the email.
"""

from typing import Literal

from pydantic import BaseModel, Field

from src.db.bookings import BookingRepository
from src.email.followup import Topic, followup_message
from src.email.sender import EmailSender
from src.tools.context import CallContext
from src.tools.once import deliver, first_time
from src.tools.send_confirmation_email import Spawn, run_in_background
from src.tools.stay import EMAIL


class SendFollowupEmailInput(BaseModel):
    """Arguments the agent passes."""

    topic: Topic = Field(
        description=(
            "What the caller was trying to do when the tool failed: 'booking' for a "
            "new booking, 'change' or 'cancellation' for an existing one, "
            "'information' for availability, prices or anything else."
        )
    )
    language: Literal["it", "en"] = Field(
        description="The language the caller is speaking now: 'it' or 'en'."
    )
    email: str | None = Field(
        default=None,
        description=(
            "The caller's email, only if they spelled one; spell it back once "
            "before passing it. Leave it out to use the email on file."
        ),
    )


class SendFollowupEmailOk(BaseModel):
    """The email is on its way (or was already sent in this call)."""

    ok: bool = True


class SendFollowupEmailError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str


async def send_followup_email(
    bookings: BookingRepository,
    sender: EmailSender,
    ctx: CallContext,
    inp: SendFollowupEmailInput,
    spawn: Spawn = run_in_background,
) -> SendFollowupEmailOk | SendFollowupEmailError:
    """Queue the follow-up email, at most once per call and address.

    Args:
        bookings: Guest access, for the email on file.
        sender: Sends from the hotel's address.
        ctx: The call, with the caller ID if it was not withheld.
        inp: Topic, language and an optional email.
        spawn: Runs the send after the tool has answered.

    Returns:
        ok once the send is queued; otherwise email_required or invalid_email.
    """
    if inp.email is not None and not EMAIL.match(inp.email):
        return SendFollowupEmailError(reason="invalid_email")
    contact = (
        await bookings.find_guest_contact(ctx.caller_phone)
        if ctx.caller_phone
        else None
    )
    to = inp.email or (contact.email if contact else None)
    if to is None:
        return SendFollowupEmailError(reason="email_required")
    key = f"{ctx.call_id}|followup|{to.lower()}"
    if first_time(key):
        message = followup_message(
            to=to,
            sender=sender.address,
            first_name=contact.first_name if contact else None,
            topic=inp.topic,
            language=inp.language,
        )
        spawn(deliver(sender, message, key, ctx.call_id, "follow-up email"))
    return SendFollowupEmailOk()
