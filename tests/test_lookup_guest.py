"""Tests for the lookup_guest tool."""

from datetime import date

import pytest

from src.db.bookings import InMemoryBookingRepository, NewBooking
from src.db.hotel import RoomType
from src.tools.context import CallContext
from src.tools.lookup_guest import LookupGuestOk, lookup_guest

PHONE = "+12025550199"


async def hotel_with_guest(email: str | None) -> InMemoryBookingRepository:
    """A one-room hotel where Ada Testa has booked from PHONE."""
    repo = InMemoryBookingRepository(
        room_types=[RoomType(name="Superior", max_guests=2, rooms=1)],
        rates=[],
        stays=[],
    )
    await repo.create_booking(
        NewBooking(
            idempotency_key="k",
            room_type="Superior",
            check_in=date(2026, 12, 10),
            check_out=date(2026, 12, 12),
            adults=1,
            total_cents=0,
            first_name="Ada",
            last_name="Testa",
            phone=PHONE,
            email=email,
            language="it",
        )
    )
    return repo


@pytest.mark.asyncio
async def test_a_returning_caller_is_found_by_caller_id() -> None:
    """The name comes back, and only whether an email is on file."""
    repo = await hotel_with_guest(email="ada@example.com")

    result = await lookup_guest(repo, CallContext(call_id="c", caller_phone=PHONE))

    assert result == LookupGuestOk(
        found=True, first_name="Ada", last_name="Testa", has_email=True
    )
    assert "ada@example.com" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_an_unknown_caller_is_not_found() -> None:
    """No guest with that phone."""
    repo = await hotel_with_guest(email=None)

    result = await lookup_guest(
        repo, CallContext(call_id="c", caller_phone="+12025550100")
    )

    assert result == LookupGuestOk(found=False)


@pytest.mark.asyncio
async def test_a_withheld_number_is_not_found() -> None:
    """No caller ID means no lookup at all."""
    repo = await hotel_with_guest(email=None)

    result = await lookup_guest(repo, CallContext(call_id="c", caller_phone=None))

    assert result == LookupGuestOk(found=False)
