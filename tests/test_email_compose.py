"""Tests for the confirmation email and its calendar invite."""

from datetime import UTC, date, datetime
from email import message_from_bytes, policy

from src.db.bookings import Booking
from src.email.compose import confirmation_message
from src.email.ics import booking_ics

NOW = datetime(2026, 11, 9, 14, 30, tzinfo=UTC)
BOOKING = Booking(
    reference="482913",
    status="confirmed",
    first_name="Ada",
    room_type="Executive Deluxe Piazza View",
    check_in=date(2026, 12, 10),
    check_out=date(2026, 12, 12),
    adults=2,
    total_cents=64000,
)


def _ics() -> str:
    return booking_ics(
        BOOKING,
        organizer="reception@hotel.example",
        attendee="ada@guest.example",
        summary="Sina Bernini Bristol, booking 482913; Executive Deluxe Piazza View",
        location="Piazza Barberini 23, Rome",
        now=NOW,
    ).decode()


def test_ics_is_a_request_invite_for_the_whole_stay() -> None:
    """REQUEST with organizer and attendee, so a later send updates the event."""
    ics = _ics()

    assert "METHOD:REQUEST\r\n" in ics
    assert "UID:booking-482913@hotel.example\r\n" in ics
    assert "DTSTART;VALUE=DATE:20261210\r\n" in ics
    assert "DTEND;VALUE=DATE:20261212\r\n" in ics
    assert "DTSTAMP:20261109T143000Z\r\n" in ics
    assert f"SEQUENCE:{int(NOW.timestamp())}\r\n" in ics
    assert "ORGANIZER:mailto:reception@hotel.example\r\n" in ics
    assert "ATTENDEE;RSVP=FALSE:mailto:ada@guest.example\r\n" in ics


def test_ics_lines_end_in_crlf_are_folded_and_escaped() -> None:
    """RFC 5545: CRLF, at most 75 octets per line, commas and semicolons escaped."""
    ics = _ics()
    lines = ics.split("\r\n")

    assert ics.endswith("END:VCALENDAR\r\n")
    assert "\n" not in ics.replace("\r\n", "")
    assert all(len(line.encode()) <= 75 for line in lines)
    unfolded = ics.replace("\r\n ", "")
    assert (
        "SUMMARY:Sina Bernini Bristol\\, booking 482913\\; Executive Deluxe Piazza "
        "View\r\n" in unfolded
    )


def test_folding_never_splits_a_multibyte_character() -> None:
    """Accented Italian text must stay valid UTF-8 on every line."""
    ics = booking_ics(
        BOOKING,
        organizer="reception@hotel.example",
        attendee="ada@guest.example",
        summary="è" * 60,
        location="Roma",
        now=NOW,
    )

    for line in ics.split(b"\r\n"):
        line.decode()  # raises if a character was cut in half
        assert len(line) <= 75


def test_english_email_lists_the_booking() -> None:
    """Dates in words, the price in euros, times and the cancellation policy."""
    msg = confirmation_message(
        BOOKING,
        to="ada@guest.example",
        sender="reception@hotel.example",
        language="en",
        now=NOW,
    )
    body = msg.get_body(("plain",)).get_content()  # type: ignore[union-attr]

    assert msg["To"] == "ada@guest.example"
    assert "reception@hotel.example" in msg["From"]
    assert "482913" in msg["Subject"]
    for text in [
        "Dear Ada",
        "482913",
        "Executive Deluxe Piazza View",
        "Thursday 10 December 2026",
        "Saturday 12 December 2026",
        "15:00",
        "12:00",
        "2 adults",
        "€640",
        "48 hours",
    ]:
        assert text in body, text


def test_italian_email_uses_italian_words() -> None:
    """The email follows the language of the call."""
    msg = confirmation_message(
        BOOKING,
        to="ada@guest.example",
        sender="reception@hotel.example",
        language="it",
        now=NOW,
    )
    body = msg.get_body(("plain",)).get_content()  # type: ignore[union-attr]

    assert "prenotazione" in msg["Subject"]
    for text in ["Gentile Ada", "giovedì 10 dicembre 2026", "2 adulti", "640 €"]:
        assert text in body, text


def test_invite_survives_serialisation_with_crlf() -> None:
    """The email library must not turn the invite's CRLF into LF."""
    msg = confirmation_message(
        BOOKING,
        to="ada@guest.example",
        sender="reception@hotel.example",
        language="en",
        now=NOW,
    )
    parsed = message_from_bytes(msg.as_bytes(), policy=policy.default)
    invite = next(p for p in parsed.iter_attachments())

    assert invite.get_content_type() == "text/calendar"
    assert invite.get_param("method") == "REQUEST"
    assert invite.get_filename() == "booking.ics"
    assert "METHOD:REQUEST\r\n" in invite.get_payload(decode=True).decode()


def test_one_adult_is_singular() -> None:
    """'1 adult' and '1 adulto', not '1 adults'."""
    single = BOOKING.model_copy(update={"adults": 1})

    for language, word in [("en", "1 adult\n"), ("it", "1 adulto\n")]:
        msg = confirmation_message(
            single,
            to="ada@guest.example",
            sender="reception@hotel.example",
            language=language,  # type: ignore[arg-type]
            now=NOW,
        )
        assert word in msg.get_body(("plain",)).get_content()  # type: ignore[union-attr]
