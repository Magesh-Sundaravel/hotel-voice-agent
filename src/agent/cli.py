"""Text REPL for talking to the agent without voice: `uv run python -m src.agent.cli`."""

import asyncio
from datetime import date

import httpx

from src.agent.llm import ChatMessage, GroqClient
from src.agent.loop import run_turn
from src.agent.prompt import build_system_prompt
from src.agent.registry import build_registry
from src.config import Settings
from src.db.seed import seed_repository


async def main() -> None:
    """Chat with the agent until EOF or an empty line."""
    settings = Settings()
    registry = build_registry(seed_repository())
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
    asyncio.run(main())
