"""The call log: one row per call, built up as the call's tools run.

Only ids and flags are stored, never names, phones, emails or transcripts
(docs/data-model.md, call_log).
"""

from typing import Literal, Protocol

from pydantic import BaseModel

Outcome = Literal["booked", "modified", "cancelled", "message", "followup"]


class CallLogError(Exception):
    """The call log could not be written; callers log it and carry on."""


class CallEvent(BaseModel):
    """What one tool call adds to its call's entry. Unset fields change nothing."""

    call_id: str
    language: Literal["it", "en"] | None = None
    outcome: Outcome | None = None
    # The booking the call touched; stored as the reservation and its guest.
    reference: str | None = None
    needs_followup: bool = False
    followup_reason: str | None = None


class CallLogEntry(BaseModel):
    """A call's entry as stored so far."""

    call_id: str
    language: Literal["it", "en"] | None
    outcome: Outcome | None
    reference: str | None
    needs_followup: bool
    followup_reason: str | None


class CallLogRepository(Protocol):
    """Storage for the call log."""

    async def record(self, event: CallEvent) -> None:
        """Create the call's entry, or merge the event into it.

        A field the event leaves unset keeps its stored value; a set one replaces
        it. needs_followup, once true, stays true.

        Raises:
            CallLogError: The entry could not be written.
        """
        ...

    async def get(self, call_id: str) -> CallLogEntry | None:
        """Return the call's entry, or None if no tool has run in it."""
        ...


class InMemoryCallLogRepository:
    """Call log kept in memory, for tests and the CLI.

    Unlike Postgres, it keeps a reference without checking that the booking exists.
    """

    def __init__(self) -> None:
        """Start with no calls."""
        self._entries: dict[str, CallLogEntry] = {}

    async def record(self, event: CallEvent) -> None:
        """Create or merge the call's entry (see CallLogRepository.record)."""
        old = self._entries.get(event.call_id)
        self._entries[event.call_id] = CallLogEntry(
            call_id=event.call_id,
            language=event.language or (old.language if old else None),
            outcome=event.outcome or (old.outcome if old else None),
            reference=event.reference or (old.reference if old else None),
            needs_followup=event.needs_followup
            or (old.needs_followup if old else False),
            followup_reason=event.followup_reason
            or (old.followup_reason if old else None),
        )

    async def get(self, call_id: str) -> CallLogEntry | None:
        """Return the call's entry, or None."""
        return self._entries.get(call_id)
