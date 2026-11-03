"""Tests for the cancel_booking tool."""

from datetime import UTC, date, datetime

import pytest

from src.tools.cancel_booking import (
    CancelBookingError,
    CancelBookingInput,
    CancelBookingOk,
    cancel_booking,
)
from tests.booking_fixtures import hotel_with_booking

# Ada checks in 10 December 2026 at 15:00 Rome (14:00 UTC), so cancelling is free
# until 8 December at 14:00 UTC.
FREE_UNTIL = datetime(2026, 12, 8, 14, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_an_early_cancellation_is_free_and_frees_the_room() -> None:
    """Exactly 48 hours before check-in is still free."""
    repo, booking = await hotel_with_booking()

    result = await cancel_booking(
        repo,
        CancelBookingInput(reference=booking.reference, last_name="Testa"),
        FREE_UNTIL,
    )

    assert result == CancelBookingOk(
        reference=booking.reference, late_cancellation=False
    )
    assert (
        await repo.count_booked("Superior", date(2026, 12, 10), date(2026, 12, 12)) == 0
    )


@pytest.mark.asyncio
async def test_a_cancellation_inside_48_hours_is_late() -> None:
    """One minute past the free window."""
    repo, booking = await hotel_with_booking()

    result = await cancel_booking(
        repo,
        CancelBookingInput(reference=booking.reference, last_name="Testa"),
        datetime(2026, 12, 8, 14, 1, tzinfo=UTC),
    )

    assert result == CancelBookingOk(
        reference=booking.reference, late_cancellation=True
    )


@pytest.mark.asyncio
async def test_cancelling_again_keeps_the_first_answer() -> None:
    """A retry after a free cancellation is still free, even if it comes late."""
    repo, booking = await hotel_with_booking()
    inp = CancelBookingInput(reference=booking.reference, last_name="Testa")
    await cancel_booking(repo, inp, FREE_UNTIL)

    again = await cancel_booking(repo, inp, datetime(2026, 12, 9, tzinfo=UTC))

    assert again == CancelBookingOk(
        reference=booking.reference, late_cancellation=False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("last_name", "now", "reason"),
    [
        ("Rossi", FREE_UNTIL, "not_found"),
        ("Testa", datetime(2026, 12, 12, 10, 0, tzinfo=UTC), "past_booking"),
    ],
)
async def test_refused_cancellations_change_nothing(
    last_name: str, now: datetime, reason: str
) -> None:
    """A wrong name or a finished stay is refused, and the booking stays confirmed."""
    repo, booking = await hotel_with_booking()

    result = await cancel_booking(
        repo, CancelBookingInput(reference=booking.reference, last_name=last_name), now
    )

    assert result == CancelBookingError(reason=reason)
    found = await repo.get_booking(booking.reference, "Testa")
    assert found is not None and found.status == "confirmed"
