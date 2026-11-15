# 006: Twilio number with the ElevenLabs native integration

Status: accepted (2026-11-15). Supersedes the Telnyx part of 001; the rest of 001 stands.

## Decision
The hotel number is a Twilio number, connected through ElevenLabs' native Twilio integration (import with Account SID + Auth Token, assign the agent), not a Telnyx SIP trunk.
- The backend needs no Twilio credentials: they live only in ElevenLabs, which sets the Twilio webhook itself.
- First test call on a US local number. An Italian number follows once Twilio approves the Regulatory Bundle.

## Alternatives considered
- Telnyx SIP trunk (001): cheaper, and a SIP trunk works with any voice platform. But we would configure the trunk by hand (FQDN connection, transport, outbound profile, media encryption), and the caller ID was unverified without extra SIP headers.
- Twilio SIP trunk to ElevenLabs: same manual work as Telnyx, with no gain over the native integration.

## Why
- The first real call is the project's main unproven claim. The native integration has the fewest manual steps where it can go wrong.
- ElevenLabs documents `system__caller_id` as filled on Twilio calls, which get_guest_info needs.
- Twilio is the provider most reviewers will recognise, and it has the most docs and community answers.

## Consequences
- Costs more: US local $1.15/month plus $0.0085/min inbound; Italian numbers are much more (toll-free $27/month, $0.46/min). See docs/external/twilio.md, section 6.
- The number is tied more closely to ElevenLabs than a SIP trunk would be. Accepted: we are already locked in on the voice layer (001).
- No trial account: it can't buy regulated numbers and probably can't reach the agent.
- `system__call_id` is null (SIP only); `system__call_sid` holds the Twilio Call SID. Nothing in the repo uses either; tools bind `system__conversation_id`.
