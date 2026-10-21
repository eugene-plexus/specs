# Console experience pass: the follow-ups

**2026-10-21. agent#21, agent#20 and library#15 are closed; library#14 was closed on the way. On Edge
specs `cc8d5ee`.**

- **Run record this follows:** [`console-ux-pass-run.md`](console-ux-pass-run.md).
- **Where it ran:** Amish_Station (Windows 11). Each run used a disposable install, its own ports and
  folders, and every ambient `EUGENE_PLEXUS_*` variable cleared. The live install was unchanged after
  every run (`liveInstallUnchanged`).

## What changed

| Issue | Change | Commits |
|---|---|---|
| agent#21: a removed machine cannot leave and re-join | Troy's call: A and B. **B:** the trust pull leaves the install when the root's signed bundle and machine list no longer list this machine. **A:** a sign-in the root does not address to this machine is a 409 that says why, and `POST /v1/node/unenroll` takes this machine's own passphrase with no session when the root no longer lists it or does not answer | contract specs `c56e0df`; agent `aaaec60`, `5787044` |
| agent#20: a stop can wait for ever | `build_server` sets `timeout_graceful_shutdown=5`. A middleware names each request a stop ends. The harness's `serve` has the same bound | agent `a94432d`; specs `f47fd31`, `c612cda` |
| library#14: a run on a removed machine waits for ever | Listing runs ends each unfinished run whose machine the trust bundle no longer lists, with the cause. A new run for such a machine is refused (409) | library `f0588ac`, `295ed51` |
| library#15: one unexplained 401 after enrollment | Closed: no 401 ended a session in CX4 or CX5 | none |

### agent#21: the adversarial review

One review found nothing that lets an outsider make a machine leave. It found these defects, and each
one is fixed in agent `5787044`:

- A root leaves a key out of the bundle for faults too, such as a duplicated or unreadable key, while it
  still has the machine registered. The machine now leaves only when the signed machine list, taken on
  the same pull, does not name it either.
- Standalone, a machine with no passphrase of its own belongs to whoever sets one first. Such a machine
  does not leave by itself. agent#22 tracks its way out; today that is a reinstall.
- Leaving by passphrase now refuses (409) when the root's answer is one the machine does not take: not
  signed by its root, older than the bundle it holds, or from a fenced epoch.
- The machine that runs the install's root does not leave by passphrase.
- A re-join between a pull and its leave is not undone.
- Concurrent leaves report what happened.

### agent#20: the cause

uvicorn's graceful wait ends with `await server.wait_closed()`. On Windows, when a peer resets a
connection, CPython 3.12's proactor transport raises `ConnectionResetError` (`WinError 10054`) from
`sock.shutdown()` before it calls `server._detach()`. The server never counts down to zero, and
`wait_closed()` never returns. Each hung run logged that traceback just before "Shutting down". The 5 s
bound covers the whole wait. The related upstream fix is CPython GH-89237; this exact case is not on the
tracker. Diagnostic runs: `D:\ep-acceptance\cx-20261020\diag20-cx5b`, `diag20-cx5c`.

## Runs of record

| Script | Result | Pins | Output |
|---|---|---|---|
| CX6 remove a machine | 12 of 13 pass; 5b not checked (the worker declared no components) | branch agent `5787044` in a disposable venv with control `d192498` | `D:\ep-acceptance\cx-20261020\cx6-rejoin2` |
| CX4 one context for fit | 7 of 7. The agent stopped cleanly | Edge specs `cc8d5ee` | `D:\ep-acceptance\cx-20261021\cx4` |
| CX5 Connect apps | 5 of 5. The agent stopped cleanly | Edge specs `cc8d5ee` | `D:\ep-acceptance\cx-20261021\cx5` |

CX6 now checks the following:

- **8a:** the removed worker left by itself, and its own passphrase signs in. One sign-in in between was
  the 409 "This machine was removed from the install".
- **8b:** a new join token joins the worker again.
- **9a:** while the install lists the worker, leaving by passphrase is refused.
- **9b:** with the root stopped, leaving by passphrase works (`controlNotified: false`).

The `browser.json` `refused` arrays:

- **CX4:** empty.
- **CX5:** two 401s, both the gateway's "Missing token" for `/v1/models`. CX5 provokes these on purpose
  when it checks the address with no key.

### Regression proof

Against the code before the fix (agent `0cb6720`), each new test fails:

- `test_a_removed_machines_sign_in_says_so_and_it_can_join_again`: the old code answers 200, not 409.
- `test_a_removed_machine_leaves_at_its_next_trust_pull`: the machine is still enrolled.
- `test_shutdown_bound.py`: the old code has no bound.
- The two library#14 tests.

Branch CI was green before each merge.

## Not checked

- **A real Windows service stop with the new agent.** The live service runs the previous Edge agent, and
  updating it needs Troy's sign-in. A disposable service needs a UAC prompt, and nobody was there to
  answer one. The CX scripts stop the agent the way a service stop does (`should_exit`). CX4 and CX5
  stopped cleanly on the new pins.
- **Leaving by passphrase from the console.** No page offers it yet (ui#20).

## Fixed on the way

- **A specs check broke after the library#14 ship.** `run-operations-checks.py` stubs the library's auth
  state with no bundle; library `295ed51` reads it as optional.
- **CX6's step 8 helpers had the same names as the setup's responses.**
