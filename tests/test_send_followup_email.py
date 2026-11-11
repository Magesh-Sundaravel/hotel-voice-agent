"""Tests for the send_followup_email tool."""

import logging
from typing import Any
from uuid import uuid4

import pytest

from src.db.bookings import InMemoryBookingRepository
from src.db.seed import seed_repository
from src.email.sender import FakeEmailSender
from src.tools.context import CallContext
from src.tools.send_followup_email import (
    SendFollowupEmailError,
    SendFollowupEmailInput,
    SendFollowupEmailOk,
    send_followup_email,
)
from tests.test_send_confirmation_email import Background, FailingSender

GIULIA = "+12025550101"  # seed guest with an email on file
MARCO = "+12025550103"  # seed guest without one
UNKNOWN = "+12025550177"


def _inp(**overrides: object) -> SendFollowupEmailInput:
    fields: dict[str, Any] = {"topic": "booking", "language": "it"}
    fields.update(overrides)
    return SendFollowupEmailInput.model_validate(fields)


async def _send(
    inp: SendFollowupEmailInput,
    caller_phone: str | None = GIULIA,
    call_id: str | None = None,
    sender: FakeEmailSender | None = None,
    repo: InMemoryBookingRepository | None = None,
) -> tuple[SendFollowupEmailOk | SendFollowupEmailError, FakeEmailSender]:
    sender = sender or FakeEmailSender()
    background = Background()
    result = await send_followup_email(
        repo or seed_repository(),
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
async def test_the_email_on_file_is_used() -> None:
    """A returning caller gets it at their stored address, greeted by name."""
    result, sender = await _send(_inp())

    assert result == SendFollowupEmailOk()
    (msg,) = sender.sent
    assert msg["To"] == "giulia.rossi@example.com"
    assert msg.get_content().startswith("Gentile Giulia")


@pytest.mark.asyncio
async def test_a_spelled_email_wins_over_the_one_on_file() -> None:
    """The caller may want it somewhere else."""
    result, sender = await _send(_inp(email="giulia@work.example"))

    assert result.ok is True
    assert sender.sent[0]["To"] == "giulia@work.example"


@pytest.mark.asyncio
@pytest.mark.parametrize("phone", [MARCO, UNKNOWN, None])
async def test_no_email_anywhere_asks_for_one(phone: str | None) -> None:
    """No email on file, no match, or a withheld number: ask the caller to spell one."""
    result, sender = await _send(_inp(), caller_phone=phone)

    assert result == SendFollowupEmailError(reason="email_required")
    assert sender.sent == []


@pytest.mark.asyncio
async def test_a_spelled_email_works_without_a_caller_id() -> None:
    """A withheld number is fine once the caller gives an email; greeting is neutral."""
    result, sender = await _send(
        _inp(email="ada@guest.example", language="en"), caller_phone=None
    )

    assert result.ok is True
    assert sender.sent[0].get_content().startswith("Dear guest")


@pytest.mark.asyncio
async def test_a_bad_email_is_refused() -> None:
    """The agent spells it back again."""
    result, sender = await _send(_inp(email="giulia at work"))

    assert result == SendFollowupEmailError(reason="invalid_email")
    assert sender.sent == []


@pytest.mark.asyncio
async def test_one_followup_per_call() -> None:
    """A second call in the same phone call sends nothing more."""
    sender = FakeEmailSender()
    await _send(_inp(), call_id="conv-fu-once", sender=sender)
    again, _ = await _send(_inp(), call_id="conv-fu-once", sender=sender)

    assert again.ok is True
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_a_failed_send_is_logged_without_pii(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only the call_id is logged."""
    with caplog.at_level(logging.WARNING, logger="src.tools.once"):
        result, _ = await _send(_inp(), call_id="conv-fu-fail", sender=FailingSender())

    assert result.ok is True
    assert "conv-fu-fail" in caplog.text
    assert "giulia" not in caplog.text.lower() and GIULIA not in caplog.text


@pytest.mark.asyncio
async def test_a_corrected_email_gets_the_followup() -> None:
    """If the first address was misheard, the corrected one still gets the email."""
    sender = FakeEmailSender()
    await _send(_inp(email="giulia@wrok.example"), call_id="conv-fix", sender=sender)
    await _send(_inp(email="giulia@work.example"), call_id="conv-fix", sender=sender)

    assert [m["To"] for m in sender.sent] == [
        "giulia@wrok.example",
        "giulia@work.example",
    ]


@pytest.mark.asyncio
async def test_a_failed_send_can_be_retried() -> None:
    """A follow-up lost to a Gmail outage must not block the retry."""
    await _send(_inp(), call_id="conv-fu-retry", sender=FailingSender())
    result, sender = await _send(_inp(), call_id="conv-fu-retry")

    assert result.ok is True
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_a_trailing_newline_is_not_a_valid_email() -> None:
    """It would break the To header later and surface as tool_error."""
    result, _ = await _send(_inp(email="giulia@work.example\n"))

    assert result == SendFollowupEmailError(reason="invalid_email")
