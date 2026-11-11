"""Contract tests for CallLogRepository, run against every implementation.

Like test_booking_repo.py, the Postgres run uses a rolled-back transaction and is
skipped when DATABASE_URL is not set.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import asyncpg
import pytest
import pytest_asyncio

from src.db.bookings import Booking, BookingRepository
from src.db.calls import CallEvent, CallLogRepository, InMemoryCallLogRepository
from src.db.postgres import PostgresCallLogRepository
from tests.test_booking_repo import (
    DATABASE_URL,
    _memory_repos,
    _postgres_repos,
    new_booking,
)


@dataclass
class Repos:
    """A call log and a booking repository over the same data."""

    calls: CallLogRepository
    bookings: BookingRepository


@pytest_asyncio.fixture(params=["memory", "postgres"])
async def repos(request: pytest.FixtureRequest) -> AsyncIterator[Repos]:
    """Yield the call log from each implementation."""
    if request.param == "memory":
        yield Repos(InMemoryCallLogRepository(), _memory_repos().bookings)
        return
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        hotel = await _postgres_repos(conn)
        yield Repos(PostgresCallLogRepository(conn), hotel.bookings)
    finally:
        await tx.rollback()
        await conn.close()


async def _booked(bookings: BookingRepository) -> str:
    created = await bookings.create_booking(new_booking())
    assert isinstance(created, Booking)
    return created.reference


@pytest.mark.asyncio
async def test_an_unknown_call_has_no_entry(repos: Repos) -> None:
    """Nothing is stored for a call until a tool runs."""
    assert await repos.calls.get("conv-none") is None


@pytest.mark.asyncio
async def test_the_first_event_creates_the_entry(repos: Repos) -> None:
    """A bare event records the call with nothing else known yet."""
    await repos.calls.record(CallEvent(call_id="conv-1"))

    entry = await repos.calls.get("conv-1")
    assert entry is not None
    assert entry.language is None
    assert entry.outcome is None
    assert entry.reference is None
    assert entry.needs_followup is False
    assert entry.followup_reason is None


@pytest.mark.asyncio
async def test_later_events_fill_in_without_erasing(repos: Repos) -> None:
    """An event without a field keeps what an earlier event stored."""
    reference = await _booked(repos.bookings)
    await repos.calls.record(
        CallEvent(
            call_id="conv-1", language="it", outcome="booked", reference=reference
        )
    )
    await repos.calls.record(CallEvent(call_id="conv-1"))

    entry = await repos.calls.get("conv-1")
    assert entry is not None
    assert (entry.language, entry.outcome, entry.reference) == (
        "it",
        "booked",
        reference,
    )


@pytest.mark.asyncio
async def test_the_latest_outcome_wins(repos: Repos) -> None:
    """Booking then cancelling in one call ends as cancelled."""
    reference = await _booked(repos.bookings)
    await repos.calls.record(
        CallEvent(call_id="conv-1", outcome="booked", reference=reference)
    )
    await repos.calls.record(
        CallEvent(call_id="conv-1", outcome="cancelled", reference=reference)
    )

    entry = await repos.calls.get("conv-1")
    assert entry is not None
    assert entry.outcome == "cancelled"


@pytest.mark.asyncio
async def test_a_followup_once_flagged_stays_flagged(repos: Repos) -> None:
    """needs_followup is never cleared by a later event in the same call."""
    await repos.calls.record(
        CallEvent(call_id="conv-1", needs_followup=True, followup_reason="message")
    )
    await repos.calls.record(CallEvent(call_id="conv-1", language="en"))

    entry = await repos.calls.get("conv-1")
    assert entry is not None
    assert entry.needs_followup is True
    assert entry.followup_reason == "message"
    assert entry.language == "en"


@pytest.mark.asyncio
async def test_calls_are_kept_apart(repos: Repos) -> None:
    """Each call_id has its own entry."""
    await repos.calls.record(CallEvent(call_id="conv-1", language="it"))
    await repos.calls.record(CallEvent(call_id="conv-2", language="en"))

    first = await repos.calls.get("conv-1")
    second = await repos.calls.get("conv-2")
    assert first is not None and second is not None
    assert (first.language, second.language) == ("it", "en")
