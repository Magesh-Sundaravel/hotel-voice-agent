# Hotel Voice Agent

24/7 AI receptionist that answers hotel phone calls in Italian and English. Portfolio project.

## Stack
- Voice: ElevenLabs Agents (STT, TTS, turn-taking)
- Phone: Telnyx SIP trunk -> ElevenLabs
- LLM: Groq, plugged into ElevenLabs as the agent's LLM
- Backend: FastAPI (Python 3.12, uv). Hosts the tools the agent calls.
- Deployment: local Docker Compose + ngrok (AWS is a future option)
- Data: Supabase (guests, rooms, rates, reservations, call log)
- Integrations: Gmail (read + send; confirmations carry an .ics invite)
- Observability + evals: Langfuse Cloud (PII masked before traces are sent)

## Layout
- src/agent/  system prompt, tool registry
- src/tools/  one module per tool
- src/voice/  ElevenLabs / Telnyx glue
- src/db/     all Supabase access
- tests/      unit tests
- evals/      golden dataset (source of truth) + runner

## Commands
- Install: `uv sync --all-extras`
- Run:     `uv run uvicorn src.main:app --reload`
- Test:    `uv run pytest -q`
- Evals:   `uv run python -m evals.run`

## Docs (read when relevant, not upfront)
- docs/architecture.md: end-to-end call flow. Read before changes that cross modules.
- docs/tools.md: tool contracts. Read before adding or changing a tool.
- docs/evals.md: golden dataset format, Langfuse sync, scoring.
- docs/decisions/: why we chose X. Don't reverse a decision without asking.
- docs/external/: verified notes on vendor APIs. Prefer these over memory.

## Workflow (per feature)
1. grill-me skill on the plan before any code
2. Tool contract in docs/tools.md
3. Build with the tdd skill
4. Add eval cases (IT + EN) to evals/golden.json, run eval-runner agent
5. Run reviewer agent, then commit
When something breaks, use the diagnosing-bugs skill.

## Done means
- Tests pass and evals don't regress
- A new tool ships with: contract in docs/tools.md + unit test + at least one eval case
