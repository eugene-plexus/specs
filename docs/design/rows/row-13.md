# Row 13: checked engine updates, and the drain they need (DI1)

Lane ENG, after row 11, whose `FairQueue.close()` and `shutting_down` refusal it uses. Sources: DI1 and DI-C3 (`deepinfer-lessons.md`), `m1-engine-acquisition.md` §3-§4, memory `project_open_threads`. The roadmap says rows 15 and 40 reuse the drain. It is rows **15 and 44**: fix that line.

## 1. What it delivers

- **A new build runs only after it passes a check.** Runtimes start from the build *in use*, not the newest on disk, so there is no silent mixed fleet.
- **The check measures the new build against the one in use,** on each model this machine serves: speed with llama-bench, and the same answers with the profile builder's KL and same-top-token instrument.
- **A pass restarts the runtimes on the new build,** each drained first, so no answer is cut. **A failure keeps the old build** and names the measured cause.
- **A machine with one replica asks first** (DI-C3): "b11800: 3% faster, same answers. Switch now, or when idle?"
- **Update all updates machines one at a time.** A model's replicas on other machines keep serving.
- **A gateway restart finishes the answers in flight** (up to 120 s). Today `routes/admin.py` exits after 500 ms, and the agent kills the gateway after 5 s.

## 2. Design

### 2.1 The runtime drain (agent and gateway; reused by rows 15 and 44)

**The agent holds the drain. Every gateway obeys it.**

1. **Start.** `POST /v1/runtimes/{name}/drain` takes the operator, the agent's own rollout, or a gateway token, as `stop` does.
2. **Leave routing.** The runtime reports `status: draining`. Gateways route only to `ready` runtimes, so older gateways obey too. No agent calls a gateway, so no new token grant is needed.
3. **Report.** Each gateway posts `.../drain/report {running}`, its own in-flight count for the runtime, on every refresh. While a drain is open, it refreshes every 2 s.
4. **Drained.** The agent waits on its real subject: every gateway issuer that read `/v1/runtimes` in the last 60 s must report `running: 0` after the drain began. If no gateway read it, it is drained at once. A reader silent for 60 s is dropped, and the message names it.
5. **Grace.** After `graceSeconds` the drain is `cut`, and `then` runs anyway: "2 answers were cut at the 120 s limit."
6. **Then.** `then: restart | stop | hold`. `DELETE` cancels the drain.

`when: idle` keeps the runtime `ready` in state `waiting_idle`. The gateway's idle pass (`lifecycle.py`) reports `idleSeconds`. Once the runtime has been idle long enough with nothing in flight, the agent starts the drain.

In the gateway, a runtime draining with `then: restart` counts as coming up. Row 11's queue keeps waiting a request whose only runtime it is, up to `swapWaitSeconds`. Affinity already moves a conversation whose home runtime is ineligible (`MOVED`). `switch`'s in-flight wait becomes the shared `drain.wait_inflight()`.

**Hooks for later rows.** The agent's `RuntimeDrains.before_stop` is where row 15 saves slots. The gateway's `DrainReporter.on_draining`, which runs before it reports 0, is where row 44 moves conversations for `maintenance`.

### 2.2 The gateway's own drain

`POST /v1/admin/restart` and the new `POST /v1/admin/drain` start `GatewayDrain`:

1. New inference requests get row 11's `shutting_down` (503, Retry-After 5).
2. `FairQueue.close()` refuses the waiters.
3. Answers in flight finish, for up to `shutdownDrainSeconds`.
4. A stream still open at that limit gets the door's error frame: "Cut: Eugene's gateway restarted after waiting 120 s for this answer. Ask again." Its row's outcome is `cut`.
5. The lifespan closes normally, and the process exits 0.

Config, health and admin routes keep answering throughout.

`/v1/admin/drain` accepts an operator session, **or a service token from this machine's own agent** (`is_local_service`, `sub: agent`). This is a new acceptance, and the reviewer's first target.

`supervisor.py` drains the gateway before every stop. It polls `GET /v1/admin/drain`, and kills only after `shutdownDrainSeconds + 5`. This works where CTRL_BREAK cannot be sent, which includes the Windows service. When the agent itself stops, it waits at most 20 s, because the service manager waits no longer.

### 2.3 The build in use (`engines/acquisition.py`)

- **The build in use.** `<engine>/in-use.json` names it, and `ManagedStore.current()` returns it. With no file, the newest build is used, as today.
- **Installs stage.** An install only stages its build. It switches at once only when no build is in use.
- **Prune** keeps the build in use, the previous build in use, and one staged build.
- **Rollback** is a rollout to the retained build, with no download.

