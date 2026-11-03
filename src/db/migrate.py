"""Apply db/migrations/*.sql to DATABASE_URL, and optionally load the seed hotel.

Usage:
    uv run python -m src.db.migrate          # apply pending migrations
    uv run python -m src.db.migrate --seed   # also load the fake seed hotel

Applied files are recorded in schema_migrations, so re-running is safe.
"""

import argparse
import asyncio
from datetime import date, timedelta
from pathlib import Path

import asyncpg

from src.config import Settings
from src.db.hotel import Rate
from src.db.seed import RATES, ROOM_TYPES, STAYS

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

# Fake guests for the seed stays. Phones are in +1 202-555-0100..0199, a range
# reserved for fiction, so they can never reach a real person.
_SEED_GUESTS = [
    ("Giulia", "Rossi", "+12025550101", "giulia.rossi@example.com", "it"),
    ("James", "Carter", "+12025550102", "james.carter@example.com", "en"),
    ("Marco", "Bianchi", "+12025550103", None, "it"),
]


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


def _stay_total_cents(rates: list[Rate], check_in: date, check_out: date) -> int:
    """Price a seed stay night by night from the seed rates."""
    total = 0
    night = check_in
    while night < check_out:
        rate = next(r for r in rates if r.valid_from <= night <= r.valid_to)
        total += rate.price_per_night_eur * 100
        night += timedelta(days=1)
    return total


async def load_seed(conn: asyncpg.Connection) -> bool:
    """Insert the seed hotel in one transaction, unless room types already exist.

    Each room type gets its own floor (Superior is 101 to 110, Deluxe 201 to 208,
    and so on). Each seed stay goes to the lowest-numbered room of its type that
    no earlier seed stay uses, and to the next fake guest in turn.

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

        guest_ids = [
            await conn.fetchval(
                "insert into guests (first_name, last_name, phone, email, language)"
                " values ($1, $2, $3, $4, $5) returning id",
                *guest,
            )
            for guest in _SEED_GUESTS
        ]

        for i, stay in enumerate(STAYS):
            type_rates = [r for r in RATES if r.room_type == stay.room_type]
            await conn.execute(
                "insert into reservations (reference, guest_id, room_id, check_in,"
                " check_out, adults, status, total_cents, idempotency_key)"
                " values ($1, $2, $3, $4, $5, 2, 'confirmed', $6, $7)",
                f"SEED{i + 1:02d}",
                guest_ids[i % len(guest_ids)],
                rooms_by_type[stay.room_type].pop(0),
                stay.check_in,
                stay.check_out,
                _stay_total_cents(type_rates, stay.check_in, stay.check_out),
                f"seed-{i + 1}",
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
