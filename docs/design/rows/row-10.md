# Row 10: Measure people served at a speed (DI3, LD5)

Lane OPS, after row 2 (its acceptance runs on row 2's harness). Risk: low. Size: M. Read later by rows 11, 13, 14 and 69 and the speed nudge (LS9m). Calls: MEASURE-WHERE, MEASURE-KEY, MEASURE-KNEE, MEASURE-DRAFT, MEASURE-REPLICAS.

## 1. What the row delivers

- "Measure people served" on a running runtime in the console. It sends agent-shaped work through the gateway to that runtime, from 1 person up, and stops past the knee.
- One sentence: "12 people at 20 tok/s each, first token in 1.4 s (agent sessions)." The levels below are the curve: "or 4 at 60".
- Each result is kept on the runtime's node with its provenance, and reads as out of date when any of it changes.

## 2. The design

### Where it runs (call MEASURE-WHERE)

An agent job, like the profile benchmark: the console starts it through the node proxy, and the task tray finds it. `scripts/serving-sweep.py` calls the same endpoints from a terminal.

### The load (`agent/serving_sweep.py`, new)

A "person" is one top-level session. `workload`:
- **`agents`** (default, LD5's shape):
  - The next prompt is the last prompt, the last answer and new text (lognormal, median 632 tokens). 4% of turns first cut the history somewhere in its last 30%, so 96% of turns reuse at least 90%.
  - Answers: lognormal, median 317 tokens, sent as `max_tokens`; the tokens made are recorded.
  - Pauses: inverse CDF on log time through p50 2 s, p90 24 s, p99 684 s, cut at 1,800 s.
  - One turn in 20 starts sub-agents, size through median 7 and p90 51, cut at 64. Each is a fresh 3-8 turn session; the person waits for all. The rate is an assumption: the study gives sizes, not frequency.
  - Warm start: each person begins at a random turn of a session (median 107 turns, p90 354), its history sent once as an uncounted warm-up. A prompt that would pass 90% of the per-slot context starts again from the system text, as a client compacts.
- **`chat`**: questions of median 60 tokens, answers of 400, pauses of 40 s.
- **`streams`**: closed loop, no pause, no growth; the classic 1..N streams, comparable with published numbers.

Text is the profile builder's bundled corpus. All people share one 2,000-token system text; a seed line per person follows it. Runs are seeded.

### A level

- People: 1, 2, 4, 8, … up to `maxPeople` (default 4 × the runtime's `parallelSlots`, at most 256).
- `windowSeconds`: default 300 (`agents`, `chat`), 120 (`streams`); `full: true` runs 3,600. Requests in flight at the end finish and count.
- The gateway's OpenAI door, streamed with `stream_options.include_usage`, through one `httpx.AsyncClient` built by `_http.py`.
- Per request, client-side: time to first content token; inter-token latency; tok/s after the first token; prompt and cached tokens; `X-Eugene-Plexus-Waited-Ms`; `X-Eugene-Plexus-Runtime`.
- Per level: streams in flight (mean, peak), requests, errors by cause, TTFT p50/p90, inter-token p50/p90, tok/s each p50/p10, total tok/s, prompt reuse, gateway wait p50, foreign requests, and GPU watts when host history has them.
- **Foreign requests:** the engine's request counter minus the job's (llama-server `/metrics`, which row 12 turns on always; vLLM's). Without a counter: "others' use: unknown".

### The knee (call MEASURE-KNEE)

The last level before TTFT p50 passes 2 × level 1's and 1 s, or tok/s each p50 falls below two thirds of level 1's. The run stops one level past the knee, at 5% errors, or at TTFT p50 above 60 s.

Sentences (`ui/src/lib/servingSentence.ts`, pure):
- "12 people at 20 tok/s each, first token in 1.4 s (agent sessions)."
- "At least 32 people at 18 tok/s each. The limit is above 32."
- "One person at 45 tok/s. A second person slows both."

### One runtime, never the cloud

- Start mints a client key with the caller's own credential (`mint_client_key`, as app installs do): `localOnly`, `allowedModels: [alias]`, concurrency 64, 10,000 a minute, `ttlDays: 1`, name "Measurement <runtime> <date>". It stays in the agent's memory. It cannot reach a cloud tier or a fallback model.
- `cancel` stops a run and revokes its key with the caller's credential; on a finished run it only revokes. The console calls it on a finished run whose `keyLive` is true (call MEASURE-KEY).
- The preflight reads the gateway's routing view with the caller's credential and lists other ready replicas of the alias. The console asks to stop them, stops them through their agents, and starts them again after (call MEASURE-REPLICAS).
- An answer from another runtime stops the run: "A request was answered by qwen3-8b on studio, not tower. The run stopped."

### Drafting (call MEASURE-DRAFT)

The record holds the drafting type, draft model and acceptance; the console puts a drafting-on and a drafting-off record of one model and machine side by side. An automatic off pass needs a launch override in `runtimes.py` (row 13's), so it is later, unless llama-server takes `speculative.n_max: 0` per request through the gateway. The builder checks that first.

### Provenance

`provenanceKey` is a sha256 of the engine, build and binary hash, launch argv, model path, size and mtime, GPUs, driver, CPU, RAM, and agent and gateway commits. On read the agent sets `current` and `staleBecause` ("the engine changed: b11301 → b11420"). It keeps the newest 20 runs per node and the newest completed run per runtime.

### Contract (`agent.yaml`)

```yaml
/v1/serving-measurements:              # get: list (?runtime=); post: start, 202
/v1/serving-measurements/preflight:    # post: otherReplicas, otherRuntimes, problems, estimateSeconds
/v1/serving-measurements/{id}/cancel:  # post: stop, and revoke the key
ServingWorkload: {type: string, enum: [agents, chat, streams]}
ServingMeasurementRequest:   # required: runtime
  {runtime, workload, maxPeople (1-256), windowSeconds (10-3600), full, seed}
ServingLevel: {people, streamsMean, streamsPeak, requests, errors, errorCauses,
  ttftP50Ms, ttftP90Ms, itlP50Ms, itlP90Ms, tokensPerSecondEachP50,
  tokensPerSecondEachP10, tokensPerSecondTotal, promptTokens, cachedTokens,
  waitedP50Ms, foreignRequests, watts}
ServingKnee: {found, people, tokensPerSecondEach, ttftP50Ms}
ServingMeasurement: {id, node, runtime, model, state (BenchmarkState), request,
  startedAt, finishedAt, progress, detail, levels, knee, provenance,
  provenanceKey, current, staleBecause, keyLive, restarts}
```

### Console and failures

- The runtime's row on Inference: the sentence and "Measured 22 Oct", or "Measured before the engine update (b11301 → b11420). Measure again."
- The panel: workload, "up to N people", and "The GPU is busy for about 40 minutes. People using qwen3-8b get slower answers meanwhile."
- Task tray: "8 people: 3 of 5 minutes." Result: the curve, the knee marked, the table.
- Failures: "qwen3-8b on tower is stopped. Start it, then measure." "Stopped at 16 people: 12% of requests failed (the driver said: …)." "Eugene could not make a measurement key: <control's words>."

**Defaults.** Nothing is deleted; no private data is exposed. The run's requests show on the Metrics page under the key "Measurement …".

## 3. Repositories and codegen

- **specs:** `agent.yaml`, `scripts/serving-sweep.py`, `scripts/serving-sweep-acceptance.py`, DI3 and LD5 "what building found".
- **agent:** `serving_sweep.py`, `routes/serving_measurements.py`, `measurement_node.py` (register the manager).
- **ui:** `lib/servingSentence.ts`, `lib/servingMeasurements.ts`, the Inference panel, `lib/tasks.ts`.
- **Codegen:** agent, control, ui; confirm the rest by regenerating and diffing.

## 4. Tests that fail before the change

agent `tests/test_serving_sweep.py`:
- `test_a_two_slot_engine_knees_at_two_people` (in-process stand-in, 2 slots, 20 ms a token, `streams`).
- `test_pauses_hit_the_published_points` (200,000 seeded samples; p50 ±5%, p90 ±10%, p99 ±15%).
- `test_burst_sizes_have_median_7_and_p90_51`, `test_96_percent_of_turns_reuse_90_percent`.
- `test_an_answer_from_another_runtime_stops_the_run`, `test_the_key_is_local_only_and_one_model`, `test_a_changed_engine_build_makes_the_record_stale`.

ui `servingSentence.test.ts`: the three sentences.

## 5. Acceptance

**CI (Linux), `scripts/serving-sweep-acceptance.py`,** on row 2's harness: real control root, agent, gateway and driver; a stand-in llama-server (2 slots, fixed prefill and decode rates, a prefix cache, `/metrics`); a stand-in cloud driver that counts calls. OS-assigned ports, never 8079-8083; `EUGENE_PLEXUS_*` cleared; 10 s windows.
1. `streams` knees at 2 people, at the stand-in's rate ±10%.
2. `agents` gives a rising TTFT curve, a sentence, and reuse above 90% at level 1.
3. A second replica is named by the preflight. The cloud driver counts zero.
4. Another key's request during a level counts as foreign.
5. Cancel stops within 5 s and revokes the key.
6. An agent restart marks the run failed; a changed engine version marks the record stale.

**On Amish_Station, once:** a small model on the 5090, `agents`, short windows; beside it `serving-sweep.py --replay <captured sessions>` with Troy's Claude Code and Codex captures. The knees must be within one level, and the burst rate is set from the captures. Record: `docs/acceptance/serving-sweep-run.md`.

## 6. Do not change

- **gateway:** every file; the run uses existing doors and headers.
- **agent:** `runtimes.py` (ENG 13), `engines/*` (ENG), `admission.py` (ENG 9), `host_probes.py`, `gpu_probe.py` (LIB 43), `apps.py`, `client_doors.py` (AG2), `profile_builds.py`.
- **ui:** `settingsTopics.ts`, `resourceTree.ts` (WEB 33), `ConfigField.tsx` (WEB 62), `gatewayDashboard.ts` (WEB 38).
- **specs:** `prompt-cache-measurement.py` (row 11 runs it); every `scripts/codegen.py`.
- **Shared:** `measurement_node.py`: add the manager only.

## 7. Size, risks, calls

**Size:** M, about 2 days. One branch, `r10-serving-sweep`: **10a (M)** contract, load, job, record; **10b (S)** console; **10c (S)** CI acceptance, the 5090 run, the record.

**Risks:** one Python process times 64 people plus bursts, so the job measures its own loop lag and marks levels above 50 ms; the burst rate is assumed until the replay run; the GPU runs up to an hour, so the estimate is shown before start.

**Calls only Troy can make (recommendation first):**
- **MEASURE-WHERE.** An agent job the console starts (GUI equality), not a specs script only.
- **MEASURE-KEY.** Accept a key that lives up to a day unless the console revokes it. A TTL in minutes needs a client-keys change (row 24).
- **MEASURE-KNEE.** TTFT p50 doubled and over 1 s, or tok/s each down by a third.
- **MEASURE-DRAFT.** Record drafting and compare records now; an automatic off pass after row 13.
- **MEASURE-REPLICAS.** One runtime now, stopping the alias's other replicas with consent; the replica set as one with row 14.

## Calls answered by Troy (2026-10-21)

- **MEASURE-KEY: Choice 1.** The run's key lives at most one day and is revoked when the run ends.
- **MEASURE-KNEE-2: Choice 1.** The run measures the owner's own machine. The thresholds (first word after more than 1 second; speed below two thirds of one person's) are the defaults, and the owner can change both on the run page.
- **MEASURE-REPLICAS: Choice 1.** Measure one copy; ask before stopping the others.
