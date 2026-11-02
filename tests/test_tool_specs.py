"""Tests for what the model sees of each tool: its description and parameter docs."""

import pytest

from src.agent.registry import build_registry
from src.db.seed import seed_repository
from src.tools import MAX_STAY_NIGHTS

# Every `reason` a tool can return. The description must name them all, so the
# model can put each one into plain words. Keep in sync with docs/tools.md.
REASONS = {
    "check_availability": {"invalid_dates", "invalid_guests", "too_many_guests"},
    "get_rates": {"unknown_room_type", "invalid_dates", "no_rate_for_dates"},
}


@pytest.fixture
def specs() -> dict[str, dict]:  # type: ignore[type-arg]
    """The tool specs exactly as they are sent to the model."""
    registry = build_registry(seed_repository())
    return {name: tool.spec().model_dump() for name, tool in registry.items()}


def test_every_parameter_has_a_description(specs: dict[str, dict]) -> None:  # type: ignore[type-arg]
    """A bare name and type leaves the model guessing what a field means."""
    for name, spec in specs.items():
        for field, schema in spec["parameters"]["properties"].items():
            assert schema.get("description", "").strip(), f"{name}.{field}"


def test_descriptions_have_at_least_four_sentences(specs: dict[str, dict]) -> None:  # type: ignore[type-arg]
    """A rough floor from Anthropic's guidance; it cannot judge the content."""
    for name, spec in specs.items():
        sentences = [s for s in spec["description"].split(". ") if s.strip()]
        assert len(sentences) >= 4, name


def test_descriptions_name_every_error_reason(specs: dict[str, dict]) -> None:  # type: ignore[type-arg]
    """The model only sees a reason code in a result, so the tool must explain it."""
    for name, reasons in REASONS.items():
        for reason in reasons:
            assert reason in specs[name]["description"], f"{name}: {reason}"


def test_descriptions_state_the_real_stay_limit(specs: dict[str, dict]) -> None:  # type: ignore[type-arg]
    """The longest stay comes from the code, so the text cannot drift from it."""
    for name in REASONS:
        assert f"{MAX_STAY_NIGHTS} nights" in specs[name]["description"], name


def test_each_tool_points_at_the_other_for_what_it_does_not_do(
    specs: dict[str, dict],  # type: ignore[type-arg]
) -> None:
    """Prices live in get_rates and availability in check_availability."""
    assert "get_rates" in specs["check_availability"]["description"]
    assert "check_availability" in specs["get_rates"]["description"]
