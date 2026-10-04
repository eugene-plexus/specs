# Windows and Mac offline removal

2026-10-04. Included in Edge installers; no published v0.1.0 release
asset was replaced, and the owner's running installation was not uninstalled.

## Behavior

Windows registers a per-install entry under Installed Apps. Mac installs a
Finder-visible removal application in the user's Applications folder. Both
launch saved local scripts. Separate unchecked choices control settings/app
data deletion and managed-download deletion, with sizes shown before removal.

The default removes owned runtimes and application versions, preserves original
model folders and personal data, and retains a small offline cleanup utility.
An inventory survives removal of Python and configuration. Follow-up cleanup
uses that inventory and remaps paths into the retained folder; it does not
recreate `agent.yaml` or operate on a new install at the former location.

Cleanup checks absolute paths and original model folders and does not traverse
links/junctions. Unknown ownership, missing Python, unreadable configuration,
credential failures and firewall failures are reported rather than silently
called success. The scripts preserve shared OS dependencies.

The old credential cleanup searched for `master-key-<fingerprint>`; both
applications actually use `master-key:<fingerprint>`. The new helper checks the
real names and the historical dash spelling, verifies deletion, and reports
exceptions. Windows service cleanup uses a temporary SYSTEM task to open the
service account's vault. Its output is written atomically, stale results are
removed before retry, and the task is removed in `finally`.

## Local checks

| Check | Result and scope |
| --- | --- |
| `scripts/uninstall.Tests.ps1` | **13/13 passed** on Windows PowerShell 5.1/Pester 3.4. Real temporary files, with services, tasks, registry and firewall actions mocked. Covers two-pass offline cleanup, cancellation, model protection, junctions, error reports, SYSTEM task selection/result handling, firewall elevation and exact embedded payloads. |
| `scripts/install-preflight.Tests.ps1` | **78/78 passed**. Existing migration, isolation, elevation, update and error-reporting behavior, plus removal dispatch. |
| `scripts/r37-install-sh-checks.sh` | **141/141 passed** under WSL. Simulated Linux, native Mac and Rosetta installer paths; the real portable Mac bundle writer runs against the fixture home. |
| `scripts/test_uninstall.py` on Windows | **7 passed, 2 platform skips**. Inventory separation, protected model roots, unreadable configuration, relative paths, actual credential names/failures and the local Mac bundle. |
| `scripts/test_uninstall.py` under WSL | **8 passed, 1 platform skip**. Also executes the real POSIX remover three times: default removal, later data/download purge without Python/config recreation, and idempotent repeat. Original model bytes survive. |
| Website | Astro check: **0 errors/warnings**; production build passed. **6 browser checks passed** across desktop and 320px layouts, including accessibility, copyable commands, JavaScript-disabled instructions and exact immutable release-asset bytes. |
| Source/package checks | Python Ruff, PowerShell parsing, POSIX shell syntax, generated-payload freshness and Git whitespace checks passed. |

CI now runs the inventory/removal suite on Windows, Linux and macOS 14/15/26.
On Mac, it also compiles every AppleScript dialog without opening one. These
new CI jobs are configured, not claimed as remotely executed in this record.

## Still to verify on desktops

- Open Windows Installed Apps, exercise the real removal window at normal and
  increased display scaling, cancel, then remove a disposable service install.
  Verify the actual SYSTEM vault entries, temporary task lifecycle, firewall
  rule and child processes are gone. Local tests mock those OS mutations.
- Open the Mac app in Finder, exercise both choices and cancellation, accept
  and refuse the firewall administrator prompt, and verify launchd and Keychain
  cleanup on a disposable installation. WSL does not establish Mac GUI behavior.
- Run the sixth task in [hobbyist sessions](hobbyist-sessions.md), including
  finding the utility unassisted and using the retained cleanup utility offline.

The older R2.2 keyring/copy checks are historical evidence, not proof of this
new workflow. The current gates above specifically avoid the old test's
recreation of configuration between uninstall and purge. The Linux
system-account removal path retains its existing behavior; these new desktop
choices also apply to POSIX per-user installations.
