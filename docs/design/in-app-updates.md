# In-app updates

**Status: designed 2026-09-27, not built.** Troy's brief: *"let Eugene check
for updates periodically, and apply them within the app. My NAS is updated,
I'd like to force update my Amish_Station from the NAS UI."*

---

## 0. What exists, measured before anything is designed

- **An installer run over an existing install is already an upgrade.** Both
  installers stop the running agent, reinstall the six packages at their
  pins, re-register autostart and start it again (`install.ps1` step 3,
  "Stop a running install before replacing its files"). Nothing new is
  needed to *perform* an upgrade. What is missing is starting one from the
  app, and knowing when one is due.
- **No install knows its own version.** Every package reports `0.1.0`
  (`agent/__init__.py`, `pyproject.toml`). The pins live only in the
  installer that ran, and the container image records none of them
  (`docker/Dockerfile` runs `install.sh`, writes no record, has no build
  label). So today neither a node nor the UI can tell two installs apart.
- **An updater cannot be the agent's child.** The agent puts every process it
  spawns in a `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` job (`orphan_kill.py`),
  and the installer's first act on an upgrade is to stop the agent. A child
  would be killed by the thing it is updating. It has to start outside the
  agent's process tree.
- **Who may write the code differs by install.**
  - The Windows service runs as LocalSystem and can rewrite its own prefix.
  - A per-user Windows install (`-NoService`) runs as the person, and its
    prefix is theirs.
  - A Linux system install runs as its own account, deliberately unable to
    write the code it runs (row 2, install permissions).
  - A `--user` Linux install is the person's.
  - The container cannot update itself at all: its code is the image, and
    Unraid's Force Update is a `docker pull`.

---

## 1. The shape proposed

1. **An install record.** Both installers, and so the image, write
   `<prefix>/install.json` holding the six pins, the channel it came from
   (`main` or a release tag) and when. The agent reports it on
   `GET /v1/node` as `install`, and says `container: true` in the image.
2. **A periodic check.** Each agent reads its channel's newest pins, from the
   installer at that channel's URL or a `pins.json` published beside it.
   It does this at start, then every 6 hours with back-off, and compares.
   `GET /v1/node` gains `update: {available, newest, checkedAt, error}`. It
   uses the egress client, so it goes through the user's proxy. It has an
   off switch on Config → Agent (GUI equality).
3. **Apply from any console.** `POST /v1/node/update` is operator-only and
   reaches any node through `node:<name>` (one console, never hop). The
   agent:
   - downloads the channel's installer into `<prefix>/update/`;
   - registers a one-shot scheduled task to run it outside its own job, as
     SYSTEM for a service install and as the person for a per-user install;
   - returns `202`.

   The installer stops the agent, upgrades, starts it, and writes
   `<prefix>/update/last.json`: from, to, and the outcome or the reason it
   failed. The agent reports that record after it restarts. Every runtime
   on that node stops across the update, and the button says so first.
4. **What the UI shows.**
   - Each node's version and whether it is behind.
   - An Issues row: "Amish_Station is behind the rest of the install",
     with Update as its action.
   - The container node's row points to Unraid's Force Update instead of a
     button, because that is the only thing that can update it.

---

## 2. The calls, with a recommendation each

| # | Question | Recommendation | The other side |
| --- | --- | --- | --- |
| 1 | What does "update" install? | **The newest on the node's own channel** (`main` for Troy's installs, the latest release tag for a release install). That is the ordinary meaning, and the two coincide right after an update. | *"Match the control root"* pins a worker to exactly what the NAS runs, which needs a pin override on the installer (installing any `eugene-plexus` commit an operator names). That is stronger against version skew and weaker against "the NAS is itself behind". |
| 2 | Linux system installs, whose code the service account cannot write | **A root oneshot unit plus a path trigger** that the installer adds. The agent writes a request file; root runs the installer. | Build Windows and the container first, and on Linux show the exact `sudo` command to paste. That is less work, but not "within the app" for Linux. |
| 3 | Apply automatically? | **Not now.** Check automatically, apply on a click. An update restarts every model on the node. | An "install updates at 3 am" toggle, later, once a failed update is known to restore itself (the join path already does). |
| 4 | Channel mismatch across nodes | **Warn, do not block.** An Issues row when a node's pins differ from the control host's. | Refusing mixed versions would strand a node that cannot update itself (the container). |

---

## 3. Not in scope

- Rolling engine (llama.cpp) upgrades are a separate thread
  (`project_open_threads`).
- Downgrade or rollback, which `docs/recovery.md` covers by hand.
