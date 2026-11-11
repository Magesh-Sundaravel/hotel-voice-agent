"""The booking confirmation email, in Italian or English, with its invite."""

from datetime import date, datetime
from email.message import EmailMessage
from typing import Literal

from src.db.bookings import Booking
from src.email.ics import booking_ics

HOTEL_NAME = "Hotel Corte Aurelia"

_WEEKDAYS = {
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "it": ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"),
}  # fmt: skip
_MONTHS = {
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
    "it": (
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ),
}  # fmt: skip

_ADULTS = {"en": ("adult", "adults"), "it": ("adulto", "adulti")}

_TEXT = {
    "en": {
        "subject": "Your booking at {hotel}, reference {reference}",
        "summary": "{hotel}, booking {reference}",
        "location": "Via della Lupa 12, Rome",
        "body": (
            "Dear {first_name},\n\n"
            "thank you for booking with {hotel}. Here are your booking details.\n\n"
            "Reference: {reference}\n"
            "Room: {room_type}\n"
            "Arrival: {check_in}, check-in from 15:00\n"
            "Departure: {check_out}, check-out by 12:00\n"
            "Nights: {nights}\n"
            "Guests: {adults} {adults_word}\n"
            "Total: €{total}, breakfast included\n\n"
            "Cancellation is free until 48 hours before check-in. To change or "
            "cancel, call us with your reference and last name.\n\n"
            "The attached invite adds your stay to your calendar.\n\n"
            "{hotel}\n"
            "Via della Lupa 12, Rome\n"
        ),
    },
    "it": {
        "subject": "La sua prenotazione al {hotel}, codice {reference}",
        "summary": "{hotel}, prenotazione {reference}",
        "location": "Via della Lupa 12, Roma",
        "body": (
            "Gentile {first_name},\n\n"
            "grazie per aver prenotato al {hotel}. Ecco i dettagli della sua "
            "prenotazione.\n\n"
            "Codice: {reference}\n"
            "Camera: {room_type}\n"
            "Arrivo: {check_in}, check-in dalle 15:00\n"
            "Partenza: {check_out}, check-out entro le 12:00\n"
            "Notti: {nights}\n"
            "Ospiti: {adults} {adults_word}\n"
            "Totale: {total} €, colazione inclusa\n\n"
            "La cancellazione è gratuita fino a 48 ore prima del check-in. Per "
            "modificare o cancellare, ci chiami con il codice e il cognome.\n\n"
            "L'invito allegato aggiunge il soggiorno al suo calendario.\n\n"
            "{hotel}\n"
            "Via della Lupa 12, Roma\n"
        ),
    },
}


_CANCEL_TEXT = {
    "en": {
        "subject": "Your booking at {hotel} is cancelled, reference {reference}",
        "body": (
            "Dear {first_name},\n\n"
            "your booking {reference} at {hotel} is cancelled.\n\n"
            "Room: {room_type}\n"
            "Arrival: {check_in}\n"
            "Departure: {check_out}\n\n"
            "{policy}"
            "The attached update removes the stay from your calendar.\n\n"
            "{hotel}\n"
            "Via della Lupa 12, Rome\n"
        ),
        "free": "There is nothing to pay for this cancellation.\n\n",
        "late": (
            "As it was cancelled less than 48 hours before check-in, the "
            "cancellation policy charge may apply.\n\n"
        ),
    },
    "it": {
        "subject": "La sua prenotazione al {hotel} è cancellata, codice {reference}",
        "body": (
            "Gentile {first_name},\n\n"
            "la sua prenotazione {reference} al {hotel} è stata cancellata.\n\n"
            "Camera: {room_type}\n"
            "Arrivo: {check_in}\n"
            "Partenza: {check_out}\n\n"
            "{policy}"
            "L'aggiornamento allegato rimuove il soggiorno dal suo calendario.\n\n"
            "{hotel}\n"
            "Via della Lupa 12, Roma\n"
        ),
        "free": "Per questa cancellazione non c'è nulla da pagare.\n\n",
        "late": (
            "Poiché è stata cancellata meno di 48 ore prima del check-in, potrebbe "
            "essere applicata la penale prevista dalla politica di cancellazione.\n\n"
        ),
    },
}


