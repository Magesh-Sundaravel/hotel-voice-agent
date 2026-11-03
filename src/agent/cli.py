"""Text REPL for talking to the agent without voice: `uv run python -m src.agent.cli`.

Pass `--caller-phone +12025550101` to call as a seed guest (Giulia Rossi); leave it
out to call with a withheld number. Bookings live in memory for this session only.
"""

import argparse
import asyncio
import uuid
from datetime import date

import httpx

from src.agent.llm import ChatMessage, GroqClient
from src.agent.loop import run_turn
from src.agent.prompt import build_system_prompt
from src.agent.registry import build_registry
from src.config import Settings
from src.db.seed import seed_repository
from src.tools.context import CallContext


async def main(caller_phone: str | None) -> None:
    """Chat with the agent until EOF or an empty line.

    Args:
        caller_phone: The caller ID to present, or None for a withheld number.
    """
    settings = Settings()
    repo = seed_repository()
    ctx = CallContext(call_id=f"cli-{uuid.uuid4().hex[:8]}", caller_phone=caller_phone)
    registry = build_registry(repo, repo, ctx)
    async with httpx.AsyncClient(timeout=15) as http:
        llm = GroqClient(settings.groq_api_key, settings.groq_model, http)
        history = [
            ChatMessage(role="system", content=build_system_prompt(date.today()))
        ]
        while True:
            try:
                text = input("caller> ").strip()
            except EOFError:
                break
            if not text:
                break
            try:
                result = await run_turn(llm, registry, history, text)
            except httpx.HTTPError as error:
                print(f"error: {type(error).__name__}")
                continue
            history = result.history
            print(f"agent> {result.reply}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chat with the agent in text.")
    parser.add_argument("--caller-phone", help="caller ID in E.164, e.g. +12025550101")
    asyncio.run(main(parser.parse_args().caller_phone))
