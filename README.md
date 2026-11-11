# Hotel Voice Agent

A 24/7 AI receptionist that answers hotel phone calls in Italian and English. Portfolio project.

> **Status: work in progress.** The agent loop, all booking tools, Gmail confirmations, tracing and an eval suite work today and can be tried in a text REPL. The backend side of the phone path (`/llm` proxy and tool webhooks, backed by Supabase) is built; it has not yet been tested on a real call through ElevenLabs and Telnyx. See [Roadmap](#roadmap).

## How it works

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
- `/llm/v1/chat/completions`: OpenAI-compatible proxy that ElevenLabs uses as its custom LLM. It adds our system prompt, forwards to Groq, streams the reply back and traces it (`src/voice/llm_proxy.py`)
- `POST /tools/{name}`: tool webhooks for ElevenLabs, authenticated with a shared secret and running the same code as the CLI and evals (`src/voice/webhooks.py`)
- Tool configs for the ElevenLabs dashboard, exported from the registry (`src/voice/export_tools.py`)
- Langfuse tracing of model calls, tool calls and eval runs, with PII masking (`src/observability.py`)
- Bilingual golden eval dataset (31 cases, Italian and English) with a runner and scorer (`evals/`)
- `/health` endpoint, Dockerfile, Compose file and CI for lint and tests

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

Run the API (needs `DATABASE_URL` and `WEBHOOK_SECRET`, plus the `GOOGLE_*` and `GMAIL_SENDER` variables for emails; apply the schema once with `uv run python -m src.db.migrate --seed`):

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
src/voice/   ElevenLabs glue: /llm proxy, tool webhooks, tool config export
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

- [x] `/llm` proxy that streams to Groq in the OpenAI format ElevenLabs expects
- [x] Authenticated tool webhooks with a ~1.5 s time budget
- [ ] ElevenLabs agent and Telnyx number tested on a real call ([setup guide](docs/setup-elevenlabs-telnyx.md))
- [x] Supabase schema, migrations, seed and Postgres repository for inventory and rates
- [x] Repository writes for guests and reservations
- [ ] Call log writes (needs the phone path)
- [x] Booking tools: create, modify and cancel a reservation, guest lookup by caller ID
- [x] Gmail confirmation emails with an `.ics` invite
- [ ] Follow-up email after a tool failure, and cancellation emails
- [ ] Language tag (it/en) on live call traces
- [x] Eval cases for booking and returning callers
- [ ] More eval cases: tool failure, language switching, withheld caller ID
- [x] CI for lint and tests
- [ ] Evals in CI (needs Groq and Langfuse keys)
- [ ] AWS deployment (ECS Fargate), as a future option
