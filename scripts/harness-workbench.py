"""Start an isolated, authenticated Eugene endpoint for real-client acceptance.

Uses an already running Strata server, without changing or supervising it.
Run with the agent repository's Python (gateway and driver must also import).
All Eugene state and ports are private; run.json contains credentials and must
stay outside version control. Stop removes only this fixture's two components.
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
import time

import httpx
import yaml


def wait(check, label, seconds=45):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            if check():
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Timed out: " + label)


def serve(root, port):
    import uvicorn
    from eugene_plexus_agent.app import create_app
    from eugene_plexus_agent.settings import Settings

    app = create_app(
        Settings(
            config_file=root / "agent.yaml", default_topology=False, bind_port=port
        )
    )
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)


def start(args):
    root = args.directory.resolve()
    root.mkdir()  # Preserve earlier evidence; never overwrite a run.
    with httpx.Client(timeout=10, trust_env=False) as client:
        health = client.get(args.strata.rstrip("/") + "/health")
        health.raise_for_status()
        assert health.json().get("service") == "strata"
        assert health.json().get("loaded") is True
        assert health.json().get("model") == args.model
    sockets = [socket.socket() for _ in range(3)]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(
        zip(["agent", "gateway", "driver"], [sock.getsockname()[1] for sock in sockets])
    )
    for sock in sockets:
        sock.close()
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    (root / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "securityMode": "prompt_on_startup",
                "components": [],
            }
        ),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env.update(PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring", PYTHONUTF8="1")
    with (root / "agent.log").open("ab") as log:
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
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    record = {
        "agentPid": proc.pid,
        "urls": urls,
        "model": args.model,
        "strata": args.strata,
        "directory": str(root),
    }

    def save():
        (root / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    save()
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
            "POST", "/v1/auth/client-keys", json={"name": "Real harness acceptance"}
        ).json()["token"]
        save()
        for name, kind, body in [
            (
                "driver",
                "inference-driver",
                {
                    "provider": "strata_local",
                    "baseUrl": args.strata,
                    "modelId": args.model,
                    "requestTimeoutSeconds": 660,
                },
            ),
            (
                "gateway",
                "gateway",
                {
                    "routingRefreshSeconds": 2,
                    "defaultTemperature": 0.1,
                    "requestTimeoutSeconds": 600,
                },
            ),
        ]:
            config = root / f"{name}.yaml"
            config.write_text(yaml.safe_dump(body), encoding="utf-8")
            call(
                "POST",
                "/v1/components",
                json={
                    "name": "harness-" + name,
                    "kind": kind,
                    "url": urls[name],
                    "spawn": {"configFile": str(config)},
                },
            )
            wait(lambda: client.get(urls[name] + "/healthz").status_code == 200, name)
        headers = {"Authorization": "Bearer " + record["applicationKey"]}
        wait(
            lambda: (
                client.get(urls["gateway"] + "/v1/models", headers=headers)
                .json()
                .get("data")
            ),
            "authenticated model discovery",
        )
        assert (
            httpx.get(urls["gateway"] + "/v1/models", trust_env=False).status_code
            == 401
        )
        models = client.get(urls["gateway"] + "/v1/models", headers=headers).json()
        (root / "models.json").write_text(
            json.dumps(models, indent=2), encoding="utf-8"
        )
    print("Authenticated candidate ready:", urls["gateway"], "model:", args.model)
    print("Private state:", root)


def stop(root):
    record = json.loads((root / "run.json").read_text(encoding="utf-8"))
    with httpx.Client(
        timeout=30,
        trust_env=False,
        headers={"Authorization": "Bearer " + record["operator"]},
    ) as client:
        for name in ("driver", "gateway"):
            response = client.delete(
                record["urls"]["agent"] + "/v1/components/harness-" + name
            )
            assert response.status_code in (200, 204, 404), response.status_code
    print("Candidate components stopped; empty fixture agent PID:", record["agentPid"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--strata")
    parser.add_argument("--model")
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--stop", type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    elif args.stop:
        stop(args.stop)
    elif all([args.directory, args.strata, args.model]):
        start(args)
    else:
        parser.error("--directory, --strata and --model are required")
