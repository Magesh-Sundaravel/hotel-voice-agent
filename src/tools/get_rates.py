"""get_rates tool: price a stay for one room type."""

from datetime import date, timedelta

from pydantic import BaseModel, Field

from src.db.hotel import HotelRepository
from src.tools import CHECK_IN_DESCRIPTION, CHECK_OUT_DESCRIPTION, MAX_STAY_NIGHTS


class GetRatesInput(BaseModel):
    """Arguments the agent passes. check_out is exclusive."""

    room_type: str = Field(
        description=(
            "Name of the room type, for example 'Junior Suite', copied from a "
            "check_availability result. Upper or lower case does not matter."
        )
    )
    check_in: date = Field(description=CHECK_IN_DESCRIPTION)
    check_out: date = Field(description=CHECK_OUT_DESCRIPTION)


class GetRatesOk(BaseModel):
    """Successful price for the whole stay."""

    ok: bool = True
    room_type: str
    nights: int
    total_eur: int
    per_night_eur: list[int]


class GetRatesError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str
    valid_room_types: list[str] = []


async def get_rates(
    repo: HotelRepository, inp: GetRatesInput, today: date | None = None
) -> GetRatesOk | GetRatesError:
    """Price a stay night by night, so season changes are handled.

    Args:
        repo: Hotel inventory access.
        inp: Room type and dates.
        today: Override for the current date (tests).

    Returns:
        The price, or an error with a spoken-friendly reason.
    """
    nights = (inp.check_out - inp.check_in).days
    if not 0 < nights <= MAX_STAY_NIGHTS or inp.check_in < (today or date.today()):
        return GetRatesError(reason="invalid_dates")
    names = {rt.name.lower(): rt.name for rt in await repo.list_room_types()}
    room_type = names.get(inp.room_type.strip().lower())
    if room_type is None:
        return GetRatesError(
            reason="unknown_room_type", valid_room_types=sorted(names.values())
        )
    rates = await repo.list_rates(room_type)
    per_night: list[int] = []
    night = inp.check_in
    while night < inp.check_out:
        match = next((r for r in rates if r.valid_from <= night <= r.valid_to), None)
        if match is None:
            return GetRatesError(reason="no_rate_for_dates")
        per_night.append(match.price_per_night_eur)
        night += timedelta(days=1)
    return GetRatesOk(
        room_type=room_type,
        nights=len(per_night),
        total_eur=sum(per_night),
        per_night_eur=per_night,
    )
