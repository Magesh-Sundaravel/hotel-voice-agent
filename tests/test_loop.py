"""Tests for the agent loop (seam B), using a scripted fake LLM."""

import asyncio
import json
from contextlib import nullcontext
from datetime import date

import pytest

from src import observability
from src.agent.llm import AssistantMessage, ChatMessage, ToolCall, ToolSpec
from src.agent.loop import FALLBACK_REPLY, run_turn
from src.agent.registry import Tool, build_registry
from src.db.bookings import InMemoryBookingRepository
from src.db.hotel import RoomType
from src.tools.check_availability import AvailabilityInput
from src.tools.context import CallContext
from tests.test_observability import FakeClient


class ScriptedLLM:
    """Returns pre-set assistant messages in order and records what it saw."""

    def __init__(self, script: list[AssistantMessage]) -> None:
        """Store the replies to hand out."""
        self._script = list(script)
        self.seen: list[list[ChatMessage]] = []
        self.tools_offered: list[int] = []

    async def complete(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> AssistantMessage:
        """Record a copy of the conversation and return the next reply."""
        self.seen.append(list(messages))
        self.tools_offered.append(len(tools))
        return self._script.pop(0)


def make_registry(today: date | None = None):
    """Registry over a one-room-type hotel."""
    repo = InMemoryBookingRepository(
        room_types=[RoomType(name="Superior", max_guests=2, rooms=2)],
        rates=[],
        stays=[],
    )
    return build_registry(repo, repo, CallContext(call_id="test"), today=today)


@pytest.mark.asyncio
async def test_plain_reply_is_returned_and_added_to_history() -> None:
    """With no tool calls the model's text is the reply."""
    llm = ScriptedLLM([AssistantMessage(content="Buongiorno!")])
    history = [ChatMessage(role="system", content="You are a receptionist.")]

    result = await run_turn(llm, make_registry(), history, "Ciao")

    assert result.reply == "Buongiorno!"
    assert [(m.role, m.content) for m in result.history] == [
        ("system", "You are a receptionist."),
        ("user", "Ciao"),
        ("assistant", "Buongiorno!"),
    ]
    assert len(history) == 1  # input history is not mutated


@pytest.mark.asyncio
async def test_tool_call_result_is_fed_back_to_the_model() -> None:
    """A tool call runs the real tool and the model sees its JSON result."""
    call = ToolCall(
        id="c1",
        name="check_availability",
        arguments='{"check_in": "2099-12-10", "check_out": "2099-12-12", "guests": 2}',
    )
    llm = ScriptedLLM(
        [
            AssistantMessage(content=None, tool_calls=[call]),
            AssistantMessage(content="We have a Superior free."),
        ]
    )

    result = await run_turn(
        llm, make_registry(), [ChatMessage(role="system", content="s")], "Room?"
    )

    assert result.reply == "We have a Superior free."
    assistant, tool_msg = llm.seen[1][-2:]
    assert assistant.role == "assistant"
    assert assistant.tool_calls == [call]
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == "c1"
    assert json.loads(tool_msg.content or "") == {
        "ok": True,
        "options": [{"room_type": "Superior", "rooms_free": 2}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments", "reason"),
    [
        ("book_the_moon", "{}", "unknown_tool"),
        ("check_availability", "not json", "invalid_arguments"),
        ("check_availability", '{"guests": "many"}', "invalid_arguments"),
    ],
)
async def test_bad_tool_call_becomes_error_result_not_a_crash(
    name: str, arguments: str, reason: str
) -> None:
    """The model gets {ok: false, reason} and can recover in the same turn."""
    call = ToolCall(id="c1", name=name, arguments=arguments)
    llm = ScriptedLLM(
        [
            AssistantMessage(content=None, tool_calls=[call]),
            AssistantMessage(content="Sorry, let me try again."),
        ]
    )

    result = await run_turn(
        llm, make_registry(), [ChatMessage(role="system", content="s")], "Room?"
    )

    assert result.reply == "Sorry, let me try again."
    tool_msg = llm.seen[1][-1]
    assert tool_msg.tool_call_id == "c1"
    assert json.loads(tool_msg.content or "") == {"ok": False, "reason": reason}


@pytest.mark.asyncio
async def test_tool_rounds_are_capped_then_model_must_answer_without_tools() -> None:
    """After 5 tool rounds the model is called once more with no tools."""
    call = ToolCall(
        id="c",
        name="check_availability",
        arguments='{"check_in": "2099-12-10", "check_out": "2099-12-12", "guests": 2}',
    )
    llm = ScriptedLLM(
        [AssistantMessage(content=None, tool_calls=[call]) for _ in range(5)]
        + [AssistantMessage(content="Let me send you an email.")]
    )

    result = await run_turn(
        llm, make_registry(), [ChatMessage(role="system", content="s")], "Room?"
    )

    assert result.reply == "Let me send you an email."
    assert llm.tools_offered == [7, 7, 7, 7, 7, 0]


@pytest.mark.asyncio
async def test_registry_uses_the_injected_today() -> None:
    """Tools judge dates against the injected today, not the system clock."""
    call = ToolCall(
        id="c1",
        name="check_availability",
        arguments='{"check_in": "2026-12-10", "check_out": "2026-12-12", "guests": 2}',
    )
    llm = ScriptedLLM(
        [
            AssistantMessage(content=None, tool_calls=[call]),
            AssistantMessage(content="ok"),
        ]
    )

    await run_turn(
        llm,
        make_registry(today=date(2099, 1, 1)),
        [ChatMessage(role="system", content="s")],
        "Room?",
    )

    assert json.loads(llm.seen[1][-1].content or "") == {
        "ok": False,
        "reason": "invalid_dates",
    }


VALID_ARGS = '{"check_in": "2099-12-10", "check_out": "2099-12-12", "guests": 2}'


@pytest.mark.asyncio
async def test_stubborn_tool_calls_after_the_cap_leave_a_valid_history() -> None:
    """If the model emits tool calls even with no tools offered, none dangle."""
    call = ToolCall(id="c", name="check_availability", arguments=VALID_ARGS)
    llm = ScriptedLLM(
        [AssistantMessage(content=None, tool_calls=[call]) for _ in range(6)]
    )

    result = await run_turn(
        llm, make_registry(), [ChatMessage(role="system", content="s")], "Room?"
    )

    assert result.reply == FALLBACK_REPLY
    answered = {m.tool_call_id for m in result.history if m.role == "tool"}
    requested = {c.id for m in result.history for c in m.tool_calls or []}
    assert requested <= answered


async def run_with_tool(tool: Tool) -> tuple[str, ScriptedLLM]:
    """Run one turn in which the model calls the given (broken) tool once."""
    call = ToolCall(id="c1", name=tool.name, arguments=VALID_ARGS)
    llm = ScriptedLLM(
        [
            AssistantMessage(content=None, tool_calls=[call]),
            AssistantMessage(content="Sorry, I cannot check right now."),
        ]
    )
    result = await run_turn(
        llm,
        {tool.name: tool},
        [ChatMessage(role="system", content="s")],
        "Room?",
    )
    return result.reply, llm


@pytest.mark.asyncio
async def test_a_tool_that_raises_becomes_an_error_result() -> None:
    """An exception inside a tool is reported to the model, not raised."""

    async def boom(_: object) -> object:
        raise RuntimeError("database is down")

    tool = Tool(
        name="check_availability",
        description="x",
        input_model=AvailabilityInput,
        handler=boom,
    )

    reply, llm = await run_with_tool(tool)

    assert reply == "Sorry, I cannot check right now."
    assert json.loads(llm.seen[1][-1].content or "") == {
        "ok": False,
        "reason": "tool_error",
    }


@pytest.mark.asyncio
async def test_a_slow_tool_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool slower than the latency budget is cut off with an error result."""
    monkeypatch.setattr("src.agent.loop.TOOL_TIMEOUT_S", 0.01)

    async def slow(_: object) -> object:
        await asyncio.sleep(5)

    tool = Tool(
        name="check_availability",
        description="x",
        input_model=AvailabilityInput,
        handler=slow,
    )

    _, llm = await run_with_tool(tool)

    assert json.loads(llm.seen[1][-1].content or "") == {
        "ok": False,
        "reason": "tool_timeout",
    }


# --- tracing ---------------------------------------------------------------


@pytest.fixture
def fake_langfuse(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """Route observability to a recording fake."""
    fake = FakeClient()
    monkeypatch.setattr(observability, "_get_client", lambda: fake)
    monkeypatch.setattr(
        observability, "propagate_attributes", lambda **_: nullcontext()
    )
    return fake


@pytest.mark.asyncio
async def test_a_turn_is_traced_with_its_tool_calls(fake_langfuse: FakeClient) -> None:
    """One turn span (caller text -> reply) with a tool span per tool call."""
    call = ToolCall(id="c1", name="check_availability", arguments=VALID_ARGS)
    llm = ScriptedLLM(
        [
            AssistantMessage(content=None, tool_calls=[call]),
            AssistantMessage(content="We have a Superior free."),
        ]
    )

    with observability.call_session("call-1", "en"):
        await run_turn(
            llm, make_registry(), [ChatMessage(role="system", content="s")], "Room?"
        )

    turn, tool = fake_langfuse.observations
    assert turn.started["name"] == "handle-caller-turn"
    assert turn.started["input"] == "Room?"
    assert turn.updates == [{"output": "We have a Superior free."}]
    assert tool.started["as_type"] == "tool"
    assert tool.started["name"] == "check_availability"
    assert tool.started["input"] == VALID_ARGS
    assert json.loads(tool.updates[0]["output"])["ok"] is True
    assert "level" not in tool.updates[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments", "reason"),
    [
        ("book_the_moon", "{}", "unknown_tool"),
        ("check_availability", "not json", "invalid_arguments"),
    ],
)
async def test_failed_tool_calls_are_marked_as_errors(
    fake_langfuse: FakeClient, name: str, arguments: str, reason: str
) -> None:
    """A tool span for a call that failed carries level ERROR and the reason."""
    call = ToolCall(id="c1", name=name, arguments=arguments)
    llm = ScriptedLLM(
        [
            AssistantMessage(content=None, tool_calls=[call]),
            AssistantMessage(content="Sorry."),
        ]
    )

    with observability.call_session("call-1", "it"):
        await run_turn(
            llm, make_registry(), [ChatMessage(role="system", content="s")], "Room?"
        )

    tool = fake_langfuse.observations[1]
    assert tool.updates[0]["level"] == "ERROR"
    assert tool.updates[0]["status_message"] == reason


@pytest.mark.asyncio
async def test_a_tracing_failure_does_not_change_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Langfuse blows up, the caller still gets the answer."""

    class Exploding:
        def start_as_current_observation(self, **_: object) -> object:
            raise RuntimeError("langfuse is down")

    monkeypatch.setattr(observability, "_get_client", lambda: Exploding())
    monkeypatch.setattr(
        observability, "propagate_attributes", lambda **_: nullcontext()
    )
    call = ToolCall(id="c1", name="check_availability", arguments=VALID_ARGS)
    llm = ScriptedLLM(
        [
            AssistantMessage(content=None, tool_calls=[call]),
            AssistantMessage(content="We have a Superior free."),
        ]
    )

    with observability.call_session("call-1", "en"):
        result = await run_turn(
            llm, make_registry(), [ChatMessage(role="system", content="s")], "Room?"
        )

    assert result.reply == "We have a Superior free."
