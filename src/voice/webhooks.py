"""ElevenLabs server tools: one generic webhook, POST /tools/{name}.

ElevenLabs sends the tool's arguments as the JSON body, plus two fields bound to
system dynamic variables so the model never generates them: `call_id`
(system__conversation_id) and `caller_phone` (system__caller_id). The request must
carry the shared secret in X-Webhook-Secret. See docs/architecture.md.
"""

import asyncio
import hmac
import json
import logging
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src import observability
from src.agent.llm import ToolCall
from src.agent.loop import run_tool
from src.agent.registry import build_registry
from src.config import Settings
from src.db.bookings import BookingRepository
from src.db.calls import CallLogError, CallLogRepository
from src.db.hotel import HotelRepository
from src.email.sender import EmailSender
from src.tools.context import CallContext
from src.tools.stay import E164
from src.voice.call_language import (
    Language,
    as_language,
    known_language,
    remember_language,
)
from src.voice.call_log import call_event

WEBHOOK_TRACE_NAME = "handle-tool-webhook"
# The call log write comes after the tool answers, so keep it short.
CALL_LOG_TIMEOUT_S = 0.5

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """What the webhooks run against; built once at startup."""

    hotel: HotelRepository
    bookings: BookingRepository
    calls: CallLogRepository
    sender: EmailSender
    settings: Settings
    http: httpx.AsyncClient


def get_services(request: Request) -> Services:
    """Return the services built by the app's lifespan."""
    return request.app.state.services  # type: ignore[no-any-return]


class ToolRequest(BaseModel):
    """The webhook body: call facts plus the tool's own arguments as extra keys."""

    model_config = ConfigDict(extra="allow")

    call_id: str
    caller_phone: str | None = None


async def require_secret(
    request: Request,
    services: Annotated[Services, Depends(get_services)],
    x_webhook_secret: Annotated[str, Header()] = "",
) -> None:
    """Refuse the request unless X-Webhook-Secret matches; an unset secret refuses all.

    Used as a router dependency, so it runs before the body is validated and an
    unauthenticated caller never sees validation details.
    """
    expected = services.settings.webhook_secret
    if not expected or not hmac.compare_digest(
        x_webhook_secret.encode(), expected.encode()
    ):
        reason = "WEBHOOK_SECRET is unset" if not expected else "secret mismatch"
        logger.warning("refused %s: %s", request.url.path, reason)
        raise HTTPException(status_code=401, detail="unauthorized")


router = APIRouter(dependencies=[Depends(require_secret)])


@router.post("/tools/{name}", response_model=None)
async def call_tool(
    name: str,
    body: ToolRequest,
    services: Annotated[Services, Depends(get_services)],
) -> BaseModel:
    """Run one tool for ElevenLabs and return its result.

    Args:
        name: Tool name, as in the registry.
        body: call_id, caller_phone and the tool's arguments.
        services: Repositories, email sender and settings.

    Returns:
        The tool's result. Tool failures are `{ok: false, reason}` with HTTP 200,
        so the agent can say them; only a bad secret (401) or an unknown tool (404)
        is an HTTP error.
    """
    # A withheld number may arrive empty or as a word; only E.164 is a caller ID.
    phone = (
        body.caller_phone
        if body.caller_phone and E164.match(body.caller_phone)
        else None
    )
    ctx = CallContext(call_id=body.call_id, caller_phone=phone)
    registry = build_registry(
        services.hotel, services.bookings, ctx, sender=services.sender
    )
    if name not in registry:
        raise HTTPException(status_code=404, detail="unknown tool")
    extra = body.model_extra or {}
    arguments = json.dumps(extra)
    # A language the model passed is the freshest; else what the /llm proxy saw.
    # Only those reach the call log; the default is a guess, for the trace tag only.
    spoken = as_language(extra.get("language")) if "language" in extra else None
    if spoken:
        remember_language(body.call_id, spoken)
    known = known_language(body.call_id)
    with (
        observability.call_session(
            body.call_id, known or services.settings.agent_language
        ),
        observability.turn_span(arguments, name=WEBHOOK_TRACE_NAME),
    ):
        result = await run_tool(
            registry,
            ToolCall(id=f"{body.call_id}:{name}", name=name, arguments=arguments),
        )
    await _log_call(services.calls, body.call_id, name, extra, result, known)
    return result


async def _log_call(
    calls: CallLogRepository,
    call_id: str,
    name: str,
    arguments: dict[str, object],
    result: BaseModel,
    language: Language | None,
) -> None:
    """Record the tool call in the call log; a failure is a warning, never an error.

    Like tracing, the call log must never break a call. Only the call_id and the
    tool name are logged.
    """
    try:
        async with asyncio.timeout(CALL_LOG_TIMEOUT_S):
            await calls.record(call_event(call_id, name, arguments, result, language))
    except (CallLogError, TimeoutError) as exc:
        logger.warning(
            "call log write failed for call %s after %s: %s",
            call_id,
            name,
            type(exc).__name__ if isinstance(exc, TimeoutError) else exc,
        )
