"""Real control + two enrolled agents; simulated installer/app boundaries.

Exercises production Update all, auth, token exchange, proxy and journal over
HTTP, kills its hosting agent during an update, then restarts it. No installed
service, package, container, model or live Eugene state is changed. Run with a
Python environment containing editable agent and control. Ephemeral ports only.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

REF = "c" * 40
STAMP = "a" * 40


def serve(kind, directory, port, host):
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(
                config_file=directory / "control.yaml", state_dir=directory / "state"
            )
        )
    else:
        from fastapi import Depends, HTTPException
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings
        from eugene_plexus_agent.dependencies import require_operator_session
        from eugene_plexus_agent._generated.models import NodeInstall, NodeUpdate
        from eugene_plexus_agent.routes import node
        from eugene_plexus_agent._private_files import write_private
        from eugene_plexus_agent.engines.devices import DeviceSnapshot

        app = create_app(
            Settings(
                config_file=directory / "agent.yaml",
                default_topology=False,
                bind_host=host,
                bind_port=port,
            )
        )
        app.state.device_detector = lambda: DeviceSnapshot(
            (), (), 16 * 2**30, 12 * 2**30, datetime.now(UTC)
        )
        state_file = directory / "fixture.json"

        def read():
            return (
                json.loads(state_file.read_text())
                if state_file.exists()
                else {"app": "old", "writes": 0}
            )

        def save(state):
            write_private(state_file, json.dumps(state))

        def views(_request=None):
            state = read()
            result = state.get("last")
            finished = result and result["outcome"] == "succeeded"
            return NodeInstall.model_validate(
                {
                    "components": [
                        {
                            "name": "agent",
                            "state": "stamped",
                            "commit": STAMP if finished else "b" * 40,
                        }
                    ],
                    "mechanism": "systemd_user",
                    "development": False,
                }
            ), NodeUpdate.model_validate(
                {
                    "enabled": False,
                    "channel": "edge",
                    "channelSource": "setting",
                    "available": not finished,
                    "behind": [] if finished else ["agent"],
                    "apply": {"possible": True},
                    "newest": {
                        "channel": "edge",
                        "ref": REF,
                        "components": {"agent": STAMP},
                    },
                    "running": result
                    if result and result["outcome"] == "running"
                    else None,
                    "last": result if finished else None,
                }
            )

        node.node_update_view = views
        replace = {
            "/v1/node/update/check",
            "/v1/node/update",
            "/v1/app-catalogue",
            "/v1/apps/{app_id}",
            "/v1/apps/{app_id}/install",
        }
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", None) not in replace
        ]
        insertion = len(app.router.routes)
        auth = [Depends(require_operator_session)]

        @app.post("/v1/node/update/check", dependencies=auth)
        async def check():
            return views()[1]

        @app.post("/v1/node/update", dependencies=auth, status_code=202)
        async def update():
            state = read()
            state["writes"] += 1
            state["last"] = {
                "target": REF,
                "startedAt": datetime.now(UTC).isoformat(),
                "outcome": "running" if kind == "root" else "succeeded",
            }
            save(state)
            return state["last"]

        @app.get("/v1/app-catalogue", dependencies=auth)
        async def catalogue():
            return {
                "apps": [
                    {
                        "origin": "catalogue",
                        "installedVersion": read()["app"],
                        "manifest": {"id": "workbench", "version": "new"},
                    }
                ]
            }

        @app.get("/v1/apps/{app_id}", dependencies=auth)
        async def get_app(app_id: str):
            return {"id": app_id, "version": read()["app"], "status": "running"}

        @app.post("/v1/apps/{app_id}/install", dependencies=auth, status_code=202)
        async def install(app_id: str):
            state = read()
            state["app"] = "new"
            state["appWrites"] = state.get("appWrites", 0) + 1
            save(state)
            return {"app": app_id, "state": "done", "version": "new"}

        @app.get("/v1/apps/{app_id}/install", dependencies=auth)
        async def get_install(app_id: str):
            if read()["app"] != "new":
                raise HTTPException(404)
            return {"app": app_id, "state": "done", "version": "new"}

        # create_app installs its static UI catch-all last; fixture boundaries
        # must precede it just like the production API routers do.
        app.router.routes[:] = (
            app.router.routes[insertion:] + app.router.routes[:insertion]
        )
    uvicorn.run(app, host=host, port=port, log_level="error", access_log=False)


def exercise(directory):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.connect(("192.0.2.1", 9))
    host = probe.getsockname()[0]
    probe.close()
    names = ("control", "root", "worker")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind((host, 0))
    ports = {n: s.getsockname()[1] for n, s in zip(names, sockets, strict=True)}
    for sock in sockets:
        sock.close()
    urls = {n: f"http://{host}:{ports[n]}" for n in names}
    procs, logs = {}, []
    phrase = secrets.token_urlsafe(24)
    client = httpx.Client(timeout=20, trust_env=False)

    def call(name, method, path, token=None, **kw):
        return client.request(
            method,
            urls[name] + path,
            headers={"authorization": "Bearer " + token} if token else {},
            **kw,
        )

    def wait(check, label, seconds=60):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            try:
                result = check()
                if result:
                    return result
            except (httpx.HTTPError, OSError, ValueError):
                pass
            time.sleep(0.2)
        raise AssertionError("Timed out: " + label)

    def start(name):
        work = directory / name
        work.mkdir(exist_ok=True)
        output = (work / "process.log").open("ab")
        logs.append(output)
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")
        }
        env.update(
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring", PYTHONUTF8="1"
        )
        procs[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                name,
                "--directory",
                str(work),
                "--port",
                str(ports[name]),
                "--host",
                host,
            ],
            env=env,
            cwd=work,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name + " health")

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": phrase})
        response.raise_for_status()
        return response.json()["sessionToken"]

    try:
        start("control")
        call(
            "control", "POST", "/v1/auth/initialize", json={"passphrase": phrase}
        ).raise_for_status()
        authority = login("control")
        for name in ("root", "worker"):
            work = directory / name
            work.mkdir()
            components = (
                [{"name": "control", "kind": "control", "url": urls["control"]}]
                if name == "root"
                else []
            )
            (work / "agent.yaml").write_text(
                yaml.safe_dump(
                    {
                        "firstRunComplete": True,
                        "updateChecks": False,
                        "advertiseUrl": urls[name],
                        "securityMode": "prompt_on_startup",
                        "components": components,
                    }
                ),
                encoding="utf-8",
            )
            start(name)
            initialized = call(
                name, "POST", "/v1/auth/initialize", json={"passphrase": phrase}
            )
            initialized.raise_for_status()
            join = call(
                "control",
                "POST",
                "/v1/nodes/join-token",
                authority,
                json={"grants": []},
            )
            join.raise_for_status()
            enrolled = call(
                name,
                "POST",
                "/v1/node/enroll",
                initialized.json()["sessionToken"],
                json={
                    "controlUrl": urls["control"],
                    "token": join.json()["token"],
                    "name": name,
                },
            )
            enrolled.raise_for_status()
        session = login("root")
        assert call("root", "POST", "/v1/updates/all", json={}).status_code == 401
        response = call("root", "POST", "/v1/updates/all", session, json={})
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        assert response.json()["root"] == "root"  # Registry still says role=agent.
        assert (
            call("root", "POST", "/v1/updates/all", session, json={}).json()["id"]
            == run_id
        )
        print(
            "PASS real enrollment, operator auth, active-root discovery and one job",
            flush=True,
        )
        journal = directory / "root" / "update-all.json"
        fixture = directory / "root" / "fixture.json"
        wait(
            lambda: (
                fixture.exists() and json.loads(fixture.read_text()).get("writes") == 1
            ),
            "root installer request",
        )
        assert json.loads(journal.read_text())["run"]["items"][0]["state"] == "updating"
        procs["root"].terminate()
        procs["root"].wait(timeout=15)
        state = json.loads(fixture.read_text())
        state["last"]["outcome"] = "succeeded"
        fixture.write_text(json.dumps(state), encoding="utf-8")
        start("root")

        def finished():
            result = call("root", "GET", "/v1/updates/all", session)
            result.raise_for_status()
            run = result.json().get("run", {})
            return run if run.get("state") != "running" else None

        run = wait(finished, "resumed job completion")
        assert run["state"] == "complete", json.dumps(run, indent=2)
        assert run["id"] == run_id and len(run["items"]) == 4
        for name in ("root", "worker"):
            state = json.loads((directory / name / "fixture.json").read_text())
            assert state["writes"] == 1 and state["appWrites"] == 1, (name, state)
        assert json.loads(journal.read_text())["token"] == ""
        assert session not in json.dumps(run)
        print(
            "PASS forced coordinator restart, normal remote token exchange and HTTP proxy, root and worker apps, no duplicate writes, private session removed",
            flush=True,
        )
    finally:
        client.close()
        for proc in procs.values():
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=15)
        for output in logs:
            output.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port, args.host)
    elif args.directory:
        args.directory.mkdir()  # Never adopt or overwrite an earlier run.
        exercise(args.directory)
    else:
        with tempfile.TemporaryDirectory(prefix="ep-update-all-") as temp:
            exercise(Path(temp))


if __name__ == "__main__":
    main()
