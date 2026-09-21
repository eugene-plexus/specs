# A7 recovery acceptance

In progress, 2026-09-21. Windows recovery has passed; container acceptance is
being run through the container workflow. Do not mark A7 complete until that
required result is recorded here.

Agent `253f6127e8586d3333c536efb8737ad0d69f5575` refuses startup and enrollment
of quarantined copies, including safe mode. Its full Windows suite passed:
962 tests, four platform-dependent skips. Agent CI
[35625192234](https://github.com/eugene-plexus/agent/actions/runs/35625192234)
passed. Development installers pin this revision; no other component changed.

## Windows failed-update exercise

`scripts/a7-recovery-acceptance.py` used a fresh disposable installed Python 3.12.14
environment, two agents, supervised control/gateway/library, a real driver and
CPU llama.cpp b11065 with Qwen3-0.6B Q4_K_M. Ports and identities were isolated.
The model and engine were read-only assets from earlier isolated acceptance,
not the owner's active model or service. The NAS was not contacted.

The test initialized/enrolled the nodes through HTTP, created a profile and two
scoped local-only keys, completed real inference and revoked one key. It stopped
both agents and their children, made encrypted checkpoints, then deliberately
uninstalled the disposable gateway package and failed a package install. It also
replaced Library state with an incompatible document to model state changed by
an unsuccessful update.

Each restore created a new virtual environment from the recorded Python version,
43 resolved packages and exact Eugene source archive revisions/hashes. Quarantined
startup was refused. After activation, both nodes authenticated, the saved profile
and local-only policy were present, the revoked key returned 401, and inference
returned `Hello! How can I assist you today?` with a smiley. The updated/damaged
state was not reused. Originals remained stopped throughout recovery.

| Operation | Observed time |
| --- | ---: |
| Root checkpoint | 5.219 s |
| Worker checkpoint | 2.656 s |
| Root reconstruction, validation, activation and login | 14.578 s |
| Worker reconstruction, validation, activation and login | 8.328 s |

These are warm-cache local timings, not download or recovery-time guarantees.
Artifacts: `%TEMP%/ep-a7-windows-run3`, log `%TEMP%/ep-a7-windows-run3.log`.
The checkpoint directories and recovered metadata contain test credentials and
must not be uploaded as public CI artifacts.

The first instrument run correctly hit the engine executable allowlist; the
instrument now configures the exact test engine directory. A second run revealed
that `driverPort` is not a runtime field: the automatic driver chose the default
8090, found it occupied, and refused to bind. The instrument now predeclares its
companion on an allocated ephemeral port. No occupant was stopped or reconfigured.
Both failed runs cleaned up their own processes.

## Refusal checks and remaining work

`scripts/a7-recovery-checks.py` passes on Windows and Linux/WSL: missing/wrong
unlock material, wrong backup password, future archive format, changed external
model, truncated encrypted state, overwriting an existing target, activating
without fencing the original, and mismatched installed software all refuse.
Source file digests remain unchanged; private directory permissions, retained
revocations, SQLite integrity and exclusion of expendable logs are checked.
The Windows run found and fixed an unclosed SQLite handle during staging cleanup.

Container restore and final published instrument checks are pending. This slice
does not demonstrate Windows reboot before sign-in, physical Mac support,
cross-platform restoration or external vLLM environment reconstruction. Those
limits are preserved in [the procedure](../recovery.md) and the roadmap.
