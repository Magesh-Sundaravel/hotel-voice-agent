"""Langfuse tracing. The only module that touches the Langfuse SDK.

Rules this module enforces (see .claude/rules/observability.md and data.md):
- Tracing never breaks a call: every SDK failure is logged as a warning and dropped.
- Tracing is off when the keys are empty, and outside `call_session`.
- Emails and phone numbers are masked before anything leaves the process.
- Only the call id, the language and tool names go into names, tags and session ids,
  because `mask` does not reach those fields.
"""

import logging
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any, Literal

from langfuse import Langfuse, propagate_attributes
from langfuse.api import NotFoundError
from pydantic import BaseModel

from src.config import Settings

logger = logging.getLogger(__name__)

MASK_FAILED = "<masked: could not process>"
TURN_NAME = "handle-caller-turn"
GENERATION_NAME = "generate-reply"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 9-15 digits with optional single separators; digit-count and date checks below.
_PHONE = re.compile(r"(?<![\w-])\+?\d(?:[\s.()-]?\d){8,14}(?![\w-])")
_ISO_DATES = re.compile(r"\d{4}-\d{2}-\d{2}(?: \d{4}-\d{2}-\d{2})*")


class CallContext(BaseModel):
    """Who a trace belongs to: the call and the caller's language."""

    call_id: str
    language: Literal["it", "en", "unknown"]


_call: ContextVar[CallContext | None] = ContextVar("call", default=None)


def _mask_phone(match: re.Match[str]) -> str:
    """Replace a long digit run unless it is just one or more ISO dates."""
    if _ISO_DATES.fullmatch(match.group()):
        return match.group()
    return "<phone>"


def _mask(data: Any) -> Any:
    """Recursively mask emails and phone numbers; other values pass through."""
    if isinstance(data, str):
        return _PHONE.sub(_mask_phone, _EMAIL.sub("<email>", data))
    if isinstance(data, dict):
        return {key: _mask(value) for key, value in data.items()}
    if isinstance(data, list | tuple):
        return [_mask(item) for item in data]
    return data


def mask(*, data: Any, **_: Any) -> Any:
    """Langfuse `mask` hook. Never raises: a failure hides the whole value."""
    try:
        return _mask(data)
    except Exception:  # noqa: BLE001 - leaking PII is worse than losing a field
        return MASK_FAILED


