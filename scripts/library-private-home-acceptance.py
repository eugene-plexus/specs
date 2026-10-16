"""Real POSIX permission denial must leave the Library's repair endpoints up.

Run as an ordinary Linux user, using a Python 3.12 environment with Library
installed. No installed service, root privileges or default ports are used.
--sabotage replaces only app.py in a temporary package copy with the pre-fix
revision, then requires the same startup gate to catch the failure.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

import httpx

import eugene_plexus_library


def exercise(*, sabotage: bool) -> None:
    if os.name != "posix" or os.geteuid() == 0:
        raise SystemExit(
            "Run as a non-root Linux user: root bypasses the permission check."
        )
    work = Path(tempfile.mkdtemp(prefix="ep-private-home-"))
    private = work / "private-home"
    models = private / "Eugene Models"
    models.mkdir(parents=True)
    sentinel = models / "keep.txt"
    sentinel.write_text("user data stays here", encoding="utf-8")
    accessible = work / "accessible-models"
    accessible.mkdir()
    private.chmod(0)
    process = None
    print(f"Artifacts: {work}", flush=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    package = Path(eugene_plexus_library.__file__).resolve().parent
    if sabotage:
        copied = work / "code" / "eugene_plexus_library"
        shutil.copytree(package, copied, ignore=shutil.ignore_patterns("__pycache__"))
        before = subprocess.check_output(
            [
                "git",
                "-C",
                str(package.parents[1]),
                "show",
                "70c5f9820af4a2337cddea4052aab6e9c25ed8f3:src/eugene_plexus_library/app.py",
            ]
        )
        (copied / "app.py").write_bytes(before)
        env["PYTHONPATH"] = str(work / "code")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env.update(
        {
            "EUGENE_PLEXUS_LIBRARY_CONFIG_FILE": str(work / "library.yaml"),
            "EUGENE_PLEXUS_LIBRARY_STATE_FILE": str(work / "library-state.json"),
            "EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS": str(models),
            "EUGENE_PLEXUS_LIBRARY_BIND_HOST": "127.0.0.1",
            "EUGENE_PLEXUS_LIBRARY_BIND_PORT": str(port),
        }
    )
    try:
        try:
            models.stat()
        except PermissionError:
            print(
                "PASS real OS denial traversing a private parent directory", flush=True
            )
        else:
            raise AssertionError(
                "fixture does not deny access; acceptance cannot prove anything"
            )
        with (
            (work / "library.log").open("wb") as log,
            httpx.Client(
                base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2
            ) as http,
        ):
            process = subprocess.Popen(
                [sys.executable, "-m", "eugene_plexus_library"],
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            deadline = time.perf_counter() + 20
            ready = False
            while time.perf_counter() < deadline:
                if process.poll() is not None:
                    break
                try:
                    if http.get("/healthz").status_code == 200:
                        ready = True
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            if sabotage:
                assert not ready and process.poll() is not None, (
                    "startup sabotage escaped"
                )
                text = (work / "library.log").read_text()
                assert (
                    "PermissionError" in text and "_announce_default_roots" in text
                ), text
                print(
                    "CAUGHT pre-fix startup crash; no Library HTTP endpoint became available",
                    flush=True,
                )
                return
            assert ready, f"Library failed to start; see {work / 'library.log'}"
            deadline = time.perf_counter() + 10
            while time.perf_counter() < deadline:
                scan = http.get("/v1/scan").json()
                if scan["state"] != "scanning" and scan.get("roots"):
                    break
                time.sleep(0.05)
            assert scan["roots"][0]["status"] == "unreadable", scan
            health = http.get("/healthz").json()
            assert health["status"] == "degraded", health
            assert health["details"]["unreadableRoots"] == [str(models)], health
            assert http.get("/v1/directories").status_code == 200
            denied = http.get("/v1/directories", params={"path": str(models)})
            assert denied.status_code == 403 and "Permission denied" in denied.text, (
                denied.text
            )
            print(
                "PASS Library stays up, reports degraded health and an actual folder permission error",
                flush=True,
            )
            assert http.get("/v1/config").json()["modelRoots"][0]["path"] == str(models)
            changed = http.patch("/v1/config", json={"modelRoots": [str(accessible)]})
            assert changed.status_code == 200, changed.text
            scan_start = http.post("/v1/scan")
            assert scan_start.status_code == 202, scan_start.text
            deadline = time.perf_counter() + 10
            while time.perf_counter() < deadline:
                scan = http.get("/v1/scan").json()
                if (
                    scan["state"] != "scanning"
                    and scan.get("roots")
                    and scan["roots"][0]["path"] == str(accessible)
                ):
                    break
                time.sleep(0.05)
            assert scan["roots"][0]["status"] == "ok", scan
            assert http.get("/healthz").json()["status"] == "ok"
            assert stat.S_IMODE(private.stat().st_mode) == 0
            assert process.poll() is None
            print(
                "PASS changing folders restores healthy scanning without restarting or changing permissions",
                flush=True,
            )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        # Only this run's temporary fixture; no user's home is ever changed.
        private.chmod(0o700)
        assert sentinel.read_text(encoding="utf-8") == "user data stays here"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sabotage", action="store_true")
    exercise(sabotage=parser.parse_args().sabotage)
