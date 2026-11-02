# Observability (Langfuse)
- Tag every trace with call_id and language (it/en)
- Tag eval runs with the git commit SHA
- Langfuse client and config live in one place; no ad-hoc client creation
- Tracing must never break a call: if Langfuse is down, log a warning and continue
