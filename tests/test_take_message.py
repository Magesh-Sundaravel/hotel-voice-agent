"""Tests for the take_message tool."""

import logging
from typing import Any
from uuid import uuid4

import pytest

from src.email.sender import FakeEmailSender
from src.tools.context import CallContext
from src.tools.take_message import (
    TakeMessageError,
    TakeMessageInput,
    TakeMessageOk,
    take_message,
)
from tests.test_send_confirmation_email import Background, FailingSender

CALLER = "+12025550199"


def _inp(**overrides: object) -> TakeMessageInput:
    fields: dict[str, Any] = {
        "first_name": "Ada",
        "last_name": "Testa",
        "message": "Would like to speak to the manager about a late arrival.",
        "language": "en",
    }
    fields.update(overrides)
    return TakeMessageInput.model_validate(fields)


async def _take(
    inp: TakeMessageInput,
    caller_phone: str | None = CALLER,
    call_id: str | None = None,
    sender: FakeEmailSender | None = None,
) -> tuple[TakeMessageOk | TakeMessageError, FakeEmailSender]:
    sender = sender or FakeEmailSender()
    background = Background()
    result = await take_message(
        sender,
        CallContext(
            call_id=call_id or f"conv-{uuid4().hex}", caller_phone=caller_phone
        ),
        inp,
        spawn=background,
    )
    await background.run()
    return result, sender


@pytest.mark.asyncio
async def test_the_message_reaches_the_hotel_inbox() -> None:
    """Reception gets the message, with the caller ID to reach the caller."""
    result, sender = await _take(_inp())

    assert result == TakeMessageOk()
    (msg,) = sender.sent
    assert msg["To"] == sender.address
    assert CALLER in msg.get_content()
    assert "late arrival" in msg.get_content()


@pytest.mark.asyncio
async def test_a_given_phone_replaces_the_caller_id() -> None:
    """The caller may want to be reached on another number."""
    result, sender = await _take(_inp(phone="+390612345678"))

    assert result.ok is True
    assert "+390612345678" in sender.sent[0].get_content()
    assert CALLER not in sender.sent[0].get_content()


@pytest.mark.asyncio
async def test_an_email_is_enough_when_the_number_is_withheld() -> None:
    """With no caller ID, an email still lets reception reply."""
    result, sender = await _take(_inp(email="ada@guest.example"), caller_phone=None)

    assert result.ok is True
    assert sender.sent[0]["Reply-To"] == "ada@guest.example"


@pytest.mark.asyncio
async def test_no_way_to_reach_the_caller_is_refused() -> None:
    """A message reception cannot answer is useless; the agent asks for a contact."""
    result, sender = await _take(_inp(), caller_phone=None)

    assert result == TakeMessageError(reason="contact_required")
    assert sender.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("phone", "06 1234 5678", "invalid_phone"),
        ("email", "ada at guest", "invalid_email"),
    ],
)
async def test_a_bad_contact_is_refused(field: str, value: str, reason: str) -> None:
    """The agent asks again rather than passing on a contact nobody can use."""
    result, sender = await _take(_inp(**{field: value}))

    assert result == TakeMessageError(reason=reason)
    assert sender.sent == []


@pytest.mark.asyncio
async def test_a_retried_call_sends_one_message() -> None:
    """ElevenLabs retries are undocumented, so the same message goes once."""
    sender = FakeEmailSender()
    await _take(_inp(), call_id="conv-retry", sender=sender)
    again, _ = await _take(_inp(), call_id="conv-retry", sender=sender)

    assert again.ok is True
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_a_failed_send_is_logged_without_pii(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The caller already heard it was passed on; the log has the call_id only."""
    with caplog.at_level(logging.WARNING, logger="src.tools.once"):
        result, _ = await _take(_inp(), call_id="conv-fail", sender=FailingSender())

    assert result.ok is True
    assert "conv-fail" in caplog.text
    assert "Testa" not in caplog.text and CALLER not in caplog.text


@pytest.mark.asyncio
async def test_a_failed_send_can_be_retried() -> None:
    """A message lost to a Gmail outage must not block the retry."""
    await _take(_inp(), call_id="conv-retry-after-fail", sender=FailingSender())
    result, sender = await _take(_inp(), call_id="conv-retry-after-fail")

    assert result.ok is True
    assert len(sender.sent) == 1
