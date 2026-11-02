# Langfuse Python SDK v5 (checked 2026-11-02; installed 5.1.0, verified against .venv source)

Docs: https://langfuse.com/docs/observability/sdk/overview , .../sdk/instrumentation , .../sdk/upgrade-path/python-v4-to-v5 , https://langfuse.com/docs/observability/features/masking , https://python.reference.langfuse.com/langfuse
Marked (src) = read in installed package `langfuse/_client/*.py`.

## 1. Server requirement
- SDK v5 needs self-hosted Langfuse >= 4.59.0 (upgrade guide). Not relevant to us: we use Langfuse Cloud (ADR 003).
- Spans go to OTLP `POST {base_url}/api/public/otel/v1/traces`, gzip, Basic auth public:secret, header `x-langfuse-ingestion-version: 4` (src).

## 2. Init, env vars, disabled mode
- `Langfuse(*, public_key, secret_key, base_url, host(deprecated), timeout=5, debug, tracing_enabled=True, flush_at, flush_interval, environment, release, sample_rate, mask, mask_otel_spans, ...)` (src). Keyword-only. One singleton per public_key; later args ignored.
- `get_client()` returns the singleton, creating `Langfuse()` from env if none exists. Explicit `Langfuse(...)` first, then `get_client()` elsewhere, is fine.
- Env: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL (LANGFUSE_HOST deprecated, still read), LANGFUSE_TRACING_ENABLED (`false` disables), LANGFUSE_TIMEOUT, LANGFUSE_FLUSH_AT, LANGFUSE_FLUSH_INTERVAL, LANGFUSE_SAMPLE_RATE, LANGFUSE_DEBUG, LANGFUSE_TRACING_ENVIRONMENT, LANGFUSE_RELEASE (src). `.env` should use BASE_URL.
- Missing key: `public_key or env` is None -> warning logged, client becomes no-op (NoOpTracer), no raise (src). Careful: env var set to the EMPTY string is not None, so it does NOT disable; pass `None` (not "") or set `tracing_enabled=False` when keys are empty.
- Disabled/no-op client: `.api`, `.async_api`, `create_dataset*`, `get_dataset` raise AttributeError/Error ("not initialized") (src). `flush()`/`shutdown()` are safe no-ops. `create_score` returns silently if tracing disabled.

## 3. mask
- Signature: `mask(*, data: Any, **kwargs) -> Any` (src types.MaskFunction; docs masking page). Return must be JSON-serialisable.
- Called synchronously when SDK attributes are created, for observation `input`, `output`, `metadata` (src span.py `_process_media_and_apply_mask`). Receives the raw object (str/dict/list), not the whole span: recurse yourself.
- Does NOT see: trace/observation names, tags, session_id, propagated metadata (UNVERIFIED for propagated metadata), third-party OTel spans. For those use `mask_otel_spans(*, params) -> MaskOtelSpansResult|None` (export stage, worker thread; exception drops the whole batch). Docs now recommend mask_otel_spans; `mask` is legacy but supported.
- If `mask` itself raises: behaviour UNVERIFIED; write it defensively.

## 4. Manual tracing (v5 names)
- Use `lf.start_as_current_observation(name=, as_type="span"|"generation"|"tool"|..., input, output, metadata, level, model, model_parameters, usage_details, cost_details, completion_start_time, trace_context)` (src). Children: `span.start_as_current_observation(...)`. Non-context version: `lf.start_observation(...)` then `.end()`.
- `start_as_current_span` / `start_as_current_generation`: NOT in the docs; appear only in stale docstrings. UNVERIFIED they exist; don't use.
- Update: `obs.update(output=..., usage_details={"input": n, "output": m}, model=...)` (docs example uses prompt_tokens/completion_tokens keys; both shown in src docstrings).
- Trace-level attrs: only via `from langfuse import propagate_attributes` (module function, not client method): `propagate_attributes(user_id, session_id, metadata: dict, version, tags: list[str], trace_name, environment, as_baggage=False)` (src). Wrap root span (or enter immediately inside). Limits: strings US-ASCII <=200 chars; metadata keys ASCII, JSON-encoded values <=200 chars; environment <=40 lowercase, not starting "langfuse". Only spans started after entry get them.
- `set_current_trace_io` / `span.set_trace_io` REMOVED in v5; trace input/output = root observation's.
- Asyncio: built on OTel contextvars; `with` blocks work in `async def`. Cross-context detach errors are swallowed (src). Calls run in other threads (`to_thread`) need context copied (asyncio.to_thread does copy it).
- One trace spanning many HTTP requests (each /llm turn is separate): `trace_context={"trace_id": Langfuse.create_trace_id(seed=call_id)}` (32 hex, deterministic; src docstring). Known issue: creates an empty phantom parent observation, https://github.com/langfuse/langfuse/issues/12896. Test before relying on it.

