"""take_message tool: pass the caller's message to reception by email.

This is the handoff to a person. The tool checks there is a way to reach the
caller, then answers; a background job emails the hotel's own inbox.
"""

from typing import Literal

from pydantic import BaseModel, Field

from src.email.followup import reception_message
from src.email.sender import EmailSender
from src.tools.context import CallContext
from src.tools.once import deliver, first_time
from src.tools.send_confirmation_email import Spawn, run_in_background
from src.tools.stay import E164, EMAIL


class TakeMessageInput(BaseModel):
    """Arguments the agent passes."""

    first_name: str = Field(min_length=1, description="The caller's first name.")
    last_name: str = Field(min_length=1, description="The caller's last name.")
    message: str = Field(
        min_length=1,
        max_length=1000,
        description=(
            "A short summary, in your own words, of what the caller wants reception "
            "to know or do, in the caller's language."
        ),
    )
    language: Literal["it", "en"] = Field(
        description="The language the caller is speaking now: 'it' or 'en'."
    )
    email: str | None = Field(
        default=None,
        description=(
            "The caller's email, only if they gave one for the reply; spell it back "
            "once before passing it."
        ),
    )
    phone: str | None = Field(
        default=None,
        description=(
            "A phone number in international format with the country code, for "
            "example +393331234567; only when the caller's number is withheld or "
            "they want to be reached on another number."
        ),
    )


class TakeMessageOk(BaseModel):
    """The message is on its way to reception."""

    ok: bool = True


class TakeMessageError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str


async def take_message(
    sender: EmailSender,
    ctx: CallContext,
    inp: TakeMessageInput,
    spawn: Spawn = run_in_background,
) -> TakeMessageOk | TakeMessageError:
    """Queue the caller's message for reception, once per call and message.

    Args:
        sender: Sends from, and to, the hotel's address.
        ctx: The call, with the caller ID if it was not withheld.
        inp: Name, message, language and an optional contact.
        spawn: Runs the send after the tool has answered.

    Returns:
        ok once the send is queued; otherwise contact_required, invalid_phone or
        invalid_email.
    """
    if inp.phone is not None and not E164.match(inp.phone):
        return TakeMessageError(reason="invalid_phone")
    if inp.email is not None and not EMAIL.match(inp.email):
        return TakeMessageError(reason="invalid_email")
    phone = inp.phone or ctx.caller_phone
    if phone is None and inp.email is None:
        return TakeMessageError(reason="contact_required")
    key = f"{ctx.call_id}|message|{inp.message}"
    if first_time(key):
        message = reception_message(
            hotel_inbox=sender.address,
            first_name=inp.first_name,
            last_name=inp.last_name,
            message=inp.message,
            language=inp.language,
            phone=phone,
            email=inp.email,
            call_id=ctx.call_id,
        )
        spawn(deliver(sender, message, key, ctx.call_id, "message for reception"))
    return TakeMessageOk()
