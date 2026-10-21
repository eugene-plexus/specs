# Row 6: Cut a patch release from a release tag while `main` has moved

Lane OPS. Risk: **high** (release gate). Size: S-M. No contract change.

## 1. What the row delivers

- `python scripts/release-line.py open v0.3` creates `release/v0.3` in specs and in every component, at the commits the `v0.3.0` tag pins. Each gets a worktree under `D:\py\eugene-plexus-release\v0.3\<repo>`.
- `release-line.py pick v0.3 agent:<sha>` cherry-picks fixes already on `main` onto the line, with `-x`.
- `release.py v0.3.1`, run from the line's specs worktree, qualifies, tags and publishes from `release/v0.3` with today's phases and gates.
- Edge never moves. No `main`, `dist` or `edge` ref changes, except one docs-only commit on specs `main` at the close (the notes and the run record).
- Only the newest line is patched, to its next number. Anything else stops with a named cause.

## 2. The design

**Why a line directory.** `ship.py` sets `ROOT = SPECS.parent`, and `current_pins()` reads the agent checkout's HEAD. A directory of worktrees on `release/vX.Y` makes every helper read the line's pins without a new parameter. `release.py` is in patch mode when the specs branch is `release/vX.Y`.

**`scripts/release-line.py` (new).**
- `open`: read the newest tag's pins (the manifest, `install.sh`, the agent's Workbench and site-host pins). ui and Workbench start at their dist commit's `main` parent. Push each missing branch, add the worktrees, and run `npm ci` in ui and `workbench/web`.
- `pick`: refuse a commit not on `origin/main` ("fix it on main first"). Skip one the line already holds. On a conflict, abort and exit 2, naming the files.
- `close`: remove the worktrees and keep the branches.

**`release.py` in patch mode.**
- **preflight.**
  - The version must be the latest release's `vX.Y.(Z+1)`. Otherwise: "v0.3.1 must follow v0.3.0, the latest release; older lines are not patched".
  - Each worktree HEAD equals `origin/release/vX.Y`.
  - Each moved head's CI rollup is SUCCESS. When it has none, dispatch `ci.yml --ref release/vX.Y` and wait.
  - The `main == Edge pin` check is skipped.
- **candidate.**
  - The console is built from ui's line head. The dist commit's parents are the tag's ui pin (not `origin/dist`) and its source. It is pushed to ui's `release/vX.Y-dist`.
  - Workbench, when it moved: the same, plus the catalogue pin on the agent's line.
  - Manifest, installers and `release-inputs.py`, then push `HEAD:release/vX.Y`.
  - A dependency change stops, naming `--resolve`.
- **evidence, qualify, tag, image, publish, website.** Unchanged. The record is pushed to the line. The tag names the line's record commit. `--latest` is correct, because only the newest line is patched.
- **close.** The publication section goes on the line. `push_docs_to_main` then commits the notes and record, read from the tag, to specs `main`. It first asserts that the diff is under `docs/` only.

**One push guard.** Every push goes through `push(repo, src, ref)`. In patch mode it refuses `main`, `dist` and `edge`, apart from `push_docs_to_main`. Patch mode never calls `ship.publish_dist` or `ship.pin_in_agent`.

**Failures, each naming the cause and the next command.**
- "agent: cherry-pick of abc1234 conflicts in src/x.py; resolve it on release/v0.3, then rerun."
- A red head: the repository, the commit and the run URL.
- A non-docs path at the close: the push is refused, naming the paths.
- "no release/v0.3 in agent; run release-line.py open v0.3."

**Defaults.** Patch from the newest tag only, with picks from `main` only. Edge is not paused: `edge.yml` advances only from `main` history.

## 3. Repositories and files

specs only:
- `scripts/release.py`, `scripts/test_release.py`;
- new `scripts/release-line.py`, `test_release_line.py`, `release-patch-acceptance.py`;
- `.github/workflows/ci.yml`, one step;
- `docs/design/release-script.md`, a "Patch releases" section;
- `docs/maintenance/testing-and-release.md`.

No codegen.

## 4. Tests that fail before the change

- `scripts/test_release.py::test_a_patch_never_pushes_main_dist_or_edge`. Every `git push` is recorded. After candidate, record and tag in patch mode, only `release/v0.3`, `release/v0.3-dist`, `release-candidate/v0.3.1` and tag `v0.3.1` were pushed. Today, candidate pushes `HEAD:main` and `refs/heads/dist`.
- `test_patch_version_must_follow_the_latest`: `v0.3.2` after `v0.3.0` exits 2, and so does `v0.2.4` while `v0.3.0` is latest.
- `scripts/test_release_line.py::test_pick_refuses_a_commit_not_on_main` and `test_pick_twice_applies_once`.

## 5. CI acceptance (high risk)

**`scripts/release-patch-acceptance.py`.** Offline, in specs CI on any change to `release*.py` or `ship.py`.
1. Bare `file://` repositories for specs and the nine components, each with tag `v1.2.0`, a `main` two commits past it, `dist` branches for ui and Workbench, and `edge`.
2. A `gh` shim on PATH answers the latest release, rollups, runs, a receipt, and release create/view/download, and records every call. `registry_digest` and the evidence phase read stubs.
3. Run `open`, `pick`, then `release.py v1.2.1` through every phase.
4. Check:
   - every `main`, `dist` and `edge` ref is unchanged, except one docs-only commit on specs `main`;
   - tag `v1.2.1` names the line's record commit;
   - its installers pin the tag's commits, except the picked repositories, which are at their line heads with the `-x` trailer;
   - the shim saw one `release create`.

**One live rehearsal, by hand, recorded in `docs/acceptance/`.** It uses a throwaway version, as the `v0.0.0-rehearsal.1` trial did.
1. `release-line.py open v0.3 --rehearsal` (branches `rehearsal/v0.3`).
2. Pick one docs-only commit.
3. Run `release.py v0.3.1-rehearsal.1 --rehearsal`. `release_gate.VERSION` accepts the suffix. Only preflight, candidate, artifacts, record and qualify run, and the record says "rehearsal: no evidence run".
4. Check: a real Release qualification passes on the line with an inert receipt; no tag, GitHub release or `ghcr` version tag exists; every Edge ref is unchanged.
5. Delete the rehearsal branches.

**The reviewer should attack:**
- every `git push`, `gh` call and `ship.*` helper that patch mode can reach;
- `--from` after the tag;
- version checks: reuse, skips, older lines, a suffix without `--rehearsal`;
- whether `publish()` still binds the tag to the tested candidate;
- the ui dist parent;
- whether a rename, mode change or submodule passes the docs-only check;
- a pick that carries a dependency change past `release-inputs.py`;
- how the website archives the previous version.

## 6. Do not change

- `scripts/install.sh` and `install.ps1` (row 8).
- `ship.py`'s Edge path (W0.7). A new helper parameter defaults to today's behaviour, and `ship.py`'s tests stay unchanged.
- `scripts/s8-ui-acceptance.py` (row 2).

## 7. Size, risks, open questions

- **Size:** S-M.
- **Risk:** the evidence runs use row 2's harness. Land row 2 first.
- **Open (Troy):** patch older lines? Recommendation: no, until a supported older line exists. The updater, the website and `--latest` all assume the newest line.
- **Open (Troy):** the notes and record go to `main` as a docs-only commit. Recommendation: yes. It changes nothing Edge ships, and `main` keeps every release's docs.