## 5. flush / shutdown / unreachable server
- `lf.flush()` blocks (OTel force_flush + score queue join + media queue join). `lf.shutdown()` flushes and joins threads; also registered via atexit (src). Short-lived scripts (evals) call `flush()` at end; in async code use `await asyncio.to_thread(lf.flush)`.
- Span export runs on a background BatchSpanProcessor thread; failures are logged, never raised into your code. Scores go through a queue with <=3 retries, failures logged and dropped (src). Docs: "cannot break your application".
- Block risk: flush()/shutdown() wait on network timeouts (default 5 s per request x retries). Exact worst case UNVERIFIED. Never call them on the request path.
- Direct REST calls (`create_dataset`, `create_dataset_item`, `get_dataset`, `auth_check`, `api.*`) are synchronous, DO raise on connection errors. `auth_check()` is blocking; docs say not for production.

## 6. Datasets, experiments, scores
- `lf.create_dataset(*, name, description, metadata, input_schema, expected_output_schema)`.
- `lf.create_dataset_item(*, dataset_name, input, expected_output, metadata, source_trace_id, source_observation_id, status, id)`: upsert by `id`; id must be globally unique across datasets (src). Fixed id is how we keep golden.json case ids stable.
- Archive: `create_dataset_item(..., id=, status="ARCHIVED")` upserts by id; docs say archived items are removed from future experiment runs (https://langfuse.com/docs/evaluation/experiments/datasets, "Edit/archive dataset items"). Docs do not say whether omitted fields are kept, so our sync resends input/expected_output/metadata when archiving. Every add/update/archive creates a dataset version, so sync writes only changed items. `get_dataset` raises `NotFoundError` for a missing dataset; item `status` is a str enum (`"ACTIVE"`/`"ARCHIVED"`). UNVERIFIED against a live project: whether `get_dataset(...).items` lists archived items.
- v5 has NO `item.run()` / `link` / manual dataset-run-item API (removed in v4/v5: https://langfuse.com/docs/observability/sdk/upgrade-path/python-v4-to-v5 ; `api.dataset_run_items` also removed, use `api.experiments`). A "dataset run" == "experiment".
- Link via `lf.get_dataset(name).run_experiment(name=, run_name=, task=, evaluators=, run_evaluators=, max_concurrency=50, metadata=, experiment_id=)` (src). `task(*, item, **kw)`, sync or async; item is a DatasetItem. Runs with same `run_name` on a dataset share one experiment id. It creates the traces itself (root name `experiment-item-run`), sets env `sdk-experiment`, uses propagated experiment attrs, and flushes at end. Our own runner can only link by calling run_experiment; manual linking of our own traces is UNVERIFIED/unsupported.
- Evaluator returns `Evaluation(name, value, comment, ...)` or dict -> stored as scores on the trace; run_evaluators -> scores on the run (`create_score(dataset_run_id=experiment_id)`).
- Scores: `lf.create_score(*, name, value, trace_id, observation_id, session_id, dataset_run_id, score_id, data_type, comment, config_id, metadata, timestamp, environment)`; `lf.score_current_trace(*, name, value, ...)` inside an active span; `span.score(...)`. Bool/int become float. Async via queue, fire-and-forget.

## Contradictions with docs/architecture.md
- None direct. Notes: architecture says "eval runs" go to Langfuse: v5 only supports that through `run_experiment` (no per-item linking API). Server must be >= 4.59.0. Tagging with git SHA and call_id/language: use propagate_attributes(tags=, metadata=, session_id=call_id) (200-char limits).
- rules/data.md (mask PII): `mask` covers input/output/metadata only; never put names/phones in trace_name, tags, session_id or span names.
