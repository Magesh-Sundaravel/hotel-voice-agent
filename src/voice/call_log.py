"""What each tool call adds to the call log (src/db/calls.py)."""

from pydantic import BaseModel

from src.db.calls import CallEvent, Outcome
from src.voice.call_language import Language

# Tools whose success changes the call's outcome, and the booking they return.
_OUTCOMES: dict[str, Outcome] = {
    "create_booking": "booked",
    "modify_booking": "modified",
    "cancel_booking": "cancelled",
}


def call_event(
    call_id: str,
    tool: str,
    arguments: dict[str, object],
    result: BaseModel,
    call_language: Language | None = None,
) -> CallEvent:
    """Turn one tool call into a call log event.

    Every call opens the entry; a successful booking write sets the outcome and the
    booking, and a message or follow-up email flags the call for staff. The
    language is the one the tool was given, else the call's language.

    Args:
        call_id: The ElevenLabs conversation id.
        tool: The tool's name.
        arguments: The arguments the model sent.
        result: What the tool returned.
        call_language: The call's language as the server knows it (never the
            default guess), if any.

    Returns:
        The event to record. It never carries a name, phone or email.
    """
    given = arguments.get("language")
    event = CallEvent(
        call_id=call_id,
        language=given if given in ("it", "en") else call_language,  # type: ignore[arg-type]
    )
    if not getattr(result, "ok", False):
        return event
    if tool in _OUTCOMES:
        event.outcome = _OUTCOMES[tool]
        event.reference = getattr(result, "reference", None)
    elif tool == "take_message":
        event.needs_followup = True
        event.followup_reason = "message"
    elif tool == "send_followup_email":
        event.needs_followup = True
        event.followup_reason = f"tool_failure:{arguments.get('topic')}"
    return event
