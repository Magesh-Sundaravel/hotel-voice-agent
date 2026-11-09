# Plan: ElevenLabs tool backend

Branch `feat/elevenlabs-tools`, PR #12. ElevenLabs Agents runs the call (STT, TTS, turn-taking); we own the tools as FastAPI webhooks and the LLM through our own `/llm` proxy to Groq.

## Status (2026-11-09)
- Steps 0-6 done; 249 tests pass; reviewer passed (before the two follow-up fixes below).
- Migration 0003 applied.
- Committed and pushed; PR #12 open.
- Open: full eval run on `gpt-oss-120b` (the daily Groq limit was used up), including the new `vague-date` cases. Merge after that.

## Decisions (from the grilling)
| # | Decision |
|---|---|
| D1 | Rename `lookup_guest` → `get_guest_info` everywhere, with no change in behaviour |
| D2 | `send_confirmation_email(reference, last_name, language)`: the model passes the language of the current call |
| D3 | It sends only to the stored email. If there is none it returns `no_email_on_file`. The email stays optional at booking |
| D4 | The tool returns right away and the email goes out in the background; the agent says "you'll receive it in a few minutes" |
| D5 | Never sent twice: `reservations.confirmation_sent_at` is claimed first, then the email is sent, and the claim is cleared if sending fails |
| D6 | Plain-text email with an all-day `.ics`: `METHOD:REQUEST`, hotel as ORGANIZER, guest as ATTENDEE with `RSVP=FALSE`, UID `booking-<reference>@<domain>`, SEQUENCE = send time in epoch seconds (Q23 replaced the first `METHOD:PUBLISH` version) |
| D7 | Gmail through `httpx` (Google's REST API), see `docs/external/gmail.md` |
| D8 | Tests, evals and the CLI use a fake sender by default; `cli --real-email` sends for real; the FastAPI app always sends for real |
| D9 | `modify_booking` clears `confirmation_sent_at`. After a modify, the agent sends the updated confirmation to the email on file without asking. Same `.ics` UID, so calendars update the event |
| D10 | Booking flow: read back the booking, then ask for the email. A returning guest with `has_email` is asked "send to the email on file?" (if no, ask for a new one). If they refuse, book anyway |
| D11 | One generic `POST /tools/{name}` route. `call_id` and `caller_phone` are bound to ElevenLabs system variables |
| D12 | 1.5 s timeout. Tool failures (`tool_timeout`, `invalid_arguments`, ...) come back as `ok:false` with HTTP 200; a bad secret gives 401; an unknown tool gives 404 |
| D13 | One `WEBHOOK_SECRET`, sent as the `X-Webhook-Secret` header and checked in constant time, for both the tools and `/llm` |
| D14 | The `/llm` proxy puts our `build_system_prompt(today)` first and keeps ElevenLabs' system message after it |
| D15 | The proxy streams Groq's reply straight through, always uses `GROQ_MODEL`, removes `elevenlabs_extra_body`, serves both possible paths and records one Langfuse generation per request |
| D16 | Traces are tagged `language="unknown"` for now; listed as an open question in `docs/architecture.md` |
| D17 | `export_tools` prints the ElevenLabs tool configs; it pushes nothing |
| D18 | Work on branch `feat/elevenlabs-tools`; commit after tests, evals and the reviewer; push and PR only when asked |
| Q24 | Gmail OAuth scope `gmail.send` only |

## Steps
- **Step 0, setup:** branch; docs-researcher verifies the Gmail send call, the refresh-token exchange, raw MIME + base64url and the scope → `docs/external/gmail.md`.
- **Step 1, rename:** `lookup_guest.py` → `get_guest_info.py`, plus registry, prompt, tests, `evals/golden.json`, `docs/tools.md`.
- **Step 2, `send_confirmation_email`** (test-first): contract in `docs/tools.md`; migration `0003_confirmation_sent_at.sql`; repository methods (find booking with email, claim, clear claim) for in-memory and Postgres; `src/email/` (`compose.py` IT/EN text, `ics.py`, `sender.py` with `EmailSender`, `GmailSender`, `FakeEmailSender`); background send that logs `guest_id` only on failure; registry entry, prompt flow (D10, send after create and after modify), CLI `--real-email`; IT + EN eval cases.
- **Step 3, tool webhooks:** `src/voice/webhooks.py` `POST /tools/{name}`; app startup builds the asyncpg pool, Postgres repositories, httpx client and `GmailSender`; `WEBHOOK_SECRET` in config and `.env.example`; one Langfuse span per request tagged with `call_id`.
- **Step 4, `/llm` proxy:** `src/voice/llm_proxy.py`; same secret; our prompt first; model forced; extra body removed; SSE streamed through; `call_id` from a header bound to `system__conversation_id` (falls back to "unknown"); Langfuse down → warning and continue; Groq failure → 502.
- **Step 5, docs:** `docs/architecture.md` (webhook route, prompt ownership, email flow, language-tag open question); `docs/external/elevenlabs.md` notes.
- **Step 6, setup:** `src/voice/export_tools.py` prints the 8 webhook tool configs; `docs/setup-elevenlabs-telnyx.md` checklist (ngrok domain, ElevenLabs secret, Custom LLM URL + header, IT/EN, tools, Google refresh token, Telnyx FQDN to `sip.rtc.elevenlabs.io`, first test call).
- **Step 7, verify and commit:** pytest → evals → reviewer → commit.

## Follow-up fixes (from Langfuse traces, same PR)
- `invalid_arguments` now returns `fields`, the names of the bad arguments (never values), so the model can correct itself.
- Prompt: a vague date ("next week", "fine mese") makes the agent ask for the exact day; eval cases `en-vague-date`, `it-vague-date`.
- `evals.run --repeats` defaults to 1.

## Not in this plan
- Reading guest emails (`check_guest_email`)
- Failure follow-up emails
- A cancellation email or `.ics` cancel
- Writing the `call_log`
- Detecting the caller's language from ElevenLabs
- Pushing tool configs to ElevenLabs through its API

## Unverified, to test on the first real call
- Which `/llm` path ElevenLabs calls
- Whether a dynamic-variable header on the custom LLM resolves `system__conversation_id`
- Whether Telnyx passes on the caller ID
- What ElevenLabs puts in its own system message
- Cause of the `tool_timeout` on `check_availability` seen in Langfuse (source run unknown)
