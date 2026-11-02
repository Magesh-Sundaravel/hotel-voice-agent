# Evals

## Source of truth
evals/golden.json in the repo. Bilingual (Italian + English), includes hard cases.
Synced one-way to a Langfuse dataset. Never edit the dataset in the Langfuse UI.

## Case format
TODO: final JSON schema (id, language, input, expected tool calls, expected answer, scoring fields)

## Running
`uv run python -m evals.run`: sync -> run every case -> score -> push results to Langfuse, tagged with the git SHA.

## Scoring
TODO: how each field is scored and what counts as a regression

## Rule
Every new tool or prompt change gets at least one new case.
