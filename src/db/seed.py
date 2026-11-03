"""Fake seed data. Fictional, per docs/data-model.md.

The single source for the seed hotel: the in-memory repository (CLI, evals, tests)
and the Postgres seed loader (src/db/migrate.py) both read these lists.
"""

from datetime import date, timedelta

from src.db.bookings import InMemoryBookingRepository, NewBooking
from src.db.hotel import Rate, RoomType

# name, max_guests, rooms, low-season EUR/night, high-season EUR/night
_ROOMS = [
    ("Superior", 2, 10, 220, 320),
    ("Deluxe", 2, 8, 280, 390),
    ("Executive Deluxe Piazza View", 3, 5, 340, 460),
    ("Junior Suite", 3, 4, 420, 560),
    ("Suite", 4, 2, 650, 850),
    ("Barberini Penthouse Suite", 4, 1, 1400, 1900),
]

# Low season is Nov to Mar, high season is Apr to Oct.
# Each entry: start, end, index of the price column in _ROOMS.
_SEASONS = [
    (date(2026, 11, 1), date(2027, 3, 31), 3),
    (date(2027, 4, 1), date(2027, 10, 31), 4),
    (date(2027, 11, 1), date(2028, 3, 31), 3),
]

ROOM_TYPES = [RoomType(name=n, max_guests=g, rooms=r) for n, g, r, _, _ in _ROOMS]

RATES = [
    Rate(
        room_type=row[0],
        valid_from=start,
        valid_to=end,
        price_per_night_eur=row[price_col],
    )
    for row in _ROOMS
    for start, end, price_col in _SEASONS
]


def _total_cents(room_type: str, check_in: date, check_out: date) -> int:
    """Price a seed stay night by night from the seed rates."""
    total = 0
    night = check_in
    while night < check_out:
        rate = next(
            r
            for r in RATES
            if r.room_type == room_type and r.valid_from <= night <= r.valid_to
        )
        total += rate.price_per_night_eur * 100
        night += timedelta(days=1)
    return total


# Fake guests. Phones are in +1 202-555-0100..0199, a range reserved for fiction,
# so they can never reach a real person.
_GIULIA = ("Giulia", "Rossi", "+12025550101", "giulia.rossi@example.com", "it")
_JAMES = ("James", "Carter", "+12025550102", "james.carter@example.com", "en")
_MARCO = ("Marco", "Bianchi", "+12025550103", None, "it")


def _booking(
    reference: str,
    guest: tuple[str, str, str, str | None, str],
    room_type: str,
    check_in: date,
    check_out: date,
) -> tuple[str, NewBooking]:
    """A seed booking with a fixed reference, so evals can ask about it."""
    first_name, last_name, phone, email, language = guest
    return reference, NewBooking(
        idempotency_key=f"seed-{reference}",
        room_type=room_type,
        check_in=check_in,
        check_out=check_out,
        adults=2,
        total_cents=_total_cents(room_type, check_in, check_out),
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        language=language,  # type: ignore[arg-type]
    )


# Overlapping stays to exercise conflicts: the only Penthouse over Christmas, and
# both Suites over New Year.
BOOKINGS = [
    _booking(
        "482913",
        _GIULIA,
        "Barberini Penthouse Suite",
        date(2026, 12, 24),
        date(2026, 12, 28),
    ),
    _booking("615204", _JAMES, "Suite", date(2026, 12, 30), date(2027, 1, 3)),
    _booking("730158", _MARCO, "Suite", date(2026, 12, 30), date(2027, 1, 3)),
]


def seed_repository() -> InMemoryBookingRepository:
    """Build the in-memory seed hotel with its guests and bookings."""
    return InMemoryBookingRepository(
        room_types=list(ROOM_TYPES), rates=list(RATES), stays=[], bookings=BOOKINGS
    )
