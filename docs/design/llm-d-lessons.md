# Lessons from llm-d

**Status: read 2026-10-21, the day after llm-d 1.0 (2026-10-20). LD-C1
taken 2026-10-21: all of LD1-LD7 go on the roadmap, placed by the master
roadmap. LD-C2 taken the same day: queue. LD-C3 to LD-C6 are still Troy's.** Troy's brief: *examine llm-d,
say where Eugene is stronger and where llm-d is stronger, and name the
features or tuning Eugene should adopt.*

What was read:
- Google Cloud's announcement, "llm-d 1.0: an open-source stack for
  distributed inference" (2026-10-20).
- llm-d.ai v1.0 docs: architecture overview; router scheduling, flow control,
  request handling, data layer and latency predictor; prefix-cache-aware
  routing; KV offloading.
- llm-d.ai blog: v1.0 "ready for Day 2", v0.8 "From Platform to Control
  Plane", "Sticky Until Saturated: Token-Aware Routing", "Serving GLM-5.2 for
  Agentic Workloads", and the tracing post.
- llama.cpp `tools/server/README.md` on master (2026-10-21), for flag names
  and defaults.

Not read: llm-d's source code. The docs leave some 1.0 features undescribed
(how a session or an agent turn is identified, default scorer weights, the
stateful Responses guide). Where this document relies on a launch post rather
than docs, it says so. Every llm-d number below is llm-d's or a partner's
reported result, not an independent benchmark.

## What llm-d is

- **A Kubernetes-native router and scheduler in front of vLLM, SGLang and
  TensorRT-LLM.** It wraps engines and does not fork them. Since v0.8 it
  calls itself "an inference control plane, not a fork of any engine
  underneath it". That is our own wording.
- **Not Google's project, and not Google-only.** Red Hat started it in
  2025-05 with Google Cloud, IBM Research, CoreWeave and NVIDIA. It became a
  CNCF Sandbox project in 2026-03 and reports 500+ contributors from 25+
  organizations. Its nightly CI (as of v0.7) runs on OpenShift, GKE and
  CoreWeave, and it is validated on NVIDIA, AMD MI300X/MI355X, Intel and
  TPU. Google's post leads
  with TPUs and GKE Inference Gateway, the managed version of the router.
- **Sized for data centres.** The headline results come from 544 H100s,
  3,000 concurrent coding agents, 17,000-node multi-region GKE, and
  64-GPU prefill/decode splits.
- **The parts:**
  - **Router.** An Envoy proxy speaking the Gateway API Inference Extension
    calls the **Endpoint Picker (EPP)** over `ext-proc` on every request.
    The EPP runs flow control, then a Filter → Score → Pick pipeline over
    the replicas in an `InferencePool`.
  - **KV cache layer.** A prefix index, either estimated in the router or
    exact from vLLM's KV events. Offload to CPU RAM, then SSD or a shared
    filesystem, and peer-to-peer pulls over RDMA.
  - **Disaggregation.** Separate prefill, decode and multimodal-encode
    pools, wide expert parallelism, and `DisaggregatedSet` to roll them
    together.
  - **Batch.** An OpenAI Batch API (`/v1/batches`, `/v1/files`) and an
    async processor that feeds queued work into spare capacity.
  - **Ops.** KEDA/HPA autoscaling on queue depth and predicted latency,
    Kueue quotas, Prometheus metrics, OpenTelemetry traces, and the Prism
    benchmark dashboard.
- **New in 1.0 (from the launch post):** v1 config API, a hot-standby
  router, prefill/decode-aware rolling updates, session-aware routing
  ("sticky until saturated"), turn-priority scheduling, and stored state for
  the Responses API (`previous_response_id`).
- **Outside Kubernetes:** a `FileDiscovery` plugin reads endpoint addresses
  from a watched file, aimed at Slurm and bare-metal research clusters. No
  llama.cpp, MLX, Ollama, Windows, macOS or single-machine path is mentioned
  anywhere.

