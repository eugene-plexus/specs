"""What an acceptance script says when a process it started never answers.

A timeout that prints only `Connection refused` names no cause (specs#117,
#123, #127). The cause is in the process's own output, so a script prints it
before it fails: whether the process had exited and with what code, and the
tail of its log. Import this beside the script (`import acceptance_logs`);
a script run by path has its own folder first on `sys.path`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

#: What a failed bind says: uvicorn's wording on Linux and macOS (98, 48) and
#: on Windows (10048, 10013). Python's own `OSError` carries the same text.
BIND_FAILURES = (
    "error while attempting to bind",
    "address already in use",
    "only one usage of each socket address",
)


def tail(path: Path, lines: int = 60) -> str:
    """The last `lines` lines of a log, or a sentence saying why there are none."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(the log {path} cannot be read: {e})"
    kept = text.splitlines()[-lines:]
    return "\n".join(kept) if kept else f"(the log {path} is empty)"


def exit_note(process: subprocess.Popen[bytes] | None, name: str = "the process") -> str:
    """Whether a process had exited, and with what code. Never waits."""
    if process is None:
        return f"{name} was never started"
    code = process.poll()
    if code is None:
        return f"{name} was still running"
    return f"{name} had exited with code {code}"


def bind_failure(text: str) -> bool:
    """Does this log say a port could not be bound?"""
    lowered = text.lower()
    return any(phrase in lowered for phrase in BIND_FAILURES)


def logs_under(directory: Path, limit: int = 8) -> list[Path]:
    """The non-empty `*.log` files under a run's folder, newest first."""
    found = [p for p in directory.rglob("*.log") if p.is_file() and p.stat().st_size > 0]
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[:limit]


def report(paths: Iterable[Path], lines: int = 60, *, base: Path | None = None) -> str:
    """Each log's tail under its own heading, ready to print."""
    parts = []
    for path in paths:
        shown = path.relative_to(base) if base is not None and path.is_relative_to(base) else path
        parts.append(f"--- {shown} (last {lines} lines) ---\n{tail(path, lines)}")
    return "\n".join(parts)
