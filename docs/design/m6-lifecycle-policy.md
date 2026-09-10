# M6 — Lifecycle policy (design)

**Status:** designed, built and **live-verified 2026-09-10**. Milestone **M6** of
[`local-inference-control-plane.md`](local-inference-control-plane.md).
Follows [M5](m5-multi-host-and-trust.md), whose core is built and whose
two-machine run has not happened. Contracts first, then implementation,
then a live acceptance run on this box — the first milestone since M3
that can be verified here, because everything it adds runs on
llama.cpp.

**What it is.** The five things an operator meets between "I launched a
model" and "the endpoint serves it well", in the order they meet them:
a launched model that is not routable; two copies of one model that are
not balanced; a backend that fails with nothing behind it; a model that
holds VRAM all night for nobody; and a launch that will not fit and
finds out by crashing. Each was named at an earlier milestone and
deferred to here. This is the llama-swap-without-Docker answer, and the
half of differentiator #7 that M0–M5 built the layers for but never
switched on.

**Three scope decisions are Troy's** (§2, §5, §5 again). Each is stated
below with a recommendation and the main tradeoff, and the build
proceeds on the recommendation because the surrounding work is the
same either way. Overturning one changes one module, not the
milestone.

---

## 0. What was verified before designing (2026-09-10)

The prompt said to verify state with `gh`, not with CLAUDE.md, because
a WSL2 session might have moved things. It had not.

| Repo | HEAD | Matches CLAUDE.md |
|---|---|---|
| `specs` | `59cdde6` | yes |
| `agent` | `53d815d` | yes |
| `gateway` | `5ad5993` | yes |
| `inference-driver` | `97f6583` | yes |
| `library` | `77f2b4d` | yes |
| `control` | `d9d344a` | yes |
| `ui` | `5ebd6eb` | yes |

All six consumers pin `73ddc83`; every working tree is clean.
`wsl --status` reports WSL is **not installed**. M4's design §8 still
says no vLLM process has run, and **`STARTUP_BUDGET_SECONDS = 600`
remains a design estimate** — there is no TIMING or SOCKET measurement
to design against, so nothing here depends on that number. M5's
two-machine run has likewise not happened; the multi-host findings
this document leans on are the in-process ones.

Four more facts, found while reading, that shape the design:

1. **This box has one GPU today.** `nvidia-smi -L` lists the RTX 5090
   only (32,607 MiB, ~2.3 GiB held idle). CLAUDE.md's "RTX 3090, RTX
   5090" is not what the driver sees. The two-replicas-on-two-GPUs case
   therefore **cannot be produced here**; §10 says what a single card
   does and does not prove.
2. **M5's agent half was never built.** The agent has no `/v1/node`, no
   `/v1/node/enroll`, no device detection, and never fills
   `Runtime.node` — `grep` for any of them in `agent/src` returns
   nothing outside `_generated/`. The control repo's 85 tests run
   against fake agents that *do* answer `/v1/node`. So `Node.devices`
   has never been reported by a real agent, and the input M6's
   admission was told to use does not exist yet on the side that has to
   measure it. M6 builds the agent's device detection and the
   unenrolled `GET /v1/node` because admission needs live per-device
   free memory on the host that will spawn the engine. Enrollment
   itself stays M5 debt.
3. **The gateway routes to a driver whose engine is not ready.** The
   routing table keys on each driver's `/v1/info.modelId`, which a
   driver reports from its config whether or not the engine behind it
   answers. The contract has said since M0 that `ready` is "the only
   state in which the gateway will route to it"; the code never checked.
   Replicas make this visible: the moment one replica is stopped, a
   round-robin that ignores status sends every other request into a
   refused connection and only the cascade saves it.
4. **The gateway's runtime join is by alias and drops replicas.** Runtime
   facts are keyed by `modelAlias`, and an alias claimed by two runtimes
   is discarded as ambiguous — so exactly the case this milestone is
   about loses attribution. M4 added `DriverInfo.runtime` for this: a
   driver names the runtime it follows, so the join is
   driver → runtime by **name**, and replicas stop being ambiguous.

