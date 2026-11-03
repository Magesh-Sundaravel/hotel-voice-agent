"""Validation and pricing shared by create_booking and modify_booking."""

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from src.db.bookings import Booking
from src.db.hotel import HotelRepository
from src.tools.get_rates import GetRatesError, GetRatesInput, get_rates

HOTEL_TZ = ZoneInfo("Europe/Rome")
E164 = re.compile(r"^\+[1-9]\d{6,14}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

REFERENCE_DESCRIPTION = (
    "The 6-digit booking reference the guest was given, for example 482913. "
    "Spaces between the digits are fine."
)
LAST_NAME_DESCRIPTION = (
    "The last name the booking is under, as the caller spells it. Upper or lower "
    "case does not matter."
)


def hotel_today(now: datetime | None = None) -> date:
    """Return the current date in the hotel's timezone (Europe/Rome).

    Args:
        now: Override for the current instant (tests).

    Returns:
        Today's date in Rome, whatever timezone the server runs in.
    """
    return (now or datetime.now(UTC)).astimezone(HOTEL_TZ).date()


def clean_reference(reference: str) -> str:
    """Keep only the digits, so '482 913' matches 482913."""
    return re.sub(r"\D", "", reference)


class PricedStay(BaseModel):
    """A valid stay, with the hotel's spelling of the room type and its price."""

    room_type: str
    nights: int
    total_eur: int


class BookingDetails(BaseModel):
    """A booking as the agent reads it back."""

    ok: bool = True
    reference: str
    status: str
    first_name: str
    room_type: str
    check_in: date
    check_out: date
    nights: int
    adults: int
    total_eur: int


async def price_stay(
    hotel: HotelRepository,
    room_type: str,
    check_in: date,
    check_out: date,
    adults: int,
    today: date | None,
) -> PricedStay | str:
    """Check a stay can be booked and price it.

    Args:
        hotel: Inventory and rates.
        room_type: Room type name, any case.
        check_in: Arrival date.
        check_out: Departure date, exclusive.
        adults: Number of adults.
        today: Override for the current date (tests).

    Returns:
        The priced stay, or the reason it cannot be booked.
    """
    if adults < 1:
        return "invalid_guests"
    rates = await get_rates(
        hotel,
        GetRatesInput(room_type=room_type, check_in=check_in, check_out=check_out),
        today,
    )
    if isinstance(rates, GetRatesError):
        return rates.reason
    max_guests = next(
        rt.max_guests
        for rt in await hotel.list_room_types()
        if rt.name == rates.room_type
    )
    if adults > max_guests:
        return "too_many_guests"
    return PricedStay(
        room_type=rates.room_type, nights=rates.nights, total_eur=rates.total_eur
    )


def details(booking: Booking) -> BookingDetails:
    """Turn a stored booking into what the agent reads back."""
    return BookingDetails(
        reference=booking.reference,
        status=booking.status,
        first_name=booking.first_name,
        room_type=booking.room_type,
        check_in=booking.check_in,
        check_out=booking.check_out,
        nights=(booking.check_out - booking.check_in).days,
        adults=booking.adults,
        total_eur=booking.total_cents // 100,
    )
