---
paths:
  - "src/tools/**"
---
# Agent tools
- One tool per file: Pydantic input and output models, async
- Never raise to the agent: return a structured error ({ok: false, reason}) it can say out loud
- Timeout on every external call (Google, Supabase)
- Write actions (create_booking, send_email) are idempotent: take an idempotency key
- Every tool call is traced in Langfuse
- Changing a tool's contract means updating docs/tools.md in the same change
