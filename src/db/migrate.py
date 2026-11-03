"""Apply db/migrations/*.sql to DATABASE_URL, and optionally load the seed hotel.

Usage:
    uv run python -m src.db.migrate          # apply pending migrations
    uv run python -m src.db.migrate --seed   # also load the fake seed hotel

Applied files are recorded in schema_migrations, so re-running is safe.
"""

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

import asyncpg

from src.config import Settings
from src.db.seed import BOOKINGS, RATES, ROOM_TYPES

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


async def apply_migrations(conn: asyncpg.Connection) -> list[str]:
    """Apply every migration file not yet recorded, each in its own transaction.

    Args:
        conn: Connection to the target database.

    Returns:
        The file names applied by this run.
    """
    await conn.execute(
        "create table if not exists schema_migrations ("
        " filename text primary key, applied_at timestamptz not null default now())"
    )
    await conn.execute("alter table schema_migrations enable row level security")
    done = {
        r["filename"]
        for r in await conn.fetch("select filename from schema_migrations")
    }
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        async with conn.transaction():
            await conn.execute(path.read_text())
            await conn.execute(
                "insert into schema_migrations (filename) values ($1)", path.name
            )
        applied.append(path.name)
    return applied


async def load_seed(conn: asyncpg.Connection) -> bool:
    """Insert the seed hotel in one transaction, unless room types already exist.

    Each room type gets its own floor (Superior is 101 to 110, Deluxe 201 to 208,
    and so on). Each seed stay goes to the lowest-numbered room of its type that
    no earlier seed booking uses, under its fixed reference.

    Args:
        conn: Connection to a migrated database.

    Returns:
        True if the seed was loaded, False if the database already had room types.
    """
    if await conn.fetchval("select exists (select 1 from room_types)"):
        return False
    async with conn.transaction():
        rooms_by_type: dict[str, list[str]] = {}
        for floor, rt in enumerate(ROOM_TYPES, start=1):
            rt_id = await conn.fetchval(
                "insert into room_types (name, max_guests) values ($1, $2) returning id",
                rt.name,
                rt.max_guests,
            )
            for rate in (r for r in RATES if r.room_type == rt.name):
                await conn.execute(
                    "insert into rates (room_type_id, valid_from, valid_to,"
                    " price_per_night_cents) values ($1, $2, $3, $4)",
                    rt_id,
                    rate.valid_from,
                    rate.valid_to,
                    rate.price_per_night_eur * 100,
                )
            room_ids = []
            for n in range(1, rt.rooms + 1):
                room_ids.append(
                    await conn.fetchval(
                        "insert into rooms (number, floor, room_type_id)"
                        " values ($1, $2, $3) returning id",
                        f"{floor}{n:02d}",
                        floor,
                        rt_id,
                    )
                )
            rooms_by_type[rt.name] = room_ids

        guest_ids: dict[str, UUID] = {}
        for reference, new in BOOKINGS:
            if new.phone not in guest_ids:
                guest_ids[new.phone] = await conn.fetchval(
                    "insert into guests (first_name, last_name, phone, email, language)"
                    " values ($1, $2, $3, $4, $5) returning id",
                    new.first_name,
                    new.last_name,
                    new.phone,
                    new.email,
                    new.language,
                )
            await conn.execute(
                "insert into reservations (reference, guest_id, room_id, check_in,"
                " check_out, adults, status, total_cents, idempotency_key)"
                " values ($1, $2, $3, $4, $5, $6, 'confirmed', $7, $8)",
                reference,
                guest_ids[new.phone],
                rooms_by_type[new.room_type].pop(0),
                new.check_in,
                new.check_out,
                new.adults,
                new.total_cents,
                new.idempotency_key,
            )
    return True


async def main(seed: bool) -> None:
    """Connect to DATABASE_URL, migrate, and optionally seed.

    Args:
        seed: Whether to load the seed hotel after migrating.
    """
    url = Settings().database_url
    if not url:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")
    conn = await asyncpg.connect(url)
    try:
        applied = await apply_migrations(conn)
        print(f"Applied: {', '.join(applied) or 'nothing new'}")
        if seed:
            loaded = await load_seed(conn)
            print("Seed loaded" if loaded else "Seed skipped: room types already exist")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", action="store_true", help="load the fake seed hotel")
    asyncio.run(main(parser.parse_args().seed))
