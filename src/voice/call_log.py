"""What each tool call adds to the call log (src/db/calls.py)."""

from pydantic import BaseModel

from src.db.calls import CallEvent, Outcome

# Tools whose success changes the call's outcome, and the booking they return.
_OUTCOMES: dict[str, Outcome] = {
    "create_booking": "booked",
    "modify_booking": "modified",
    "cancel_booking": "cancelled",
}


def call_event(
    call_id: str, tool: str, arguments: dict[str, object], result: BaseModel
) -> CallEvent:
    """Turn one tool call into a call log event.

    Every call opens the entry; a successful booking write sets the outcome and the
    booking. The language is taken from any tool that was given one.

    Args:
        call_id: The ElevenLabs conversation id.
        tool: The tool's name.
        arguments: The arguments the model sent.
        result: What the tool returned.

    Returns:
        The event to record. It never carries a name, phone or email.
    """
    language = arguments.get("language")
    event = CallEvent(
        call_id=call_id,
        language=language if language in ("it", "en") else None,  # type: ignore[arg-type]
    )
    if not getattr(result, "ok", False):
        return event
    if tool in _OUTCOMES:
        event.outcome = _OUTCOMES[tool]
        event.reference = getattr(result, "reference", None)
    return event
