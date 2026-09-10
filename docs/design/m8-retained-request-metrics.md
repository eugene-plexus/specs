# M8 — Retained request metrics (design)

**Status:** designed 2026-09-10 (late), not built. Milestone **M8** of
[`local-inference-control-plane.md`](local-inference-control-plane.md).
Follows [M7](m7-second-host-readiness.md), which is built and
live-verified on one box.

**What it is.** Every completion the gateway serves already reports how
it was served — `x_eugene_plexus` carries driver, runtime, backend,
`latency_ms`, `attempts`, `tier`, `swapped_in`, `waited_ms`, and OpenAI
`usage` carries token counts. **None of it is stored anywhere.** So the
question a control plane whose seventh differentiator is "many backends
at once, load-balanced, with failover" cannot answer about its own
install is:

> Is vLLM faster than llama.cpp for this model on this box?

Nor: has this backend been failing? did the cascade fire last night? is
tier 2 quietly serving everything? what does a wake actually cost? Each
of those is one number that crossed the wire and was discarded.

M8 keeps it. **Recording only** — the balancer is not changed. §4 argues
why that split is the point rather than a hedge.

**Two scope decisions are Troy's** (§4, §5). Each is stated with a
recommendation and the main tradeoff; the build proceeds on the
recommendation, because the storage and the surface are the same either
way. Overturning one changes one module, not the milestone.

---

## 0. What was verified before designing (2026-09-10, late)

Verified against the org with `gh`, not against CLAUDE.md.

| Repo | HEAD | `SPECS_REF` | CLAUDE.md's table |
|---|---|---|---|
| `specs` | `ab69d3c` | — | stale (`a0d793e`) |
| `agent` | `c068ab1` | `a0d793e` | stale (`6589820`) |
| `gateway` | `57ab64c` | `a0d793e` | stale (`2e5544d`) |
| `inference-driver` | `b2bf9c3` | `a0d793e` | stale (`907cd00`) |
| `library` | `52d7c45` | `a0d793e` | stale (`d6ea284`) |
| `control` | `1bd792a` | `a0d793e` | stale (`48cfeb2`) |
| `ui` | `4faa4d7` | `a0d793e` | stale (`3cf98cc`) |

**All six consumers are level at `a0d793e`** and every HEAD has moved
past what CLAUDE.md records — the install rework and the trust-root fix
landed after that table was written. Specs commits since `a0d793e` are
docs, scripts and the acceptance record, so **no re-pin is outstanding**;
the pin is correct and the table is not. Verify HEADs against the org,
never against the table.

**`scripts/m7-acceptance.sh` was re-run and PASSED** — 41 checks, 0
failures, **green on the first attempt** where the original needed
three. That is the outstanding regression proof for the first-boot
topology change; the record is in
[`m7-two-agent-run.md`](../acceptance/m7-two-agent-run.md).

Four facts found by reading the gateway, each of which shapes the design.

**1. The response envelope is the wrong recording point; the routing
hooks are the right one.** `x_eugene_plexus` is set in exactly one place
— `_to_chat_completion` (`routes/inference.py:351`). The streaming path
builds `ChatCompletionChunk` and **never sets it**, so *streamed
requests carry no routing information at all today*. An implementation
that recorded from the envelope would therefore be silently blind to
every streaming client, which is most real clients.

Meanwhile `RoutingHooks.on_attempt_start` / `on_attempt_end` already
fire around **every attempt on both paths**, because they live inside
`TieredClient.generate`, which streaming calls too. The seam exists and
is already load-bearing (it is what feeds `least_busy`). It carries
`driver: str` and `served: bool` and nothing else.

*Consequence:* record at the hooks, not at the envelope. This is the
single most important decision in the document and it is not a
preference — the envelope cannot see half the traffic.

**2. `latency_ms` includes failed attempts, so throughput from it is
wrong exactly when it matters.** `started` is taken in the route *after*
the wake completes, so `latency_ms` correctly excludes `waited_ms` (a
thing I assumed wrongly before reading, and it is worth stating so
nobody re-derives it). But the whole cascade loop runs inside
`client.generate()`, so a request whose primary timed out for 30 s and
whose secondary answered in 800 ms reports `latency_ms: 30800` against
the backend that took 800 ms. Divide the secondary's token count by that
and vLLM looks four times slower than it is.

