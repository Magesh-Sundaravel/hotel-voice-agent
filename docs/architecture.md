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
Local, for a portfolio demo: FastAPI runs in Docker Compose on the developer's laptop; Supabase and Langfuse are hosted (`docker-compose.yml`).
ngrok (free static domain) exposes FastAPI to ElevenLabs. The laptop must be on while calls come in.
Supabase is the hosted free tier. AWS is a future option (ECS Fargate would be the choice: no cold starts, long-lived streaming for the LLM proxy); nothing is deployed there.

## Components
| Component | Owns | Code |
|---|---|---|
| ElevenLabs agent | voice, turn-taking, tool definitions (exported from the registry) | dashboard config, `src/voice/export_tools.py` |
| FastAPI backend (local, via ngrok) | tool webhooks, `/llm` proxy, system prompt | src/tools/, src/voice/, src/agent/ |
| Supabase (hosted) | guests, rooms, room types, rates, reservations, call log (see data-model.md) | src/db/ |
| Gmail | send confirmations (with .ics invite) and follow-ups; read on demand | src/email/, src/tools/send_confirmation_email.py |
| Langfuse Cloud | traces, eval runs, scores | evals/ |

Room availability lives only in Supabase. There is no calendar integration; guests get a calendar invite as an `.ics` attachment on the confirmation email.

