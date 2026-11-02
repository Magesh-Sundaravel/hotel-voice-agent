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
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any, Literal

from langfuse import Langfuse, propagate_attributes
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
