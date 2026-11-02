# Architecture

## Call flow
1. Guest dials the hotel number (Telnyx)
2. Telnyx SIP trunk routes the call to the ElevenLabs agent
3. ElevenLabs does STT -> LLM (Groq) -> TTS
4. When the LLM calls a tool, ElevenLabs hits our FastAPI backend on AWS
5. Backend reads/writes Supabase, Google Calendar, Gmail and returns a result
6. Agent speaks the result
7. Tool calls (and LLM calls, see open questions) are traced in Langfuse

## Components
| Component | Owns | Code |
|---|---|---|
| ElevenLabs agent | voice, turn-taking, prompt, tool definitions | src/agent/, src/voice/ |
| FastAPI backend (AWS) | tool endpoints | src/tools/ |
| Supabase | guests, bookings | src/db/ |
| Google Calendar | availability, events | src/tools/ |
| Gmail | read + send guest emails | src/tools/ |
| Langfuse (self-hosted, AWS) | traces, eval runs, scores | evals/ |

## Google auth
OAuth client (ID + secret) + a refresh token obtained once via manual consent.
Backend uses the refresh token to get access tokens; no human in the loop at runtime.

## Open questions
- TODO: how tool calls are authenticated (shared secret? signed requests?)
- TODO: how a returning caller is matched to a guest_id
- TODO: what happens when a tool fails mid-call (fallback line? transfer to human?)
- TODO: does ElevenLabs call Groq directly, or through our backend as a proxy? Only the proxy lets Langfuse trace LLM calls.
- TODO: which AWS service runs the backend (ECS Fargate? App Runner? Lambda?)
- TODO: which Gmail emails are read, and what triggers reading them
