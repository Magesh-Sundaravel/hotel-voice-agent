"""Contract tests for BookingRepository, run against every implementation.

The same tests run on the in-memory repository (CLI, evals, tool tests) and on the
Postgres one, so the fake cannot drift from the real database. The Postgres run
uses a transaction that is rolled back, and is skipped when DATABASE_URL is not set.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

import asyncpg
import pytest
import pytest_asyncio

from src.config import Settings
from src.db.bookings import (
    Booking,
    BookingChange,
    BookingConflict,
    BookingRepository,
    GuestSummary,
    InMemoryBookingRepository,
    NewBooking,
)
from src.db.hotel import HotelRepository, Rate, RoomType
from src.db.postgres import PostgresBookingRepository, PostgresHotelRepository

DATABASE_URL = Settings().database_url

# The test hotel: two Standard rooms (max 2) and one Big room (max 4).
STD = "test Std"
BIG = "test Big"


@dataclass
class Repos:
    """Both views of one test hotel."""

    hotel: HotelRepository
    bookings: BookingRepository


async def _postgres_repos(conn: asyncpg.Connection) -> Repos:
    """Insert the test hotel inside the open transaction."""
    for name, max_guests, rooms in [(STD, 2, 2), (BIG, 4, 1)]:
        rt = await conn.fetchval(
            "insert into room_types (name, max_guests) values ($1, $2) returning id",
            name,
            max_guests,
        )
        for n in range(1, rooms + 1):
            await conn.execute(
                "insert into rooms (number, floor, room_type_id) values ($1, 9, $2)",
                f"T{name[-3:]}{n}",
                rt,
            )
    return Repos(PostgresHotelRepository(conn), PostgresBookingRepository(conn))


def _memory_repos() -> Repos:
    """The same test hotel in memory."""
    repo = InMemoryBookingRepository(
        room_types=[
            RoomType(name=STD, max_guests=2, rooms=2),
            RoomType(name=BIG, max_guests=4, rooms=1),
        ],
        rates=[
            Rate(
                room_type=STD,
                valid_from=date(2026, 1, 1),
                valid_to=date(2028, 12, 31),
                price_per_night_eur=100,
            )
        ],
        stays=[],
    )
    return Repos(repo, repo)


@pytest_asyncio.fixture(params=["memory", "postgres"])
async def repos(request: pytest.FixtureRequest) -> AsyncIterator[Repos]:
    """Yield the test hotel from each implementation."""
    if request.param == "memory":
        yield _memory_repos()
        return
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        yield await _postgres_repos(conn)
    finally:
        await tx.rollback()
        await conn.close()


def new_booking(**overrides: object) -> NewBooking:
    """A valid booking request; override any field."""
    fields: dict[str, object] = {
        "idempotency_key": "call-1|std|2026-12-10|2026-12-12|+12025550199",
        "room_type": STD,
        "check_in": date(2026, 12, 10),
        "check_out": date(2026, 12, 12),
        "adults": 2,
        "total_cents": 20000,
        "first_name": "Ada",
        "last_name": "Testa",
        "phone": "+12025550199",
        "email": None,
        "language": "it",
    }
    fields.update(overrides)
    return NewBooking.model_validate(fields)


@pytest.mark.asyncio
async def test_a_created_booking_can_be_read_back(repos: Repos) -> None:
    """Create returns a 6-digit reference that get_booking finds, any name case."""
    created = await repos.bookings.create_booking(new_booking())

    assert isinstance(created, Booking)
    assert len(created.reference) == 6 and created.reference.isdigit()
    found = await repos.bookings.get_booking(created.reference, "TESTA")
    assert found == created
    assert found.status == "confirmed"
    assert (found.first_name, found.room_type, found.adults, found.total_cents) == (
        "Ada",
        STD,
        2,
        20000,
    )


@pytest.mark.asyncio
async def test_a_wrong_last_name_finds_nothing(repos: Repos) -> None:
    """The reference alone is not enough to read a booking."""
    created = await repos.bookings.create_booking(new_booking())

    assert await repos.bookings.get_booking(created.reference, "Rossi") is None


@pytest.mark.asyncio
async def test_the_same_idempotency_key_returns_the_same_booking(repos: Repos) -> None:
    """A retried tool call books nothing new."""
    first = await repos.bookings.create_booking(new_booking())
    again = await repos.bookings.create_booking(new_booking())

    assert again == first
    assert (
        await repos.hotel.count_booked(STD, date(2026, 12, 10), date(2026, 12, 12)) == 1
    )


@pytest.mark.asyncio
async def test_a_full_room_type_gives_no_availability(repos: Repos) -> None:
    """The only Big room is taken, so an overlapping booking is refused."""
    await repos.bookings.create_booking(new_booking(room_type=BIG))

    second = await repos.bookings.create_booking(
        new_booking(
            room_type=BIG,
            idempotency_key="call-2",
            phone="+12025550198",
            check_in=date(2026, 12, 11),
            check_out=date(2026, 12, 13),
        )
    )

    assert second == BookingConflict(reason="no_availability")


@pytest.mark.asyncio
async def test_a_stay_starting_on_the_checkout_day_fits(repos: Repos) -> None:
    """check_out is exclusive, so back-to-back stays share the one Big room."""
    await repos.bookings.create_booking(new_booking(room_type=BIG))

    second = await repos.bookings.create_booking(
        new_booking(
            room_type=BIG,
            idempotency_key="call-2",
            phone="+12025550198",
            check_in=date(2026, 12, 12),
            check_out=date(2026, 12, 14),
        )
    )

    assert isinstance(second, Booking)


@pytest.mark.asyncio
async def test_an_unknown_phone_finds_no_guest(repos: Repos) -> None:
    """No guest row exists until someone books."""
    assert await repos.bookings.find_guest("+12025550199") is None


@pytest.mark.asyncio
async def test_a_returning_guest_is_reused_and_a_new_email_stored(
    repos: Repos,
) -> None:
    """Same phone, same name in any case: one guest, with the latest email."""
    await repos.bookings.create_booking(new_booking())

    second = await repos.bookings.create_booking(
        new_booking(
            idempotency_key="call-2",
            first_name="ADA",
            last_name="testa",
            email="ada@example.com",
            check_in=date(2027, 1, 10),
            check_out=date(2027, 1, 12),
        )
    )

    assert isinstance(second, Booking)
    assert second.first_name == "Ada"
    assert await repos.bookings.find_guest("+12025550199") == GuestSummary(
        first_name="Ada", last_name="Testa", has_email=True
    )


@pytest.mark.asyncio
async def test_a_phone_on_file_under_another_name_is_refused(repos: Repos) -> None:
    """Someone else's phone cannot book under a new name."""
    await repos.bookings.create_booking(new_booking())

    second = await repos.bookings.create_booking(
        new_booking(idempotency_key="call-2", first_name="Bruno", last_name="Verdi")
    )

    assert second == BookingConflict(reason="phone_belongs_to_other_guest")


NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_cancelling_frees_the_room(repos: Repos) -> None:
    """A cancelled booking no longer counts as booked."""
    created = await repos.bookings.create_booking(new_booking())

    cancelled = await repos.bookings.cancel_booking(created.reference, "Testa", NOW)

    assert cancelled is not None
    assert (cancelled.status, cancelled.cancelled_at) == ("cancelled", NOW)
    assert (
        await repos.hotel.count_booked(STD, date(2026, 12, 10), date(2026, 12, 12)) == 0
    )


@pytest.mark.asyncio
async def test_cancelling_twice_keeps_the_first_cancellation_time(
    repos: Repos,
) -> None:
    """Cancel is idempotent; the original time decides whether it was late."""
    created = await repos.bookings.create_booking(new_booking())
    await repos.bookings.cancel_booking(created.reference, "Testa", NOW)

    again = await repos.bookings.cancel_booking(
        created.reference, "Testa", datetime(2026, 12, 9, tzinfo=UTC)
    )

    assert again is not None and again.cancelled_at == NOW


@pytest.mark.asyncio
async def test_cancelling_with_a_wrong_last_name_does_nothing(repos: Repos) -> None:
    """The reference alone cannot cancel a booking."""
    created = await repos.bookings.create_booking(new_booking())

    assert await repos.bookings.cancel_booking(created.reference, "Rossi", NOW) is None
    found = await repos.bookings.get_booking(created.reference, "Testa")
    assert found is not None and found.status == "confirmed"


def change(**overrides: object) -> BookingChange:
    """The new values for a booking made by new_booking(); override any field."""
    fields: dict[str, object] = {
        "room_type": STD,
        "check_in": date(2026, 12, 10),
        "check_out": date(2026, 12, 12),
        "adults": 2,
        "total_cents": 20000,
    }
    fields.update(overrides)
    return BookingChange.model_validate(fields)


@pytest.mark.asyncio
async def test_modifying_keeps_the_reference_and_moves_the_stay(repos: Repos) -> None:
    """New dates, adults and price; same reference; availability follows."""
    created = await repos.bookings.create_booking(new_booking())

    moved = await repos.bookings.modify_booking(
        created.reference,
        "testa",
        change(
            check_in=date(2027, 1, 5),
            check_out=date(2027, 1, 8),
            adults=1,
            total_cents=30000,
        ),
    )

    assert isinstance(moved, Booking)
    assert moved.reference == created.reference
    assert (moved.check_in, moved.check_out, moved.adults, moved.total_cents) == (
        date(2027, 1, 5),
        date(2027, 1, 8),
        1,
        30000,
    )
    assert (
        await repos.hotel.count_booked(STD, date(2026, 12, 10), date(2026, 12, 12)) == 0
    )
    assert await repos.hotel.count_booked(STD, date(2027, 1, 5), date(2027, 1, 8)) == 1


