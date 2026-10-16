# Library startup with an inaccessible model folder

Recorded 2026-10-15. Library fix: `52877227470b8e65690f2bdedf413428a9ad9089`.

## Report and observed cause

A CachyOS user's setup screenshot showed the Library at `127.0.0.1:8082`
unreachable, both while finding the home directory and while browsing
`/home/ray/Eugene Models/`. The reported error was "All connection attempts
failed", not a filesystem permission response. No install method or logs were
available. The screenshot alone does not establish why that user's Library
failed to start.

Investigation found a matching startup defect. The Linux system installer runs
Eugene as its service account, supplies the installing user's primary group,
and defaults the model folder to that user's home. It warns when the home lacks
group traversal but does not change home permissions. On Python 3.12, the
Library's startup diagnostic called `Path.is_dir()` without handling an access
error. An inaccessible parent therefore raised `PermissionError` before the
HTTP listener started, taking the folder picker and configuration API down too.

The fix handles filesystem errors in this diagnostic, logs the path and actual
cause, and leaves the Library running. Its existing scanner and health endpoint
report the inaccessible root. Its directory endpoint returns a permission error;
the configuration endpoint can select another folder without a restart. A path
that is a regular file is now described as such. No permissions are widened and
the selected root is not silently removed or replaced.

## Validation

- Targeted Library tests: `tests/test_default_roots.py` and
  `tests/test_directories.py`, **26 passed** on Windows and **26 passed** on
  Linux with Python 3.12.14. Regression coverage includes access denied, I/O
  failure, and a regular file used as a root. The new error cases failed before
  the fix.
- Library Ruff lint and format checks passed. Mypy passed for the native and
  Linux platforms. Staged secret scanning and whitespace checks passed.
- Real Linux acceptance used Ubuntu under WSL, an ordinary non-root account,
  a temporary Python 3.12 environment, isolated configuration, and an ephemeral
  loopback port. No installed service or real home folder was modified.
- `scripts/library-private-home-acceptance.py` creates a temporary parent that
  denies traversal, verifies the OS actually returns `PermissionError`, and
  launches the production Library entry point. The service remained available,
  scanning reported `unreadable`, health reported `degraded`, and browsing the
  restricted folder returned HTTP 403 with the actual permission error.
- Updating the root to an accessible temporary folder and rescanning restored
  healthy status in the same process. The inaccessible parent's permissions and
  a sentinel file remained unchanged.
- The script's `--sabotage` option restores the old `app.py` only in a temporary
  package copy. The same startup gate caught the original crash before any HTTP
  endpoint became available. The real checkout was not reverted.
- Adversarial review checked that a failed diagnostic cannot abort startup,
  that the cause remains visible, and that recovery neither weakens permissions
  nor discards the user's configuration.

Reproduce from a Linux checkout with the Library installed editable in a Python
3.12 environment containing `httpx`; use a non-root account:

```sh
python specs/scripts/library-private-home-acceptance.py --sabotage
python specs/scripts/library-private-home-acceptance.py
```

## Scope and delivery

This reproduces real Linux filesystem denial, not a full CachyOS installation
or the reporting user's machine. Their startup logs would still be needed to
confirm the same cause. Access to the original folder still requires suitable
filesystem permissions; setup can instead choose a folder the service can use.

The Library fix and matching `main` installer pins are published together with
this acceptance record. Only the Library pin changes. The immutable v0.2.2
release assets and website installer link are not updated by a `main` push.
Installer generation, pin agreement, committed artifact checksums, and the
deliberately divergent-pin rejection were checked before publishing the pins.
