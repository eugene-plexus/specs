"""Folders after a mount changes: put each hole back and prove a check notices.

2026-09-27. Troy set a Library folder's Windows mount and was told "Nodes
pick the change up at their next launch", read it as "reboot every node",
and found his worker refusing the model anyway. Two things were built:

* the page names the running models still on the file they opened before
  the change (`Runtime.openedPath` beside `localPath`) and restarts them from
  whichever console is open, through `node:<name>`;
* a machine that could not read the Library's folders says why
  (`LibraryFolderReach.libraryError`), and a refusal that applied no
  folder's mount says the folders were unread instead of telling the
  operator to set the mount they already set. The live worker could not
  read them because the container's control host was registered at
  127.0.0.1.

Restores from a COPY, never `git checkout --`, and opens with a baseline
assertion that every gate passes unsabotaged (memory:
`sabotage-runs-restore-from-a-copy`).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
PLANNER = ("agent", "src/eugene_plexus_agent/runtimes.py")
ROUTES = ("agent", "src/eugene_plexus_agent/routes/runtimes.py")
FOLDERS = ("agent", "src/eugene_plexus_agent/library_folders.py")
ADMISSION = ("agent", "src/eugene_plexus_agent/admission.py")
STALE = ("ui", "src/lib/stalePaths.ts")
REACH = ("ui", "src/lib/libraryReach.ts")
PAGE = ("ui", "src/components/LibraryFolders.tsx")
TIMEOUT = 900

SABOTAGES: list[tuple[str, tuple[str, str], str, str]] = [
    # --- the agent: what a running process opened ------------------------------
    (
        "openedPath records the Library's spelling, not the file opened",
        PLANNER,
        "self.opened_path = launch_spec.modelPath",
        "self.opened_path = self.spec.modelPath",
    ),
    (
        "a crashed runtime still reports a file open",
        PLANNER,
        "planner.opened_path if planner is not None and status in _PROCESS_RUNNING else None",
        "planner.opened_path if planner is not None else None",
    ),
    (
        "a restart opens the model through the old copy of the folders",
        ROUTES,
        "    # folders as they are now, which is usually why someone pressed it.\n"
        "    await refresh_library_folders(request)\n",
        "    # folders as they are now, which is usually why someone pressed it.\n",
    ),
    # --- the agent: why the folders were not read ------------------------------
    (
        "the lookup's reason is dropped",
        ROUTES,
        'request.state.library_unavailable = f"The install\'s Library could not be found: {exc}"',
        "request.state.library_unavailable = None",
    ),
    (
        "the refresh does not keep the reason it was handed",
        FOLDERS,
        "            cache.note_failure(unavailable)\n",
        "            pass\n",
    ),
    (
        "a successful read keeps the old failure",
        FOLDERS,
        "        self._failure = None\n        self._folders = list(folders)",
        "        self._folders = list(folders)",
    ),
    (
        "the Folders check leaves the reason out",
        FOLDERS,
        "libraryError=None if library_consulted else cache.failure,",
        "libraryError=None,",
    ),
    (
        "admission is never told the folders were unread",
        ROUTES,
        "folders_unread = None if consulted or cache is None else cache.failure",
        "folders_unread = None",
    ),
    (
        "the refusal tells the operator to set the mount they already set",
        ADMISSION,
        "if location.mapping is None and folders_unread:",
        "if False:",
    ),
    # --- the page --------------------------------------------------------------
    (
        "a model is compared with its declaration, not with what it opened",
        STALE,
        "r.openedPath && r.localPath && r.openedPath !== r.localPath",
        "r.localPath && r.modelPath !== r.localPath",
    ),
    (
        "the restart goes to this machine, not the model's",
        PAGE,
        "await api.post(m.target, `/v1/runtimes/",
        'await api.post("agent", `/v1/runtimes/',
    ),
    (
        "the page never reads what is running when it opens",
        PAGE,
        "      void readRunning(node);\n",
        "",
    ),
    (
        "a folder save does not look for models left on the old file",
        PAGE,
        "await Promise.all(nodes.map((node) => readRunning(node)));",
        "await Promise.resolve();",
    ),
    (
        "an override save does not look for models left on the old file",
        PAGE,
        "        await readRunning(selectedNode);\n",
        "",
    ),
    (
        "a machine that could not read the folders is not named",
        STALE,
        "reach && !reach.libraryConsulted && reach.libraryError",
        "reach && reach.libraryConsulted && reach.libraryError",
    ),
    (
        "a machine that could not read the folders is promised the next start",
        STALE,
        "const silent = checks.filter((c) => c.reach === null)",
        "const silent = checks.filter((c) => !c.reach?.libraryConsulted)",
    ),
    (
        "the cell of a machine that could not read the folders is grey",
        REACH,
        'tone: !reach.libraryConsulted && reach.libraryError ? "error" : "unknown",',
        'tone: "unknown",',
    ),
]

FILES = sorted({target for _, target, _, _ in SABOTAGES})


def run(repo: str) -> tuple[int, str]:
    if repo == "ui":
        argv = [
            "npx.cmd",
            "vitest",
            "run",
            "src/lib/stalePaths",
            "src/lib/libraryReach",
            "src/components/LibraryFoldersRestart",
        ]
    else:
        py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
        argv = [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
        argv += [
            "tests/test_runtime_end_to_end.py",
            "tests/test_library_folders.py",
            "tests/test_storage_separation.py",
        ]
    try:
        done = subprocess.run(
            argv,
            cwd=ROOT / repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    only = sys.argv[1:]
    sabotages = [s for s in SABOTAGES if not only or any(o in s[0] for o in only)]
    repos = sorted({repo for _, (repo, _), _, _ in sabotages})
    backup = Path(tempfile.mkdtemp(prefix="folders-restart-sabotage-"))
    for repo, relative in FILES:
        destination = backup / repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")
    for repo in repos:
        code, out = run(repo)
        print(f"[baseline {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, (repo, relative), old, new in sabotages:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8", newline="").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="").write(source.replace(old, new, 1))
        try:
            code, _ = run(repo)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1
    print(f"\n{caught} caught, {escaped} escaped, {len(sabotages)} sabotages")
    for repo in repos:
        code, out = run(repo)
        print(f"[restored {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
