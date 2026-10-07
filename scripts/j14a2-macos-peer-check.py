"""J14a.2 on macOS: the agent's own reader (`loopback_peer.py`) against real
loopback connections from this account and from a second one.

Run on a macOS runner after making a second account, with the agent checkout
beside this one (or its path in `EP_AGENT`):

    python3 scripts/j14a2-macos-peer-check.py --other eptest2

Loads `loopback_peer.py` by path (it needs only the standard library), so no
agent install is needed. Exits non-zero on any failed check.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path

CLIENT = (
    "import socket,sys,time;c=socket.create_connection(('127.0.0.1',int(sys.argv[1])));"
    "time.sleep(3);c.close()"
)


def reader() -> object:
    agent = Path(os.environ.get("EP_AGENT", Path(__file__).resolve().parents[2] / "agent"))
    path = agent / "src" / "eugene_plexus_agent" / "loopback_peer.py"
    spec = importlib.util.spec_from_file_location("loopback_peer", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--other", required=True)
    args = parser.parse_args()
    peer = reader()
    other_uid = subprocess.run(["id", "-u", args.other], capture_output=True, text=True,
                               check=True).stdout.strip()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    failed = 0

    def check(label: str, argv: list[str], expected: str) -> None:
        nonlocal failed
        client = subprocess.Popen([*argv, "python3", "-c", CLIENT, str(port)])
        conn, address = server.accept()
        try:
            got = peer.peer_account(address[1], port)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - reported
            got = f"{type(exc).__name__}: {exc}"
        ok = got == expected
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} {label}: read {got!r}, expected {expected!r}")
        client.wait()
        conn.close()

    own = peer.own_account()  # type: ignore[attr-defined]
    check("a connection from this account reads as this account", [], own)
    check(f"a connection from {args.other} reads as {args.other}",
          ["sudo", "-n", "-u", args.other], other_uid)
    try:
        peer.peer_account(1, port)  # type: ignore[attr-defined]
        print("FAIL a port with no connection was given an account")
        failed += 1
    except peer.PeerUnknown as exc:  # type: ignore[attr-defined]
        print(f"PASS a port with no connection is refused: {exc}")
    server.close()
    print(f"macOS {os.uname().release}: {'all passed' if not failed else f'{failed} failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
