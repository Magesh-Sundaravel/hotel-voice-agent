"""Tests for the Langfuse side of the evals: dataset sync and experiment runs."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from langfuse.api import NotFoundError

from evals import run
from evals.schema import Dataset
from evals.sync import build_items
from src import observability
from src.config import Settings
from tests.test_eval_run import DATASET, scripted_runs

# --- build_items ---------------------------------------------------------


def test_items_use_the_case_id_and_hide_expectations_from_the_input() -> None:
    """The item id is the case id. The input is what the caller says, nothing else."""
    items = build_items(DATASET)

    assert [i.id for i in items] == ["en-case", "it-case"]
    english = items[0]
    assert english.input == {
        "language": "en",
        "today": "2026-11-02",
        "turns": [{"caller": "Room for two, December 10th to 12th?"}],
    }
    assert english.expected_output["turns"][0]["tool_calls"] == [
        {"name": "check_availability", "args": {"guests": 2}}
    ]
    assert items[1].expected_output["turns"][0]["must_not_call_tools"] is True


# --- sync_dataset --------------------------------------------------------


class FakeLangfuseDatasets:
    """Stands in for the Langfuse client's dataset methods."""

    def __init__(self, existing: list[SimpleNamespace] | None) -> None:
        """`existing` is the dataset's items, or None when the dataset is missing."""
        self.items = existing
        self.created_datasets: list[dict[str, Any]] = []
        self.upserts: list[dict[str, Any]] = []

    def get_dataset(self, name: str) -> SimpleNamespace:
        """Return the dataset or raise like the SDK does."""
        if self.items is None:
            raise NotFoundError(body={})
        return SimpleNamespace(items=self.items)

    def create_dataset(self, **kwargs: Any) -> None:
        """Record the creation; the dataset starts empty."""
        self.created_datasets.append(kwargs)
        self.items = []

    def create_dataset_item(self, **kwargs: Any) -> None:
        """Record an upsert."""
        self.upserts.append(kwargs)


def _stored(spec: observability.DatasetItemSpec, **changes: Any) -> SimpleNamespace:
    """A dataset item as Langfuse returns it, equal to `spec` unless changed."""
    fields: dict[str, Any] = {**spec.model_dump(), "status": "ACTIVE", **changes}
    return SimpleNamespace(**fields)


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeLangfuseDatasets) -> None:
    monkeypatch.setattr(observability, "_get_client", lambda: fake)


def test_sync_creates_a_missing_dataset_and_all_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First sync: create the dataset, then every item with its case id."""
    fake = FakeLangfuseDatasets(None)
    _install(monkeypatch, fake)

    changed, archived = observability.sync_dataset("ds", build_items(DATASET))

    assert (changed, archived) == (2, 0)
    assert len(fake.created_datasets) == 1
    assert [u["id"] for u in fake.upserts] == ["en-case", "it-case"]
    assert all(
        u["dataset_name"] == "ds" and u["status"] == "ACTIVE" for u in fake.upserts
    )


def test_sync_leaves_unchanged_items_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every upsert is a new dataset version, so identical items are skipped."""
    items = build_items(DATASET)
    fake = FakeLangfuseDatasets([_stored(i) for i in items])
    _install(monkeypatch, fake)

    assert observability.sync_dataset("ds", items) == (0, 0)
    assert fake.upserts == []


def test_sync_updates_a_changed_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """An edited case is upserted under the same id."""
    items = build_items(DATASET)
    stale = _stored(items[0], input={"language": "en", "turns": []})
    fake = FakeLangfuseDatasets([stale, _stored(items[1])])
    _install(monkeypatch, fake)

    assert observability.sync_dataset("ds", items) == (1, 0)
    assert [u["id"] for u in fake.upserts] == ["en-case"]


def test_sync_archives_items_that_left_the_golden_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed case must stop running: archive it, never delete.

    The old input and expected output are sent back, so archiving cannot blank them.
    """
    items = build_items(DATASET)
    content = {"input": {"a": 1}, "expected_output": {"b": 2}, "metadata": {"c": 3}}
    gone = SimpleNamespace(id="old-case", status="ACTIVE", **content)
    already_archived = SimpleNamespace(id="older-case", status="ARCHIVED", **content)
    fake = FakeLangfuseDatasets([*(_stored(i) for i in items), gone, already_archived])
    _install(monkeypatch, fake)

    assert observability.sync_dataset("ds", items) == (0, 1)
    assert fake.upserts == [
        {"dataset_name": "ds", "id": "old-case", "status": "ARCHIVED", **content}
    ]


def test_sync_brings_back_an_archived_case_that_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A case that is in the file again is made active again."""
    items = build_items(DATASET)
    fake = FakeLangfuseDatasets(
        [_stored(items[0], status="ARCHIVED"), _stored(items[1])]
    )
    _install(monkeypatch, fake)

    assert observability.sync_dataset("ds", items) == (1, 0)
    assert fake.upserts[0]["status"] == "ACTIVE"