**Verdict: the niche holds, but it is not "Google versus everyone else".**
llm-d is a scheduler for fleets of identical data-centre accelerators run by
a platform team on Kubernetes. Eugene is for machines people own: mixed
consumer cards, Windows, macOS and Unraid, GGUF, a model library, sign-in, a
UI and cloud subscriptions. The two meet only at the router, and there
llm-d has spent a year on problems Eugene has met at small scale. Most of
what follows is router work.

An llm-d endpoint is an OpenAI-compatible server, so an install can already
add one as a backend through the driver's custom `baseUrl`. A business with a
cluster gets one endpoint for that cluster and its desktops without any new
code.

## Where Eugene is ahead

| Area | Eugene | llm-d |
| --- | --- | --- |
| Engines and hardware | llama.cpp on every backend it builds for, plus vLLM, MLX and Strata; any GPU a person owns, and CPU | vLLM, SGLang, TRT-LLM on data-centre NVIDIA, AMD, Intel and TPU |
| Platforms | Windows, macOS, Linux, Unraid; one installer | Linux on Kubernetes, with Gateway API CRDs, Helm or Kustomize, LWS and DRA |
| Installing engines | The agent installs, updates and supervises them | Container images; the operator's job |
| Models | Library, fit before download, downloads into the person's folders, profiles | None; the model is an image or PVC concern |
| Front door | OpenAI, Anthropic, Responses and Gemini doors; tool-call repair; server-run tools | OpenAI shapes only |
| Cloud subscriptions | Routing and failover across local runtimes and provider accounts | None; GKE's managed gateway fails over between regions, not providers |
| Identity | Sign-in (OIDC), people, client keys with limits, per-node keys, TLS between machines | None. Tenant and priority come from headers, and the docs warn that client-set headers are "an abuse vector" an upstream gateway must strip |
| Failover safety | Retries only safe failures; never after emitted text; capacity refusals do not trip the circuit | No in-flight failover (listed as future work). With the EPP down, the llm-d recipe's `FailOpen` sends traffic straight to engines with no queueing or gating |
| Mixed hardware | Per-runtime slots, pool and fit; replicas of one model on unlike machines are normal | The latency predictor assumes "the pool must be homogeneous", and the default saturation detector averages unlike endpoints without weighting |
| Settings | Every component remote-configurable, with UI metadata | YAML and CRDs |
| UI | Console and Workbench | Prism (benchmarks) and Grafana |

Eugene also reached llm-d's routing answer independently and measured it on
real agent sessions. PC4 and CB1-CB5 (`cache-aware-balancing.md`) give
conversation affinity with a spill when saturated, placement by load, and a
token budget that holds turns in the gateway rather than overflowing an
engine's pool. That is "sticky until saturated" plus "hold requests in the
router under saturation", built 2026-10-02. Eugene also measured prefix-hash
placement and found it no better than `spread` for its workload. llm-d's
large prefix-hit gains come from many users sharing long system prompts on
one platform, which is not a homelab's traffic.

## Where llm-d is ahead

- **Scheduling under contention.** Priority bands, per-tenant fairness,
  queue TTLs, sheddable traffic, in-flight eviction and named drop reasons.
  Eugene refuses or makes requests race.
- **Cost-based placement.** Stickiness breaks when the warm replica's
  predicted wait exceeds a cold replica's by a set penalty. Eugene decides by
  free slots.
- **KV tiers.** CPU offload is on by default in their guides, with disk and
  peer tiers. Eugene leaves llama-server's RAM cache at the upstream 8 GiB
  default and launches vLLM with none.
- **Stateful APIs.** Stored Responses state and a Batch API. Eugene's
  Responses door refuses `previous_response_id`, and there is no batch.
- **Observability.** Prometheus metrics and end-to-end OpenTelemetry traces
  with the routing decision on the span. Eugene keeps richer per-request
  records in SQLite but exports neither.
- **Benchmarks.** Standard recipes, a shared workload tool (inference-perf)
  and a public results dashboard. Eugene has no concurrency sweep yet (DI3).
- **Operations at scale.** Router hot standby, drain-aware 503s, coordinated
  rolling updates, autoscaling, P/D disaggregation, wide-EP and RDMA KV
  transfer. Most of this does not apply to Eugene's audience; see "Not
  taking".
