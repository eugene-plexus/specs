"""U1: isolated real root + agent + Workbench, with the production UI in Chrome.

Run from sibling checkouts after building ui and workbench/web:
  ../control/.venv/Scripts/python scripts/u1-accounts-acceptance.py
Each server uses its own checkout's virtual environment and an ephemeral port.
No model, provider credentials, installed service or default port is used.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(
                config_file=directory / "control.yaml", state_dir=directory / "state"
            )
        )
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml",
                default_topology=False,
                bind_port=port,
                ui_dir=ROOT / "ui/out",
            )
        )
    else:
        from eugene_plexus_workbench.app import create_app
        from eugene_plexus_workbench.settings import Settings

        settings = json.loads((directory / "settings.json").read_text())
        app = create_app(Settings(data_dir=directory, bind_port=port, **settings))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(directory: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "c2", Path(__file__).with_name("c2-sign-in-acceptance.py")
    )
    c2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(c2)
    ports = {}
    for name in ("control", "agent", "workbench"):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            ports[name] = sock.getsockname()[1]
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    processes = {}
    logs = []
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    password = secrets.token_urlsafe(24)
    with (
        httpx.Client(trust_env=False, timeout=30) as http,
        httpx.Client(trust_env=False, timeout=30) as member,
    ):

        def call(name, method, path, token=None, **kwargs):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            return http.request(method, urls[name] + path, headers=headers, **kwargs)

        def start(name):
            work = directory / name
            work.mkdir(exist_ok=True)
            log = (work / "process.log").open("ab")
            logs.append(log)
            python = (
                ROOT
                / name
                / ".venv"
                / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            )
            processes[name] = subprocess.Popen(
                [
                    str(python),
                    str(Path(__file__).resolve()),
                    "--serve",
                    name,
                    "--directory",
                    str(work),
                    "--port",
                    str(ports[name]),
                ],
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            deadline = time.perf_counter() + 45
            while time.perf_counter() < deadline:
                try:
                    if call(name, "GET", "/healthz").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                if processes[name].poll() is not None:
                    raise RuntimeError(f"{name} stopped; see {work / 'process.log'}")
                time.sleep(0.1)
            raise RuntimeError(f"{name} did not start")

        def sign_in():
            start_signin = member.get(urls["workbench"] + "/signin")
            assert start_signin.status_code == 302, start_signin.text
            code, location = c2.sign_in(
                member, start_signin.headers["location"], name="Ada", password=password
            )
            assert code == 302, (code, location)
            callback = member.get(location)
            assert callback.status_code == 303, callback.text
            secret = parse_qs(urlsplit(callback.headers["location"]).fragment)[
                "signin"
            ][0]
            member.headers.update(
                {"X-Workbench-Secret": secret, "Origin": urls["workbench"]}
            )

        try:
            start("control")
            start("agent")
            assert (
                call(
                    "control",
                    "POST",
                    "/v1/auth/initialize",
                    json={"passphrase": password},
                ).status_code
                == 204
            )
            token = call(
                "control", "POST", "/v1/auth/login", json={"passphrase": password}
            ).json()["sessionToken"]
            join = call(
                "control",
                "POST",
                "/v1/nodes/join-token",
                token,
                json={"nodeName": "u1-node"},
            ).json()["token"]
            local = call(
                "agent", "POST", "/v1/auth/initialize", json={"passphrase": password}
            ).json()["sessionToken"]
            enrolled = call(
                "agent",
                "POST",
                "/v1/node/enroll",
                local,
                json={"controlUrl": urls["control"], "token": join, "name": "u1-node"},
            )
            assert enrolled.status_code == 200, enrolled.text
            operator = call(
                "agent", "POST", "/v1/auth/login", json={"passphrase": password}
            ).json()["sessionToken"]
            registered = call(
                "agent",
                "POST",
                "/v1/components",
                operator,
                json={"name": "control", "kind": "control", "url": urls["control"]},
            )
            assert registered.status_code == 201, registered.text
            app = call(
                "control",
                "POST",
                "/v1/oidc/clients",
                token,
                json={
                    "name": "Workbench",
                    "redirectUris": [urls["workbench"] + "/oidc/callback"],
                },
            ).json()
            ada = call(
                "control",
                "POST",
                "/v1/people",
                token,
                json={"name": "Ada", "password": password},
            ).json()
            work = directory / "workbench"
            work.mkdir()
            secret_file = work / "client-secret"
            secret_file.write_text(app["clientSecret"], encoding="utf-8")
            (work / "settings.json").write_text(
                json.dumps(
                    {
                        "oidc_issuer": urls["agent"] + "/oidc",
                        "oidc_client_id": app["client"]["clientId"],
                        "oidc_secret_file": str(secret_file),
                    }
                )
            )
            start("workbench")
            sign_in()
            me = member.get(urls["workbench"] + "/api/me")
            assert me.status_code == 200 and me.json()["sub"] == ada["id"], me.text
            chat = member.post(
                urls["workbench"] + "/api/chats",
                json={"model": "acceptance-no-inference"},
            )
            assert chat.status_code == 201, chat.text
            chat_id = chat.json()["id"]
            print(
                "PASS existing central account signs into real Workbench and owns a chat",
                flush=True,
            )
            context = directory / "browser-context.json"
            context.write_text(
                json.dumps(
                    {"url": urls["agent"], "token": operator, "output": str(directory)}
                )
            )
            subprocess.run(
                [
                    "node",
                    str(ROOT / "ui/scripts/accounts-browser-acceptance.mjs"),
                    str(context),
                ],
                cwd=ROOT / "ui",
                check=True,
                env=env,
            )
            listed = call("control", "GET", "/v1/people", token).json()["people"][0]
            assert listed["id"] == ada["id"] and len(listed["groups"]) == 1
            assert listed["appsInEffect"] == [app["client"]["clientId"]]
            group_id = listed["groups"][0]
            sign_in()
            assert (
                member.get(urls["workbench"] + f"/api/chats/{chat_id}").status_code
                == 200
            )
            print(
                "PASS group assignment preserves subject and existing private chat",
                flush=True,
            )
            processes["control"].terminate()
            processes["control"].wait(timeout=15)
            start("control")
            token = call(
                "control", "POST", "/v1/auth/login", json={"passphrase": password}
            ).json()["sessionToken"]
            restored = call("control", "GET", "/v1/people", token).json()["people"][0]
            assert (
                restored["groups"] == [group_id]
                and restored["appsInEffect"] == listed["appsInEffect"]
            )
            print(
                "PASS root restart replays group definitions and memberships",
                flush=True,
            )
            assert (
                call(
                    "control", "DELETE", f"/v1/permission-groups/{group_id}", token
                ).status_code
                == 204
            )
            empty = call("control", "GET", "/v1/people", token).json()["people"][0]
            assert (
                empty["groups"]
                == empty["appsInEffect"]
                == empty["permissionsInEffect"]
                == []
            )
            # Advance only the disposable app session's refresh deadline. The actual
            # refresh uses Workbench's provider over the agent and real root.
            with sqlite3.connect(work / "workbench.sqlite3") as db:
                db.execute("UPDATE sessions SET access_expires_at = 0")
            assert member.get(urls["workbench"] + "/api/me").status_code == 401
            print(
                "PASS last-group deletion denies real Workbench refresh; no default access restored",
                flush=True,
            )
            assert (
                call(
                    "control",
                    "PATCH",
                    f"/v1/people/{ada['id']}",
                    token,
                    json={"groups": None},
                ).status_code
                == 200
            )
            sign_in()
            assert (
                member.get(urls["workbench"] + f"/api/chats/{chat_id}").status_code
                == 200
            )
            print(
                "PASS explicit individual-access restoration recovers the same account and chat",
                flush=True,
            )
            (directory / "result.json").write_text(
                json.dumps(
                    {
                        "passed": True,
                        "components": list(ports),
                        "chatPreserved": True,
                        "refreshDenied": True,
                    },
                    indent=2,
                )
            )
        finally:
            for process in processes.values():
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
            for log in logs:
                log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", choices=["control", "agent", "workbench"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = args.directory or Path(tempfile.mkdtemp(prefix="ep-u1-acceptance-"))
        directory.mkdir(exist_ok=True)
        print(f"Acceptance artifacts: {directory}", flush=True)
        exercise(directory)
