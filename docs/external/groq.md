# Groq API (checked 2026-11-02)

## 1. Endpoint and auth
Src: https://console.groq.com/docs/api-reference , https://console.groq.com/docs/openai
- Base URL `https://api.groq.com/openai/v1`; `POST /chat/completions`.
- Auth: `Authorization: Bearer $GROQ_API_KEY`, `Content-Type: application/json`.
- 400 error if sent: `logprobs`, `logit_bias`, `top_logprobs`, `messages[].name`. `n` must be 1. temperature 0 becomes 1e-8.
- Streaming: SSE, ends `data: [DONE]`. `stream_options` exists, properties not shown (UNVERIFIED).

## 2. Tool calling shape
Src: https://console.groq.com/docs/tool-use , api-reference above
- Request: `tools: [{type:"function", function:{name, description, parameters:<JSON Schema>}}]`. Only functions; max 128.
- `tool_choice`: `none` (default w/o tools), `auto` (default with tools), `required`, or `{"type":"function","function":{"name":"x"}}`.
- `parallel_tool_calls`: bool, default true.
- Response: assistant message has `tool_calls: [{id, type, function:{name, arguments}}]`. `arguments` is a JSON STRING.
- Reply: append the assistant message, then one `{role:"tool", tool_call_id:<same id>, content:<string>}` per call (the tool-use page also shows `name` on tool messages; see pitfall below). Loop until no `tool_calls`.
- Streaming tool_call deltas: not described on the pages read (UNVERIFIED). The proxy must pass them through unchanged.

## 3. Models with tool calling
Src: https://console.groq.com/docs/tool-use , https://console.groq.com/docs/models
| ID | Status | Speed t/s | Parallel tools |
|---|---|---|---|
| openai/gpt-oss-20b | production | 1000 | No |
| openai/gpt-oss-120b | production | 500 | No |
| llama-3.3-70b-versatile | production, DEPRECATED (see below) | 280 | Yes |
| llama-3.1-8b-instant | production, DEPRECATED | 560 | Yes |
| qwen/qwen3.8-27b | preview | 450 | Yes |
| minimaxai/minimax-m2.7, meta-models/muse-spark-open | preview | 260 / 350 | Yes |
- Context 131,072 for all above except minimax (196,608). Preview models "not for production", may vanish at short notice.
- Deprecations Src: https://console.groq.com/docs/deprecations : llama-3.3-70b-versatile and llama-3.1-8b-instant shutdown 2026-08-16 (already past today). Replacements: gpt-oss-120b / gpt-oss-20b (qwen3.6-27b for 70B, itself shut down 2026-09-14 -> qwen3.8-27b). The models page still lists the Llamas as production: contradictory. Do not use them; test before trusting.

## 4. Recommendation
- Primary: `openai/gpt-oss-120b` (production, not deprecated, 500 t/s, tools supported). Fallback/faster: `openai/gpt-oss-20b`.
- Italian quality: docs say nothing per model. UNVERIFIED; test with the IT eval cases.
- gpt-oss has no parallel tool calls. Decision: `GroqClient` deliberately does NOT send `parallel_tool_calls` (UNVERIFIED that the param is accepted on gpt-oss, and the live evals ran fine without it). The loop answers every tool call it receives, so a parallel call would still be handled. Revisit if Groq starts returning 400 on it or the model emits parallel calls. Fits "one question at a time".
- Reasoning latency/effort params for gpt-oss: not checked (UNVERIFIED).

## 5. Rate limits
Src: https://console.groq.com/docs/rate-limits
- Free-tier numbers are NOT in the fetched docs. Page says exact limits are in the console account limits page.
- The model table (labelled "base limits for Developer plan") shows gpt-oss-120b and 20b: 30 RPM, 1K RPD, 8K TPM, 200K TPD. Treat as an upper hint for free, UNVERIFIED. Llama models absent from the table.
- Implication: 8K TPM is tight; system prompt + tool schemas + history re-sent every turn. Keep prompt small, check console, handle 429.

## 6. Pitfalls
- `arguments` is a string: parse it, handle invalid JSON.
- `tool_call_id` must match. `content` must be a string (serialize results).
- Do not send `messages[].name` (400 per OpenAI-compat page) although the tool-use sample includes `name` on tool messages. Omit it. UNVERIFIED which wins.
- Each tool round trip is another inference call; adds latency per turn.
- Doc samples contain invalid JSON (trailing commas, # comments).

## Contradictions with docs/architecture.md
- Architecture names Groq generically; no model chosen. Any plan using llama-3.3-70b-versatile is invalid (shut down 2026-08-16 per deprecations page).
- Proxy must strip `messages[].name` and other unsupported fields (logprobs etc.) as well as `elevenlabs_extra_body`, or Groq returns 400.
- Base URL `.../openai/v1` is consistent with the "appends /chat/completions" open point in architecture.md; `/llm` is our own URL so it is moot.
