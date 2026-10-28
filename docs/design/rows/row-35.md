# Row 35: tray: pause models and keep serving

Lane AG2, second in its lane. **High risk: a new way to act on the agent.**
Size M. Repos: specs, agent, ui. Control does not change.

Sources: `windows-comes-back-by-itself.md` §3.5, §6 ("the tray holds
nothing") and §8; agent `tray.py`, `_tray_window.py`, `tokens.py`,
`measurement_node.py`, `node_work.py`; `per-node-token-keys.md` D4 and D5;
`install.ps1` `Grant-ServiceControl`.

## 1. What it delivers

- **Two new tray items.** The menu gains **Pause models (frees the graphics card)** and **Resume models**.
- **Pause stops every model on this machine, and Eugene keeps running.** The console, the gateway, Workbench, cloud accounts and the other machines go on serving.
- **While paused, nothing starts a model here.** A request, Run, a benchmark and a reboot all leave it stopped. A request for a model that only this machine serves is refused, with the cause: "Models on Amish_Station are paused from its tray icon. Resume them there or in Eugene's console."
- **Resume starts again what Pause stopped,** through memory admission, and names each model it could not start.
- **The tray holds no credential.** Windows' own sign-in decides, with the rule that Stop Eugene uses today: an account that may stop the service may pause its models.
- **The console can do the same.** It shows the pause on Machines and Backends, and has Pause and Resume on every OS (GUI equality).

## 2. The design

### Why the tray gets no token

| Option | What a thief gets | Cost |
|---|---|---|
| **A. A named pipe, with the caller's Windows identity** | Nothing to steal. A process of an allowed account on this machine can pause. | Windows-only code |
| B. A local service token, `sub: tray`, `aud: node:<self>`, in a file the person can read | A token that works from any machine that can reach port 8079, until it expires | A token file, its rotation and its revocation |
| C. Let a client key reach pause | Every client key is widened, which R2.4 narrowed | A change to `tokens.py` in every repo |

- **A grants nothing new.** The accounts that A admits can already stop the whole service, which does more than pause.
- **B is allowed but rejected.** A node key may mint any `sub` to its own machine (D4), but B puts a long-lived secret in a user session. R2.6 refused to do that (§6).
- **Recommend A.** The roadmap asks for a narrow credential. The narrowest is none.

### The pipe (agent, new `tray_pipe.py`)

- **Where it runs.** The agent starts it in `app.py`'s lifespan, on Windows only.
- **Its name** is `\\.\pipe\eugene-plexus-agent-<port>`. The port keeps two installs on one machine apart.
- **How it is created.** With `FILE_FLAG_FIRST_PIPE_INSTANCE` and `PIPE_REJECT_REMOTE_CLIENTS`.
- **When the name is taken.** The agent does not serve the pipe. `GET /v1/node` reports `pause.trayChannel: taken`, and the log says: "The tray's channel \\.\pipe\eugene-plexus-agent-8079 is held by another program (process 1234), so the tray cannot pause models."
- **Who may connect (the DACL):**
  - SYSTEM and Administrators;
  - each SID that holds `SERVICE_STOP` in an allow ACE of the agent's own service. The agent reads them with `QueryServiceObjectSecurity`. The installer's `sc sdset` puts the installing account there.
  - On an install without the service, the agent's own account.
- **Each connection is checked again.** The agent calls `ImpersonateNamedPipeClient`, reads the token's user SID, reverts, and compares the SID with the list read now. A grant removed with `sc sdset` takes effect at the next connection.
- **The protocol.** One JSON line in and one out, at most 4 KiB, with a 5-second read timeout. The verbs are `state`, `pause` and `resume`. Any other verb gets `{"ok": false, "error": "unknown verb"}`. One thread serves one connection at a time, and a client that holds the pipe is dropped at the timeout.
- **The tray checks the other end.** `GetNamedPipeServerProcessId` must equal the service's process id from `QueryServiceStatusEx`. If it does not, the tray shows "Eugene's tray channel is held by another program" and sends nothing.

### Pause and Resume (agent, new `pause.py`)

The pipe and the console routes both call these.

**Pause:**

1. Take the launch lock.
2. Cancel a benchmark or settings build that is running. The models it stopped join the pause's list.
3. Stop each running runtime with the new reason `StopReason.paused`.
4. Record `{since, by: tray|console, runtimes}` in `state.py`.

**Effects of a pause:**

- **Answers in progress stop at once.** A person who is starting a game wants the card now. Row 13's drain can add a grace period later.
- **Starts are refused.** `node_work.launch_guard` answers 409 with the sentence in §1. That one guard covers Start, Restart, a gateway wake, Run from the Library, benchmarks and settings builds. The gateway already passes the agent's sentence on to the caller, so the gateway does not change.
- **It survives a restart.** `state.remembered_stops()` includes the paused runtimes, so the supervisor does not start them at boot. `routes/runtimes._compose` reports `stopReason: paused` for them. `runtimes.py` (row 13) does not change.

**Resume:** clear the record, then start the list with `measurement_node.restart_stopped`, through admission and never forced. Each runtime's result is `started`, `refused` (with admission's reason) or `gone`.

