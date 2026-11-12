---
name: diagnosing-bugs
description: Find the root cause of a bug before fixing it. Use when a test, an eval case, a webhook or a live call breaks, or when the agent behaves differently than expected.
---
# Diagnosing bugs

Do not change code until the cause is known.

1. **Reproduce.** Get the smallest repeatable case: a failing unit test, a single eval (`uv run python -m evals.run --case <id>`), or a CLI session (`uv run python -m src.agent.cli`). If it only happens on a live call, find the trace in Langfuse by `call_id`.
2. **Locate the layer.** Decide where it goes wrong, in this order:
   - Prompt or model: the model called the wrong tool, skipped a step, or spoke badly. Check the system prompt (src/agent/prompts/) and the tool descriptions (src/agent/registry.py).
   - Tool: wrong result for valid arguments. Check the tool module in src/tools/.
   - Data: wrong rows or a bad query. Check src/db/ and the migrations in db/migrations/.
   - Glue: auth, argument binding, streaming or timeouts. Check src/voice/ and the vendor notes in docs/external/.
3. **Form one hypothesis** and test it with a log line, a breakpoint or a narrower test. Discard it if the evidence disagrees. Never log PII while debugging: `guest_id` only.
4. **Write a failing test** that captures the bug, then fix it (see the tdd skill).
5. **Check for regressions:** `uv run pytest -q`, and the eval-runner agent if the prompt, a tool or its description changed.
6. Report the cause in one or two sentences, the fix, and the test that now guards it.
