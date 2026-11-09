# ElevenLabs Agents (checked 2026-11-02)
Docs index: https://elevenlabs.io/docs/llms.txt (paths now /docs/eleven-agents/..., old /agents-platform/ still resolves)

## 1. Custom LLM
Src: https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm.md
- Dashboard: agent LLM = Custom LLM, enter Server URL + Model ID.
- Server must mimic OpenAI POST /v1/chat/completions (or /v1/responses). Examples serve /v1/chat/completions.
- Streaming required: text/event-stream, `data: {json}\n\n`, end with `data: [DONE]\n\n`.
- Body: messages, model, temperature, max_tokens, stream, user_id, tools (if system tools on), elevenlabs_extra_body (strip before forwarding upstream).
- Needs function calling support for system tools. Not usable with Realtime models.
- UNVERIFIED: whether ElevenLabs appends /chat/completions to the URL (docs silent; test; Groq base is .../openai/v1).
- UNVERIFIED: how the API key reaches the endpoint. Docs only show creating a workspace secret (dropdown "Create new secret"); no Authorization header or custom headers documented on this page. Check dashboard UI for a header/key field.
- Groq is not mentioned. Groq as a built-in provider vs custom: UNVERIFIED here.

## 2. Server (webhook) tools
Src: https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools.md
Src: https://elevenlabs.io/docs/api-reference/tools/create
- Config: url (may have {path} placeholders), method GET/POST/PUT/PATCH/DELETE, content_type JSON (default) or form-urlencoded.
- Headers: `request_headers` map; value = literal, secret, dynamic variable or env var. Shared secret: header type "Secret" (Create New Secret) in dashboard. Also Workspace Auth Connections (OAuth2, Basic).
- Timeout: `response_timeout_secs`, default 20, allowed 5-300 for webhooks.
- `execution_mode`: immediate (default), post_tool_speech, async.
- Param value sources (exactly one): description (LLM fills), dynamic_variable, is_system_provided, constant_value, is_omitted.
- Retries: UNVERIFIED, not documented. Assume none; make tools idempotent.
- Note: 5 s minimum timeout vs our ~1.5 s latency budget: the budget is ours to enforce server-side.

## 3. Caller ID / conversation id
Src: https://elevenlabs.io/docs/agents-platform/customization/personalization/dynamic-variables
- `system__caller_id` (caller phone), `system__called_number`, `system__call_id` (SIP Call-ID, SIP trunk only), `system__conversation_id`, `system__agent_id`.
- Prompts: `{{system__caller_id}}`. Tools: bind a param to the dynamic variable (dynamic_variable value type) so it is sent in the call, not LLM-generated. conversation_id is available the same way.
- Caller id/call id come from SIP `X-CALLER-ID` / `X-CALL-ID` headers if sent (sip-trunking page). UNVERIFIED: whether Telnyx populates caller_id without those headers (likely from SIP From, test it).
- Custom inbound `X-Foo-Bar` headers become `{{sip_foo_bar}}`.
- Caller id is unauthenticated data; do not use for auth (docs say same for system__user_id).

## 4. Telnyx SIP trunk (inbound)
Src: https://elevenlabs.io/docs/eleven-agents/phone-numbers/telephony/telnyx.md
Src: https://elevenlabs.io/docs/eleven-agents/phone-numbers/sip-trunking.md
- Telnyx: create FQDN-type SIP connection; FQDN `sip.rtc.elevenlabs.io`; assign your number on Numbers tab.
- Inbound tab: destination number format +E.164, transport TCP (docs for Telnyx), pick region. Outbound: voice profile + credentials.
- ElevenLabs side: import number as SIP trunk phone number (E.164, leading + must match), assign agent. Endpoint sip.rtc.elevenlabs.io: TCP 5060, TLS 5061 (recommended prod), UDP experimental.
- Media encryption Disabled/Allowed/Required (test Allowed first). Codecs G.722, PCMU, PCMA. TLS >= 1.2. Digest auth recommended; else ACL.
- UNVERIFIED: Telnyx-specific TLS/SRTP settings.

## Contradictions with docs/architecture.md
Not checked: architecture.md was not read (task said edit/touch nothing else). Compare manually, especially LLM auth and tool retry assumptions.

## 5. Custom LLM proxy follow-up (checked 2026-11-09; supersedes the UNVERIFIED lines in section 1 where noted)
Src: https://elevenlabs.io/docs/api-reference/agents/create.md (CustomLLM schema)
Src: https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm/groq-cloud.md
Src: https://elevenlabs.io/docs/eleven-agents/integrate/environment-variables.md
Src: https://elevenlabs.io/docs/eleven-agents/customization/personalization.md
Src: https://elevenlabs.io/docs/eleven-agents/customization/tools/system-tools/language-detection.md
Src: https://elevenlabs.io/docs/eleven-agents/customization/voice/customization/language.md
- Path: still UNVERIFIED. Docs disagree: Groq guide enters base `https://api.groq.com/openai/v1` (implies append); env-vars example sets url `.../v1/chat/completions` (full path). Schema: url = "URL of the Chat Completions compatible endpoint". Serve both `/llm/v1` and `/llm/v1/chat/completions`, log the path hit.
- Auth: VERIFIED fields `custom_llm.api_key` (workspace secret ref `{secret_id}` or env var), `custom_llm.request_headers` (literal | secret `{secret_id}` | dynamic var `{variable_name}` | env var), `auth_connection` ("only ... Authorization Bearer token are supported"). UNVERIFIED: api_key sent as `Authorization: Bearer` (implied, not stated). Safest: Secret-type request header, same as tools.
- IDs in body: VERIFIED none documented (no conversation_id/caller/call id fields). user_id: only seen in example server code; UNVERIFIED that it is populated for phone calls.
- IDs via headers: VERIFIED schema allows a dynamic-variable header on custom LLM. UNVERIFIED that `system__conversation_id` resolves there (docs only say system vars work for tool params/headers). Test.
- elevenlabs_extra_body: set via `custom_llm_extra_body` in conversation_initiation_client_data. Inbound-call initiation webhook runs for SIP trunk, receives caller_id, called_number, call_sid, agent_id, conversation_id (+ call_id, sip_headers on SIP), may return custom_llm_extra_body: VERIFIED. That it arrives as `elevenlabs_extra_body` and needs a Security override toggle: UNVERIFIED. No `{{var}}` templating into extra body documented.
- Languages: primary `conversation_config.agent.language` + `conversation_config.language_presets` per extra language (first message etc. overridable). `language_detection` system tool (params `language`, `reason`) switches mid-call; target languages must be in agent settings. VERIFIED.
- Current language to LLM/tools: no `system__` language variable documented (UNVERIFIED/absent). Our proxy sees the language_detection call in `tools`/messages since our LLM emits it (inference). Alternative: Update state system tool sets a custom dynamic var, bindable to tool params (UNVERIFIED end to end).
- Webhook body: VERIFIED `request_body_schema` "object which will be sent as the json body"; properties = top-level keys, application/json default. Property `dynamic_variable` binds a var (e.g. system__conversation_id) instead of LLM fill; `is_system_provided` also exists. VERIFIED schema; system__ binding per dynamic-variables page.
- Contradicted architecture.md ("no custom headers are documented for custom LLMs" and the `/llm` open point): fixed there on 2026-11-09; the proxy now authenticates with a Secret-type request header.