**Runtimes that change during a pause:** a runtime declared during a pause stays stopped, because of the guard. A runtime removed during a pause is dropped from the list.

### Contract (`agent.yaml`)

- **`StopReason` gains `paused`:** "Stopped by Pause, from this machine's tray icon or the console. A start, a gateway wake or a Run is refused with 409 until Resume."
- **`NodePause`** is `{since, by: tray|console, runtimes: string[], trayChannel: serving|taken|unavailable}`, at `NodeInfo.pause`. It is absent when the machine is not paused. `trayChannel` is always present on Windows.
- **`POST /v1/node/pause` and `POST /v1/node/resume`** need an operator session (`require_operator_session`). A gateway token, a control token or a client key is refused with 403. Each returns `NodePauseResult {pause, results: [{name, state, detail}]}`. A second pause returns 200 with the existing record.
- **Other machines.** The console reaches a worker by the existing token exchange (D7).

### Tray (`tray.py`, `_tray_window.py`)

`menu_for` stays a pure function, so the tests cover the whole menu:

- Open Eugene
- **Pause models (frees the graphics card):** enabled while the service runs and the models are not paused
- **Resume models:** enabled while paused
- Stop Eugene
- Start Eugene
- Allow commands from Workbench... (job sites only)
- Hide this icon (it is in your Start menu)

**Other text:**

- **Tooltip while paused:** "Eugene is running - models paused".
- **Pipe access denied:** the Pause item reads "Pause models (this account may not)" and is greyed.
- **Resume balloon:** "Resumed 2 of 3 models. qwen3-30b: not enough GPU memory (21.4 GB needed, 9.8 GB free)."

The tray reads `state` every 5 seconds, with the service state.

### Console (ui)

- **Machines, the machine card.** "Models paused from the tray icon since 20:14", with a Resume button. A running machine has a **Pause models** button. It asks: "Pause the models on Amish_Station? Answers in progress there stop. Eugene keeps serving everything else."
- **Backends.** A runtime that Pause stopped reads "Paused".

### Defaults

- Nothing is deleted.
- Pause never happens automatically.
- A pause lasts through a reboot until someone resumes (call 2).

## 3. Repositories and files

- **specs:**
  - `agent.yaml`;
  - `scripts/row35-tray-pause-acceptance.py` and its Windows job in `ci.yml`;
  - `windows-comes-back-by-itself.md` §8: the open question, answered.
- **agent:**
  - new `tray_pipe.py` and `pause.py`;
  - `tray.py`, `_tray_window.py`, `app.py`, `state.py`, `node_work.py`;
  - `routes/node.py`, `routes/runtimes.py` (`_compose` only);
  - tests.

  pywin32 is already in the service and tray extras.
- **ui:** the machine card (`src/app/nodes/page.tsx`) and the Backends runtime row.
- **Codegen:** agent and ui. Control generates `agent_models.py` but uses none of this, so it is not re-pinned. The gateway reads `stopReason` as text.

## 4. Test that fails before the change

**agent `tests/test_pause.py::test_pause_stops_and_refuses_wake`**

1. A stand-in runtime is running.
2. `POST /v1/node/pause` with an operator session.
3. `POST /v1/runtimes/{name}/start` with a gateway token.

Expected: after step 2, the runtime is stopped with reason `paused`. Step 3 gets 409, and the response names the pause. Today step 2 gets 404, because the route does not exist.

**Also:**

- `test_pause_survives_restart`;
- `test_resume_restarts_through_admission`;
- `test_pause_refuses_gateway_and_client_tokens`;
- `test_pipe_acl_from_service_dacl`: a recorded SDDL gives SYSTEM, Administrators and the user's SID, and not `IU`, `SU` or `WD`;
- `test_menu_offers_pause_and_resume`;
- `test_tray_refuses_imposter_server`.

## 5. Acceptance (high risk) and review

`scripts/row35-tray-pause-acceptance.py`, a Windows job on GitHub's runner. It builds on `windows-service-smoke.py`: a service with a unique name, a disposable venv and config, its own ports (18379-18383, never 8079-8083), `EUGENE_PLEXUS_*` cleared, and a stand-in engine.

1. Create two standard local accounts. `eprow35a` gets start and stop with `sc sdset`, as the installer does. `eprow35b` gets nothing.
2. Run the tray's own pause call as `eprow35a`, unelevated. First assert `IsUserAnAdmin() == 0`, which is R2.6's check-6 lesson. The stand-in engine's process ends, and `GET /v1/node` shows the pause.
3. Send a chat for that model through the gateway. It is refused, and the body names the pause.
4. Restart the service. The engine stays stopped.
5. Run the same call as `eprow35b`. It gets access denied, and nothing changes.
6. Connect through `\\127.0.0.1\pipe\...`, the remote path. It is refused.
7. Start a program that takes the pipe name before the service starts. The agent reports `taken`, and the tray call refuses that program.
8. Call `POST /v1/node/resume` with a client key and with a gateway token. Both are refused. With an operator session, the engine runs again.

