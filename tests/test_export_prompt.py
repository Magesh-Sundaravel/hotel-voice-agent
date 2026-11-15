"""Tests for the ElevenLabs system prompt export."""

from src.voice.export_prompt import export_prompt


def test_today_becomes_the_elevenlabs_date_variable() -> None:
    """ElevenLabs fills {{system__time_date}} on every call; ours is never left in."""
    prompt = export_prompt()

    assert "{{system__time_date}}" in prompt
    assert "{{today}}" not in prompt

