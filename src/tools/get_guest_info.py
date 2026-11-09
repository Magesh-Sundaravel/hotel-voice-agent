"""get_guest_info tool: is the caller a returning guest, from their caller ID."""

from pydantic import BaseModel

from src.db.bookings import BookingRepository
from src.tools.context import CallContext


class GetGuestInfoInput(BaseModel):
    """No arguments: the caller ID comes from the call context."""


class GetGuestInfoOk(BaseModel):
    """Result. found=False covers both no match and a withheld number."""

    ok: bool = True
    found: bool
    first_name: str | None = None
    last_name: str | None = None
    has_email: bool | None = None


async def get_guest_info(
    bookings: BookingRepository, ctx: CallContext
) -> GetGuestInfoOk:
    """Find the guest whose phone is the caller ID.

    Args:
        bookings: Guest and reservation access.
        ctx: The call, with the caller ID if it was not withheld.

    Returns:
        The guest's name and whether an email is on file, or found=False.
    """
    if ctx.caller_phone is None:
        return GetGuestInfoOk(found=False)
    guest = await bookings.find_guest(ctx.caller_phone)
    if guest is None:
        return GetGuestInfoOk(found=False)
    return GetGuestInfoOk(found=True, **guest.model_dump())
