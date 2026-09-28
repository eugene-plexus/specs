# In-app updates: the run

**2026-09-27.** Design: `docs/design/in-app-updates.md`.

- **Linux system install, live:** `scripts/updates-system-install-acceptance.sh`
  passes all 14 checks. It took three executions in WSL2; the first two each
  found a product defect (§2).
- **In CI:** the same script now runs on every push, in its own job, on the
  runner's systemd.
- **Sabotage** (`scripts/updates-sabotage.py`): **44 of 44 caught**, 32 in the
  agent and 12 in the UI.
- **Pester** (`install-preflight.Tests.ps1`): 62 of 62, including the port
  guard added here, whose two sabotages are both caught.
- **The Windows service path has now run once, on Amish_Station**
  (2026-09-27, owner-performed and owner-reported; §4). No script
  measured it.

| Repo | Commit | What changed |
| --- | --- | --- |
| `specs` | `a634187`, `2fccbeb` | the contract: `NodeIdentity.install` / `.update`, `POST /v1/node/update{,/check}` |
| `specs` | `4cde9a0` | installers `-Update` / `--update`, the root helper, the container's name and host, pins |
| `specs` | `c8b2d95`, `5e6a84b`, `9f2fe06` | the three fixes the live run found (§2) |
| `specs` | `d0aa2c8`, `7e1f4bd` | the run in CI, starting from the previous push |
| `agent` | `76a4cdc`, `06c321b` | the commit stamp; the check, the apply, the wrappers |
| `control`, `gateway`, `inference-driver`, `library` | `bd7c92c` / `32a110f`, `f6e0211`, `8c6f5a8`, `cec7815` | the commit stamp; control regenerated |
| `ui` | `2a43893`, dist `645ab74` | Nodes → Versions, the three Issues kinds |

---

## 1. What the run does

It runs as root in a guest with systemd, and refuses a machine that already
has an install. Each check below says what it proves.

1. **A system install, as `sudo` runs it**, on port 8179, not the default.
   With `EP_FROM`, the install is from an earlier specs commit's installer.
2. **The helper and its units are root's and live outside the prefix.**
   Checked: `root:root 755`, a `711` staging folder, the path unit enabled,
   and nothing run from the venv.
3. **`GET /v1/node` is right about the install:**
   - six `stamped` components;
   - the agent's commit is the one the installer pinned;
   - the mechanism is `systemd_system`.
4. **A request naming junk** (`../../../etc/passwd; touch /tmp/ep-pwned`) is
   refused. The record does not repeat what it named, and nothing runs.
5. **A request that is a symlink to `/etc/shadow`** reads nothing: it is read
   as the account, which cannot open that file. It is removed, and no record
   carries the file's contents.
6. **A real update.**
   - The agent says it can update itself.
   - The update is asked for through `POST /v1/node/update`, or through the
     request file the route writes, when the target is not what this agent
     found newest.
   - Root runs the target's installer, and the agent that comes back reports
     `succeeded`.
   - The install then runs **exactly the six commits the target pins**, and
     the check says how many of them moved.
7. **Everything in `update/` is the account's**, not root's.
8. **Teardown** leaves nothing behind.

## 2. What the live executions found

All three defects were in the installers. None would have shown in a unit test.

1. **systemd gives a unit with no `User=` no `HOME`,** and `install.sh` reads
   `$HOME` under `set -u`. So the first real update died at once:
   `install.sh: 74: HOME: parameter not set`, exit 2. The helper exports
   root's home now (`c8b2d95`).

   The same commit also made the helper replace itself by renaming a new file
   into place. The installer it runs rewrites the helper while `sh` is still
   reading it, and `tee` would have truncated the running file.
2. **An update waited on the wrong port.** The second execution installed
   everything, then waited for the agent on 8079 while the install listens
   on 8179. `--update` took the port from its own environment, and the root
   helper starts with none. `install.sh` now reads the port from the unit or
   plist it keeps (`5e6a84b`).

   **`install.ps1` had the same hole with a worse end.** Under `-Update`,
   `Set-ServiceBootstrap` writes the service's environment back from `$Port`,
   so a service on another port would have been moved to 8079.
   `Get-InstalledPort` now reads the service's own registry entry (or, for a
   task install, the account variable) before that write. Found by reading
   once the Linux half had failed; the Windows half has not run.
3. **A Pester anchor assumed LF,** and CI's Windows checkout is CRLF
   (`9f2fe06`). This was an instrument defect, found by CI on the fix's own
   commit.

Along the way, the container workflow on `c8b2d95` failed in the A7 recovery
check, which had not failed in the dozen runs before it. That check waited for
the runtime to be ready by asking the worker, but sent its completion to the
gateway, which learns of readiness one routing refresh later. It now waits
through the gateway's own "still coming up" for up to 60 s, and still fails
on anything else (`3773a67`).

## 3. In CI from now on

The job `Linux system install updates itself through its root helper` in
`ci.yml`:
- installs from the **previous push's** installer (`github.event.before`);
- updates to the commit under test;
- took 36 s on `7e1f4bd`.

**So a commit that moves a pin is a real version change** from the pins
before it to the pins it names, with nobody running anything. **The first one
ran on `8f2b995` (2026-09-27):** it installed from `24429e1` (agent `06c321b`),
root updated it, and 6e read *"runs all six commits 8f2b995 pins, 3 of them
new"* -- agent, control and the UI moved.

Two limits:
- **The edge gate counts this job.** A network failure in it blocks `edge`
  until the next green push.
- **It is not a pull-request gate in practice.** Work lands straight on
  `main`. For a pull request the job updates to the head commit and starts
  from the base.

## 4. What it does not prove

- **The Windows service path has run once, and only as the owner's own
  report.** That is the SYSTEM task, the wrapper and `install.ps1 -Update`
  as SYSTEM. It cannot run here from a script without touching this
  machine's live service.
  - The wrapper did run for real as a user. That found PowerShell 5.1's
    `Start-Process` splitting a folder name with a space in it, now fixed.
  - **2026-09-27, Amish_Station: Troy updated the machine from the
    console** and reported it as successful, just before the session
    that recorded it. It is the service install in
    `C:\ProgramData\EugenePlexus`, so the one-shot task ran as SYSTEM.
    Afterwards the agent answered `/healthz` `ok`. The install's
    `update\` folder, which the wrapper creates, is dated 21:54 local
    time; it is protected, so its `last.json` was not read.
  - **Not recorded:** the commits it moved from and to, its duration,
    and whether its models came back by themselves. A second update,
    with Nodes → Versions read before and after, would close those.
- **The per-user Linux path** (`systemd-run --user`) and **macOS** are covered
  by unit tests and sabotages only. macOS is refused with the installer
  command, as designed.
- **The UI was never driven in a browser.** The card, the confirm, the
  "Updating" hold through the restart, and Check now are covered by component
  and page tests (1,234 green) and 12 UI sabotages.
- **The container steps are text.** Nothing runs them. An existing Unraid
  container shows the general Docker steps until
  `EUGENE_PLEXUS_CONTAINER_HOST=unraid` is added on its Edit page, since
  dockerMan does not merge new template fields.
