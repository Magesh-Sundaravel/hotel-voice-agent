"""Eval runner: play the golden dataset through the agent loop and score it."""

import argparse
import asyncio
from pathlib import Path

import httpx
from pydantic import BaseModel

from evals.schema import Dataset, EvalCase
from evals.scoring import score_turn
from src.agent.llm import ChatMessage, GroqClient, LLMClient, ToolCall
from src.agent.loop import run_turn
from src.agent.prompt import build_system_prompt
from src.agent.registry import Tool, build_registry
from src.config import Settings
from src.db.seed import seed_repository

GOLDEN_PATH = Path(__file__).parent / "golden.json"


class CaseSummary(BaseModel):
    """Outcome of one case over all its repeats."""

    case_id: str
    language: str
    runs: int
    passed_runs: int
    failures: list[str] = []


class Report(BaseModel):
    """Results of a whole eval run."""

    cases: list[CaseSummary]

    @property
    def flaky_case_ids(self) -> list[str]:
        """Cases that passed in some repeats and failed in others."""
        return [c.case_id for c in self.cases if 0 < c.passed_runs < c.runs]

    @property
    def overall_pass_rate(self) -> float:
        """Share of all runs (cases x repeats) that passed."""
        return _rate(self.cases)

    @property
    def pass_rate_by_language(self) -> dict[str, float]:
        """Pass rate per reply language."""
        languages = sorted({c.language for c in self.cases})
        return {
            lang: _rate([c for c in self.cases if c.language == lang])
            for lang in languages
        }


def _rate(cases: list[CaseSummary]) -> float:
    """Passed runs divided by total runs."""
    total = sum(c.runs for c in cases)
    return sum(c.passed_runs for c in cases) / total if total else 0.0


async def _run_case_once(
    case: EvalCase, llm: LLMClient, registry: dict[str, Tool], system_prompt: str
) -> list[str]:
    """Play one scripted conversation and return every failed check (none = pass)."""
    history = [ChatMessage(role="system", content=system_prompt)]
    failures: list[str] = []
    for turn in case.turns:
        try:
            result = await run_turn(llm, registry, history, turn.caller)
        except httpx.HTTPError as error:
            failures.append(f"request failed: {type(error).__name__}")
            break
        new_messages = result.history[len(history) :]
        calls: list[ToolCall] = [c for m in new_messages for c in m.tool_calls or []]
        failures += score_turn(turn.expect, case.language, calls, result.reply)
        history = result.history
    return failures


async def run_dataset(dataset: Dataset, llm: LLMClient, repeats: int) -> Report:
    """Run every case `repeats` times, one after another, and summarise.

    Args:
        dataset: The golden dataset.
        llm: The model client.
        repeats: How many times to run each case.

    Returns:
        A report with per-case outcomes and pass rates.
    """
    registry = build_registry(seed_repository(), today=dataset.today)
    system_prompt = build_system_prompt(dataset.today)
    summaries: list[CaseSummary] = []
    for case in dataset.cases:
        passed_runs = 0
        failures: list[str] = []
        for _ in range(repeats):
            run_failures = await _run_case_once(case, llm, registry, system_prompt)
            passed_runs += not run_failures
            failures += run_failures
        summaries.append(
            CaseSummary(
                case_id=case.id,
                language=case.language,
                runs=repeats,
                passed_runs=passed_runs,
                failures=failures,
            )
        )
    return Report(cases=summaries)


def _print_report(report: Report) -> None:
    """Print a plain-text summary of the run."""
    for c in report.cases:
        print(f"{c.passed_runs}/{c.runs}  {c.case_id}")
        for failure in dict.fromkeys(c.failures):
            print(f"        - {failure}")
    print(f"\nOverall pass rate: {report.overall_pass_rate:.0%}")
    for language, rate in report.pass_rate_by_language.items():
        print(f"  {language}: {rate:.0%}")
    if report.flaky_case_ids:
        print(f"Flaky cases: {', '.join(report.flaky_case_ids)}")


async def main() -> None:
    """Run the golden dataset against Groq and print the report."""
    parser = argparse.ArgumentParser(description="Run the golden eval dataset.")
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        choices=range(1, 100),
        metavar="N",
        help="runs per case",
    )
    args = parser.parse_args()
    settings = Settings()
    dataset = Dataset.model_validate_json(GOLDEN_PATH.read_text())
    async with httpx.AsyncClient(timeout=30) as http:
        llm = GroqClient(settings.groq_api_key, settings.groq_model, http)
        _print_report(await run_dataset(dataset, llm, args.repeats))


if __name__ == "__main__":
    asyncio.run(main())
