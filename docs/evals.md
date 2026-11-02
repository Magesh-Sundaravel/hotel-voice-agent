# Evals

## Source of truth
evals/golden.json in the repo. Bilingual (Italian + English), includes hard cases.
Synced one-way to a Langfuse dataset. Never edit the dataset in the Langfuse UI.

## Case format
Pydantic models in `evals/schema.py` are the schema; `tests/test_eval_schema.py` validates `golden.json` against them.

```
{ "today": "2026-11-02",            // injected into the system prompt and the tools
  "cases": [ {
    "id": "it-relative-date",       // unique; becomes the Langfuse dataset item id
    "language": "it",               // "it" | "en": every reply must be in this language
    "tags": ["relative-date"],      // free-form, for slicing results
    "turns": [ {                    // scripted caller lines, at least one
      "caller": "Avete una camera per domani sera?",
      "expect": {
        "tool_calls": [ {"name": "check_availability", "args": {"guests": 2}} ],
        "must_not_call_tools": false,
        "exclusive": false
      } } ] } ] }
```

- Cases run against the seed repository (`src/db/seed.py`), so tool results are fixed.
- Callers are scripted. There is no simulated-caller LLM.
- Tags in use: `relative-date`, `missing-info`, `limited-availability`, `season-boundary`, `too-many-guests`, `past-date`.
- Tags planned, no case yet (they need checks the scorer does not have): `out-of-scope` (a booking request we cannot do yet), `language-switch`.

## Running
`uv run python -m evals.run`: sync -> run every case -> score -> push results to Langfuse, tagged with the git SHA.

## Scoring
Deterministic checks only. No LLM judge yet.
Per turn:
- Tool calls: every call in `expect.tool_calls` must appear among the agent's calls, in that order. For each, every key listed in `args` must match (compared as strings, so `"2"` equals `2`); other args are ignored. Extra calls are allowed (e.g. a read-only `get_rates` after `check_availability`) unless `exclusive` is true, which requires the agent's calls to be exactly the expected ones.
- `must_not_call_tools`: the agent must answer in words without calling any tool (e.g. it asks for the missing date).
- Reply rules, always on: the reply is not empty, has no markdown, no digits or ISO dates, at most 2 sentences, and its language equals `language`. The language check is a stopword heuristic for it/en.
A case passes only if every check on every turn passes.
Run score = pass rate over all runs (cases x repeats), reported overall and split Italian vs English. A case that passes in some repeats and fails in others is listed as flaky.
Each case runs `--repeats` times (default 5), sequentially. The Groq client waits and retries on HTTP 429 (limits are about 30 requests/min and 8K tokens/min, UNVERIFIED for the free tier). A request that still fails counts as a failed run with the reason `request failed: <error type>`; it does not stop the eval. A full default run is about 50 case runs, so use `--repeats 1` or 2 while iterating.
Regression (a case that passed in the previous run of the same dataset and fails now) is NOT built yet. The runner prints rates and flaky cases and always exits 0. Comparing with the previous run belongs with the Langfuse sync.
Known gap: whether a spoken price or availability statement is correct is not checked. Tool args are the proxy. Add a judge if that proves too weak.

## Rule
Every new tool or prompt change gets at least one new case.
