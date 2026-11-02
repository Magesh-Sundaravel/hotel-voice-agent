"""Tests for the get_rates tool (seam A)."""

from datetime import date

import pytest

from src.db.hotel import InMemoryHotelRepository, Rate, RoomType
from src.tools.get_rates import GetRatesError, GetRatesInput, GetRatesOk, get_rates

TODAY = date(2026, 11, 2)


def make_repo() -> InMemoryHotelRepository:
    """Superior is 200 EUR in low season (Nov-Mar) and 300 EUR in high (Apr-Oct)."""
    return InMemoryHotelRepository(
        room_types=[RoomType(name="Superior", max_guests=2, rooms=2)],
        rates=[
            Rate(
                room_type="Superior",
                valid_from=date(2026, 11, 1),
                valid_to=date(2027, 3, 31),
                price_per_night_eur=200,
            ),
            Rate(
                room_type="Superior",
                valid_from=date(2027, 4, 1),
                valid_to=date(2027, 10, 31),
                price_per_night_eur=300,
            ),
        ],
        stays=[],
    )


@pytest.mark.asyncio
async def test_prices_a_stay_within_one_season() -> None:
    """Two low-season nights cost 2 x 200."""
    result = await get_rates(
        make_repo(),
        GetRatesInput(
            room_type="Superior",
            check_in=date(2026, 12, 10),
            check_out=date(2026, 12, 12),
        ),
        today=TODAY,
    )
    assert result == GetRatesOk(
        room_type="Superior", nights=2, total_eur=400, per_night_eur=[200, 200]
    )


@pytest.mark.asyncio
async def test_prices_across_the_season_boundary_night_by_night() -> None:
    """Nights of 30 and 31 March are low, 1 April is high."""
    result = await get_rates(
        make_repo(),
        GetRatesInput(
            room_type="Superior", check_in=date(2027, 3, 30), check_out=date(2027, 4, 2)
        ),
        today=TODAY,
    )
    assert result == GetRatesOk(
        room_type="Superior", nights=3, total_eur=700, per_night_eur=[200, 200, 300]
    )


@pytest.mark.asyncio
async def test_unknown_room_type() -> None:
    """A room type the hotel does not have is reported by name."""
    result = await get_rates(
        make_repo(),
        GetRatesInput(
            room_type="Igloo", check_in=date(2026, 12, 10), check_out=date(2026, 12, 12)
        ),
        today=TODAY,
    )
    assert result == GetRatesError(
        reason="unknown_room_type", valid_room_types=["Superior"]
    )


@pytest.mark.asyncio
async def test_invalid_dates() -> None:
    """A zero-night stay is rejected."""
    result = await get_rates(
        make_repo(),
        GetRatesInput(
            room_type="Superior",
            check_in=date(2026, 12, 10),
            check_out=date(2026, 12, 10),
        ),
        today=TODAY,
    )
    assert result == GetRatesError(reason="invalid_dates")


@pytest.mark.asyncio
async def test_no_rate_for_dates() -> None:
    """Dates beyond the published rates cannot be priced."""
    result = await get_rates(
        make_repo(),
        GetRatesInput(
            room_type="Superior",
            check_in=date(2028, 1, 10),
            check_out=date(2028, 1, 12),
        ),
        today=TODAY,
    )
    assert result == GetRatesError(reason="no_rate_for_dates")


@pytest.mark.asyncio
async def test_room_type_match_ignores_case() -> None:
    """The model may say "superior"; the result uses the hotel's own name."""
    result = await get_rates(
        make_repo(),
        GetRatesInput(
            room_type="superior",
            check_in=date(2026, 12, 10),
            check_out=date(2026, 12, 11),
        ),
        today=TODAY,
    )
    assert result == GetRatesOk(
        room_type="Superior", nights=1, total_eur=200, per_night_eur=[200]
    )


@pytest.mark.asyncio
async def test_stay_longer_than_thirty_nights_is_rejected() -> None:
    """A runaway check_out from the model is rejected, not looped over."""
    result = await get_rates(
        make_repo(),
        GetRatesInput(
            room_type="Superior",
            check_in=date(2026, 12, 1),
            check_out=date(9999, 12, 31),
        ),
        today=TODAY,
    )
    assert result == GetRatesError(reason="invalid_dates")
