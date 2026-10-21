# One command for a release: `scripts/release.py`

Troy, 2026-10-19, after v0.3.0 took 80+ minutes of his active session, most of
it waiting: a release runs in the background, end to end, and comes back only
when it needs a judgment. Asking a session for a release is the approval to
publish the GitHub release once every gate passes (memory
`feedback_release_request_is_approval`). Edge stays ungated; component CI that
goes red on Edge is named at session start, so a release does not find it
first.

## Shape

Built like `scripts/ship.py`: one script, phases in order, each one idempotent
and resumable from a state file, stopping with a named cause on the first
failure. The session runs it in the background (`--wait`) and is woken only by
its exit.

```
python scripts/release.py v0.3.1            # every phase, stop at the first failure
python scripts/release.py v0.3.1 --dry-run  # what each phase would do
python scripts/release.py v0.3.1 --from qualify   # resume after a fix
```

State and evidence: `docs/private/release-v0.3.1/` (`state.json`, one log per
run, the packaged installers), gitignored as the earlier `release-*` folders.

## Phases

1. **preflight.** Every component's `main` equals its Edge pin (anything
   unshipped stops: run `ship.py` first); every pin's own CI is green (the
   session-start check's logic); the newest rehearsal passed or is older than
   the newest pin change; the version is new, three-part, above the last
   release; no `EUGENE_PLEXUS_*` variable in the environment.
2. **candidate.** Rebuild the console `dist` from the Edge console's source with
   `NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF=<version>` (ship.py's build, one
   env var added), check every static file against the export and that no
   `specs/main` installer reference remains; pin it; `release-inputs.py`; check
   the agent's Workbench and site-host pins against the installers. Commit and
   push `main` (Edge runs CI on it as usual; nothing waits).
3. **local evidence**, the runs CI cannot do, on this machine, isolated ports,
   ambient variables cleared, packaged installers from `release-artifacts.py`:
   - fresh install, Windows 11 and Ubuntu under WSL2 (`s10-acceptance.py`,
     seeded Gemma 4 E4B, real CPU inference);
   - in-place upgrade from the previous release on Windows with a person's data
     (`release-upgrade-acceptance.py`);
   - the Linux system install's in-app update from the previous release
     (`updates-system-install-acceptance.sh`, as root inside WSL: no UAC);
   - recovery (`a7-recovery-acceptance.py`).
   The two WSL runs and the two Windows runs go in parallel pairs.
4. **record.** Write `docs/acceptance/<version>-release-run.md` in v0.3.0's
   shape from the results: candidate pins, package hashes, the acceptance
   records added since the last tag (`git diff --name-only`), install,
   upgrade and recovery tables, and "untested paths" carried from the last
   record, minus what this run covered. The release notes are drafted from
   the same list. The session reads both before qualification; they are the
   human attestation the runbook asks for. Commit, push.
5. **qualify.** Dispatch Release qualification on `main` at that commit with
   the version and record (no tag yet); wait; on failure, stop with the
   failing jobs and their log lines. A fix is a new candidate: `--from
   candidate`.
6. **tag.** Annotated tag at the qualified commit; push it.
7. **image.** Dispatch Container image with `publish=true` and the
   qualification run; wait; confirm the registry digest anonymously.
8. **publish.** `release-artifacts.py` assets; `gh release create` as Latest
   with the notes; download every asset and match GitHub's digests; the
   previous release's installed agent (from phase 3) finds the new release in
   a read-only update check.
9. **website.** The version's data and installers; dispatch its deployment;
   check the live installers' hashes.

## Stops that need the session

A failed phase, a red component CI in preflight, a qualification failure, a
mismatch in any digest or pin. Never a stop for approval: the request was the
approval. A security or data-loss finding sets `EDGE_PUBLICATION_PAUSED` and
stops for Troy.

## What building found (2026-10-19)

- **The evidence runs are sequential**, not paired: the Windows fresh install
  and the upgrade harness both start at port 19000 and both drive the one
  Chrome. About eight minutes in all.
- **The release notes are the one piece of prose.** The record is generated
  from the results; the notes (`docs/releases/<version>.md`, the previous
  release's shape) are the session's to write. The record phase stops with
  exit 3 until they exist, so a session can write them while the evidence runs.
- **Qualification runs on a `release-candidate/<version>` branch** at the record
  commit, not on `main`: an Edge ship from another session cannot change what
  is qualified. Branch pushes run no CI. The tag is made at that commit and the
  branch deleted.
- **A runtime change after the candidate stops the record** (anything outside
  `docs/` between the candidate and `HEAD`): the evidence would no longer
  describe what is tagged. Don't ship to Edge during a release.
- **The update check needs a previous release still installed.** The upgrade
  run's prefix becomes the new release, and recovery uninstalls the gateway
  from the fresh install. The close phase uses the previous release run's
  Windows install (kept in its state file, or found under `%TEMP%`), and says
  so plainly in the record if there is none.
- **`updates-system-install-acceptance.sh` exits 0 with failed checks**; only
  its closing `ALL PASS` counts.

## What stays manual

The NAS root container upgrade (Troy's, root first; this machine has no
Docker), physical hardware outside this box, and upstream reports.

## Patch releases (row 6, 2026-10-21)

A fix for the newest release ships as its next patch while `main` has moved
on. Design: [`rows/row-06.md`](rows/row-06.md); Troy's calls PATCH-OLD
(choice 2) and PATCH-NOTES (choice 1).

```
python scripts/release-line.py open v0.3                 # release/v0.3 at v0.3.0's pins
python scripts/release-line.py pick v0.3 agent:<commit>  # a fix already on main, with -x
cd ../eugene-plexus-release/v0.3/specs
python scripts/release.py v0.3.1                         # patch mode: the line's branch
python scripts/release-line.py close v0.3                # worktrees go; branches stay
```

- **The line.** `open` makes `release/vX.Y` in specs and in the nine
  components, at the commits the line's newest release pins (ui and Workbench
  at the source their dist commit was built from). Each gets a worktree under
  `eugene-plexus-release/vX.Y/`, so `ship.py`'s `ROOT` is the line and every
  helper reads the line's pins.
