# 002: Single LLM with native tool calling, no LangGraph

Status: accepted

## Decision
One LLM call loop with native tool calling. The previous LangGraph version is not carried over.

## Why
- A phone call is one turn at a time, and native tool calling already handles it.
- A graph adds latency to every turn and a state machine to maintain.

## Revisit if
- A flow needs explicit multi-step state, such as group bookings or payments.
- Evals show the single prompt can't hold the policies.