### 2.4 The check and the rollout (new `engine_rollout.py`)

The rollout's state is saved: `installing → checking → asking → switching → done | kept | failed | cancelled`.

1. **What is checked:** this node's llama.cpp runtimes on the managed build (not those with their own `binary`), at most 4 models.
2. **Stopping them:** a drain with `reason: check` and `then: stop`, recorded as `stopReason: measurement`. The benchmark job's one-job-per-node rule applies.
   - If every model has another ready replica, the check starts now.
   - Otherwise it waits for 600 s of idle. The page offers Check now.
3. **Measuring each model,** with the tool finder and KL parser imported from `profile_builds.py`:
   - speed: llama-bench pp512 and tg128, 3 repetitions, on both builds;
   - answers: the old build writes the KL base on the bundled text (4,096 tokens × 2 chunks). The new build reads it.
4. **The pass rule:** both speeds within 5% of the old build's or better, and `sameTopTokenPercent − standardError ≥ 99.0`.
5. **The outcome:**
   - **Pass, with replicas:** the pointer moves. Each runtime starts on the new build, one at a time, and must be ready within 10 min.
   - **Pass, one replica:** the runtimes start on the old build, then the page asks. Switch now, or when idle, drains with `then: restart`.
   - **Fail:** the runtimes start on the old build. The state is `kept`.
6. **A start failure on the new build** moves the pointer back. Each runtime already moved restarts on the old build, drained.

### Contracts

```yaml
# agent.yaml
RuntimeStatus: [..., draining]
Runtime.drain: RuntimeDrain
RuntimeDrainRequest:
  reason: [update, check, maintenance, operator]
  when: {enum: [now, idle], default: now}
  idleSeconds: {minimum: 60, maximum: 86400, default: 600}
  graceSeconds: {minimum: 0, maximum: 900, default: 120}
  then: {enum: [restart, stop, hold], default: hold}
RuntimeDrain: request fields + state [waiting_idle, draining, drained, cut, cancelled],
  startedAt, deadline, running, message
/v1/runtimes/{name}/drain: post drainRuntime, delete cancelRuntimeDrain
/v1/runtimes/{name}/drain/report: post reportRuntimeDrain   # gateway token; {running, idleSeconds}
ManagedEngine: version is the build in use; + stagedVersion
/v1/engines/{engine}/rollout: post {version, switch: ask|auto}, get, delete
/v1/engines/{engine}/rollout/answer: post {choice: switch_now|switch_idle|keep}
EngineRollout: {version, from, state, check: {models: [EngineCheckModel], passes},
  runtimes: [{name, state, message}], message}
EngineCheckModel: {model, promptTps {old,new}, generationTps {old,new},
  sameTopTokenPercent, standardError, meanKld, passes, reason}
UpdateAllItemKind: [node, app, engine]
# gateway.yaml
/v1/admin/drain: post drainGateway, get getGatewayDrain
GatewayDrain: {state: [serving, draining, exiting], running, startedAt, deadline}
config shutdownDrainSeconds: {default: 120, minimum: 0, maximum: 900}
```

### Failures and UI text

- "b11800 is 12% slower at generating on Qwen3.6-27B here; kept b11719."
- "b11800 answers differently on qwen3-8b: 97.1% same next token, 99% needed. Kept b11719."
- "b11800 cannot read b11719's comparison file: {tail}. Switch anyway, or keep b11719." This is the expert override.
- "b11800 did not start qwen3-8b: exit 3221225477. Kept b11719."
- Engines panel: "llama.cpp b11719 in use · b11800 checking, model 2 of 3", with "Use b11719 again" after a switch.
- Runtime row: "Draining for an update · 2 answers running · 95 s left".
- `lib/issues.ts`, during a rollout: "Updating: 1 of 3 runtimes on b11800".

**Defaults.** Nothing deletes user data or exposes private data. These change behaviour:
- installs stage instead of switching;
- both grace periods are 120 s;
- a failed build stays on disk (about 0.7 GB) until the next install.

## 3. Repositories and codegen

- **specs:** `agent.yaml`, `gateway.yaml`, the acceptance script, the roadmap fix.
- **agent:** `engines/acquisition.py`, `runtimes.py`, `routes/runtimes.py`, `supervisor.py`, `update_all.py`, and new `runtime_drain.py` and `engine_rollout.py`.
- **gateway:** `routes/admin.py`, `lifecycle.py`, `app.py`, `dependencies.py`, and new `drain.py`. In `routing.py`, only `_RuntimeFacts`, `ineligible_reason`, `waking` and the refresh interval.
- **ui:** `app/inference/page.tsx`, `lib/issues.ts`, the runtime status words.

