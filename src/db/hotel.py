"""Hotel inventory access. The only place room and rate data is read."""

from datetime import date
from typing import Protocol

from pydantic import BaseModel


class RoomType(BaseModel):
    """A kind of room and how many of it the hotel has."""

    name: str
    max_guests: int
    rooms: int


class Rate(BaseModel):
    """Nightly price for a room type over an inclusive date range."""

    room_type: str
    valid_from: date
    valid_to: date
    price_per_night_eur: int


class Stay(BaseModel):
    """An existing confirmed stay. check_out is exclusive."""

    room_type: str
    check_in: date
    check_out: date


class HotelRepository(Protocol):
    """Read access to inventory, rates and existing stays."""

    async def list_room_types(self) -> list[RoomType]:
        """Return every room type."""
        ...

    async def count_booked(
        self, room_type: str, check_in: date, check_out: date
    ) -> int:
        """Return how many rooms of a type are taken at any point in the stay."""
        ...

    async def list_rates(self, room_type: str) -> list[Rate]:
        """Return every rate row for a room type."""
        ...


class InMemoryHotelRepository:
    """HotelRepository backed by lists, for tests and the local CLI."""

    def __init__(
        self, room_types: list[RoomType], rates: list[Rate], stays: list[Stay]
    ) -> None:
        """Store the inventory, rates and existing stays."""
        self._room_types = room_types
        self._rates = rates
        self._stays = stays

    async def list_room_types(self) -> list[RoomType]:
        """Return every room type."""
        return list(self._room_types)

    async def count_booked(
        self, room_type: str, check_in: date, check_out: date
    ) -> int:
        """Return how many stays of this type overlap the given dates."""
        return sum(
            1
            for s in self._stays
            if s.room_type == room_type
            and s.check_in < check_out
            and check_in < s.check_out
        )

    async def list_rates(self, room_type: str) -> list[Rate]:
        """Return every rate row for a room type."""
        return [r for r in self._rates if r.room_type == room_type]
