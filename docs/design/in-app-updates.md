# In-app updates

**Status: built 2026-09-27.** Troy's brief: *"let Eugene check for updates
periodically, and apply them within the app. My NAS is updated, I'd like to
force update my Amish_Station from the NAS UI."*

All four calls went as recommended (§2). Troy also asked three questions that
changed the shape:
- where the version is kept, which is now in the code (§1.1);
- the channel names, which are now `edge` and `releases` (§1.2);
- advice for container hosts other than Unraid (§1.5).

Record: `docs/acceptance/updates-run.md`.

---

## 0. What existed, measured before anything was designed

- **An installer run over an existing install is already an upgrade.** Both
  installers stop the running agent, reinstall the six packages at their
  pins, re-register autostart and start it again. Nothing new was needed to
  *perform* an upgrade. What was missing was starting one from the app, and
  knowing when one was due.
- **No install knew its own version.** Every package reports `0.1.0`, the pins
  lived only in the installer that ran, and the container image recorded
  none of them.
- **An updater cannot be the agent's child.** The agent puts every child in a
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` job, and an upgrade starts by stopping
  the agent.
- **Who may write the code differs by install:**
  - The Windows service runs as LocalSystem, and a per-user Windows install as
    the person; each can rewrite its own prefix.
  - A Linux system install runs as its own account, which owns its prefix, venv
    included.
  - The container can never update itself: an update is a new image.

---

## 1. What was built

### 1.1 The version is in the code

Troy's instinct was a value baked into the code rather than a record file,
and it is. Each package has a `_build.py`:

```python
COMMIT = "$Format:%H$"
```

It is marked `export-subst` in the package's `.gitattributes`. GitHub builds
every source archive with `git archive`, which replaces the placeholder with
the commit. This was verified on GitHub's real archives: the agent at
`76a4cdc` and the UI `dist` branch at `645ab74` each carry their own commit.

The installers install nothing else. So the version is written by git, not by
anything of ours, and there is no file to edit.

**Why this beats a record file.** The threat is the same either way: anyone
who can edit a file in the prefix can edit the code beside it. The real
difference is that this reports what was *actually* installed. An upgrade
that half-failed (the 2026-09-15 file-in-use case) keeps the old commit, so a
mixed install is visible as one. An installer-written record would have
claimed the new version.

The agent reads all six from its own venv, as text rather than by importing.
`GET /v1/node` carries them as `install`, each component one of:
- `stamped`, with its commit;
- `development` (a git checkout);
- `unrecorded` (installed before 2026-09-27);
- `missing`.

### 1.2 Two channels: `edge` and `releases`

- **`edge`** (Troy: the name the container already uses) is the head of
  `main`, gated. It is the newest `main` commit on which every workflow that
  ran succeeded, CI among them.

  The container workflow runs only when the image's inputs change, so a
  commit it did not run for changed nothing in the image. This is the commit
  the `:edge` image was built from, so a native install is never offered an
  update the container was not given.
- **`releases`** is the newest published release, prereleases included. It is
  read from the release's own `manifest.json`, and the installer is checked
  against the checksums that manifest publishes.

An unset `updateChannel` follows what the machine was installed from:
- `releases` when its six commits are exactly one of the five newest
  releases;
- a container's own image tag;
- `edge` otherwise.

### 1.3 The check

- **When:** a minute after boot, every six hours, and on
  `POST /v1/node/update/check`.
- **Never on `GET /v1/node`,** which every console polls; that reads the last
  result.
- **Failures** go through the engine release list's `describe_fetch_failure`,
  so a failed check names its cause (rate limit, certificate, timeout).
- **Kept result:** the last good answer stands through a failed check.
- **Settings:** `updateChecks` (on by default; nothing is installed without a
  click) and `updateChannel`, on Config → Agent → Updates.

### 1.4 Applying one

`POST /v1/node/update {target}` is operator-only, reached from any console
through `node:<name>`. **`target` must be the ref this agent itself found**,
so a click is never an update to something the person did not see, and a
caller cannot name anything else.

| Install | Started as | Runs |
| --- | --- | --- |
| Windows service | one-shot scheduled task, **as SYSTEM** | `install.ps1 -Update` |
| Windows per-user | one-shot scheduled task, as the person | `install.ps1 -NoService -Update` |
| Linux per-user | `systemd-run --user` transient unit | `install.sh --user --update` |
| Linux system | a request file; root's `eugene-plexus-update.path` | `install.sh --update`, by a root helper |
| container | refused, with the steps (§1.5) | — |
| macOS, or nothing starts it | refused, with the installer command | — |

On Windows the task runs PowerShell from Windows itself, never Python from the
install: the installer stops every process running from inside the install
folder.

Running the wrapper for real found PowerShell 5.1's `Start-Process` splitting
a folder name with a space in it, so the installer never ran. The arguments
are quoted by hand now.

**`-Update` / `--update`** replaces the packages, refreshes the service host
(`winservice update`) and starts Eugene again. It keeps everything else about
the install as it is:
- its autostart and the tray icon;
- who may start and stop the service;
- the folder's permissions and its unit.

Run as SYSTEM, an ordinary run would have re-registered those for SYSTEM. It
refuses anything that is not already an install, and refuses an autostart that
runs a different install. The second guard was added after the first version
was found able to re-point this machine's live service at another folder.

**The Linux system install's root helper follows one rule: root never runs,
and never writes through, anything the Eugene account controls.** The account
owns the prefix, so it could plant code for root to run, or plant a symlink
for root to write through. So the helper:
- is root-owned and lives outside the prefix, at
  `/usr/local/lib/eugene-plexus/update`;
- reads the request as the account (`runuser`);
- accepts only a 40-hex specs commit or a `v*` release tag;
- downloads our installer for it into a root-only staging folder;
- checks it against the release's `SHA256SUMS` when there is one;
- runs it;
- has the account copy the record back.

A compromised account can still ask for any *published* specs commit, which
is a downgrade, not code of its own. That is the accepted cost.

The wrapper writes `update/last.json` (target, times, outcome, and on a
failure the installer's last lines). The agent that comes back reports it,
and an update that never reports back becomes a failure after 45 minutes.

### 1.5 A container is told how, in its platform's words

From inside a container nothing reliable says what launched it, so a template
we write says so: `EUGENE_PLEXUS_CONTAINER_HOST=unraid` in the Unraid
template, and `compose` in `docker/compose.yaml`. The steps then read:
- **Unraid:** Docker tab → Force Update.
- **Compose:** `docker compose pull && docker compose up -d`.
- **Anything else:** general Docker. Pull the image, recreate the container
  with the same `/data` and `/models`, or use Portainer, Synology, TrueNAS or
  a similar tool's re-pull button.

A container pinned to a release is told to change its tag to the new release
first, since re-pulling the same tag gets nothing. The image reports its own
name (`EUGENE_PLEXUS_CONTAINER_IMAGE`, a build argument CI sets).

An existing Unraid container gets the general steps until the new template
field is added by hand: dockerMan does not merge new template fields.

### 1.6 The page

**Nodes → Versions** shows a card per machine: what it runs, whether a newer
version is out, and when it last looked.
- **Update** asks first and says what it costs: that machine's Eugene
  restarts, and its models stop for a minute or two.
- **Through the restart,** the card keeps saying "Updating" until the machine
  reports back.
- **Check now** runs the check on that machine.

**Issues** gains three kinds: an update is ready; the last update did not
finish, in its own words; and machines on different versions when none is
simply behind.

---

## 2. The calls (all taken as recommended, Troy 2026-09-27)

| # | Question | Taken |
| --- | --- | --- |
| 1 | What does "update" install? | The newest on the node's own channel. |
| 2 | Linux system installs | A root oneshot unit plus a path trigger, set up by the installer. |
| 3 | Apply automatically? | Not now: check automatically, apply on a click. |
| 4 | Machines on different versions | Warn, do not block. |

---

## 3. The first update is by hand

An install made before this has no `POST /v1/node/update` to call. Run the
installer on it once, the same one-line command, and it can update itself
from then on.

## 4. Not in scope

- Rolling engine (llama.cpp) upgrades (`project_open_threads`).
- Downgrade or rollback, which `docs/recovery.md` covers by hand.
