# Row 2: The shared acceptance harness behaves like the real server

Lane OPS. Risk: cross. Size: M. No contract change.

## 1. What the row delivers

- Every script that starts an agent through `s8-ui-acceptance.py --serve` runs the agent's own start path, `build_server`, as the service and `python -m eugene_plexus_agent` do. It does not use `create_app` with its own uvicorn.
- That agent has the console log copy (`GET /v1/logs` shows its boot lines), the machine port (LT1), and the client doors (LT2): TLS beside plain HTTP on the console, gateway and app ports.
- The harness still stops through its `stop` file, on Windows and Linux.
- A CI check proves the harness is the real server, and fails if it builds its own app again.
- Older agents still run through the harness, which matters because `release-upgrade-acceptance.py` starts v0.3.0. v0.2.0 and v0.3.0 have `build_server(settings, *, unattended)`.

## 2. The design

**Today.** `serve()` calls `install_console_capture`, `create_app` and its own `uvicorn.Config`. It copies two lines of `build_server` by hand and misses the rest: entry-point preparation, the bind-host rule, the machine port, the client doors and the restart branch.

**Agent (`__main__.py`).** `_serve` becomes public:

```python
def serve(settings, *, unattended=False, should_stop=None) -> None
```

- `should_stop` None: unchanged, which is `server.run()` and then `reexec()` when a restart is requested.
- `should_stop` given: `asyncio.run(server.serve())`, polling `should_stop` every 0.1 s and setting `should_exit` when it says stop. The restart branch is the same.
- `main()` calls `serve(...)`. The service, the CLI and the harness share one function.

**Harness (`specs/scripts/s8-ui-acceptance.py`, `serve()`).**
1. Pick a free machine port (`bind(("127.0.0.1", 0))`). Never 8079-8083, and never the live install's +200 ports.
2. Build `Settings(config_file=..., bind_port=port, default_topology=False, machine_port=<free>)`. Pass `machine_port` only when `Settings.model_fields` has it, because older agents refuse unknown fields. Leave `machine_port_enabled` and `client_doors_enabled` unset, so `build_server` turns them on as an install does.
3. If the agent has `serve(..., should_stop=)`, call it with `unattended=True` and `should_stop=lambda: (root / "stop").exists()`.
4. Otherwise, call `build_server(settings, unattended=True)` with the same poll loop, and print "harness: agent <version> has no serve(should_stop); running its build_server".
5. Delete the hand copies: the capture call, the `GRACEFUL_SHUTDOWN_SECONDS` import, and the private `uvicorn.Config`.
6. Add `--machine-port` for scripts that run two agents on one host.

The child environment still drops every `EUGENE_PLEXUS_*` variable.

**What changes for callers.** With the doors on, the agent owns the gateway's declared port and pumps it to the gateway on an internal loopback port. That is the installed layout. Scripts that use the gateway URL keep working. A script that checks which process holds a port, or counts processes, is fixed to expect the real layout; the harness is never bent back. The callers are cx2, cx3, cx4, cx5, cx7, cx8, cx9, s9, s10 and `release-upgrade-acceptance.py`. None of them runs in CI.

**Behaviour on each failure.**
- **The machine port cannot bind.** `GET /v1/node` already names the error (`Door.error`). The CI check prints it verbatim.
- **The entry-point file is broken.** `build_server` exits with `agent: <cause>`. The caller's "isolated agent exited" names the `agent.log` that holds it.
- **A restart is requested.** `reexec` runs the same command again, and on Windows the PID changes. The harness prints "agent restarted in place (entry point)". An install behaves the same way.
- **An agent older than v0.2.0.** Stop: "agent <version> predates build_server; v0.2.0 is the oldest supported."

**Defaults.** The installed ones: machine port, doors and console copy are all on. A script that turns one off does it through an install's own environment variable, with a comment saying why.

## 3. Repositories and files

- **agent:** `src/eugene_plexus_agent/__main__.py`, `tests/test_shutdown_bound.py`.
- **specs:**
  - `scripts/s8-ui-acceptance.py`;
  - new `scripts/harness-acceptance.py` and `scripts/test_s8_harness.py`;
  - `.github/workflows/ci.yml`, one step in Pinned integration on both OSes;
  - the callers whose expectations change.
- **Codegen:** none.
- **Order:** merge agent first, then specs with the agent pin, through `ship.py`. CI runs the check against the pinned agent, so the script and the pin go in one push.

## 4. Tests that fail before the change

- `specs/scripts/test_s8_harness.py::test_serve_goes_through_the_agents_own_start_path`:
  - Setup: inject fake `eugene_plexus_agent.__main__` and `.settings` modules into `sys.modules`, so no agent install is needed.
  - Assert: `serve()` called the fake `serve` once, with `unattended=True`, and with a `machine_port` that is not 8083.
  - Assert: `create_app` was never called. Today it is.
- `agent/tests/test_shutdown_bound.py::test_serve_stops_when_should_stop_says_so`: `should_exit` is set within 0.5 s of `should_stop` turning True, and the lifespan shutdown runs.
- **CI acceptance, `scripts/harness-acceptance.py`** (Pinned integration, Linux and Windows). It starts the harness on free ports and checks:
  1. `GET /v1/logs` holds "console output is mirrored to".
  2. `GET /v1/node` lists the machine port as listening, and a TLS handshake to it completes.
  3. `https://127.0.0.1:<console port>/healthz` answers 200.
  4. The stop file ends the process within 15 s, with no child left under the prefix.

  Today, checks 1-3 fail.
- **Sabotage once:** make `serve()` call `create_app` again. Check 3 must fail.

## 5. Do not change

These are other rows' files:
- `agent/machine_port.py`, `node_identity.py` (row 3)
- `agent/client_doors.py`, `apps.py` (rows 25, 34)
- `agent/entrypoint.py` (row 45)
- `agent/reach.py` (row 8)
- `specs/scripts/release.py` (row 6)

A door or port defect found here goes in an `agent` issue, not a patch in this row.

## 6. Size, risks, open questions

- **Size:** M. The harness is small. The work is the ten callers' expectations, each run once locally by `runner` in one batch.
- **Risk:** `release.py`'s evidence phase runs s10 and the upgrade run through this harness. Land row 2 before row 6.
- **Risk:** a stand-in gateway that binds its declared port itself now collides with the agent. Declare it through the agent's topology.
- **Open:** run `python -m eugene_plexus_agent --unattended` as a subprocess instead? That would also exercise `main()` and `load_settings()`, but Windows has no clean stop signal. Recommendation: in-process `serve(should_stop=...)`. `harness-acceptance.py` also runs `load_settings()` with an installer's variables and compares its result with the harness's `Settings`.
