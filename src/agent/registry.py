"""Tool registry: the tools the agent can call, with their schemas."""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time
from typing import cast

from pydantic import BaseModel, ConfigDict

from src.agent.llm import ToolSpec
from src.db.bookings import BookingRepository
from src.db.hotel import HotelRepository
from src.email.sender import EmailSender, FakeEmailSender
from src.tools import MAX_STAY_NIGHTS
from src.tools.cancel_booking import HOTEL_TZ, CancelBookingInput, cancel_booking
from src.tools.check_availability import AvailabilityInput, check_availability
from src.tools.context import CallContext
from src.tools.create_booking import CreateBookingInput, create_booking
from src.tools.get_booking import GetBookingInput, get_booking
from src.tools.get_guest_info import GetGuestInfoInput, get_guest_info
from src.tools.get_rates import GetRatesInput, get_rates
from src.tools.modify_booking import ModifyBookingInput, modify_booking
from src.tools.send_confirmation_email import (
    SendConfirmationEmailInput,
    send_confirmation_email,
)
from src.tools.send_followup_email import SendFollowupEmailInput, send_followup_email
from src.tools.take_message import TakeMessageInput, take_message

# What the model reads when it decides whether and how to call a tool. Follows
# Anthropic's guidance: what it does, when to use it, what it returns, what it does
# not do, and what each error reason means. Keep the reasons in sync with
# docs/tools.md (tests/test_tool_specs.py checks they are all named).
_AVAILABILITY_DESCRIPTION = (
    "Checks which room types have at least one free room for the whole stay and can "
    "hold the whole party. "
    "Use it as soon as you know the arrival date, the departure date and the number "
    "of guests; do not wait for the caller to choose a room type, because the result "
    "is what you offer them. "
    "It returns every room type that fits, with how many rooms of it are free, and "
    "an empty list means the hotel is fully booked for those dates. "
    "It does not return prices (use get_rates for that) and it cannot make a "
    "booking. "
    "On failure it returns a reason instead: "
    f"invalid_dates when the departure is not after the arrival, the arrival is in "
    f"the past or the stay is longer than {MAX_STAY_NIGHTS} nights; "
    "invalid_guests when the guest count is below one; "
    "too_many_guests when the party is larger than the biggest room, which means no "
    "single room fits them."
)
_RATES_DESCRIPTION = (
    "Prices a stay for one room type, night by night, so a stay that crosses from "
    "low to high season is priced correctly. "
    "Use it once the caller has chosen a room type from a check_availability result "
    "(which needs the guest count) and you have the arrival date and the departure "
    "date. "
    "It returns the total in euros for the whole stay, the number of nights and the "
    "price of each night. "
    "It does not check that the room is free or that it fits the party, so call "
    "check_availability first, and it cannot make a booking. "
    "On failure it returns a reason instead: "
    "unknown_room_type when the name is not one of the hotel's room types (the "
    "result then lists the valid names, so offer those); "
    f"invalid_dates when the departure is not after the arrival, the arrival is in "
    f"the past or the stay is longer than {MAX_STAY_NIGHTS} nights; "
    "no_rate_for_dates when some night of the stay has no price set."
)

