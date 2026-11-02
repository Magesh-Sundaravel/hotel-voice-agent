# Architecture

## Call flow
1. Guest dials the hotel number (Telnyx)
2. Telnyx SIP trunk routes the call to the ElevenLabs agent
3. ElevenLabs does STT -> LLM -> TTS. The LLM is our own `/llm` proxy in FastAPI, which forwards to Groq (see LLM path)
4. When the LLM calls a tool, ElevenLabs hits our FastAPI backend through ngrok
5. Backend reads/writes Supabase and Gmail and returns a result
6. Agent speaks the result
7. Tool calls and LLM calls are traced in Langfuse

## Run model
Local, for a portfolio demo: FastAPI and Langfuse run in Docker Compose on the developer's laptop (`docker-compose.yml`).
ngrok (free static domain) exposes FastAPI to ElevenLabs. The laptop must be on while calls come in.
Supabase is the hosted free tier. AWS is a future option (ECS Fargate would be the choice: no cold starts, long-lived streaming for the LLM proxy); nothing is deployed there.

## Components
| Component | Owns | Code |
|---|---|---|
| ElevenLabs agent | voice, turn-taking, prompt, tool definitions | src/agent/, src/voice/ |
| FastAPI backend (local, via ngrok) | tool endpoints, `/llm` proxy | src/tools/, src/voice/ |
| Supabase (hosted) | guests, rooms, room types, rates, reservations, call log (see data-model.md) | src/db/ |
| Gmail | send confirmations (with .ics invite) and follow-ups; read on demand | src/tools/ |
| Langfuse (self-hosted, Docker Compose) | traces, eval runs, scores | evals/ |

Room availability lives only in Supabase. There is no calendar integration; guests get a calendar invite as an `.ics` attachment on the confirmation email.

## LLM path
ElevenLabs is configured with a custom LLM that points at FastAPI `/llm` (OpenAI-compatible). The proxy forwards to Groq and records the call in Langfuse.
This is the only way Langfuse can trace LLM calls. The extra hop is small next to Groq's latency.
Request shape (verified in docs/external/elevenlabs.md): OpenAI `chat/completions`-style, streamed as SSE ending in `data: [DONE]`. Strip `elevenlabs_extra_body` before forwarding to Groq.
Unverified, to test when wiring it up: whether ElevenLabs appends `/chat/completions` to the configured URL, and how a secret reaches `/llm` (no custom headers are documented for custom LLMs). If no header can be sent, authenticate `/llm` with an unguessable path or the workspace secret mechanism instead.

## Tool authentication
Tool webhooks: ElevenLabs sends a shared secret as a Secret-type `request_headers` entry. FastAPI compares it in constant time (`hmac.compare_digest`). The secret is in `.env` locally.
`/llm`: see the open point above.
Upgrade path: signed requests (HMAC over body + timestamp).

## Tool latency and retries
ElevenLabs' minimum webhook timeout is 5 s, above our ~1.5 s budget, so the backend enforces the budget itself. Retries are undocumented, so assume none and keep every tool idempotent (see data-model.md).

## Returning callers
The caller ID (E.164) arrives as the `system__caller_id` dynamic variable and is bound to a tool parameter so the LLM never generates it. It is matched against `guests.phone`. Unverified: whether Telnyx supplies it without extra SIP headers; test on the first real call.
- Match: greet by first name, confirm identity before using any stored detail.
- No match or withheld number: ask the name. A guest row is created only when a booking is made. A bare call stores nothing.

## Tool failure
Tools return `{ok: false, reason}`. The agent never promises a callback. After one retry it says it will send an email so the guest can write down what they need.
- Email on file: send the follow-up email to it.
- No email on file: ask the caller to spell it and read it back once. If they decline or it fails, apologise and ask them to call again.
- `call_log` records `needs_followup` and `followup_reason`. No PII in the log.

## Gmail
- Send: booking confirmation (with `.ics`), modification and cancellation (same `.ics` UID, updated or cancelled), and failure follow-ups.
- Read: only on demand, via `check_guest_email`. When a caller says they replied to our email, the tool searches the hotel inbox for recent messages from that guest's address and the agent summarises them in a sentence or two.
- No polling, no auto-replies, no email content in logs or traces.

## Google auth
OAuth client (ID + secret) + a refresh token obtained once via manual consent. Scope: Gmail only (send + read).
Backend uses the refresh token to get access tokens; no human in the loop at runtime.

## Open questions
None. (Eval format and scoring are tracked in docs/evals.md.)
