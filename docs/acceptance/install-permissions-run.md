# Install permissions: another account on the machine (2026-09-24)

**What was wrong.** Measured on the live Windows service install, ACLs only
(the file was never opened):

| Path | Grant | Meaning |
|---|---|---|
| `C:\ProgramData\EugenePlexus\node.yaml` | `BUILTIN\Users:(I)(RX)` | every local account can read the install's signing key, which mints operator tokens for every node |
| `C:\ProgramData\EugenePlexus` | `BUILTIN\Users:(I)(CI)(WD,AD)` | every local account can add files and folders anywhere under the prefix; a `.pth` in the venv runs as LocalSystem at the next start |
| `%LOCALAPPDATA%\EugenePlexus\node.yaml` (the pre-service install, left behind) | `CodexSandboxUsers:(I)(M,DC)` | a sandbox group can read and rewrite a copy of the key |

All of it is inherited: `%ProgramData%` hands it to every folder under it, and
the profile hands the sandbox group's grant to everything in
`%LOCALAPPDATA%`. `_private_files` in the agent, control and the library makes
secrets owner-only on POSIX and calls the Windows half "the installer's
business"; no installer had done it.

**Scope, as decided (Troy, 2026-09-24):** other accounts on the machine. Not
a Windows administrator or root, which no ACL stops, and not a program running
as the agent's own account, which can read the agent's memory as easily as its
files.

## What was built

- **`install.ps1` `Protect-InstallDirectory`** (specs): the prefix gets a
  protected ACL with nothing inherited, SYSTEM and Administrators in full, and
  on a per-user install the person. A service install opens three doors:
  - Users may list the prefix itself, this folder only, so a non-elevated
    re-run still detects the install;
  - Users may read `venv\` and `pythons\`, for the tray icon;
  - the installing person may change `models\`.

  It is called before anything else is written and again after step 5. It is
  never fatal.
- **Agent `install_permissions`** (agent `7de79f2`): at startup, off the event
  loop, it reads the ACLs of the config directory, `node.yaml`, `agent.yaml`
  and both interpreter prefixes. It names every account outside this one,
  SYSTEM and Administrators that can read a secret or add a file. The result
  is a log warning plus `details.installPermissions` on `/healthz`; the status
  stays `ok`. It reports and never repairs.
- **Both installers re-pinned** to agent `7de79f2`.

## Evidence

- `agent`: `tests/test_install_permissions.py`, 14 cases. They include the
  measured ACE lists and one case against a real Windows ACL built with
  `SetNamedSecurityInfo`. The full suite gives **1137 passed, 12 skipped**;
  ruff, format and mypy are clean.
- `specs`: `scripts/install-preflight.Tests.ps1`, **17 of 17**. The
  permission cases run unelevated on real folders under `%ProgramData%`, and
  the first asserts the inherited Users grants are present before anything
  asserts they are gone. One case asserts the installer calls the function at
  both points.
- `scripts/install-permissions-sabotage.py`: **17 sabotages, 17 caught**
  across both repos, restored from a copy, with baseline and restore passes.
- Read-only against this machine's installs, the new check names exactly the
  grants in the table above, plus `Authenticated Users` add-file on the
  developer's own `agent\.venv`.

**Two gates that could not fail, found on the way:**
- Pester 3.4's `Should Be` against an array passes when every actual item is
  *in* the expected set, a subset check. SID comparisons are joined strings
  now.
- The sabotage harness first ran Pester with `-Show None`, which Pester 3.4
  does not have. The result was null, the exit code 0, and all eight installer
  sabotages "escaped". A null result or zero tests is now exit 99.

## Not done

- **Not run elevated, and not on the live install.** The service-install path
  was exercised unelevated on a folder shaped like one. Re-running the
  installer elevated on the live box is Troy's; after it, the agent's startup
  log should carry no `install permissions:` warning.
- **The PowerShell 7 branch is untested.** It uses
  `[IO.FileSystemAclExtensions]`; this box has no `pwsh`.
- **The leftover `%LOCALAPPDATA%\EugenePlexus`** keeps the sandbox group's
  grant until it is deleted. It is Troy's machine and Troy's call.
- **Files planted before the fix stay**, and a prefix a non-admin created
  before the first install keeps that user as its owner. Owners keep
  `WRITE_DAC`, and nothing here resets ownership.
- **Not surfaced in the UI.** The warning is in the log and on `/healthz`
  only.
- **Linux and macOS are unchanged.** The agent, control and library already
  create their secrets 0600.