Two models were on disk (a 16.5 GB 27B and a 22.8 GB 40B, both Q4).
Neither fits twice on 30 GB free, so a 1.8 GB Qwen3-1.7B Q8_0 was
fetched into `d:\py\eugene-plexus\smoke-test\models\` for the replica
run. The 40B is the admission test's "will not fit".

---

## 1. The seam, as an operator meets it

**Launch.** The library's profile editor posts `RuntimeSpec` to the
agent; the engine loads; `gateway /v1/models` returns `[]`. M2 named
the gap, M4 made a driver able to *follow* a runtime by `runtimeName`,
and the UI's post-launch text still says "not routable yet: an
inference-driver has to point at it". Nothing creates the driver.

**Replicas.** Two runtimes with one alias need two hand-made drivers.
The gateway groups them by model id and sorts them by name; every
request goes to the first, the second serves only when the first fails.
`routing.py` says so in a comment: round-robin was deferred to this
milestone so failover stayed testable.

**Failover.** A cascade exists across drivers serving the *same* model
id, and nowhere else. There is no way to say "this alias, then that
one": a local 30B and a `claude_code_cli` driver serve different model
ids and never meet. `llm-priority-list-failover` has been designed since
v0.3 and this is the first milestone with two backends to cascade
between.

**Idle.** A `ready` engine holds its VRAM until an operator presses
Stop. `POST /v1/runtimes/{name}/stop` exists precisely because "an
engine holds GPU memory", and nothing calls it.

**Admission.** A runtime that does not fit spawns, reads weights for a
minute, and dies with a CUDA out-of-memory in the captured engine
output. The library can compute fit to the byte and does, on the
discovery screen; the launch path never asks.

---

## 2. Driver provisioning — a companion driver per runtime

> **Troy's call. Recommendation: per-launch, created by the agent.**
> Main tradeoff: one more process per loaded model, against a pool's
> allocation state and drivers whose identity changes per launch.

### The two shapes

**A companion driver per runtime.** When a runtime is declared, the
agent also declares an `inference-driver` component that follows it by
`runtimeName`, spawns it, and removes it when the runtime is removed.
Two replicas are two runtimes are two drivers. Launch is one call and
ends with a routable model.

**A declared pool.** The wizard declares N drivers up front; a launch
claims a free one, patches its `runtimeName`, and restarts it. Fewer
processes when models come and go; a driver's name stays constant.

### Why the companion wins

- **It is the existing rule, not a new mechanism.** The contract has
  said since M0 that a driver runs *one instance per backend* and
  *belongs next to its engine*. A runtime is a backend. One driver per
  runtime is that sentence applied; a pool contradicts it — a pooled
  driver is a driver per *slot*, whose backend changes.
- **The driver's name is what the gateway routes on and what a
  response reports.** `CompletionRoutingInfo.driver` and the admin
  panel both name drivers. A pool makes `gpu-driver-3` mean a different
  model every hour; a companion means `qwen3-a-driver` means what it
  says for as long as it exists.
- **A pool needs allocation state** — which driver is claimed by which
  runtime — and that state has to survive an agent restart and be
  reconciled when it disagrees with reality. The companion has none: the
  runtime declaration *is* the record, and the companion is derived
  from it deterministically (§7 on why this keeps it out of the log).
- **Multi-host placement falls out.** The agent that spawns the engine
  spawns the driver beside it, on the same host. A pool would need a
  per-node pool or a placement decision.
- **Pool exhaustion is a failure mode with no good answer.** Refuse the
  launch, or evict a running model's driver. The companion has no
  ceiling other than the one admission enforces on VRAM.

The cost is real and small: an inference-driver is a FastAPI process,
roughly 60–80 MB resident and one port, per loaded model. On an install
serving three models that is three processes an operator would not
have counted. §9 keeps it as a risk.

### Who creates it: the agent

Not the UI (the flow must work from `curl`), not the library (M2: it
never launches and never calls the agent), not the control root (M5: it
spawns nothing and forwards declarations), and not the gateway (it
holds no backend knowledge and cannot spawn). The agent already owns
component spawning, port assignment, config-file scaffolding and the
service-token trio. Provisioning a companion is one more topology entry
written by the process that already writes them.

### Shape

- **`RuntimeSpec.autoDriver`**, boolean, default **true**. False means
  "I will front this runtime myself" — the M4 workflow, still supported,
  and how an operator points one hand-tuned driver at an engine.
- The companion is named **`<runtime>-driver`**, kind `inference-driver`,
  URL on a port the agent assigns from the runtime range, config file
  `drivers/<runtime>-driver.yaml` beside the agent's own config. Its
  config is three lines: `provider: openai_compat_custom`,
  `runtimeName: <runtime>`, `modelId: <alias>`. The gateway keys on
  `modelId`, so the alias goes in verbatim.
- **`Runtime.driver`** reports the companion's component name, so the
  dashboard can say which driver fronts which engine without the
  operator joining two lists.
- **Ordering.** The runtime is persisted first — its port is assigned at
  write time — and the companion is declared second, so when the driver
  resolves `runtimeName` the answer exists. M4's "a driver written
  before its runtime comes up degraded" cannot happen on this path.
- **Coupling.** `DELETE /v1/runtimes/{name}` removes the companion;
  `PATCH` re-targets it if the alias changed; a rename renames it.
  `stop`/`start` leave the driver running — it is cheap, and a driver
  answering `/v1/info` for a stopped engine is what lets the gateway
  list an on-demand model (§5).
- **Reconcile at boot.** For every runtime with `autoDriver: true` and
  no component named `<runtime>-driver`, create it. An agent upgraded
  onto an existing install gains companions for its runtimes on first
  start; an operator who deleted a companion by hand gets it back,
  which is the honest reading of `autoDriver: true`.
- **Collision.** A component already named `<runtime>-driver` that is
  not a companion is a 409 at declaration, naming both.

### The gate the gateway was missing

Two facts from §0 meet here. A companion driver is a running process
whose `/v1/info` reports a `modelId` whether its engine is `ready`,
`loading` or `stopped`. So the gateway must join each driver to its
runtime by `DriverInfo.runtime` and route only to backends whose
runtime is `ready` (or that follow no runtime at all — a cloud or CLI
driver has no engine of ours to be not-ready). This is what makes a
stopped replica invisible to the balancer instead of a guaranteed
failed attempt, and it is the contract's stated rule finally enforced.

The M4 alias join goes. Attribution by name means
`CompletionRoutingInfo.runtime` is filled for replicas too — it names
the runtime behind the driver that actually answered.

---

## 3. Load balancing — least outstanding requests, weighted by slots

**The signal that is always present is the gateway's own.** M4
recorded that vLLM serves `/load` as a live in-flight count and
llama.cpp serves nothing comparable. Whatever balances the two has to
work when the number is absent, and the gateway holds a better number
anyway: it knows exactly how many requests *it* has in flight to each
backend, for every engine, with no extra round trip and no per-engine
adapter. Engines bind to loopback with no auth of their own, so traffic
that bypasses the gateway is a configuration an operator chose rather
than a case to design for.

**Policy:** among the eligible backends of a tier (§4), pick the one
with the lowest `inflight / parallelSlots`, where `parallelSlots` comes
from the runtime's reported capabilities and defaults to 1 for a
backend with no runtime. Ties break round-robin with a rotating cursor
per model, so an idle install alternates — which is what the acceptance
run observes — and a busy one fills capacity before queueing on a
saturated replica. Chosen per request, on the way through; the cascade
then walks the *rest* of the tier in the same order, so a failed
replica costs one attempt rather than a request.

**`loadBalancing`** on the gateway's config trio takes `least_busy`
(default) and `round_robin`. The second exists because a strictly
alternating order is worth having when an operator is comparing two
replicas or reproducing a report, and because a knob that is tunable
belongs in the UI.

**Not consumed at M6: vLLM's `/load`.** The gateway's own count is a
superset for traffic through the gateway, symmetric across engines, and
free. Recorded as the refinement it is: a driver could expose its
engine's load on `/v1/info` later and the balancer could prefer it
where present. Nothing in this design blocks that, and nothing here
depends on it.

---

## 4. Priority-list failover — every model is a slot

**A slot is an ordered list of tiers; a tier is every eligible backend
serving one model id.** The insight that makes this small: a model id
already names a replica set (§2), so a priority list of model ids *is*
a priority list of tiers, and the natural no-config case — a client
asks for `qwen3-1.7b` — is the one-tier slot `[qwen3-1.7b]`.

A configured slot extends that list:

```yaml
modelSlots:
  - model: coder                      # what a client asks for
    targets: [qwen3-coder-30b, claude-opus-4-7]
  - model: qwen3-1.7b                 # a real alias, given a fallback
    targets: [claude-opus-4-7]
