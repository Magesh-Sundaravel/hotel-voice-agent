"""create_booking tool: book one room for a stay."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from src.db.bookings import BookingConflict, BookingRepository, NewBooking
from src.db.hotel import HotelRepository
from src.tools import CHECK_IN_DESCRIPTION, CHECK_OUT_DESCRIPTION
from src.tools.context import CallContext
from src.tools.stay import E164, EMAIL, price_stay


class CreateBookingInput(BaseModel):
    """Arguments the agent passes. check_out is exclusive."""

    room_type: str = Field(
        description=(
            "Name of the room type the caller chose, copied from a "
            "check_availability result. Upper or lower case does not matter."
        )
    )
    check_in: date = Field(description=CHECK_IN_DESCRIPTION)
    check_out: date = Field(description=CHECK_OUT_DESCRIPTION)
    adults: int = Field(description="Number of people staying in the room. At least 1.")
    first_name: str = Field(description="The guest's first name, as they said it.")
    last_name: str = Field(description="The guest's last name, as they spelled it.")
    language: Literal["it", "en"] = Field(
        description="The language the caller is speaking: 'it' or 'en'."
    )
    email: str | None = Field(
        default=None,
        description=(
            "The guest's email for the confirmation, spelled back to them once. "
            "Leave out if they would rather not give one."
        ),
    )
    phone: str | None = Field(
        default=None,
        description=(
            "The guest's mobile in international format, like +393471234567. Only "
            "when the caller's number is withheld, or the caller is not the guest "
            "get_guest_info found. Otherwise leave out: the caller ID is used."
        ),
    )


class CreateBookingOk(BaseModel):
    """The booking that was made."""

    ok: bool = True
    reference: str
    room_type: str
    check_in: date
    check_out: date
    nights: int
    adults: int
    total_eur: int
    email_on_file: bool


class CreateBookingError(BaseModel):
    """Failure the agent can say out loud."""

    ok: bool = False
    reason: str


async def create_booking(
    hotel: HotelRepository,
    bookings: BookingRepository,
    ctx: CallContext,
    inp: CreateBookingInput,
    today: date | None = None,
) -> CreateBookingOk | CreateBookingError:
    """Book the lowest free room of a type, priced from the hotel's rates.

    Args:
        hotel: Inventory and rates.
        bookings: Guest and reservation access.
        ctx: The call: its id (for idempotency) and the caller ID.
        inp: The stay and the guest.
        today: Override for the current date (tests).

    Returns:
        The booking, or an error with a spoken-friendly reason.
    """
    stay = await price_stay(
        hotel, inp.room_type, inp.check_in, inp.check_out, inp.adults, today
    )
    if isinstance(stay, str):
        return CreateBookingError(reason=stay)
    phone = inp.phone.replace(" ", "") if inp.phone else ctx.caller_phone
    if phone is None:
        return CreateBookingError(reason="phone_required")
    if not E164.match(phone):
        return CreateBookingError(reason="invalid_phone")
    email = inp.email.strip() if inp.email else None
    if email is not None and not EMAIL.match(email):
        return CreateBookingError(reason="invalid_email")
    result = await bookings.create_booking(
        NewBooking(
            idempotency_key="|".join(
                [
                    ctx.call_id,
                    stay.room_type,
                    str(inp.check_in),
                    str(inp.check_out),
                    phone,
                ]
            ),
            room_type=stay.room_type,
            check_in=inp.check_in,
            check_out=inp.check_out,
            adults=inp.adults,
            total_cents=stay.total_eur * 100,
            first_name=inp.first_name.strip(),
            last_name=inp.last_name.strip(),
            phone=phone,
            email=email,
            language=inp.language,
        )
    )
    if isinstance(result, BookingConflict):
        return CreateBookingError(reason=result.reason)
    guest = await bookings.find_guest(phone)
    return CreateBookingOk(
        reference=result.reference,
        room_type=result.room_type,
        check_in=result.check_in,
        check_out=result.check_out,
        nights=stay.nights,
        adults=result.adults,
        total_eur=result.total_cents // 100,
        email_on_file=guest is not None and guest.has_email,
    )