- **People.** 500+ contributors against one person and agents. Eugene
  should take their measurements as free research and not race them on
  data-centre features.

## What to take

Ordered by what each does for Eugene's users. LD2, LD3 and LD5 fold into
slices already designed (PC7, DI5, DI3). LD6 and LD7 belong to the Platform
half, which was always on the roadmap and comes after the Inference half.

### LD1. Queue fairly by person and priority

**What llm-d does:**
- Each request gets a flow key: a fairness ID (the tenant) and a priority.
  Each flow has its own queue in the router.
- Dispatch serves the highest priority band that has work, round-robin
  across tenants within that band, and first-come-first-served within a
  tenant.
- When the pool is saturated, requests wait in the router, not in the
  engines. Their "healthy buffer" rule: keep just enough queued at each
  engine that batching never starves, and keep the rest in the router.
- Each band has its own request and byte limits, so a flood in a low band
  cannot fill the space a higher band needs. Queued requests expire after a
  TTL (60 s in their example).
- Negative priority is sheddable: refused first, and optionally cancelled
  in flight to free room for a blocked higher band.
- Every refusal names its reason in `x-llm-d-request-dropped-reason`:
  `rejected-saturated`, `rejected-ttl-expired`, `evicted`,
  `rejected-no-endpoints`, `rejected-shutting-down`. Saturation and TTL are
  429s; no endpoints and draining are 503s.
- Metrics: queue size, queue time by outcome, pool saturation, requests by
  outcome and priority, and a Jain's fairness index per program.
- Mistral uses it to give each commercial tier its own priority band. Users
  turn it on; the defaults behave as first-come-first-served.

**What Eugene has:**
- A client key's `maxConcurrentRequests` (default 2) and `requestsPerMinute`
  (default 60). Over either limit is an immediate 429 with `Retry-After`
  (`gateway/.../admission.py`, `control/.../client_admission.py`).
- CB3's budget wait (`gateway/.../budget.py`, `admit`). Every waiter wakes on
  any change, and the first to re-check wins. There is no order and no
  fairness. When the wait runs out, the request goes to the engine anyway,
  and llama-server's own queue is first-in-first-out and knows nothing about
  people.
- No priority anywhere. `service_tier` is only passed through to OpenAI.

**Why it matters here:**
- **Agent traffic arrives in bursts.** In llm-d's trace of 219 Claude Code
  sessions (78,099 requests), 52% of requests arrived in groups: median 7,
  p90 51. A Claude Code key at the default limit of 2 sees most of a
  sub-agent burst refused and retried with backoff. This is expected from
  the code, not measured on Eugene; the slice measures it first.
- **A shared machine is the business case.** A small office or an MSP
  client with one or two cards has one person's agent loop able to take
  every slot while a colleague's chat waits behind it.
- **Eugene has its own background work.** Workbench's memory learning and
  tidy pass compete with chat on equal terms today.
- **Eugene can do this properly where llm-d cannot.** The fairness ID is the
  signed-in person, or the key when no person owns it. The priority comes
  from the key or app, set by the operator, never from a header a client
  can forge.