@pytest.mark.asyncio
async def test_a_booking_does_not_block_its_own_new_dates(repos: Repos) -> None:
    """Extending the only Big room's stay by a night overlaps only itself."""
    created = await repos.bookings.create_booking(new_booking(room_type=BIG))

    moved = await repos.bookings.modify_booking(
        created.reference,
        "Testa",
        change(room_type=BIG, check_out=date(2026, 12, 13), total_cents=30000),
    )

    assert isinstance(moved, Booking) and moved.check_out == date(2026, 12, 13)


@pytest.mark.asyncio
async def test_modifying_into_a_full_type_changes_nothing(repos: Repos) -> None:
    """The Big room is taken, so the switch is refused and the booking stays put."""
    await repos.bookings.create_booking(
        new_booking(
            room_type=BIG,
            idempotency_key="call-2",
            phone="+12025550198",
            first_name="Bruno",
            last_name="Verdi",
        )
    )
    created = await repos.bookings.create_booking(new_booking())

    result = await repos.bookings.modify_booking(
        created.reference, "Testa", change(room_type=BIG)
    )

    assert result == BookingConflict(reason="no_availability")
    assert await repos.bookings.get_booking(created.reference, "Testa") == created


@pytest.mark.asyncio
async def test_modifying_with_a_wrong_last_name_finds_nothing(repos: Repos) -> None:
    """The reference alone cannot change a booking."""
    created = await repos.bookings.create_booking(new_booking())

    assert (
        await repos.bookings.modify_booking(
            created.reference, "Rossi", change(adults=1)
        )
        is None
    )


SENT_AT = datetime(2026, 11, 9, 14, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_confirmation_target_carries_the_stored_email(repos: Repos) -> None:
    """The email is only for sending; the tool never shows it to the model."""
    created = await repos.bookings.create_booking(
        new_booking(email="ada@guest.example")
    )

    target = await repos.bookings.get_confirmation_target(created.reference, "testa")

    assert target is not None
    assert target.booking == created
    assert target.email == "ada@guest.example"
    assert target.guest_id
    assert (
        await repos.bookings.get_confirmation_target(created.reference, "Rossi") is None
    )


@pytest.mark.asyncio
async def test_a_guest_without_email_has_no_target_email(repos: Repos) -> None:
    """No email on file is reported, not guessed."""
    created = await repos.bookings.create_booking(new_booking())

    target = await repos.bookings.get_confirmation_target(created.reference, "Testa")

    assert target is not None and target.email is None


@pytest.mark.asyncio
async def test_a_confirmation_is_claimed_once_until_released(repos: Repos) -> None:
    """The claim stops a second send; releasing it after a failure allows a retry."""
    created = await repos.bookings.create_booking(new_booking())

    assert await repos.bookings.claim_confirmation(created.reference, SENT_AT)
    assert not await repos.bookings.claim_confirmation(created.reference, SENT_AT)
    await repos.bookings.release_confirmation(created.reference, SENT_AT)
    assert await repos.bookings.claim_confirmation(created.reference, SENT_AT)


@pytest.mark.asyncio
async def test_a_stale_release_keeps_a_newer_claim(repos: Repos) -> None:
    """An old failed send must not clear the mark of a newer, successful one."""
    created = await repos.bookings.create_booking(new_booking())
    later = SENT_AT.replace(minute=45)
    await repos.bookings.claim_confirmation(created.reference, SENT_AT)
    await repos.bookings.modify_booking(created.reference, "Testa", change(adults=1))
    await repos.bookings.claim_confirmation(created.reference, later)

    await repos.bookings.release_confirmation(created.reference, SENT_AT)

    assert not await repos.bookings.claim_confirmation(created.reference, later)


@pytest.mark.asyncio
async def test_modifying_a_booking_allows_a_new_confirmation(repos: Repos) -> None:
    """Changed details need a new email, so modify clears the claim."""
    created = await repos.bookings.create_booking(new_booking())
    await repos.bookings.claim_confirmation(created.reference, SENT_AT)

    await repos.bookings.modify_booking(created.reference, "Testa", change(adults=1))

    assert await repos.bookings.claim_confirmation(created.reference, SENT_AT)


@pytest.mark.asyncio
async def test_the_guest_contact_is_found_by_phone(repos: Repos) -> None:
    """The follow-up email needs the stored address; it never reaches the model."""
    assert await repos.bookings.find_guest_contact("+12025550199") is None
    await repos.bookings.create_booking(new_booking(email="ada@guest.example"))

    contact = await repos.bookings.find_guest_contact("+12025550199")

    assert contact is not None
    assert (contact.first_name, contact.email) == ("Ada", "ada@guest.example")
    assert contact.guest_id
