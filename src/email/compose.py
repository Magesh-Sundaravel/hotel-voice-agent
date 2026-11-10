"""The booking confirmation email, in Italian or English, with its invite."""

from datetime import date, datetime
from email.message import EmailMessage
from typing import Literal

from src.db.bookings import Booking
from src.email.ics import booking_ics

HOTEL_NAME = "Sina Bernini Bristol"

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
        "location": "Piazza Barberini 23, Rome",
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
            "Piazza Barberini 23, Rome\n"
        ),
    },
    "it": {
        "subject": "La sua prenotazione al {hotel}, codice {reference}",
        "summary": "{hotel}, prenotazione {reference}",
        "location": "Piazza Barberini 23, Roma",
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
            "Piazza Barberini 23, Roma\n"
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