*Consequence:* time each **attempt**, and attribute an attempt's latency
to the backend that served it. A request-level row cannot be corrected
after the fact.

**3. `usage` is optional, and absent for whole classes of backend.**
`_to_chat_completion` sets usage only `if response.usage is not None`.
So tokens/sec is not always computable, and a schema or a UI that
assumes it will show zeros that read as "this backend is slow" rather
than "this backend does not report".

*Consequence:* token counts are nullable throughout, aggregates report
how many samples they are built from, and "no data" is rendered
differently from "zero".

**4. One recording point, and one gateway per install.** The gateway
serves `/v1/chat/completions` only — there is no `/v1/completions` — so
there is exactly one route to instrument. And the first-boot topology
declares a gateway on the control host while an enrolling node sets
`EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=0`, so an install has one gateway
even when it has N nodes. Gateway-local storage is therefore
install-wide by construction, not per-host.

*Caveat, stated because it is load-bearing:* nothing **enforces** one
gateway. Two would give two partial histories with no merge. §6 lists
this as the risk it is.

### One thing this milestone would have made diagnosable

M7 left an undiagnosed window: a request ~2.5 s after a cross-host idle
unload was routed to the stopped runtime's driver instead of waking it,
twice, and `scripts/m7-acceptance.sh:226` still sleeps 4 s to avoid it
(`EP_WAKE_DELAY=0` reproduces). That is a routing decision that nothing
records. Every fact needed to diagnose it — which backend was picked,
what its `runtime_status` was believed to be, when the table last
refreshed, whether a wake was attempted — is computed and thrown away.

This is not an argument that M8 fixes it. It is an argument about what
the absence of retained routing data costs, made by the one open bug the
project already has.

---

## 1. What an operator wants to know

Five questions, in the order they get asked. Each maps to a query, and
the mapping is what the schema has to serve.

1. **"Which of my backends is faster for this model?"** Group by
   (model, backend, runtime); compare tokens/sec and time-to-first-byte.
   The headline question, and the one differentiator #7 needs.
2. **"Is anything failing?"** Error counts and cascade rate per backend
   over a window. `attempts > 1` is already the visible evidence failover
   fired; unretained, it is visible only to whoever was watching that
   request.
3. **"What is idle unload costing me?"** Count of `swapped_in`, and the
   distribution of `waited_ms`. M6 made the policy; nothing measures it.
4. **"Is a later tier quietly serving everything?"** `tier > 1` rate per
   slot. A cascade that always works hides a broken primary — named as a
   risk in the v0.3 plan, still unmeasured.
5. **"What did last night look like?"** The same numbers, bucketed by
   hour, after a restart. This is the question that decides the storage
   answer in §3, because it is the only one an in-memory counter cannot
   answer at all.

