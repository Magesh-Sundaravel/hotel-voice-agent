"""Fake seed data for the local CLI. Fictional, per docs/data-model.md."""

from datetime import date

from src.db.hotel import InMemoryHotelRepository, Rate, RoomType, Stay

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


def seed_repository() -> InMemoryHotelRepository:
    """Build the seed hotel with a few overlapping stays to exercise conflicts."""
    return InMemoryHotelRepository(
        room_types=[
            RoomType(name=n, max_guests=g, rooms=r) for n, g, r, _, _ in _ROOMS
        ],
        rates=[
            Rate(
                room_type=row[0],
                valid_from=start,
                valid_to=end,
                price_per_night_eur=row[price_col],
            )
            for row in _ROOMS
            for start, end, price_col in _SEASONS
        ],
        stays=[
            Stay(
                room_type="Barberini Penthouse Suite",
                check_in=date(2026, 12, 24),
                check_out=date(2026, 12, 28),
            ),
            *[
                Stay(
                    room_type="Suite",
                    check_in=date(2026, 12, 30),
                    check_out=date(2027, 1, 3),
                )
                for _ in range(2)
            ],
        ],
    )
