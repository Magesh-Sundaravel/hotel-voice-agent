"""ElevenLabs server tools: one generic webhook, POST /tools/{name}.

ElevenLabs sends the tool's arguments as the JSON body, plus two fields bound to
system dynamic variables so the model never generates them: `call_id`
(system__conversation_id) and `caller_phone` (system__caller_id). The request must
carry the shared secret in X-Webhook-Secret. See docs/architecture.md.
"""

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
from src.db.hotel import HotelRepository
from src.email.sender import EmailSender
from src.tools.context import CallContext
from src.tools.stay import E164

WEBHOOK_TRACE_NAME = "handle-tool-webhook"

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """What the webhooks run against; built once at startup."""

    hotel: HotelRepository
    bookings: BookingRepository
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
    arguments = json.dumps(body.model_extra or {})
    # The caller's language is not known to tools yet (docs/architecture.md).
    with (
        observability.call_session(body.call_id, "unknown"),
        observability.turn_span(arguments, name=WEBHOOK_TRACE_NAME),
    ):
        return await run_tool(
            registry,
            ToolCall(id=f"{body.call_id}:{name}", name=name, arguments=arguments),
        )
