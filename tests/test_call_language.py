"""Tests for working out a live call's language from what ElevenLabs sends."""

import json
from typing import Any

import pytest

from src.voice.call_language import call_language, detect_language, known_language


def _switch(language: str) -> dict[str, Any]:
    """An assistant turn that called ElevenLabs' language_detection system tool."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "t1",
                "type": "function",
                "function": {
                    "name": "language_detection",
                    "arguments": json.dumps(
                        {"language": language, "reason": "caller switched"}
                    ),
                },
            }
        ],
    }


USER = {"role": "user", "content": "Hello"}


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "en"),
        ("it", "it"),
        ("en-GB", "en"),
        ("Italian", "it"),
        ("inglese", "en"),
        ("fr", None),
    ],
)
def test_the_language_detection_call_names_the_language(
    language: str, expected: str | None
) -> None:
    """ElevenLabs' codes and names map to it/en; other languages are ignored."""
    assert detect_language([USER, _switch(language), USER]) == expected


def test_the_latest_switch_wins() -> None:
    """A caller can switch back."""
    assert detect_language([_switch("en"), USER, _switch("it"), USER]) == "it"


def test_no_switch_and_bad_arguments_detect_nothing() -> None:
    """Broken arguments are skipped, never an error."""
    broken = _switch("en")
    broken["tool_calls"][0]["function"]["arguments"] = "{not json"

    assert detect_language([USER]) is None
    assert detect_language([broken]) is None


def test_the_call_keeps_its_language_between_requests() -> None:
    """Once switched, later requests and tool webhooks use it."""
    call_id = "conv-lang"

    assert call_language(call_id, [USER], default="it") == "it"
    assert call_language(call_id, [_switch("en")], default="it") == "en"
    assert call_language(call_id, [USER], default="it") == "en"
    assert known_language(call_id) == "en"


def test_an_unknown_call_id_is_never_remembered() -> None:
    """Without X-Call-Id every call would share one language."""
    call_language("unknown", [_switch("en")], default="it")

    assert known_language("unknown") is None


def test_the_default_is_never_remembered_as_known() -> None:
    """A guess must not reach the call log through the webhooks."""
    call_language("conv-guess", [USER], default="en")

    assert known_language("conv-guess") is None
