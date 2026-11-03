"""Tests for the get_booking tool."""

from datetime import date

import pytest

from src.tools.get_booking import GetBookingError, GetBookingInput, get_booking
from src.tools.stay import BookingDetails
from tests.booking_fixtures import hotel_with_booking


@pytest.mark.asyncio
async def test_reads_back_a_booking_said_with_spaces() -> None:
    """The reference may come as spoken groups; the name in any case."""
    repo, booking = await hotel_with_booking()
    spoken = f"{booking.reference[:3]} {booking.reference[3:]}"

    result = await get_booking(
        repo, GetBookingInput(reference=spoken, last_name="testa")
    )

    assert result == BookingDetails(
        reference=booking.reference,
        status="confirmed",
        first_name="Ada",
        room_type="Superior",
        check_in=date(2026, 12, 10),
        check_out=date(2026, 12, 12),
        nights=2,
        adults=2,
        total_eur=200,
    )


@pytest.mark.asyncio
async def test_a_wrong_name_or_reference_is_not_found() -> None:
    """Both mistakes give the same answer, so references cannot be probed."""
    repo, booking = await hotel_with_booking()

    wrong_name = await get_booking(
        repo, GetBookingInput(reference=booking.reference, last_name="Rossi")
    )
    wrong_ref = await get_booking(
        repo, GetBookingInput(reference="000000", last_name="Testa")
    )

    assert wrong_name == wrong_ref == GetBookingError(reason="not_found")
