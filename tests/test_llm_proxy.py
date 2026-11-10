"""Tests for the /llm proxy: ElevenLabs custom LLM -> Groq, streamed through."""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
import pytest_asyncio

from src import observability
from src.agent.llm import GROQ_CHAT_URL
from src.config import Settings
from src.db.seed import seed_repository
from src.email.sender import FakeEmailSender
from src.main import app
from src.voice.webhooks import Services, get_services
from tests.test_observability import FakeClient

SECRET = "s3cret"
HEADERS = {"X-Webhook-Secret": SECRET, "X-Call-Id": "conv-9"}
SSE = (
    'data: {"choices":[{"delta":{"role":"assistant","content":"Buon"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"giorno"}}]}\n\n'
    "data: [DONE]\n\n"
)
ELEVENLABS_BODY = {
    "model": "whatever-elevenlabs-sends",
    "stream": True,
    "messages": [
        {"role": "system", "content": "ElevenLabs system text"},
        {"role": "user", "content": "Ciao", "name": "caller"},
    ],
    "tools": [{"type": "function", "function": {"name": "check_availability"}}],
    "user_id": "u1",
    "elevenlabs_extra_body": {"x": 1},
}


class FakeGroq:
    """Streams SSE back and records what it was sent."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "boom"})
        return httpx.Response(
            200, content=SSE.encode(), headers={"content-type": "text/event-stream"}
        )


@pytest_asyncio.fixture
async def groq() -> AsyncIterator[FakeGroq]:
    """The app with a fake Groq behind the proxy."""
    fake = FakeGroq()
    repo = seed_repository()
    services = Services(
        hotel=repo,
        bookings=repo,
        sender=FakeEmailSender(),
        settings=Settings(webhook_secret=SECRET, groq_api_key="gk", groq_model="gm"),
        http=httpx.AsyncClient(transport=httpx.MockTransport(fake)),
    )
    app.dependency_overrides[get_services] = lambda: services
    yield fake
    app.dependency_overrides.clear()


async def _post(path: str, headers: dict[str, str] = HEADERS) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post(path, json=ELEVENLABS_BODY, headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/llm/v1/chat/completions", "/llm/v1/chat/completions/chat/completions"]
)
async def test_streams_groqs_reply_back_unchanged(groq: FakeGroq, path: str) -> None:
    """Both URLs work until we know whether ElevenLabs appends the path."""
    response = await _post(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == SSE


@pytest.mark.asyncio
async def test_forwards_with_our_prompt_model_and_key(groq: FakeGroq) -> None:
    """Our prompt first, ElevenLabs' after it; our model; no ElevenLabs extras."""
    await _post("/llm/v1/chat/completions")

    (request,) = groq.requests
    assert str(request.url) == GROQ_CHAT_URL
    assert request.headers["Authorization"] == "Bearer gk"
    sent = json.loads(request.content)
    assert sent["model"] == "gm"
    assert sent["stream"] is True
    assert "elevenlabs_extra_body" not in sent
    assert "user_id" not in sent
    assert sent["tools"] == ELEVENLABS_BODY["tools"]
    system, user = sent["messages"]
    assert system["role"] == "system"
    assert system["content"].startswith("You are the phone receptionist")
    assert system["content"].endswith("ElevenLabs system text")
    assert user == {"role": "user", "content": "Ciao"}


@pytest.mark.asyncio
async def test_a_wrong_secret_is_refused(groq: FakeGroq) -> None:
    """Nobody else can spend the Groq key."""
    response = await _post(
        "/llm/v1/chat/completions", headers={"X-Webhook-Secret": "nope"}
    )

    assert response.status_code == 401
    assert groq.requests == []


@pytest.mark.asyncio
async def test_the_secret_is_checked_before_the_body(groq: FakeGroq) -> None:
    """An unauthenticated caller gets 401 even with a malformed body."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/llm/v1/chat/completions", json={"junk": 1})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_groq_error_is_a_502(groq: FakeGroq) -> None:
    """ElevenLabs sees a gateway error, not a half stream."""
    groq.status = 500

    response = await _post("/llm/v1/chat/completions")

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_records_one_generation_in_the_call_session(
    groq: FakeGroq, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reply text is traced once the stream ends, keyed by X-Call-Id."""
    fake = FakeClient()
    monkeypatch.setattr(observability, "_get_client", lambda: fake)
    propagated: list[dict[str, Any]] = []

    @contextmanager
    def fake_propagate(**kwargs: Any) -> Iterator[None]:
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(observability, "propagate_attributes", fake_propagate)

    await _post("/llm/v1/chat/completions")

    assert propagated[0]["session_id"] == "conv-9"
    generation = next(
        o for o in fake.observations if o.started["as_type"] == "generation"
    )
    assert generation.started["model"] == "gm"
    assert {"output": "Buongiorno"} in generation.updates


@pytest.mark.asyncio
async def test_a_broken_tracer_does_not_break_the_reply(
    groq: FakeGroq, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If Langfuse is down the caller still hears the answer."""

    class BrokenClient(FakeClient):
        def start_as_current_observation(self, **kwargs: Any) -> Any:
            raise RuntimeError("langfuse down")

    broken = BrokenClient()
    monkeypatch.setattr(observability, "_get_client", lambda: broken)

    response = await _post("/llm/v1/chat/completions")

    assert response.text == SSE
