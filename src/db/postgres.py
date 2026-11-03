"""HotelRepository and BookingRepository backed by Postgres (hosted Supabase), over asyncpg."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from uuid import UUID

import asyncpg

from src.db.bookings import (
    Booking,
    BookingChange,
    BookingConflict,
    GuestSummary,
    NewBooking,
    new_reference,
    same_name,
)
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


@asynccontextmanager
async def _transaction(
    db: asyncpg.Pool | asyncpg.Connection,
) -> AsyncIterator[asyncpg.Connection]:
    """Run a block in a transaction (a savepoint if one is already open)."""
    if isinstance(db, asyncpg.Pool):
        async with db.acquire() as conn, conn.transaction():
            yield conn
    else:
        async with db.transaction():
            yield db


# Tries per write when a concurrent booking takes the chosen room first.
_WRITE_ATTEMPTS = 3


async def _lowest_free_room(
    conn: asyncpg.Connection,
    room_type: str,
    check_in: date,
    check_out: date,
    exclude_reservation: str | None = None,
    prefer_room: UUID | None = None,
) -> UUID | None:
    """Return the lowest-numbered active room of the type free for the whole stay.

    exclude_reservation is a reference whose own stay is ignored, and prefer_room
    is picked first when free (both for modify, so a guest keeps their room).
    """
    return await conn.fetchval(
        "select r.id from rooms r join room_types rt on rt.id = r.room_type_id"
        " where rt.name = $1 and r.is_active and not exists ("
        "  select 1 from reservations res where res.room_id = r.id"
        "  and res.status = 'confirmed' and res.check_in < $3 and $2 < res.check_out"
        "  and res.reference is distinct from $4)"
        " order by r.id is not distinct from $5 desc, r.number limit 1",
        room_type,
        check_in,
        check_out,
        exclude_reservation,
        prefer_room,
    )


_BOOKING_SELECT = (
    "select res.reference, res.status, g.first_name, rt.name as room_type,"
    " res.check_in, res.check_out, res.adults, res.total_cents, res.cancelled_at"
    " from reservations res"
    " join guests g on g.id = res.guest_id"
    " join rooms r on r.id = res.room_id"
    " join room_types rt on rt.id = r.room_type_id"
)


class PostgresBookingRepository:
    """Guests and reservations in Postgres. Every write is one transaction."""

    def __init__(self, db: asyncpg.Pool | asyncpg.Connection) -> None:
        """Store the pool or connection to query."""
        self._db = db

    async def create_booking(self, new: NewBooking) -> Booking | BookingConflict:
        """Book the lowest-numbered free room of the type for the whole stay.

        If a concurrent booking takes the chosen room first, the exclusion
        constraint rejects the insert and the next free room is tried.
        """
        for _ in range(_WRITE_ATTEMPTS):
            try:
                return await self._create_once(new)
            except asyncpg.ExclusionViolationError:
                continue
        return BookingConflict(reason="no_availability")

    async def _create_once(self, new: NewBooking) -> Booking | BookingConflict:
        """One attempt at create_booking, in its own transaction."""
        async with _transaction(self._db) as conn:
            existing = await conn.fetchval(
                "select reference from reservations where idempotency_key = $1",
                new.idempotency_key,
            )
            if existing:
                return await self._get(conn, existing)
            guest = await conn.fetchrow(
                "select id, first_name, last_name from guests where phone = $1"
                " for update",
                new.phone,
            )
            if guest and not same_name(
                guest["first_name"], guest["last_name"], new.first_name, new.last_name
            ):
                return BookingConflict(reason="phone_belongs_to_other_guest")
            if guest is None:
                guest_id = await conn.fetchval(
                    "insert into guests (first_name, last_name, phone, email, language)"
                    " values ($1, $2, $3, $4, $5) returning id",
                    new.first_name,
                    new.last_name,
                    new.phone,
                    new.email,
                    new.language,
                )
            else:
                guest_id = guest["id"]
                if new.email:
                    await conn.execute(
                        "update guests set email = $2 where id = $1",
                        guest_id,
                        new.email,
                    )
            room_id = await _lowest_free_room(
                conn, new.room_type, new.check_in, new.check_out
            )
            if room_id is None:
                return BookingConflict(reason="no_availability")
            reference = new_reference()
            await conn.execute(
                "insert into reservations (reference, guest_id, room_id, check_in,"
                " check_out, adults, status, total_cents, idempotency_key)"
                " values ($1, $2, $3, $4, $5, $6, 'confirmed', $7, $8)",
                reference,
                guest_id,
                room_id,
                new.check_in,
                new.check_out,
                new.adults,
                new.total_cents,
                new.idempotency_key,
            )
            return await self._get(conn, reference)

    async def find_guest(self, phone: str) -> GuestSummary | None:
        """Find the guest with this phone (E.164)."""
        row = await self._db.fetchrow(
            "select first_name, last_name, email is not null as has_email"
            " from guests where phone = $1",
            phone,
        )
        return GuestSummary(**dict(row)) if row else None

    async def get_booking(self, reference: str, last_name: str) -> Booking | None:
        """Find a booking by reference and the guest's last name, any case."""
        row = await self._db.fetchrow(
            _BOOKING_SELECT
            + " where res.reference = $1 and lower(g.last_name) = lower(trim($2))",
            reference,
            last_name,
        )
        return Booking(**dict(row)) if row else None

    async def modify_booking(
        self, reference: str, last_name: str, change: BookingChange
    ) -> Booking | BookingConflict | None:
        """Apply new values to a confirmed booking, keeping its reference.

        The guest keeps their room when it is still free and of the new type;
        otherwise they move to the lowest-numbered free room.
        """
        for _ in range(_WRITE_ATTEMPTS):
            try:
                return await self._modify_once(reference, last_name, change)
            except asyncpg.ExclusionViolationError:
                continue
        return BookingConflict(reason="no_availability")

    async def _modify_once(
        self, reference: str, last_name: str, change: BookingChange
    ) -> Booking | BookingConflict | None:
        """One attempt at modify_booking, in its own transaction."""
        async with _transaction(self._db) as conn:
            current = await conn.fetchrow(
                "select res.room_id, res.status from reservations res"
                " join guests g on g.id = res.guest_id"
                " where res.reference = $1 and lower(g.last_name) = lower(trim($2))"
                " for update of res",
                reference,
                last_name,
            )
            if current is None:
                return None
            if current["status"] != "confirmed":
                return await self._get(conn, reference)
            room_id = await _lowest_free_room(
                conn,
                change.room_type,
                change.check_in,
                change.check_out,
                exclude_reservation=reference,
                prefer_room=current["room_id"],
            )
            if room_id is None:
                return BookingConflict(reason="no_availability")
            await conn.execute(
                "update reservations set room_id = $2, check_in = $3, check_out = $4,"
                " adults = $5, total_cents = $6 where reference = $1",
                reference,
                room_id,
                change.check_in,
                change.check_out,
                change.adults,
                change.total_cents,
            )
            return await self._get(conn, reference)

    async def cancel_booking(
        self, reference: str, last_name: str, now: datetime
    ) -> Booking | None:
        """Cancel a booking at `now`; an already cancelled one is returned unchanged."""
        async with _transaction(self._db) as conn:
            await conn.execute(
                "update reservations res set status = 'cancelled', cancelled_at = $3"
                " from guests g where g.id = res.guest_id and res.reference = $1"
                " and lower(g.last_name) = lower(trim($2)) and res.status = 'confirmed'",
                reference,
                last_name,
                now,
            )
            row = await conn.fetchrow(
                _BOOKING_SELECT
                + " where res.reference = $1 and lower(g.last_name) = lower(trim($2))",
                reference,
                last_name,
            )
            return Booking(**dict(row)) if row else None

    @staticmethod
    async def _get(conn: asyncpg.Connection, reference: str) -> Booking:
        """Read a booking known to exist."""
        row = await conn.fetchrow(
            _BOOKING_SELECT + " where res.reference = $1", reference
        )
        return Booking(**dict(row))
