"""Tests for the send_confirmation_email tool."""

import logging
from collections.abc import Coroutine
from datetime import UTC, date, datetime
from email.message import EmailMessage
from typing import Any

import pytest

from src.db.bookings import BookingChange, InMemoryBookingRepository, NewBooking
from src.email.sender import EmailSendError, FakeEmailSender
from src.tools.send_confirmation_email import (
    SendConfirmationEmailError,
    SendConfirmationEmailInput,
    SendConfirmationEmailOk,
    drain_background,
    run_in_background,
    send_confirmation_email,
)
from tests.booking_fixtures import hotel_with_booking

NOW = datetime(2026, 11, 9, 14, 30, tzinfo=UTC)
EMAIL = "ada@guest.example"


class Background:
    """Collects background jobs so a test can run them when it chooses."""

    def __init__(self) -> None:
        self.jobs: list[Coroutine[Any, Any, None]] = []

    def __call__(self, job: Coroutine[Any, Any, None]) -> None:
        self.jobs.append(job)

    async def run(self) -> None:
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            await job


class FailingSender(FakeEmailSender):
    """Gmail is down."""

    async def send(self, message: EmailMessage) -> None:
        raise EmailSendError("Gmail send failed: HTTP 503")


async def _hotel(email: str | None = EMAIL) -> tuple[InMemoryBookingRepository, str]:
    """The fixture hotel plus a booking by Bea Bianchi with this email."""
    repo, _ = await hotel_with_booking()
    booking = await repo.create_booking(
        NewBooking(
            idempotency_key="bea",
            room_type="Suite",
            check_in=date(2026, 12, 20),
            check_out=date(2026, 12, 23),
            adults=3,
            total_cents=90000,
            first_name="Bea",
            last_name="Bianchi",
            phone="+12025550188",
            email=email,
            language="it",
        )
    )
    return repo, booking.reference  # type: ignore[union-attr]


def _inp(reference: str, language: str = "en", last_name: str = "bianchi") -> Any:
    return SendConfirmationEmailInput(
        reference=reference, last_name=last_name, language=language
    )


@pytest.mark.asyncio
async def test_sends_the_confirmation_in_the_call_language() -> None:
    """The guest stored Italian, but this call is in English: English wins."""
    repo, reference = await _hotel()
    sender, background = FakeEmailSender(), Background()

    result = await send_confirmation_email(
        repo, sender, _inp(reference, "en"), NOW, background
    )
    assert result == SendConfirmationEmailOk()
    assert sender.sent == []  # nothing is sent before the reply goes back

    await background.run()
    (msg,) = sender.sent
    assert msg["To"] == EMAIL
    assert reference in msg["Subject"]
    assert "Dear Bea" in msg.get_body(("plain",)).get_content()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_a_spoken_reference_with_spaces_is_found() -> None:
    """References come as spoken digit groups."""
    repo, reference = await _hotel()
    background = Background()
    spoken = f"{reference[:3]} {reference[3:]}"

    result = await send_confirmation_email(
        repo, FakeEmailSender(), _inp(spoken), NOW, background
    )

    await background.run()
    assert result == SendConfirmationEmailOk()


@pytest.mark.asyncio
async def test_a_second_call_sends_nothing() -> None:
    """Retries and repeated calls never send a second email."""
    repo, reference = await _hotel()
    sender, background = FakeEmailSender(), Background()

    await send_confirmation_email(repo, sender, _inp(reference), NOW, background)
    await background.run()
    again = await send_confirmation_email(
        repo, sender, _inp(reference), NOW, background
    )
    await background.run()

    assert again == SendConfirmationEmailOk()
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_after_a_modify_the_updated_booking_is_sent() -> None:
    """modify_booking clears the mark, so the new details go out."""
    repo, reference = await _hotel()
    sender, background = FakeEmailSender(), Background()
    await send_confirmation_email(repo, sender, _inp(reference), NOW, background)
    await background.run()

    await repo.modify_booking(
        reference,
        "Bianchi",
        BookingChange(
            room_type="Suite",
            check_in=date(2026, 12, 20),
            check_out=date(2026, 12, 24),
            adults=3,
            total_cents=120000,
        ),
    )
    await send_confirmation_email(repo, sender, _inp(reference), NOW, background)
    await background.run()

    assert len(sender.sent) == 2
    body = sender.sent[1].get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "Thursday 24 December 2026" in body


