# Guest data
- Guest data is PII: never log names, phone numbers or emails; log guest_id only
- Langfuse: mask phones and emails before they reach a trace. Names may appear in traces (accepted, see docs/decisions/003-langfuse-cloud.md)
- All database access goes through src/db/; no Supabase calls anywhere else
- Tests and evals use fake guests only; never commit real data
