# M8 acceptance — the gateway retains what it serves

**Status:** passed 2026-09-10 (late), on the third attempt, and
**extended and re-run green (17 checks)** the same night for the phase
decomposition and balancer-decision work — see "The local hop, measured"
at the end. Script:
[`scripts/m8-acceptance.sh`](../../scripts/m8-acceptance.sh). Design in
[`m8-retained-request-metrics.md`](../design/m8-retained-request-metrics.md);
follows [M7's two-agent run](m7-two-agent-run.md).

```
agent :8079 --spawns--> control :8083, gateway :8080, library :8082
            --spawns--> ollama-small :8091  -> ollama :11434  (dolphin3 8B Q4)
            --spawns--> ollama-big   :8092  -> ollama :11434  (qwen3-coder 30B MoE)
            --spawns--> dead-backend :8093  -> 127.0.0.1:1    (nothing listens)
gateway     --records--> metrics.sqlite3, beside gateway.yaml in the install dir
```

Ollama rather than llama.cpp, deliberately: it was already running on
this box with two models of very different sizes, and **two real models
behind one gateway is the comparison the milestone exists for**. The
engine-supervision path is M0's and M6's ground and is not re-proved
here.

**Thirteen checks, all green** on the run recorded below; **seventeen**
after the phase-decomposition section was added.

---

## What it proved

### A streaming completion is retained, and now says who served it

The defect the whole design was shaped around. `x_eugene_plexus` was set
in exactly one place, and the streaming path was not it — so streamed
requests carried no routing information at all, and a recorder hooked to
the response would have been silently blind to every streaming client.

```
final frame: {"id":"chatcmpl-f12ea8…","choices":[{…"finish_reason":"stop"}],
              "usage":{…},"x_eugene_plexus":{"driver":"ollama-small",…}}
served streamed=True  attempts=1 total=203ms tok=6
served streamed=False attempts=1 total=984ms tok=100
```

Both shapes in the store, and the stream distinguishable by
`streamed: true`. Recording happens at the routing hooks, which fire on
both paths.

### The two-row shape earns itself

A slot whose tier 1 is a reachable driver fronting a closed port:

```
slot answered: ollama-small tier=2 attempts=2
attempts=2 tier=2 [('dead-backend', 2171ms, failed, 'DriverError'),
                   ('ollama-small', 4189ms, served, -)]
survivor took 4189 ms of a 6360 ms request - 2171 ms was the dead backend
```

**Computed from the request total, the survivor would have scored 34%
lower than it did.** That is the argument for a per-attempt row,
measured rather than asserted. The failed attempt carries
`DriverError` — the exception **class**, never its message, because a
driver error can carry a provider's response body and this string is
retained and rendered.

`tier: 2` is correct here, which matters for the defect below: the tier
is preserved when the earlier target *is* served by a reachable driver.

### Tokens per second, per backend, on this box

| model | backend | tok/s (run 2) | tok/s (run 3) | samples |
|---|---|---|---|---|
| dolphin3-abliterated 8B Q4 | `ollama-small` | 33.5 | 29.6 | 6 |
| qwen3-coder:30b (MoE) | `ollama-big` | 19.7 | 3.3 | 4 |

The question the milestone exists to answer, answered. Read the next
section before drawing a conclusion from the second row.

### The rest

- `rowsDropped: 0` throughout — no back-pressure at this rate.
- **Metrics off answers 503 "disabled"**, not an empty 200. "Switched
  off" and "nothing served" have different fixes.
- **History survives a restart.** 11 rows before and after a real
  `POST /v1/components/gateway/restart`, with a fresh
  `gatewayStartedAt` beside them so a partial window is legible as
  partial. This is the reason the store is SQLite and not a counter: the
  agent respawns every child on operator login.
- The rollup ran and correctly produced **nothing**, because all traffic
  was inside the current, incomplete hour and rolling up a partial
  bucket is how double-counting starts. Verified separately that a
  completed hour does roll up and that re-running maintenance does not
  double-count.

---

## What the run found that the design did not predict

### An external backend's own model load is inside the request we measure

`swappedIn` and `waitedMs` only cover runtimes **this** control plane
supervises. Ollama loads its own model, and that load happens inside a
request the gateway is timing. One first request measured **17.9 s and
5 tok/s** against **116.8 tok/s** on a later sample of the same backend
and the same model.

The 30B moving from 19.7 to 3.3 tok/s between two runs is the same
cause, not noise: Ollama had unloaded it in between and reloaded it
inside a measured request.

Consequences, all now implemented or written down:

- Percentiles rather than means, so one cold outlier does not dominate.
- **The sample count is displayed next to every median** in the UI.
- The script warms both backends before the comparison.
- The UI says outright that these numbers describe this machine and are
  not a benchmark.

A cold start being indistinguishable from a slow backend is a real limit
of measuring at this layer, and no amount of averaging fixes it — only
warming up, or a backend that tells us it is loading.

### Our tokens/sec is a whole-request rate, not a decode rate

Completion tokens over the serving attempt's wall clock, so prompt
processing and backend-side queueing are inside it. A 6-token streamed
reply scores lower than a 100-token one from the same engine. Comparing
two backends is only meaningful at the same prompt and `max_tokens` —
which this script does and a UI cannot enforce.

### Two failed attempts at constructing a live cascade

Worth recording, because both mistakes are easy to repeat.

1. **A tier whose target names a model id nothing serves does not
   cascade.** `RoutingTable.resolve()` drops such a tier, the slot
   collapses to one, and the fallback answers as **tier 1**. See the
   open defect below.
2. **Patching `baseUrl` on an `ollama_local` driver is silently
   ignored.** The named local providers carry a fixed
   `default_base_url`, and the `baseUrl` field is
   `showWhen: provider == openai_compat_custom`. The "dead" driver
   talked to the real Ollama and **served** the request — and the
   metrics correctly recorded a success, which is the only reason the
   mistake was visible.

The construction that works: `openai_compat_custom` with a `baseUrl`
pointing at a closed port. A driver the gateway **can** reach whose
backend refuses. A driver the gateway cannot reach is dropped from the
table and produces no cascade at all.

---

## Open, and not closed by this run

- ~~**`resolve()` drops a tier whose target nothing serves.**~~
  **FIXED** the same night, gateway `c7190f6`, on Troy's call after
  seeing the two cases side by side. Every configured tier is kept now,
  including empty ones, so a fallback reports its real tier; the slot's
  own implicit self-tier is still dropped when nothing serves it,
  because keeping *that* one would push each configured target up a
  number — the same defect in the other direction, and how the first
  attempt at the fix broke five tests.
- **vLLM against llama.cpp is still unmeasured.** No Windows build, WSL
  not installed. M8 makes the heterogeneous comparison possible, not
  available. The WSL2 session now answers three open questions.
- **The balancer does not consume any of this.** By decision — see §4
  of the design.
- **No browser has opened `/metrics`.** The page has component tests
  driving its three restraints, and the data behind it is proved here,
  but the rendering is unobserved.

## Timings worth keeping

| What | Measured |
|---|---|
| A warm 8B Q4 completion, 100 tokens, through the gateway | about 1.0 s |
| The same backend cold, model load included | 17.9 s |
| A cascade: failed attempt plus the survivor | 2,171 ms + 4,189 ms = 6,360 ms |
| Store size after 11 requests | 4 KB plus a 300 KB write-ahead log |
| Whole run | about four minutes |


---

## The local hop, measured (2026-09-10, later still)

The script gained a section for the phase decomposition and the
balancer-decision recording (design §11). **17 checks, 0 failures.**

```
  ollama-small  routing p50 = 0 ms   control-plane overhead p50 = 116 ms  max 131 ms
  ollama-big    routing p50 = 0 ms   control-plane overhead p50 = 120 ms  max 120 ms

  requests with a recorded decision: 1 of 11
    failover-test  least_busy  [(dead-backend, tier1, ok, 0/1), (ollama-small, tier2, ok, 0/1)]
```

**Routing is free.** Nothing needed a refresh, so resolving and picking
came in under a millisecond. That phase was added on suspicion and the
suspicion was wrong — worth knowing, and the cheap half of the work.

**The control plane's own cost is about 116 ms a request** and does not
vary much (114 / 116 / 120), so it is a fixed per-request cost rather
than a load effect. On completions of roughly a second that is better
than a tenth of the request.

`gateway.yaml` has said since M0 that "the extra local hop is
sub-millisecond against a multi-second generation" and is "not a cost
worth optimising away". What was measured is the serving attempt's
gateway-side time minus the **driver's own** `latencyMs`, which contains
the loopback round trip *and* everything the driver does around its
backend call. A loopback round trip really is sub-millisecond, so the
sentence about the hop is probably still true; what is false is the
inference that the two-layer split is therefore free.

Where to look next, in order of likelihood: Pydantic validation of a
full completion body in the driver; `response.elapsed` not covering the
body read, which would misattribute the time rather than locate it in
the driver; and the gateway's own response construction, inside
`elapsedMs` but outside anything the driver reports. **A finding, not a
conclusion** — but a four-milestone-old architectural justification is
now a number, and it is not the number the sentence implies.

The balancer's decision was recorded for exactly one of eleven
requests, which is the design working: ten had a single eligible backend
and nothing to explain. The one that did was the cascade, and it kept
both candidates with the tier each sat in.
