"""Restore enrolled worker/root checkpoints and infer with a real CPU model.

Run using a disposable installed Python, never the live service's environment:
this deliberately uninstalls its gateway to model a failed update.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time

import httpx
import yaml


def serve(root, port):
    from eugene_plexus_agent.__main__ import build_server
    from eugene_plexus_agent.settings import Settings

    server = build_server(
        Settings(
            config_file=root / "agent.yaml", bind_port=port, default_topology=False
        ),
        unattended=True,
    )

    def watch():
        while not (root / "acceptance-stop").exists():
            time.sleep(0.1)
        server.should_exit = True

    threading.Thread(target=watch, daemon=True).start()
    server.run()


def exercise(args):
    spec = importlib.util.spec_from_file_location(
        "recovery", Path(__file__).with_name("recovery.py")
    )
    recovery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recovery)
    root = args.directory.resolve()
    if root.exists():
        raise ValueError("acceptance directory must be new")
    recovery.private_directory(root)
    # Destructive injection is confined to the explicitly selected disposable
    # venv and is refused unless the caller gave its exact resolved prefix.
    if Path(sys.prefix).resolve() != args.disposable_venv.resolve():
        raise ValueError("--disposable-venv must match this interpreter's exact prefix")
    sockets = [socket.socket() for _ in range(7)]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(
        zip(
            ("root", "worker", "control", "gateway", "library", "engine", "driver"),
            [s.getsockname()[1] for s in sockets],
        )
    )
    for sock in sockets:
        sock.close()
    phrase = secrets.token_urlsafe(24)
    password = secrets.token_urlsafe(24)
    processes, logs = {}, []
    client = httpx.Client(timeout=90, trust_env=False)
    locations = {n: root / n for n in ("root", "worker")}
    timings = {}

    def url(name):
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        return client.request(
            method,
            url(name) + path,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            **kwargs,
        )

    def wait(check, label, seconds=90):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                result = check()
                if result:
                    return result
            except (httpx.HTTPError, KeyError):
                pass
            time.sleep(0.25)
        raise AssertionError("timed out: " + label)

    def start(name, python=Path(sys.executable)):
        directory = locations[name]
        (directory / "acceptance-stop").unlink(missing_ok=True)
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")
        }
        env.update(
            {
                "PYTHONUTF8": "1",
                "CUDA_VISIBLE_DEVICES": "-1",
                "HIP_VISIBLE_DEVICES": "-1",
                "ROCR_VISIBLE_DEVICES": "-1",
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(directory / "engines"),
            }
        )
        output = (root / (name + "-process.log")).open("ab")
        logs.append(output)
        processes[name] = subprocess.Popen(
            [str(python), __file__, "--serve", str(directory), str(ports[name])],
            cwd=directory,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name + " health")

    def stop(name):
        process = processes.pop(name, None)
        if process:
            (locations[name] / "acceptance-stop").write_text("stop")
            process.wait(timeout=60)
            assert process.returncode == 0, (name, process.returncode)

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": phrase})
        response.raise_for_status()
        return response.json()["sessionToken"]

    def infer(token):
        response = call(
            "gateway",
            "POST",
            "/v1/chat/completions",
            token,
            json={
                "model": "a7-model",
                "messages": [{"role": "user", "content": "Say hello. /no_think"}],
                "max_tokens": 64,
                "temperature": 0,
            },
        )
        assert response.status_code == 200, response.text
        content = response.json()["choices"][0]["message"]["content"]
        assert content.strip(), response.text
        print("PASS real completion:", repr(content), flush=True)

    try:
        for name, directory in locations.items():
            directory.mkdir()
            components = []
            if name == "root":
                components = [
                    {
                        "name": k,
                        "kind": k,
                        "url": url(k),
                        "spawn": {"configFile": str(directory / (k + ".yaml"))},
                    }
                    for k in ("control", "gateway", "library")
                ]
            else:
                components = [
                    {
                        "name": "a7-model-driver",
                        "kind": "inference-driver",
                        "url": url("driver"),
                        "spawn": {
                            "configFile": str(
                                directory / "drivers/a7-model-driver.yaml"
                            )
                        },
                    }
                ]
            (directory / "agent.yaml").write_text(
                yaml.safe_dump(
                    {
                        "firstRunComplete": True,
                        "securityMode": "prompt_on_startup",
                        "advertiseUrl": url(name),
                        "components": components,
                        "engineBinaryRoots": [str(args.engine.resolve().parent)],
                    }
                ),
                encoding="utf-8",
            )
        (locations["root"] / "library.yaml").write_text(
            yaml.safe_dump({"modelRoots": [str(args.model.resolve().parent)]}),
            encoding="utf-8",
        )
        start("root")
        agent_token = call(
            "root", "POST", "/v1/auth/initialize", json={"passphrase": phrase}
        ).json()["sessionToken"]
        wait(
            lambda: call("control", "GET", "/healthz").status_code == 200,
            "root control",
        )
        call(
            "control", "POST", "/v1/auth/initialize", json={"passphrase": phrase}
        ).raise_for_status()
        operator = login("control")
        for name in ("root", "worker"):
            if name == "worker":
                start(name)
                agent_token = call(
                    name, "POST", "/v1/auth/initialize", json={"passphrase": phrase}
                ).json()["sessionToken"]
            # The root runs the gateway, which reaches the worker's driver
            # only with the gateway grant (per-node token keys).
            grants = ["gateway"] if name == "root" else []
            join = call(
                "control", "POST", "/v1/nodes/join-token", operator, json={"grants": grants}
            ).json()["token"]
            call(
                name,
                "POST",
                "/v1/node/enroll",
                agent_token,
                json={
                    "controlUrl": url("control"),
                    "token": join,
                    "name": "a7-" + name,
                },
            ).raise_for_status()
        operator = login("root")
        # A session is good on the machine it was signed in on and the
        # root; the worker takes its own.
        worker_session = login("worker")
        runtime = {
            "name": "a7-model",
            "modelAlias": "a7-model",
            "engine": "llama_cpp",
            "binary": str(args.engine.resolve()),
            "modelPath": str(args.model.resolve()),
            "host": "127.0.0.1",
            "port": ports["engine"],
            "autoDriver": True,
            "autoStart": True,
            "flags": {"gpuLayers": 0, "contextSize": 2048},
        }
        response = call("worker", "POST", "/v1/runtimes", worker_session, json=runtime)
        assert response.status_code == 201, response.text
        wait(
            lambda: any(
                r["status"] == "ready"
                for r in call("worker", "GET", "/v1/runtimes", worker_session).json()[
                    "runtimes"
                ]
            ),
            "CPU engine ready",
        )
        models = wait(
            lambda: call("library", "GET", "/v1/models", operator).json().get("models"),
            "library scan",
        )
        model_id = next(
            m["id"] for m in models if Path(m["path"]).resolve() == args.model.resolve()
        )
        profile = {
            "name": "recovery-profile",
            "engine": "llama_cpp",
            "contextSize": 2048,
            "temperature": 0,
            "maxTokens": 64,
            "default": True,
        }
        response = call(
            "library", "POST", f"/v1/models/{model_id}/profiles", operator, json=profile
        )
        assert response.status_code == 201, response.text
        profile_id = response.json()["id"]
        keys = []
        for name in ("retained", "revoked"):
            response = call(
                "root",
                "POST",
                "/v1/auth/client-keys",
                operator,
                json={
                    "name": name,
                    "limits": {
                        "allowedModels": ["a7-model"],
                        "localOnly": True,
                        "maxConcurrentRequests": 1,
                        "requestsPerMinute": 30,
                    },
                },
            )
            assert response.status_code == 201, response.text
            keys.append(response.json())
        wait(
            lambda: any(
                m["id"] == "a7-model"
                for m in call("gateway", "GET", "/v1/models", keys[0]["token"])
                .json()
                .get("data", [])
            ),
            "gateway discovers worker",
        )
        infer(keys[0]["token"])
        call(
            "root", "DELETE", "/v1/auth/client-keys/" + keys[1]["key"]["id"], operator
        ).raise_for_status()
        wait(
            lambda: (
                call("gateway", "GET", "/v1/models", keys[1]["token"]).status_code
                == 401
            ),
            "revocation",
        )
        stop("worker")
        stop("root")
        print(
            "PASS originals and children stopped before checkpoint/update", flush=True
        )
        for name in ("root", "worker"):
            started = time.monotonic()
            recovery.backup(
                locations[name],
                root / (name + "-checkpoint"),
                password,
                {"agent": phrase, "control": phrase},
                [args.engine.resolve().parent],
                stopped=True,
            )
            timings[name + "BackupSeconds"] = time.monotonic() - started
        # A real failed package operation after the previous processes stopped,
        # with partial package mutation and deliberately incompatible new state.
        subprocess.run(
            [
                str(args.uv),
                "pip",
                "uninstall",
                "--python",
                sys.executable,
                "eugene-plexus-gateway",
            ],
            check=True,
        )
        failed = subprocess.run(
            [
                str(args.uv),
                "pip",
                "install",
                "--python",
                sys.executable,
                "--no-index",
                "eugene-a7-intentionally-nonexistent==0",
            ],
            capture_output=True,
        )
        assert failed.returncode != 0
        (locations["root"] / "library-state.json").write_text(
            '{"incompatibleFutureSchema":true}'
        )
        print(
            "PASS failed update injected after stop, with missing package and changed state",
            flush=True,
        )
        for name in ("root", "worker"):
            started = time.monotonic()
            replacement = root / (name + "-replacement")
            recovery.restore(
                root / (name + "-checkpoint"), replacement, password, args.uv
            )
            python = (
                replacement
                / "venv"
                / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            )
            blocked = subprocess.run(
                [
                    str(python),
                    "-c",
                    "from pathlib import Path; from eugene_plexus_agent.__main__ import build_server; from eugene_plexus_agent.settings import Settings; "
                    "build_server(Settings(config_file=Path(__import__('sys').argv[1])), unattended=True)",
                    str(replacement / "state/agent.yaml"),
                ],
                capture_output=True,
            )
            assert blocked.returncode != 0 and b"quarantined" in blocked.stderr
            recovery.activate(replacement, original_stopped=True)
            locations[name] = replacement / "state"
            start(name, python)
            if name == "root":
                wait(
                    lambda: call("control", "GET", "/healthz").status_code == 200,
                    "restored root",
                )
            # An enrolled agent's sign-in is checked by the control root
            # (per-node token keys), so it answers once the root does.
            wait(
                lambda: call(
                    name, "POST", "/v1/auth/login", json={"passphrase": phrase}
                ).status_code
                == 200,
                f"{name} sign-in after restore",
            )
            if name == "root":
                login("control")
            timings[name + "RestoreSeconds"] = time.monotonic() - started
        operator = login("root")
        worker_session = login("worker")
        response = call(
            "library", "GET", f"/v1/models/{model_id}/profiles/{profile_id}", operator
        )
        assert (
            response.status_code == 200
            and response.json()["name"] == "recovery-profile"
        ), response.text
        policy = call("root", "GET", "/v1/auth/client-keys", operator).json()
        assert any(
            k["id"] == keys[0]["key"]["id"] and k["limits"]["localOnly"]
            for k in policy["keys"]
        ), policy
        assert call("gateway", "GET", "/v1/models", keys[1]["token"]).status_code == 401
        wait(
            lambda: any(
                r["status"] == "ready"
                for r in call("worker", "GET", "/v1/runtimes", worker_session).json()[
                    "runtimes"
                ]
            ),
            "restored runtime",
        )
        wait(
            lambda: any(
                m["id"] == "a7-model"
                for m in call("gateway", "GET", "/v1/models", keys[0]["token"])
                .json()
                .get("data", [])
            ),
            "restored route",
        )
        infer(keys[0]["token"])
        print(
            "PASS restored authentication, profile, local-only policy, revoked key and actual inference",
            flush=True,
        )
        (root / "result.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "timings": timings,
                    "modelSha256": recovery.digest(args.model),
                },
                indent=2,
            )
        )
        print(json.dumps(timings), flush=True)
    finally:
        for name in list(processes):
            stop(name)
        for log in logs:
            log.close()
        client.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--directory", required=True, type=Path)
        parser.add_argument("--disposable-venv", required=True, type=Path)
        parser.add_argument("--uv", required=True, type=Path)
        parser.add_argument("--model", required=True, type=Path)
        parser.add_argument("--engine", required=True, type=Path)
        exercise(parser.parse_args())