## LLM path
ElevenLabs is configured with a custom LLM that points at FastAPI `/llm/v1/chat/completions` (OpenAI-compatible, `src/voice/llm_proxy.py`). The proxy forwards to Groq and records the call in Langfuse.
This is the only way Langfuse can trace LLM calls. The extra hop is small next to Groq's latency.
Request shape (verified in docs/external/elevenlabs.md): OpenAI `chat/completions`-style, streamed as SSE ending in `data: [DONE]`.
What the proxy does to each request:
- Puts our system prompt (`build_system_prompt`, today's date in Rome) before ElevenLabs' own system text, so callers get exactly the prompt the evals test. The ElevenLabs dashboard prompt is only a placeholder.
- Forces `GROQ_MODEL`, whatever model name ElevenLabs sends, and drops `elevenlabs_extra_body`.
- Streams Groq's bytes back unchanged; a Groq failure before the stream starts is a 502.
- Records one Langfuse generation when the stream ends, in the session named by the `X-Call-Id` header.
Auth: `custom_llm.request_headers` carries the shared secret as a Secret-type header (verified in docs/external/elevenlabs.md, section 5).
Both `/llm/v1/chat/completions` and `/llm/v1/chat/completions/chat/completions` are served, and the path hit is logged, until we know whether ElevenLabs appends `/chat/completions` to the configured URL.

## Tool webhooks
One route, `POST /tools/{name}` (`src/voice/webhooks.py`), runs any registry tool through the same code as the CLI and evals (`run_tool`: argument validation, the 1.5 s budget, never raising).
The JSON body is the tool's arguments plus `call_id` (bound to `system__conversation_id`) and `caller_phone` (bound to `system__caller_id`), so the model never generates them. A caller ID that is not E.164 (empty, or a word for a withheld number) counts as withheld.
Tool failures are `{ok: false, reason}` with HTTP 200 so the agent can say them. Only a bad secret (401) or an unknown tool (404) is an HTTP error.
`src/voice/export_tools.py` prints the ElevenLabs tool configs from the registry, so the dashboard never drifts from the code.

## Authentication
One shared secret, `WEBHOOK_SECRET`, sent by ElevenLabs as a Secret-type `X-Webhook-Secret` header on tool webhooks and on `/llm`. FastAPI compares it in constant time (`hmac.compare_digest`); an unset secret refuses every request. The secret is in `.env` locally.
Upgrade path: signed requests (HMAC over body + timestamp).

## Tool latency and retries
ElevenLabs' minimum webhook timeout is 5 s, above our ~1.5 s budget, so the backend enforces the budget itself. Retries are undocumented, so assume none and keep every tool idempotent (see data-model.md).

## Returning callers
The caller ID (E.164) arrives as the `system__caller_id` dynamic variable and is bound to a tool parameter so the LLM never generates it. It is matched against `guests.phone`. Unverified: whether Telnyx supplies it without extra SIP headers; test on the first real call.
- Match: greet by first name, confirm identity before using any stored detail.
- No match or withheld number: ask the name. A guest row is created only when a booking is made. A bare call stores nothing.

## Tool failure
Tools return `{ok: false, reason}`. The agent never promises a callback. After one retry it offers an email so the guest can write down what they need, and calls `send_followup_email` if they agree.
- Email on file: the follow-up email goes to it.
- No email on file: ask the caller to spell it and read it back once. If they decline or it fails, apologise and ask them to call again.
- `call_log` records `needs_followup` and `followup_reason`. No PII in the log.

## Handoff to a person
The agent cannot transfer a call. When the caller asks for a person, or wants something no tool does, it takes a message with `take_message`: name, a short summary and a way to reach them (the caller ID, or a phone or email they give). The message is emailed to the hotel's own inbox (`GMAIL_SENDER`), with the caller's email as Reply-To. The agent says the message was passed to reception, without saying when or how they will reply.

## Call log
Every tool webhook also writes the call's `call_log` row, keyed by `call_id` (see data-model.md). It records the outcome (booked, modified, cancelled), the reservation, the language once a tool is given one, and whether staff need to follow up. Like tracing, it never breaks a call.

## Gmail
- Send (built): `send_confirmation_email` after create_booking, modify_booking and cancel_booking, to the email on file, in the language of the call. The tool answers at once and the email goes out in the background; the agent says it will arrive in a few minutes. `reservations.confirmation_sent_at` stops a second send; modify and cancel clear it. A cancelled booking gets a cancellation with a `METHOD:CANCEL` update (same UID).
- The `.ics` is an iTIP `METHOD:REQUEST` (hotel as ORGANIZER, guest as ATTENDEE with `RSVP=FALSE`) with a stable UID per booking and a growing SEQUENCE, so a modified booking updates the same calendar event. Gmail may still show RSVP buttons (to check on the first real email). See docs/external/gmail.md.
- Send (built): `send_followup_email` to the caller after a tool keeps failing, and `take_message` to the hotel's own inbox. Both send in the background, at most once per call (in memory, so only within one running server).
- Read (planned): only on demand, via `check_guest_email`. When a caller says they replied to our email, the tool searches the hotel inbox for recent messages from that guest's address and the agent summarises them in a sentence or two.
- No polling, no auto-replies, no email content in logs or traces.

## Google auth
OAuth client (ID + secret) + a refresh token obtained once via manual consent, for the account in `GMAIL_SENDER`. Scope: `gmail.send` only for now. Reading later needs `gmail.readonly` (a Restricted scope) and a new consent.
Backend uses the refresh token to get access tokens; no human in the loop at runtime.
The OAuth app must be published "In production" (unverified is fine for one account): in "Testing", refresh tokens with Gmail scopes expire after 7 days. Changing the account's password also revokes the token.

## Open questions
To settle on the first real call (see docs/setup-elevenlabs-telnyx.md):
- Which `/llm` path ElevenLabs calls (the proxy logs it).
- Whether a dynamic-variable header resolves `system__conversation_id` on the custom LLM (`X-Call-Id`); if not, LLM traces land in session "unknown".
- What ElevenLabs puts in its own system message, now placed after ours.
- Whether Gmail and Google Calendar remove the event when the cancellation's `METHOD:CANCEL` update arrives (docs/external/gmail.md marks it UNVERIFIED); check on the first real cancellation.
- Language tag: no ElevenLabs variable gives the caller's language, so the `/llm` proxy reads it from the latest `language_detection` call in the conversation, else uses `AGENT_LANGUAGE` (the agent's default language, `en` as in docs/setup-elevenlabs-telnyx.md), and remembers it per call_id for the tool webhooks (`src/voice/call_language.py`). This needs `X-Call-Id` to resolve (above); without it, traces get `AGENT_LANGUAGE`. Unverified: the name and argument format ElevenLabs uses for `language_detection` in the messages it sends; `it`, `it-IT` and `Italian` are all accepted.
(Eval format and scoring are tracked in docs/evals.md.)
