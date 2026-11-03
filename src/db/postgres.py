"""HotelRepository backed by Postgres (hosted Supabase), over asyncpg."""

from datetime import date

import asyncpg

from src.db.hotel import Rate, RoomType


class PostgresHotelRepository:
    """Read access to inventory, rates and stays in Postgres.

    Takes a pool in the app or a single connection in tests, which lets tests run
    inside a transaction that is rolled back.
    """

    def __init__(self, db: asyncpg.Pool | asyncpg.Connection) -> None:
        """Store the pool or connection to query."""
        self._db = db

    async def list_room_types(self) -> list[RoomType]:
        """Return every room type with its number of active rooms."""
        rows = await self._db.fetch(
            "select rt.name, rt.max_guests,"
            " count(r.id) filter (where r.is_active) as rooms"
            " from room_types rt left join rooms r on r.room_type_id = rt.id"
            " group by rt.id order by rt.max_guests, rt.name"
        )
        return [
            RoomType(name=row["name"], max_guests=row["max_guests"], rooms=row["rooms"])
            for row in rows
        ]

    async def count_booked(
        self, room_type: str, check_in: date, check_out: date
    ) -> int:
        """Return how many active rooms of this type are taken at any point in the stay.

        Both ranges treat check_out as exclusive, so a stay that leaves on the
        arrival day does not overlap. A room with several stays in the window
        counts once.
        """
        return await self._db.fetchval(
            "select count(distinct res.room_id) from reservations res"
            " join rooms r on r.id = res.room_id"
            " join room_types rt on rt.id = r.room_type_id"
            " where rt.name = $1 and r.is_active and res.status = 'confirmed'"
            " and res.check_in < $3 and $2 < res.check_out",
            room_type,
            check_in,
            check_out,
        )

    async def list_rates(self, room_type: str) -> list[Rate]:
        """Return every rate row for a room type, converted from cents to euros."""
        rows = await self._db.fetch(
            "select rt.name, r.valid_from, r.valid_to, r.price_per_night_cents"
            " from rates r join room_types rt on rt.id = r.room_type_id"
            " where rt.name = $1 order by r.valid_from",
            room_type,
        )
        return [
            Rate(
                room_type=row["name"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                price_per_night_eur=row["price_per_night_cents"] // 100,
            )
            for row in rows
        ]