_GET_GUEST_INFO_DESCRIPTION = (
    "Finds out whether the caller is a returning guest, from the number they are "
    "calling from; it takes no arguments. "
    "Use it once the caller wants to book and you need their name, before asking "
    "for it. "
    "It returns found with the guest's first and last name and whether an email "
    "is on file, or found false when there is no match or the number is withheld, "
    "in which case ask for the name. "
    "When found, confirm the name with the caller before using it; if they are "
    "someone else, ask for their own mobile number and pass it to create_booking. "
    "It does not read bookings (use get_booking) and it does not create a guest."
)
_CREATE_BOOKING_DESCRIPTION = (
    "Books one room of a type for a stay and returns the booking reference. "
    "Use it only after check_availability has shown the type is free, get_rates "
    "has priced it, and the caller has said yes to your read-back of the dates, "
    "room type, number of adults, name and total price. "
    "It returns the 6-digit reference, the dates, the total in euros and whether "
    "an email is on file; read the reference digit by digit. "
    "The price is worked out by the hotel, so never pass one; it books one room "
    "only and does not send the confirmation email (use send_confirmation_email). "
    "On failure it returns a reason instead: "
    f"invalid_dates when the departure is not after the arrival, the arrival is in "
    f"the past or the stay is longer than {MAX_STAY_NIGHTS} nights; "
    "invalid_guests when adults is below one; "
    "unknown_room_type when the name is not one of the hotel's room types; "
    "too_many_guests when more adults than this room type holds; "
    "no_availability when no room of the type is left, which can happen during the "
    "call, so offer the other free types; "
    "no_rate_for_dates when some night has no price; "
    "phone_required when the number is withheld and no phone was passed, so ask "
    "for a mobile number; "
    "invalid_phone when the phone is not in international format with the country "
    "code, so ask again; "
    "phone_belongs_to_other_guest when that phone is on file under another name, "
    "so ask for the caller's own number; "
    "invalid_email when the email is not a valid address, so spell it back again."
)
_GET_BOOKING_DESCRIPTION = (
    "Reads back an existing booking from its reference and the guest's last name. "
    "Use it whenever the caller asks about, wants to change or wants to cancel a "
    "booking, and always before modify_booking or cancel_booking, so you can read "
    "the details back and confirm it is the right one. "
    "It returns the status, the first name, the room type, the dates, the number "
    "of adults and the total in euros. "
    "It does not change anything and it cannot find a booking without its "
    "reference. "
    "On failure it returns a reason instead: not_found when no booking has that "
    "reference and last name; ask the caller to repeat both, without saying which "
    "one was wrong."
)
_MODIFY_BOOKING_DESCRIPTION = (
    "Changes the dates, the number of adults or the room type of a confirmed "
    "booking, keeping the same reference; pass only what changes. "
    "Use it after get_booking has found the booking, get_rates has priced the new "
    "stay, and the caller has said yes to the new details and the new total. "
    "It returns the updated booking with its new total in euros; then call "
    "send_confirmation_email so the guest gets the new details. "
    "It does not cancel a booking (use cancel_booking) or change the guest's name. "
    "On failure it returns a reason instead: "
    "not_found when no booking has that reference and last name; "
    "cancelled when the booking is cancelled, so offer a new booking; "
    "past_booking when the stay has already ended; "
    "nothing_to_change when no new value was passed; "
    f"invalid_dates when the departure is not after the arrival, the arrival is in "
    f"the past or the stay is longer than {MAX_STAY_NIGHTS} nights; "
    "invalid_guests when adults is below one; "
    "unknown_room_type when the name is not one of the hotel's room types; "
    "too_many_guests when more adults than the room type holds; "
    "no_availability when the new dates or room type are not free; "
    "no_rate_for_dates when some night has no price."
)
_CANCEL_BOOKING_DESCRIPTION = (
    "Cancels a booking and frees its room. "
    "Use it after get_booking has found the booking and the caller has said yes "
    "to cancelling it. "
    "It returns late_cancellation, which is true when it is less than forty-eight "
    "hours before check-in: then tell the caller the cancellation policy charge "
    "may apply, without naming an amount. "
    "It does not refund or charge anything, and it does not change a booking "
    "(use modify_booking). "
    "On failure it returns a reason instead: "
    "not_found when no booking has that reference and last name; "
    "past_booking when the stay has already ended."
)
_SEND_CONFIRMATION_DESCRIPTION = (
    "Emails the guest their booking as it now stands, to the email address on "
    "file: a confirmation with a calendar invite for a confirmed booking, or a "
    "cancellation that removes the event from their calendar for a cancelled one. "
    "Call it right after create_booking, modify_booking or cancel_booking "
    "succeeds, without asking the caller again, then say the email will arrive in "
    "a few minutes. "
    "It returns ok once the email is on its way; calling it again for the same "
    "booking sends nothing more until the booking changes again. "
    "It does not take an email address: create_booking stores the email, and this "
    "tool cannot change it. "
    "On failure it returns a reason instead: "
    "not_found when no booking has that reference and last name; "
    "no_email_on_file when the guest gave no email, so say nothing more about "
    "email."
)
_TAKE_MESSAGE_DESCRIPTION = (
    "Passes a message from the caller to the hotel's reception team by email; this "
    "is how the caller reaches a person, because you cannot transfer the call. "
    "Use it when the caller asks for a person, a manager or a department, or wants "
    "something no other tool does, such as a special request or a complaint, once "
    "you have their first and last name and a short summary of what they want. "
    "It returns ok once the message is on its way; then say you have passed it to "
    "reception, without saying when or how they will reply. "
    "It does not book, change or cancel anything and it does not email the caller "
    "(use send_followup_email when a tool keeps failing). "
    "On failure it returns a reason instead: "
    "contact_required when the number is withheld and no phone or email was "
    "passed, so ask for a phone number or an email; "
    "invalid_phone when the phone is not in international format with the country "
    "code, so ask again; "
    "invalid_email when the email is not a valid address, so spell it back again."
)
_SEND_FOLLOWUP_DESCRIPTION = (
    "Emails the caller so they can write down what they need and reception can "
    "finish it by email, when you could not do it on the phone. "
    "Use it only after a tool has failed with tool_error or tool_timeout, or "
    "another failure the caller cannot fix, you tried once more and it failed "
    "again, and the caller agreed to receive an email. "
    "It returns ok once the email is on its way, to the email the caller spelled "
    "or else the one on file; then say it will arrive in a few minutes. "
    "It does not retry the failed tool or explain what went wrong, and it does not "
    "pass a message to reception (use take_message for that). "
    "On failure it returns a reason instead: "
    "email_required when no email was passed and none is on file, so ask the "
    "caller to spell one and read it back once; "
    "invalid_email when the email is not a valid address, so spell it back again."
)


