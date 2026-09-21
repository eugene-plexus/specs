"""Isolated, authenticated real-model A4 workbench. No installed state is changed.

Start with --engine, --model and --projector absolute paths. The agent supervises
the real gateway, driver and llama.cpp. CPU-only by default; all state/ports are
private to this run. Credentials stay in the temporary directory, never stdout.
Stop with --stop DIRECTORY (stops only the declared isolated components/runtime).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import yaml


def serve(directory: Path, port: int):
    import uvicorn
    from eugene_plexus_agent.app import create_app
    from eugene_plexus_agent.settings import Settings

    app = create_app(
        Settings(
            config_file=directory / "agent.yaml", default_topology=False, bind_port=port
        )
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", access_log=False)


def wait(check, label, seconds=30):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            if check():
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Timed out: " + label)


def start(args):
    root = Path(tempfile.mkdtemp(prefix="ep-a4-acceptance-"))
    sockets = [socket.socket() for _ in range(4)]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(
        zip(
            ["agent", "gateway", "driver", "runtime"],
            [sock.getsockname()[1] for sock in sockets],
        )
    )
    for sock in sockets:
        sock.close()
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    config = {
        "firstRunComplete": True,
        "securityMode": "prompt_on_startup",
        "components": [],
        "engineBinaryRoots": [str(Path(args.engine).resolve().parent)],
    }
    (root / "agent.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env["PYTHONUTF8"] = "1"
    log = (root / "agent.log").open("ab")
    proc = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--serve",
            str(root),
            "--port",
            str(ports["agent"]),
        ],
        cwd=root,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    log.close()
    record = {
        "directory": str(root),
        "agentPid": proc.pid,
        "urls": urls,
        "ports": ports,
    }
    (root / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("A4 isolated workbench:", root, flush=True)
    with httpx.Client(timeout=30, trust_env=False) as client:

        def call(method, path, **kwargs):
            response = client.request(method, urls["agent"] + path, **kwargs)
            response.raise_for_status()
            return response

        wait(lambda: call("GET", "/healthz").status_code == 200, "agent")
        phrase = secrets.token_urlsafe(24)
        call("POST", "/v1/auth/initialize", json={"passphrase": phrase})
        operator = call("POST", "/v1/auth/login", json={"passphrase": phrase}).json()[
            "sessionToken"
        ]
        client.headers["Authorization"] = "Bearer " + operator
        record["operator"] = operator
        record["applicationKey"] = call(
            "POST", "/v1/auth/client-keys", json={"name": "A4 application acceptance"}
        ).json()["token"]
        (root / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        runtime = {
            "name": "a4-vision",
            "modelAlias": "a4-vision",
            "engine": "llama_cpp",
            "modelPath": str(Path(args.model).resolve()),
            "binary": str(Path(args.engine).resolve()),
            "port": ports["runtime"],
            "autoStart": False,
            "startOnDemand": True,
            "autoDriver": False,
            "flags": {
                "contextSize": 16384,
                "gpuLayers": 0,
                "threads": 8,
                "batchSize": 256,
                "ubatchSize": 128,
                "parallelSlots": 1,
                "projectorPath": str(Path(args.projector).resolve()),
                "projectorOnCpu": True,
            },
            "env": {"CUDA_VISIBLE_DEVICES": ""},
        }
        call("POST", "/v1/runtimes?force=true", json=runtime)
        for name, kind, body in [
            (
                "driver",
                "inference-driver",
                {
                    "provider": "openai_compat_custom",
                    "runtimeName": "a4-vision",
                    "modelId": "a4-vision",
                    "requestTimeoutSeconds": 660,
                },
            ),
            (
                "gateway",
                "gateway",
                {
                    "routingRefreshSeconds": 2,
                    "defaultMaxTokens": 1024,
                    "defaultTemperature": 0.1,
                    "requestTimeoutSeconds": 600,
                },
            ),
        ]:
            config_file = root / f"{name}.yaml"
            config_file.write_text(yaml.safe_dump(body), encoding="utf-8")
            call(
                "POST",
                "/v1/components",
                json={
                    "name": "a4-" + name,
                    "kind": kind,
                    "url": urls[name],
                    "spawn": {"configFile": str(config_file)},
                },
            )
            wait(lambda: client.get(urls[name] + "/healthz").status_code == 200, name)
        app_headers = {"Authorization": "Bearer " + record["applicationKey"]}
        wait(
            lambda: (
                client.get(urls["gateway"] + "/v1/models", headers=app_headers)
                .json()
                .get("data")
            ),
            "authenticated model discovery",
        )
        response = httpx.get(urls["gateway"] + "/v1/models", trust_env=False)
        assert response.status_code == 401
        print(
            "Real agent, gateway and driver ready; authentication verified. Model is cold.",
            flush=True,
        )


def stop(root):
    record = json.loads((root / "run.json").read_text(encoding="utf-8"))
    with httpx.Client(
        timeout=30,
        trust_env=False,
        headers={"Authorization": "Bearer " + record["operator"]},
    ) as client:
        base = record["urls"]["agent"]
        for path in [
            "/v1/runtimes/a4-vision",
            "/v1/components/a4-driver",
            "/v1/components/a4-gateway",
        ]:
            response = client.delete(base + path)
            assert response.status_code in (200, 204, 404), response.status_code
    # Leave the empty isolated agent for explicit PID-checked cleanup by the caller.
    print(
        "Isolated runtime and components stopped; empty agent PID", record["agentPid"]
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--stop", type=Path)
    parser.add_argument("--engine")
    parser.add_argument("--model")
    parser.add_argument("--projector")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    elif args.stop:
        stop(args.stop)
    else:
        if not all([args.engine, args.model, args.projector]):
            parser.error("--engine, --model and --projector are required")
        start(args)
