"""Integration tests for PostgresHotelRepository against the hosted database.

Each test runs inside a transaction that is rolled back, inserts only its own rows
and never migrates, so the live database is left exactly as it was. Skipped when
DATABASE_URL is not set. Needs a database prepared with
`uv run python -m src.db.migrate --seed`: the seed-match tests read the seed. Room type names are prefixed so they never clash with
the seed.
"""

from collections.abc import AsyncIterator
from datetime import date
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from src.config import Settings
from src.db.hotel import Rate, RoomType
from src.db.postgres import PostgresHotelRepository
from src.db.seed import RATES, ROOM_TYPES

DATABASE_URL = Settings().database_url

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    """A connection inside a transaction that is always rolled back."""
    connection = await asyncpg.connect(DATABASE_URL)
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


async def add_room_type(
    conn: asyncpg.Connection, name: str, max_guests: int = 2
) -> UUID:
    """Insert a room type and return its id."""
    return await conn.fetchval(
        "insert into room_types (name, max_guests) values ($1, $2) returning id",
        f"test {name}",
        max_guests,
    )


async def add_room(
    conn: asyncpg.Connection, room_type_id: UUID, number: str, active: bool = True
) -> UUID:
    """Insert a room of a type and return its id."""
    return await conn.fetchval(
        "insert into rooms (number, floor, room_type_id, is_active)"
        " values ($1, 9, $2, $3) returning id",
        f"T{number}",
        room_type_id,
        active,
    )


async def add_stay(
    conn: asyncpg.Connection,
    room_id: UUID,
    check_in: date,
    check_out: date,
    status: str = "confirmed",
) -> None:
    """Insert a reservation for a new fake guest on a room."""
    key = uuid4().hex
    guest_id = await conn.fetchval(
        "insert into guests (first_name, last_name, phone, language)"
        " values ('Test', 'Guest', $1, 'en') returning id",
        f"+1555{uuid4().int % 10**7:07d}",
    )
    await conn.execute(
        "insert into reservations (reference, guest_id, room_id, check_in, check_out,"
        " adults, status, total_cents, idempotency_key)"
        " values ($1, $2, $3, $4, $5, 1, $6, 0, $7)",
        f"T{key[:8]}",
        guest_id,
        room_id,
        check_in,
        check_out,
        status,
        key,
    )


@pytest.mark.asyncio
async def test_rates_are_returned_in_euros(conn: asyncpg.Connection) -> None:
    """Rates stored in cents come back as whole euros per night."""
    rt = await add_room_type(conn, "Rates")
    await conn.execute(
        "insert into rates (room_type_id, valid_from, valid_to, price_per_night_cents)"
        " values ($1, '2026-11-01', '2027-03-31', 22000)",
        rt,
    )

    rates = await PostgresHotelRepository(conn).list_rates("test Rates")

    assert rates == [
        Rate(
            room_type="test Rates",
            valid_from=date(2026, 11, 1),
            valid_to=date(2027, 3, 31),
            price_per_night_eur=220,
        )
    ]


@pytest.mark.asyncio
async def test_room_count_leaves_out_inactive_rooms(conn: asyncpg.Connection) -> None:
    """Only active rooms count towards a room type's total."""
    rt = await add_room_type(conn, "Count", max_guests=3)
    await add_room(conn, rt, "1")
    await add_room(conn, rt, "2")
    await add_room(conn, rt, "3", active=False)

    room_types = await PostgresHotelRepository(conn).list_room_types()

    assert RoomType(name="test Count", max_guests=3, rooms=2) in room_types


@pytest.mark.asyncio
async def test_overlapping_stays_are_booked_and_checkout_day_is_free(
    conn: asyncpg.Connection,
) -> None:
    """A stay overlapping the dates counts; one leaving on arrival day does not."""
    rt = await add_room_type(conn, "Overlap")
    room_a = await add_room(conn, rt, "A")
    room_b = await add_room(conn, rt, "B")
    await add_stay(conn, room_a, date(2026, 12, 8), date(2026, 12, 11))
    await add_stay(conn, room_b, date(2026, 12, 5), date(2026, 12, 10))

    booked = await PostgresHotelRepository(conn).count_booked(
        "test Overlap", date(2026, 12, 10), date(2026, 12, 12)
    )

    assert booked == 1


