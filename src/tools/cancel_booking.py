"""cancel_booking tool: cancel a booking and say whether it was late."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.db.bookings import BookingRepository
from src.tools.stay import LAST_NAME_DESCRIPTION, REFERENCE_DESCRIPTION, clean_reference

HOTEL_TZ = ZoneInfo("Europe/Rome")
CHECK_IN_TIME = time(15, 0)
FREE_CANCELLATION = timedelta(hours=48)


class CancelBookingInput(BaseModel):
    """Arguments the agent passes."""

    reference: str = Field(description=REFERENCE_DESCRIPTION)
    last_name: str = Field(description=LAST_NAME_DESCRIPTION)


class CancelBookingOk(BaseModel):
    """The booking is cancelled. late_cancellation means the policy charge may apply."""

    ok: bool = True
    reference: str
    late_cancellation: bool


class CancelBookingError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str


async def cancel_booking(
    bookings: BookingRepository,
    inp: CancelBookingInput,
    now: datetime | None = None,
) -> CancelBookingOk | CancelBookingError:
    """Cancel a booking, free its room and flag a cancellation inside 48 hours.

    Args:
        bookings: Guest and reservation access.
        inp: Reference and last name.
        now: Override for the current time (tests).

    Returns:
        Whether it was a late cancellation, or an error with a spoken-friendly reason.
    """
    now = now or datetime.now(UTC)
    reference = clean_reference(inp.reference)
    current = await bookings.get_booking(reference, inp.last_name)
    if current is None:
        return CancelBookingError(reason="not_found")
    if (
        current.status == "confirmed"
        and current.check_out <= now.astimezone(HOTEL_TZ).date()
    ):
        return CancelBookingError(reason="past_booking")
    cancelled = await bookings.cancel_booking(reference, inp.last_name, now)
    if cancelled is None or cancelled.cancelled_at is None:
        return CancelBookingError(reason="not_found")
    check_in_at = datetime.combine(cancelled.check_in, CHECK_IN_TIME, HOTEL_TZ)
    return CancelBookingOk(
        reference=reference,
        late_cancellation=cancelled.cancelled_at > check_in_at - FREE_CANCELLATION,
    )