**The slice:**
- **One ordered queue per runtime in the gateway,** replacing the wake-all
  wait: band, then round-robin across people, then arrival. It dispatches
  when the runtime has a free slot and room in its pool (CB3's ledger).
- **Three bands:** interactive (the default), background, and sheddable.
  A key or app carries its band. A request may lower its own band, never
  raise it.
- **Over a key's concurrency limit, wait instead of refusing,** up to a
  bound and a TTL, then 429 as today (LD-C2). The limit still caps how much
  of the machine the key holds at once; the burst runs two at a time
  instead of failing.
- **Refusals name their cause** in the door's own words, with the reason
  recorded: queue full, waited too long, no runtime, shutting down. That is
  the "failures name their observed cause" rule, and llm-d's list is a good
  checklist.
- **Record queue time.** `budget.py` already computes `waited_ms` and never
  persists it. Add it to the request row and the Metrics page, with queue
  depth per runtime.
- **Not in the first cut:** cancelling a running background request for an
  interactive one. llm-d notes that capacity returns only after the engine
  aborts and frees its KV, which needs checking per engine.

**Risk:** medium. It is the gateway's request path, and band assignment
touches keys and apps, so it gets one adversarial review. Accept with the
cache-balancing harness: hit rates within noise of today's, no turn starved
past the TTL, and one person's 51-request burst leaving another person's
TTFT p50 within a stated bound.

### LD2. Size the RAM prompt cache from the machine, and turn on vLLM's

**What llm-d does:**
- CPU RAM is the first offload tier, and their guide says it "should always
  be enabled" when the machine has more RAM than VRAM.
- Agentic results from the GLM-5.2 study: with CPU offload, output +13%,
  median TTFT −32%, and median turn time −27% at concurrency 32. On paused
  conversations (400 at once), median TTFT fell from 124.5 s to 22.2 s. A
  restore took ~59 ms against rereading ~45,000 tokens.
- Gaps between turns: median 2 s, p90 24 s, p99 11.4 minutes. Cache state
  has to outlive a person reading an answer or a tool running.
- vLLM's flags as llm-d uses them: `--kv-offloading-backend native` and
  `--kv-offloading-size <GB>`.

**What Eugene has:**
- llama-server's `--cache-ram` is never set by the agent, so it is the
  upstream default of 8,192 MiB. CB measured that as ~10 conversations of a
  1B model and ~2-3 of an 8B. Machines in Eugene's audience often have 64-256
  GB of RAM.
- PC7 already plans `--cache-ram`, `--cache-reuse` and `--ctx-checkpoints`
  as profile settings, with admission counting the cache.
- vLLM is launched with no KV offload.

**The slice:** build PC7 with a computed default.
- **llama.cpp:** a share of the RAM left after weights and experts held in
  RAM, with a cap. It is shown on the profile ("prompt cache: 24 GiB, about
  9 conversations of this model"), and admission counts it.
- **vLLM:** offload on by default with the same arithmetic. Check the flag
  names against the pinned vLLM before building.
- **One known risk to measure first:** CB's remaining failures were
  llama-server pausing its main loop 6-10 s while updating the RAM cache at
  an LRU slot pick. A larger cache could make that pause longer. The slice
  measures the pause at 8 GiB and at the computed size before choosing the
  default (LD-C5).

DI2 (keep the cache on disk across restarts) is the next tier down. The
inter-turn gaps above are more evidence for it. llm-d's note that a
filesystem tier "does not evict data" is already handled by DI2's cap and
LRU.

**Risk:** low. Admission must count the RAM, or a big cache starves the
experts-in-RAM case that A3 was built for.

### LD3. Decide between waiting and moving by predicted time to first token

**What llm-d does ("sticky until saturated"):**
- It keeps a request on replicas holding at least 80% of its prompt. Among
  those, it scores load as uncached prompt tokens in flight when
  prefill-bound, or active streams when decode-bound.
- Stickiness breaks only when the best warm replica's estimated TTFT exceeds
  the best cold replica's by more than `maxTTFTPenaltyMs`.
- The estimate needs no model: in-flight uncached tokens ÷ the replica's
  peak prefill rate, calibrated once as `max-num-batched-tokens` ÷ the time
  to prefill one full chunk.
- Reported: 2.9× input throughput at the knee on a prefill-bound
  code-generation workload against a plain Kubernetes Service. These are
  single runs, and they warn that the values do not carry across models,
  hardware or engines without re-measuring.
- Their fuller option is an online XGBoost predictor for TTFT and time per
  output token. Its features: KV use, input length, queue depth, running
  requests, prefix match and tokens in flight. It reports ~5% error, but
  only on identical replicas.

**What Eugene has:**
- A conversation moves only when its replica's slots are full and another
  replica has a free slot (`routing.py`).
- Under CB3, a held conversation waits for room on its own replica up to
  `swapWaitSeconds` (default 120 s), then goes in the usual order.
- Neither rule weighs the wait against rereading the prompt elsewhere. A
  195,000-token agent turn (llm-d's median for Claude Code) should wait a
  long time for its warm replica. A 2,000-token chat turn should move almost
  at once.

**The slice:** fold this into DI5, which already plans a per-runtime fit
`ttft ≈ a + b·uncached + c·uncached·cached` from retained metrics.
- **Start with llm-d's calibration.** Each runtime's peak prefill rate can
  come from retained metrics (uncached prompt tokens ÷ TTFT on requests that
  did not wait), or from a prompt-processing run added to the profile
  benchmark, which today measures decode at depth (`--n-prompt 0`). Neither
  needs a predictor.
- **The rule:** wait on the warm replica while its predicted TTFT is no
  more than a penalty above the best cold replica's prediction, including
  the reread. Then move.
- **Per runtime, never pooled,** because Eugene's replicas of one model run
  on unlike machines.
- **If an online fit is added later,** keep llm-d's training detail: bucket
  samples by KV use and cache-hit rate, so rare regimes are not forgotten.

**Measure first** with the cache-balancing harness, and adopt only what
beats CB3's current rule, as CB did. Low risk.

### LD4. Export Prometheus metrics and OpenTelemetry traces, named the way llm-d names them

**What llm-d does:**
- Prometheus metrics for everything the router decides.
- Traces from the proxy through the router to the engine, using W3C
  `traceparent`, OTLP and the GenAI semantic conventions:
  `gen_ai.latency.time_to_first_token`, `gen_ai.latency.time_in_queue`,
  `gen_ai.usage.prompt_tokens`.
- Router spans carry the decision: each scorer's value, the prefix-cache
  hit, and the prefill/decode choice.
- Telemetry is metadata only, never prompts or completions. Sampling is
  decided once at the entry, and they suggest ~0.1 in production.

**What Eugene has:**
- Per-request rows in SQLite (schema v13), with more of the decision than
  llm-d's metrics carry: candidates with in-flight and slot counts, strategy,
  affinity outcome, tier and wake wait.
- No Prometheus or OTLP export. It was deferred in M8 and is listed in the
  audience roadmap. The setups review counted it among its top gaps.

**The slice:**
- **`GET /metrics` on the gateway's existing port,** not a new one. Use GenAI
  names where they exist, and `eugene_*` for routing, affinity, budget and
  queue (LD1).
- **Engine metrics per runtime.** The agent already reads llama-server's
  `/metrics`. It can relabel `requests_deferred` (the engine's own queue) and
  the speculative-decoding counters with node and runtime.
- **An optional OTLP exporter,** configured from the console (GUI equality),
  with spans for door → routing → driver → engine. Prompts are never
  exported, which keeps "the owner may not read people's chats".

**Risk:** low, but metrics carry person and key labels, so access to
`/metrics` needs the same rule as the Metrics page.

### LD5. Give DI3's sweep agent-shaped load and a knee

**What llm-d does:**
- llm-d-benchmark recipes run on `inference-perf` (kubernetes-sigs, a
  Python tool for any OpenAI-compatible endpoint), and results are published
  to Prism.
- Workloads are split by bottleneck: code generation (prefill-bound),
  reasoning (decode-bound) and multi-turn agent sessions with pauses.
- Results are reported at the knee, the concurrency where latency turns up.
- The GLM-5.2 study published the shape of real Claude Code traffic:
  - Median request: 195K tokens in, 317 tokens out.
  - Each turn adds a median of 632 tokens. 96% of turns reuse at least 90%
    of their input as a verbatim prefix.
  - Sessions run a median of 107 turns (p90 354), about an hour.
  - Gaps between turns are 2 s median, 24 s p90 and 11.4 min p99.
  - Sub-agent bursts are median 7 and p90 51.

**What Eugene has:** DI3 is designed and unbuilt. The cache-balancing harness
replays real Claude Code and Codex sessions of 8 tool turns each.

**The slice:** extend DI3.
- **Session length and pauses.** Replays of 8 turns understate how cache
  pressure builds over an hour-long session. Add long sessions and pauses
  drawn from the published distribution.
- **Bursts.** Add sub-agent bursts at the published sizes. LD1 is measured
  against these.
- **The knee.** Report it, and state it as people at a speed, as DI3 already
  says.
- **Optionally, inference-perf for plain chat.** Using it to drive the plain
  chat part would make Eugene's numbers comparable with published ones.
  Agent replays stay Eugene's own.

Low risk.

### What building LD5 found (row 10, phase 2, 2026-10-22)

- The published pause quantiles use inverse-CDF interpolation in log time;
  seeded distribution checks cover pauses, burst sizes and prompt reuse.
- The 5% burst frequency is an assumption, not a study result. The 5090 run
  beside captured Claude Code/Codex replay must calibrate it and compare knees.
- Both knee thresholds are editable in the console. Troy's absolute one-second
  first-token ceiling overrides the original doubled-baseline proposal.
- Drafting configuration and observed acceptance are retained for comparing
  records. llama-server exposes speculative parameters, but Eugene's gateway
  request schema has no per-request drafting override; automatic off stays row 13.
- Agent and UI unit checks cover records and sentences. Process acceptance is
  assigned to CI; no live hardware measurement is claimed by this build.

### LD6. Store responses, and use the chain as the conversation key

**What llm-d does:** 1.0 keeps Responses state so a client sends
`previous_response_id` instead of the history. The launch post says this
avoids resending and recomputing history. Where the state lives and how long
is not documented.

**What Eugene has:**
- The Responses door refuses `previous_response_id` and `conversation` with
  a 400 and ignores `store: true`.
- Affinity is keyed by `prompt_cache_key`, Claude Code's session id, or a
  hash of the model, the first system message and the first user message.
  Two chats that open the same way share a hash.

**The slice (Platform half):**
- **A response store in the gateway.** Clients that chain by id stop
  getting a 400.
- **The chain is an exact conversation key.** Affinity uses it before any
  hash.
- **The store holds people's chats.** It needs the same privacy review as
  DI2's disk cache (TTL, per-person ownership, "the owner may not read
  people's chats").

Medium risk, because of the stored data.

### LD7. Run batch jobs in the machine's idle time

**What llm-d does:**
- A Batch API (`/v1/batches`, `/v1/files`).
- An async processor that pulls work from a queue and dispatches it through
  the same flow control as live traffic, in strict lower-priority lanes, so
  "background jobs run in slack capacity without starving interactive
  users".
- RL time-slicing interleaves inference into idle accelerator time, raising
  duty cycles from ~40% to >70%.

**What Eugene has:** no batch API.

**The slice (Platform half, after LD1):**
- **Batch as background-band traffic.** It is not a separate path, so it
  never competes with chat.
- **The home case:** "summarise these 5,000 documents tonight" on a card
  that sits idle overnight. The job shows its estimated time and tokens
  before it starts, because electricity is a real cost for this audience.

Low risk once LD1 exists.

## Smaller things to check

Each of these is a check, not a finding.
- **The gateway restarts without draining.** `routes/admin.py` exits 500 ms
  after a restart request, which cuts streams in flight. llm-d answers new
  requests with a retryable 503 (`rejected-shutting-down`) while it drains.
  Check whether a bounded drain is worth adding to the restart.
- **A hint from waiting, not autoscaling.** llm-d autoscales on router queue
  depth because GPU utilisation hides demand. Eugene cannot add machines, but
  with LD1's queue time recorded the Metrics page can say "people waited on
  this model 18% of the time; a second replica fits on <node>". That fits
  the admin-dashboard direction.
- **LoRA adapters.** llm-d routes to replicas that already hold a requested
  adapter. llama-server loads adapters without applying them
  (`--lora-init-without-apply`) and switches them per request through
  `/lora-adapters`. Eugene passes `--lora` only through `extraArgs`, and the
  Library calls an adapter folder "not a model". Revisit when the Library
  learns adapters.
- **Cold-start spreading.** llm-d's `no-hit-lru-scorer` sends prompts with
  no cache hit anywhere to the replica that least recently took one, so new
  conversations seed different replicas. Check that `spread`'s rotation
  tie-break already does this when conversation counts are equal.
- **The words "inference control plane".** llm-d now uses Eugene's
  description of itself. See LD-C6.

## Not taking, with the reason

- **Kubernetes, Gateway API, Envoy `ext-proc`, LeaderWorkerSet, KEDA,
  Kueue.** Eugene's audience runs Windows, macOS and Unraid without a
  cluster, and every one of these assumes one.
- **Prefill/decode disaggregation, wide expert parallelism and
  `DisaggregatedSet`.** The reasons in `deepinfer-lessons.md` stand:
  - llama.cpp cannot split the stages.
  - The gains need many GPUs. In llm-d's own GLM sweep on 24-64 H200s, a
    third prefill instance added only 3%.
  - The best case in Eugene's audience is vLLM on one multi-GPU business
    box. Reconsider it there, and only there.
- **A precise prefix index from engine KV events.** vLLM emits KV events
  over ZeroMQ and llama.cpp does not, and CB measured prefix placement no
  better than `spread` for Eugene's traffic. Reconsider if vLLM replicas
  serving many people with one long shared system prompt become common. That
  is the case behind llm-d's 35% → 70% hit-rate result.
- **Peer-to-peer KV pulls and shared KV stores.** The LAN arithmetic in
  `deepinfer-lessons.md` stands: an 8B's 30,000-token conversation is
  3.7 GiB, which takes about 34 s on gigabit. llm-d does this over RDMA.
- **A latency-predictor service.** llm-d runs XGBoost training and
  prediction sidecars at ~300 queries/s each. For a handful of runtimes, a
  per-runtime formula (LD3/DI5) is enough, and their predictor assumes
  identical replicas, which Eugene's are not.
- **Weighted-random picking.** llm-d uses it to avoid many routers piling
  onto one replica from stale metrics. Eugene has one gateway counting its
  own requests in flight, so its numbers are not stale.
- **A second, hot-standby gateway.** CB measured two gateways losing
  affinity (66-75% against 75-81%), and a restart lost 0.2 points. The
  control root's warm standby covers what must survive.
- **Self-asserted priority and tenant headers.** llm-d's docs warn against
  them, and Eugene has the identity to avoid them (LD1).

## Calls for Troy

| # | Question | Recommended |
| --- | --- | --- |
| LD-C1 | Which of LD1-LD7 go on the roadmap, and in what order? | **Taken 2026-10-21: all seven.** Their order is set in the master roadmap with everything else unfinished. (Recommended was LD1, then LD2 and LD5, then LD3, then LD4, with LD6 and LD7 in the Platform half.) |
| LD-C2 | LD1: over a key's concurrency limit, wait in a queue or keep refusing with 429? | **Taken 2026-10-21: queue.** Troy: the hard limit was there to make early development faster; a queue is the more advanced feature, and Eugene is ready for it. Not the highest priority. This reverses A5's "Refused admission does not enter a queue" ([`scoped-client-access.md`](scoped-client-access.md)). The queue is bounded; LD1's design sets the bounds (recommended: up to 8 waiting per key, for up to 60 s, then 429). The concurrency limit itself stays: a key still runs at most its limit at once. |
| LD-C3 | LD1: is fairness per person or per key? | **Per person when Eugene knows the person behind the request** (a signed-in app such as Workbench, or a key a person holds), **otherwise per key.** One person running three tools then gets one share, not three. |
| LD-C4 | LD1: where does priority come from? | **The operator sets each key's or app's band, and a request may only lower its own.** Workbench's memory learning and tidy pass go in background. Never a header that raises priority. |
| LD-C5 | LD2: what is the default size of llama-server's RAM prompt cache? | **Computed: 25% of the RAM free after weights and experts, between 8 and 64 GiB.** Settle it after measuring the main-loop pause at the computed size against the 8 GiB default. If the pause grows, keep 8 GiB and offer the larger size as a setting. |
| LD-C6 | llm-d now calls itself "an inference control plane". Change how Eugene describes itself? | **Keep the description, and lead with whose machines.** "A control plane for the machines you own: any GPU, Windows, macOS and Linux, your model folders, one sign-in." For the website batch. |