def _date_words(day: date, language: Literal["it", "en"]) -> str:
    """A date as a person writes it: 'Thursday 10 December 2026'."""
    weekday = _WEEKDAYS[language][day.weekday()]
    return f"{weekday} {day.day} {_MONTHS[language][day.month - 1]} {day.year}"


def confirmation_message(
    booking: Booking,
    *,
    to: str,
    sender: str,
    language: Literal["it", "en"],
    now: datetime,
) -> EmailMessage:
    """Build the confirmation email with the stay attached as a calendar invite.

    Args:
        booking: The confirmed booking.
        to: The guest's email.
        sender: The hotel's sending address.
        language: The language of the call.
        now: Send time, for the invite's DTSTAMP and SEQUENCE.

    Returns:
        A plain-text email with `booking.ics` attached.
    """
    text = _TEXT[language]
    fields = {
        "hotel": HOTEL_NAME,
        "reference": booking.reference,
        "first_name": booking.first_name,
        "room_type": booking.room_type,
        "check_in": _date_words(booking.check_in, language),
        "check_out": _date_words(booking.check_out, language),
        "nights": (booking.check_out - booking.check_in).days,
        "adults": booking.adults,
        "adults_word": _ADULTS[language][booking.adults != 1],
        "total": booking.total_cents // 100,
    }
    msg = EmailMessage()
    msg["From"] = f"{HOTEL_NAME} <{sender}>"
    msg["To"] = to
    msg["Subject"] = text["subject"].format(**fields)
    msg.set_content(text["body"].format(**fields))
    invite = booking_ics(
        booking,
        organizer=sender,
        attendee=to,
        summary=text["summary"].format(**fields),
        location=text["location"],
        now=now,
    )
    msg.add_attachment(
        invite,
        maintype="text",
        subtype="calendar",
        filename="booking.ics",
        params={"method": "REQUEST", "charset": "UTF-8"},
    )
    return msg


def cancellation_message(
    booking: Booking,
    *,
    to: str,
    sender: str,
    language: Literal["it", "en"],
    now: datetime,
    late: bool,
) -> EmailMessage:
    """Build the cancellation email, with an update that removes the calendar event.

    Args:
        booking: The cancelled booking.
        to: The guest's email.
        sender: The hotel's sending address.
        language: The language of the call.
        now: Send time, for the update's DTSTAMP and SEQUENCE.
        late: Cancelled inside 48 hours of check-in; the policy charge may apply.
            No amount is ever named.

    Returns:
        A plain-text email with `booking.ics` (METHOD:CANCEL, same UID) attached.
    """
    text = _CANCEL_TEXT[language]
    fields = {
        "hotel": HOTEL_NAME,
        "reference": booking.reference,
        "first_name": booking.first_name,
        "room_type": booking.room_type,
        "check_in": _date_words(booking.check_in, language),
        "check_out": _date_words(booking.check_out, language),
        "policy": text["late"] if late else text["free"],
    }
    msg = EmailMessage()
    msg["From"] = f"{HOTEL_NAME} <{sender}>"
    msg["To"] = to
    msg["Subject"] = text["subject"].format(**fields)
    msg.set_content(text["body"].format(**fields))
    update = booking_ics(
        booking,
        organizer=sender,
        attendee=to,
        summary=_TEXT[language]["summary"].format(**fields),
        location=_TEXT[language]["location"],
        now=now,
        method="CANCEL",
    )
    msg.add_attachment(
        update,
        maintype="text",
        subtype="calendar",
        filename="booking.ics",
        params={"method": "CANCEL", "charset": "UTF-8"},
    )
    return msg
