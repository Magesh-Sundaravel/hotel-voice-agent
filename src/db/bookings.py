"""Guest and reservation access: the BookingRepository protocol and its in-memory fake."""

import secrets
import uuid
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from src.db.hotel import InMemoryHotelRepository, Rate, RoomType, Stay


class NewBooking(BaseModel):
    """Everything needed to book one room. The price is computed by the caller."""

    idempotency_key: str
    room_type: str
    check_in: date
    check_out: date
    adults: int
    total_cents: int
    first_name: str
    last_name: str
    phone: str
    email: str | None
    language: Literal["it", "en"]


class BookingChange(BaseModel):
    """The full new values for a modified booking. The price is computed by the caller."""

    room_type: str
    check_in: date
    check_out: date
    adults: int
    total_cents: int


class Booking(BaseModel):
    """A reservation as the tools see it. check_out is exclusive."""

    reference: str
    status: Literal["confirmed", "cancelled"]
    first_name: str
    room_type: str
    check_in: date
    check_out: date
    adults: int
    total_cents: int
    cancelled_at: datetime | None = None


class GuestSummary(BaseModel):
    """What the agent may know about a returning guest: never the phone or email."""

    first_name: str
    last_name: str
    has_email: bool


class GuestContact(BaseModel):
    """How to email a guest. Used by the server only; never sent to the model."""

    guest_id: str
    first_name: str
    email: str | None


class ConfirmationTarget(BaseModel):
    """What sending a confirmation needs. The email never reaches the model."""

    booking: Booking
    guest_id: str
    email: str | None


class BookingConflict(BaseModel):
    """Why a write could not be done, in a word the tool passes on."""

    reason: Literal["no_availability", "phone_belongs_to_other_guest"]


class BookingRepository(Protocol):
    """Write access to guests and reservations."""

    async def find_guest(self, phone: str) -> GuestSummary | None:
        """Find the guest with this phone (E.164)."""
        ...

    async def find_guest_contact(self, phone: str) -> GuestContact | None:
        """Find the id, first name and email of the guest with this phone (E.164)."""
        ...

    async def create_booking(self, new: NewBooking) -> Booking | BookingConflict:
        """Book the lowest free room of the type; the same key returns the same booking."""
        ...

    async def get_booking(self, reference: str, last_name: str) -> Booking | None:
        """Find a booking by reference and the guest's last name, any case."""
        ...

    async def modify_booking(
        self, reference: str, last_name: str, change: BookingChange
    ) -> Booking | BookingConflict | None:
        """Apply new values to a confirmed booking, keeping its reference.

        Availability ignores the booking's own current stay.
        """
        ...

    async def cancel_booking(
        self, reference: str, last_name: str, now: datetime
    ) -> Booking | None:
        """Cancel a booking at `now`; an already cancelled one is returned unchanged."""
        ...

    async def get_confirmation_target(
        self, reference: str, last_name: str
    ) -> ConfirmationTarget | None:
        """Find a booking with its guest's id and email, by reference and last name."""
        ...

    async def claim_confirmation(self, reference: str, now: datetime) -> bool:
        """Mark the confirmation as sent at `now`; False if it already was."""
        ...

    async def release_confirmation(self, reference: str, claimed_at: datetime) -> None:
        """Clear the mark set at `claimed_at` after a failed send, so a retry works.

        A newer mark (the booking was modified and re-sent meanwhile) is kept.
        """
        ...


def same_name(first_a: str, last_a: str, first_b: str, last_b: str) -> bool:
    """Whether two names are the same person's, ignoring case and outer spaces."""
    return (first_a.strip().lower(), last_a.strip().lower()) == (
        first_b.strip().lower(),
        last_b.strip().lower(),
    )


def new_reference() -> str:
    """A random 6-digit reference, easy to say aloud in Italian and English."""
    return f"{secrets.randbelow(10**6):06d}"


