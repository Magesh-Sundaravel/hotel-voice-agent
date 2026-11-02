# Guest data
- Guest data is PII: never log names, phone numbers or emails; log guest_id only
- Same for Langfuse: mask names, phones and emails before they reach a trace
- All database access goes through src/db/; no Supabase calls anywhere else
- Tests and evals use fake guests only; never commit real data