@pytest.mark.asyncio
async def test_a_failed_send_is_logged_without_pii_and_can_be_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The caller already heard 'it is on its way', so the failure only logs."""
    repo, reference = await _hotel()
    background = Background()

    with caplog.at_level(logging.WARNING):
        await send_confirmation_email(
            repo, FailingSender(), _inp(reference), NOW, background
        )
        await background.run()

    assert "guest" in caplog.text
    assert EMAIL not in caplog.text and "Bianchi" not in caplog.text
    sender = FakeEmailSender()
    await send_confirmation_email(repo, sender, _inp(reference), NOW, background)
    await background.run()
    assert len(sender.sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", ["name", "reference"])
async def test_a_wrong_name_or_reference_is_not_found(wrong: str) -> None:
    """Same answer for both, so references cannot be probed."""
    repo, reference = await _hotel()
    inp = _inp(reference, last_name="Rossi") if wrong == "name" else _inp("000000")

    result = await send_confirmation_email(
        repo, FakeEmailSender(), inp, NOW, Background()
    )

    assert result == SendConfirmationEmailError(reason="not_found")


@pytest.mark.asyncio
async def test_a_cancelled_booking_gets_no_confirmation() -> None:
    """Confirming a cancelled stay would mislead the guest."""
    repo, reference = await _hotel()
    await repo.cancel_booking(reference, "Bianchi", NOW)

    result = await send_confirmation_email(
        repo, FakeEmailSender(), _inp(reference), NOW, Background()
    )

    assert result == SendConfirmationEmailError(reason="cancelled")


@pytest.mark.asyncio
async def test_no_email_on_file_sends_nothing() -> None:
    """The email is optional at booking."""
    repo, reference = await _hotel(email=None)
    background = Background()

    result = await send_confirmation_email(
        repo, FakeEmailSender(), _inp(reference), NOW, background
    )

    assert result == SendConfirmationEmailError(reason="no_email_on_file")
    assert background.jobs == []


class BrokenSender(FakeEmailSender):
    """Fails with something other than EmailSendError (a bug, a closed client)."""

    async def send(self, message: EmailMessage) -> None:
        raise RuntimeError("client closed")


@pytest.mark.asyncio
async def test_any_failure_in_the_job_releases_the_mark(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Otherwise one unexpected error would block the confirmation for good."""
    repo, reference = await _hotel()
    background = Background()

    with caplog.at_level(logging.WARNING):
        await send_confirmation_email(
            repo, BrokenSender(), _inp(reference), NOW, background
        )
        await background.run()

    assert "RuntimeError" in caplog.text
    sender = FakeEmailSender()
    await send_confirmation_email(repo, sender, _inp(reference), NOW, background)
    await background.run()
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_the_job_emails_the_booking_as_it_is_when_it_runs() -> None:
    """A modify between the reply and the send must not mail stale details."""
    repo, reference = await _hotel()
    sender, background = FakeEmailSender(), Background()
    await send_confirmation_email(repo, sender, _inp(reference), NOW, background)

    await repo.modify_booking(
        reference,
        "Bianchi",
        BookingChange(
            room_type="Suite",
            check_in=date(2026, 12, 20),
            check_out=date(2026, 12, 24),
            adults=3,
            total_cents=120000,
        ),
    )
    await background.run()

    body = sender.sent[0].get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "Thursday 24 December 2026" in body


@pytest.mark.asyncio
async def test_pending_sends_are_awaited_at_shutdown() -> None:
    """The app waits for queued emails before closing the HTTP client and pool."""
    repo, reference = await _hotel()
    sender = FakeEmailSender()
    await send_confirmation_email(repo, sender, _inp(reference), NOW, run_in_background)

    await drain_background(timeout_s=1.0)

    assert len(sender.sent) == 1
