"""lookup_guest tool: is the caller a returning guest, from their caller ID."""

from pydantic import BaseModel

from src.db.bookings import BookingRepository
from src.tools.context import CallContext


class LookupGuestInput(BaseModel):
    """No arguments: the caller ID comes from the call context."""


class LookupGuestOk(BaseModel):
    """Result. found=False covers both no match and a withheld number."""

    ok: bool = True
    found: bool
    first_name: str | None = None
    last_name: str | None = None
    has_email: bool | None = None


async def lookup_guest(bookings: BookingRepository, ctx: CallContext) -> LookupGuestOk:
    """Find the guest whose phone is the caller ID.

    Args:
        bookings: Guest and reservation access.
        ctx: The call, with the caller ID if it was not withheld.

    Returns:
        The guest's name and whether an email is on file, or found=False.
    """
    if ctx.caller_phone is None:
        return LookupGuestOk(found=False)
    guest = await bookings.find_guest(ctx.caller_phone)
    if guest is None:
        return LookupGuestOk(found=False)
    return LookupGuestOk(found=True, **guest.model_dump())
