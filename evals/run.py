"""Eval runner: play the golden dataset through the agent loop and score it."""

import argparse
import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel

from evals.schema import GOLDEN_PATH, Dataset, EvalCase
from evals.scoring import score_turn
from evals.sync import DATASET_NAME, git_sha, sync_dataset, sync_prompt
from src import observability
from src.agent.llm import ChatMessage, GroqClient, LLMClient, ToolCall
from src.agent.loop import run_turn
from src.agent.prompt import PROMPT_NAME, build_system_prompt
from src.agent.registry import Tool, build_registry
from src.config import Settings
from src.db.seed import seed_repository


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
    call_id = f"eval-{case.id}-{uuid.uuid4().hex[:6]}"
    with observability.call_session(call_id, case.language):
        for turn in case.turns:
            try:
                result = await run_turn(llm, registry, history, turn.caller)
            except httpx.HTTPError as error:
                failures.append(f"request failed: {type(error).__name__}")
                break
            new_messages = result.history[len(history) :]
            calls: list[ToolCall] = [
                c for m in new_messages for c in m.tool_calls or []
            ]
            failures += score_turn(turn.expect, case.language, calls, result.reply)
            history = result.history
    return failures


async def _run_case(
    case: EvalCase,
    llm: LLMClient,
    registry: dict[str, Tool],
    system_prompt: str,
    repeats: int,
) -> CaseSummary:
    """Run one case `repeats` times and summarise."""
    passed_runs = 0
    failures: list[str] = []
    for _ in range(repeats):
        run_failures = await _run_case_once(case, llm, registry, system_prompt)
        passed_runs += not run_failures
        failures += run_failures
    return CaseSummary(
        case_id=case.id,
        language=case.language,
        runs=repeats,
        passed_runs=passed_runs,
        failures=failures,
    )


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
    return Report(
        cases=[
            await _run_case(case, llm, registry, system_prompt, repeats)
            for case in dataset.cases
        ]
    )


def tools_fingerprint(registry: dict[str, Tool]) -> str:
    """Short hash of every tool's name, description and schema.

    It changes when a tool is added, removed or edited, so two Langfuse runs show
    at a glance whether the tools differed.
    """
    specs = [registry[name].spec().model_dump() for name in sorted(registry)]
    return hashlib.sha256(json.dumps(specs, sort_keys=True).encode()).hexdigest()[:8]


def run_on_langfuse(dataset: Dataset, settings: Settings, repeats: int) -> Report:
    """Sync prompt and dataset, then run all cases as one Langfuse experiment.

    Each case is one experiment item. Its score `pass_rate` is the share of its
    repeats that passed, so one run per code change is enough to compare.
    Call it only when `observability.is_enabled()`; it raises otherwise.

    Args:
        dataset: The golden dataset.
        settings: Groq key and model.
        repeats: How many times to run each case.

    Returns:
        The same report a local run prints.
    """
    sha = git_sha()
    prompt_version = sync_prompt(sha)
    sync_dataset(dataset)
    registry = build_registry(seed_repository(), today=dataset.today)
    system_prompt = build_system_prompt(dataset.today)
    cases = {case.id: case for case in dataset.cases}
    summaries: dict[str, CaseSummary] = {}

    async def task(*, item: Any, **_: Any) -> dict[str, Any]:
        # Built here, not outside: the SDK runs this task on its own event loop.
        async with httpx.AsyncClient(timeout=30) as http:
            llm = GroqClient(settings.groq_api_key, settings.groq_model, http)
            summary = await _run_case(
                cases[item.id], llm, registry, system_prompt, repeats
            )
        summaries[item.id] = summary
        return summary.model_dump()

    def evaluator(*, output: dict[str, Any], **_: Any) -> dict[str, Any]:
        reasons = "; ".join(dict.fromkeys(output["failures"]))
        return {
            "name": "pass_rate",
            "value": output["passed_runs"] / output["runs"],
            "comment": reasons or None,
        }

    now = datetime.now(UTC)
    url = observability.run_experiment(
        DATASET_NAME,
        f"{sha}-v{prompt_version}-{now:%m%d-%H%M}",
        task,
        evaluator,
        {
            "git_sha": sha,
            "prompt_name": PROMPT_NAME,
            "prompt_version": str(prompt_version),
            "model": settings.groq_model,
            "tools": ",".join(registry),
            "tools_hash": tools_fingerprint(registry),
            "repeats": str(repeats),
        },
    )
    if url:
        print(f"Langfuse experiment: {url}\n")
    # An item that crashed is logged by Langfuse and skipped. Count it as failed
    # here, so a crash cannot make the pass rate look better.
    return Report(
        cases=[
            summaries.get(case.id)
            or CaseSummary(
                case_id=case.id,
                language=case.language,
                runs=repeats,
                passed_runs=0,
                failures=["task crashed, see the trace in Langfuse"],
            )
            for case in dataset.cases
        ]
    )


async def _run_local(dataset: Dataset, settings: Settings, repeats: int) -> Report:
    """Run the dataset against Groq without touching Langfuse."""
    async with httpx.AsyncClient(timeout=30) as http:
        llm = GroqClient(settings.groq_api_key, settings.groq_model, http)
        return await run_dataset(dataset, llm, repeats)


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


def main() -> None:
    """Run the golden dataset against Groq and print the report.

    With Langfuse keys set, the run is synced and recorded as an experiment.
    Without them it runs locally and nothing is uploaded.
    """
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
    if observability.is_enabled():
        report = run_on_langfuse(dataset, settings, args.repeats)
    else:
        print("Langfuse keys not set: running locally, nothing is uploaded.\n")
        report = asyncio.run(_run_local(dataset, settings, args.repeats))
    _print_report(report)
    observability.flush()


if __name__ == "__main__":
    main()
