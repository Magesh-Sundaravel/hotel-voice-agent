"""Dry run: send one fake call through the agent loop and trace it to Langfuse.

Uses a scripted LLM (no Groq key needed) and an in-memory hotel. The caller text
holds a fake email and phone so you can check in Langfuse that they are masked.

Run: `uv run python -m evals.trace_dryrun`
"""

import asyncio
import uuid

from src import observability
from src.agent.llm import AssistantMessage, ChatMessage, ToolCall, ToolSpec
from src.agent.loop import run_turn
from src.agent.registry import build_registry
from src.db.bookings import InMemoryBookingRepository
from src.db.hotel import RoomType
from src.tools.context import CallContext

USER_TEXT = (
    "Hi, I'm Mario Rossi, mario.rossi@example.com, +39 333 123 4567. "
    "Do you have a room for two from 2099-12-10 to 2099-12-12?"
)


class ScriptedLLM:
    """Asks for availability first, then answers in words."""

    def __init__(self) -> None:
        """Start before the tool call."""
        self._asked = False

    async def complete(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> AssistantMessage:
        """Return a tool call on the first pass, a spoken reply after."""
        if self._asked:
            return AssistantMessage(content="Yes, we have a Superior room free.")
        self._asked = True
        call = ToolCall(
            id="c1",
            name="check_availability",
            arguments='{"check_in": "2099-12-10", "check_out": "2099-12-12", "guests": 2}',
        )
        return AssistantMessage(content=None, tool_calls=[call])


async def main() -> None:
    """Run one traced turn inside a call session, then flush."""
    repo = InMemoryBookingRepository(
        room_types=[RoomType(name="Superior", max_guests=2, rooms=2)],
        rates=[],
        stays=[],
    )
    call_id = f"dryrun-{uuid.uuid4().hex[:8]}"
    with observability.call_session(call_id, "en"):
        result = await run_turn(
            ScriptedLLM(),
            build_registry(repo, repo, CallContext(call_id=call_id)),
            [],
            USER_TEXT,
        )
    observability.flush()
    print(f"call_id: {call_id}")
    print(f"reply:   {result.reply}")


if __name__ == "__main__":
    asyncio.run(main())