Explicitly **not** in scope: per-token timing, GPU utilisation sampling,
prompt/response content. The first needs the token stream the gateway
does not yet proxy (M0's deliberate limitation, still open); the second
belongs to the agent, which owns device detection; the third is a
privacy decision nobody has asked for and it is not being made
incidentally by a metrics feature.

---

## 2. Where the data is captured

**At the hooks, per attempt, in the gateway.** `RoutingHooks` grows from
two methods to a richer `on_attempt_end`:

```python
class RoutingHooks(Protocol):
    def on_attempt_start(self, driver: str) -> None: ...
    def on_attempt_end(
        self,
        driver: str,
        *,
        served: bool,
        elapsed_ms: int,             # THIS attempt, not the request
        error: str | None = None,    # exception class name, never the message
    ) -> None: ...
```

`TieredClient.generate` already brackets each attempt; it gains a
`time.monotonic()` around the `await` and passes the delta. Per-request
facts the hooks cannot see — the requested model, `waited_ms`,
`swapped_in`, token counts, the served tier — are joined in the route,
which already holds all of them, via one `record()` call after the
response is built.

That split is deliberate: **the hooks are the only place that sees a
failed attempt** (the route sees an exception, not which of four
backends produced it), and **the route is the only place that sees
tokens and wake cost**. Neither alone is sufficient, which is why an
attempt row and a request row are different rows.

Two shapes, then:

- **`request`** — one row per completion the gateway accepted: requested
  model, served model, slot, tier, `attempts`, `swapped_in`,
  `waited_ms`, total wall-clock, prompt/completion tokens (nullable),
  outcome, timestamp.
- **`attempt`** — one row per backend touched: parent request, driver,
  runtime, node, backend kind, `elapsed_ms`, served or the error class.

A request that cascaded across three backends is one `request` row and
three `attempt` rows. Tokens/sec for a backend is then computed from the
*serving attempt's* `elapsed_ms` and the request's completion tokens —
which is fact 2 of §0 made structural rather than remembered.

**Errors are recorded as an exception class name, never a message.**
Driver error messages can carry a provider's response body, and a
metrics table is exactly the kind of thing that gets pasted into an
issue. Cardinality is a secondary reason; the first is that this must
not become an accidental credential store.

### Streaming

Recording works for streams because the hooks do. But the **response**
still tells a streaming client nothing about routing, and that is a real
gap now that the data is being kept — the UI playground streams.

Recommendation, separable from the rest: emit `x_eugene_plexus` on the
**final chunk**, which is where OpenAI puts `usage` under
`stream_options.include_usage`. It is additive, ignored by clients that
do not know it, and it makes the streaming and non-streaming surfaces
agree. Token counts are already available on that path — `_stream_completion`
awaits a full `GenerateResponse` before framing, so `usage` is in hand.

---

## 3. Where the data lives

**SQLite, one file beside the gateway's config, `sqlite3` from the
standard library.**

The gateway's cwd is the install directory (the agent spawns it there,
and `config_file` defaults to a bare `config.yaml`), so
`metrics.sqlite3` lands next to `gateway.yaml` — outside every checkout,
which is the property the install rework established and which
`dev-seed.ps1` depends on.

Why SQLite rather than the two alternatives:

- **In-memory counters only.** Cannot answer question 5, and the
  gateway restarts more than one might think: the agent respawns every
  child on operator login, and M6 restarts drivers on config change. An
  install's performance history would reset every time someone logged
  in. This alone disqualifies it.
- **Append-only JSONL.** Durable and trivial to write, but every
  question in §1 becomes a full-file scan in Python, and retention means
  rewriting the file. SQL does the grouping, and an index on
  `(started_at)` makes a window query cheap.

SQLite specifics that matter and are easy to get wrong:

- **WAL mode**, so a long-running read for the metrics endpoint cannot
  block a write on the request path.
- **Writes off the request path.** A completion must never wait on a
  disk flush or a lock. Rows go onto an `asyncio.Queue`, and a single
  background task drains it in batched transactions. A full queue
  **drops rows and increments a dropped counter that the endpoint
  reports** — metrics degrade before inference does, and they say so
  rather than lying by omission. This is the same shape as
  [[degraded-mode-required]]: the observability layer must not be able
  to take down the thing it observes.
- **`synchronous = NORMAL`.** Losing the last few rows to a power cut is
  an acceptable trade for not fsyncing per completion; these are
  measurements, not the replicated log.
- **No migration framework.** One `schema_version` in a table, and a
  gateway that finds a version it does not know **renames the file aside
  and starts fresh** rather than refusing to boot. Metrics are not worth
  a degraded control plane, and this is the one place where discarding
  data is the right answer.

**This is explicitly not replicated state.** M5 settled that liveness is
never in the log and M6 added nothing to it; per-request measurements
are further from install-wide truth than liveness is. The control root
does not see this file, `LogOp` stays closed at nine, and a standby
promoted after a failover starts with no history — correctly, because
the history described a different process's traffic.

---

## 4. DECISION (Troy's): does the balancer use it in M8?

**Recommendation: no. Record and expose in M8; balance on it in M9, or
never.**

The argument for doing it now is that §1's first question exists to be
acted on, and least-busy is a crude signal — it cannot tell a fast
backend from a slow one, only a busy one from an idle one.

The argument against, which I think wins:

