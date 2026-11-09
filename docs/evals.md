# Evals

## Source of truth
evals/golden.json in the repo. Bilingual (Italian + English), includes hard cases.
Synced one-way to a Langfuse dataset. Never edit the dataset in the Langfuse UI.

## System prompt
The prompt lives in `src/agent/prompts/receptionist.md` (variable: `{{today}}`, Langfuse syntax). The call path reads this file; it never fetches from Langfuse.
`uv run python -m evals.sync` uploads it to Langfuse as prompt `hotel-receptionist`, labelled `production`, with the git SHA as commit message. It creates a new version only when the text differs from the current production version. Never edit the prompt in the Langfuse UI.

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
        "exclusive": false,
        "forbidden_tools": ["create_booking"]   // must not be called this turn
      } } ],
    "caller_phone": "+12025550101" } ] }  // optional caller ID; absent = withheld
```

- Cases run against the seed repository (`src/db/seed.py`), so tool results are fixed. Every run of a case gets a fresh copy, so a booking made in one run never leaks into another.
- The seed bookings have fixed references: 482913 (Giulia Rossi, Penthouse, 24 to 28 December 2026), 615204 (James Carter, Suite) and 730158 (Marco Bianchi, Suite), both 30 December to 3 January. Seed guest phones are +12025550101 to 0103.
- `forbidden_tools` is how a case checks that the agent waits for the caller's yes: the turn that reads a booking back forbids the write, and the caller's yes turn expects it.
- Callers are scripted. There is no simulated-caller LLM.
- Tags in use: `relative-date`, `missing-info`, `limited-availability`, `season-boundary`, `too-many-guests`, `past-date`, `booking-read`, `booking-create`, `booking-modify`, `booking-cancel`, `returning-caller`, `confirm-before-write`, `confirmation-email`.
- Tags planned, no case yet (they need checks the scorer does not have): `language-switch`.

## Running
`uv run python -m evals.run`: sync the prompt and the dataset -> run every case -> score -> record one Langfuse experiment.
`uv run python -m evals.sync` does only the sync step.

Run part of the dataset while iterating: `--case ID` (repeatable) and `--tag TAG` (repeatable) pick cases by id or by tag; a case is run if it matches either. An unknown id or a tag that matches nothing is an error. The whole dataset is still synced, so nothing is archived. A partial experiment is named with a `-partial` suffix and has run metadata `cases` listing what ran, so it is never mistaken for a full run. Compare only experiments that ran the same cases.
Example: `uv run python -m evals.run --tag booking-cancel --repeats 1`.

- **Dataset sync:** golden cases become items of the Langfuse dataset `hotel-golden`, keyed by case id. The item input holds only what the caller says; the checks go in `expected_output`. Only items that changed are written (every write is a new dataset version). A case removed from `golden.json` is archived, which drops it from later runs.
- **Experiment:** one experiment per run, named `<git sha>-v<prompt version>-<MMDD-HHMM>` (UTC). Each case is one item and gets a score `pass_rate` (the share of its repeats that passed) with the failure reasons as the comment. Traces of the run (turns, model calls, tool calls) hang under each item.
- **Run metadata:** `git_sha` (ends in `-dirty` if the tree has uncommitted or untracked files), `prompt_version`, `model`, `tools` (names), `tools_hash` (changes when any tool's name, description or schema changes), `repeats`.
- **Comparing:** in Langfuse open the dataset, select two experiments and compare. Cases whose `pass_rate` moved are the effect of the change; `tools` and `tools_hash` say whether the tools differed.
- **Without Langfuse keys** the run is local: same report, nothing uploaded.
- The prompt text is not linked to the traces. Which prompt a run used is in its name and `prompt_version`.

## Scoring
Deterministic checks only. No LLM judge yet.
Per turn:
- Tool calls: every call in `expect.tool_calls` must appear among the agent's calls, in that order. For each, every key listed in `args` must match (compared as strings, so `"2"` equals `2`); other args are ignored. Extra calls are allowed (e.g. a read-only `get_rates` after `check_availability`) unless `exclusive` is true, which requires the agent's calls to be exactly the expected ones.
- `must_not_call_tools`: the agent must answer in words without calling any tool (e.g. it asks for the missing date).
- Reply rules, always on: the reply is not empty, has no markdown, no digits or ISO dates, at most 2 sentences, and its language equals `language`. The language check is a stopword heuristic for it/en.
A case passes only if every check on every turn passes.
While running, each finished case prints one progress line, e.g. `[3/29] PASS  en-relative-date  (1/1, 42s)` (PASS only when every repeat passed). The full report follows at the end.

Run score = pass rate over all runs (cases x repeats), reported overall and split Italian vs English. A case that passes in some repeats and fails in others is listed as flaky.
Each case runs `--repeats` times (default 5), sequentially. The Groq client waits and retries on HTTP 429 (limits are about 30 requests/min and 8K tokens/min, UNVERIFIED for the free tier). A request that still fails counts as a failed run with the reason `request failed: <error type>`; it does not stop the eval. A full default run is about 50 case runs, so use `--repeats 1` or 2 while iterating.
Regression (a case that passed in the previous run of the same dataset and fails now) is NOT checked in code. The runner prints rates and flaky cases and always exits 0. Compare two experiments in the Langfuse UI.
Known gap: whether a spoken price or availability statement is correct is not checked. Tool args are the proxy. Add a judge if that proves too weak.

## Rule
Every new tool or prompt change gets at least one new case.