Regenerate agent and ui from `agent.yaml`, and gateway and ui from `gateway.yaml`. Control generates `agent_models.py` but uses none of it, so it needs no re-pin. The gateway reads runtimes as raw JSON.

## 4. Tests that fail before

- **gateway `test_drain.py::test_restart_finishes_open_streams`.** Three 2-second streams are open when a restart arrives. All three finish whole, a new request gets 503 `shutting_down`, and then the process exits. Today the streams are cut at 500 ms.
- **agent `test_runtime_drain.py::test_drain_waits_for_the_gateway_report`.** `then: restart` runs only after the gateway that read the runtime reports 0.
- **agent `test_engine_rollout.py::test_install_does_not_change_the_build_in_use`.**
- **Also:** `test_failed_check_keeps_old_build`, `test_start_failure_rolls_back`, `test_one_replica_asks`, `test_cut_at_grace_names_count`, `test_rollout_resumes_after_restart`, `test_only_local_agent_token_may_drain_gateway`, `test_gateway_stop_drains_first`.

## 5. Acceptance (CI, Linux, about 6 min)

`specs/scripts/row13-engine-update-acceptance.py` runs on OS-assigned ports (never 8079-8083), with `EUGENE_PLEXUS_*` cleared. It starts:
- a control root;
- two agents;
- one gateway;
- row 11's stand-in llama-server, which here reports its build;
- stand-ins for llama-bench and llama-perplexity, with set speeds and agreement.

It checks:
1. Two replicas on two machines, then Update all: every stream open during a drain finishes.
2. A build 12% slower is kept.
3. A build that will not start is rolled back.
4. A machine with one replica asks, and Switch when idle runs after the idle time.
5. A gateway restart finishes its streams.
6. An agent stop drains its gateway.

**The reviewer should attack:**
- the local-agent token on `/v1/admin/drain`;
- a drain that never ends;
- the pointer left on a failed build after a crash;
- `prune` deleting the build in use;
- a measurement stop racing a wake;
- reports from tokens without the `gateway` grant.

## 6. Do not change

- **agent:**
  - `admission.py`, `engines/llama_cpp.py`, `engines/vllm.py` (rows 9, 15, 18, 20);
  - `benchmarks.py` (row 10: import only);
  - `apps.py`, `client_doors.py` (AG2).
- **gateway:**
  - `affinity.py` (rows 14, 15, 44);
  - `budget.py`, `admission.py`, `client_keys.py` (rows 11, 24, 40);
  - `decisions.py`, `metrics.py` (rows 1, 38: outcome values only);
  - in `routing.py`, row 11's `pick` and `_budget_for`.
- **ui:** `GatewayOperations.tsx`, `gatewayDashboard.ts`, `settingsTopics.ts`, `ConfigField.tsx`, `configValue.ts`.
- **every repository:** `scripts/codegen.py`.

## 7. Size, risks, split, calls

**L, about 6 days,** on one branch, `r13-engine-update`. Each step passes its changed-file tests:
- **13a (S-M):** the gateway drain and the supervisor.
- **13b (M):** the runtime drain and idle.
- **13c (M-L):** the build in use, the check, the rollout, the UI.
- **13d (S):** Update all with engines.

Then one acceptance run, and one review of the token change.

**Risks:**
- The KL base file may change format between builds. The check then reads "cannot compare" and offers Switch anyway.
- A one-GPU machine is offline for 2-4 minutes per model during the check. That is why the check waits for idle.
- Answers on a runtime that crashes are still lost.

**Calls only Troy can make:**
- **DI-C3:** ask before switching on a machine with one replica. Built as recommended.
- **The check's thresholds.** Recommended: at most 5% slower, and at least 99.0% same top token. Kernels change between builds, so the answers are never bit-exact.
- **Drain grace.** Recommended: cut after 120 s, editable per drain and in the gateway config, rather than wait without a limit. An update must end.

## Calls answered by Troy (2026-10-21)

- **DI-C3: one replica at a time, when the rest can carry the load.** With two or more replicas, Eugene updates one replica at a time, and only while the others can carry the current demand (measured from the queue and the slots in use). Otherwise it waits. The one-replica case is asked again (DI-C3b). Default until he answers: switch when the runtime has been idle for 5 minutes.
- **R13-CHECK: the check is not a gate on numbers.** A new build may carry a security fix or a critical bug fix. Speed and agreement are measured and shown, and never block. Asked again (R13-CHECK-2) for one case. Default until he answers: a build that cannot start or cannot answer with a model is not used for that model, and the page says what failed.
- **R13-DRAIN: Choice 1, with a count.** Wait up to 120 seconds. The console shows how many answers the restart waits for.
