# 003: Langfuse, self-hosted on AWS, for observability and evals

Status: accepted

## Decision
Langfuse for tracing, eval runs and scores, self-hosted on AWS.
The golden dataset lives in the repo (evals/golden.json) and is synced one-way to Langfuse.

## Why
TODO

## Consequences
- Running Langfuse ourselves: TODO list required services and AWS cost
- Dataset is versioned in git; Langfuse dataset is a copy, never edited in the UI

## Revisit if
TODO
