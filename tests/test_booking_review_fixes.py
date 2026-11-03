"""Regression tests for the booking review follow-ups."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from src.db.bookings import BookingConflict, NewBooking
from src.db.postgres import PostgresBookingRepository
from src.tools import modify_booking as modify_module
from src.tools.modify_booking import (
    ModifyBookingError,
    ModifyBookingInput,
    modify_booking,
)
from src.tools.stay import hotel_today
from tests.booking_fixtures import hotel_with_booking

NEW = NewBooking(
    first_name="Ada",
    last_name="Testa",
    phone="+12025550199",
    email=None,
    language="en",
    room_type="Superior",
    check_in=date(2026, 12, 10),
    check_out=date(2026, 12, 12),
    adults=2,
    total_cents=20000,
    idempotency_key="key-1",
)


@pytest.mark.asyncio
async def test_a_unique_violation_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reference or idempotency-key collision retries instead of failing."""
    repo = PostgresBookingRepository(MagicMock())
    booking = MagicMock()
    once = AsyncMock(side_effect=[asyncpg.UniqueViolationError("dup"), booking])
    monkeypatch.setattr(repo, "_create_once", once)

    assert await repo.create_booking(NEW) is booking
    assert once.await_count == 2


@pytest.mark.asyncio
async def test_repeated_unique_violations_give_up_with_a_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retries are bounded."""
    repo = PostgresBookingRepository(MagicMock())
    monkeypatch.setattr(
        repo, "_create_once", AsyncMock(side_effect=asyncpg.UniqueViolationError("dup"))
    )

    assert await repo.create_booking(NEW) == BookingConflict(reason="no_availability")


def test_hotel_today_is_the_date_in_rome() -> None:
    """23:30 UTC on 11 December is already 12 December in Rome."""
    assert hotel_today(datetime(2026, 12, 11, 23, 30, tzinfo=UTC)) == date(2026, 12, 12)


@pytest.mark.asyncio
async def test_modify_uses_the_hotel_date_when_today_is_not_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ada checks out 12 December; in Rome it is already the 12th."""
    monkeypatch.setattr(modify_module, "hotel_today", lambda: date(2026, 12, 12))
    repo, booking = await hotel_with_booking()

    result = await modify_booking(
        repo,
        repo,
        ModifyBookingInput(reference=booking.reference, last_name="Testa", adults=1),
    )

    assert result == ModifyBookingError(reason="past_booking")