1. **A latency-weighted balancer has a known failure mode and needs
   data to be designed against.** Weight by observed throughput and the
   fastest backend attracts every request until it saturates, at which
   point its throughput collapses and traffic stampedes to the next one
   — oscillation, not balance. The fixes (decay, a floor of exploratory
   traffic, hysteresis) all have constants in them, and **there is no
   data on this box to choose those constants from.** M8 produces
   exactly that data.
2. **A cold backend never earns a request.** Any weighting scheme needs
   a deliberate exploration policy or a newly-started replica — the
   thing M6's wake-on-demand produces — starves. That is a design
   question, not a tuning question.
3. **The routing path is the load-bearing one.** M6's live run found two
   routing defects that fixtures could not, and M7 left a routing window
   still open and undiagnosed. Adding a new input to the picker while a
   routing bug is open makes the open bug harder to see.
4. **Recording alone is independently valuable.** Questions 2 through 5
   in §1 are answered by visibility, with no balancer change at all.

The tradeoff of deciding this way: differentiator #7 stays at
"load-balanced" rather than "intelligently load-balanced" for another
milestone, and the headline question gets *answered* rather than *acted
on*. If Troy wants the balancer in M8, the storage and surface here are
unchanged — it becomes an additional `loadBalancing` enum value reading
the same rollups, and the exploration policy needs designing first.

---

## 5. DECISION (Troy's): retention

**Recommendation: raw rows for 7 days, hourly rollups kept
indefinitely, both configurable.**

An hourly rollup per (model, driver, runtime, backend, outcome) is a few
hundred rows a day at most and answers every question in §1 at hour
granularity forever. Raw rows answer questions nobody predicted — "what
happened at 02:14" — and are what a real diagnosis needs, but they grow
with traffic.

Sizing, so the default is a number rather than a feeling: a request row
plus its attempt rows is roughly 200 bytes. A heavy personal install at
one completion per second all day is ~17 MB/day, so 7 days is ~120 MB.
That is a lot for a config directory and nothing for a machine with
models on it. A realistic install is orders of magnitude below that.

The alternatives and why they lose: **raw-only** is simplest and
unbounded, which is fine until it is not, and the failure lands on a
user's disk. **Rollup-only** is fixed-size and cannot answer question 5
at the granularity that makes it useful, and once a raw row is gone no
future question can reach it.

Pruning runs on the same background task that writes, once an hour, and
is a `DELETE` plus an `INSERT ... SELECT` into the rollup table. Not a
separate scheduler: a second timer is a second thing to fail silently.

---

## 6. Risks

- **Two gateways, two partial histories.** Nothing enforces one gateway
  per install (§0 fact 4), and a second one would keep its own file with
  no merge and no indication that it is partial. Mitigation for M8:
  the metrics response names the gateway instance and its start time, so
  a partial history is legible as partial. A real answer belongs with
  whatever eventually enforces the topology invariant.
- **The recording path is on the request path even when the write is
  not.** Building a row per attempt allocates on every completion. It is
  small, but "small" is how the routing table came to be a refresh
  interval behind. `metricsEnabled: false` must skip construction, not
  just the write.
- **Clock skew and monotonic time.** `elapsed_ms` comes from
  `time.monotonic()` and is sound. `started_at` is wall-clock and is
  what windows and rollups group by, so a clock step mid-window skews a
  bucket. Acceptable and worth writing down; M5 already lists clock skew
  as untested on real hardware.
- **A metrics endpoint is an information disclosure surface.** Model
  names and traffic volumes are not nothing on a shared tailnet. It sits
  behind the same operator auth as `/v1/admin/routing`, and reads accept
  operator only — not `service:*`, since no component needs it.
- **Measuring makes it tempting to compare across installs.** These
  numbers are only meaningful about this box. The UI must not present
  them as a benchmark, per the line M3 locked: **we state what fits,
  never what is better.** The same restraint applies to speed — report
  what happened here, do not rank hardware.

---

## 7. Contract

New on `gateway.yaml`. No `common.yaml` change, so **only `gateway` and
`ui` need a re-pin** — the M3 shape rather than the M2 shape.

