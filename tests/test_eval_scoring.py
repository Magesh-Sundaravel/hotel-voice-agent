"""Tests for the deterministic turn scorer (seam D)."""

import pytest

from evals.schema import ExpectedToolCall, TurnExpect
from evals.scoring import score_turn
from src.agent.llm import ToolCall

AVAIL_ARGS = '{"check_in": "2026-12-10", "check_out": "2026-12-12", "guests": 2}'
GOOD_REPLY = "We have rooms free. Which type would you like?"


def call(name: str, arguments: str = "{}") -> ToolCall:
    """Build a tool call the agent made."""
    return ToolCall(id="c", name=name, arguments=arguments)


def expect_availability(**args: object) -> TurnExpect:
    """Expect one check_availability call with the given args."""
    return TurnExpect(
        tool_calls=[ExpectedToolCall(name="check_availability", args=dict(args))]
    )


def test_expected_call_with_matching_args_passes() -> None:
    """Only the listed args are compared, so extra args are fine."""
    failures = score_turn(
        expect_availability(guests=2),
        "en",
        [call("check_availability", AVAIL_ARGS)],
        GOOD_REPLY,
    )
    assert failures == []


def test_expected_call_with_wrong_args_fails() -> None:
    """A listed arg with a different value is a failure."""
    failures = score_turn(
        expect_availability(guests=4),
        "en",
        [call("check_availability", AVAIL_ARGS)],
        GOOD_REPLY,
    )
    assert len(failures) == 1
    assert "check_availability" in failures[0]


def test_missing_expected_call_fails() -> None:
    """If the agent made no call, the expected one is missing."""
    failures = score_turn(expect_availability(guests=2), "en", [], GOOD_REPLY)
    assert len(failures) == 1


def test_extra_calls_are_allowed_by_default() -> None:
    """A read-only get_rates after the expected call does not fail the turn."""
    failures = score_turn(
        expect_availability(guests=2),
        "en",
        [call("check_availability", AVAIL_ARGS), call("get_rates")],
        GOOD_REPLY,
    )
    assert failures == []


def test_expected_calls_must_appear_in_order() -> None:
    """get_rates before check_availability breaks an availability-then-rates case."""
    expect = TurnExpect(
        tool_calls=[
            ExpectedToolCall(name="check_availability"),
            ExpectedToolCall(name="get_rates"),
        ]
    )
    failures = score_turn(
        expect, "en", [call("get_rates"), call("check_availability")], GOOD_REPLY
    )
    assert len(failures) == 1


def test_exclusive_forbids_extra_calls() -> None:
    """With exclusive set, the agent's calls must be exactly the expected ones."""
    expect = TurnExpect(
        tool_calls=[ExpectedToolCall(name="check_availability")], exclusive=True
    )
    failures = score_turn(
        expect,
        "en",
        [call("check_availability", AVAIL_ARGS), call("get_rates")],
        GOOD_REPLY,
    )
    assert len(failures) == 1
    assert "get_rates" in failures[0]


def test_must_not_call_tools_passes_without_calls() -> None:
    """Asking a clarifying question with no tool call passes."""
    failures = score_turn(
        TurnExpect(must_not_call_tools=True), "en", [], "May I have your dates?"
    )
    assert failures == []


def test_must_not_call_tools_fails_when_a_tool_was_called() -> None:
    """Calling any tool breaks a must_not_call_tools turn."""
    failures = score_turn(
        TurnExpect(must_not_call_tools=True),
        "en",
        [call("get_rates")],
        "May I have your dates?",
    )
    assert len(failures) == 1
    assert "get_rates" in failures[0]


def reply_failures(reply: str) -> list[str]:
    """Score a reply on a turn with no tool expectations, as an English case."""
    return score_turn(TurnExpect(), "en", [], reply)


def test_clean_spoken_reply_passes() -> None:
    """Two short sentences with room names and spoken prices are fine."""
    reply = (
        "We have the Superior and the Aurelia Penthouse Suite free. "
        "The Superior is two hundred and twenty euros a night."
    )
    assert reply_failures(reply) == []


@pytest.mark.parametrize(
    ("reply", "keyword"),
    [
        ("We have **Superior** rooms free.", "markdown"),
        ("We have: - Superior - Deluxe", "markdown"),
        ("Visit `our site` for more.", "markdown"),
        ("The Superior costs 220 euros a night.", "digit"),
        ("We have rooms free on 2026-12-10.", "digit"),
        ("We have rooms. They are nice. Which one would you like?", "sentence"),
    ],
)
def test_reply_rule_violations_are_reported(reply: str, keyword: str) -> None:
    """Each voice-rule violation produces a failure that names the rule."""
    failures = reply_failures(reply)
    assert len(failures) == 1
    assert keyword in failures[0]


ITALIAN_SLIP = (
    "Abbiamo diverse camere libere per domani notte, dalla Superior alla "
    "Aurelia Penthouse Suite. Quale tipologia di camera le interessa?"
)
ENGLISH_WITH_ITALIAN_NAMES = (
    "We have the Superior and the Executive Deluxe Courtyard View free. "
    "Which type would you like?"
)


def test_italian_reply_to_an_english_case_fails() -> None:
    """The slip seen in the live run: an English caller gets Italian."""
    failures = score_turn(TurnExpect(), "en", [], ITALIAN_SLIP)
    assert len(failures) == 1
    assert "language" in failures[0]


def test_english_reply_to_an_italian_case_fails() -> None:
    """The reverse mismatch is caught too."""
    failures = score_turn(TurnExpect(), "it", [], ENGLISH_WITH_ITALIAN_NAMES)
    assert len(failures) == 1
    assert "language" in failures[0]


def test_matching_language_passes_even_with_foreign_room_names() -> None:
    """Italian room names inside an English reply do not flip the verdict."""
    assert score_turn(TurnExpect(), "en", [], ENGLISH_WITH_ITALIAN_NAMES) == []
    assert score_turn(TurnExpect(), "it", [], ITALIAN_SLIP) == []


def test_reply_with_no_language_signal_is_not_flagged() -> None:
    """A one-word reply gives the heuristic nothing to go on, so it passes."""
    assert score_turn(TurnExpect(), "it", [], "Certo.") == []


def test_empty_reply_fails() -> None:
    """A silent turn is a failure even when no tool calls were expected."""
    failures = score_turn(TurnExpect(), "en", [], "")
    assert len(failures) == 1
    assert "empty" in failures[0]


def test_args_match_after_the_tool_would_coerce_them() -> None:
    """The model sending "2" for guests still runs the tool, so it still matches."""
    failures = score_turn(
        expect_availability(guests=2),
        "en",
        [call("check_availability", '{"guests": "2"}')],
        GOOD_REPLY,
    )
    assert failures == []


def test_italian_words_that_look_english_do_not_flip_the_verdict() -> None:
    """ "i" is an Italian article: this Italian reply must not read as English."""
    assert (
        score_turn(TurnExpect(), "it", [], "Ecco i prezzi della Suite e del Deluxe.")
        == []
    )


def test_a_forbidden_tool_fails_and_others_are_allowed() -> None:
    """Reading a booking is fine; cancelling before the caller says yes is not."""
    expect = TurnExpect(
        tool_calls=[ExpectedToolCall(name="get_booking")],
        forbidden_tools=["cancel_booking"],
    )

    ok = score_turn(expect, "en", [call("get_booking")], GOOD_REPLY)
    bad = score_turn(
        expect, "en", [call("get_booking"), call("cancel_booking")], GOOD_REPLY
    )

    assert ok == []
    assert bad == ["called cancel_booking, which this turn forbids"]
