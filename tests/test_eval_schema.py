"""Tests for the eval dataset schema and the golden file."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.schema import Dataset

GOLDEN = Path(__file__).parent.parent / "evals" / "golden.json"


def test_golden_file_is_valid_and_bilingual() -> None:
    """golden.json parses, and has Italian and English cases."""
    dataset = Dataset.model_validate_json(GOLDEN.read_text())
    languages = [c.language for c in dataset.cases]
    assert languages.count("it") >= 4
    assert languages.count("en") >= 4


def case(case_id: str, turns: int = 1) -> dict[str, object]:
    """Build a minimal case as raw JSON data."""
    return {
        "id": case_id,
        "language": "en",
        "turns": [{"caller": "Hello"} for _ in range(turns)],
    }


def test_duplicate_case_ids_are_rejected() -> None:
    """Case ids map to Langfuse dataset item ids, so they must be unique."""
    with pytest.raises(ValidationError, match="duplicate"):
        Dataset.model_validate({"today": "2026-11-02", "cases": [case("a"), case("a")]})


def test_case_needs_at_least_one_turn() -> None:
    """A case with no caller turns is meaningless."""
    with pytest.raises(ValidationError):
        Dataset.model_validate({"today": "2026-11-02", "cases": [case("a", turns=0)]})


def test_turn_expectations_are_not_exclusive_by_default() -> None:
    """Extra read-only tool calls are allowed unless a turn says `exclusive`."""
    dataset = Dataset.model_validate(
        {
            "today": "2026-11-02",
            "cases": [
                {
                    "id": "a",
                    "language": "en",
                    "turns": [
                        {"caller": "Hi"},
                        {"caller": "Hi", "expect": {"exclusive": True}},
                    ],
                }
            ],
        }
    )
    default_turn, strict_turn = dataset.cases[0].turns
    assert default_turn.expect.exclusive is False
    assert strict_turn.expect.exclusive is True
