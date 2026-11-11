---
name: tdd
description: Build a feature test-first with red, green, refactor cycles. Use when implementing a tool, a repository method or any behaviour change (step 3 of the CLAUDE.md workflow).
---
# Test-driven development

Work in small cycles. Each cycle adds one behaviour.

1. **Red.** Write one failing test in tests/ for the next behaviour in the contract (docs/tools.md). Run `uv run pytest -q tests/<file> -x` and confirm it fails for the expected reason, not an import or typo error.
2. **Green.** Write the least code that makes it pass. Run the same test, then the full suite with `uv run pytest -q`.
3. **Refactor.** Clean up names and duplication with the suite green. Run `uv run ruff check .` and `uv run ruff format .`.
4. Repeat until every line of the contract has a test: the happy path, each `reason`, idempotency on a retried call, and the timeout.

Project conventions:
- Use the in-memory repositories and the fixtures in tests/booking_fixtures.py; no network in unit tests. Postgres tests skip themselves when DATABASE_URL is unset.
- Fake guests only, with phone numbers from the reserved +1 202 555 01xx range; never real data.
- Assert on the structured result (`ok`, `reason`, fields), never on the exact spoken wording.
- Tools never raise to the agent: test that unexpected errors come back as `{ok: false, reason}`.
- Stop and tell the user if a test shows the contract itself is wrong; update docs/tools.md in the same change.
