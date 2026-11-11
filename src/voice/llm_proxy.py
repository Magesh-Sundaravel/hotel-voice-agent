"""The ElevenLabs custom LLM: an OpenAI-compatible endpoint that forwards to Groq.

ElevenLabs sends `chat/completions` requests here and expects an SSE stream back.
The proxy puts our system prompt first (so callers get the same prompt the evals
test), forces our Groq model, drops `elevenlabs_extra_body`, streams Groq's bytes
through untouched and records one Langfuse generation once the stream ends.
Request shape: docs/external/elevenlabs.md, sections 1 and 5.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.background import BackgroundTask

from src import observability
from src.agent.llm import GROQ_CHAT_URL
from src.agent.prompt import build_system_prompt
from src.tools.stay import hotel_today
from src.voice.call_language import Language, call_language
from src.voice.webhooks import Services, get_services, require_secret

logger = logging.getLogger(__name__)

LLM_TRACE_NAME = "handle-llm-request"
_GROQ_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
# Body fields passed on to Groq. Anything else ElevenLabs sends (user_id,
# elevenlabs_extra_body, ...) is dropped: Groq rejects unknown or unsupported
# fields with a 400 (docs/external/groq.md, section 1), which would end the call.
_FORWARDED_FIELDS = (
    "tools",
    "tool_choice",
    "temperature",
    "max_tokens",
    "top_p",
    "stop",
)

router = APIRouter(dependencies=[Depends(require_secret)])


class ChatCompletionRequest(BaseModel):
    """An OpenAI chat/completions body; only _FORWARDED_FIELDS reach Groq."""

    model_config = ConfigDict(extra="allow")

    messages: list[dict[str, Any]]


class ProxyError(BaseModel):
    """Returned with HTTP 502 when Groq cannot answer."""

    error: str


def _with_our_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put our system prompt before ElevenLabs' own system text, or add it.

    Also drops `name` from messages, which Groq rejects with a 400.
    """
    ours = build_system_prompt(hotel_today())
    out = [{k: v for k, v in m.items() if k != "name"} for m in messages]
    for i, message in enumerate(out):
        if message.get("role") == "system":
            out[i] = {**message, "content": f"{ours}\n\n{message.get('content') or ''}"}
            return out
    return [{"role": "system", "content": ours}, *out]


def _reply_from_sse(raw: bytes) -> Any:
    """Rebuild the reply from the stream, for the trace: text and tool names."""
    text: list[str] = []
    tools: list[str] = []
    for line in raw.decode(errors="replace").splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            delta = json.loads(line[6:])["choices"][0]["delta"]
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        text.append(delta.get("content") or "")
        for call in delta.get("tool_calls") or []:
            name = (call.get("function") or {}).get("name")
            if name:
                tools.append(name)
    reply = "".join(text)
    return {"content": reply, "tool_calls": tools} if tools else reply


def _trace(
    call_id: str,
    language: Language,
    model: str,
    messages: list[dict[str, Any]],
    raw: bytes,
) -> None:
    """Record the request as one generation in the call's session."""
    last_user = next(
        (m.get("content") for m in reversed(messages) if m.get("role") == "user"), ""
    )
    with (
        observability.call_session(call_id, language),
        observability.turn_span(str(last_user), name=LLM_TRACE_NAME),
        observability.generation(model, messages) as gen,
    ):
        gen.update(output=_reply_from_sse(raw))


async def _relay(
    upstream: httpx.Response,
    call_id: str,
    language: Language,
    model: str,
    messages: list[dict[str, Any]],
) -> AsyncIterator[bytes]:
    """Pass Groq's (decompressed) bytes through, then trace what was said.

    The trace runs before the stream is closed: closing can raise when the
    client disconnects, and the trace must not be skipped.
    """
    received = bytearray()
    try:
        async for chunk in upstream.aiter_bytes():
            received.extend(chunk)
            yield chunk
    finally:
        try:
            _trace(call_id, language, model, messages, bytes(received))
        finally:
            await upstream.aclose()


@router.post("/llm/v1/chat/completions", response_model=None)
# Whether ElevenLabs appends /chat/completions to the configured URL is unverified.
@router.post("/llm/v1/chat/completions/chat/completions", response_model=None)
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
    services: Annotated[Services, Depends(get_services)],
    x_call_id: Annotated[str, Header()] = "unknown",
) -> StreamingResponse | JSONResponse:
    """Forward one ElevenLabs LLM request to Groq and stream the answer back.

    Args:
        request: The raw request, to log which path ElevenLabs used.
        body: The chat/completions body.
        services: Settings and the shared HTTP client.
        x_call_id: system__conversation_id, if ElevenLabs resolves it in headers.

    Returns:
        Groq's SSE stream, or 502 when Groq fails before streaming.
    """
    extra = body.model_extra or {}
    # Field names only: which path and fields ElevenLabs sends is still unverified.
    logger.info(
        "custom LLM request on %s, not forwarded: %s",
        request.url.path,
        sorted(set(extra) - set(_FORWARDED_FIELDS)),
    )
    settings = services.settings
    language = call_language(x_call_id, body.messages, settings.agent_language)
    messages = _with_our_prompt(body.messages)
    payload = {
        **{k: v for k, v in extra.items() if k in _FORWARDED_FIELDS},
        "model": settings.groq_model,
        "stream": True,
        "messages": messages,
    }
    upstream_request = services.http.build_request(
        "POST",
        GROQ_CHAT_URL,
        json=payload,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        timeout=_GROQ_TIMEOUT,
    )
    try:
        upstream = await services.http.send(upstream_request, stream=True)
    except httpx.HTTPError as error:
        logger.warning("Groq unreachable: %s", type(error).__name__)
        return JSONResponse(ProxyError(error="upstream_unreachable").model_dump(), 502)
    if upstream.status_code != 200:
        await upstream.aclose()
        logger.warning("Groq returned HTTP %s", upstream.status_code)
        return JSONResponse(ProxyError(error="upstream_error").model_dump(), 502)
    return StreamingResponse(
        _relay(upstream, x_call_id, language, settings.groq_model, messages),
        media_type="text/event-stream",
        # Closes Groq's stream even if the response body is never iterated.
        background=BackgroundTask(upstream.aclose),
    )
