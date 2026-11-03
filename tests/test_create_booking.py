"""Tests for the create_booking tool."""

from datetime import date

import pytest

from src.db.bookings import InMemoryBookingRepository
from src.db.hotel import Rate, RoomType
from src.tools.context import CallContext
from src.tools.create_booking import (
    CreateBookingError,
    CreateBookingInput,
    CreateBookingOk,
    create_booking,
)

TODAY = date(2026, 11, 2)
PHONE = "+12025550199"
CTX = CallContext(call_id="call-1", caller_phone=PHONE)


def make_repo() -> InMemoryBookingRepository:
    """2 Superior (max 2) at 100 a night and 1 Suite (max 4) at 300 a night."""
    rates = [
        Rate(
            room_type=name,
            valid_from=date(2026, 11, 1),
            valid_to=date(2027, 3, 31),
            price_per_night_eur=price,
        )
        for name, price in [("Superior", 100), ("Suite", 300)]
    ]
    return InMemoryBookingRepository(
        room_types=[
            RoomType(name="Superior", max_guests=2, rooms=2),
            RoomType(name="Suite", max_guests=4, rooms=1),
        ],
        rates=rates,
        stays=[],
    )


def booking_input(**overrides: object) -> CreateBookingInput:
    """Two nights in a Superior for Ada Testa; override any field."""
    fields: dict[str, object] = {
        "room_type": "Superior",
        "check_in": date(2026, 12, 10),
        "check_out": date(2026, 12, 12),
        "adults": 2,
        "first_name": "Ada",
        "last_name": "Testa",
        "language": "it",
    }
    fields.update(overrides)
    return CreateBookingInput.model_validate(fields)


async def book(
    repo: InMemoryBookingRepository,
    ctx: CallContext = CTX,
    **overrides: object,
) -> CreateBookingOk | CreateBookingError:
    """Run the tool with today fixed."""
    return await create_booking(repo, repo, ctx, booking_input(**overrides), TODAY)


@pytest.mark.asyncio
async def test_books_a_room_priced_by_the_server() -> None:
    """The total comes from the rates; the reference can be read back."""
    repo = make_repo()

    result = await book(repo, room_type="superior")

    assert isinstance(result, CreateBookingOk)
    assert (result.room_type, result.nights, result.total_eur) == ("Superior", 2, 200)
    assert result.email_on_file is False
    found = await repo.get_booking(result.reference, "Testa")
    assert found is not None and found.total_cents == 20000


@pytest.mark.asyncio
async def test_an_email_given_is_on_file() -> None:
    """A valid email is stored with the guest."""
    result = await book(make_repo(), email="ada@example.com")

    assert isinstance(result, CreateBookingOk) and result.email_on_file is True


@pytest.mark.asyncio
async def test_a_retried_call_returns_the_same_booking() -> None:
    """Same call, same stay, same phone: no second booking."""
    repo = make_repo()

    first = await book(repo)
    again = await book(repo)

    assert isinstance(first, CreateBookingOk) and again == first


@pytest.mark.asyncio
async def test_the_phone_given_overrides_the_caller_id() -> None:
    """Someone else on a shared phone books under their own number."""
    repo = make_repo()

    await book(repo, phone="+12025550123")

    assert await repo.find_guest("+12025550123") is not None
    assert await repo.find_guest(PHONE) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ctx", "overrides", "reason"),
    [
        (CallContext(call_id="c", caller_phone=None), {}, "phone_required"),
        (CTX, {"phone": "3471234567"}, "invalid_phone"),
        (CTX, {"email": "ada at example"}, "invalid_email"),
        (CTX, {"adults": 0}, "invalid_guests"),
        (CTX, {"adults": 3}, "too_many_guests"),
        (CTX, {"room_type": "Attic"}, "unknown_room_type"),
        (CTX, {"check_in": date(2026, 11, 1)}, "invalid_dates"),
        (
            CTX,
            {"check_in": date(2027, 3, 30), "check_out": date(2027, 4, 2)},
            "no_rate_for_dates",
        ),
    ],
)
async def test_bad_requests_are_refused_with_a_reason(
    ctx: CallContext, overrides: dict[str, object], reason: str
) -> None:
    """Each problem the agent can fix comes back as a reason, and nothing is booked."""
    repo = make_repo()

    result = await book(repo, ctx, **overrides)

    assert result == CreateBookingError(reason=reason)
    assert (
        await repo.count_booked("Superior", date(2026, 12, 10), date(2026, 12, 12)) == 0
    )


@pytest.mark.asyncio
async def test_a_full_room_type_gives_no_availability() -> None:
    """The only Suite is taken by an earlier call."""
    repo = make_repo()
    await book(
        repo,
        CallContext(call_id="other", caller_phone="+12025550111"),
        room_type="Suite",
        first_name="Bruno",
        last_name="Verdi",
    )

    result = await book(repo, room_type="Suite")

    assert result == CreateBookingError(reason="no_availability")


@pytest.mark.asyncio
async def test_a_phone_on_file_under_another_name_is_refused() -> None:
    """The caller ID belongs to Ada, but the caller says they are Bruno."""
    repo = make_repo()
    await book(repo)

    result = await book(
        repo,
        CallContext(call_id="call-2", caller_phone=PHONE),
        first_name="Bruno",
        last_name="Verdi",
    )

    assert result == CreateBookingError(reason="phone_belongs_to_other_guest")
