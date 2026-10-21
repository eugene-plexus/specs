# Row 12: Metrics export with names that last (LD4, B2-MET, MET-RU)

Lane GW, after row 11 (its queue names are part of this contract). Risk: cross; the `readMetrics` grant is an auth change and gets one review. Size: M-L. Calls: MET-NAMES, MET-AUTH, MET-PEOPLE, MET-OTLP, MET-ENGINE.

## 1. What the row delivers

- `GET /metrics` in Prometheus text on the gateway's own port, and on each agent's port for its engines.
- A scraper signs in with a client key that has "May read metrics". The console makes the key and prints the scrape configuration.
- An optional OTLP exporter (metrics and traces), set from the console, off by default, never sending prompts or answers.
- `/v1/systemone` decisions become request rows (B2-MET), and `bucket=hour` serves the stored rollups past retention (MET-RU).

## 2. The design

### Names (call MET-NAMES)

GenAI names are pinned to the semantic-conventions release current at build time, written here. Upstream marks the GenAI group as in development; Eugene keeps these names until a major release even if upstream renames, and `eugene_build_info{semconv=...}` says which.

- **Door view** (the gateway as a GenAI server), histograms: `gen_ai_server_request_duration_seconds`, `gen_ai_server_time_to_first_token_seconds`, `gen_ai_server_time_per_output_token_seconds`. Labels: `gen_ai_operation_name`, `gen_ai_request_model`, `gen_ai_response_model`, `error_type`, `door`.
- **Backend view** (the gateway as a client of each runtime or account): `gen_ai_client_operation_duration_seconds`, `gen_ai_client_token_usage` (`gen_ai_token_type`). Labels: `gen_ai_provider_name`, `runtime`, `node`, `driver`.

| Eugene's own | Type | Labels |
|---|---|---|
| `eugene_requests_total` | counter | door, model, outcome, tier, key_id, person |
| `eugene_tokens_total` | counter | type (input, output, cached), model, runtime, key_id, person |
| `eugene_attempts_total`, `eugene_cascades_total` | counter | model, driver, runtime, node, served, retry_disposition |
| `eugene_routing_seconds` | histogram | strategy |
| `eugene_affinity_total` | counter | model, outcome (hit, new, moved) |
| `eugene_wake_total`, `eugene_wake_wait_seconds` | counter, histogram | model, runtime |
| `eugene_in_flight`, `eugene_runtime_slots` | gauge | runtime, node |
| `eugene_budget_reserved_tokens`, `eugene_budget_pool_tokens` | gauge | runtime |
| `eugene_queue_waiting` | gauge | runtime, band |
| `eugene_queue_wait_seconds` | histogram | band, outcome |
| `eugene_queue_refused_total` | counter | reason, band |
| `eugene_circuit_open` | gauge | driver |
| `eugene_tool_executions_total` | counter | tool, outcome |
| `eugene_metrics_rows_dropped_total` | counter | |
| `eugene_client_key_info`, `eugene_build_info` | gauge, always 1 | key_id, key_name; component, commit, semconv |

**Engine (agent):** `eugene_engine_requests_waiting` (llama.cpp `requests_deferred`, vLLM `num_requests_waiting`), `_requests_running`, `_kv_cache_usage_ratio`, `_prompt_tokens_total`, `_generated_tokens_total`, `_draft_tokens_total`, `_draft_accepted_tokens_total`, `_scrape_ok`; labels node, runtime, model, engine. A counter the engine lacks has no series, never a 0. The engine's own series pass through under upstream's names with the same labels.

