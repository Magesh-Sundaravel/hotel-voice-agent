# 003: Langfuse Cloud, with PII masking, for observability and evals

Status: accepted (supersedes the original decision to self-host via Docker Compose)

## Decision
Langfuse Cloud (https://cloud.langfuse.com, EU region) for tracing, eval runs and scores.
The golden dataset lives in the repo (evals/golden.json) and is synced one-way to Langfuse.

## Why
- Nothing to run locally: no Postgres, ClickHouse, Redis or MinIO on the laptop.
- Traces stay reachable when the stack is down, and from a backend deployed off the laptop.
- Free tier covers a portfolio project.

## Consequences
- Traces leave the machine, so masking of names, phones and emails must happen before data reaches a trace (see `.claude/rules/data.md`). Tests and evals use fake guests only.
- Config is `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` in `.env`. Use `https://us.cloud.langfuse.com` if the project is in the US region.
- Dataset is versioned in git; Langfuse dataset is a copy, never edited in the UI.
- The Langfuse services in `docker-compose.yml` are kept as an optional self-host path for anyone replicating the project. They are not needed for normal development; point `LANGFUSE_BASE_URL` at `http://localhost:3000` to use them.

## Revisit if
- Masking cannot be guaranteed and guest data must stay on the machine (then self-host again).
- Free-tier limits are hit.
