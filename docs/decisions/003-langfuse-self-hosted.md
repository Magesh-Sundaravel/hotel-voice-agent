# 003: Langfuse, self-hosted locally via Docker Compose, for observability and evals

Status: accepted

## Decision
Langfuse for tracing, eval runs and scores, self-hosted on the developer's machine through `docker-compose.yml`.
The golden dataset lives in the repo (evals/golden.json) and is synced one-way to Langfuse.

## Why
- Guest PII never leaves the machine (masking still applies, see `.claude/rules/data.md`).
- Keeps the project simple and free of cloud cost; the same compose file runs the whole demo.

## Consequences
- Services required: langfuse-web, langfuse-worker, Postgres, ClickHouse, Redis, MinIO (S3-compatible storage). Taken from the official Langfuse compose file; images are the v4 tags.
- Cost: no cloud bill. It needs RAM and disk on the laptop (ClickHouse is the heavy part).
- Traces are reachable only while the stack is up. LLM and tool traces come from the backend in the same compose network (`http://langfuse-web:3000`).
- Dataset is versioned in git; Langfuse dataset is a copy, never edited in the UI.
- Moving to AWS later means running the same services there (or switching to Langfuse Cloud with masking).

## Revisit if
- We deploy the backend off the laptop and need traces from it.
- The local stack gets too heavy for the machine.
