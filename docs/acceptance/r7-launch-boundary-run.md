# R7 step 1 — child credentials and runtime launch policy

Executed 2026-09-20 on Windows and Ubuntu under WSL. Agent `64ea8b2` and
inference-driver `e10896d`; both installer pins updated. No OpenAPI or generated
model changes, so other consumers and the UI dist pin remain unchanged.

## Reproduction and result

Before changing production code, 11 agent launch-boundary checks failed:
ambient credentials reached unrelated components and engines, gateway received
the master key, credential overrides were accepted, arbitrary binaries were
probed, and raw arguments needed no explicit approval. Five driver checks failed
for CLI credential inheritance, including case-insensitive variable names.
Another five agent checks failed for version, help, interpreter, and hardware
probes inheriting credentials. All now pass.

Gateway gets its service token and current verification material, but no master
encryption key. Library and driver retain their own deliberate master key for
at-rest credentials. Control keeps its own passphrase-file bootstrap and gets no
agent credentials. Component `spawn.env` cannot replace credential wiring.
Third-party engines, probes, and buffered/streaming CLI children receive no
`EUGENE_PLEXUS_*` variables. Backend API keys, proxy settings, GPU selection,
and UTF-8 behavior are preserved.

Runtime `binary` is checked before its version probe. Default approval covers
the managed engine directory, `engineBinaryRoots`, the exact engine executable
found on PATH, and the configured `vllmBinary`. Canonical containment rejects
sibling prefixes and symlink escapes. `extraArgs` and arbitrary binary paths
need `allowUnrestrictedEngineLaunch: true`; even that override cannot inject
Plexus credentials. API admission/create/update validate the policy, and the
planner rechecks it against current config before every launch.

Both settings are standard Config fields, with safe defaults, labels, types,
descriptions, validation, and persistence. The existing schema-driven UI renders
them without a new UI build. After upgrading, add a custom engine's directory
to **Trusted engine directories** before restarting it. Existing raw `extraArgs`
require **Allow unrestricted engine launch**. Already-running processes are not
reconfigured by changing these settings.

## Verification

Full agent suites: **904 passed / 4 skipped on Windows**, **891 passed / 17
skipped on Linux**. The final added admission/config integration check passed
in focused runs on both platforms: **29 passed / 1 skipped Windows**, **30 passed
Linux**. The Windows skip is directory-symlink creation without the necessary
OS permission; Linux executes that check. Other skips are existing platform/UI
conditions. Full driver suites: **414 passed / 3 skipped on each platform**
(the skips require live CLI/API backends). Ruff lint/format and both mypy checks
pass.

Real harmless Python children exercise the engine launch environment and both
driver CLI paths. They print variable **names**, never real secret values, and
use no models or network listeners. Component roles and Config/API behavior use
isolated temporary state through the existing test fixtures. The running install,
enrollment, passphrase files, ports, scheduled tasks, and installed configs were
not changed.

`scripts/r7-launch-boundary-checks.py` copies sources/tests into temporary trees,
runs baselines, breaks 15 guards separately, and requires each relevant test to
fail with an assertion. It restores saved bytes after each mutation and checks
both restored baselines. **15/15 caught on Windows; 15/15 caught on Linux.**
Checks cover environment filtering, gateway master-key delivery, override
rejection, binary/argument policy, containment, launch-time revalidation,
route validation, probe environments, and both real CLI subprocess paths.
Specs CI runs this gate on Windows and Linux against the installer-pinned
consumer commits.

Local invocation (consumer dev environments installed):

```powershell
../agent/.venv/Scripts/python.exe scripts/r7-launch-boundary-checks.py
```

On Linux, pass `--agent-python` and `--driver-python` for separate virtual
environments, or use `--current-python` when both consumers' dev dependencies
are installed in the invoking interpreter.

## Remaining R7 work

This is process-environment isolation, not an OS sandbox. Children still run as
the same OS user. HS256 verification material still permits minting operator
tokens. R7 steps 2–4 must define the asymmetric credential contract, implement
the five independent security modules and enrollment/rekey plumbing, and prove
an old install can rotate without re-enrolling its nodes. Trusted agents remain
minters; only gateway, library and driver become public-key-only verifiers.
