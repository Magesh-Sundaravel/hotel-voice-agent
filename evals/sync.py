"""Sync the repo's prompt and golden dataset to Langfuse. The repo is the source of truth.

Run: uv run python -m evals.sync
"""

import subprocess

from evals.schema import GOLDEN_PATH, Dataset
from src import observability
from src.agent.prompt import PROMPT_NAME, load_prompt_template

DATASET_NAME = "hotel-golden"


def git_sha() -> str:
    """Return the short commit SHA, with `-dirty` when there are uncommitted changes.

    Untracked files count as changes, so a stray scratch file makes a run `-dirty`.

    Returns:
        The SHA, such as `81ea27b` or `81ea27b-dirty`.
    """
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    return f"{sha}-dirty" if status.strip() else sha


def build_items(dataset: Dataset) -> list[observability.DatasetItemSpec]:
    """One Langfuse item per case. The input holds only what the caller says.

    Expectations go in `expected_output`, so a Langfuse reader (or an LLM judge
    later) can tell the question from the answer key.

    Args:
        dataset: The golden dataset.

    Returns:
        One item per case, with the case id as the item id.
    """
    return [
        observability.DatasetItemSpec(
            id=case.id,
            input={
                "language": case.language,
                "today": dataset.today.isoformat(),
                "turns": [{"caller": turn.caller} for turn in case.turns],
            },
            expected_output={
                "turns": [turn.expect.model_dump(mode="json") for turn in case.turns]
            },
            metadata={"tags": case.tags},
        )
        for case in dataset.cases
    ]


def sync_prompt(sha: str) -> int:
    """Upload the system prompt if it changed, print what happened, return its version."""
    version, created = observability.push_prompt(
        PROMPT_NAME, load_prompt_template(), sha
    )
    state = "uploaded new version" if created else "already up to date, version"
    print(f"{PROMPT_NAME}: {state} {version}")
    return version


def sync_dataset(dataset: Dataset) -> None:
    """Make the Langfuse dataset match the golden file, and print what changed."""
    changed, archived = observability.sync_dataset(DATASET_NAME, build_items(dataset))
    print(f"{DATASET_NAME}: {changed} items written, {archived} archived")


def main() -> None:
    """Sync the prompt, then the dataset."""
    sync_prompt(git_sha())
    sync_dataset(Dataset.model_validate_json(GOLDEN_PATH.read_text()))


if __name__ == "__main__":
    main()