def build_client(settings: Settings) -> Langfuse | None:
    """Create the Langfuse client, or None when keys are missing or init fails."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            mask=mask,
        )
    except Exception as error:  # noqa: BLE001 - tracing must never break startup
        logger.warning("Langfuse disabled: %s", type(error).__name__)
        return None


@lru_cache(maxsize=1)
def _get_client() -> Langfuse | None:
    """The process-wide client (built once, from .env / environment)."""
    return build_client(Settings())


def is_enabled() -> bool:
    """True when Langfuse keys are configured and the client was built."""
    return _get_client() is not None


def _require_client() -> Langfuse:
    """The client for a deliberate command (sync, experiment).

    Raises:
        RuntimeError: Langfuse keys are not configured.
    """
    client = _get_client()
    if client is None:
        raise RuntimeError(
            "Langfuse is off: set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY"
        )
    return client


class Observation:
    """A live span that swallows SDK errors. `update` is a no-op when untraced."""

    def __init__(self, inner: Any | None = None) -> None:
        """Wrap an SDK observation, or nothing."""
        self._inner = inner

    def update(self, **kwargs: Any) -> None:
        """Set output, usage, level etc. on the observation."""
        if self._inner is None:
            return
        try:
            self._inner.update(**kwargs)
        except Exception as error:  # noqa: BLE001 - tracing must never break a call
            logger.warning("Langfuse update failed: %s", type(error).__name__)


@contextmanager
def call_session(call_id: str, language: str) -> Iterator[None]:
    """Mark everything inside as part of one phone call.

    Args:
        call_id: The ElevenLabs conversation id, or a generated id.
        language: "it" or "en"; anything else is recorded as "unknown".
    """
    lang: Literal["it", "en", "unknown"] = (
        "it" if language == "it" else "en" if language == "en" else "unknown"
    )
    token = _call.set(CallContext(call_id=call_id, language=lang))
    try:
        yield
    finally:
        _call.reset(token)


@contextmanager
def _observe(**kwargs: Any) -> Iterator[Observation]:
    """Open an SDK observation if tracing is on; otherwise yield a dummy.

    Errors raised by the SDK on open or close are logged. Errors raised by the
    caller's own code inside the block propagate untouched.
    """
    client = _get_client() if _call.get() else None
    if client is None:
        yield Observation()
        return
    try:
        manager = client.start_as_current_observation(**kwargs)
        inner = manager.__enter__()
    except Exception as error:  # noqa: BLE001 - tracing must never break a call
        logger.warning("Langfuse span failed to open: %s", type(error).__name__)
        yield Observation()
        return
    try:
        yield Observation(inner)
    finally:
        _close(manager, sys.exc_info())


def _close(manager: Any, exc_info: tuple[Any, Any, Any]) -> None:
    """Close an SDK observation, logging instead of raising."""
    try:
        manager.__exit__(*exc_info)
    except Exception as error:  # noqa: BLE001 - tracing must never break a call
        logger.warning("Langfuse span failed to close: %s", type(error).__name__)


@contextmanager
def turn_span(user_text: str) -> Iterator[Observation]:
    """One caller turn = one trace. The call is the Langfuse session."""
    call = _call.get()
    if call is None:
        with _observe() as obs:
            yield obs
        return
    try:
        scope = propagate_attributes(
            session_id=call.call_id,
            trace_name=TURN_NAME,
            tags=[f"lang:{call.language}"],
        )
        scope.__enter__()
    except Exception as error:  # noqa: BLE001 - tracing must never break a call
        logger.warning("Langfuse attributes failed: %s", type(error).__name__)
        scope = None
    try:
        with _observe(as_type="span", name=TURN_NAME, input=user_text) as obs:
            yield obs
    finally:
        if scope is not None:
            _close(scope, sys.exc_info())


def generation(model: str, messages: list[dict[str, Any]]) -> Any:
    """One model invocation (an LLM call), input in OpenAI message format."""
    return _observe(
        as_type="generation", name=GENERATION_NAME, model=model, input=messages
    )


def tool_span(name: str, args: Any) -> Any:
    """One tool call, named after the tool."""
    return _observe(as_type="tool", name=name, input=args)


def push_prompt(name: str, text: str, commit_message: str) -> tuple[int, bool]:
    """Upload prompt text to Langfuse unless the production version already has it.

    Unlike tracing, this is a deliberate command, so failures are raised.

    Args:
        name: Langfuse prompt name.
        text: The prompt, with `{{variable}}` placeholders.
        commit_message: Recorded on the new version (the git SHA).

    Returns:
        (version, created): the production version now in Langfuse, and whether
        this call created it.

    Raises:
        RuntimeError: Langfuse keys are not configured.
    """
    client = _require_client()
    try:
        current = client.get_prompt(name, label="production", cache_ttl_seconds=0)
        if current.prompt == text:
            return current.version, False
    except NotFoundError:
        pass
    created = client.create_prompt(
        name=name,
        prompt=text,
        type="text",
        labels=["production"],
        commit_message=commit_message,
    )
    return created.version, True


class DatasetItemSpec(BaseModel):
    """One Langfuse dataset item. `id` is stable, so a sync updates in place."""

    id: str
    input: dict[str, Any]
    expected_output: dict[str, Any]
    metadata: dict[str, Any]


def sync_dataset(name: str, items: list[DatasetItemSpec]) -> tuple[int, int]:
    """Make the Langfuse dataset match `items`. The repo is the source of truth.

    Every write creates a dataset version, so only items that differ are written.
    Items that are no longer in `items` are archived, which drops them from
    future experiment runs. An archived item keeps its old input and expected
    output, so archiving cannot blank it.

    Args:
        name: Langfuse dataset name; created if it does not exist.
        items: The items the dataset should hold.

    Returns:
        (changed, archived): how many items were created or updated, and how many
        were archived.

    Raises:
        RuntimeError: Langfuse keys are not configured.
    """
    client = _require_client()
    try:
        stored = {item.id: item for item in client.get_dataset(name).items}
    except NotFoundError:
        client.create_dataset(name=name)
        stored = {}
    wanted = {item.id for item in items}
    changed = 0
    for item in items:
        old = stored.get(item.id)
        if (
            old is not None
            and old.status == "ACTIVE"
            and old.input == item.input
            and old.expected_output == item.expected_output
            and old.metadata == item.metadata
        ):
            continue
        client.create_dataset_item(
            dataset_name=name, status="ACTIVE", **item.model_dump()
        )
        changed += 1
    archived = 0
    for item_id, old in stored.items():
        if item_id not in wanted and old.status == "ACTIVE":
            client.create_dataset_item(
                dataset_name=name,
                id=item_id,
                input=old.input,
                expected_output=old.expected_output,
                metadata=old.metadata,
                status="ARCHIVED",
            )
            archived += 1
    return changed, archived


def run_experiment(
    dataset_name: str,
    run_name: str,
    task: Callable[..., Any],
    evaluator: Callable[..., Any],
    metadata: dict[str, str],
    item_ids: set[str] | None = None,
) -> str | None:
    """Run `task` on the active items of a dataset, as one Langfuse experiment.

    Items run one at a time (the Groq free tier is rate limited). Call this from
    sync code: the SDK starts its own event loop for an async `task`.

    Args:
        dataset_name: Langfuse dataset to run on.
        run_name: Unique name of this run; runs with the same name are merged.
        task: Async function called as `task(item=...)` for each item.
        evaluator: Called as `evaluator(output=..., ...)`; returns a score dict.
        metadata: Short string values attached to the run and its traces.
        item_ids: Run only the items with these ids; None runs them all.

    Returns:
        The experiment's URL in Langfuse, if the SDK gave one.

    Raises:
        RuntimeError: Langfuse keys are not configured.
    """
    client = _require_client()
    dataset = client.get_dataset(dataset_name)
    if item_ids is not None:
        dataset.items = [item for item in dataset.items if item.id in item_ids]
    result = dataset.run_experiment(
        name=dataset_name,
        run_name=run_name,
        task=task,
        evaluators=[evaluator],
        max_concurrency=1,
        metadata=metadata,
    )
    return result.experiment_url


def flush() -> None:
    """Send buffered spans. Call once at exit of short-lived processes.

    Blocks while the server is slow or down, so never call it on a request path.
    """
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as error:  # noqa: BLE001 - tracing must never break exit
        logger.warning("Langfuse flush failed: %s", type(error).__name__)
