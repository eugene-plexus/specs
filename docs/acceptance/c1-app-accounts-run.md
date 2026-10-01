# C1 acceptance: an app cannot read the install's keys

**2026-10-01.** `scripts/c1-app-accounts-acceptance.py`, run by
`.github/workflows/c1-app-accounts.yml` on **windows-latest** (Windows
Server 2025) and **ubuntu-24.04**: **42 of 42 checks on each**, on the
candidates agent `bd4f4e8`, control `71aa23a` and gateway `33d9c0e`
(run 36868116674). Design: [`../design/workbench.md`](../design/workbench.md)
§1-§3. Sabotage: `scripts/c1-sabotage.py`, **19 of 19 caught** across the agent, control, the gateway and the UI.

The run installs Eugene the way a person installs it as the machine's
service: `install.ps1` elevated on Windows, so the agent is LocalSystem in
`%ProgramData%`, and `sudo install.sh` on Linux, so the agent is the
`eugene-plexus` account in `/var/lib/eugene-plexus`. It onboards through
the API, installs two copies of the app fixture as custom apps, and asks
each one, from inside its own process, who it runs as and which files
under the prefix it can open. The fixture's `GET /probe` returns names
only, never a byte of what a file holds. On Windows it also lists its
account's stored credentials that mention Eugene.

## Before: the failing check

On the pins of the day (agent `05d88f8`), both platforms failed the same
14 checks (Linux run 36860672849, Windows run 36862136748):

| | Windows service install | Linux system install |
|---|---|---|
| The app runs as | `nt authority\system` | `eugene-plexus` (uid 999) |
| It reads | `node.yaml`, `agent.yaml`, `apps.yaml`, `control.yaml`, `control-state/log.jsonl`, `snapshot.json`, `trust_bundle.json`, the other app's `client_key` | `node.yaml`, `agent.yaml`, the 0400 `passphrase`, `control-state/log.jsonl`, `snapshot.json`, `trust_bundle.json`, the other app's `client_key`, all of uv's cache |
| Its keyring | `eugene-plexus-agent`, `eugene-plexus-control`, both `master-key:` entries | (none: this install uses the passphrase file) |

That is the root token key's unlock on a one-machine install, which is the
whole install (`per-node-token-keys.md` §2).

## After

On both platforms, on the candidates:

- **Each app runs as an account of its own** (checks 20, 28):
  `nt service\eugeneplexusapp-probe-a` and `-probe-b` on Windows;
  `eapp-6794af8371f2` (uid 63363) and `eapp-3e2c743bc943` (uid 63771) on
  Linux.
- **It cannot open** `node.yaml`, `agent.yaml`, the passphrase file, the
  control root's files or the other app's folder, and it sees none of the
  install's keyring entries (21-25). **Outside its own folder and the
  interpreters it can read nothing in the install** (26). It can still read
  its own key (27).
- **The install says so** (30-31): the catalogue reports
  `ownAccounts: true`, and each app reports `isolation: own_account` and
  its account by name.
- **What the app prints reaches the Logs page** through the launcher and
  `POST /v1/logs`, under source `app: <id>` (32).
- **Stop, start and uninstall go through the service manager** (33-35).
  After an uninstall, Windows answers `1060` (no such service) and systemd
  reports the unit inactive.

## What the runs found, each fixed

1. **`install.ps1` ran uv's own installer in its own process.** uv's
   installer catches any error, writes it to the information stream and
   calls `exit 1`. That ended `install.ps1` with exit code 1 after
   "fetching uv" and no words, because the silencing took the reason with
   it. It runs in a child process now, and its words are printed when it
   fails.
2. **Windows PowerShell started from PowerShell 7 loaded PowerShell 7's
   modules** (`PSModulePath` names them first) and failed inside uv's
   installer: *"The 'Get-ExecutionPolicy' command was found in the module
   'Microsoft.PowerShell.Security', but the module could not be loaded."*
   `install.ps1` drops PowerShell 7's module folders from its own path when
   it runs in 5.1. The harness leaves the runner's path as it is, to prove
   it.
3. **Uninstall left the Windows service** and answered 204.
   `win32service.DELETE` does not exist (DELETE is a standard right, in
   `win32con`). The error was logged and swallowed. The service is now
   opened with the right itself. A removal that fails fails the uninstall
   with a 500 saying the key is already off, and the app stays listed.
4. **Two Linux apps shared one uid** (65412), found by reading the first
   run's facts, not by a check. systemd names a template unit's dynamic
   user after the template, so every app shared one account and could
   reach the others' processes. The root helper now writes a drop-in per
   instance, `User=eapp-<12 hex of sha256(id)>`; systemd takes names of at
   most 31 characters and an id may be 40. Check 28 asserts it.
5. **An uninstall's second stop request went unanswered for 60 s** on
   Linux. The supervisor and the runner each sent one. Removal is one
   request now. The helper lists requests until none is left, and its
   service has `StartLimitIntervalSec=0`, because systemd's default of five
   runs in ten seconds could refuse a boot with several apps and leave the
   path unit failed.

## What the runner cannot show

- **A graceful stop.** The run proves the process stops. That the app got
  a console break (Windows) or SIGTERM (Linux) first is proved by
  `tests/test_app_accounts.py` on this box and on Linux CI, not on a
  runner's service.
- **An agent restart with apps running** (the app is kept, its admin token
  taken back). Unit-tested only.
- **The installs that cannot make accounts** (per-user Windows, Linux
  `--user`, macOS): an app with `localActions` true is refused there.
  Unit- and UI-tested; a per-user install on a runner is a later run.
- **What else on the machine the account can read.** The probe walks the
  install's prefix. On Linux `ProtectHome=yes` hides `/home` and the system
  is read-only to a dynamic user. On Windows a virtual account can read
  what any local account can (`C:\Users\Public`, for one); that is outside
  what this slice set out to protect.
- **An app installed before C1** on an install that later gains accounts:
  its key has no `writeLogs`, so its output is refused at the ingress until
  the app is installed again. Nothing released has apps, so there is no
  migration.

## Local evidence before the pin

- agent 1,536 tests, mypy clean for Windows and Linux; control 267,
  gateway 1,041, ui 1,579.
- `install.sh`: `r37-install-sh-checks.sh` 97/97 and `r37-sabotage.py`
  13/13 in WSL. `install.ps1`: Pester 62/62.
- Every script specs CI runs (23), against these checkouts: all pass.
  `s10-checks` failed the first time: its guard expects `if ($Isolated)`
  in `install.ps1`'s first 180 lines, and the module-path fix had pushed it
  down. The fix now sits below that guard.

## After the pin

- The C1 run on the pins themselves, no candidate overrides (run
  36870493798): 42 of 42 on each runner.
- specs CI green on `ca61b76`. The container image's acceptance failed
  once on check 18 (on stop, only one of the three children logged its
  shutdown). The rerun passed 29 of 29, so it is a timing flake, like
  p3-audio's 503 in A4.