- **Picks.** Only commits on `main`: "fix it on main first". A commit the line
  holds already is skipped. A conflict is aborted, and its files are named.
- **Patch mode.** `release.py` is in patch mode when the specs checkout is on
  `release/vX.Y`. The version must be the next patch of the line's newest
  release. Preflight skips the `main == Edge pin` check, and requires each
  worktree at its line head and each moved head's own CI green (it starts the
  run on the line when there is none). The candidate is the last release's pins
  plus the line's commits. The console is rebuilt from ui's line head, on the
  last release's dist (`release/vX.Y-dist`), never on `main`'s `dist`.
  Workbench is rebuilt only when it moved, and is then pinned on the agent's
  line. A dependency change stops the candidate until the lock is re-resolved
  on the line.
- **One push guard.** Every push goes through `release.push()`. In patch mode
  it moves only the line, the line's dist, `release-candidate/<version>` and
  the tag. It never moves `main`, `dist` or `edge`, except for one commit at
  the close. That commit puts the notes and the record on specs `main`, built
  without a checkout of `main`. The guard refuses it unless the commit is one
  commit on `origin/main` and adds or changes only regular files under
  `docs/`. `edge` is never pushed in any mode.
- **Older lines (PATCH-OLD).** Only the newest line is patched, unless the fix
  is a security fix: `open --security` and `release.py --security`. Without
  the flag, an older line is refused, and the message says why. The record
  names the security fix. An older line's patch is published without
  `--latest`. The website is not changed: it offers the newest line. The close
  phase runs no update check, because no updater offers that patch.
- **Rehearsal.** `open vX.Y --rehearsal` makes `rehearsal/vX.Y`.
  `release.py vX.Y.Z-rehearsal.N --rehearsal` runs only preflight, candidate,
  artifacts, record and qualify. The record says "rehearsal: no evidence run".
  `close --rehearsal --delete-branches` deletes the rehearsal's branches.
- **CI.** `release-patch-acceptance.py` runs the whole path offline in CI on
  Linux and Windows. It uses bare `file://` repositories and a recording
  stand-in for GitHub. It checks that no `main`, `dist` or `edge` ref moved
  except one documentation-only commit on specs `main`. It also checks that
  every push went to the line's refs, and that the tag names the line's record
  commit.

### What building found

- **v0.3.0 predates the tooling.** The v0.3.0 tag has no `release.py`, and its
  Release qualification requires the tag before it qualifies. `open`
  therefore commits main's release tooling onto the specs line when the
  release's own differs: `release.py`, `release-line.py`, `ship.py`,
  `release-qualification.yml` and `container.yml`. The record lists that
  commit. The acceptance scripts that the evidence phase runs stay the line's
  own.
- **The evidence phase uses this machine's harnesses.** On a clean `main`,
  s10 and the upgrade acceptance fail today (specs#97). Fix specs#97 before a
  real patch release. The offline acceptance uses stand-ins for the evidence
  phase.
- **A rerun of the candidate** builds the console on the earlier candidate's
  dist commit, which holds the last release's dist. The line's dist branch
  therefore only fast-forwards. A Workbench build of the same source is used
  again, so a rerun makes no second agent pin commit.
- **ui and Workbench CI run on a push of `release/vX.Y-dist`.** Their
  `ci.yml` ignores only `dist`. The runs are harmless, but they cost CI time
  (ui#24, workbench#18).
- **`--security` is the operator's claim.** Nothing checks that the picks fix
  a security problem. The record names the flag, so the claim is on record
  for whoever reads it.
- **Latest can change while a run waits.** A run that stops for its notes can
  resume after a newer release is Latest. `publish` and `website` read Latest
  again: a patch older than Latest is published without `--latest`, and the
  website is not changed.
- **A failed push to main stops with its cause.** At the close, only a race is
  retried (main moved after the fetch). A refusing hook, a permission error or
  a network failure stops the run and names the error.
- **The first real rehearsal is the compatibility test.** The first
  `--rehearsal` on v0.3 tests main's `release.py` with the v0.3.0 tag's other
  tooling: `release-inputs.py`, `release-artifacts.py`, the `ci.yml` that
  qualification calls, and the evidence scripts. The offline acceptance
  cannot show that.
