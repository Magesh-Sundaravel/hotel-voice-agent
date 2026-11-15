# Twilio -> ElevenLabs Agents, inbound (checked 2026-11-15)
Official docs only. ElevenLabs index: https://elevenlabs.io/docs/eleven-agents/llms.txt

## 1. Native integration
Src: https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/native-integration.md
Src: https://elevenlabs.io/docs/eleven-agents/api-reference/phone-numbers/create.md
- Dashboard: ElevenAgents > Phone Numbers > import. Fields: Label, Phone Number, Twilio SID, Twilio Token.
- Credentials: Account SID (`AC...`) + Auth Token, or (docs "Recommended") an API key: key SID (`SK...`) in the SID field, key Secret in the Token field.
- API: `POST https://api.elevenlabs.io/v1/convai/phone-numbers`, body `provider: "twilio"`, `label`, `phone_number`, `sid`, `token`; optional `agent_id`, `enable_sms` (default true, set false for voice-only numbers), `region_config` {`region_id` us1|ie1|au1, `token`, `edge_location`}, `account_auth_token`. Returns `phone_number_id`. Auth header not shown on the page; `xi-api-key` is the standard ElevenLabs header.
- API-key catch (API reference only, not on the dashboard guide): `account_auth_token` is "required for API Key imports so inbound webhook signatures can be validated". UNVERIFIED: whether the dashboard asks for it too. Account SID + Auth Token avoids the question.
- Webhook: "ElevenLabs automatically configures the Twilio phone number with the correct settings". Nothing to set in the Twilio console. The exact voice URL/TwiML it writes is not documented.
- Number must be a purchased number in the Twilio account. Verified caller IDs are outbound-only and cannot be assigned an agent.
- Assign: pick the agent in the number's inbound dropdown (or `agent_id` on import), then call the number.

## 2. Backend credentials
- None needed for inbound-only. Twilio credentials live only in ElevenLabs. Twilio sends the call to ElevenLabs, and ElevenLabs calls our tool webhooks as it does today. This is an inference: no doc page says it outright, and none asks the tool server for Twilio credentials.
- We would need them only for the optional conversation-initiation webhook (section 3) or for outbound/register-call (https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/register-call.md), and neither needs them on our side for inbound.

## 3. Call metadata
Src: https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables.md
Src: https://elevenlabs.io/docs/eleven-agents/customization/personalization/twilio-personalization.md
- `system__caller_id` (caller E.164, e.g. "+14155552671"), `system__called_number`, `system__call_sid` (Twilio Call SID, Twilio calls only), `system__conversation_id`, `system__agent_id`. All may be null when not applicable.
- `system__call_id` is SIP trunk only, so it is null on Twilio native calls.
- Optional initiation webhook: ElevenLabs POSTs `caller_id`, `agent_id`, `called_number`, `call_sid`, `conversation_id`. It returns `{type: "conversation_initiation_client_data", dynamic_variables, conversation_config_override}`, and `dynamic_variables` "must contain all dynamic variables defined for the agent". You enable it in ElevenAgents settings (URL + secret headers) and in the agent's Security tab. No timeout is stated.

## 4. Trial accounts
Src: https://www.twilio.com/docs/usage/trials/try-out-voice
Src: https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account.md
Src: https://www.twilio.com/docs/phone-numbers/regulatory/faq
- Calls only to and from verified numbers (max 5), only in your sign-up country, 10 min per call, 75 min total.
- `<Stream>`, `<ConversationRelay>`, `<Dial><Sip>`, `<Dial><Number>` are blocked on trial and replaced by a spoken "The {verb} verb is not available on trial accounts." The docs don't say which TwiML ElevenLabs uses (likely a media stream), so a trial probably can't reach the agent. UNVERIFIED: no ElevenLabs page mentions trials.
- Trial accounts cannot buy regulated numbers, which rules out Italy.
- "Press any key" trial announcement before TwiML: UNVERIFIED. Only the Help Center mentions it (https://help.twilio.com/articles/360036052753), and that page would not load; the current docs pages don't mention it.
- Conclusion: upgrade (add funds) before testing.

## 5. Italy (+39)
Src: https://www.twilio.com/en-us/guidelines/it/regulatory
Src: https://www.twilio.com/docs/phone-numbers/regulatory/faq
- A Regulatory Bundle must be approved before you can buy the number.
- Local: address inside the number's prefix area (no PO box). Business: name, VAT/registration ID, proof of address (registry extract, utility bill, tax notice, rent receipt, deed), plus the representative's ID document, date and place of birth, codice fiscale and nationality. Individual: ID document + proof of local address + the same personal data.
- Mobile: address anywhere in the world, same documents. Toll-free: businesses only.
- Review: Twilio "strive[s] ... within a 72-hour timeframe". Documents in about 24 business hours.
- Cheapest first test: a US local number on an upgraded account (no bundle needed for US local: UNVERIFIED, though none is listed). Call it from a verified or any phone. International call cost to the caller is not covered here.

## 6. Pricing (USD, list prices)
Src: https://www.twilio.com/en-us/voice/pricing/us
Src: https://www.twilio.com/en-us/voice/pricing/it
Src: https://www.twilio.com/en-us/sip-trunking/pricing/it (as of Oct 2026)
- US: local $1.15/mo, inbound $0.0085/min. Toll-free $2.15/mo, $0.0220/min.
- IT: toll-free $27/mo, inbound $0.4614/min. Mobile number $45/mo. Local geographic number price and local or mobile inbound rate: not listed on any page (UNVERIFIED, check the Console or the Pricing API).
- ElevenLabs per-minute agent cost is extra and not covered here.

## Impact on this repo (checked 2026-11-15)
- Tool webhooks bind `call_id` to `system__conversation_id` and `caller_phone` to `system__caller_id` (`src/voice/export_tools.py`). Both are filled on Twilio calls, so nothing in the code changes.
- `X-Call-Id` on the unused `/llm` proxy also carries `system__conversation_id`, not the SIP-only `system__call_id`.
