# 005: ElevenLabs built-in LLM for live calls

Status: accepted (2026-11-15). Supersedes the LLM part of 001; the rest of 001 stands.

## Decision
Live calls use an LLM built into ElevenLabs Agents (`claude-haiku-5.5`, picked in the agent's LLM dropdown), not Groq behind our `/llm` proxy.
- The system prompt is pasted into the dashboard. `src/agent/prompts/receptionist.md` stays the only source: `uv run python -m src.voice.export_prompt` prints it with `{{today}}` replaced by ElevenLabs' `{{system__time_date}}`. The agent timezone is set to Europe/Rome.
- The tools are unchanged: ElevenLabs webhooks to FastAPI `/tools/*`, with `X-Webhook-Secret`.
- The `/llm` proxy (`src/voice/llm_proxy.py`) and its tests stay in the repo, unused on live calls, as the way back to Groq or another OpenAI-compatible LLM.
- Evals keep running on Groq (`src/agent/llm.py`), for local checking only.

## Alternatives considered
- Groq free tier: 8K tokens/min. ElevenLabs sends parallel requests of about 2K tokens each and retries on errors, so one turn used up the minute's budget and the call failed with 429 (tested 2026-11-15, on both gpt-oss-120b and gpt-oss-20b).
- Groq paid tier: works with no change, but costs money. Still the easiest way back.
- NVIDIA NIM free: no gpt-oss-120b; gpt-oss-20b timed out at 60 s; nemotron-3.5-lightning took 7.1 s to first output. Too slow for voice (budget ~1.5 s).
- Cerebras free trial: $5 for 30 days only, not tested.

## Consequences
- **The evals do not test the live model.** They grade Groq with our prompt; callers talk to the ElevenLabs model with the same prompt plus ElevenLabs' own system text. A passing eval run is a check of the prompt and tools, not proof of call behaviour.
- **No LLM traces in Langfuse for live calls.** Langfuse gets only the tool traces. Transcripts live in ElevenLabs (Agent > Conversations).
- **Wrong language tag on Italian calls.** `call_language` learned the language from the proxy. Without it, tool traces and `call_log.language` always get `AGENT_LANGUAGE` (`en`). Known gap.
- The prompt in the dashboard can drift from the repo. Rerun `export_prompt` and paste again after every prompt change.
- LLM usage is billed by ElevenLabs against its credits.

## Open follow-ups
1. Language tag: add a `language` parameter, filled by the model, to every tool (changes the tool contracts in docs/tools.md).
2. Post-call webhook from ElevenLabs to put transcripts in Langfuse.
