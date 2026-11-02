"""Tests for the system prompt file and its sync to Langfuse."""

from datetime import date
from typing import Any

import pytest
from langfuse.api import NotFoundError

from src import observability
from src.agent.prompt import PROMPT_NAME, build_system_prompt, load_prompt_template


def test_template_keeps_the_langfuse_variable() -> None:
    """The stored text uses Langfuse's {{today}} syntax, the only variable."""
    assert load_prompt_template().count("{{today}}") == 1


def test_build_fills_in_today_with_english_names() -> None:
    """The date is rendered the same way whatever the machine locale."""
    prompt = build_system_prompt(date(2026, 11, 2))
    assert "Today is Monday 2 November 2026." in prompt
    assert "{{" not in prompt


class FakeStoredPrompt:
    """A prompt version as returned by the Langfuse client."""

    def __init__(self, prompt: str, version: int) -> None:
        """Keep the text and version number."""
        self.prompt = prompt
        self.version = version


class FakePromptClient:
    """Stands in for the Langfuse client's prompt methods."""

    def __init__(self, stored: FakeStoredPrompt | None) -> None:
        """Start with the given production version, or none."""
        self.stored = stored
        self.created: list[dict[str, Any]] = []

    def get_prompt(self, name: str, **kwargs: Any) -> FakeStoredPrompt:
        """Return the stored version or raise like the SDK does."""
        if self.stored is None:
            raise NotFoundError(body={})
        return self.stored

    def create_prompt(self, **kwargs: Any) -> FakeStoredPrompt:
        """Record the upload and return it as the next version."""
        self.created.append(kwargs)
        return FakeStoredPrompt(
            kwargs["prompt"], (self.stored.version + 1) if self.stored else 1
        )


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakePromptClient | None) -> None:
    monkeypatch.setattr(observability, "_get_client", lambda: fake)


def test_push_creates_the_first_version_labelled_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No prompt in Langfuse yet: upload version 1."""
    fake = FakePromptClient(None)
    _install(monkeypatch, fake)
    assert observability.push_prompt("p", "text", "abc123") == (1, True)
    assert fake.created == [
        {
            "name": "p",
            "prompt": "text",
            "type": "text",
            "labels": ["production"],
            "commit_message": "abc123",
        }
    ]


def test_push_skips_identical_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same text as the production version: no new version."""
    fake = FakePromptClient(FakeStoredPrompt("text", 3))
    _install(monkeypatch, fake)
    assert observability.push_prompt("p", "text", "abc123") == (3, False)
    assert fake.created == []


def test_push_uploads_changed_text_as_a_new_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different text: upload the next version."""
    fake = FakePromptClient(FakeStoredPrompt("old", 3))
    _install(monkeypatch, fake)
    assert observability.push_prompt("p", "new", "abc123") == (4, True)


def test_push_fails_loudly_when_tracing_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sync that silently does nothing would be worse than an error."""
    _install(monkeypatch, None)
    with pytest.raises(RuntimeError, match="LANGFUSE"):
        observability.push_prompt("p", "text", "abc123")


def test_prompt_name_is_stable() -> None:
    """Renaming the prompt would orphan its Langfuse history."""
    assert PROMPT_NAME == "hotel-receptionist"
