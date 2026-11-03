"""A small in-memory hotel with one existing booking, for the booking tool tests."""

from datetime import date

from src.db.bookings import Booking, InMemoryBookingRepository, NewBooking
from src.db.hotel import Rate, RoomType

TODAY = date(2026, 11, 2)


async def hotel_with_booking() -> tuple[InMemoryBookingRepository, Booking]:
    """2 Superior (max 2, 100/night), 1 Suite (max 4, 300/night), and Ada's stay.

    Ada Testa has a Superior for 2 adults, 10 to 12 December 2026.
    """
    repo = InMemoryBookingRepository(
        room_types=[
            RoomType(name="Superior", max_guests=2, rooms=2),
            RoomType(name="Suite", max_guests=4, rooms=1),
        ],
        rates=[
            Rate(
                room_type=name,
                valid_from=date(2026, 11, 1),
                valid_to=date(2027, 3, 31),
                price_per_night_eur=price,
            )
            for name, price in [("Superior", 100), ("Suite", 300)]
        ],
        stays=[],
    )
    booking = await repo.create_booking(
        NewBooking(
            idempotency_key="k",
            room_type="Superior",
            check_in=date(2026, 12, 10),
            check_out=date(2026, 12, 12),
            adults=2,
            total_cents=20000,
            first_name="Ada",
            last_name="Testa",
            phone="+12025550199",
            email=None,
            language="it",
        )
    )
    assert isinstance(booking, Booking)
    return repo, booking
