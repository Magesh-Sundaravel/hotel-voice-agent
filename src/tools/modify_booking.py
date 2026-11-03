"""modify_booking tool: change the dates, adults or room type of a booking."""

from datetime import date

from pydantic import BaseModel, Field

from src.db.bookings import BookingChange, BookingConflict, BookingRepository
from src.db.hotel import HotelRepository
from src.tools import CHECK_IN_DESCRIPTION, CHECK_OUT_DESCRIPTION
from src.tools.stay import (
    LAST_NAME_DESCRIPTION,
    REFERENCE_DESCRIPTION,
    BookingDetails,
    clean_reference,
    details,
    price_stay,
)


class ModifyBookingInput(BaseModel):
    """Arguments the agent passes. Leave out what stays the same."""

    reference: str = Field(description=REFERENCE_DESCRIPTION)
    last_name: str = Field(description=LAST_NAME_DESCRIPTION)
    check_in: date | None = Field(
        default=None,
        description=f"New arrival date, only if it changes. {CHECK_IN_DESCRIPTION}",
    )
    check_out: date | None = Field(
        default=None,
        description=f"New departure date, only if it changes. {CHECK_OUT_DESCRIPTION}",
    )
    adults: int | None = Field(
        default=None, description="New number of people staying, only if it changes."
    )
    room_type: str | None = Field(
        default=None,
        description=(
            "New room type, only if it changes, copied from a check_availability "
            "result. Upper or lower case does not matter."
        ),
    )


class ModifyBookingError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str


async def modify_booking(
    hotel: HotelRepository,
    bookings: BookingRepository,
    inp: ModifyBookingInput,
    today: date | None = None,
) -> BookingDetails | ModifyBookingError:
    """Change a confirmed booking, rechecked and repriced, keeping its reference.

    Args:
        hotel: Inventory and rates.
        bookings: Guest and reservation access.
        inp: Reference, last name and the fields that change.
        today: Override for the current date (tests).

    Returns:
        The updated booking, or an error with a spoken-friendly reason.
    """
    if all(v is None for v in (inp.check_in, inp.check_out, inp.adults, inp.room_type)):
        return ModifyBookingError(reason="nothing_to_change")
    reference = clean_reference(inp.reference)
    current = await bookings.get_booking(reference, inp.last_name)
    if current is None:
        return ModifyBookingError(reason="not_found")
    if current.status == "cancelled":
        return ModifyBookingError(reason="cancelled")
    if current.check_out <= (today or date.today()):
        return ModifyBookingError(reason="past_booking")
    check_in = inp.check_in or current.check_in
    check_out = inp.check_out or current.check_out
    adults = current.adults if inp.adults is None else inp.adults
    stay = await price_stay(
        hotel, inp.room_type or current.room_type, check_in, check_out, adults, today
    )
    if isinstance(stay, str):
        return ModifyBookingError(reason=stay)
    result = await bookings.modify_booking(
        reference,
        inp.last_name,
        BookingChange(
            room_type=stay.room_type,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            total_cents=stay.total_eur * 100,
        ),
    )
    if result is None:
        return ModifyBookingError(reason="not_found")
    if isinstance(result, BookingConflict):
        return ModifyBookingError(reason=result.reason)
    return details(result)
