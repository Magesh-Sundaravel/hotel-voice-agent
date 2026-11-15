# Setup: Gmail, backend, ElevenLabs, Twilio

One-time steps only a human can do, in order. Each ends with a check. Vendor facts come from docs/external/; anything marked "check" is unverified and should be confirmed (and noted in docs/external/) the first time.

## 1. Gmail (confirmation emails)
1. In Google Cloud: create a project, enable the Gmail API, and create an OAuth client.
2. OAuth consent screen: External. Add the scope `https://www.googleapis.com/auth/gmail.send` only. Then **Publish app** ("In production"). Leave it unverified. In "Testing", the refresh token dies after 7 days (docs/external/gmail.md, section 1).
3. Get a refresh token once, signed in as the hotel Gmail account, with `access_type=offline`. One way to do it is the Google OAuth Playground, using your own client ID and secret. Click through the "unverified app" warning.
4. In `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `GMAIL_SENDER` (that account's address).
- Check: `uv run python -m src.agent.cli --real-email`, book a room giving your own email, and confirm the email arrives with `booking.ics`. Also check whether Gmail shows RSVP buttons, and record it in docs/external/gmail.md.

## 2. Database
- `uv run python -m src.db.migrate` (applies any migration in `db/migrations/` not yet recorded in `schema_migrations`).
- Check: `uv run pytest -q` passes, including the Postgres variants.

## 3. Backend online
1. `.env`: set `WEBHOOK_SECRET` to `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. `docker compose up api`, then `ngrok http --url=<your-static-domain> 8000`.
- Check: `curl https://<your-static-domain>/health` returns `{"status":"ok"}`. Also `curl -X POST https://<domain>/tools/get_guest_info -H 'Content-Type: application/json' -d '{"call_id":"t"}'` returns 401 (no secret).

## 4. ElevenLabs agent
1. Workspace secrets: create a secret holding the `WEBHOOK_SECRET` value, and note its secret id.
   The tool configs reference it by id. Find the id with `curl -s https://api.elevenlabs.io/v1/convai/secrets -H "xi-api-key: <your ElevenLabs API key>"` (field `secret_id`).
2. Agent > LLM: the built-in `claude-haiku-5.5`, not Custom LLM (docs/decisions/005-elevenlabs-llm.md).
   - The unused alternative, Custom LLM through our `/llm` proxy to Groq, is described in docs/architecture.md (LLM path). It needs a paid Groq tier.
3. Agent > Prompt: paste the output of `uv run python -m src.voice.export_prompt`. Set the agent timezone to **Europe/Rome** in the System Prompt editor; `{{system__time_date}}` uses it. Paste again after every change to `src/agent/prompts/receptionist.md`.
4. Languages: English as the default plus an Italian preset, each with its own first message. Turn on the `language_detection` system tool. The default language must match `AGENT_LANGUAGE` in `.env` (`en`), which tags traces and the call log (it does not switch with the caller: docs/decisions/005-elevenlabs-llm.md).
5. Tools: run `uv run python -m src.voice.export_tools --base-url https://<domain> --secret-id <id>` and add each of the 10 configs as a webhook tool (JSON editor).
   - Check: the dashboard accepts the outer fields `type: "webhook"` and `api_schema`, and the per-property `dynamic_variable`. If it renames anything, fix `src/voice/export_tools.py` and note it in docs/external/elevenlabs.md.
- Check: talk to the agent from the ElevenLabs test widget. Ask for availability, then book with an email. In the backend logs:
  - The agent knows today's date (ask "what day is it today?"). If it reads out `{{system__time_date}}`, the variable wasn't filled: check the timezone setting.
  - The tool webhooks return 200.
  - The confirmation email arrives.

## 5. Twilio phone number (docs/external/twilio.md)
1. Twilio: upgrade the account (add funds). A trial can't buy regulated numbers and probably blocks the media stream ElevenLabs uses.
2. Buy a US local number for the first test call. An Italian number needs an approved Regulatory Bundle first (address and ID documents, about 72 h review); do that in parallel.
3. ElevenLabs > Phone Numbers > import from Twilio: label, the number (E.164 with the leading +), Account SID and Auth Token. ElevenLabs sets the Twilio webhook itself; leave the Twilio console alone. Turn SMS off if it offers the option.
   - Account SID + Auth Token, not an API key: an API-key import also needs `account_auth_token` (API reference).
4. Assign the agent in the number's inbound dropdown.
- Check: call the number from a phone. The agent answers with the English first message.

## 6. First real call: settle the open points (docs/architecture.md, Open questions)
- Whether `system__caller_id` arrived. Call from a number on file: get_guest_info should find the guest.
- What ElevenLabs adds to the system prompt on its own (Agent > Conversations, conversation details).
- (Settled 2026-11-15, Custom LLM path only: ElevenLabs calls `/llm/v1/chat/completions` and `X-Call-Id` arrives.)
Write each answer into docs/external/elevenlabs.md and remove it from the open questions.
