"""Tests for the check_availability tool (seam A)."""

from datetime import date

import pytest

from src.db.hotel import InMemoryHotelRepository, RoomType, Stay
from src.tools.check_availability import (
    AvailabilityError,
    AvailabilityInput,
    AvailabilityOk,
    check_availability,
)

TODAY = date(2026, 11, 2)


def make_repo(stays: list[Stay] | None = None) -> InMemoryHotelRepository:
    """Build a tiny hotel: 2 Superior (max 2) and 1 Suite (max 4)."""
    return InMemoryHotelRepository(
        room_types=[
            RoomType(name="Superior", max_guests=2, rooms=2),
            RoomType(name="Suite", max_guests=4, rooms=1),
        ],
        rates=[],
        stays=stays or [],
    )


@pytest.mark.asyncio
async def test_lists_room_types_with_free_rooms() -> None:
    """An empty hotel offers every room type that fits the party."""
    result = await check_availability(
        make_repo(),
        AvailabilityInput(
            check_in=date(2026, 12, 10), check_out=date(2026, 12, 12), guests=2
        ),
        today=TODAY,
    )
    assert isinstance(result, AvailabilityOk)
    assert {(o.room_type, o.rooms_free) for o in result.options} == {
        ("Superior", 2),
        ("Suite", 1),
    }


def stay(check_in: date, check_out: date, room_type: str = "Suite") -> Stay:
    """Build an existing stay."""
    return Stay(room_type=room_type, check_in=check_in, check_out=check_out)


@pytest.mark.asyncio
async def test_overlapping_stay_removes_fully_booked_type() -> None:
    """The only Suite is taken on one of the nights, so Suite is not offered."""
    repo = make_repo([stay(date(2026, 12, 11), date(2026, 12, 13))])
    result = await check_availability(
        repo,
        AvailabilityInput(
            check_in=date(2026, 12, 10), check_out=date(2026, 12, 12), guests=2
        ),
        today=TODAY,
    )
    assert isinstance(result, AvailabilityOk)
    assert [o.room_type for o in result.options] == ["Superior"]


@pytest.mark.asyncio
async def test_checkout_day_is_free_for_a_new_guest() -> None:
    """A stay ending on the 10th does not block a stay starting on the 10th."""
    repo = make_repo([stay(date(2026, 12, 8), date(2026, 12, 10))])
    result = await check_availability(
        repo,
        AvailabilityInput(
            check_in=date(2026, 12, 10), check_out=date(2026, 12, 12), guests=2
        ),
        today=TODAY,
    )
    assert isinstance(result, AvailabilityOk)
    assert "Suite" in [o.room_type for o in result.options]


@pytest.mark.asyncio
async def test_fully_booked_is_ok_with_empty_options() -> None:
    """No availability is an answer, not an error."""
    repo = make_repo([stay(date(2026, 12, 1), date(2026, 12, 20))])
    result = await check_availability(
        repo,
        AvailabilityInput(
            check_in=date(2026, 12, 10), check_out=date(2026, 12, 12), guests=4
        ),
        today=TODAY,
    )
    assert result == AvailabilityOk(options=[])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("check_in", "check_out"),
    [
        (date(2026, 12, 12), date(2026, 12, 10)),
        (date(2026, 12, 10), date(2026, 12, 10)),
        (date(2026, 11, 1), date(2026, 11, 3)),
    ],
)
async def test_invalid_dates(check_in: date, check_out: date) -> None:
    """Reversed, zero-night and past stays are rejected."""
    result = await check_availability(
        make_repo(),
        AvailabilityInput(check_in=check_in, check_out=check_out, guests=2),
        today=TODAY,
    )
    assert result == AvailabilityError(reason="invalid_dates")


@pytest.mark.asyncio
async def test_too_many_guests() -> None:
    """A party larger than every room type gets a specific reason."""
    result = await check_availability(
        make_repo(),
        AvailabilityInput(
            check_in=date(2026, 12, 10), check_out=date(2026, 12, 12), guests=9
        ),
        today=TODAY,
    )
    assert result == AvailabilityError(reason="too_many_guests")


@pytest.mark.asyncio
@pytest.mark.parametrize("guests", [0, -1])
async def test_guests_must_be_at_least_one(guests: int) -> None:
    """Zero or negative party sizes are rejected with a speakable reason."""
    result = await check_availability(
        make_repo(),
        AvailabilityInput(
            check_in=date(2026, 12, 10), check_out=date(2026, 12, 12), guests=guests
        ),
        today=TODAY,
    )
    assert result == AvailabilityError(reason="invalid_guests")


@pytest.mark.asyncio
async def test_stay_longer_than_thirty_nights_is_rejected() -> None:
    """A runaway check_out from the model is rejected, not looped over."""
    result = await check_availability(
        make_repo(),
        AvailabilityInput(
            check_in=date(2026, 12, 1), check_out=date(2027, 1, 1), guests=2
        ),
        today=TODAY,
    )
    assert result == AvailabilityError(reason="invalid_dates")
