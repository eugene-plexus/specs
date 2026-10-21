# Console experience pass, CX2-CX9: the end-of-pass run

**2026-10-20, run of record: 7 of 8 scripts pass. CX6 passes 8 of 9 checks, and step 8 (re-join) fails on
a product defect left open for a call (agent#21).**

- **Design:** [`docs/design/console-ux-pass.md`](../design/console-ux-pass.md). CX1 has no script; it was
  routine Edge work.
- **Handoff:** `docs/private/handoff-console-test-run.md`.
- **Where it ran:** Amish_Station (Windows 11). Each run used a disposable install from this checkout's
  installer, the pinned UI wheel, claimed ports from 19000, and every ambient `EUGENE_PLEXUS_*` variable
  cleared. The live install was unchanged after every run (`liveInstallUnchanged`).
- **Scripts:** `specs` branch `cx-test-run` at `1696c2d`.
- **Pins (Edge specs `a016502`):**

  | Component | Pin |
  |---|---|
  | agent | `0cb6720` |
  | control | `d192498` |
  | gateway | `dd0ef74` |
  | inference-driver | `01e40d5` |
  | library | `3dd4d71` |
  | tool-driver | `3d63f6b` |
  | ui (dist) | `7705b1f` (from `70a527b8`) |
  | site-host | `63239f4` |

  Every run of record was on these pins. CX6 ran in the venv of the CX4 install, which holds the same
  agent and control.

## Results

| Script | Checks | Not checked | Output |
|---|---|---|---|
| CX2 setup resumes | 9 of 9 | none | `D:\ep-acceptance\cx-20261020\final-cx2` |
| CX3 one-click run asks first | 7 of 7 | none | `...\final-cx3` |
| CX4 one context for fit | 7 of 7, served 32,768 | none | `...\final-cx4` |
| CX5 Connect apps | 5 of 5 | none | `...\final-cx5` |
| CX6 remove a machine | 8 passed, step 8 failed | 5b | `...\cx6-r3` |
| CX7 saves that restart say so | 11 of 11 | 2 | `...\final-cx7` |
| CX8 failures link to logs | 12 of 12 | 4 | `...\cx8-r3` |
| CX9 models already in Ollama | 19 of 19 | 4 | `...\cx9` |

### Not checked, with the scripts' reasons

- **CX6, 5b** (the worker's components gone from `/v1/components`): "the worker declared no components
  before removal".
- **CX7:**
  - "that the restart ends an answer an app is reading (no model is served)";
  - "which save a restart followed; only that one restart followed both saves".
- **CX8:**
  - "Machines: 'Logs →' on a down machine (one machine here; none is stopped)";
  - "Hosts: 'Logs →' on a silent machine (no second machine is enrolled)";
  - "an app's lastError 'Logs →' and a failed install's 'Logs →' (no app is installed or made to fail)";
  - "the '(driver: <word>)' suffix on 'x of y ready' (every backend here is ready; the word is a unit
    test)".
- **CX9:**
  - "Ollama itself: the store is a stand-in, so Ollama's own delete, prune and migration are not
    exercised";
  - "a store on another machine (CX9-C3 leaves it for later)";
  - "a manifest list whose llamacpp child is a blob reference (unit-tested in the Library only)";
  - "the 'may not load in llama.cpp' warning for a migrated family (the stand-in's architecture is not
    one)".
- **CX6, by its own docstring:** the "only gateway" refusal. No real gateway runs there; the unit tests
  cover it.

## Product defects found

| # | Found by | Defect | Fix | On Edge |
|---|---|---|---|---|
| 1 | CX2 | A new browser on a half-set-up install was sent to sign-in, not setup (CX2-C1 did not hold). Home's runs poll read the library with no session, and the 401 bounced the browser before the setup gate had decided | ui `1722b506`: the runs poll reads nothing without a session. Regression test in `oneClickRun.test.ts` | specs `0dea127` |
| 2 | CX3 | A renamed Hugging Face repo could not be downloaded. `ggml-org/models` became `ggml-org/models-moved`; the old name answers 307 with no metadata, so the file list read the redirect as "non-JSON" and a HEAD took its size off the redirect | library `3dd4d71`: a same-hub redirect without `X-Repo-Commit` is a rename and is followed; the hub's own redirects (Trap 2) are not. Two regression tests in `test_hub.py` | specs `8aae348` |
| 3 | CX4, CX5 (intermittent) | Setup ended at "Your session ended". The runs poll Home started kept one more read after the gate sent the browser to setup. That read, holding the session while setup changed it over at enrollment, got a 401 that the api client took as a sign-out | ui `70a527b8`: the poll asks whether anyone is watching before it reads, and carries the session as a supplied bearer, so a refusal fails the poll and does not end the session. Three regression tests. One adversarial review (session handling): no findings | specs `a016502` |
| 4 | CX6 | A removed machine that is still running cannot be signed in to leave its old enrollment, so it cannot re-join. Its sign-in is forwarded to the root, which addresses the session only to `control`, and its own agent refuses that for `POST /v1/node/unenroll` | **Not fixed: a security call.** agent#21 gives two options and a recommendation | no |

Each fix's regression test fails without the fix. Each fix had branch CI green before its fast-forward
and ship.

## Filed, not fixed

- **agent#20:** the agent's shutdown can wait for ever on an open connection. uvicorn logs "Waiting for
  connections to close" and never runs the lifespan shutdown that stops the children. `build_server`
  sets no `timeout_graceful_shutdown`. Seen in CX4 r2, CX8 r3 and the final CX5. The scripts now kill
  the process tree after 45 s.
- **library#15:** setup's session was refused once by the library about a second after enrollment.
  Seen in the first CX4 run, before fix 3. The reason was not recorded. Every browser half now records
  each 401 with its body (`browser.json` `refused`). No session-ending 401 appeared in any run after fix 3.
- **agent#21:** defect 4 above.

## Harness errors fixed on the way

- **CX2:** `getByRole("alert")` also matched Next.js's route announcer.
- **CX3:** the wait for `awaiting-install` sat out 15 minutes on a run that had failed. It now stops
  when the run ends.
- **CX4:** it required 8 checks but records the 7 its docstring lists.
- **CX6:**
  - it needs an interpreter with the pinned agent and control, which ambient Python does not have;
  - three `record.add(..., status=...)` calls collided with the check's own `status`.
- **CX8:**
  - the stand-in primary refused with a generic 503. That is "outcome unknown", which the gateway
    rightly does not replay, so no failover happened. It now refuses as a loading llama-server does;
  - the link check did not take the static export's `/logs/?q=`.
- **s8 harness `serve()`** (shared by CX2-CX5 and CX7-CX9): it built the agent without the console
  mirror that `build_server` installs, so `GET /v1/logs` had nothing to search.
- **All:** a 45 s fallback that kills the agent's process tree (agent#20), and each 401 recorded with its
  body.

## Runs before the run of record

- **CX2:** a selector error, then defect 1. It passed on the third run.
- **CX3:** defect 2, then a pass.
- **CX4:** defect 3, then a run whose checks all passed but whose exit failed (the count of 8, agent#20),
  then a pass.
- **CX5:** defect 3, then a pass.
- **CX6:** no interpreter, then the `status=` collision, then the run of record.
- **CX8:** no failover (the stand-in), then no log lines (the s8 `serve()`), then a pass.
- **CX2, CX3, CX4, CX5 and CX7** were run again on the final pins, after fix 3 and the s8 change. Those
  are the runs of record above.
