"""Tool registry: the tools the agent can call, with their schemas."""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import cast

from pydantic import BaseModel, ConfigDict

from src.agent.llm import ToolSpec
from src.db.hotel import HotelRepository
from src.tools.check_availability import AvailabilityInput, check_availability
from src.tools.get_rates import GetRatesInput, get_rates


class Tool(BaseModel):
    """A callable tool: schema for the model plus the handler to run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[BaseModel]]

    def spec(self) -> ToolSpec:
        """Return the schema the model sees."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.input_model.model_json_schema(),
        )


def build_registry(repo: HotelRepository, today: date | None = None) -> dict[str, Tool]:
    """Build the tool registry bound to a hotel repository.

    Args:
        repo: Hotel inventory access.
        today: Override for the current date, so evals are deterministic.
    """

    async def _availability(inp: BaseModel) -> BaseModel:
        return await check_availability(repo, cast(AvailabilityInput, inp), today)

    async def _rates(inp: BaseModel) -> BaseModel:
        return await get_rates(repo, cast(GetRatesInput, inp), today)

    tools = [
        Tool(
            name="check_availability",
            description=(
                "List room types with a free room for the whole stay. "
                "Dates are YYYY-MM-DD; check_out is the departure day."
            ),
            input_model=AvailabilityInput,
            handler=_availability,
        ),
        Tool(
            name="get_rates",
            description=(
                "Price a stay for one room type. "
                "Dates are YYYY-MM-DD; check_out is the departure day."
            ),
            input_model=GetRatesInput,
            handler=_rates,
        ),
    ]
    return {t.name: t for t in tools}
