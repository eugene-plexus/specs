# The metrics page becomes a dashboard, and the gateway learns to time the first token

**Status: built 2026-09-21.** Troy picked this slice ("Additional Metrics,
Graphs, Statistics, and performance data") over MCP tooling and multi-user
roles, and delegated the content: *"I expect you to know what information will
be most interesting and useful for enthusiasts... All I know is that our UI
and UX must be top notch."* This document records what was measured, what was
decided, and why the two headline numbers are the ones enthusiasts actually
quote.

## §0 What exists, measured before designing

Three inventories over the working trees (gateway, ui, agent+library), same
day. The load-bearing facts:

- **TTFT is recorded nowhere.** M8 scoped it out explicitly
  (`m8-retained-request-metrics.md` §"Out", restated at M10), and the only
  TTFT numbers in the org are client-side: the playground's
  `firstFrameMs` (browser clock) and load-script instruments. The gateway's
  `tokensPerSecond` is `completion_tokens / serving_attempt.elapsed_ms` — a
  whole-attempt rate that **includes prefill**, so it understates decode
  speed on every long prompt, worst on exactly the hardware-limited box an
  enthusiast is tuning.
- **The time series already exists and nothing reads it.**
  `GET /v1/metrics?bucket=hour` has been in the contract since M8, computed
  from raw rows with honest per-bucket percentiles — and
  `ui/src/app/metrics/page.tsx` never sends `bucket`. The history chart's
  data was one query param away the whole time.
- **Percentiles cannot be recombined client-side.** `bucket=hour` groups by
  the full `(model, driver, runtime, node, backend)` tuple. A UI holding
  per-backend groups can sum `requests` across them, but the install-wide
  p90 latency is not computable from per-group p90s. An overview chart
  therefore needs the server to aggregate at a coarser grain — a new
  `groupBy` parameter, not client-side math that would be quietly wrong.
- **The one recording point that covers both doors:** every streamed attempt
  passes `TieredClient.stream`'s `async for event in stream` loop
  (`driver_client.py`), which already holds `started = time.perf_counter()`
  and fires `on_attempt_end`. Recording the first event there is per-attempt
  (matching where `elapsed_ms` lives), covers the OpenAI and Anthropic doors
  for free, and needs one hook kwarg + one `AttemptRow` field + one column.
- **No chart library, and none wanted.** The UI's only chart is R6.1's
  hand-rolled inline SVG (`ProfileBenchmark.tsx`), `currentColor`-themed,
  paired with a data table for accessibility. Series colors are bounded by
  the theme system: four accent *roles*, per-theme values, never a raw hex.
- **Non-streamed requests have no TTFT by construction** — `generate()`
  returns a completed response. The field is null there, and null must render
  as "unreported", never 0 (the page's standing rule).

## §1 What enthusiasts want, ranked from the field research

From the two threads (T1 2026-09-07, T2 2026-09-17) and the peer products:

1. **Decode tok/s** — the number people post and compare. Whole-request
   rates are not comparable across prompt lengths; decode rates are.
2. **TTFT** — "does it feel fast", and the honest place cold starts show up.
3. **The comparison table** — model × backend × node. M8's own record says
   "is vLLM faster than llama.cpp for this model on this box" was *not
   answerable by the system*; the rows have been retained ever since.
4. **Failover honesty** — did tier 2 quietly serve everything; what a wake
   costs (`swappedIn`/`waitedMs` already separate it).
5. **History** — requests, tokens, errors, latency over time.

Deliberately **not** built: a prompt-processing (pp) rate derived from TTFT.
TTFT includes routing and the driver hop, so `prompt_tokens / ttft`
understates pp in a way that looks precise — a confidently wrong number, the
class of defect this project keeps finding. Real pp curves are the
benchmark's job (`llama-bench` already sweeps; extending R6.1 to
`--n-prompt` sweeps is a future slice). Also out: VRAM/load-time history —
both need new agent-side collection loops (nothing in the agent retains
samples today; measured in §0), which is a new responsibility and its own
slice.

## §2 The contract change (`gateway.yaml`)

- **`MetricAttempt.firstMs`** — ms from attempt start to its first streamed
  event. Null for non-streamed attempts and historical rows.
- **`MetricsGroup.ttftMs`** (`Percentiles | null`) — over streamed serving
  attempts. Includes the gateway→driver hop, so dominated by prefill on a
  local engine but not a pure prefill measurement; the description says so.
- **`MetricsGroup.decodeTokensPerSecond`** (`Throughput | null`) — completion
  tokens over the serving attempt's time *after* its first event. Qualifies
  only with ≥2 tokens and ≥250 ms of decode window (the playground's own
  guard, kept consistent), so its `samples` can be lower than
  `tokensPerSecond.samples`. `tokensPerSecond` stays beside it: whole-attempt
  rate, prefill included — the two differing is the prefill cost made
  visible.
- **`groupBy` on `GET /v1/metrics`** — `backend` (default, today's tuple),
  `model` (collapse the backend dims), `total` (one group per bucket). Exists
  because percentiles do not recombine; the coarser grain is computed over
  the bucket's raw rows, so its p90 is a real p90.

Codegen radius: `gateway.yaml` is consumed by `gateway` and `ui` only; the
other four stay back, correctly.

## §3 The gateway build

- `SCHEMA_VERSION = 5`; in-place migration from 2/3/4 adds
  `attempt.first_ms INTEGER` (the existing ALTER-ADD pattern).
- `RoutingHooks.on_attempt_end` gains `first_ms: int | None = None`;
  `TieredClient.stream` stamps `perf_counter()` on the first event and passes
  it on all three end paths (success, exception, finally) — a stream that
  emitted a token and then broke still had a TTFT, and recording it is
  honest. `generate()` never passes it: no first token exists to time.
- `summary()` gains `group_by`; the attributed-attempt SELECT also reads
  `served.first_ms`; per group it collects `_ttft` (first_ms present) and
  `_decode` (usage + window guard) and emits the two new fields, null when
  empty.

## §4 The UI build

`/metrics` becomes a dashboard, top to bottom:

1. **Stat tiles** — requests, error rate, cascade rate, p50 latency,
   p50 TTFT, p50 decode tok/s over the window, each with its sample count.
   From one `groupBy=total, bucket=none` read.
2. **History charts** — requests+errors (bars), tokens in/out is not
   per-bucket-available (prompt tokens are request-level; completion sums
   ride on groups) so the chart pair is: latency p50/p90 (lines) and decode
   tok/s p50 (line), plus the request/error bars. From one
   `groupBy=total, bucket=hour` read. Hand-rolled SVG, theme tokens only,
   an accessible table under a disclosure beside each chart.
3. **The comparison table** — existing per-group table, extended with TTFT
   and decode columns, from `groupBy=backend, bucket=none` (the default
   read the page already makes).
4. Client keys and recent requests, unchanged.

Polling via `usePolling` at 15 s (the aggregate band), replacing
refresh-only; the window selector stays; a model filter drives the `model`
param. Null renders "unreported"; sample counts stay visible beside every
throughput number; the 503 "metrics off" screen is untouched.

## §5 Record

Filled in at the end of the build: see the git history of this file's
commit and `docs/acceptance/` for the checks.
