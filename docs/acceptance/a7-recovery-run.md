# A7 recovery acceptance

Completed 2026-09-21. Windows and container recovery passed. Implementation:
specs `7c51a0f`, hardened in `2d298fb`, `d2cdf4a` and `b7bf2ea`; the procedure is
[backup and recovery](../recovery.md).

Agent `253f6127e8586d3333c536efb8737ad0d69f5575` refuses startup and enrollment
of quarantined copies, including safe mode. Its full Windows suite passed:
962 tests, four platform-dependent skips. Agent CI
[35625192234](https://github.com/eugene-plexus/agent/actions/runs/35625192234)
passed. Final agent revision `d1cfe73140f464c8772f45f57441c6c0fbcf7fc1` also fixes
the Event Log startup failure found by the final Windows CI run (below).
Development installers pin that revision; no other component changed.

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
| Root checkpoint | 3.250 s |
| Worker checkpoint | 2.203 s |
| Root reconstruction, validation, activation and login | 12.562 s |
| Worker reconstruction, validation, activation and login | 11.750 s |

These are warm-cache local timings, not download or recovery-time guarantees.
Final artifacts: `%TEMP%/ep-a7-contained`, log `%TEMP%/ep-a7-contained.log`.
Earlier successful runs remain at `%TEMP%/ep-a7-windows-run3` and
`%TEMP%/ep-a7-windows-final`. The final run also verifies that the managed base
Python lives inside each replacement's `pythons` directory, avoiding a dependency
on the restoring user's Python cache when registering a Windows service.
The checkpoint directories and recovered metadata contain test credentials and
must not be uploaded as public CI artifacts.

The first instrument run correctly hit the engine executable allowlist; the
instrument now configures the exact test engine directory. A second run revealed
that `driverPort` is not a runtime field: the automatic driver chose the default
8090, found it occupied, and refused to bind. The instrument now predeclares its
companion on an allocated ephemeral port. No occupant was stopped or reconfigured.
Both failed runs cleaned up their own processes.

## Container recovery

[Container run 35627102605](https://github.com/eugene-plexus/specs/actions/runs/35627102605)
passed the existing image checks and the new recovery exercise before publishing
development `edge`. `scripts/a7-container-acceptance.sh` uses that built image in
a disposable derivative with `libgomp1` for its CPU inference fixture. The production
control-plane image still carries no inference engine. No host ports are published;
all fixture nodes and their original/restored identities use container loopback,
and originals stop before replacements activate.

The same failed-package/incompatible-state scenario recovered profiles, scoped
local-only policy and revocation, authenticated both nodes, and served the real
Qwen3-0.6B completion through the recovered gateway and worker. This reconstructs
both environments; it is not a restart of the pre-update virtual environment.
Final timings: root/worker backup 2.984/2.499 s; root/worker recovery through
login 12.343/9.389 s. All owned processes and the disposable container were removed.
The test's deliberately removed package existed only in that container's writable
layer, not the image subsequently published.

Model SHA256: `ac2d97712095a558e31573f62f466a3f9d93990898b0ec79d7c974c1780d524a`.
Linux llama.cpp b11065 archive SHA256:
`f00971c1b044fae179230bfc6f8d9f8461b778fef9ffac2b450088081a8ecd43`.
Both downloads are checked against these hashes in the instrument. Engine build
metadata/version output and companion file checksums are captured by the helper.

## Refusal checks and limits

`scripts/a7-recovery-checks.py` passes on Windows and Linux/WSL: missing/wrong
unlock material, wrong backup password, future archive format, changed external
model, truncated encrypted state, path traversal, overwriting an existing target,
activating without fencing the original, and incompatible installed Python all
refuse. Older agents lacking quarantine support and base Python installations
outside the replacement are also refused. Nested engine `bin` support files are retained.
Source file digests remain unchanged; private directory permissions, retained
revocations, SQLite integrity and exclusion of expendable logs are checked.
The Windows run found and fixed an unclosed SQLite handle during staging cleanup.

Full specs CI passed at `2d298fb`
([35626260508](https://github.com/eugene-plexus/specs/actions/runs/35626260508));
final recovery refusal checks also passed locally on Windows and Linux, and the
final container workflow verified actual inference against `b7bf2ea`. This slice
does not demonstrate Windows reboot before sign-in, physical Mac support,
cross-platform restoration or external vLLM environment reconstruction. Those
limits are preserved in [the procedure](../recovery.md) and the roadmap.

The first `b7bf2ea` Windows CI attempt exposed two older failures. The service
smoke test received Windows error 5 from `RegisterEventSource/ReportEvent`, which
aborted startup before the agent could run. A failing regression reproduced the
failure; `d1cfe73` moves optional Event Log notification after console capture and
retains a warning instead of aborting. Nine focused Windows service/quarantine
tests pass (two platform-specific skips). The profile-cache instrument also had
a one-second stale observation window that could expire during a slow HTTP call.
It now uses a five-second window, still verifies expiry, and waits the full retry
backoff before asserting recovery. No cache behavior or production deadline changed.
