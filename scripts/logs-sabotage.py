"""Logs from the UI, and Start after a failed load: put each hole back.

2026-09-27. Troy: *"Like a Docker environment, I should be able to read
all node logs from the UI."* Each agent's one stream is now stamped at
receipt in UTC and tagged with its source, read back at `GET /v1/logs`,
followed at `GET /v1/logs/stream`, masked on the way out, and shown on a
Logs page for one machine or all of them on one timeline. And Start on a
model whose load had failed answered "already running; nothing to do".

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
RUNTIMES = ("agent", "src/eugene_plexus_agent/runtimes.py")
SUPERVISOR = ("agent", "src/eugene_plexus_agent/supervisor.py")
LOGS = ("agent", "src/eugene_plexus_agent/logs.py")
TEE = ("agent", "src/eugene_plexus_agent/console_logging.py")
ROUTE = ("agent", "src/eugene_plexus_agent/routes/logs.py")
UI_LOGS = ("ui", "src/lib/logs.ts")
UI_VIEW = ("ui", "src/components/LogsView.tsx")
UI_TREE = ("ui", "src/lib/resourceTree.ts")
TIMEOUT = 900

SABOTAGES: list[tuple[str, tuple[str, str], str, str]] = [
    # --- Start after a failed load ------------------------------------------------
    (
        "a runtime whose loop gave up still counts as running",
        RUNTIMES,
        "return (sp is not None and sp.supervising) or name in self._copy_jobs",
        "return sp is not None or name in self._copy_jobs",
    ),
    (
        "Start keeps the ended record and starts nothing",
        RUNTIMES,
        "            if existing.supervising:\n                return\n",
        "            return\n",
    ),
    (
        "a loop that has ended still reads as supervising",
        SUPERVISOR,
        "return self._task is not None and not self._task.done()",
        "return self._task is not None",
    ),
    # --- the line format -----------------------------------------------------------
    (
        "every line is tagged as the agent's",
        LOGS,
        'return f"{_format_time(moment)} [{source}] {text}"',
        'return f"{_format_time(moment)} [agent] {text}"',
    ),
    (
        "the agent's own lines keep the local time the stamp replaces",
        LOGS,
        "text = own.group(3) if own is not None else line",
        "text = line",
    ),
    (
        "the tee writes lines unstamped",
        TEE,
        r'stamped = logs.stamp(_ANSI_SGR_RE.sub("", line.rstrip("\r")))',
        r'stamped = _ANSI_SGR_RE.sub("", line.rstrip("\r"))',
    ),
    (
        "the tee publishes nothing to follow",
        TEE,
        "                logs.BUS.publish(stamped)\n",
        "",
    ),
    # --- reading ---------------------------------------------------------------------
    (
        "only the newest file is read",
        LOGS,
        'names = [LOG_FILE] + [f"{LOG_FILE}.{n}" for n in range(1, BACKUPS + 1)]',
        "names = [LOG_FILE]",
    ),
    (
        "history comes back newest first",
        LOGS,
        "    wanted.reverse()\n",
        "",
    ),
    (
        "since is ignored",
        LOGS,
        "if since is not None and line.time is not None and line.time < since:",
        "if False:",
    ),
    (
        "a tail never says there is more",
        LOGS,
        "                truncated = True\n",
        "                truncated = False\n",
    ),
    (
        "the updater's log is served unasked",
        LOGS,
        "        if sources and UPDATE_SOURCE in sources:",
        "        if True:",
    ),
    # --- masking and access -----------------------------------------------------------
    (
        "nothing is masked",
        ROUTE,
        "text=logs.redact(line.text)",
        "text=line.text",
    ),
    (
        "a token is not recognised",
        LOGS,
        r'    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),' + "\n",
        "",
    ),
    (
        "anyone reads the log",
        ROUTE,
        "_auth = [Depends(require_operator_session)]",
        "_auth: list[object] = []",
    ),
    # --- following -----------------------------------------------------------------
    (
        "a follow ignores its source filter",
        ROUTE,
        "if not logs.matches(line, sources=sources, contains=wanted, since=None):",
        "if False:",
    ),
    (
        "a follower is never told it lost lines",
        ROUTE,
        "if follower.dropped > reported:",
        "if False:",
    ),
    (
        "lost lines are not counted",
        LOGS,
        "                self.dropped += 1\n",
        "                pass\n",
    ),
    # --- the page -----------------------------------------------------------------
    (
        "machines are not put on one timeline",
        UI_LOGS,
        "a.at - b.at || a.machine - b.machine || a.index - b.index",
        "a.machine - b.machine || a.index - b.index",
    ),
    (
        "a line with no time sinks to the start",
        UI_LOGS,
        "if (!Number.isNaN(own)) last = own;",
        "last = Number.isNaN(own) ? Number.NEGATIVE_INFINITY : own;",
    ),
    (
        "the source a link names is not asked for",
        UI_LOGS,
        'for (const source of filters.sources ?? []) params.append("source", source);',
        "for (const source of filters.sources ?? []) void source;",
    ),
    (
        "Download leaves the stamps out",
        UI_LOGS,
        'const parts = [line.time ?? "-"];',
        "const parts: string[] = [];",
    ),
    (
        "the Inference link names the wrong source",
        UI_LOGS,
        "encodeURIComponent(`engine: ${runtime}`)",
        "encodeURIComponent(runtime)",
    ),
    (
        "a line arriving by both roads shows twice",
        UI_VIEW,
        "const after = early.filter((l) => !seen.has(keyOf(l)));",
        "const after = early;",
    ),
    (
        "a line written during the history read is lost",
        UI_VIEW,
        "else early.push(...fresh);",
        "else void fresh;",
    ),
    (
        "Follow off still follows",
        UI_VIEW,
        "      if (follow) {",
        "      if (true) {",
    ),
    (
        "a machine that does not answer is not named",
        UI_VIEW,
        "const troubled = machines.filter((m) => state[m.target]?.error);",
        "const troubled: TargetNode[] = [];",
    ),
    (
        "a machine under Agents has no Logs page",
        UI_TREE,
        "    // That machine's own log: its agent and everything it runs.\n"
        '    { id: "logs", label: "Logs", route: "/logs", icon: "ScrollText" },\n',
        "",
    ),
]

FILES = sorted({target for _, target, _, _ in SABOTAGES})


def run(repo: str) -> tuple[int, str]:
    if repo == "ui":
        argv = [
            "npx.cmd",
            "vitest",
            "run",
            "src/lib/logs",
            "src/components/LogsView",
            "src/lib/resourceTree",
        ]
    else:
        py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
        argv = [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
        argv += [
            "tests/test_logs.py",
            "tests/test_console_logging.py",
            "tests/test_runtime_end_to_end.py",
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
    backup = Path(tempfile.mkdtemp(prefix="logs-sabotage-"))
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
