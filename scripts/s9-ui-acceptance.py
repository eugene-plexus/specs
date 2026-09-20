"""S9: packaged UI, real components and CPU inference, isolated from the install.

Run with an integration interpreter containing all Eugene packages and the UI
wheel. Requires --engine and --model; never downloads or changes the live service.
Output, logs and disposable credentials stay in a new --output directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import yaml


def check(root: Path, engine: Path, model: Path) -> None:
    assert engine.is_file() and model.is_file()
    root.mkdir(parents=True, exist_ok=False)
    sockets = [socket.socket() for _ in range(6)]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(zip(("agent", "control", "gateway", "library", "driver", "engine"),
                     (sock.getsockname()[1] for sock in sockets)))
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    configs = {
        "agent": {"firstRunComplete": True, "securityMode": "prompt_on_startup",
                  "components": [{"name": name, "kind": "inference-driver" if name == "driver" else name,
                                  "url": urls[name], "spawn": {"configFile": f"{name}.yaml"}}
                                 for name in ("control", "gateway", "library", "driver")]},
        "control": {},
        "gateway": {"routingRefreshSeconds": 1},
        "library": {"modelRoots": [str(model.parent)], "scanOnStartup": True},
        "driver": {"provider": "openai_compat_custom", "modelId": "s9-phone-model",
                   "baseUrl": urls["engine"]},
    }
    for name, config in configs.items():
        (root / f"{name}.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    processes = []
    logs = []
    for sock in sockets:
        sock.close()
    try:
        commands = [
            ("engine", [str(engine), "-m", str(model), "--alias", "s9-phone-model",
                        "--host", "127.0.0.1", "--port", str(ports["engine"]),
                        "--device", "none", "--n-gpu-layers", "0", "--ctx-size", "2048",
                        "--threads", "4", "--jinja"]),
            ("agent", [sys.executable, str(Path(__file__).resolve().with_name("s8-ui-acceptance.py")),
                       "--serve", str(root), "--port", str(ports["agent"])])]
        for name, command in commands:
            log = (root / f"{name}.log").open("w", encoding="utf-8")
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        with httpx.Client(trust_env=False, timeout=10) as client:
            def wait(path: str, headers: dict | None = None, predicate=lambda r: r.status_code == 200):
                for _ in range(180):
                    try:
                        response = client.get(path, headers=headers)
                        if predicate(response):
                            return response
                    except httpx.HTTPError:
                        pass
                    assert all(p.poll() is None for p in processes), "acceptance process exited"
                    time.sleep(.5)
                raise AssertionError(f"not ready: {path}")
            wait(urls["engine"] + "/health")
            wait(urls["agent"] + "/healthz")
            login = client.post(urls["agent"] + "/v1/auth/initialize",
                                json={"passphrase": "s9-disposable-passphrase"})
            login.raise_for_status()
            token = login.json()["sessionToken"]
            headers = {"Authorization": f"Bearer {token}"}
            wait(urls["gateway"] + "/v1/models", headers,
                 lambda r: r.status_code == 200 and any(m["id"] == "s9-phone-model"
                                                       for m in r.json().get("data", [])))
            wait(urls["library"] + "/healthz")
            scan = client.post(urls["library"] + "/v1/scan", headers=headers, json={"full": False})
            assert scan.status_code in (200, 202, 409), scan.text
            session = root / "session.json"
            session.write_text(json.dumps({"url": urls["agent"], "token": token}), encoding="utf-8")
        subprocess.run(["node", str(Path(__file__).with_name("s9-browser-acceptance.mjs")),
                        str(session), str(root)], check=True)
    finally:
        (root / "stop").touch()
        if len(processes) > 1:
            processes[1].wait(timeout=30)  # Agent gracefully stops its own children.
        if processes:
            processes[0].terminate()
            processes[0].wait(timeout=15)
        for log in logs:
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    check(args.output.resolve(), args.engine.resolve(), args.model.resolve())
