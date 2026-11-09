# Hotel Voice Agent

A 24/7 AI receptionist that answers hotel phone calls in Italian and English. Portfolio project.

> **Status: work in progress.** The agent loop, two read-only tools, tracing and an eval suite work today and can be tried in a text REPL. The phone path (ElevenLabs and Telnyx wiring, `/llm` proxy, tool webhooks) is not built yet. The Supabase schema and a Postgres repository exist, but the app doesn't use them until the phone path is wired. See [Roadmap](#roadmap).

## How it will work

```
Caller -> Telnyx SIP trunk -> ElevenLabs Agent (STT, turn-taking, TTS)
                                   |
                                   +-> /llm proxy (FastAPI) -> Groq     (traced in Langfuse)
                                   +-> tool webhooks (FastAPI) -> Supabase, Gmail
```

ElevenLabs handles speech and turn-taking. The LLM is Groq, reached through our own OpenAI-compatible `/llm` endpoint so every model call can be traced. The FastAPI backend hosts the tools the agent calls. Full flow: [docs/architecture.md](docs/architecture.md).

## Stack

| Concern | Choice |
|---|---|
| Voice | ElevenLabs Agents |
| Phone | Telnyx SIP trunk |
| LLM | Groq (`openai/gpt-oss-120b` by default) |
| Backend | FastAPI, Python 3.12, uv |
| Data | Supabase (hosted free tier) |
| Email | Gmail (confirmations with an `.ics` invite) |
| Observability and evals | Langfuse Cloud, with phones and emails masked |
| Deployment | Docker Compose on a laptop, exposed through ngrok |

Why these choices: [docs/decisions/](docs/decisions/).

## What works today

- Agent loop with native tool calling and no graph framework (`src/agent/`)
- Tools: `check_availability`, `get_rates`, `get_guest_info`, `create_booking`, `get_booking`, `modify_booking`, `cancel_booking` and `send_confirmation_email` (Gmail, with an `.ics` invite), backed by an in-memory seed repository in the CLI and evals, with a Postgres version tested against Supabase (`src/tools/`, `src/db/`)
- Langfuse tracing of model calls and eval runs, with PII masking (`src/observability.py`)
- Bilingual golden eval dataset (24 cases, Italian and English) with a runner and scorer (`evals/`)
- `/health` endpoint, Dockerfile and Compose file

Tool contracts are in [docs/tools.md](docs/tools.md).

## Getting started

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras
cp .env.example .env     # then fill in GROQ_API_KEY at minimum
```

Chat with the agent in the terminal, no voice involved:

```bash
uv run python -m src.agent.cli
# call as returning guest Giulia Rossi (seed booking 482913):
uv run python -m src.agent.cli --caller-phone +12025550101
```

Run the API:

```bash
uv run uvicorn src.main:app --reload
# or
docker compose up api
```

Run the tests and the evals:

```bash
uv run pytest -q
uv run python -m evals.run
```

Evals send traces to Langfuse, so set the `LANGFUSE_*` variables first. The dataset format and scoring are described in [docs/evals.md](docs/evals.md).

## Project layout

```
src/agent/   system prompt, LLM client, agent loop, tool registry, text CLI
src/tools/   one module per tool
src/voice/   ElevenLabs and Telnyx glue (not built yet)
src/db/      all data access: Postgres on Supabase, plus an in-memory repo for the CLI, tests and evals
tests/       unit tests
evals/       golden dataset (source of truth) and runner
docs/        architecture, tool contracts, data model, decisions, vendor notes
```

## Design rules

- Everything the agent says is spoken: no markdown, lists, URLs or emojis. Replies are one or two sentences, in the caller's language.
- Guest data is PII. Only `guest_id` is logged, phones and emails are masked before reaching Langfuse, and all tests and evals use fake guests.
- Tracing must never break a call.
- A tool is done when it has a contract in `docs/tools.md`, a unit test and at least one eval case.

## Roadmap

- [ ] `/llm` proxy that streams to Groq in the OpenAI format ElevenLabs expects
- [ ] Authenticated tool webhooks with a ~1.5 s time budget
- [ ] ElevenLabs agent and Telnyx number configuration (`src/voice/`)
- [x] Supabase schema, migrations, seed and Postgres repository for inventory and rates
- [x] Repository writes for guests and reservations
- [ ] Call log writes (needs the phone path)
- [x] Booking tools: create, modify and cancel a reservation, guest lookup by caller ID
- [ ] Gmail confirmation emails with an `.ics` invite
- [ ] More eval cases: booking, returning callers, tool failure, language switching
- [ ] CI for tests, lint and evals
- [ ] AWS deployment (ECS Fargate), as a future option
