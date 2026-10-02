# Cache-aware balancing, v2: many conversations, many replicas

**Status: measured 2026-10-02 (late); the calls in §6 are Troy's and not
taken.** Follows [`prompt-cache.md`](prompt-cache.md) (PC1-PC7). Every
number below is in
[`docs/acceptance/cache-aware-balancing-measurement.md`](../acceptance/cache-aware-balancing-measurement.md).

Troy's brief: *load balancing that is cache-aware at scale — dozens of users
across dozens of backends.* PC4 (`conversation`, gateway `0718e3f`) was built
for one conversation on two replicas and measured one request at a time, and
its calls were taken without numbers for anything bigger. This document puts
the next calls with their numbers.

## 1. What decides whether a turn is cheap

A turn is cheap when the engine that gets it still holds the conversation's
prompt. Four things decide that; the gateway owns only the first today.

1. **Which replica gets the turn**: the gateway (PC4).
2. **Whether that replica has room.** llama-server's slots share one KV pool
   (`-c`) by default; when the prompts in flight on a replica add up past
   it, the engine refuses the next one or cuts a stream mid-answer, and the
   gateway today counts that as a broken backend and moves the conversation
   somewhere cold (record §5).
3. **Which of the replica's slots gets it**: llama-server, which sends every
   conversation that shares a prompt family to the one most similar idle
   slot, so **a replica keeps one conversation per family in its slots
   however many it has** (record §1; upstream #22083). The rest live in its
   RAM prompt cache (8 GiB by default): ~10 conversations of a 1B model,
   ~2-3 of an 8B.
4. **Whether the pool and that RAM cache still hold the conversation.**
   When they do not, the engine rereads it and says nothing; the only signal
   is the cached-token count on the answer (PC5).

And one thing bounds what any placement can share: **what two
conversations have in common.** Two Claude Code sessions in one project
share ~17,900 tokens; in two projects, ~670, because the project's path is
early in the system prompt. Two Codex users share ~9,600 of ~11,000 whatever
their project (record §6).

## 2. What the measurement says

Real Claude Code and Codex sessions (8 tool turns each) replayed through a
real install, each session a closed loop with think times, 64 tokens
generated a turn, time to first token at the client. Llama 3.2 1B, replicas
of 4 slots on one GPU; run-to-run noise is about 1.5 points. Reused share of
prompt tokens, TTFT p50:

| Policy | 3 replicas, 12 at once (room per slot) | 3 replicas, 24 at once (past the slots) | 8 replicas, 32 at once (past the pool) | 8 replicas, 64 at once (overload) |
|---|---|---|---|---|
| `least_busy` (before PC4) | 67.7%, 1.49 s | 64.7%, 7.57 s | 49.7%, 6.35 s, 60 failed | 43.6%, 16.1 s, 76 failed |
| PC4 (`conversation`, today) | 80.8%, 0.71 s | 75.0%, 4.51 s | 60.4%, 4.00 s, 56 failed | 45.4%, 15.0 s, 100 failed |
| spread | 81.3%, 0.73 s | 75.6%, 3.77 s | **80.2%, 1.05 s**, 44 failed | 71.4%, 2.96 s, 109 failed |
| spread + token budget | | | **81.5%, 1.26 s, 0 failed** (p99 16.9 s, against 30.5) | **72.7%, 4.01 s, 0 failed** (p99 19.0 s, against 84.8) |
| PC4 + safe slot pinning | 84.2%, 0.48 s | 76.2%, 4.49 s | 71.4%, 1.66 s, 29 failed | 40.6%, 14.2 s, 115 failed |
| spread + safe slot pinning | **85.4%, 0.43 s** | **77.8%, 4.30 s** | 79.1%, 1.20 s, 53 failed | 67.4%, 13.0 s, 115 failed |
| stateless rendezvous hashing | 76.4%, 1.13 s | 75.4%, 3.65 s | 73.5%, 2.23 s, 102 failed | 70.0%, 13.6 s, 130 failed |
| PC4 with two gateways | 75.2%, 0.93 s | 66.5%, 5.41 s | 66.7%, 2.81 s, 114 failed | 58.4%, 15.8 s, 137 failed |

**And the 8B, three replicas at `-c 65536` with four agents each (record §8): through Eugene as it
is, 158 of 204 turns fail** — a few prompts outgrow a pool, the circuit counts each as a broken
backend, and "cooling down" refuses everything else on healthy replicas. The budget alone answers
166; 35 of its 38 failures are still the circuit.

- **On a real install today, the pool and the circuit come first.** Four slots share one
  context; agent prompts in flight outgrow it; the gateway's circuit then takes the replica out.
  That is an outage, not a cache miss, and it needs CB3 before anything about caching.
- **Affinity is the first caching lever**: PC4 against `least_busy` reads 41% fewer
  tokens and halves TTFT at 12 at once.
- **Placing new conversations by what a replica holds is the second, and
  the one that scales**: within noise on three replicas, +20 points and a
  quarter of the TTFT on eight. `least_busy` counts requests in flight, and
  a replica whose agents are all thinking between turns looks empty.
- **A token budget removes the pool's failures** (engines as launched today): none in 1,152 turns at 32 and 64 at once, where
  spread alone failed 44 and 109, and the p99 falls by half to three quarters.
- **Slot pinning helps only where the pool holds a conversation per slot**:
  +3.4 points there (131,072 tokens for 4 slots, conversations to 31,000),
  1-10 points worse where it does not (98,304 for 4, and in overload). **Pinning the obvious
  way wedges llama-server** (record §4): a request pinned to a slot that is
  still busy stalled engines for up to 30 minutes. Waiting in front of the
  engine until the slot is idle removed it: 0 stalls in 1,224 turns.
- **Prompt-family placement, rendezvous hashing and a second gateway** each
  measured at or below the simpler choice.

## 3. The design

### CB1. Affinity is always on

Every request with a conversation key goes back to the replica that served
it, by PC4's rule (the key, the 30-minute table, the saturation spill), for
every `loadBalancing` value. `loadBalancing` then says only where a **new**
conversation goes. The value `conversation` is read as the default with
affinity, so no config file breaks and each request's recorded strategy
still says what ran.

The one honest use of no affinity is benchmarking replicas against each
other, where a tool sends one prompt again and again and PC4's fingerprint
pins it to one replica. That gets its own switch, `conversationAffinity`
(default on).

### CB2. A new conversation goes where there is room: `spread`

A new value of `loadBalancing`, and the default: a new conversation goes to
the replica **holding the fewest conversations per slot**, counted from the
affinity table (keys seen in its 30 minutes, whether or not a request is in
flight), ties broken by requests in flight, then rotation. `least_busy` and
`round_robin` stay selectable. A small change in `RoutingTable._order`: the
table already holds every key's backend and last-seen time.

### CB3. A turn waits for room in its replica's pool

**The budget.** Per runtime, the prompt tokens in flight (each request's
estimate: the conversation's last prompt tokens plus its new text at ~3.5
characters a token, or the whole request's size for a new one, plus its
`max_tokens`) must fit the runtime's pool. A turn that does not fit waits in
the gateway, its own replica first while it holds the conversation, until a
request there finishes; a request bigger than the pool alone is sent anyway
and the engine's own refusal is the honest answer. The wait is bounded like
a swap wait, after which the normal cascade runs.

**The pool size** comes from the agent: `/props` gives `n_ctx`,
`total_slots` and whether the pool is unified (one pool of `n_ctx`) or
divided (`n_ctx` per slot). A field on the runtime's capabilities, so a
contract change on `agent.yaml` (read by the gateway).

**A pool refusal under load is load, not a broken backend.** llama-server's
`500 Context size has been exceeded`, and a stream it cut for the same
reason, become a capacity outcome in the driver: cascade-eligible, and not
counted by the circuit (PC3's rule, one case further). Measured on the 8B,
this is most of the damage: 115-131 of a run's failures were the circuit
refusing healthy replicas after 22-42 real overflows (gateway#8).

**A margin on the estimate.** The budget's estimate (characters ÷ 3.5) let
two overflows through on a pool that holds two prompts; the budget keeps
10% of the pool spare.

### CB4. llama.cpp slot pinning, safely, where the pool has room

**Where.** The companion inference-driver fronts one engine and sees every
request to it, so it owns *conversation → slot*: least recently used out,
`total_slots` of them. The gateway hands it the conversation key (an
internal `GenerateRequest` field, never forwarded upstream); the driver adds
`id_slot`.

**The rule that makes it safe: never name a busy slot.** A turn whose slot
is busy, and a new conversation when no slot is idle, wait in the driver;
the engine would have queued them anyway. What it must not get is a request
pinned to a busy slot.

**What the engine needs.** `--no-cache-idle-slots`, or each new task clears
the idle slots the map points at (upstream #28139); the RAM prompt cache
stays on, because past the slots it holds the overflow (without it, 36%
reused: record §4).

**When.** Only where the pool holds a conversation per slot: pinned slots
keep their histories between turns, which competes with what is in flight.
So a profile setting, **off by default**, its description saying the rule
(context per slot at least as long as the conversations it serves), and the
agent sets the flag and the driver's pinning together. vLLM and MLX need
none of this (vLLM shares prefix blocks across requests; MLX keeps an LRU of
prompt caches).

### CB5. Evictions are visible

A turn that goes back to its replica (an affinity hit) and reuses less than
its previous prompt was **evicted**. The gateway records it beside `hit |
new | moved` (metrics v12), and the Metrics page shows evictions per
backend: "this model needs more context or another replica", where today an
operator sees only a slow model. Steering placement on it was not measured
and is not proposed.

## 4. Not scheduled, with the numbers

- **Prompt-family (prefix-hash) placement.** No better than spread anywhere
  (81.4% / 75.8% / 77.4% against 81.3% / 75.6% / 80.2%), impossible with
  pinned slots, and across users a Claude Code family is one project (~670
  tokens shared between two), so at scale it would help Codex users' first
  turns, once per replica.
- **Rendezvous hashing.** Recomputing a bounded load on every request moves
  conversations when the load shifts (31 moved turns against PC4's 5); it
  pays only with several gateways, Eugene has one per install, and losing
  PC4's table (a gateway restart) cost 0.2 points.
- **Two gateways.** If one is ever built, its affinity table is the problem
  (66-75% against 75-81%), and hashing does not rescue it.

## 5. How it fits PC6 and PC7, and upstream

PC6 (carry client `cache_control` to hosted Claude) is untouched. PC7
(engine cache settings on a profile; admission counts `--cache-ram`) is
where CB4's setting lives, beside `--cache-ram`, `--cache-reuse` and
`--ctx-checkpoints`; with CB3 the agent also reports the pool.

Upstream, for Troy's report (record §1 and §4 have the logs and source
lines): llama-server's similarity slot choice keeps one conversation per
family (known: #22083), `id_slot` is dropped on `/v1/messages` (known:
#28554), an empty pinned slot skips the prompt cache (known: #28139), and
**a request pinned to a busy slot can wedge the server** (not found
upstream; `get_available_slot` runs its cache update on the busy slot;
master `bed0a8566` unchanged; a two-request repro did not reproduce it).

## 6. Calls — Troy's

| # | Call | Recommendation | The trade-off, measured |
|---|---|---|---|
| 1 | Affinity always on, with an off switch only for benchmarking | **Yes** | +13 points over `least_busy` and half the TTFT at 12 at once; without the switch a benchmark repeating one prompt lands on one replica |
| 2 | `spread` as the default for new conversations | **Yes** | Noise on 3 replicas (+0.5), +20 points and TTFT p50 4.00 → 1.05 s on 8, +26 points and 15.0 → 3.0 s in overload. Costs nothing measurable |
| 3 | The token budget, waiting in the gateway, and a pool refusal that does not trip the circuit | **Yes, first** | 0 failed turns against 44 and 109; p99 30.5 → 16.9 s and 84.8 → 19.0 s on 8 replicas. A turn may wait for room instead of failing over cold, which costs the median in overload (2.96 → 4.01 s). On the 8B at 64k with four agents a replica: 158 of 204 turns fail today, 38 with the budget alone (35 of them the circuit). A contract change (the pool on runtime capabilities) and the driver's capacity outcome |
| 4 | llama.cpp slot pinning as a profile setting, off by default | **Yes, off by default** | +3.4 points, TTFT p50 0.71 → 0.48 s where the pool holds a conversation per slot; 1-10 points worse where it does not and in overload; ~4,300 more tokens on each new conversation's first turn; depends on llama-server slot behaviour with two open upstream PRs (#22083, #28992). The safe rule is not optional and gets a test that fails without it |
| 5 | Record evictions and show them per backend | **Yes** | No routing change |
| 6 | Leave prefix placement, rendezvous and multi-gateway unbuilt | **Yes** | Each measured at or below the simpler choice (§4) |

## 7. Slices, once the calls are taken

| Slice | What | Where |
|---|---|---|
| CB3 | the capacity outcome and the circuit (first: it is today's outage); then the pool on runtime capabilities, the budget and the wait | inference-driver (`failures.py`), gateway (`circuit.py`, `routing.py`), `agent.yaml` + agent (`/props`) |
| CB1 | affinity on for every strategy; `conversationAffinity` | gateway (`routing.py`, config, `gateway.yaml` prose) |
| CB2 | `spread` | gateway |
| CB4 | the driver's slot map with the safe rule; the profile setting; the engine flag | `inference-driver.yaml` + driver, agent (PC7) |
| CB5 | `evicted` in metrics v12 and the Metrics page | gateway, ui |

Each ends with a check that fails without it, from
`prompt-cache-measurement.py --experiments concurrent`: CB3 on the 8B shape (no turn refused as
"cooling down", none failed), CB2/CB3 on the
8-replica shape (reuse above 78%, no failed turns), CB4's safe rule on the
24-at-once shape that wedged (no turn reaching the deadline), and their unit
tests sabotage-checked.