**The reviewer should attack:**

- how the DACL is derived: deny ACEs, group SIDs, `IU`, `SU`, `WD`;
- impersonation: its level, and the revert on every path;
- remote clients, and a pipe name that another program holds;
- a client that connects and never writes;
- the routes' authentication;
- the boot path: `autoStart` starting a paused runtime;
- a measurement that is running when Pause comes.

Pause as a lever for someone allowed to stop the service is accepted: that account can already stop the service.

## 6. Do not change (other lanes' hot files)

- **agent:**
  - `runtimes.py`, `engines/acquisition.py` (13);
  - `admission.py`, `engines/llama_cpp.py`, `engines/vllm.py` (9, 20, 41, 42);
  - `benchmarks.py` (10);
  - `node_identity.py` (3, 46), `keyring_store.py` (46);
  - `enrollment.py` (36);
  - `client_tls.py`, `entrypoint.py` (45).
- **gateway:** `lifecycle.py`, `routing.py`. Neither changes.
- **`tokens.py` in every repo:** this row does not touch it.

## 7. Size, risks, calls

**Size M, about 1.5 days.** If it runs over, split it: 35a is the pipe and the tray, and 35b is the console routes and UI.

**Risks:**

- Pipe security and impersonation inside a service, through pywin32.
- A forgotten pause. The console shows it wherever it lists the machine.
- Answers cut when a pause starts.

**Calls for Troy:**

1. **The tray gets no Eugene credential.** A local pipe uses the caller's Windows identity, and the service's stop right is the rule. Recommend yes.
2. **A pause lasts through a reboot.** Recommend yes: a reboot during a game must not load the card again.
3. **A pause stops answers in progress.** Recommend yes now, and reuse row 13's drain later.
4. **A pause cancels a running benchmark or settings build.** Recommend yes.

## Calls answered by Troy (2026-10-21)

- **TRAY-1 to TRAY-4: Choice 1 each.** The tray holds no key and asks over a local channel; a pause survives a reboot; it stops answers in progress; it cancels a running benchmark.

## What building found (2026-10-27)

- **`NodeIdentity.pause` is present on every agent from row 35 on**, with `paused: false` when the machine is not paused, rather than absent. It carries `trayChannel` either way, and it tells the console which machines can pause: an older agent has no `pause`, and its card offers no button that would 404.
- **The per-connection check is Windows' own `AccessCheck`**, against the service's DACL read at that moment and the caller's token, not a comparison of the user's SID with a list. Groups and deny ACEs count as Windows counts them. The pipe's DACL is the outer gate: SYSTEM, Administrators, and each named account or group (`S-1-5-21-…`, `S-1-12-1-…`) the service lets stop it; never a broad group (`WD`, `AU`, `BU`, `IU`, `SU`, …), whatever the service grants; every deny of the stop right copied; `NETWORK` denied. Clients get read and `FILE_WRITE_DATA` only, never `FILE_APPEND_DATA` (`FILE_CREATE_PIPE_INSTANCE`). One instance, `FILE_FLAG_FIRST_PIPE_INSTANCE`, `PIPE_REJECT_REMOTE_CLIENTS`. The DACL is refreshed in place (`SetSecurityInfo`) before each connection.
- **The tray connects at identification level**: the agent learns who asks and cannot act as them. A name another program holds is read over an anonymous connection, so the squatter cannot act as the agent either.
- **A reboot during a pause holds every runtime the boot would start**, not only those Pause stopped: a runtime the gateway had unloaded (`idle`) would otherwise start at boot, because `autoStart` is all the boot reads. The boot adds them to the pause's list, and Resume starts them, as the boot would have. A damaged `pausedModels` record keeps the machine paused.
- **The guard refuses a declaration and an edit too**, since both launch. A runtime declared during a pause is refused with the pause's sentence rather than declared stopped.
- **A runtime Resume could not start stays stopped as a person's stop** (`operator`, remembered), so it reads truly and a reboot does not start it behind the refusal's back.
- **`paused` belongs to Pause.** A stop request that names it is recorded as `operator`.
- **The gateway passes the sentence on only for a `startOnDemand` runtime**, the wake path. A request for a model whose only runtime is paused and not `startOnDemand` gets the gateway's own "none of its runtimes asked to be started on demand" (gateway#21; `lifecycle.py` and `routing.py` belong to other lanes).
- **The pause's 409 is a `Problem`** whose `detail` is the sentence; the measurement's 409 stays text, as it was.
- **Only `build_server` opens the pipe** (`Settings.tray_channel_enabled`, as the machine port): an app built in a test or a harness holds no pipe.
- **The Windows acceptance's engine is a Kev stand-in** (`kevPython` pointing at an interpreter whose `kev.serve` answers `/v1/models`): a service loads no test adapter. The chat through the gateway runs in the console path, on Linux.
- **Mixed versions:** no request or report a machine sends gains a field, so the root need not go first. `GET /v1/node` gains `pause`, which consoles read and an older console ignores. `StopReason` gains `paused`; the gateway reads it as text, and an older console shows the word.
