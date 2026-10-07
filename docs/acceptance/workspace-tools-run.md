# 2b.3a: the workspace tools — run record

**Date:** 2026-10-07. **Design:**
[`job-sites-own-enrollment.md`](../design/job-sites-own-enrollment.md) §3.3
(the split, J67-J76, *What building 2b.3a found*). **Landed and pinned
2026-10-07**: site-host `4f6c075`, agent `9cef806` (which pins that
site host), in both installers. No new calls. Control, Workbench and the UI
are unchanged, so nothing moves on the root.

2b.3a is the tools Claude Code-style work needs, on today's grants: a reader
gets `read_text` (any part of a file), `glob` and `grep`; a writer also gets
`edit_text` (one exact passage, checked against the hash the person read).
2b.3b, each person's keys, workspaces and allow/ask/deny rules, follows.

| Repo | Commit | What |
|---|---|---|
| site-host | `4f6c075` | `workspace_tools.py` (new): ranged read, edit, the walk, `glob`, `grep`; `file_server.py`: six tools and `check_arguments`; `folder_io.py`, `folder_windows.py`, `folder_linux.py`: entries with kind, size and write time; `host.py`: readers get `glob`/`grep`, writers `edit_text`, a timed-out read *failed*; `pathspec` and `regex` |
| agent | `9cef806` | pins that site host (`SITE_HOST_COMMIT`); carries `102ef8e` (`python-multipart` declared) |
| specs | this commit | contract prose naming `edit_text` beside `write_text` (`site-host.yaml`, `components/sites.yaml`, `control.yaml`; prose only, no consumer re-pinned); `job-sites-acceptance.py`'s new `workspace_tools_check()`; `b23a-sabotage.py`; both installers |

## What was run

**Unit suites** (the site host's own venvs): Windows 276 passed and Linux (WSL,
editable) 271 passed before the escapes were closed; 24 new tests in
`test_workspace_tools.py`, and `test_host.py`'s two expected tool listings
changed. Closing the escapes added one test and widened another; that file and
`test_host.py` were re-run: Windows 46 passed (both files), Linux 25 passed
(`test_workspace_tools.py`). ruff, ruff format,
mypy and `mypy --platform linux` clean.

**`scripts/job-sites-acceptance.py --root-wsl` — 28 passed, 0 failed, 4
skipped** (203 s; the root in WSL2, the site host on Windows, the agent's
venv). The four skips are the one-account cases that need a second OS account
(the sudo run on Linux makes them). The new check:

> **2b.3a, through the root:** bo finds files by name (newest first,
> `.gitignore` and a link to outside the folder passed over), searches their
> contents with line numbers, reads any part of a 20,000-line file with the
> whole file's hash, and edits one exact passage in place; a stale hash, an
> ambiguous passage and a pattern that never finishes are refused or
> stopped, and every answer stays under 70,000 bytes.

It runs after ada gives bo write access, through `/oidc/sites/mcp`, so each
call crosses the root, the site host's held-change gate (J14a) and bo's worker.
The tool listing check now expects `glob` and `grep` for a reader.

**`scripts/b23a-sabotage.py` — 33 of 36 caught on the first pass; the three
escapes were missing tests, not product defects, and are closed:**

| Escape | Why it escaped | Now |
|---|---|---|
| a `.gitignore`'d folder is entered | the file check hid its files anyway, and the skip counts coincided | a test of git's rule: with `build/` and `!build/keep.py`, `build/keep.py` stays hidden, because git never re-includes a file under an excluded folder; checked file by file, it would come back (pathspec 1.1.1 says so) |
| a deeper `.gitignore` is not read | the nested test started *at* `src`, so `src/.gitignore` was loaded as an ancestor | the same test also searches from the top, where `src/.gitignore` is met on the way down |
| Windows: a file given as the path is walked as a folder | the sabotaged `winerror == 267` branch was dead: Python raises ERROR_DIRECTORY as `NotADirectoryError` | the branch is deleted; the entry now sabotages the `NotADirectoryError` branch that does the work |

Re-run of only those entries (`--label gitignore --label "Windows: a file"`):
**5 of 5 caught** (the three escapes, and the two other `.gitignore`
entries the label also matches), baseline and restored gates passing. With
the first pass, **36 of 36**. The acceptance was not re-run for test-only
changes and a dead branch deleted (CLAUDE.md's testing policy).

## What building found

Recorded in the design doc's §3.3; in short:

1. **The MCP SDK does not check a tool's arguments against its schema.** A
   40,000-character `oldText` reached the worker's own check. So
   `file_server.check_arguments`, which the worker runs itself, is the only
   check between a call and the folder code. Before 2b.3a the worker checked
   only the argument names and `path`'s type, and `write_text`'s
   8,192-character limit was enforced by Workbench alone; the site host's
   test for that limit passed for another reason (its call was create-only on
   a file that existed). Sabotage: *THE FINDING: the worker takes arguments
   unchecked* is caught.
2. **A full 32 KiB read could exceed the site's 70,000-byte answer.** An MCP
   answer carries the result twice, as text and as structured content, and
   escapes the text a second time: a 16,384-character file of quotes made a
   98,494-byte answer. Every tool now cuts its answer to 60,000 bytes for both
   copies, says so, and says where to read on. Sabotages *an answer is not cut
   to fit* and *the budget counts the result once* are caught.
3. **A search that ran out of time read as *it may have acted*.** The site
   host said that of every timed-out `tools/call`. A file server read or
   search now *failed*, saying so; a write still says it may have acted.

## Not done

- No browser drove the new tools through Workbench; the acceptance calls
  `/oidc/sites/mcp` directly. Workbench's tool loop, its 16,384-character
  `MAX_ARGUMENTS` (why `oldText` caps at 4,096 and `newText` at 8,192), and
  prompting are 2b.3b's.
- Not run on Amish_Station as a service; the per-user and service paths are
  unchanged by this slice, and the deploy is the agent alone.