**Spans:** GenAI attributes where defined (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`). llm-d's `gen_ai.latency.*` only if the pinned release defines them; otherwise `eugene.latency.time_to_first_token` and `eugene.latency.time_in_queue`, and row 11's doc is corrected.

**Bounded series.** `model` is a configured slot or model, else `other`, so a made-up model name makes no series. `key_id` and `person` are bounded by the registry. Buckets are fixed, 0.05 to 120 s.

### Code

- **gateway `telemetry.py` (new):** instruments, a Prometheus text writer, an OTLP/HTTP JSON encoder. No new dependency (call MET-OTLP).
- **gateway `routes/telemetry.py` (new):** `GET /metrics`, `GET /v1/metrics/export`.
- `_record` in `routes/inference.py` calls `telemetry.observe(row)`. Gauges are read at scrape time from the routing table, budget and row 11's queue, read only.
- **B2-MET:** `create_decision` builds a `_Recording` and calls `_record(..., door="decisions")` on success and failure. Today it writes nothing.
- **OTLP:** one exporter task posts metrics to `<endpoint>/v1/metrics` every `telemetryOtlpIntervalSeconds` and batches spans to `<endpoint>/v1/traces`, through the gateway's one HTTP client (`is_internal()` decides the proxy). Spans: the door (root; takes an incoming `traceparent`), routing, each attempt; `traceparent` goes to the driver. Sampled once at the door. A full buffer drops spans and counts them; the exporter never blocks a request.
- **agent `engine_metrics.py`, `routes/metrics.py` (new):** read each running runtime's `/metrics` at scrape time, in parallel, 2 s each, and add labels.
- llama-server gets `--metrics` always; today `speculation.metrics_argv` adds it only when drafting (ENG file, §6).

### Access (call MET-AUTH)

- Gateway and agent `/metrics`, and `/v1/metrics/export`, admit an operator session or a client key with `readMetrics: true`. No credential: 401. A key without the grant: 403, "This key may not read metrics. Turn on May read metrics for it under Keys."
- The key is checked with admission `purpose: metrics`: no model, no lease. control's `client_admission.py` and the agent's standalone mirror (its own `client_admission.py`) accept it, and the agent's forward (`client_key_registry.py`) passes it on.
- "Make a scrape key" sets `allowedModels: []` (no inference) and `readMetrics: true`.

### Rollups (MET-RU)

- With `bucket=hour`, hours past retention come from `rollup` with `source: rollup`: counts, `tokensPerSecond` from sums, `latencyMeanMs`, `latencyMaxMs`; no percentiles. Hours inside retention stay `source: raw`. `bucket=none` stays raw only.
- Store v14 → v15 in place; `rollup` gains `first_ms_sum`, `first_ms_samples`, `prompt_tokens`, `cached_tokens`, `queued_ms_sum`, `refused`.

### Contract

```yaml
# gateway.yaml
/metrics: {get: {operationId: getPrometheusMetrics}}       # 200 text/plain, 401, 403
/v1/metrics/export: {get: {operationId: getMetricsExport}} # 200 MetricsExport
MetricsSource: {type: string, enum: [raw, rollup]}
MetricsGroup: {source, latencyMeanMs, latencyMaxMs}        # added
MetricsExport:
  prometheus: {path, lastScrapeAt, lastScrapeKeyName}
  otlp: {state: [off, ok, failing], endpoint, lastSuccessAt, lastError}
# agent.yaml: GET /metrics, same responses
# client-keys.yaml
ClientKeyLimits.readMetrics: {type: boolean, default: false}  # grants nothing else
ClientAdmissionRequest.purpose: [inference, logs, catalog, metrics]
```

Gateway config, from its schema: `telemetryOtlpEndpoint` (url; empty is off), `telemetryOtlpAuthorization` (secret), `telemetryOtlpSignals` (metrics, traces, both), `telemetryTraceSampleRatio` (default 1), `telemetryOtlpIntervalSeconds` (60), `telemetryExportPersonLabels` (false). Correct "which no endpoint serves yet" in `/v1/metrics/requests`.

### Console

- Metrics page, "Export": "Prometheus: scrape /metrics on the gateway and on each machine, with a key that may read metrics." Buttons "Make a scrape key" and "Copy scrape configuration" (every machine, with `authorization.credentials`).
- OTLP state: "Sending to http://collector:4318. Last sent 10:02." or "Export to http://collector:4318 is failing: connection refused. Requests are served as usual."
- The key editor: "May read metrics".

**Defaults.** Export is off. **Flag: private data.** Prometheus carries person and key labels behind the Metrics page's access. OTLP leaves the install, so person labels stay off there unless turned on (call MET-PEOPLE).

## 3. Repositories and codegen

specs, gateway, agent, control, ui (add control and ui to the row). Codegen: control, agent, gateway, ui for `client-keys.yaml`; gateway, ui for `gateway.yaml`; agent, control, ui for `agent.yaml`. Confirm by regenerating every consumer and diffing.

## 4. Tests that fail before the change

gateway `tests/test_telemetry.py`:
- `test_metrics_shows_ttft_and_requests_after_a_stream`: `gen_ai_server_time_to_first_token_seconds_count{...} 1` and `eugene_requests_total{door="chat",outcome="served",...} 1`. Today: 404.
- `test_metrics_refuses_no_key_and_a_key_without_read_metrics`, `test_a_made_up_model_name_makes_no_series`.
- `test_a_decision_writes_a_row`. Today: no row.
- `test_hour_buckets_past_retention_come_from_rollups`. Today: empty and truncated.
- `test_otlp_payload_has_no_message_text`: a canary in the prompt is in no exported byte.

control `test_metrics_purpose_needs_read_metrics`; agent `test_engine_metrics_are_labelled_per_runtime`.

## 5. Acceptance

**CI (Linux, about 6 min), `scripts/row12-metrics-acceptance.py`:** real control root, agent, gateway, driver; a stand-in llama-server with `/metrics`; a real Prometheus and OpenTelemetry Collector (pinned binaries, sha256 checked). OS-assigned ports, never 8079-8083; `EUGENE_PLEXUS_*` cleared.
1. Prometheus scrapes gateway and agent with a scrape key: `up == 1`.
2. After 10 requests (5 streamed, 2 to a made-up model, 1 decision): the counts, 5 TTFT samples, no made-up series, `door="decisions"` once.
3. A key without the grant: target down, 403.
4. `eugene_engine_requests_waiting{runtime=...}` follows the stand-in.
5. The Collector's file has metrics and spans with `gen_ai.request.model`, no canary, no person label.
6. With the Collector stopped, `/v1/metrics/export` says failing with the cause; requests are still served.
7. A v14 store migrates; 10-day-old rows are served as rollups.

**The reviewer should attack:** a scrape key that runs inference; an inference key that reads metrics; the standalone mirror; unbounded labels; prompt text in spans; the exporter slowing requests.

## 6. Do not change

- **gateway:** `routing.py`, `budget.py`, `admission.py`, `fair_queue.py` (row 11's; read only); `lifecycle.py`, `routes/admin.py` (ENG 13); `affinity.py` (ENG 15, 44).
- **ui:** `GatewayOperations.tsx`, `gatewayDashboard.ts` (WEB 38; charts over rollups are row 38's); `settingsTopics.ts` (WEB 33); `ConfigField.tsx`, `configValue.ts` (WEB 62).
- **control:** `person_access.py`, `permissions.py` (TRUST). **agent:** `apps.py`, `client_doors.py` (AG2). Every `scripts/codegen.py`.
- **Shared:** `metrics.py` (WEB 38, ENG 13): add columns only. `routes/inference.py` (OPS 1, GW 55): the decision `_record` and `observe` only. `client_admission.py` (GW 11, 24, 40): the `metrics` purpose only. `engines/speculation.py` (ENG 17, 41): `--metrics` always; the ENG lane lands it, or this row with the orchestrator's agreement.

## 7. Size, risks, calls

**Size:** M-L, about 3 days. One branch, `r12-metrics`: **12a (M)** contracts, `readMetrics`, gateway `/metrics`, decision rows; **12b (S)** rollups, store v15; **12c (S)** engine metrics, `--metrics`; **12d (M)** OTLP and the console. One acceptance run; one review of the access part.

**Risks:** the names become a public contract, and a later rename breaks alerts. `--metrics` opens `/metrics` on each llama-server port; it shows counts only.

**Calls only Troy can make (recommendation first):**
- **MET-NAMES.** GenAI names where defined, pinned to one release; `eugene_*` otherwise.
- **MET-AUTH.** A `readMetrics` key grant for scrapers, reviewed as an auth change.
- **MET-PEOPLE.** Person labels in Prometheus, yes; in OTLP, off by default.
- **MET-OTLP.** OTLP/HTTP JSON written by hand: no SDK, no gRPC, no new dependency. The OpenTelemetry Collector takes it.
- **MET-ENGINE.** Engine metrics on each agent, not gathered through the gateway: Prometheus already reports a machine that is down, and gathering would slow every scrape on one slow machine.
