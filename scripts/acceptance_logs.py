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


def ephemeral_range() -> tuple[int, int]:
    """The ports this OS hands to a program that asks for any port, and to the source
    side of every outgoing connection: Linux's `ip_local_port_range` (32768-60999 unless
    set), 49152-65535 on Windows and macOS."""
    try:
        text = Path("/proc/sys/net/ipv4/ip_local_port_range").read_text(encoding="ascii")
        low, high = (int(part) for part in text.split())
        return low, high
    except (OSError, ValueError):
        return 49152, 65535


#: Ports below the OS's own range that a script may pick. Never the defaults (8079-8084)
#: or the live install's (+200), and nothing a service on this machine usually holds.
_QUIET_FLOOR = 10000
_QUIET_CEILING = 30000
_FORBIDDEN = set(range(8079, 8085)) | set(range(8279, 8285))


def quiet_ports(count: int, *, avoid: Iterable[int] = (), host: str = "127.0.0.1") -> list[int]:
    """`count` distinct ports nothing holds now, **below the range the OS hands out**.

    A port picked with `bind(0)` and released is in that range, and so is every port an
    agent picks for its own children (the gateway's door, an app's) and the source port of
    every connection a client opens: any of them can take it before the process the
    script picked it for binds it. Specs#130 (an agent: "address already in use") and
    #132 (a gateway whose door led to the driver's port) were that. A port the OS never
    hands out cannot be taken that way; only a process that asks for this very port can.
    """
    import random
    import socket

    low, _ = ephemeral_range()
    ceiling = min(_QUIET_CEILING, low)
    if ceiling - _QUIET_FLOOR < count * 4:
        raise RuntimeError(
            f"this OS hands out ports from {low}: no room below it for {count} quiet ports"
        )
    skip = set(avoid) | _FORBIDDEN
    held: list[socket.socket] = []
    ports: list[int] = []
    try:
        for port in random.sample(range(_QUIET_FLOOR, ceiling), ceiling - _QUIET_FLOOR):
            if len(ports) == count:
                break
            if port in skip:
                continue
            sock = socket.socket()
            try:
                sock.bind((host, port))
            except OSError:
                sock.close()
                continue
            held.append(sock)
            ports.append(port)
    finally:
        for sock in held:
            sock.close()
    if len(ports) < count:
        raise RuntimeError(f"found {len(ports)} of {count} free ports below {ceiling}")
    return ports


def quiet_port(*avoid: int) -> int:
    """One `quiet_ports` port that is none of `avoid`."""
    return quiet_ports(1, avoid=avoid)[0]


def _part_events(log: str, part: str) -> list[tuple[int, str]]:
    import re

    name = re.escape(part)
    return [
        (m.start(), m.group("kind"))
        for m in re.finditer(
            rf"(?P<kind>spawning {name}:|{name} exited (?:on request|cleanly)|"
            rf"^\[(?:driver: )?{name}\][^\n]*Application startup complete)",
            log,
            re.MULTILINE,
        )
    ]


def part_events(log: str, part: str) -> int:
    """How many spawns, exits and starts of `part` the agent's log holds: it moves while
    the agent is still restarting the part."""
    return len(_part_events(log, part))


def part_is_up(log: str, part: str) -> bool:
    """Whether a part the agent supervises is up by the agent's own log: its latest event
    is its own `Application startup complete.`, not a spawn or an exit after it.

    The agent restarts every child after sign-in and after enrollment, and a gateway
    drains first, so a check that runs just after an install can meet a part that is
    between two processes (specs#132: a gateway's 502 "Server disconnected"). Lines are
    the agent's `spawning <part>:` and `<part> exited on request|cleanly (rc=N)`, and the
    child's own `[<part>]` or `[driver: <part>]` startup line.
    """
    events = _part_events(log, part)
    return bool(events) and events[-1][1].endswith("startup complete")


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
