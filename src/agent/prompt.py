"""System prompt for the hotel receptionist."""

from datetime import date
from pathlib import Path

PROMPT_NAME = "hotel-receptionist"
_PROMPT_FILE = Path(__file__).parent / "prompts" / "receptionist.md"


_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


def load_prompt_template() -> str:
    """Return the prompt text as stored, with the `{{today}}` variable unfilled.

    This is the exact text uploaded to Langfuse.
    """
    return _PROMPT_FILE.read_text(encoding="utf-8").rstrip("\n")


def build_system_prompt(today: date) -> str:
    """Return the system prompt with today's date filled in.

    The date is rendered with fixed English names, so it does not depend on the
    machine's locale.
    """
    weekday = _WEEKDAYS[today.weekday()]
    date_text = f"{weekday} {today.day} {_MONTHS[today.month - 1]} {today.year}"
    return load_prompt_template().replace("{{today}}", date_text)
