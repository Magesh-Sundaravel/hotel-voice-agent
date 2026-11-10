"""Sending email: the EmailSender protocol, Gmail over httpx, and a fake.

Gmail facts (endpoints, token refresh, base64url `raw`) are in
docs/external/gmail.md.
"""

import base64
import time
from collections.abc import Callable
from email import policy
from email.message import EmailMessage
from typing import Protocol

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
# Refresh this long before Google's expiry, so a token never dies mid-request.
_TOKEN_MARGIN_S = 60
# Sends run in the background, so this guards against hangs, not the call budget.
_TIMEOUT_S = 10.0


class EmailSendError(Exception):
    """The email could not be sent. The message never contains PII."""


class EmailSender(Protocol):
    """Sends one email from the hotel's address."""

    address: str

    async def send(self, message: EmailMessage) -> None:
        """Send the message, or raise EmailSendError."""
        ...


class FakeEmailSender:
    """Keeps sent emails in memory, for tests, evals and the CLI."""

    def __init__(self, address: str = "reception@hotel.example") -> None:
        """Start with no emails sent.

        Args:
            address: The From address the tool will use.
        """
        self.address = address
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        """Record the message."""
        self.sent.append(message)


class GmailSender:
    """Sends through the Gmail API with a refresh token, no human in the loop."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        address: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the OAuth client and the hotel account's refresh token.

        Args:
            http: Shared HTTP client.
            address: The Gmail account the refresh token belongs to.
            client_id: OAuth client ID.
            client_secret: OAuth client secret.
            refresh_token: Obtained once by manual consent (scope gmail.send).
            clock: Seconds, for token expiry (tests).
        """
        self.address = address
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    async def _access_token(self) -> str:
        """Return a cached access token, refreshing it near expiry."""
        if self._token and self._clock() < self._expires_at:
            return self._token
        response = await self._http.post(
            TOKEN_URL,
            timeout=_TIMEOUT_S,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
        )
        if response.status_code != 200:
            raise EmailSendError(f"token refresh failed: HTTP {response.status_code}")
        try:
            body = response.json()
            token = str(body["access_token"])
            expires_in = float(body["expires_in"])
        except (ValueError, KeyError, TypeError) as exc:
            raise EmailSendError("token response malformed") from exc
        self._token = token
        self._expires_at = self._clock() + expires_in - _TOKEN_MARGIN_S
        return token

    async def send(self, message: EmailMessage) -> None:
        """Send the message as base64url `raw`.

        Raises:
            EmailSendError: On a token, HTTP or network failure.
        """
        try:
            token = await self._access_token()
            raw = base64.urlsafe_b64encode(message.as_bytes(policy=policy.SMTP))
            response = await self._http.post(
                SEND_URL,
                timeout=_TIMEOUT_S,
                headers={"Authorization": f"Bearer {token}"},
                json={"raw": raw.decode()},
            )
        except httpx.HTTPError as exc:
            raise EmailSendError(f"Gmail unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise EmailSendError(f"Gmail send failed: HTTP {response.status_code}")
