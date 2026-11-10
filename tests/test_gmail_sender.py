"""Tests for GmailSender against a fake Google, using httpx.MockTransport."""

import base64
import json
from email import message_from_bytes
from email.message import EmailMessage

import httpx
import pytest

from src.email.sender import EmailSendError, GmailSender

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _message() -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = "ada@guest.example"
    msg["Subject"] = "Booking 482913"
    msg.set_content("Hello")
    return msg


class FakeGoogle:
    """Answers the token and send endpoints and records every request."""

    def __init__(self, token_status: int = 200, send_status: int = 200) -> None:
        self.token_status = token_status
        self.send_status = send_status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == TOKEN_URL:
            body = {"access_token": f"tok{len(self.requests)}", "expires_in": 3600}
            return httpx.Response(self.token_status, json=body)
        if str(request.url) == SEND_URL:
            return httpx.Response(self.send_status, json={"id": "m1"})
        return httpx.Response(404)


def _sender(google: FakeGoogle, clock: list[float]) -> GmailSender:
    return GmailSender(
        httpx.AsyncClient(transport=httpx.MockTransport(google)),
        address="reception@hotel.example",
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
        clock=lambda: clock[0],
    )


@pytest.mark.asyncio
async def test_refreshes_a_token_then_sends_the_raw_message() -> None:
    """The refresh token buys an access token; the message goes as base64url."""
    google = FakeGoogle()

    await _sender(google, [0.0]).send(_message())

    token_req, send_req = google.requests
    form = dict(x.split("=") for x in token_req.content.decode().split("&"))
    assert form == {
        "client_id": "cid",
        "client_secret": "csecret",
        "grant_type": "refresh_token",
        "refresh_token": "rtoken",
    }
    assert send_req.headers["Authorization"] == "Bearer tok1"
    raw = json.loads(send_req.content)["raw"]
    sent = message_from_bytes(base64.urlsafe_b64decode(raw))
    assert sent["Subject"] == "Booking 482913"


@pytest.mark.asyncio
async def test_reuses_the_token_until_it_is_about_to_expire() -> None:
    """One refresh per hour, not per email."""
    google = FakeGoogle()
    clock = [0.0]
    sender = _sender(google, clock)

    await sender.send(_message())
    clock[0] = 3000.0
    await sender.send(_message())
    clock[0] = 3590.0
    await sender.send(_message())

    urls = [str(r.url) for r in google.requests]
    assert urls == [TOKEN_URL, SEND_URL, SEND_URL, TOKEN_URL, SEND_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize(("token_status", "send_status"), [(400, 200), (200, 403)])
async def test_a_google_error_raises_email_send_error(
    token_status: int, send_status: int
) -> None:
    """A revoked token or a refused send is one error type for the caller."""
    google = FakeGoogle(token_status=token_status, send_status=send_status)

    with pytest.raises(EmailSendError):
        await _sender(google, [0.0]).send(_message())


@pytest.mark.asyncio
async def test_a_network_error_raises_email_send_error() -> None:
    """Timeouts and connection errors do not leak httpx types."""

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    sender = GmailSender(
        httpx.AsyncClient(transport=httpx.MockTransport(fail)),
        address="reception@hotel.example",
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )

    with pytest.raises(EmailSendError):
        await sender.send(_message())


@pytest.mark.asyncio
async def test_a_malformed_token_response_raises_email_send_error() -> None:
    """A 200 without an access token is a send failure, not a KeyError."""

    def odd(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    sender = GmailSender(
        httpx.AsyncClient(transport=httpx.MockTransport(odd)),
        address="reception@hotel.example",
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )

    with pytest.raises(EmailSendError):
        await sender.send(_message())
