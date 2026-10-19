"""Unreadable config recovery over a real Library HTTP process on isolated ports."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def check(root: Path, blocked: bool) -> None:
    root.mkdir()
    config = root / "config.yaml"
    original = b"modelRoots: [unfinished\n"
    config.write_bytes(original)
    state = root / "library-state.json"
    if blocked:
        config.with_name(config.name + ".bak").mkdir()
        state.write_text(
            '{"version":1,"models":[],"profiles":{"m":{"not":"a list"}}}',
            encoding="utf-8",
        )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env.update(
        EUGENE_PLEXUS_LIBRARY_CONFIG_FILE=str(config),
        EUGENE_PLEXUS_LIBRARY_STATE_FILE=str(state),
        EUGENE_PLEXUS_LIBRARY_BIND_HOST="127.0.0.1",
        EUGENE_PLEXUS_LIBRARY_BIND_PORT=str(port),
    )
    with (root / "library.log").open("wb") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "eugene_plexus_library"],
            env=env,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", trust_env=False
            ) as client:
                deadline = time.perf_counter() + 30
                while True:
                    try:
                        health = client.get("/healthz").json()
                        break
                    except httpx.TransportError:
                        assert proc.poll() is None and time.perf_counter() < deadline, (
                            "startup failed"
                        )
                        time.sleep(0.05)
                assert health["status"] == "degraded", health
                assert "config.yaml" in health["details"]["configError"], health
                assert root.name not in str(health), health
                response = client.patch("/v1/config", json={"modelRoots": []})
                if blocked:
                    storage = health["details"]["storageError"]
                    assert "library-state.json" in storage, health
                    assert "start Eugene v0.3.0 once" in storage, health
                    assert response.status_code == 409, response.text
                    assert root.name not in response.text and "backup" in response.text
                    assert config.read_bytes() == original
                else:
                    assert response.status_code == 200, response.text
                    assert (
                        config.with_name(config.name + ".bak").read_bytes()
                        == original
                    )
                    assert "configError" not in client.get("/healthz").json()["details"]
        finally:
            proc.send_signal(
                signal.CTRL_BREAK_EVENT
            ) if os.name == "nt" else proc.terminate()
            proc.wait(timeout=30)
    assert str(config) in (root / "library.log").read_text(encoding="utf-8")
    print(
        f"PASS {'v0.1 state refused by name, repair never overwrites a backup' if blocked else 'bad YAML repaired with backup'}; public errors omit paths",
        flush=True,
    )


if __name__ == "__main__":
    root = Path(tempfile.mkdtemp(prefix="ep-library-config-"))
    for blocked in (False, True):
        check(root / ("blocked" if blocked else "repair"), blocked)
    print(f"Logs: {root}")
