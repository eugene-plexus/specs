# Gateway operations dashboard

Built 2026-10-15. Troy requested a Gateway Metrics page comparable in clarity
and coverage to an AWS dashboard, then specifically asked for varied dial
styles where the data supports them.

The gateway already exposes the measurements needed for this slice. No wire
contract, gateway code, database migration, or model configuration changed.
The console combines retained metrics with `/v1/admin/routing`.

## Reading order

1. Request count, failures, failovers, median latency, first token and decode
   speed, followed by a success-rate donut and explicit outcome counts.
2. Six hourly history panels: traffic, failures, latency p50/p90, decode,
   first token, and failovers/cold starts. First-token and decode panels depend
   on reported observations. Tables expose chart data without hover.
3. Current routing capacity: unique routable backends, outstanding requests,
   eligible routing slots, discovery age, control-root and unreachable-driver
   warnings. Each backend has a semicircular needle gauge, status and counts.
4. Latency p90/p99, routing/overhead/wake distributions, a segmented prompt-cache
   ring, conversation continuity, evictions, and serving-tier distribution.
5. Detailed backend comparison behind a disclosure; client-key usage; request
   investigation with server-side outcome filtering and existing attempt traces.

The page refreshes every 15 seconds while visible and can export its snapshot
as JSON, including timestamps, filters, scope descriptions and partial-read errors.
Navigation anchors make each section reachable on a long dashboard.

## Measurement boundaries

- Historical totals and percentiles come from `groupBy=total`. Per-backend
  medians are never averaged. Null remains unreported, including old gateways'
  absent p99 and capacity counters. Measured zero remains zero.
- Routing counters are keyed by `(node, driver)`, matching the gateway's
  counter identity. Model aliases and fallback tiers do not multiply capacity;
  identical driver names on different nodes remain separate.
- Capacity is a current, all-model snapshot. Slots include the gateway's
  default when an engine has not advertised its capacity. They are routing
  slots, not GPU utilization or guaranteed throughput. A needle caps at its
  scale while its numeric percentage still reports overload above 100%.
- Cache reuse divides cached tokens by prompt tokens from reporting requests,
  not by all requests. Unknown or empty denominators produce an empty dial.
- Client-key usage is all models in the selected window. Recent requests are
  the latest 25 retained matching the model and outcome, independent of the
  historical window; the page and export say so.
- Partial edge hours, expired history, dropped measurements and stale reads
  are identified. A failed refresh keeps the last snapshot with a warning and
  disables export. An old response cannot replace a newer filter selection.
- Side-read failures remain local to their panels. Disabled recording is
  distinct from an empty window. The UI does not turn a failed read into a
  green health indication.

Dials have real denominators: success out of recorded requests, occupied slots
out of routing capacity, cached tokens out of reported prompt tokens. Latency
and token speed keep numeric values and history rather than invented gauge
limits. Patterns, labels, needle position, and dashed comparison lines supplement
color. Theme tokens supply all colors; narrow layouts stack the panels.

Historical CPU/GPU/RAM telemetry, alert rules/notifications, SLO evaluation and
longer/finer-grained retention are separate capabilities, not simulated by this
page. This slice retains the existing hourly gateway history resolution.

See [acceptance evidence](../acceptance/gateway-dashboard-run.md).
