"""Tests for the Langfuse wrapper: masking, no-op modes and fail-safe behaviour."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from src import observability
from src.config import Settings


class FakeObservation:
    """Records update() calls."""

    def __init__(self, started: dict[str, Any]) -> None:
        """Keep the arguments the observation was started with."""
        self.started = started
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        """Record an update."""
        self.updates.append(kwargs)


class FakeClient:
    """Stands in for the Langfuse client."""

    def __init__(self) -> None:
        """Start with no observations."""
        self.observations: list[FakeObservation] = []
        self.flushed = False

    @contextmanager
    def start_as_current_observation(self, **kwargs: Any) -> Iterator[FakeObservation]:
        """Record the observation and hand it to the caller."""
        obs = FakeObservation(kwargs)
        self.observations.append(obs)
        yield obs

    def flush(self) -> None:
        """Record the flush."""
        self.flushed = True


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """Install a fake client and record propagate_attributes calls."""
    fake = FakeClient()
    monkeypatch.setattr(observability, "_get_client", lambda: fake)
    propagated: list[dict[str, Any]] = []

    @contextmanager
    def fake_propagate(**kwargs: Any) -> Iterator[None]:
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(observability, "propagate_attributes", fake_propagate)
    fake.propagated = propagated  # type: ignore[attr-defined]
    return fake


# --- masking -------------------------------------------------------------


def test_mask_hides_emails_and_phones_in_text() -> None:
    """Emails and phone numbers are replaced; the rest of the sentence stays."""
    text = "Scrivi a mario.rossi@example.com o chiama +39 333 123 4567 grazie"
    masked = observability.mask(data=text)
    assert "mario.rossi" not in masked
    assert "333" not in masked
    assert masked.startswith("Scrivi a ") and masked.endswith(" grazie")


def test_mask_recurses_into_nested_data_and_keeps_non_text() -> None:
    """Dicts and lists are walked; numbers and None pass through."""
    data = {"a": ["x@y.io", {"b": "0612345678"}], "n": 3, "z": None}
    masked = observability.mask(data=data)
    assert masked["n"] == 3 and masked["z"] is None
    assert "x@y.io" not in str(masked) and "0612345678" not in str(masked)


def test_mask_keeps_iso_dates_and_date_ranges() -> None:
    """Stay dates are not PII and are needed to debug availability calls."""
    text = '{"check_in": "2026-11-05", "check_out": "2026-11-08"} 2026-11-05 2026-11-08'
    assert observability.mask(data=text) == text


def test_mask_never_raises() -> None:
    """A broken payload gets a placeholder, not an exception."""

    class Bad(dict):  # type: ignore[type-arg]
        def items(self) -> Any:
            raise RuntimeError("boom")

    assert observability.mask(data=Bad()) == observability.MASK_FAILED


# --- client construction ---------------------------------------------------


def test_no_keys_means_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty keys disable tracing; the SDK is never constructed."""
    built: list[Any] = []
    monkeypatch.setattr(observability, "Langfuse", lambda **kw: built.append(kw))
    assert observability.build_client(Settings(_env_file=None)) is None
    assert built == []


def test_keys_build_a_client_with_mask_and_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK gets the keys, the host and our mask function."""
    built: list[dict[str, Any]] = []
    monkeypatch.setattr(observability, "Langfuse", lambda **kw: built.append(kw) or 1)
    settings = Settings(
        _env_file=None,
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_base_url="http://localhost:3000",
    )
    assert observability.build_client(settings) == 1
    assert built == [
        {
            "public_key": "pk",
            "secret_key": "sk",
            "base_url": "http://localhost:3000",
            "mask": observability.mask,
        }
    ]


def test_a_failing_sdk_constructor_disables_tracing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """If the SDK cannot start we log a warning and run without tracing."""

    def boom(**_: Any) -> None:
        raise RuntimeError("no")

    monkeypatch.setattr(observability, "Langfuse", boom)
    settings = Settings(
        _env_file=None, langfuse_public_key="pk", langfuse_secret_key="sk"
    )
    assert observability.build_client(settings) is None
    assert "Langfuse" in caplog.text


# --- spans -----------------------------------------------------------------


def test_nothing_is_recorded_outside_a_call(client: FakeClient) -> None:
    """Without call_session every wrapper is a no-op."""
    with observability.turn_span("hi") as turn:
        turn.update(output="x")
    with observability.tool_span("check_availability", {}):
        pass
    assert client.observations == []


def test_turn_span_carries_call_id_and_language(client: FakeClient) -> None:
    """One trace per turn; the call is the session; language is a tag."""
    with (
        observability.call_session("call-1", "it"),
        observability.turn_span("Ciao") as turn,
    ):
        turn.update(output="Buongiorno")
    (obs,) = client.observations
    assert obs.started["name"] == "handle-caller-turn"
    assert obs.started["as_type"] == "span"
    assert obs.started["input"] == "Ciao"
    assert obs.updates == [{"output": "Buongiorno"}]
    assert client.propagated == [  # type: ignore[attr-defined]
        {
            "session_id": "call-1",
            "trace_name": "handle-caller-turn",
            "tags": ["lang:it"],
        }
    ]


def test_generation_and_tool_span_types(client: FakeClient) -> None:
    """LLM calls are generations with the model; tools are tool observations."""
    with observability.call_session("c", "en"):
        with observability.generation("m1", [{"role": "user", "content": "hi"}]):
            pass
        with observability.tool_span("get_rates", {"guests": 2}):
            pass
    gen, tool = client.observations
    assert gen.started["as_type"] == "generation" and gen.started["model"] == "m1"
    assert gen.started["name"] == "generate-reply"
    assert tool.started["as_type"] == "tool" and tool.started["name"] == "get_rates"
    assert tool.started["input"] == {"guests": 2}


def test_sdk_errors_never_reach_the_caller(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A client that raises on start or update only produces warnings."""

    class Exploding:
        def start_as_current_observation(self, **_: Any) -> Any:
            raise RuntimeError("langfuse is down")

    monkeypatch.setattr(observability, "_get_client", lambda: Exploding())
    with (
        observability.call_session("c", "en"),
        observability.turn_span("hi") as turn,
    ):
        turn.update(output="x")
        result = "body ran"
    assert result == "body ran"
    assert any(r.levelname == "WARNING" for r in caplog.records)
    # only the error type is logged: its message could carry guest data
    assert "RuntimeError" in caplog.text
    assert "langfuse is down" not in caplog.text


def test_errors_from_the_body_still_propagate(client: FakeClient) -> None:
    """Fail-safe tracing must not hide the application's own exceptions."""
    with (
        pytest.raises(ValueError),
        observability.call_session("c", "en"),
        observability.turn_span("hi"),
    ):
        raise ValueError("app bug")


def test_flush_calls_the_client_and_swallows_errors(
    client: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """flush() is safe when tracing is on, off, or broken."""
    observability.flush()
    assert client.flushed

    def boom() -> None:
        raise RuntimeError("x")

    client.flush = boom  # type: ignore[method-assign]
    observability.flush()
    monkeypatch.setattr(observability, "_get_client", lambda: None)
    observability.flush()
