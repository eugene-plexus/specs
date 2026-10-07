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

**Superseded 2026-09-30** ([`settings-accuracy.md`](settings-accuracy.md),
decisions 1-6): `updateChannel` has a default, `releases` (the `:edge` image's
environment says `edge`), and is never inferred. An install that never saved
one keeps, once, the channel this rule gave it, and only a **newer** version is
ever offered — each part placed by commit date. The rule it replaced, kept for
that one settling (`updates.channel_before_default`): an unset `updateChannel`
followed what the machine was installed from:
- `releases` when its commits are exactly one of the five newest releases;
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
- **At Update confirmation (2026-10-04):** the console checks the selected
  machine's channel again and submits that newly returned target. The agent
  checks once more before starting. A failed final check installs nothing;
  a target that changes between those calls is refused and shown for the
  next attempt. The kept result is for display, never a fallback installer.
- **Settings:** `updateChecks` (on by default; nothing is installed without a
  click) and `updateChannel`, on Config → Agent → Updates.

### 1.4 Applying one

`POST /v1/node/update {target}` is operator-only, reached from any console
through `node:<name>`. **`target` must be the ref this agent itself found**,
and the final channel check must still name that ref. The confirmation says
it uses the newest version on the machine's channel; a caller cannot supply
an arbitrary version or installer URL.

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

It also keeps the install's port, read from where the autostart keeps it (the
unit, the plist, the service's registry entry, or the account variable a task
reads), never from the update's own environment. The live run found the
Linux half waiting on 8079 for an install on 8179, and on Windows the same
mistake would have moved a service's port.

**The Linux system install's root helper follows one rule: root never runs,
and never writes through, anything the Eugene account controls.** The account
owns the prefix, so it could plant code for root to run, or plant a symlink
for root to write through. So the helper:
- is root-owned and lives outside the prefix, at
  `/usr/local/lib/eugene-plexus/update`, and is replaced by renaming a new
  file into place, since the installer it runs rewrites it;
- sets `HOME`, which systemd gives a unit with no `User=` none of;
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

**Shared status (2026-10-04).** Machines, the header's Needs Attention list,
and Home subscribe to one browser snapshot and one poll. A Check now, update
completion, configuration write, or return to the tab refreshes that shared
snapshot. A write during an outstanding read queues a subsequent read; an
older response cannot restore a warning after the fix has been observed.
The poll pauses while the tab is hidden and speeds up while Machines watches
an update. It is disposed when the last consumer leaves.

Version differences compare full stamped commits for components present on
multiple machines, including UI-only releases. On a mismatch, enabled checks
older than a minute are refreshed through each machine's existing update-check
endpoint. Automatic retries are spaced by at least five minutes per machine;
Check now remains available. Disabled checks, development checkouts and
running updates are respected. This never applies an update.

A mismatch is not proof that an update is available: machines can follow
different channels, and the Edge image can publish before the remaining
native release checks finish. Machines displays the same mismatch explanation
as Needs Attention, with “No newer update found” instead of “Up to date” for
those cards. A failed check is not an all-clear. Only the agent's verified
update target enables Update; the existing fresh check on confirmation and
the agent's refusal to downgrade still apply.

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

---

## 5. Edge as a published marker (BANKED 2026-10-07 by Troy: a sketch for later, not started; the calls below were never put)

**Why.** On 2026-10-07 every node named `d8975ed` (2026-09-28) as edge, read
itself as newer and offered nothing: each node computes edge from GitHub's run
history, and the filtered listing it read was nine days behind the unfiltered
one. Agent `44c9391` patched the read, but every node still recomputes edge
from a list GitHub builds lazily, and two agents can disagree. Troy's idea:
make edge a fact published once, not a computation done everywhere.

**The shape.**

- **A branch `edge` in this repository**, fast-forwarded by one workflow,
  `edge.yml`. Nothing else writes it. A ruleset on `edge` forbids force-push
  and deletion, so the server itself refuses any move that is not forward.