```

Tiers for `coder`: drivers serving `coder` (none — it is a virtual
name), then drivers serving `qwen3-coder-30b` (balanced across its
replicas), then drivers serving `claude-opus-4-7`. Tiers for
`qwen3-1.7b`: its own replicas, then the cloud driver. The rule is
uniform — `tiers = [model] + targets`, empty tiers dropped — so nothing
special-cases a virtual alias.

**Cloud subscriptions are just another entry** because a
`claude_code_cli` driver already serves a model id
(`claude-opus-4-7`) that a target can name. No new driver kind, no new
provider field, no "cloud" flag anywhere.

**Cascade rule, unchanged in kind:** transport error, 5xx and timeout
cascade; 4xx hard-fails. New in extent: the walk is *within the tier
first, then the next tier*, and `attempts` counts every backend tried.
`ChatCompletionResponse.model` already names what answered, which after
a cross-tier cascade is a different model id than was asked for — the
contract said so since M0 and it is now reachable.

**A tier whose runtimes are asleep is awaited, not skipped.** With a
local model in tier 1 declared `startOnDemand` and a cloud driver in
tier 2, the gateway wakes the local model and waits (§5) rather than
falling straight through to the subscription. The operator put the
local model first; skipping it because it was idle would spend money
*because* idle unload worked, which defeats the point. The wait is
bounded by `swapWaitSeconds`; past it, the next tier is tried, and the
response says so.

**Config type.** `ConfigValueType` has carried `driver_list`, reserved
since M2 for exactly this, under a name that says the wrong thing —
targets are model ids, not drivers, because a model id expands to a
replica set and a driver name does not. It becomes **`model_slots`**,
holding an ordered JSON array of `{model, targets}`. That is a
`common.yaml` change, so **the re-pin radius is all six consumers**
(§7). The UI falls through unknown value types to free text today, so
until a structured renderer exists this field edits as JSON in a
textarea. Named in §8 as the UI gap it is, not hidden.

**Why a config field and not a resource.** Slots are a routing policy
the operator sets and rarely changes — the shape of the standard
config trio, editable from the generic editor with no gateway-specific
UI code, and validated per key on PATCH like everything else. A
`/v1/admin/slots` collection would be a second config surface for one
list. The gateway's own config is a component's file, not control
state: nothing here is replicated, for the same reason no component's
trio is (§7).

---

## 5. Idle unload and swap on demand

Three components each see one third of the picture:

| | sees requests | owns topology | owns the process |
|---|---|---|---|
| gateway | **yes** — the only one | reads it | no |
| control root | no | **yes** — declarations, replicated | no |
| agent | no | this host's | **yes** |

> **Troy's call. Recommendation: the gateway decides, the agent
> executes, and nothing about it enters the replicated log.** Main
> tradeoff: a stop/start that crosses hosts goes gateway → that node's
> agent directly, so the gateway has to learn which agent owns a
> runtime, against routing it through the control root and losing model
> swapping whenever management is down.

### Why the gateway decides

Idle is a property of traffic, and only the gateway has the traffic. An
agent could count requests at the engine, but a driver's health probe,
a UI test button and a real completion look the same at that port, and
a vLLM `/load` of zero says nothing about a llama.cpp replica. Demand
is what a *client* asked for, by model id, and that arrives at exactly
one place. M5's split table already put "idle-unload triggers" on the
gateway's row; this only makes it true.

### Why the agent executes without the control root in the path

M5's guarantee, tested by `m5-acceptance.sh`, is that inference
survives the control root dying. Idle unload and swap-in are
data-path behaviours: a request for a sleeping model has to wake it
whether or not management is up. Routing "start this engine" through
the control root's log would make every on-demand model unreachable the
moment the root is `down`, which turns a management outage into an
inference outage — the exact thing M5 spent a milestone preventing.

So the gateway calls the **owning node's agent** at
`POST /v1/runtimes/{name}/stop` and `/start`. Which agent that is comes
from `Runtime.node` (the agent fills it from its own identity, and it
is absent on an unenrolled single-host agent) joined to the control
root's `GET /v1/nodes` for the URL — read on the same refresh as
topology when the gateway is configured with a `controlUrl`, and
falling back to the gateway's one configured agent URL otherwise. That
closes the trap the prompt named: both the driver and the gateway
default to `loopback:8079`, and the first lifecycle action that crossed
hosts would have gone to the wrong agent. The driver's own lookup stays
local on purpose — a driver lives beside its engine and its agent, so
loopback is right there and wrong everywhere else.

### Reconciled with M5's three rules

1. **LogOp stays closed at nine.** "Runtime X is stopped because idle"
   is a fact about a process, observed by one gateway at one moment. It
   is *liveness*. A promoted standby cannot have seen the traffic that
   made it true, and replicating it would do one of two bad things: a
   stale "loaded" bit would start a model nobody asked for on a host
   that had freed the memory, or a stale "unloaded" bit would hide one
   that is serving. The right answer after a promotion is what the
   control root already does — ask each agent what is running. No new
   op, argued and not assumed.
2. **Declarations are unchanged and still replicated.** `autoStart`,
   `idleUnloadSeconds` and `startOnDemand` are fields on `RuntimeSpec`,
   which rides inside `putRuntime` verbatim. The policy replicates; its
   current effect does not.
3. **Liveness is layered on at render time.** `Runtime.stopReason` is
   the agent's observation, reported on `GET /v1/runtimes` and relayed
   through the union view like `status` is, and never written anywhere
   a standby reads.

### Auth

`stop` and `start` were operator-only, on the reasoning that a leaked
service token must not be able to start or stop a process holding a
GPU. They now accept the operator **or the gateway's own service
audience** — `service:gateway`, checked exactly, not "any service
token". The gateway is the component M5 named for this job, and the
audience is what the token scheme exists to say. A leaked driver or
library token still cannot touch an engine.

### Per-runtime policy, on the spec

- **`idleUnloadSeconds`**: stop the engine after this long with no
  request for its model through the gateway. Absent or 0 means never,
  which is every existing declaration's behaviour unchanged.
- **`startOnDemand`**, default **false**: start this runtime when a
  request arrives for a model it serves and it is `stopped`. False by
  default so that a hand-pressed Stop stays stopped; the UI's launch
  dialog sets both when the operator picks a lifecycle. Combined with
  `autoStart: false`, this is llama-swap's model: declare five, load
  none, serve whichever is asked for, unload it when it goes quiet.

Both are engine-agnostic. Nothing here knows what `loading` costs for a
given engine — that is the adapter's startup budget, and it is why the
swap wait is a gateway knob rather than a constant.

### What the gateway does

- Tracks `lastRequestAt` and an in-flight count per backend, keyed to
  the runtime behind it.
- Every `idleCheckSeconds` (default 15), for each `ready` runtime with
  `idleUnloadSeconds > 0`, no in-flight requests, and idle longer than
  its timeout: `POST .../stop` with `{"reason": "idle"}`. Never with a
  request in flight, and never a runtime that has not declared a
  timeout.
- On a request whose tiers have no eligible backend but at least one
  `stopped` runtime with `startOnDemand`: `POST .../start`, then poll
  the runtime until `ready` or `swapWaitSeconds` (default 120), refresh,
  and serve. The response carries `swapped_in: true` and the wait in
  `waited_ms`. Streaming waits before the stream opens. Past the wait,
  the next tier is tried; with none, a 503 that names the runtime and
  says it is still loading.
- **Eviction, bounded by opt-in.** If the agent refuses the start on
  admission (§6), the gateway stops the most-idle `ready` runtimes on
  the same node that have themselves declared `idleUnloadSeconds` and
  have nothing in flight, until the deficit is covered, then retries
  once. Only runtimes that opted into lifecycle policy are ever evicted;
  a model declared without a timeout is never unloaded by anyone but
  the operator.

### What the agent does

`POST /v1/runtimes/{name}/stop` gains an optional body
`StopRequest{reason}`; the agent records it and reports
`Runtime.stopReason` as `operator`, `idle` or `autoStart`, cleared on
start. The dashboard can then say "unloaded after 600 s idle" rather
than showing a stopped model with no explanation.

---

## 6. VRAM-aware admission — refuse, never queue

> **Decision: refuse, with the arithmetic in the response and a
> `force` override. Never queue.**

**Why not queue.** A queue is a promise about the future the control
plane cannot keep. When VRAM frees depends on idle policy and operator
action; a queued launch that fires at three in the morning because a
neighbour idled out is a surprise, and a queue needs ordering and
persistence across restarts — new replicated state, which §5 refused
for the same reason. What "queue" is actually asked for is covered
another way: declare the model with `startOnDemand` and the gateway's
swap-in *is* a queue of length one, triggered by a real request, with
eviction bounded by opt-in.

**Why refuse at all**, when the standing rule is "never reject a model
the user owns": because the refusal is a *statement of arithmetic with
an override*, not a judgement about the model. The operator sees
required bytes, free bytes, which device, what basis, and which
runtimes hold the memory, and passes `?force=true` if they know better.
The alternative — spawn and let CUDA say no — costs a minute of weight
reading and an out-of-memory in a log, which is the current behaviour
and the complaint.

### Inputs

- **Free memory per device, live, on the host that will spawn.** The
  agent gains device detection (`engines/devices.py`): `nvidia-smi
  --query-gpu=index,name,memory.total,memory.free`, verified here on the
  5090; ROCm, XPU and Metal readers written from their tools' documented
  output and marked unverified, each failure a named warning rather
  than a silent zero, exactly as the library's `hardware.py` does. It
  is a second copy of a small thing — the rule is components share
  schemas, not code, and the agent has to work with no library present.
  It backs `GET /v1/node` (`devices`, `os`, `arch`, `enrolled: false`)
  as well, which the contract has described since M5 and no agent has
  served.
- **Target devices** from the spec's `env` — `CUDA_VISIBLE_DEVICES` or
  `HIP_VISIBLE_DEVICES` — else every device of the detected kind. The
  budget is the *largest single* target device's free memory, because
  llama.cpp's default split is by layers and a model that fits across
  two cards and on neither is `split`, not `fits`.
- **Required bytes.** When a `library` component is in this agent's
  topology, the agent asks it: `GET /v1/models?path=<modelPath>` for the
  id, then `GET /v1/models/{id}/fit?contextLength=&vramBytes=<free>`
  with the spec's `contextSize` (or the model's own context when
  unset, which is what the engine would take). `basis: metadata`. With
  no library reachable, the file's size on disk plus a 10% allowance,
  `basis: file_size`, said out loud.

### Verdict

The library's four verdicts are kept in meaning and mapped onto a
launch decision by what the spec asked for:

| fit | `gpuLayers` unset, negative, or ≥ 99 (full offload — 99 is llama.cpp's idiom for everything) | `gpuLayers` set below that |
|---|---|---|
| `fits` | admit | admit |
| `tight` | **refuse** — something else holds the memory now; §5's eviction is the answer, or free it | admit |
| `split` | **refuse** — it would spill or fail at load | admit — the operator chose partial offload |
| `no` | **refuse** | **refuse** — larger than VRAM and RAM together |
| `unknown` | admit, `warning` set | admit, `warning` set |

`unknown` — no detection tool, an unreadable device — never blocks a
launch: a verdict computed from a missing budget is worse than no
verdict, and refusing on it would refuse every AMD box until that path
is verified on hardware.

### Surface

- **`POST /v1/runtimes/admission`**, body `RuntimeSpec`, returns
  `Admission` with 200 always: `decision` (`admit` | `refuse`), `fit`,
  `requiredBytes`, `freeBytes`, `device`, `basis`, `blockers` (the
  `ready` runtimes on that device, most idle first — the list §5's
  eviction walks), `reason` in prose. The dry run for a launch dialog,
  for the control root before forwarding, and for the acceptance run.
- **Enforced** in `POST /v1/runtimes` when `autoStart` is true and in
  `POST /v1/runtimes/{name}/start`; both refuse with **422** and the
  `Admission` prose in `detail`, both take `?force=true`. A runtime
  declared with `autoStart: false` is not measured — it is not being
  launched — and is measured when it starts.
- Not shared with the library's `Fit`. The library describes a model
  against a host; this decides a launch of a spec on a device. They
  overlap on the verdict words and diverge on everything else, and a
  shared schema would couple the discovery screen to the supervisor.

---

## 7. Contract

Every change below, by document. Nothing changes on
`inference-driver.yaml`, `library.yaml` or `control.yaml`: the driver
already reports `runtime`, the library already computes fit, and
`RuntimePlacementSpec.spec` is opaque so the new spec fields forward
through the control root untouched.

```
common.yaml
  ConfigValueType   driver_list -> model_slots          (reserved since M2; renamed,
                                                          shape defined; re-pins ALL SIX)

