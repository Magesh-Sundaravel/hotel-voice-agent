"""Tests for the modify_booking tool."""

from datetime import UTC, date, datetime

import pytest

from src.tools.modify_booking import (
    ModifyBookingError,
    ModifyBookingInput,
    modify_booking,
)
from src.tools.stay import BookingDetails
from tests.booking_fixtures import TODAY, hotel_with_booking


@pytest.mark.asyncio
async def test_a_longer_stay_is_repriced_and_keeps_its_reference() -> None:
    """Only check_out changes; the rest of the booking is kept."""
    repo, booking = await hotel_with_booking()

    result = await modify_booking(
        repo,
        repo,
        ModifyBookingInput(
            reference=booking.reference, last_name="Testa", check_out=date(2026, 12, 13)
        ),
        TODAY,
    )

    assert isinstance(result, BookingDetails)
    assert (result.reference, result.check_out, result.nights, result.total_eur) == (
        booking.reference,
        date(2026, 12, 13),
        3,
        300,
    )


@pytest.mark.asyncio
async def test_an_upgrade_changes_room_type_and_price() -> None:
    """Moving to the Suite reprices at the Suite's rate."""
    repo, booking = await hotel_with_booking()

    result = await modify_booking(
        repo,
        repo,
        ModifyBookingInput(
            reference=booking.reference, last_name="Testa", room_type="suite"
        ),
        TODAY,
    )

    assert isinstance(result, BookingDetails)
    assert (result.room_type, result.total_eur) == ("Suite", 600)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({}, "nothing_to_change"),
        ({"last_name": "Rossi", "adults": 1}, "not_found"),
        ({"adults": 3}, "too_many_guests"),
        ({"adults": 0}, "invalid_guests"),
        ({"room_type": "Attic"}, "unknown_room_type"),
        ({"check_in": date(2026, 12, 12)}, "invalid_dates"),
    ],
)
async def test_bad_changes_are_refused_with_a_reason(
    fields: dict[str, object], reason: str
) -> None:
    """Each problem comes back as a reason, and the booking is unchanged."""
    repo, booking = await hotel_with_booking()
    inp = ModifyBookingInput.model_validate(
        {"reference": booking.reference, "last_name": "Testa", **fields}
    )

    result = await modify_booking(repo, repo, inp, TODAY)

    assert result == ModifyBookingError(reason=reason)
    assert await repo.get_booking(booking.reference, "Testa") == booking


@pytest.mark.asyncio
async def test_a_cancelled_booking_cannot_be_modified() -> None:
    """Offer a new booking instead."""
    repo, booking = await hotel_with_booking()
    await repo.cancel_booking(
        booking.reference, "Testa", datetime(2026, 11, 2, tzinfo=UTC)
    )

    result = await modify_booking(
        repo,
        repo,
        ModifyBookingInput(reference=booking.reference, last_name="Testa", adults=1),
        TODAY,
    )

    assert result == ModifyBookingError(reason="cancelled")


@pytest.mark.asyncio
async def test_a_finished_stay_cannot_be_modified() -> None:
    """On 12 December Ada has already checked out."""
    repo, booking = await hotel_with_booking()

    result = await modify_booking(
        repo,
        repo,
        ModifyBookingInput(reference=booking.reference, last_name="Testa", adults=1),
        date(2026, 12, 12),
    )

    assert result == ModifyBookingError(reason="past_booking")
