"""The language of a live call: Italian or English.

No ElevenLabs variable carries it (docs/external/elevenlabs.md, section 5). The
/llm proxy sees the whole conversation, including the agent's calls to
ElevenLabs' `language_detection` system tool, so it works the language out there
and remembers it per call_id. The tool webhooks, in the same server, read it back.
Kept in memory and bounded: a restart forgets it and falls back to the default.
"""

import json
from collections import OrderedDict
from typing import Any, Literal

Language = Literal["it", "en"]

_MAX_CALLS = 10_000
_known: OrderedDict[str, Language] = OrderedDict()


def as_language(value: object) -> Language | None:
    """Map 'it', 'it-IT', 'Italian', 'en', 'en-GB', 'English', 'inglese' and the like."""
    text = str(value).strip().lower()
    if text.startswith("it"):
        return "it"
    if text.startswith(("en", "ingl")):
        return "en"
    return None


def detect_language(messages: list[dict[str, Any]]) -> Language | None:
    """Return the language of the latest language_detection call, if any.

    Args:
        messages: The chat/completions messages ElevenLabs sent.

    Returns:
        "it" or "en", or None when there is no such call (or it names neither).
    """
    for message in reversed(messages):
        for call in reversed(message.get("tool_calls") or []):
            function = call.get("function") or {}
            if function.get("name") != "language_detection":
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except (ValueError, TypeError):
                continue
            if isinstance(arguments, dict):
                language = as_language(arguments.get("language"))
                if language:
                    return language
    return None


def remember_language(call_id: str, language: Language) -> None:
    """Store a call's language; "unknown" (no X-Call-Id) is never stored."""
    if call_id == "unknown":
        return
    _known[call_id] = language
    _known.move_to_end(call_id)
    if len(_known) > _MAX_CALLS:
        _known.popitem(last=False)


def known_language(call_id: str) -> Language | None:
    """Return the language stored for a call, if any."""
    return _known.get(call_id)


def call_language(
    call_id: str, messages: list[dict[str, Any]], default: Language
) -> Language:
    """Work out a call's language from one /llm request, remembering any switch.

    Args:
        call_id: The ElevenLabs conversation id, or "unknown".
        messages: The conversation so far.
        default: The agent's primary language, used until the caller switches.

    Returns:
        The latest switch in the conversation, else what the call last used,
        else the default. Only a switch is remembered: the default is a guess.
    """
    detected = detect_language(messages)
    if detected:
        remember_language(call_id, detected)
    return detected or known_language(call_id) or default