agent.yaml
  RuntimeSpec       + autoDriver (default true)
                    + idleUnloadSeconds
                    + startOnDemand (default false)
  Runtime           + driver         companion component name
                    + stopReason     operator | idle | autoStart
  POST /v1/runtimes/admission        dry run -> Admission
  POST /v1/runtimes                  ?force ; 422 on admission
  POST /v1/runtimes/{name}/start     ?force ; 422 on admission
  POST /v1/runtimes/{name}/stop      optional body StopRequest{reason}
  stop/start auth                    operator OR service:gateway
  Admission, StopRequest             new schemas
  GET /v1/node                       unchanged; now served (devices, unenrolled)

gateway.yaml
  config            + modelSlots (model_slots), loadBalancing (enum),
                      swapWaitSeconds, idleCheckSeconds, controlUrl
  GET /v1/admin/routing              the resolved table: slots -> tiers ->
                                     backends, in-flight, runtime state
  ModelRoutingInfo  + tiers, ready_backends
  CompletionRoutingInfo + tier, swapped_in, waited_ms
  /v1/chat/completions 503 text     names the runtime being woken
  info.description                  routing table joins by DriverInfo.runtime;
                                     routes only to ready runtimes
```

**Re-pin radius: all six.** `common.yaml` changes, and
`datamodel-code-generator` emits every schema in the components
document whether referenced or not (M4's finding). The `ui` generates
from all five documents and needs no codegen-list change — no new
document lands, so the second edit that bit at M5 does not apply. Each
consumer's generated models are diffed against the previous pin before
the bump, as the workflow requires.

**What this deliberately does not add.** No `Runtime.node` on the
spec (placement stays on the control root's `RuntimePlacementSpec`);
no new `LogOp`; no `driverPool`; no per-request `/load` field; no
change to `RuntimeStatus` — a stopped-because-idle runtime is
`stopped`, with `stopReason` beside it, because the state is the same
state and a new enum member for the reason would be M4's mechanism
mistake in reverse.

---

## 8. Scope

**In:** the companion driver and its reconcile; the gateway's
name-keyed runtime join and the `ready` gate; least-busy balancing with
a round-robin option; model slots with tiered cascade; idle unload;
start on demand with a bounded wait; opt-in eviction; admission on the
agent with a dry-run endpoint, enforcement and `force`; agent device
detection and the unenrolled `/v1/node`; the supervision-loop fix for a
planner that raises something other than `SpawnPlanError` (the M4
process note, fixed here because `runtimes.py` is touched); the six-way
re-pin; `scripts/m6-acceptance.sh`, run.

**Out:**

- **A structured UI editor for `modelSlots`.** It edits as JSON in the
  generic editor's fallback textarea. The renderer is `ui`-repo work
  with no contract consequence.
- **The UI's `runtime_name` dropdown**, still (M4).
- **Placement across nodes** — "which node should host this model" —
  is not decided here. Admission answers "does it fit where the operator
  put it". `Node.devices` across hosts is the input a later placement
  policy reads.
- **Consuming vLLM's `/load`.** §3.
- **Two-GPU verification.** The box has one card (§0). The replica,
  kill, idle and admission paths are verified on one device; per-device
  pinning is exercised (`CUDA_VISIBLE_DEVICES=0` on both) but cannot be
  distinguished from not pinning.
- **Multi-host lifecycle actions on real hardware.** The gateway
  resolves the owning agent through `/v1/nodes`; with one node it always
  resolves to the same agent. Same open question as M4 and M5.
- **True token streaming** through the cascade (M0's limitation, still).

---

## 9. Risks

- **One more process per model.** §2's cost. Measured, not assumed:
  the acceptance run records the companion's resident size. If the
  first-run experience gets worse, so does the product.
- **Idle unload will fire while a slow client is thinking.** A chat
  client that pauses ten minutes between turns pays the load again. The
  default is *never*; an operator who sets 600 s has chosen that, and
  `swapped_in` on the next response tells them what it cost.
- **The gateway is now a lifecycle actor with a service token that can
  stop engines.** Deliberate and narrow (§5), but it is the first time
  a non-operator credential can free a GPU. A compromised gateway can
  stop your models. It could already refuse to route to them.
- **Admission arithmetic is estimation with named assumptions**, and the
  library's own doc says it will sometimes be wrong. `force` exists so
  that a wrong estimate costs a flag, not a model. The `tight` refusal
  is the one most likely to annoy: it says "something else holds the
  memory", which on a desktop is often a browser.
- **Eviction is only as safe as opt-in.** A runtime with
  `idleUnloadSeconds` set can be stopped by a request for a *different*
  model. That is the contract of setting it, and the doc says so on the
  field. A model that must stay resident sets none.
- **The agent detects devices twice in the install** (agent and
  library, two readers of the same `nvidia-smi`). They can disagree by
  a few MiB across a second. Admission uses the agent's, because the
  agent is on the host that spawns; the library's stays the discovery
  screen's.
- **The renamed `ConfigValueType` value forces a six-way re-pin** for a
  string nobody consumed. The alternative — keeping `driver_list` and
  defining "a list of model ids" under it — would have been the cheaper
  lie.

---

## 10. Verification

`scripts/m6-acceptance.sh`, on this box, six processes: agent, control,
gateway, library, and two companion drivers it did not write, over two
`llama-server` replicas of one 1.8 GB GGUF pinned to `CUDA_VISIBLE_DEVICES=0`.

1. **Launch ends routable.** `POST /v1/runtimes` twice with one alias
   and no driver config anywhere. Both companions appear in
   `/v1/components`; when both runtimes are `ready`, `gateway
   /v1/models` lists the alias once with two drivers.
2. **Round-robin.** Six sequential completions; `x_eugene_plexus.driver`
   alternates and `.runtime` names a different replica each time.
3. **Kill one replica through the OS.** `Stop-Process` on its pid. The
   next completion returns; either the refresh already dropped the dead
   replica (`attempts: 1`, the other driver) or the cascade fired
   (`attempts: 2`). Both are passes; the record says which.
4. **Idle unload.** Both replicas declared `idleUnloadSeconds: 20`. No
   requests for 45 s; `nvidia-smi --query-gpu=memory.used` drops by at
   least the model's size; both runtimes read `stopped` with
   `stopReason: idle`; `/v1/models` still lists the alias.
5. **Swap on demand.** A completion for the alias while both are
   stopped returns, with `swapped_in: true`, `waited_ms > 0`, and one
   runtime back at `ready`.
6. **Admission.** `POST /v1/runtimes/admission` for the 40B at
   `contextSize: 131072` returns `decision: refuse` with the numbers;
   `POST /v1/runtimes` for it returns 422; the same with `?force=true`
   is accepted (and immediately deleted before it loads).
7. **Failover across tiers.** A `modelSlots` entry mapping `coder` to
   `[<alias>, <a driver that is stopped>]`; a completion for `coder`
   returns from tier 1 with `tier: 1`.

**What one GPU proves and does not.** Everything above is about
processes, routing and memory returned to the device, and one card is
enough for all of it. What it cannot show is a replica landing on a
*second* card — the env var is passed, argv shows it, and the engine
would honour it, but the observable is identical to not pinning. When a
second GPU is in the box, re-run with `CUDA_VISIBLE_DEVICES` 0 and 1
and check `nvidia-smi` per device; the script takes the device list as
an environment variable for exactly that.

Unit tests use fake drivers (gateway) and a fake engine plus stubbed
detection (agent), as M5 did. The live run is where every prior
milestone's worst defects came from, and it is not skipped.

---

## 11. Implementation notes (2026-09-10)

Built the same day as the design, in two repos plus a six-way re-pin,
and verified by [`scripts/m6-acceptance.sh`](../../scripts/m6-acceptance.sh)
— record in [`docs/acceptance/m6-six-process-run.md`](../acceptance/m6-six-process-run.md).
Twenty-nine checks green on the second run; the first run found two
defects, both real, both below.

| Repo | Landed | What |
|---|---|---|
| `specs` | `8727736` | the contracts of §7, verbatim |
| `agent` | `62f693b`, `7565031` | `companions.py`, `admission.py`, `engines/devices.py`, `routes/node.py`, stop reasons, `service:gateway` on stop/start, the supervision-loop fix; 283 tests |
| `gateway` | `c53ebcd`, `c43baf8` | the name-keyed join and `ready` gate, `TieredClient`, least-busy balancing, `lifecycle.py`, `GET /v1/admin/routing`, refresh on demand; 124 tests |
| `inference-driver` `library` `control` | `7fe3e1e` `57024d6` `ca17ba4` | re-pin only |
| `ui` | `f679fab` | re-pin, a `model_slots` JSON editor, the honest post-launch message, `stopReason` on the dashboard |

### What the live run found

**The routing table was a refresh interval behind about readiness.**
The design said the gateway routes only to `ready` runtimes (§2) and
the code did — against a snapshot up to `routingRefreshSeconds` old,
15 s by default. Every request in the seconds after both replicas
turned `ready` met a table that still said `loading`; the completion
after a replica was killed met one that had not noticed. **New rule:**
a request that finds nothing eligible refreshes the table — shared
across concurrent callers, at most once a second — before waking
anything or answering; a request that finds a backend never pays for a
topology read. That keeps M0's "a request never pays for discovery" on
the path that matters and removes a fifteen-second 503 after every
load.

**`gpuLayers: 99` read as partial offload.** §6's table said full
offload was "unset or ≥ 999". Every profile in this project writes 99,
llama.cpp's idiom for everything, and the 40B at 128k was *admitted* as
partial offload the operator had chosen. The threshold is 99, negative
counts as full too (`-1` is upstream's spelling), and the table above
says so now.

### Where the implementation departs from, or refines, this document

1. **Topology comes from each agent, not from the control root's union
   views.** §5 and the first draft of `gateway.yaml` said the gateway
   would read the control root's `/v1/components` and `/v1/runtimes`
   when a `controlUrl` is set. It reads the control root's **node list**
   instead and then each node's agent directly. Two reasons, one
   contractual: `RuntimePlacement` in `control.yaml` carries no
   capabilities, no `idleUnloadSeconds`, no `startOnDemand`, no
   `stopReason` — it is the reporting shape, and adding lifecycle fields
   to it would duplicate the agent's `Runtime` in a second document. The
   other is the design's own argument: a poll that dies with the control
   root would take model swapping down with management. The control
   root's contribution is the one thing only it knows — which agents
   exist and where. `gateway.yaml`'s text is corrected in the same
   commit as this note.
2. **The alias join survives as a fallback.** A driver that reports no
   `runtime` — a hand-written `baseUrl`, a driver older than M4 — is
   joined to the runtime whose alias equals its model id when exactly
   one does, as before. Replica pairs still drop it, because naming one
   of two is a coin flip; a companion always reports `runtime` and never
   hits this path.
3. **Idle is counted from "ready" for a runtime that never served.**
   The gateway records when it first saw each runtime `ready`; a model
   loaded at boot with no traffic unloads after its timeout rather than
   sitting resident because no request ever stamped it.
4. **`stopReason` defaults are derived, not stored.** A `stopped` runtime
   with no recorded reason is `autoStart` when declared with `autoStart:
   false`, else `operator` — the only two ways to be stopped without the
   agent having been told why.
5. **The companion's URL is loopback.** `http://127.0.0.1:<port>`, like
   every component the agent spawns. On a remote node a gateway on
   another host cannot reach it. The M5 design already carries this gap
   for hand-written components; it is M7's (networked polish) to give
   the agent an advertise address. Named here so the first two-host run
   is not surprised by it. **Resolved at M7**: `Component.advertiseUrl`,
   see [`m7-second-host-readiness.md`](m7-second-host-readiness.md) §4.
