# 004: Direct Postgres (asyncpg), not the supabase client

Status: accepted

## Decision
The backend talks to the hosted Supabase Postgres directly with asyncpg, through the session pooler (`DATABASE_URL`). The `supabase` Python client, and the REST API it uses, are not used. RLS is on for every table with no policies, so the public REST API exposes nothing.

## Why
- Booking (pick a free room, then an idempotent insert) needs a transaction. The REST API has none, so it would have to live in plpgsql functions called over RPC.
- Integration tests run inside a transaction that is rolled back, so they leave the hosted database untouched.
- One script (`src/db/migrate.py`) applies the schema and seed. The client cannot run DDL.
- No HTTP hop per query, which helps the ~1.5 s tool budget.

## Revisit if
- We need Supabase Auth, Storage or Realtime.
- Code outside the backend (a browser or mobile app) needs to read the data.