class _Guest(BaseModel):
    """A guest record in memory."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    first_name: str
    last_name: str
    phone: str
    email: str | None
    language: str


class _Reservation(BaseModel):
    """A reservation record in memory."""

    booking: Booking
    phone: str
    idempotency_key: str
    confirmation_sent_at: datetime | None = None


class InMemoryBookingRepository(InMemoryHotelRepository):
    """The in-memory hotel with bookings, for tests, evals and the CLI.

    Implements both HotelRepository and BookingRepository, so a booking made here
    is seen by count_booked. It tracks room counts, not room numbers.
    """

    def __init__(
        self,
        room_types: list[RoomType],
        rates: list[Rate],
        stays: list[Stay],
        bookings: list[tuple[str, NewBooking]] | None = None,
    ) -> None:
        """Build the hotel with anonymous stays and existing (reference, booking)s."""
        super().__init__(room_types, rates, stays)
        self._guests: dict[str, _Guest] = {}
        self._reservations: list[_Reservation] = []
        for reference, new in bookings or []:
            self._guests.setdefault(
                new.phone,
                _Guest(
                    first_name=new.first_name,
                    last_name=new.last_name,
                    phone=new.phone,
                    email=new.email,
                    language=new.language,
                ),
            )
            self._reservations.append(
                _Reservation(
                    booking=Booking(
                        reference=reference,
                        status="confirmed",
                        first_name=new.first_name,
                        room_type=new.room_type,
                        check_in=new.check_in,
                        check_out=new.check_out,
                        adults=new.adults,
                        total_cents=new.total_cents,
                    ),
                    phone=new.phone,
                    idempotency_key=new.idempotency_key,
                )
            )

    async def count_booked(
        self, room_type: str, check_in: date, check_out: date
    ) -> int:
        """Return seed stays plus confirmed bookings of the type overlapping the stay."""
        booked = await super().count_booked(room_type, check_in, check_out)
        return booked + sum(
            1
            for res in self._reservations
            if res.booking.status == "confirmed"
            and res.booking.room_type == room_type
            and res.booking.check_in < check_out
            and check_in < res.booking.check_out
        )

    async def create_booking(self, new: NewBooking) -> Booking | BookingConflict:
        """Book a room of the type and remember the guest."""
        for res in self._reservations:
            if res.idempotency_key == new.idempotency_key:
                return res.booking
        guest = self._guests.get(new.phone)
        if guest and not same_name(
            guest.first_name, guest.last_name, new.first_name, new.last_name
        ):
            return BookingConflict(reason="phone_belongs_to_other_guest")
        rooms = next(rt.rooms for rt in self._room_types if rt.name == new.room_type)
        if await self.count_booked(new.room_type, new.check_in, new.check_out) >= rooms:
            return BookingConflict(reason="no_availability")
        if guest is None:
            guest = _Guest(
                first_name=new.first_name,
                last_name=new.last_name,
                phone=new.phone,
                email=new.email,
                language=new.language,
            )
            self._guests[new.phone] = guest
        elif new.email:
            guest.email = new.email
        booking = Booking(
            reference=new_reference(),
            status="confirmed",
            first_name=guest.first_name,
            room_type=new.room_type,
            check_in=new.check_in,
            check_out=new.check_out,
            adults=new.adults,
            total_cents=new.total_cents,
        )
        self._reservations.append(
            _Reservation(
                booking=booking, phone=new.phone, idempotency_key=new.idempotency_key
            )
        )
        return booking

    async def find_guest(self, phone: str) -> GuestSummary | None:
        """Find the guest with this phone."""
        guest = self._guests.get(phone)
        if guest is None:
            return None
        return GuestSummary(
            first_name=guest.first_name,
            last_name=guest.last_name,
            has_email=guest.email is not None,
        )

    async def find_guest_contact(self, phone: str) -> GuestContact | None:
        """Find the id, first name and email of the guest with this phone."""
        guest = self._guests.get(phone)
        if guest is None:
            return None
        return GuestContact(
            guest_id=guest.id, first_name=guest.first_name, email=guest.email
        )

    async def get_booking(self, reference: str, last_name: str) -> Booking | None:
        """Find a booking by reference and last name, any case."""
        res = self._find(reference, last_name)
        return res.booking if res else None

    async def cancel_booking(
        self, reference: str, last_name: str, now: datetime
    ) -> Booking | None:
        """Cancel a booking at `now`; an already cancelled one is returned unchanged."""
        res = self._find(reference, last_name)
        if res is None:
            return None
        if res.booking.status == "confirmed":
            res.booking = res.booking.model_copy(
                update={"status": "cancelled", "cancelled_at": now}
            )
            res.confirmation_sent_at = None  # the cancellation email is now due
        return res.booking

    async def modify_booking(
        self, reference: str, last_name: str, change: BookingChange
    ) -> Booking | BookingConflict | None:
        """Apply new values to a confirmed booking, keeping its reference."""
        res = self._find(reference, last_name)
        if res is None or res.booking.status != "confirmed":
            return res.booking if res else None
        old = res.booking
        overlaps_itself = (
            old.room_type == change.room_type
            and old.check_in < change.check_out
            and change.check_in < old.check_out
        )
        booked = await self.count_booked(
            change.room_type, change.check_in, change.check_out
        )
        rooms = next(rt.rooms for rt in self._room_types if rt.name == change.room_type)
        if booked - overlaps_itself >= rooms:
            return BookingConflict(reason="no_availability")
        res.booking = old.model_copy(update=change.model_dump())
        res.confirmation_sent_at = None
        return res.booking

    async def get_confirmation_target(
        self, reference: str, last_name: str
    ) -> ConfirmationTarget | None:
        """Find a booking with its guest's id and email."""
        res = self._find(reference, last_name)
        if res is None:
            return None
        guest = self._guests[res.phone]
        return ConfirmationTarget(
            booking=res.booking, guest_id=guest.id, email=guest.email
        )

    async def claim_confirmation(self, reference: str, now: datetime) -> bool:
        """Mark the confirmation as sent; False if it already was."""
        res = next(r for r in self._reservations if r.booking.reference == reference)
        if res.confirmation_sent_at is not None:
            return False
        res.confirmation_sent_at = now
        return True

    async def release_confirmation(self, reference: str, claimed_at: datetime) -> None:
        """Clear the mark set at `claimed_at`; a newer mark is kept."""
        res = next(r for r in self._reservations if r.booking.reference == reference)
        if res.confirmation_sent_at == claimed_at:
            res.confirmation_sent_at = None

    def _find(self, reference: str, last_name: str) -> _Reservation | None:
        """The reservation with this reference and guest last name, any case."""
        for res in self._reservations:
            guest = self._guests[res.phone]
            if (
                res.booking.reference == reference
                and guest.last_name.lower() == last_name.strip().lower()
            ):
                return res
        return None
