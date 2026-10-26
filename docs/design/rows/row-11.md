# Row 11: one fair queue in the gateway (LD1)

Lane GW, after row 24. It needs row 10 for the knee and row 24 for the shared key bucket. Sources: LD1, CB3, A5.

## 1. What it delivers

- A request over its key's concurrency limit waits instead of getting a 429. Up to 8 may wait per key and person, for up to 60 s. The key still runs at most its limit at once, across every gateway.
- Requests for a busy local runtime wait in the gateway, not in the engine. They leave by band, then person by turns, then arrival, so one person's burst does not hold back another person.
- A request that meets a starting runtime waits for it, up to `swapWaitSeconds`, instead of getting an immediate 503.
- Each refusal names its cause in the door's own words.
- Queue time is kept on every request row and shown on the Metrics page, with how many are waiting on each runtime.
- Workbench's memory learning and tidy pass run in the background band.

## 2. Design

### The queue

New module `fair_queue.py` holds one `FairQueue` per routing table. An entry holds:
- its arrival time (`perf_counter` at the request's start);
- its band, its fairness id and its key (limit and `maxQueuedRequests`);
- the runtimes it may go to: its home replica while affinity holds it, or else the front tier's runtimes, or none for a cloud backend;
- its size (prompt and reserve) and its deadline.

**Band.** The bands are interactive, background and sheddable. The band in effect is the lower of the key's band and the `X-Eugene-Band` header. A header asking for a higher band is ignored, and the row records the band used.

**Band from a person's group (LD-C4, Troy 2026-10-21).** The operator gives a permission group a queue band (`PermissionGroup.queueBand`, new, default interactive). When the root verified a person, `check` returns the highest band among that person's groups, and that band replaces the key's band. The header can still only lower it. This is part 11e, after 11a-11d.

**Fairness id (LD-C3).**
- `person:<personId>` when the root verified a person. Workbench sends `X-Eugene-Person-Token` with its app key, and `check` returns `personId`.
- Otherwise `key:<id>`, or `session:<sub>` for an operator session, or `anonymous`.
- Open WebUI sends no person token, so its users share one id.

**Order (LD-C3, Troy 2026-10-21).** By band. Within a band, by arrival: first come, first served. A burst from one person cannot take every slot, because condition (a) below holds each key to its limit.

**When an entry may leave.** Two conditions must both hold:
- (a) its key holds fewer leases on this gateway than its limit;
- (b) one of its runtimes has a free slot (counted only when the agent reports `parallelSlots`) and room in its pool (`PoolLedger.fits`, only when it reports `contextPoolTokens`).

An entry with no runtimes needs only (a).

**No overtaking on a runtime.** The first entry in order that waits on runtime R, with room under its key, claims R. If that entry does not fit R's pool, nothing after it leaves on R. An entry blocked by its key claims nothing, so a key at its limit never holds back other keys.

**Dispatch.**
- It runs when an attempt ends, a lease is released, a runtime becomes ready or an entry arrives. A 1 s tick also runs it for keys the root refused. Each run is one linear pass over the queue.
- At dispatch, the queue reserves the slot and the pool tokens. Then the request acquires its lease.
- A root 429 with reason `concurrency` means another gateway holds the key's leases. The queue frees what it reserved, keeps the entry's place, and tries again at the next local release or after 1 s.
- Any other refusal ends the request.
- If the client hangs up or the deadline passes, the entry is removed. Nothing was acquired, so nothing is released.

**Bounds.**
- At most `maxQueuedRequests` wait per key and fairness id. It is counted per person because Workbench's one app key serves everyone.
- At most `queueMaxRequests` wait in the gateway. When it is full, an arrival whose band is higher than the lowest waiting band takes the place of that band's newest entry, which is refused as set aside. Otherwise the arrival is refused.

**TTL.** After `queueWaitSeconds`, a request moves to its slot's next tier if it has one (TIER-SPILL, §7). Otherwise it is refused.

### Admission moves to dispatch

- `ClientRequest.authorize` sends `check`, which takes no lease and returns the limits, band and person. `acquire` happens at dispatch.
- A wake starts only when the key has room on this gateway, so a key at its limit cannot wake or evict runtimes.
- Chat doors wait in `TieredClient._admit`. Other doors with a model (embeddings, rerank, audio, images, moderations, video) wait in the same queue inside `authorize`, with no runtimes.
- The cost is one more round trip to the root per request, a few milliseconds on a LAN.

### WAKE

`lifecycle.py` is row 13's, so it is not edited. When `wake` is not ok and `resolution.waking()` is not empty, `_prepare` in `routes/inference.py` waits on one shared poll per runtime: `table.refresh()` each second, until the runtime is ready or crashed, or `swapWaitSeconds` passes. The request then joins the queue with its original arrival time.

### CB-C

- `TurnBudget.admit` hands its wait to the queue. `PoolLedger.changed`, which wakes every waiter, is removed.
- A turn reserves its prompt plus the lower of `max_tokens` and its conversation's p95 answer over the last 16 answers. A new conversation reserves 4,096 in place of the p95.
- `ConversationSizes` keeps those answer lengths. The 10% spare stays.

### Contracts

- `client-keys.yaml`, `ClientKeyLimits`:
  - `band`: interactive, background or sheddable, default interactive.
  - `maxQueuedRequests`: 0 to 64, default 8. 0 refuses at once, as today.
  - Neither is in the policy digest, so changing them never cuts a running request.
- `control.yaml` and `agent.yaml`:
  - An admission 429 carries `X-Eugene-Refusal-Reason: concurrency|rate`. Today the agent's forward (`client_key_registry.py`) copies only `Retry-After`, so it must also pass this header on. The agent's standalone mirror sets it too.
  - `check` with a model also applies `allowedModels`.
- `gateway.yaml`:
  - an `X-Eugene-Band` request header;
  - `MetricsGroup.queuedMs`;
  - `MetricsSummary.refused` (by reason) and `MetricsSummary.queue` (per runtime: waiting by band, running, slots);
  - `queuedMs`, `band` and `refusal` on request rows.
- Gateway config: `queueWaitSeconds` (default 60, 5-600) and `queueMaxRequests` (default 256, 16-4,096). `swapWaitSeconds` also covers a runtime that is starting.

### Refusals

| Cause | `code` | OpenAI, Responses | Anthropic | Words |
|---|---|---|---|---|
| Key's line full | `key_queue_full` | 429, Retry-After 5 | `rate_limit_error` | "This key has 2 running and 8 waiting for you, its most. Retry when one finishes." |
| Queue full | `queue_full` | 503, Retry-After 5 | `overloaded_error` | "Eugene has 256 requests waiting, its most. Retry in a few seconds." |
| Set aside | `set_aside` | 503, Retry-After 10 | `overloaded_error` | "Set aside for a more urgent request. Retry later." |
| Waited for the key | `key_queue_timeout` | 429, Retry-After 5 | `rate_limit_error` | "Waited 60 s for this key's turn (2 at once). Retry, or raise the key's limit." |
| Waited for room | `queue_timeout` | 503, Retry-After 10 | `overloaded_error` | "Waited 60 s for room on qwen3-8b on tower, 14 ahead. Retry shortly." |
| Still starting | `still_starting` | 503, Retry-After 10 | `overloaded_error` | "qwen3-8b on tower is still starting after 120 s. Retry shortly." |
| No runtime | existing | 503 | `overloaded_error` | `_not_ready`'s words |
| Shutting down | `shutting_down` | 503, Retry-After 5 | `overloaded_error` | "Eugene's gateway is restarting. Retry in a few seconds." |
| Rate | `rate_limited` | 429 | `rate_limit_error` | "This key's 60 requests a minute are used. Retry in 12 s." |

- A stream whose head is already sent gets the same type and words in the door's error frame (`response.failed` on Responses), with the retry time in the words.
- On shutdown, `FairQueue.close()` refuses every waiter. Row 13 adds the drain.

### Metrics, UI, Workbench

- The store moves from v13 to v14 in place, adding the columns `queued_ms`, `band` and `refusal`. A queue refusal writes a row with outcome `refused`.
- Names for row 12: `eugene_queue_waiting{runtime,band}`, `eugene_queue_wait_seconds{band,outcome}` and `eugene_queue_refused_total{reason,band}`; in traces, `gen_ai.latency.time_in_queue`.
- The key limits editor gains "Priority: Interactive / Background / Dropped first when busy" and "Requests that may wait: 8 (0 refuses at once)".
- `app/metrics/page.tsx` shows "Waited in line" (p50 and p95), lines such as "3 waiting for qwen3-8b on tower", and "Refused: 4 queue full, 1 waited too long". The new settings render from the config schema.
- Workbench's `memory_learn.py` and `memory_tidy.py` call `hub.complete(..., band="background")`. A refusal means the work is tried at the next pass.

**Defaults.** None deletes data or exposes a secret. Two change behaviour:
- Requests past a runtime's reported slots wait in the gateway, not in llama-server.
- A wait for room in the pool ends at 60 s with the next tier or a refusal. Today it is sent to the engine anyway after 120 s.

## 3. Repositories and codegen

specs, control, agent, gateway, ui and workbench (add workbench to the row). Regenerate control, agent, gateway and ui for the key and admission contracts. Regenerate gateway and ui for `gateway.yaml`.

## 4. Tests that fail before

These are in gateway `tests/test_fair_queue.py`:
- **`test_over_the_concurrency_limit_waits_instead_of_429`.** A key with limit 2 sends 3 requests at once to a fake driver that holds each for 0.3 s. All three return 200, the third has `queued_ms ≥ 250`, and the driver never sees more than 2. Today the third gets a 429.
- **`test_one_persons_burst_does_not_hold_back_another`.**
  - One runtime has 2 slots. The fake driver serves 2 at a time in arrival order, as llama-server does, and takes a fixed 0.2 s per request.
  - Persons A and B share one app key (limit 64, queue 64), each with their own person token.
  - A sends 51 requests at once, and B sends 1 request 50 ms later.
  - The bound: B waits no more than one service time plus 100 ms (≤ 300 ms), and all 51 of A's requests finish within the TTL. Today B waits about 5 s.
- Also:
  - `test_background_waits_for_interactive`
  - `test_a_header_cannot_raise_the_band`
  - `test_a_key_at_its_limit_does_not_block_another_key`
  - `test_a_big_turn_is_not_overtaken_on_its_runtime`
  - `test_ttl_moves_to_the_next_tier_then_refuses`
  - `test_cancel_while_waiting_leaks_nothing`
  - `test_a_starting_runtime_is_waited_for`: today this is an immediate 503.

Rewrite `test_pool_budget.py::test_the_wait_is_bounded_then_the_usual_order_runs`. In control, add `test_concurrency_refusal_names_its_reason` and `test_band_change_does_not_cut_a_renewal`.

## 5. Acceptance (CI, Linux, about 5 min)

**`specs/scripts/ld1-fair-queue-acceptance.py`** starts:
- a real control root, one enrolled agent, two gateways and a real inference driver;
- a stand-in llama-server: an executable Python script that answers `--version`, `--help`, `/health` and `/props` (2 slots), streams each answer in a fixed 2 s, queues anything past 2 in arrival order, and counts concurrency. The real agent launches it as a `llama_cpp` runtime with `startOnDemand`.

Every process gets an OS-assigned loopback port (never 8079-8083) and a temporary folder, with `EUGENE_PLEXUS_*` cleared.

**Checks:**
1. A key with limit 2 sends 10 requests at once. All return 200, the stand-in sees at most 2 at a time, and the rows carry `queued_ms`.
2. The 11th request gets `key_queue_full` with Retry-After.
3. Key A, with its limit raised, sends 51 requests, and key B sends 1 request 0.5 s later. B's time to first token is ≤ 3 s; today it is about 50 s.
4. A background key waits behind interactive requests, and its `X-Eugene-Band: interactive` is ignored.
5. With the TTL set to 5 s, a request gets `queue_timeout` on both the OpenAI and Anthropic doors, streamed and not streamed.
6. Four requests that meet a starting runtime are all served, with no 503.
7. Two gateways share one key with limit 2. The stand-in never sees more than 2, and B's waiter leaves when A releases.
8. A client that disconnects while waiting frees its place at once.
9. A gateway stopped with waiters refuses them `shutting_down` and never hangs.
10. A v13 metrics store migrates.

**Not in CI.** On Amish_Station:
- the CB run, `prompt-cache-measurement.py --experiments concurrent`, with a real llama-server: reuse within noise of CB3's record, and no failed turns;
- row 10's sweep.

**The reviewer should attack:**
- starvation, through pool claims or under constant interactive load;
- raising a band through a header, a person token or an app key;
- lease leaks from a lost acquire or a cancel during dispatch;
- two dispatches on one slot during the acquire round trip;
- a key at its limit forcing wakes or evictions;
- maps that grow without bound;
- over-admission across gateways;
- the wrong error type after a stream's head is sent;
- an answer that outruns its CB-C reserve.

## 6. Do not change

Files owned by other lanes:
- gateway `lifecycle.py` and `routes/admin.py` (ENG 13), `affinity.py` (ENG 15, 44) and `decisions.py` (OPS 1);
- control `person_access.py` and `permissions.py` (TRUST);
- agent `apps.py` and `client_doors.py` (AG2), and `admission.py` (ENG 9; engine admission);
- ui `GatewayOperations.tsx` and `gatewayDashboard.ts` (WEB 38), `settingsTopics.ts` (WEB 33), and `ConfigField.tsx` and `configValue.ts` (WEB 62);
- workbench `store.py`, `context.py` and `tools.py`;
- every `scripts/codegen.py`.

Shared files:
- `routing.py` (TRUST 37, LIB 61): keep edits to `pick` and `_budget_for`;
- `metrics.py` (WEB 38): add columns only.

## 7. Size, risks, split

L, about 5-6 days. **Split it** on one branch, `ld1`. Each step must pass its changed-file tests:
- **11a (S):** contract fields, control and the agent mirror, then regenerate.
- **11b (M):** `FairQueue` with the key gate for every door, check then acquire at dispatch, the refusals, and metrics v14.
- **11c (M):** the runtime gate in place of CB3's wait, WAKE, CB-C, TTL and spill, and shutdown.
- **11d (S):** bands end to end: the header, Workbench, the UI editor and the Metrics page.

After the last step, one acceptance run and one adversarial review come before the merge.

**Risks:**
- This is the gateway's hot path.
- A wrong `parallelSlots` throttles a runtime. An engine that reports none is not slot-gated.
- A CB-C reserve can be outrun. The 10% spare absorbs some of it, and the CB run checks it.
- Fairness is per gateway. The root enforces only the limits.

**Calls only Troy can make:**
- **TIER-SPILL.** At the TTL, should a request move to its next tier, which may be a paid cloud account? Recommended: yes. The operator set that tier as the fallback, and the Metrics page counts each spill. Today such a request goes to the busy engine.
- **Keys a person holds.** LD-C3 names them, but a key has no owner. Recommended: add an owner with row 37 or 40. Until then, a key with no verified person gets one share.

## Calls answered by Troy (2026-10-21)

- **WAKE: wait in the queue.** A request for a runtime that is starting waits in the one queue.
- **LD-C3 and LD-C4: priority from groups, then first come, first served.** See "Order" and "Band from a person's group" in section 2.
- **KEY-OWNER: Choice 1.** A key with no owner is its own fairness id until rows 37 or 40 add an owner.
- **TIER-SPILL: Choice 1, built as rules.** Tier moves are a list of rules, each a condition and an action, stored as data. The first and only rule today is "waited more than 60 seconds: move to the next tier". Administrators get more conditions later. The Metrics page counts every move.
- **CB-C2: Choice 3.** Each request holds back the length of its conversation's recent long answers (95 of 100 are shorter), or 4,096 tokens for a new conversation, but never less than a floor the owner sets (a gateway setting, default 1,024). The Metrics page counts each answer that ran out of room.
- **GROUP-POLICY: Choice 2.** All group policies come first, in row 70. This row reads the queue band from row 70's policies; part 11e is dropped from this row, and row 11 needs row 70.

## What building found (2026-10-26)

- **"First come, first served" and the burst test disagree; built: persons in turns.** §2 "Order" says arrival order within a band, but §1, the issue and §4's `test_one_persons_burst_does_not_hold_back_another` need B served at the next free slot while A's 51 wait under one app key (limit 64), and condition (a) cannot do that: A's key has room. Built as llm-d does and LD-C3 words it ("one person running three tools gets one share"): within a band the flow served longest ago goes first, and each flow is first come, first served. Measured: B waited 5.48 s on main and at most 300 ms here.
- **Every door has the key gate.** Embeddings, rerank, audio, images, moderations, video, decisions and web search wait for their key's turn in `authorize`; chat waits in `TieredClient._admit`. A wake takes the key's turn first, so a key at its limit cannot start or evict a runtime.
- **A per-key bound applies only to a key with limits.** A legacy key, an operator session and an install without sign-in are bounded by `queueMaxRequests` alone, so nothing that runs today is refused for a bound it never had. A key with `maxQueuedRequests: 0` is refused at once both when it is at its limit here and when the root says another gateway holds its leases ("0 refuses at once, as today").
- **The answer's room is capped by `max_tokens`, then the floor applies to the estimate.** Holding a 1,024 floor for a request that may write 10 tokens would starve its runtime, so the room is `min(max_tokens, max(floor, p95 or 4,096))`.
- **A stop must close the line when the signal arrives.** uvicorn waits for every request in flight, waiters included, before the lifespan ends, so closing only there would hang a stop for up to `queueWaitSeconds`. The gateway's entrypoint runs uvicorn's server with a `handle_exit` that closes the queue first; the lifespan closes it too. `routes/admin.py`'s restart (`os._exit`) is row 13's to drain.
- **A new agent must not send defaults a root a release behind refuses.** The specs integration's C6 job (agent from this branch, root at its pin) failed an app install: the agent forwarded the whole `ClientKeyCreateRequest`, with `band: null` and `maxQueuedRequests: 8`, and the older root's models forbid unknown fields. The agent now forwards only what the caller set, and the console sends a band and a bound only when they are not the defaults. Changing them still needs the root updated first.
- **`check` before `acquire` is visible in admission logs.** A chat is now check, acquire, renew, release (one more round trip, as §2 said); the gateway tests that pinned the old order were updated.
- **The Metrics summary's window ends at the second before `until`.** Rows recorded in the current second are not in `GET /v1/metrics` until it passes (existing behaviour, `_iso` truncates `until`). Tests that read the summary at once pass an explicit `until`.
- **Root refusal retries need their own timer.** `loop.call_later` runs on the loop's clock, so the pass it starts can come a tick before `perf_counter` reaches the retry time; each pass re-arms the timer for what is still held back (found as a 1-in-4 hang in the two-gateway test).
- **Not built here:** the Metrics page's live line reads this gateway only (fairness is per gateway, as §7 says); the engine-side check (`prompt-cache-measurement.py --experiments concurrent`) and row 10's sweep stay on Amish_Station.
