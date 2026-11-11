"""Tests for the reception message and the follow-up email."""

import pytest

from src.email.followup import followup_message, reception_message


def _reception(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "hotel_inbox": "reception@hotel.example",
        "first_name": "Ada",
        "last_name": "Testa",
        "message": "Would like a quiet room away from the lift.",
        "language": "en",
        "phone": "+12025550199",
        "email": None,
        "call_id": "conv-1",
    }
    fields.update(overrides)
    return fields


def test_the_reception_message_goes_to_the_hotel_inbox() -> None:
    """Staff get who called, how to reach them and what they want."""
    msg = reception_message(**_reception())  # type: ignore[arg-type]

    assert msg["To"] == "reception@hotel.example"
    assert "Ada Testa" in msg["Subject"]
    body = msg.get_content()
    assert "Would like a quiet room away from the lift." in body
    assert "+12025550199" in body
    assert "English" in body
    assert "conv-1" in body
    assert msg["Reply-To"] is None


def test_a_caller_email_becomes_the_reply_to() -> None:
    """Reception can answer the caller straight from the message."""
    msg = reception_message(**_reception(email="ada@guest.example", phone=None))  # type: ignore[arg-type]

    assert msg["Reply-To"] == "ada@guest.example"
    assert "ada@guest.example" in msg.get_content()


def test_names_cannot_inject_headers() -> None:
    """The model writes the name, so a line break must not reach a header."""
    msg = reception_message(**_reception(first_name="Ada\r\nBcc: x@evil.example"))  # type: ignore[arg-type]

    assert "\n" not in msg["Subject"]
    assert msg["Bcc"] is None


@pytest.mark.parametrize(
    ("language", "greeting", "topic_word"),
    [("en", "Dear Ada", "booking"), ("it", "Gentile Ada", "prenotazione")],
)
def test_the_followup_is_in_the_callers_language(
    language: str, greeting: str, topic_word: str
) -> None:
    """The guest gets an apology and an invitation to reply, never a callback."""
    msg = followup_message(
        to="ada@guest.example",
        sender="reception@hotel.example",
        first_name="Ada",
        topic="booking",
        language=language,  # type: ignore[arg-type]
    )

    assert msg["To"] == "ada@guest.example"
    body = msg.get_content()
    assert body.startswith(greeting)
    assert topic_word in body
    assert "Hotel Corte Aurelia" in msg["From"]
    assert "call you" not in body and "richiamer" not in body


def test_the_followup_without_a_name_is_still_polite() -> None:
    """A caller who gave only an email gets a neutral greeting."""
    msg = followup_message(
        to="ada@guest.example",
        sender="reception@hotel.example",
        first_name=None,
        topic="information",
        language="en",
    )

    assert msg.get_content().startswith("Dear guest")
