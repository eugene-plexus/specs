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
| `eugene_budget_reserved_tokens`, `eugene_budget_pool_tokens` | gauge | runtime, node |
| `eugene_queue_waiting` | gauge | runtime, node, band |
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

## Calls answered by Troy (2026-10-21)

- **MET-AUTH: Choice 1.** A client key can get "May read metrics"; a second model reviews it.
- **MET-PEOPLE: Choice 2.** No person names in any exported metric, the Prometheus page included. Series per key stay.
- **MET-NAMES: Choice 2.** `eugene_*` names for every metric.
- **MET-ENGINE: Choice 1.** Each agent serves its own engines' metrics.

## What building found (2026-11-15)

**Built as designed, with the answered calls applied.**

- **Names (MET-NAMES, Choice 2).** Every name starts with `eugene_`; none is a GenAI name. The door view is `eugene_request_duration_seconds{door,model,outcome}`, `eugene_time_to_first_token_seconds{model}` and `eugene_time_per_output_token_seconds{model}`; the backend view is `eugene_attempts_total`, `eugene_attempt_duration_seconds{driver,runtime,node,served}` and `eugene_tokens_total`. The table in section 2 holds for the other names. Added, not in the table: `eugene_telemetry_series_dropped_total{family}`, `eugene_telemetry_spans_dropped_total`, `eugene_metrics_enabled`. `eugene_build_info` has `component`, `version`, `commit` and no `semconv`.
- **People (MET-PEOPLE, Choice 2).** No `person` label anywhere, so the `telemetryExportPersonLabels` setting is not built. `eugene_client_key_info{key_id,key_name}` is on the Prometheus page only; an OTLP payload leaves it out.
- **Spans.** `eugene.latency.time_to_first_token` (on the attempt) and `eugene.latency.time_in_queue` (on the door's span); the pinned conventions do not define `gen_ai.latency.*`. Spans are written from the finished request row, so their times are the row's: the door spans the request, attempts follow each other from its start. A caller's `traceparent` is continued, and one it did not sample is not traced. **`traceparent` is not sent to the driver**: a driver makes no span of its own yet, so nothing would read it.
- **Telemetry needs the request store.** Counters are made from the rows the store records, so `metricsEnabled: false` leaves the counters empty. `/metrics` says so with `eugene_metrics_enabled 0`.
- **Rollups (MET-RU).** `MetricsGroup.latencyMs` is no longer required: a `source: rollup` group has `latencyMeanMs`, `latencyMaxMs` and `tokensPerSecondMean` (a mean is not given as `p50`). The rollup also gained `token_ms_sum` (not in the design), because tokens over the time of requests that reported none would understate the rate. The rollup now attributes a request to the same attempt the live summary does and leaves refused requests out of its counts. Hours rolled up before v15 have the new columns at zero.
- **gateway#19** is built here: `affinity_key` (v15) and `MetricRequest.affinityKey`. It is null when `conversationAffinity` is off.
- **Access.** The gateway and the agent each check `limits.readMetrics` themselves, besides the authority's own refusal, and each is covered by a test that fails when the other is removed. Platform `client_admission.py` takes purpose `metrics`.
- **`--metrics`** is now always passed to llama-server, in `engines/speculation.py` (the ENG file), with one assertion changed in `tests/test_speculation.py`.

**Review fixes (2026-11-15).**

- A collector credential is trimmed when it is read from the config, and one a header cannot hold (a control character inside it) is refused with "the collector credential has a character a header cannot hold" and is never sent. An export failure says its own words only for a connect error, a timeout, a status and a bad address; any other says its exception type and nothing more, because the HTTP library quotes the header it refused. The cause is logged once for each change.
- The scrape key has `allowedTools: []` as well as `allowedModels: []`: an absent `allowedTools` permits every tool, and the root admits a search (purpose `search`) with no model.
- `eugene_budget_reserved_tokens`, `eugene_budget_pool_tokens` and `eugene_queue_waiting` carry `node`, so two machines' same-named runtimes are two series.
- An address that is not a URL (`http://[bad`) is named in `lastError`, and the exporter sends again when any export setting changes, not only the address.
- A standalone agent asks its own registry for every read of `/metrics`, so a revoked key or a withdrawn grant stops at once; an enrolled one keeps the root's answer for 15 s. The gateway keeps it for 10 s. A revoked key is refused by the gateway's own key policy before the kept answer is read.
- A browser that opens the agent's `/metrics` (no credential, asks for html) is sent to the console's `/metrics/` page, which the path hides.
- The agent logs why an engine's `/metrics` could not be read, once for each change.
- `scripts/row12-metrics-acceptance.py` runs in the specs integration (shard L3): a real root, agent, driver and gateway, a stand-in llama-server that serves `/metrics` only when started with `--metrics`, and a stand-in OTLP collector.

**Mixed versions.** A standby control root one release behind loops on a key record that has `readMetrics` (it refuses a field it does not know): update the standby before making the first scrape key, as for row 11's `band`. A gateway one release behind refuses a `readMetrics` key for inference, for the same reason. A key without it is answered as before.