6. **Eviction ordering is the gateway's.** The agent's `blockers` come
   evictable-first, then by name; the gateway re-sorts by its own idle
   knowledge, because the agent cannot know idleness and did not
   pretend to.
7. **An agent whose `/v1/runtimes` cannot be read leaves its drivers
   routable on faith.** No facts means no gate, and the cascade sorts out
   the dead ones — nothing stops routing over a missing runtime list,
   which is the degraded-mode rule applied to the gateway.
8. **The supervision-loop fix landed.** A planner that raises anything
   other than `SpawnPlanError` is a crash with `last_error` set rather
   than a dead task and a runtime at `starting` forever. Tested with a
   `TypeError`, which is what M4 met.
9. **Admission measures against the largest single free device**, not
   the sum, and via the library only when the model is under a library
   root — the 40B was, so the run's `basis` was `metadata`. A model the
   library has not scanned falls to `file_size` plus 10%, said out loud.

### Process notes

- **The Write tool emits CRLF; the repos are LF.** Every file went
  through a byte-level normalizer before commit, as the M4 memo said to.
  Bash heredocs were used only for commit messages; every multi-line
  patch was a Python script run from a file. Zero heredoc casualties.
- **A test that truncates a 200 GiB file takes 150 s on Windows.** NTFS
  zero-fills; the first agent test run took four minutes for 36 tests.
  Admission grew a `size_of` seam and the tests describe a size instead
  of creating one.
- **Pydantic's trailing slash bit again**, in a test this time: a
  companion's `url` came back as `http://127.0.0.1:8091/`. Parse ports
  with `urlparse`, never `rsplit(":")`.
- **The venv launcher hides the process you meant to measure.** On
  Windows the venv's `python.exe` is a 5 MB stub whose child is the
  interpreter; the pid the agent holds is the stub's. Sum the tree.
- **`nvidia-smi -L` is the hardware inventory, not CLAUDE.md.** The box
  has one GPU today; the design and the script say so and take the
  device list as a variable.
