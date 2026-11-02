"""check_availability tool: which room types are free for a stay."""

from datetime import date

from pydantic import BaseModel, Field

from src.db.hotel import HotelRepository
from src.tools import CHECK_IN_DESCRIPTION, CHECK_OUT_DESCRIPTION, MAX_STAY_NIGHTS


class AvailabilityInput(BaseModel):
    """Arguments the agent passes. check_out is exclusive."""

    check_in: date = Field(description=CHECK_IN_DESCRIPTION)
    check_out: date = Field(description=CHECK_OUT_DESCRIPTION)
    guests: int = Field(
        description="Total number of people who will stay, children included. At least 1."
    )


class RoomOption(BaseModel):
    """A room type with at least one free room."""

    room_type: str
    rooms_free: int


class AvailabilityOk(BaseModel):
    """Successful result. Empty options means fully booked."""

    ok: bool = True
    options: list[RoomOption]


class AvailabilityError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str


async def check_availability(
    repo: HotelRepository, inp: AvailabilityInput, today: date | None = None
) -> AvailabilityOk | AvailabilityError:
    """List room types with a free room for the whole stay that fit the party.

    Args:
        repo: Hotel inventory access.
        inp: Dates and party size.
        today: Override for the current date (tests).

    Returns:
        The free options, or an error with a spoken-friendly reason.
    """
    nights = (inp.check_out - inp.check_in).days
    if not 0 < nights <= MAX_STAY_NIGHTS or inp.check_in < (today or date.today()):
        return AvailabilityError(reason="invalid_dates")
    if inp.guests < 1:
        return AvailabilityError(reason="invalid_guests")
    room_types = await repo.list_room_types()
    if all(rt.max_guests < inp.guests for rt in room_types):
        return AvailabilityError(reason="too_many_guests")
    options: list[RoomOption] = []
    for room_type in room_types:
        if room_type.max_guests < inp.guests:
            continue
        booked = await repo.count_booked(room_type.name, inp.check_in, inp.check_out)
        free = room_type.rooms - booked
        if free > 0:
            options.append(RoomOption(room_type=room_type.name, rooms_free=free))
    return AvailabilityOk(options=options)
