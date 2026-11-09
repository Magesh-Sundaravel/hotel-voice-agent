# Setup: Gmail, backend, ElevenLabs, Telnyx

One-time steps only a human can do, in order. Each ends with a check. Vendor facts come from docs/external/; anything marked "check" is unverified and should be confirmed (and noted in docs/external/) the first time.

## 1. Gmail (confirmation emails)
1. In Google Cloud: create a project, enable the Gmail API, and create an OAuth client.
2. OAuth consent screen: External. Add the scope `https://www.googleapis.com/auth/gmail.send` only. Then **Publish app** ("In production"). Leave it unverified. In "Testing", the refresh token dies after 7 days (docs/external/gmail.md, section 1).
3. Get a refresh token once, signed in as the hotel Gmail account, with `access_type=offline`. One way to do it is the Google OAuth Playground, using your own client ID and secret. Click through the "unverified app" warning.
4. In `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `GMAIL_SENDER` (that account's address).
- Check: `uv run python -m src.agent.cli --real-email`, book a room giving your own email, and confirm the email arrives with `booking.ics`. Also check whether Gmail shows RSVP buttons, and record it in docs/external/gmail.md.

## 2. Database
- `uv run python -m src.db.migrate` (applies `0003_confirmation_sent_at.sql`).
- Check: `uv run pytest -q` passes, including the Postgres variants.

## 3. Backend online
1. `.env`: set `WEBHOOK_SECRET` to `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. `docker compose up api`, then `ngrok http --url=<your-static-domain> 8000`.
- Check: `curl https://<your-static-domain>/health` returns `{"status":"ok"}`. Also `curl -X POST https://<domain>/tools/get_guest_info -H 'Content-Type: application/json' -d '{"call_id":"t"}'` returns 401 (no secret).

## 4. ElevenLabs agent
1. Workspace secrets: create a secret holding the `WEBHOOK_SECRET` value, and note its secret id.
2. Agent > LLM: **Custom LLM**.
   - Server URL: `https://<domain>/llm/v1/chat/completions`.
   - Model ID: anything; the proxy uses `GROQ_MODEL`.
   - Request headers:
     - `X-Webhook-Secret`: type Secret, the secret above.
     - `X-Call-Id`: type dynamic variable, `system__conversation_id`.
3. Agent > Prompt: a one-line placeholder such as "The system prompt is supplied by the backend." The proxy puts the real prompt first.
4. Languages: English as the default plus an Italian preset, each with its own first message. Turn on the `language_detection` system tool.
5. Tools: run `uv run python -m src.voice.export_tools --base-url https://<domain> --secret-id <id>` and add each of the 8 configs as a webhook tool (JSON editor).
   - Check: the dashboard accepts the outer fields `type: "webhook"` and `api_schema`, and the per-property `dynamic_variable`. If it renames anything, fix `src/voice/export_tools.py` and note it in docs/external/elevenlabs.md.
- Check: talk to the agent from the ElevenLabs test widget. Ask for availability, then book with an email. In the backend logs:
  - `custom LLM request on /llm/...`: note which path was hit. If it's the doubled `/chat/completions/chat/completions`, change the Server URL to `https://<domain>/llm/v1`.
  - The tool webhooks return 200.
  - The confirmation email arrives.

## 5. Telnyx phone number (docs/external/elevenlabs.md, section 4)
1. Telnyx: create an FQDN SIP connection to `sip.rtc.elevenlabs.io`.
   - Inbound: destination number format +E.164, transport TCP.
   - Assign the number on the Numbers tab.
2. ElevenLabs: import the number as a SIP trunk number (E.164 with the leading +) and assign the agent. Media encryption: Allowed, to start.
- Check: call the number from a phone.

## 6. First real call: settle the open points (docs/architecture.md, Open questions)
- Which `/llm` path ElevenLabs called (backend log).
- Whether `X-Call-Id` arrived with the conversation id. In Langfuse, the LLM traces should share a session with the tool traces, not sit under "unknown".
- Whether `system__caller_id` arrived. Call from a number on file: get_guest_info should find the guest.
- What ElevenLabs puts in its own system message (it appears after ours in the Langfuse generation input).
Write each answer into docs/external/elevenlabs.md and remove it from the open questions.