def test_sync_fails_loudly_when_tracing_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silently syncing nothing would hide a missing key."""
    monkeypatch.setattr(observability, "_get_client", lambda: None)
    with pytest.raises(RuntimeError, match="LANGFUSE"):
        observability.sync_dataset("ds", build_items(DATASET))


# --- the tool fingerprint ------------------------------------------------


def test_fingerprint_changes_when_a_tool_changes() -> None:
    """Adding a tool or rewording its description must show up in a run."""
    registry = run.spec_registry(DATASET.today)
    before = run.tools_fingerprint(registry)

    assert run.tools_fingerprint(registry) == before
    registry["get_rates"].description += " Extra words."
    assert run.tools_fingerprint(registry) != before
    del registry["get_rates"]
    assert run.tools_fingerprint(registry) != before


# --- an experiment run ---------------------------------------------------


class FakeExperiment:
    """Plays the part of Langfuse's run_experiment: run each item, then score it."""

    def __init__(self, dataset: Dataset) -> None:
        """Remember the items to run and start with no calls."""
        self.dataset = dataset
        self.calls: list[dict[str, Any]] = []
        self.scores: list[dict[str, Any]] = []

    def __call__(
        self,
        dataset_name: str,
        run_name: str,
        task: Callable[..., Any],
        evaluator: Callable[..., Any],
        metadata: dict[str, str],
    ) -> str:
        """Run the task and evaluator on every case, in order, like the SDK."""
        import asyncio

        self.calls.append(
            {"dataset_name": dataset_name, "run_name": run_name, "metadata": metadata}
        )

        async def go() -> None:
            for case in self.dataset.cases:
                output = await task(item=SimpleNamespace(id=case.id))
                self.scores.append(evaluator(output=output))

        asyncio.run(go())
        return "https://langfuse.test/experiment/1"


def _wire(monkeypatch: pytest.MonkeyPatch, fake: FakeExperiment) -> None:
    """Replace Langfuse and Groq with fakes. Both runs of en-case pass."""
    monkeypatch.setattr(observability, "run_experiment", fake)
    llm = scripted_runs()  # one script for the whole run, like the real client's state
    monkeypatch.setattr(run, "GroqClient", lambda *a, **k: llm)
    monkeypatch.setattr(run, "git_sha", lambda: "abc1234")
    monkeypatch.setattr(run, "sync_prompt", lambda sha: 7)
    monkeypatch.setattr(run, "sync_dataset", lambda dataset: None)


def test_an_experiment_run_reports_and_scores_every_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One experiment per run. Each case gets a pass_rate score and a reason."""
    fake = FakeExperiment(DATASET)
    _wire(monkeypatch, fake)

    report = run.run_on_langfuse(DATASET, Settings(groq_api_key="k"), repeats=2)

    assert report.overall_pass_rate == 0.75
    assert [(s["name"], s["value"]) for s in fake.scores] == [
        ("pass_rate", 1.0),
        ("pass_rate", 0.5),
    ]
    assert "language" in fake.scores[1]["comment"]
    assert fake.scores[0]["comment"] is None


def test_the_run_is_named_and_described_so_runs_can_be_compared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Name carries sha and prompt version; metadata carries the tools and the model."""
    fake = FakeExperiment(DATASET)
    _wire(monkeypatch, fake)

    run.run_on_langfuse(DATASET, Settings(groq_api_key="k", groq_model="m"), repeats=2)

    call = fake.calls[0]
    assert call["dataset_name"] == run.DATASET_NAME
    assert call["run_name"].startswith("abc1234-v7-")
    metadata = call["metadata"]
    assert metadata["git_sha"] == "abc1234"
    assert metadata["prompt_version"] == "7"
    assert metadata["model"] == "m"
    assert metadata["tools"] == (
        "check_availability,get_rates,lookup_guest,create_booking,get_booking,"
        "modify_booking,cancel_booking"
    )
    assert metadata["repeats"] == "2"
    assert len(metadata["tools_hash"]) == 8


def test_a_case_whose_task_crashed_counts_as_failed_not_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Langfuse logs a crashed item and moves on. The report must not hide it."""

    class CrashingExperiment(FakeExperiment):
        def __call__(self, *args: Any, **kwargs: Any) -> str:  # type: ignore[override]
            return "url"  # never runs any item

    _wire(monkeypatch, CrashingExperiment(DATASET))

    report = run.run_on_langfuse(DATASET, Settings(groq_api_key="k"), repeats=2)

    assert report.overall_pass_rate == 0.0
    assert [c.case_id for c in report.cases] == ["en-case", "it-case"]
    assert "crashed" in report.cases[0].failures[0]
