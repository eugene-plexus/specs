# R3.6 - loading time is not healthy uptime

**2026-09-20. Committed and published; both installers re-pinned.**
Contract `f545c2c`; agent `159ec39` (full pin
`159ec397e1c6415619764f835d9e8378ad1ae059`), archive verified to resolve.
Roadmap section 4 item 6, review section 6.3 finding 37. Implementation is in
the agent's `supervisor.py` and `runtimes.py`; tests extend the existing
`test_runtime_end_to_end.py`. This repo carries the verification scripts and
a prose change to `RuntimeStatus.crashed` in `openapi/agent.yaml`.

## Reproduction And Policy

The first check used the real runtime supervisor and a controllable child,
observed it loading, then failed the process. The unchanged loop made **five
spawn calls**, each retrying an unchanged declaration. A multi-minute network
model load pays that read cost on every attempt.

The policy now distinguishes three cases:

- A launch that fails or a nonzero exit **before readiness** stops automatic
  retries immediately. `lastError` retains the underlying diagnosis and says
  to check settings and the engine log, then restart the runtime to retry.
- An engine observed ready still recovers after a nonzero exit, with the
  existing 2/4/6/8-second delays and five-consecutive-crash limit.
- **60 seconds of continuously observed readiness** clears prior crash
  history. Time loading is never credited. A failed readiness observation
  resets the stability window, but does not erase the fact that this process
  previously served. Each replacement must earn its own readiness and clock.

The 60-second stability boundary is an internal recovery policy, not a new
user setting. Tests pin both 59 and 60 seconds, repeated successful probes,
lost readiness, a long load followed by brief readiness, and a replacement
that becomes ready before any loading probe. Timing uses `perf_counter()`.

The startup-stop behavior is enabled only for engine runtimes. Components
retain their existing retry and safe-mode escalation. Clean exits and
operator-requested exits keep their existing treatment. This does not abort
a slow live load, predict an OOM, parse failures into retry classes, or change
an adapter's loading budget.

## Two Necessary Follow-Ups

**Restart could not restart a terminated supervision task.** It reset the
counter and signaled a live child, but after the loop gave up there was no
child and no task to resume. It now starts a new task in that case. The
live-child stop/escalation path remains first; an existing test caught a
first version that started a task before dealing with its live child.

**Readiness must belong to the process that was probed.** The runtime poller
captures the spawn timestamp and checks both the supervised object and its
timestamp after the await. A late success from an old process cannot make a
replacement's failed load eligible for automatic retries. A dead process is
not probed or credited. This guards the retry decision, not a new wire field.

## Verification

| Gate                                     | Result                                                  |
| ---------------------------------------- | ------------------------------------------------------- |
| Initial runtime reproduction, before fix | 5 spawns instead of 1                                   |
| Neighboring Windows lifecycle gate       | 180 passed before the final extra regression            |
| Final Windows runtime file               | 14 passed                                               |
| Windows full agent suite                 | 876 passed, 3 skipped after final regeneration          |
| Linux Python 3.12.14 full suite          | 857 passed, 17 skipped, 5 baseline failures             |
| Mypy on Windows and Linux                | 58 source files, no issues                              |
| Ruff                                     | Agent and verification scripts pass                     |
| Redocly 2.30.4                           | Agent contract validates                                |
| Real-process acceptance                  | 6 PASS Windows; 6 PASS Linux                            |
| Copied-checkout sabotages                | 15/15 Windows; 15/15 Linux; restored baselines green    |

All five Linux failures were rerun against an **untouched Git archive of the
committed agent**, using its source and tests rather than the modified
checkout, and all five failed there too:

- `test_seeding_declares_a_port_nothing_is_holding`
- `test_seeding_keeps_the_default_port_when_it_is_free`
- `test_open_runs_even_when_an_icon_is_already_showing`
- `test_no_icon_does_the_open_and_leaves`
- `test_ensure_console_is_a_no_op_where_there_is_already_one`

The first two need sibling components installed in the agent's interpreter;
the isolated Linux venv has only the agent's dev extra. The last three assume
Windows behavior without arranging it on Linux. None is altered by this slice.

The sabotage escape was useful: removing the per-spawn stability-clock reset
initially passed because every test observed **Loading** on the replacement,
which independently reset the same clock. A new case goes directly to Ready
after an unobserved load; the mutation now fails. The mutation harness also
normalizes CRLF for matching and restores original bytes exactly. No checkout
is ever mutated, and collection errors or a hung runner do not count as caught.

## Real-Process Run

`scripts/r36-acceptance.py` runs the real agent API on **8179** and a real
Python child on **8199**, with the llama.cpp adapter's real health/props
probes. The stand-in replaces binary resolution and argv only. It reports
loading or ready and exits on command; it never loads a model.

The six checks observe loading, fail it and prove it remains at one spawn
past the original two-second retry delay, correct the cause and use the real
Restart endpoint, crash a ready process and observe a different PID recover,
stop that replacement through the API, then stop the owned agent. State,
credentials, and mode files live in a temporary directory. Ambient
`EUGENE_PLEXUS_*` values are stripped. Both ports must be free before starting;
no unrelated listener or process is killed.

```powershell
& ../agent/.venv/Scripts/python.exe scripts/r36-acceptance.py
& ../agent/.venv/Scripts/python.exe scripts/r36-sabotage.py
```

Linux used `/home/tcorbin/.cache/eugene-r36-venv/bin/python`, installed with
Python 3.12 and the agent's `[dev]` extra. The scripts are the same files.

Two harness corrections preceded the clean Windows run: the token helper
returns `(token, expiry)` and accepts no subject argument; and hard-stopping
the agent left its temporary log briefly held open on Windows. The harness
now launches an owned process group and uses the project's graceful stop
helper. All behavior checks had passed before that cleanup failure, but the
run was counted complete only after cleanup passed too.

## Limits And Publication

No real llama.cpp/vLLM failure, network model read, OOM, macOS, service-mode
agent, or browser was exercised. The 60-second threshold is covered with an
injected clock, not a minute-long real-engine run. The live acceptance proves
the loading-versus-ready decision, manual retry, and real process boundaries.
Stopping on the first failed load deliberately sacrifices automatic recovery
from a transient startup fault; the operator can retry without re-declaring
the runtime. Five baseline Linux failures remain documented above.

The contract and agent were published directly to main with DCO sign-off.
Both installers carry the agent commit above; the live install was not updated.
The parsed contract comparison confirmed that formatter edits aside, only
`RuntimeStatus.description` changed. All six consumers were regenerated into
temporary outputs using their own installed tools. Agent `models.py` and
control `agent_models.py` changed only that docstring; the gateway, driver,
and library models were byte-identical apart from the pin header. The UI's
R3.6 change is JSDoc only; its other generated differences are the R3.3/R3.4
changes already deliberately left unpinned. Only the implementing agent moved
`SPECS_REF` to `f545c2c99aaa71bd44a900d778a287bc9c90deaf`. No UI rebuild.

Agent CI run `35521633539` is tracked separately from the green Windows gate:
the preceding agent revision already had failing Linux CI, and the five local
Linux failures above were independently reproduced on its untouched source.
The roadmap remains the sole pickup-point document.