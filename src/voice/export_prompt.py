"""Print the system prompt for the ElevenLabs dashboard, ready to paste.

    uv run python -m src.voice.export_prompt

Live calls use an ElevenLabs built-in LLM (docs/decisions/005-elevenlabs-llm.md),
so the prompt is pasted into the dashboard. Our `{{today}}` becomes ElevenLabs'
`{{system__time_date}}`, which it fills in the agent's timezone on every call.
Rerun and paste again after every change to src/agent/prompts/receptionist.md.
"""

from src.agent.prompt import load_prompt_template

_ELEVENLABS_DATE = "{{system__time_date}}"


def export_prompt() -> str:
    """Return the prompt with today's date left to ElevenLabs.

    Returns:
        The prompt text, with `{{today}}` replaced by `{{system__time_date}}`.
    """
    return load_prompt_template().replace("{{today}}", _ELEVENLABS_DATE)


if __name__ == "__main__":
    print(export_prompt())
