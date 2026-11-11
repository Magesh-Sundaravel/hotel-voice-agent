"""Tests for the eval runner (seam E), using a scripted fake LLM."""

import re

import httpx
import pytest

from evals.run import Report, break_tools, run_dataset, select_cases
from evals.schema import Dataset
from src.agent.llm import AssistantMessage, ToolCall
from src.agent.loop import run_tool
from src.agent.registry import build_registry
from src.db.seed import seed_repository
from src.tools.context import CallContext
from tests.test_loop import ScriptedLLM

AVAILABILITY_CALL = ToolCall(
    id="c1",
    name="check_availability",
    arguments='{"check_in": "2026-12-10", "check_out": "2026-12-12", "guests": 2}',
)

DATASET = Dataset.model_validate(
    {
        "today": "2026-11-02",
        "cases": [
            {
                "id": "en-case",
                "language": "en",
                "turns": [
                    {
                        "caller": "Room for two, December 10th to 12th?",
                        "expect": {
                            "tool_calls": [
                                {"name": "check_availability", "args": {"guests": 2}}
                            ]
                        },
                    }
                ],
            },
            {
                "id": "it-case",
                "language": "it",
                "turns": [
                    {
                        "caller": "Quanto costa una camera?",
                        "expect": {"must_not_call_tools": True},
                    }
                ],
            },
        ],
    }
)


def scripted_runs() -> ScriptedLLM:
    """en-case passes twice. it-case passes once, then gets an English reply."""
    en_run = [
        AssistantMessage(content=None, tool_calls=[AVAILABILITY_CALL]),
        AssistantMessage(content="We have rooms free. Which type would you like?"),
    ]
    return ScriptedLLM(
        [
            *en_run,
            *en_run,
            AssistantMessage(content="Quale data di arrivo preferisce?"),
            AssistantMessage(content="Which date would you like to arrive?"),
        ]
    )


@pytest.mark.asyncio
async def test_pass_rates_overall_and_by_language() -> None:
    """3 of 4 runs pass overall. English is 2/2, Italian is 1/2."""
    report = await run_dataset(DATASET, scripted_runs(), repeats=2)

    assert report.overall_pass_rate == 0.75
    assert report.pass_rate_by_language == {"en": 1.0, "it": 0.5}


@pytest.mark.asyncio
async def test_flaky_cases_are_listed_with_their_failures() -> None:
    """A case that passes once and fails once is flaky, and says why it failed."""
    report = await run_dataset(DATASET, scripted_runs(), repeats=2)

    assert report.flaky_case_ids == ["it-case"]
    italian = next(c for c in report.cases if c.case_id == "it-case")
    assert len(italian.failures) == 1
    assert "language" in italian.failures[0]
    english = next(c for c in report.cases if c.case_id == "en-case")
    assert english.failures == []


class FailsOnceLLM:
    """Raises a timeout on its first call, then behaves like the wrapped LLM."""

    def __init__(self, inner: ScriptedLLM) -> None:
        """Wrap the scripted LLM."""
        self._inner = inner
        self._failed = False

    async def complete(self, messages: list, tools: list) -> AssistantMessage:  # type: ignore[type-arg]
        """Fail once, then delegate."""
        if not self._failed:
            self._failed = True
            raise httpx.ReadTimeout("slow")
        return await self._inner.complete(messages, tools)


@pytest.mark.asyncio
async def test_an_http_error_fails_that_run_and_the_rest_continue() -> None:
    """A timeout in one run is recorded as a failure, not a crashed eval."""
    inner = ScriptedLLM(
        [
            AssistantMessage(content="Quale data di arrivo preferisce?"),
        ]
    )
    dataset = Dataset.model_validate(
        {
            "today": "2026-11-02",
            "cases": [
                DATASET.model_dump()["cases"][0],
                DATASET.model_dump()["cases"][1],
            ],
        }
    )

    report = await run_dataset(dataset, FailsOnceLLM(inner), repeats=1)

    english, italian = report.cases
    assert english.passed_runs == 0
    assert "request failed" in english.failures[0]
    assert italian.passed_runs == 1


@pytest.mark.asyncio
async def test_each_finished_case_prints_a_progress_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Lines appear as cases finish, so a long run is not silent until the end."""
    await run_dataset(DATASET, scripted_runs(), repeats=2)

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert re.fullmatch(r"\[1/2\] PASS  en-case  \(2/2, \d+s\)", lines[0])
    assert re.fullmatch(r"\[2/2\] FAIL  it-case  \(1/2, \d+s\)", lines[1])


def test_an_empty_report_has_a_zero_rate_not_a_crash() -> None:
    """No runs means 0%, not a division by zero."""
    assert Report(cases=[]).overall_pass_rate == 0.0


def _tagged() -> Dataset:
    """Two cases: en-case tagged `a`, it-case tagged `b`."""
    data = DATASET.model_dump(mode="json")
    data["cases"][0]["tags"] = ["a"]
    data["cases"][1]["tags"] = ["b"]
    return Dataset.model_validate(data)


def test_no_selection_keeps_every_case() -> None:
    """Without --case or --tag nothing is filtered."""
    assert select_cases(_tagged(), [], []) == _tagged()


def test_cases_are_picked_by_id_or_by_tag() -> None:
    """An id or any matching tag selects a case."""
    assert [c.id for c in select_cases(_tagged(), ["it-case"], []).cases] == ["it-case"]
    assert [c.id for c in select_cases(_tagged(), [], ["a"]).cases] == ["en-case"]
    both = select_cases(_tagged(), ["it-case"], ["a"])
    assert [c.id for c in both.cases] == ["en-case", "it-case"]


def test_an_unknown_id_or_empty_tag_match_is_an_error() -> None:
    """A typo must not silently run nothing."""
    with pytest.raises(ValueError, match="unknown case id: nope"):
        select_cases(_tagged(), ["nope"], [])
    with pytest.raises(ValueError, match="no case has any of the tags: zzz"):
        select_cases(_tagged(), [], ["zzz"])


@pytest.mark.asyncio
async def test_a_case_can_make_a_tool_fail() -> None:
    """failing_tools lets a case test the retry-then-email path."""
    repo = seed_repository()
    registry = break_tools(
        build_registry(repo, repo, CallContext(call_id="eval-fail")),
        ["check_availability"],
    )

    first = await run_tool(registry, AVAILABILITY_CALL)
    again = await run_tool(registry, AVAILABILITY_CALL)
    rates = await run_tool(
        registry,
        ToolCall(
            id="c2",
            name="get_rates",
            arguments='{"room_type": "Suite", "check_in": "2026-12-10",'
            ' "check_out": "2026-12-12"}',
        ),
    )

    assert first.model_dump() == {"ok": False, "reason": "tool_error"}
    assert again.model_dump() == {"ok": False, "reason": "tool_error"}
    assert rates.model_dump()["ok"] is True


def test_failing_tools_must_be_real_tools() -> None:
    """A typo in the dataset should fail loudly, not test nothing."""
    with pytest.raises(ValueError, match="book_spa"):
        break_tools({}, ["book_spa"])
