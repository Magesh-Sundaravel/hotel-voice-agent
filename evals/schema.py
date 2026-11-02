"""Schema of evals/golden.json, the source of truth for the eval dataset."""

from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

GOLDEN_PATH = Path(__file__).parent / "golden.json"


class ExpectedToolCall(BaseModel):
    """A tool call the agent must make. Only the listed args are compared."""

    name: str
    args: dict[str, Any] = {}


class TurnExpect(BaseModel):
    """What must be true after one caller turn."""

    tool_calls: list[ExpectedToolCall] = []
    must_not_call_tools: bool = False
    exclusive: bool = False


class Turn(BaseModel):
    """One scripted caller line and its expectations."""

    caller: str
    expect: TurnExpect = TurnExpect()


class EvalCase(BaseModel):
    """A scripted conversation. Replies must be in `language`."""

    id: str
    language: Literal["it", "en"]
    tags: list[str] = []
    turns: list[Turn] = Field(min_length=1)


class Dataset(BaseModel):
    """The whole golden dataset. `today` is injected into the prompt and tools."""

    today: date
    cases: list[EvalCase]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "Dataset":
        """Reject duplicate case ids (they become Langfuse dataset item ids)."""
        ids = [c.id for c in self.cases]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        return self
