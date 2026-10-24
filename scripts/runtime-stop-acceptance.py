"""Stop a real isolated agent's engine tree; reject stale Strata listeners.

Uses free ports, a borrowed fixture engine and tiny prepared files. No model,
GPU, live-install state or provider credentials. The leaf ignores the stop
signal until the check releases it, modelling a native engine freeing memory.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psutil
import yaml


def wait(predicate, label, seconds=30):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            if result := predicate():
                return result
        except (httpx.HTTPError, KeyError, ValueError, OSError):
            pass
        time.sleep(0.05)
    raise AssertionError(f"timed out: {label}")


def main():
    spec = importlib.util.spec_from_file_location(
        "ls5_fixture", Path(__file__).with_name("ls5-preparation-acceptance.py")
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    directory = Path(tempfile.mkdtemp(prefix="ep-runtime-stop-"))
    print(f"isolated tree: {directory}", flush=True)
    agent_port, runtime_port, machine_port = fixture.free_ports(3)
    root = directory / "strata"
    server = fixture.fake_strata(root)
    # A direct interpreter lets the simulated native child outlive its launcher.
    # CPython's Windows venv redirector has additional automatic job cleanup.
    if os.name == "nt":
        shutil.copyfile(sys._base_executable, root / ".venv/Scripts/python.exe")
    leaf = root / "leaf.py"
    leaf.write_text(
        "import os, signal, time\nfrom pathlib import Path\n"
        "root = Path(__file__).parent\n"
        "for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):\n"
        "    if hasattr(signal, name): signal.signal(getattr(signal, name), signal.SIG_IGN)\n"
        "(root / 'leaf.pid').write_text(str(os.getpid()))\n"
        "while not (root / 'release').exists(): time.sleep(.02)\n",
        encoding="utf-8",
    )
    launch = """
import signal, subprocess, sys
root = Path(__file__).resolve().parent.parent
child = subprocess.Popen([sys._base_executable, str(root / "leaf.py")],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def stop(*_):
    raise SystemExit(0)
for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
    if hasattr(signal, name): signal.signal(getattr(signal, name), stop)
ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
"""
    server.write_text(
        fixture.FAKE_SERVER.replace(
            "ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()",
            launch,
        ),
        encoding="utf-8",
    )
    model = directory / "prepared"
    (model / "pack").mkdir(parents=True)
    (model / "tokenizer").mkdir()
    for name in ("vocab.json", "merges.txt", "token_type.json"):
        (model / "tokenizer" / name).write_text("{}", encoding="utf-8")
    (model / "shard.gguf").touch()
    (model / "strata.json").write_text(
        json.dumps(
            {
                "exe": "fixture",
                "args": [
                    "--pack",
                    "pack",
                    "--native",
                    "shard.gguf",
                    "--max-context",
                    "32768",
                ],
                "tokenizer": "tokenizer",
            }
        ),
        encoding="utf-8",
    )
    provenance = model / "fixture.eugene-prepared.json"
    provenance.write_text(
        json.dumps({"engine": "strata", "entry": "strata.json"}), encoding="utf-8"
    )
    config = directory / "agent.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "securityMode": "prompt_on_startup",
                "strataServer": str(server),
                "components": [],
                "runtimes": [],
            }
        ),
        encoding="utf-8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith("EUGENE_PLEXUS_")
    }
    env.update(
        EUGENE_PLEXUS_AGENT_CONFIG_FILE=str(config),
        EUGENE_PLEXUS_AGENT_BIND_HOST="127.0.0.1",
        EUGENE_PLEXUS_AGENT_BIND_PORT=str(agent_port),
        EUGENE_PLEXUS_AGENT_MACHINE_PORT=str(machine_port),
        EUGENE_PLEXUS_AGENT_ENGINE_ROOT=str(directory / "engines"),
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        PYTHONUNBUFFERED="1",
    )
    with (directory / "agent.log").open("wb") as log:
        agent = subprocess.Popen(
            [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{agent_port}", trust_env=False, timeout=60
        )
        try:
            wait(lambda: client.get("/healthz").status_code == 200, "agent")
            token = client.post(
                "/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)}
            ).json()["sessionToken"]
            client.headers["Authorization"] = f"Bearer {token}"
            result = client.post(
                "/v1/runtimes",
                json={
                    "name": "tree",
                    "engine": "strata",
                    "modelPath": str(provenance),
                    "port": runtime_port,
                    "autoStart": False,
                    "autoDriver": False,
                },
            )
            assert result.status_code in (200, 201), result.text
            route = "/v1/runtimes/tree"
            # A listener left by a previous run must never make this launch ready.
            with socket.socket() as previous:
                previous.bind(("127.0.0.1", runtime_port))
                previous.listen()
                started = client.post(route + "/start")
                assert started.is_success, f"start refused ({started.status_code}): {started.text}"
                refused = wait(
                    lambda: (
                        r
                        if (r := client.get(route).json())["status"] == "crashed"
                        else None
                    ),
                    "occupied port refusal",
                )
                assert "already held" in refused["lastError"], refused
                assert not (root / "leaf.pid").exists()
            print(
                "PASS stale listener refuses before launch and names its port",
                flush=True,
            )
            started = client.post(route + "/start")
            assert started.is_success, f"start refused ({started.status_code}): {started.text}"
            wait(lambda: client.get(route).json()["status"] == "ready", "runtime ready")
            leaf_process = psutil.Process(int((root / "leaf.pid").read_text()))
            parent = psutil.Process(client.get(route).json()["pid"])
            with ThreadPoolExecutor(1) as pool:
                stopped = pool.submit(client.post, route + "/stop")
                try:
                    wait(lambda: not parent.is_running(), "engine launcher exited")
                    # Allow the output reader's one-second drain to finish.
                    # A pending request before parent exit proves nothing.
                    time.sleep(1.2)
                    assert leaf_process.is_running()
                    assert not stopped.done(), (
                        "Stop returned before the native child exited"
                    )
                    assert client.get(route).json()["status"] != "stopped"
                finally:
                    (root / "release").touch()
                stopped.result(timeout=10).raise_for_status()
            assert (
                not leaf_process.is_running()
                or leaf_process.status() == psutil.STATUS_ZOMBIE
            )
            assert client.get(route).json()["status"] == "stopped"
            print(
                "PASS Stop waits for the native child; stopped means the tree exited",
                flush=True,
            )
        finally:
            (root / "release").touch()
            client.close()
            if agent.poll() is None:
                agent.send_signal(
                    signal.CTRL_BREAK_EVENT
                ) if os.name == "nt" else agent.terminate()
            agent.wait(timeout=45)
    print("ALL PASS: 2 checks; fixture tree retained for logs", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
