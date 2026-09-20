# R3.7 - native Python from a Rosetta terminal

2026-09-20. Roadmap section 4 item 7. Changes are in `install.sh` and
`bootstrap.sh`; no component, contract, or installer package pin changes.

Both scripts check Apple hardware when `uname` reports Intel on macOS and
request `cpython-3.12-macos-aarch64-none` on Apple Silicon. This is uv's
[documented architecture-qualified request format](https://docs.astral.sh/uv/concepts/python-versions/).
The bootstrap qualifies numeric Python versions and preserves explicit
interpreter choices. Intel Macs and Linux retain their existing requests.

Both scripts inspect the resulting interpreter before installing packages.
An incompatible existing environment is preserved, with its path and recovery
instructions in the error. Newly created environments are checked too. A
native environment is reused on subsequent runs. The agent's child processes
use that same Python, so the existing native-platform detection can select
Metal without pretending an Intel interpreter is an ARM interpreter.

## Verification

Run from Linux or WSL:

```sh
python3 scripts/r37-sabotage.py --before-ref c6bcdbb
bash scripts/r37-install-sh-checks.sh
python3 scripts/r37-sabotage.py
bash scripts/r22-install-sh-checks.sh
```

The standalone regression executes both complete setup scripts with isolated
command stand-ins. It clears the environment, uses temporary homes and
prefixes, and starts no services. **88 checks pass**, covering Linux x86/ARM,
Intel Macs, native Apple Silicon, Rosetta, unavailable hardware probes,
preinstalled uv, environment reuse, incompatible interpreters, inspection
failure, alternate versions, and explicit interpreter overrides. The old
revision fails the same behavior gate. All **13 sabotage variants are caught**;
the scripts are copied before mutation and the restored baseline passes.
The neighboring R2.2 POSIX installer suite also passes. The new regression and
sabotage gate run in specs CI.

## Hardware verification still owed

These results simulate platform facts; they do not establish that a Mac runs
the installed product. On an Apple Silicon Mac, run a fresh isolated install
from a Rosetta terminal and check the venv's `platform.machine()` is `arm64`.
Confirm the agent reports Metal and selects `macos-arm64`, the library reports
unified memory, and a small model serves a completion. Repeat the native
terminal path and test an existing Intel environment's refusal. No Mac was
available in this session; no end-to-end Mac or launchd result is claimed.
