"""get_booking tool: read back an existing booking."""

from pydantic import BaseModel, Field

from src.db.bookings import BookingRepository
from src.tools.stay import (
    LAST_NAME_DESCRIPTION,
    REFERENCE_DESCRIPTION,
    BookingDetails,
    clean_reference,
    details,
)


class GetBookingInput(BaseModel):
    """Arguments the agent passes."""

    reference: str = Field(description=REFERENCE_DESCRIPTION)
    last_name: str = Field(description=LAST_NAME_DESCRIPTION)


class GetBookingError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str


async def get_booking(
    bookings: BookingRepository, inp: GetBookingInput
) -> BookingDetails | GetBookingError:
    """Find a booking by reference and the guest's last name.

    Args:
        bookings: Guest and reservation access.
        inp: Reference and last name.

    Returns:
        The booking, or not_found for a wrong reference or a wrong name alike.
    """
    booking = await bookings.get_booking(clean_reference(inp.reference), inp.last_name)
    if booking is None:
        return GetBookingError(reason="not_found")
    return details(booking)
