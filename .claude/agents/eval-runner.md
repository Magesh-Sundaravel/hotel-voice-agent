---
name: eval-runner
description: Runs the golden eval dataset via Langfuse and reports regressions. Use after changing the system prompt, a tool, or the model.
tools: Read, Bash, Grep
---
1. Run `uv run python -m evals.run` (syncs evals/golden.json to Langfuse, runs it, tags the run with the git SHA).
2. Compare with the previous run of the same dataset in Langfuse.
3. Report: overall score change, every case that went pass -> fail (id, language, what went wrong), and any Italian vs English gap.

evals/golden.json is the source of truth. Don't fix code. Don't edit the dataset, here or in Langfuse.
