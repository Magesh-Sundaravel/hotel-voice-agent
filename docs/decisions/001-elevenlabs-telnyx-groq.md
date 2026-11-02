# 001: ElevenLabs Agents + Telnyx SIP + Groq

Status: accepted

## Decision
ElevenLabs Agents for voice, Telnyx SIP trunk for the phone number, Groq as the LLM (behind our own `/llm` proxy so Langfuse can trace it).
The backend runs locally in Docker Compose and is exposed to ElevenLabs through ngrok. AWS is a future option, not a current target.

## Alternatives considered
Vapi, Retell, Twilio for the number.

## Why
- ElevenLabs Agents covers STT, TTS and turn-taking in one product, with strong Italian voices. Vapi and Retell are comparable, but here voice quality is the product.
- Telnyx SIP is cheaper than Twilio and offers Italian numbers.
- Groq gives fast inference, which matters for the latency budget in `.claude/rules/voice.md`.
- Local + ngrok keeps the portfolio demo simple and free of cloud cost. The demo is recorded with the laptop on.

## Consequences
- Lock-in on the voice layer (ElevenLabs).
- Three vendors to keep working together (ElevenLabs, Telnyx, Groq).
- Groq rate limits and model choice constrain the agent.
- Calls only work while the laptop is on and ngrok is up. The free ngrok static domain keeps tool URLs stable across restarts.
- `.claude/rules/python.md` says production secrets live in AWS Secrets Manager. There is no production yet, so secrets stay in `.env` until there is.
