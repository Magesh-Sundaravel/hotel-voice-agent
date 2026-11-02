"""Tool registry: the tools the agent can call, with their schemas."""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import cast

from pydantic import BaseModel, ConfigDict

from src.agent.llm import ToolSpec
from src.db.hotel import HotelRepository
from src.tools import MAX_STAY_NIGHTS
from src.tools.check_availability import AvailabilityInput, check_availability
from src.tools.get_rates import GetRatesInput, get_rates

# What the model reads when it decides whether and how to call a tool. Follows
# Anthropic's guidance: what it does, when to use it, what it returns, what it does
# not do, and what each error reason means. Keep the reasons in sync with
# docs/tools.md (tests/test_tool_specs.py checks they are all named).
_AVAILABILITY_DESCRIPTION = (
    "Checks which room types have at least one free room for the whole stay and can "
    "hold the whole party. "
    "Use it as soon as you know the arrival date, the departure date and the number "
    "of guests; do not wait for the caller to choose a room type, because the result "
    "is what you offer them. "
    "It returns every room type that fits, with how many rooms of it are free, and "
    "an empty list means the hotel is fully booked for those dates. "
    "It does not return prices (use get_rates for that) and it cannot make a "
    "booking. "
    "On failure it returns a reason instead: "
    f"invalid_dates when the departure is not after the arrival, the arrival is in "
    f"the past or the stay is longer than {MAX_STAY_NIGHTS} nights; "
    "invalid_guests when the guest count is below one; "
    "too_many_guests when the party is larger than the biggest room, which means no "
    "single room fits them."
)
_RATES_DESCRIPTION = (
    "Prices a stay for one room type, night by night, so a stay that crosses from "
    "low to high season is priced correctly. "
    "Use it once the caller has chosen a room type from a check_availability result "
    "(which needs the guest count) and you have the arrival date and the departure "
    "date. "
    "It returns the total in euros for the whole stay, the number of nights and the "
    "price of each night. "
    "It does not check that the room is free or that it fits the party, so call "
    "check_availability first, and it cannot make a booking. "
    "On failure it returns a reason instead: "
    "unknown_room_type when the name is not one of the hotel's room types (the "
    "result then lists the valid names, so offer those); "
    f"invalid_dates when the departure is not after the arrival, the arrival is in "
    f"the past or the stay is longer than {MAX_STAY_NIGHTS} nights; "
    "no_rate_for_dates when some night of the stay has no price set."
)


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
            description=_AVAILABILITY_DESCRIPTION,
            input_model=AvailabilityInput,
            handler=_availability,
        ),
        Tool(
            name="get_rates",
            description=_RATES_DESCRIPTION,
            input_model=GetRatesInput,
            handler=_rates,
        ),
    ]
    return {t.name: t for t in tools}