- **The rule is today's, unchanged:** the newest `main` commit on which every
  workflow that ran on push concluded `success` on its latest attempt, CI among
  them. A re-run that passes (A4's flake, specs #16) moves it. A run started by
  hand (`workflow_dispatch`) neither gates nor counts, as today.
- **Evaluated from per-commit facts, not a filtered list.** The candidates are
  `main`'s own history (`git log --first-parent`, from git, not an index),
  newest first, down to the current marker. Each candidate's runs come from
  `actions/runs?head_sha=` and are checked against the commit's own check
  suites (`commits/{sha}/check-suites`, app `github-actions`): a suite with no
  run in the list means the list is behind, and the commit waits for the next
  evaluation. Measured 2026-10-07 on `213698c` and `88699c7`: one suite per
  run, and A4's second attempt shows `success` in both.
- **When it runs:** on completion of each push-triggered workflow
  (`workflow_run`, filtered to `main`, event `push`, this repository), daily
  (so a dropped event heals within a day), and by hand. One at a time
  (`concurrency`, never cancelled). While a check is still running it exits
  green with "nothing to move", so the intermediate evaluations do not paint
  commits red.
- **It fails visibly** (GitHub mails the owner) only when it should have moved
  and could not: a push refused, the image retag failed, or the newest green
  commit is newer than the marker after it ran.
- **Fork safety:** candidates come only from `main`'s history. The event
  payload only says "evaluate now"; nothing from it is promoted or executed.
- **A CI check** fails if a workflow that runs on push to `main` is missing
  from `edge.yml`'s `workflow_run` list (otherwise the marker would wait for
  the daily run after that workflow finished last).
- **The agent** (`updates.newest_edge`) reads `GET commits/edge` (one API call,
  cached 60 s, instead of today's runs list plus `commits/main`), then
  `install.sh` at that commit for the pins, as today. It does not recompute.
- **The image** (call 6): `container.yml` pushes only `:sha-<commit>`, and
  `edge.yml` retags `:edge` to the image of the newest commit at or before the
  marker that has one. A registry-side retag of the bytes that passed, not a
  rebuild. The newest such commit is the right image even when the marker's
  own commit built none: a commit that ran no container workflow changed no
  image input.

**The calls.**

| # | Question | Recommended | Against it |
| --- | --- | --- | --- |
| 5 | What is the marker? | A branch `edge`, fast-forward only, guarded by a ruleset. Forward-only is enforced by the server, not by the workflow's care. | A force-moved tag `edge` reads as a version and breaks git's "tags do not move" (a clone that fetched it keeps the old one). A JSON file needs a commit or a Pages deploy per move and a third thing to keep consistent. The branch shows GitHub's "recent pushes" banner. |
| 6 | Does the image move with the marker? | Yes: `:edge` is retagged by `edge.yml`, so an Unraid pull never gets an image whose CI failed, and the container's Versions card agrees with every native node exactly. | Today `:edge` moves when the image's own checks pass; it can be ahead of native edge (`88699c7`: image pushed, CI cancelled). Changing it touches the container workflow. |
| 7 | When the marker cannot be read | Nothing is offered, and the check says why ("the edge marker is missing"). No fallback computation: one source of truth. | A fallback to `44c9391`'s computation keeps working through a GitHub outage of one endpoint, at the cost of two answers that can disagree, which is what failed. |
| 8 | Older agents | Nothing beyond `44c9391` (already pinned): each reads the marker after its next update. Four machines exist. | The console could flag a node whose reported edge is older than another node's on the same channel ("this machine's update check is out of date"). A UI change for a case that ends with one update. |
| 9 | The README and `tailnet.md` one-liners | Install from `specs/edge/...` instead of `specs/main/...`, so a fresh install gets the gated build. The installers' own `INSTALLER_URL` stays `main` (update mode installs a named commit). | Installing a candidate pin before its checks finish then needs the `main` URL typed by hand. |
| 10 | Monitoring | The daily run fails if the newest green commit on `main` is newer than the marker after it tried. | No monitor: a stuck marker shows only as "no update offered". |

**The test plan** (testing policy): the evaluator is a script
(`scripts/edge_marker.py`) with fixture tests (green, running, red, cancelled,
re-run, suite missing from the list). The real environment is GitHub: a trial
branch whose workflow runs on `push` moves a separate ref, `edge-trial`, and
reports its verdict on `213698c`/`299ff5a` (moves), `88699c7` (CI cancelled)
and `14b1998` (CI failed); then, on `main`, the real marker moving on the next
commit's last completion. The agent's reader gets its unit tests and sabotage of
the reader only.