class Tool(BaseModel):
    """A callable tool: schema for the model plus the handler to run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[BaseModel]]

    def spec(self) -> ToolSpec:
        """Return the schema the model sees."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.input_model.model_json_schema(),
        )


def build_registry(
    hotel: HotelRepository,
    bookings: BookingRepository,
    ctx: CallContext,
    today: date | None = None,
    sender: EmailSender | None = None,
) -> dict[str, Tool]:
    """Build the tool registry bound to the hotel and to one call.

    Args:
        hotel: Inventory and rates.
        bookings: Guests and reservations.
        ctx: The call's id and caller ID, which the model never sees.
        today: Override for the current date, so evals are deterministic. When set,
            cancel_booking also treats "now" as 10:00 hotel time on that day.
        sender: Sends confirmation emails; a fake that sends nothing by default.
    """
    now = datetime.combine(today, time(10, 0), HOTEL_TZ) if today else None

    async def _availability(inp: BaseModel) -> BaseModel:
        return await check_availability(hotel, cast(AvailabilityInput, inp), today)

    async def _rates(inp: BaseModel) -> BaseModel:
        return await get_rates(hotel, cast(GetRatesInput, inp), today)

    async def _guest_info(_: BaseModel) -> BaseModel:
        return await get_guest_info(bookings, ctx)

    async def _create(inp: BaseModel) -> BaseModel:
        return await create_booking(
            hotel, bookings, ctx, cast(CreateBookingInput, inp), today
        )

    async def _get(inp: BaseModel) -> BaseModel:
        return await get_booking(bookings, cast(GetBookingInput, inp))

    async def _modify(inp: BaseModel) -> BaseModel:
        return await modify_booking(
            hotel, bookings, cast(ModifyBookingInput, inp), today
        )

    async def _cancel(inp: BaseModel) -> BaseModel:
        return await cancel_booking(bookings, cast(CancelBookingInput, inp), now)

    email_sender = sender or FakeEmailSender()

    async def _confirm(inp: BaseModel) -> BaseModel:
        return await send_confirmation_email(
            bookings,
            email_sender,
            cast(SendConfirmationEmailInput, inp),
            now or datetime.now(UTC),
        )

    async def _message(inp: BaseModel) -> BaseModel:
        return await take_message(email_sender, ctx, cast(TakeMessageInput, inp))

    async def _followup(inp: BaseModel) -> BaseModel:
        return await send_followup_email(
            bookings, email_sender, ctx, cast(SendFollowupEmailInput, inp)
        )

    tools = [
        Tool(
            name="check_availability",
            description=_AVAILABILITY_DESCRIPTION,
            input_model=AvailabilityInput,
            handler=_availability,
        ),
        Tool(
            name="get_rates",
            description=_RATES_DESCRIPTION,
            input_model=GetRatesInput,
            handler=_rates,
        ),
        Tool(
            name="get_guest_info",
            description=_GET_GUEST_INFO_DESCRIPTION,
            input_model=GetGuestInfoInput,
            handler=_guest_info,
        ),
        Tool(
            name="create_booking",
            description=_CREATE_BOOKING_DESCRIPTION,
            input_model=CreateBookingInput,
            handler=_create,
        ),
        Tool(
            name="get_booking",
            description=_GET_BOOKING_DESCRIPTION,
            input_model=GetBookingInput,
            handler=_get,
        ),
        Tool(
            name="modify_booking",
            description=_MODIFY_BOOKING_DESCRIPTION,
            input_model=ModifyBookingInput,
            handler=_modify,
        ),
        Tool(
            name="cancel_booking",
            description=_CANCEL_BOOKING_DESCRIPTION,
            input_model=CancelBookingInput,
            handler=_cancel,
        ),
        Tool(
            name="send_confirmation_email",
            description=_SEND_CONFIRMATION_DESCRIPTION,
            input_model=SendConfirmationEmailInput,
            handler=_confirm,
        ),
        Tool(
            name="take_message",
            description=_TAKE_MESSAGE_DESCRIPTION,
            input_model=TakeMessageInput,
            handler=_message,
        ),
        Tool(
            name="send_followup_email",
            description=_SEND_FOLLOWUP_DESCRIPTION,
            input_model=SendFollowupEmailInput,
            handler=_followup,
        ),
    ]
    return {t.name: t for t in tools}
