"""The calendar invite for a booking (RFC 5545, sent as an iTIP REQUEST).

REQUEST with the hotel as organizer and the guest as attendee is what makes mail
clients update the same event when a modified booking is sent again: the UID stays
the same and SEQUENCE grows. See docs/external/gmail.md, section 6.
"""

from datetime import UTC, datetime
from typing import Literal

from src.db.bookings import Booking

_MAX_LINE_OCTETS = 75


def _escape(text: str) -> str:
    """Escape a TEXT value: backslash, semicolon, comma and newline."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line at 75 octets without splitting a UTF-8 character."""
    parts: list[str] = []
    current = ""
    for char in line:
        if len((current + char).encode()) > _MAX_LINE_OCTETS:
            parts.append(current)
            current = " "  # a continuation line starts with one space
        current += char
    parts.append(current)
    return "\r\n".join(parts)


def booking_ics(
    booking: Booking,
    *,
    organizer: str,
    attendee: str,
    summary: str,
    location: str,
    now: datetime,
    method: Literal["REQUEST", "CANCEL"] = "REQUEST",
) -> bytes:
    """Build the invite for a stay as an all-day event from check-in to check-out.

    Args:
        booking: The booking; check_out is exclusive, as DTEND is.
        organizer: The hotel's sending address.
        attendee: The guest's email.
        summary: Event title, in the guest's language.
        location: Hotel address.
        now: Send time; it sets DTSTAMP and SEQUENCE, so each send supersedes
            the last one.
        method: REQUEST adds or updates the event; CANCEL removes it (same UID).

    Returns:
        The .ics file as UTF-8 bytes with CRLF line endings.
    """
    domain = organizer.rsplit("@", 1)[1]
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Hotel Voice Agent//Booking//EN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:booking-{booking.reference}@{domain}",
        f"DTSTAMP:{now.astimezone(UTC):%Y%m%dT%H%M%SZ}",
        f"SEQUENCE:{int(now.timestamp())}",
        f"DTSTART;VALUE=DATE:{booking.check_in:%Y%m%d}",
        f"DTEND;VALUE=DATE:{booking.check_out:%Y%m%d}",
        f"SUMMARY:{_escape(summary)}",
        f"LOCATION:{_escape(location)}",
        f"ORGANIZER:mailto:{organizer}",
        f"ATTENDEE;RSVP=FALSE:mailto:{attendee}",
        "STATUS:CANCELLED" if method == "CANCEL" else "STATUS:CONFIRMED",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode()