```
GET /v1/metrics
  query: window (ISO 8601 duration or `since`), model?, driver?, runtime?,
         backend?, bucket=(none|hour)
  -> MetricsSummary {
       gateway_instance, gateway_started_at,   # partial-history legibility
       window_start, window_end,
       rows_dropped,                           # honest about back-pressure
       groups: [ MetricsGroup {
         model, driver, runtime, node, backend,
         requests, errors, cascaded, swapped_in,
         latency_ms: { p50, p90, p99, max },
         tokens_per_second: { p50, p90, samples } | null,   # null = not reported
         waited_ms: { p50, max } | null,
         tier_counts: { "1": n, "2": n }
       } ]
     }

GET /v1/metrics/requests
  query: limit, cursor, model?, driver?, outcome?
  -> RequestPage { requests: [ RequestRecord { ..., attempts: [AttemptRecord] } ],
                   next_cursor? }
```

`tokens_per_second: null` where no backend in the group reported usage,
distinct from a present object with `samples: 0`. §0 fact 3 is a schema
obligation, not a UI convention.

Config trio gains, per [[feedback-remote-config]] and
[[gui-equality-for-configurable-things]]:

| Key | Default | Notes |
|---|---|---|
| `metricsEnabled` | `true` | False skips row construction entirely |
| `metricsRetentionDays` | `7` | Raw rows; 0 keeps rollups only |
| `metricsRollupEnabled` | `true` | Hourly rollups, kept indefinitely |

And, separable (§2): `x_eugene_plexus` added to `ChatCompletionChunk` so
a streaming client can see routing at all.

---

## 8. Scope

**In.** The hook change and per-attempt timing; the SQLite writer with
queued off-path writes and back-pressure reporting; retention and hourly
rollups; the two endpoints; the config trio; `x_eugene_plexus` on the
final stream chunk; a UI panel answering §1's five questions.

**Out.** Balancer changes (§4). Per-token / time-to-first-token timing —
needs the token stream the gateway still does not proxy. GPU sampling —
the agent owns devices. Prometheus / OpenTelemetry export: worth
wanting, and a second consumer of the same tables, so it is a later
addition rather than a design constraint. Cross-install comparison,
deliberately (§6).

---

## 9. Verification

Fixtures cannot settle this milestone, and the record is unambiguous
about why: **every real defect in M6 and M7 came from a live run.** The
specific things a fixture would get wrong here are known in advance:
that the streaming path records at all (§0 fact 1 exists because reading
found the envelope blind), and that a cascade attributes latency to the
right backend (§0 fact 2).

`scripts/m8-acceptance.sh`, run on this box, must show:

1. A non-streaming and a **streaming** completion both producing rows —
   the streaming one is the check that would have failed under an
   envelope-based implementation.
2. Two llama.cpp replicas of one model served alternately, with
   per-replica rows distinguishable by `runtime`, and tokens/sec within
   a sane band of each other. Same setup M6 used, so it is known to work.
3. A killed replica producing an `attempt` row with an error class and a
   `request` row with `attempts: 2` — **and the surviving backend's
   tokens/sec unaffected by the dead one's timeout.** This is the §0
   fact 2 regression test and the one number worth printing.
4. An idle unload and wake producing `swapped_in: true` with a
   `waited_ms` matching what M6's run measured (~2.5 s).
5. A cloud driver answering from tier 2 with `tier: 2` retained.
6. Rows surviving a gateway restart, then an hourly rollup produced by
   hand-advancing the prune, then raw rows pruned with the rollup intact.
7. `metricsEnabled: false` producing no rows and no file growth.

The number this milestone exists to produce, printed at the end: **the
tokens/sec of each backend for one model on this box.** If the run
cannot print that line, the milestone has not landed.

**vLLM remains unverifiable here** — no Windows build, WSL not
installed — so the headline llama.cpp-vs-vLLM comparison still needs
the second host that M4 and M5 have both been waiting on. M8 makes the
comparison *possible*; it does not make it *available*. That is the
honest state, and it is one more argument for the WSL2 session, which
now answers three open questions instead of two.

---

## 10. Implementation notes

*(To be written as it is built, following the pattern of M6 §11 and
M7 §11: what the live run found, and where the implementation departs
from this document.)*
