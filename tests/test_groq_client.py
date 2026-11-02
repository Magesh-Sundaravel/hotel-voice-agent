"""Tests for the Groq client wire format (seam C)."""

import json

import httpx
import pytest

from src.agent.llm import AssistantMessage, ChatMessage, GroqClient, ToolCall, ToolSpec

TOOL = ToolSpec(
    name="check_availability",
    description="List free room types.",
    parameters={"type": "object", "properties": {}},
)


def make_client(
    handler: httpx.MockTransport,
) -> GroqClient:
    """Build a client whose HTTP calls go to the mock transport."""
    return GroqClient(
        api_key="test-key",
        model="openai/gpt-oss-120b",
        http=httpx.AsyncClient(transport=handler),
    )


@pytest.mark.asyncio
async def test_sends_groq_request_and_parses_tool_calls() -> None:
    """Request carries auth, model, tools and messages; tool_calls are parsed."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "check_availability",
                                        "arguments": '{"guests": 2}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    client = make_client(httpx.MockTransport(handler))
    reply = await client.complete(
        [
            ChatMessage(role="system", content="Be brief."),
            ChatMessage(role="user", content="Hi"),
            ChatMessage(role="tool", content='{"ok": true}', tool_call_id="call_0"),
        ],
        [TOOL],
    )

    request = seen[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": "List free room types.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert body["messages"][2] == {
        "role": "tool",
        "content": '{"ok": true}',
        "tool_call_id": "call_0",
    }
    assert reply == AssistantMessage(
        content=None,
        tool_calls=[
            ToolCall(id="call_1", name="check_availability", arguments='{"guests": 2}')
        ],
    )


def ok_response() -> httpx.Response:
    """A minimal successful completion."""
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": "Ciao"}}]}
    )


@pytest.mark.asyncio
async def test_retries_on_429_waiting_as_long_as_retry_after_says() -> None:
    """Two 429s then a 200: the client waits each time and returns the reply."""
    responses = [
        httpx.Response(429, headers={"retry-after": "7"}),
        httpx.Response(429),
        ok_response(),
    ]
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    client = GroqClient(
        api_key="k",
        model="m",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: responses.pop(0))
        ),
        sleep=fake_sleep,
    )

    reply = await client.complete([ChatMessage(role="user", content="Hi")], [])

    assert reply == AssistantMessage(content="Ciao")
    assert waits == [7, 5]  # Retry-After when present, else the 5 s default


@pytest.mark.asyncio
async def test_gives_up_after_three_retries() -> None:
    """A persistent 429 raises after 1 try + 3 retries, so the caller sees it."""
    attempts: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(429)

    async def no_sleep(_: float) -> None:
        return None

    client = GroqClient(
        api_key="k",
        model="m",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=no_sleep,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.complete([ChatMessage(role="user", content="Hi")], [])
    assert len(attempts) == 4


@pytest.mark.asyncio
async def test_a_non_numeric_retry_after_falls_back_to_the_default_wait() -> None:
    """Retry-After may be an HTTP date; the client must not crash on it."""
    responses = [
        httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        ok_response(),
    ]
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    client = GroqClient(
        api_key="k",
        model="m",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: responses.pop(0))
        ),
        sleep=fake_sleep,
    )

    await client.complete([ChatMessage(role="user", content="Hi")], [])

    assert waits == [5]
