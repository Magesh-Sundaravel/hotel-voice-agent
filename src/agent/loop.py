"""The agent loop: one user turn, with tool calls until the model answers."""

import asyncio
import logging

from pydantic import BaseModel, ValidationError

from src import observability
from src.agent.llm import ChatMessage, LLMClient, ToolCall
from src.agent.registry import Tool

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
TOOL_TIMEOUT_S = 1.5  # the latency budget for a tool, see .claude/rules/voice.md
# Last resort when the model gives no words. English only: the loop does not know
# the caller's language, and silence on a phone call is worse.
FALLBACK_REPLY = "Sorry, I can't check that right now."


class ToolFailure(BaseModel):
    """Error result for a call the loop could not run."""

    ok: bool = False
    reason: str


class TurnResult(BaseModel):
    """Outcome of one turn: the spoken reply and the updated history."""

    reply: str
    history: list[ChatMessage]


async def run_turn(
    llm: LLMClient,
    registry: dict[str, Tool],
    history: list[ChatMessage],
    user_text: str,
) -> TurnResult:
    """Run one caller turn and return the reply.

    Args:
        llm: The model client.
        registry: Tools the model may call.
        history: Conversation so far, starting with the system message.
        user_text: What the caller just said.

    Returns:
        The reply and a new history (the input list is not modified).
    """
    messages = [*history, ChatMessage(role="user", content=user_text)]
    specs = [t.spec() for t in registry.values()]
    with observability.turn_span(user_text) as turn:
        for round_number in range(MAX_TOOL_ROUNDS + 1):
            is_last = round_number == MAX_TOOL_ROUNDS
            # The last pass offers no tools, so the model has to answer in words.
            reply = await llm.complete(messages, [] if is_last else specs)
            if not reply.tool_calls or is_last:
                # Never keep tool calls we will not answer: the next request would fail.
                text = reply.content or FALLBACK_REPLY
                messages.append(ChatMessage(role="assistant", content=text))
                turn.update(output=text)
                return TurnResult(reply=text, history=messages)
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=reply.content,
                    tool_calls=reply.tool_calls,
                )
            )
            for call in reply.tool_calls:
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=await _run_tool(registry, call),
                        tool_call_id=call.id,
                    )
                )
    raise AssertionError("unreachable: the last round always returns")


async def _run_tool(registry: dict[str, Tool], call: ToolCall) -> str:
    """Run one tool call inside a trace span and return its JSON result."""
    with observability.tool_span(call.name, call.arguments) as span:
        result = await _execute_tool(registry, call)
        if isinstance(result, ToolFailure):
            span.update(
                output=result.model_dump_json(),
                level="ERROR",
                status_message=result.reason,
            )
        else:
            span.update(output=result.model_dump_json())
    return result.model_dump_json()


async def _execute_tool(registry: dict[str, Tool], call: ToolCall) -> BaseModel:
    """Run one tool call and return its result model. Never raises."""
    tool = registry.get(call.name)
    if tool is None:
        return ToolFailure(reason="unknown_tool")
    try:
        args = tool.input_model.model_validate_json(call.arguments)
    except ValidationError:
        return ToolFailure(reason="invalid_arguments")
    try:
        return await asyncio.wait_for(tool.handler(args), TOOL_TIMEOUT_S)
    except TimeoutError:
        logger.warning("tool %s timed out", call.name)
        return ToolFailure(reason="tool_timeout")
    except Exception as error:  # noqa: BLE001 - a tool must never crash the call
        # Log the tool and error type only: messages may carry guest data.
        logger.warning("tool %s failed: %s", call.name, type(error).__name__)
        return ToolFailure(reason="tool_error")