@pytest.mark.asyncio
async def test_cancelled_stays_are_not_booked(conn: asyncpg.Connection) -> None:
    """A cancelled reservation frees its room."""
    rt = await add_room_type(conn, "Cancelled")
    room = await add_room(conn, rt, "C")
    await add_stay(
        conn, room, date(2026, 12, 10), date(2026, 12, 12), status="cancelled"
    )

    booked = await PostgresHotelRepository(conn).count_booked(
        "test Cancelled", date(2026, 12, 10), date(2026, 12, 12)
    )

    assert booked == 0


@pytest.mark.asyncio
async def test_database_rejects_a_double_booking(conn: asyncpg.Connection) -> None:
    """Two confirmed overlapping stays on one room violate the exclusion constraint."""
    rt = await add_room_type(conn, "Double")
    room = await add_room(conn, rt, "D")
    await add_stay(conn, room, date(2026, 12, 10), date(2026, 12, 12))

    with pytest.raises(asyncpg.ExclusionViolationError):
        await add_stay(conn, room, date(2026, 12, 11), date(2026, 12, 13))


@pytest.mark.asyncio
async def test_a_room_with_two_short_stays_counts_once(
    conn: asyncpg.Connection,
) -> None:
    """Two back-to-back stays on one room inside the dates take one room, not two."""
    rt = await add_room_type(conn, "Twice")
    room = await add_room(conn, rt, "W")
    await add_room(conn, rt, "X")
    await add_stay(conn, room, date(2026, 12, 1), date(2026, 12, 3))
    await add_stay(conn, room, date(2026, 12, 5), date(2026, 12, 8))

    booked = await PostgresHotelRepository(conn).count_booked(
        "test Twice", date(2026, 12, 1), date(2026, 12, 10)
    )

    assert booked == 1


@pytest.mark.asyncio
async def test_stays_on_inactive_rooms_are_not_booked(
    conn: asyncpg.Connection,
) -> None:
    """An inactive room is out of capacity, so its stays don't take capacity either."""
    rt = await add_room_type(conn, "Retired")
    room = await add_room(conn, rt, "R", active=False)
    await add_stay(conn, room, date(2026, 12, 10), date(2026, 12, 12))

    booked = await PostgresHotelRepository(conn).count_booked(
        "test Retired", date(2026, 12, 10), date(2026, 12, 12)
    )

    assert booked == 0


@pytest.mark.asyncio
async def test_database_rejects_a_rate_that_is_not_whole_euros(
    conn: asyncpg.Connection,
) -> None:
    """Rates are quoted in whole euros, so the database refuses stray cents."""
    rt = await add_room_type(conn, "Cents")

    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "insert into rates (room_type_id, valid_from, valid_to,"
            " price_per_night_cents) values ($1, '2026-11-01', '2027-03-31', 22050)",
            rt,
        )


# --- Seam B: the seeded database matches the in-memory seed ------------------


@pytest.mark.asyncio
async def test_seeded_room_types_match_the_in_memory_seed(
    conn: asyncpg.Connection,
) -> None:
    """After `migrate --seed`, the database has exactly the seed's room types."""
    room_types = await PostgresHotelRepository(conn).list_room_types()

    assert sorted(room_types, key=lambda rt: rt.name) == sorted(
        ROOM_TYPES, key=lambda rt: rt.name
    )


@pytest.mark.asyncio
async def test_seeded_rates_match_the_in_memory_seed(conn: asyncpg.Connection) -> None:
    """After `migrate --seed`, every room type has exactly the seed's rates."""
    repo = PostgresHotelRepository(conn)

    for rt in ROOM_TYPES:
        expected = [r for r in RATES if r.room_type == rt.name]
        assert await repo.list_rates(rt.name) == expected
