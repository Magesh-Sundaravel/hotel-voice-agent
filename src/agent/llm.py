"""LLM client for Groq's OpenAI-compatible chat completions API."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RETRIES = 3
DEFAULT_RETRY_WAIT_S = 5.0


class ToolSpec(BaseModel):
    """A tool the model may call. `parameters` is a JSON Schema object."""

    name: str
    description: str
    parameters: dict[str, Any]


class ToolCall(BaseModel):
    """A tool call requested by the model. `arguments` is a JSON string."""

    id: str
    name: str
    arguments: str


class ChatMessage(BaseModel):
    """One message in the conversation sent to the model."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def to_wire(self) -> dict[str, Any]:
        """Serialize to the API format. Never sends `name` (Groq rejects it)."""
        wire = self.model_dump(exclude_none=True, exclude={"tool_calls"})
        if self.tool_calls:
            wire["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        return wire


class AssistantMessage(BaseModel):
    """The model's reply: text, tool calls, or both."""

    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMClient(Protocol):
    """Anything that can turn a conversation into the next assistant message."""

    async def complete(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> AssistantMessage:
        """Return the model's next message."""
        ...


def _retry_wait(response: httpx.Response) -> float:
    """Seconds to wait after a 429: Retry-After if it is a number, else the default."""
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return DEFAULT_RETRY_WAIT_S


class GroqClient:
    """LLMClient backed by Groq."""

    def __init__(
        self,
        api_key: str,
        model: str,
        http: httpx.AsyncClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Store credentials, model id, the shared HTTP client and the sleep function."""
        self._api_key = api_key
        self._model = model
        self._http = http
        self._sleep = sleep

    async def complete(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> AssistantMessage:
        """Call chat/completions and parse the first choice."""
        body = {
            "model": self._model,
            "messages": [m.to_wire() for m in messages],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ],
        }
        for attempt in range(MAX_RETRIES + 1):
            response = await self._http.post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            if response.status_code != 429 or attempt == MAX_RETRIES:
                break
            await self._sleep(_retry_wait(response))
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        return AssistantMessage(
            content=message.get("content"),
            tool_calls=[
                ToolCall(
                    id=c["id"],
                    name=c["function"]["name"],
                    arguments=c["function"]["arguments"],
                )
                for c in message.get("tool_calls") or []
            ],
        )
