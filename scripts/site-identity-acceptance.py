"""An actual unreadable site.json must not expose paths through HTTP health."""

import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="ep-site-identity-"))
    (root / "site.json").mkdir()  # Actual read failure on both Windows and POSIX.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("EUGENE_PLEXUS_", "SITE_HOST_"))
    }
    channel = (
        r"\\.\pipe\ep-identity-" + secrets.token_hex(8)
        if os.name == "nt"
        else str(root / "channel")
    )
    env.update(
        EUGENE_PLEXUS_APP_DATA_DIR=str(root),
        EUGENE_PLEXUS_APP_BIND_PORT=str(port),
        SITE_HOST_CHANNEL=channel,
    )
    with (root / "site.log").open("wb") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "eugene_plexus_site_host"],
            env=env,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(trust_env=False) as client:
                deadline = time.perf_counter() + 30
                while True:
                    try:
                        response = client.get(f"http://127.0.0.1:{port}/healthz")
                        break
                    except httpx.TransportError:
                        assert proc.poll() is None and time.perf_counter() < deadline
                        time.sleep(0.05)
                assert response.status_code == 503, response.text
                reason = response.json()["reason"]
                assert "site.json" in reason and "unreadable" in reason, reason
                assert root.name not in reason, reason
        finally:
            proc.send_signal(
                signal.CTRL_BREAK_EVENT
            ) if os.name == "nt" else proc.terminate()
            proc.wait(timeout=30)
    assert str(root / "site.json") in (root / "site.log").read_text(encoding="utf-8")
    print(
        f"PASS unreadable site.json: health names the file and log keeps its path; {root}"
    )


if __name__ == "__main__":
    main()
