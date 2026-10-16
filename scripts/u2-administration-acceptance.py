"""U2: disposable real root, agent, Workbench and Chrome; no release build.

Run with control/.venv's Python. Next dev forwards to the temporary agent.
All ports and state are isolated; all APIs are real. No inference or live keys.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]


def exercise(*, production_ui: bool = False) -> None:
    directory = Path(tempfile.mkdtemp(prefix="ep-u2-acceptance-"))
    print(f"Acceptance artifacts: {directory}", flush=True)
    spec = importlib.util.spec_from_file_location(
        "c2", Path(__file__).with_name("c2-sign-in-acceptance.py")
    )
    c2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(c2)
    ports = {}
    for name in ("control", "agent", "workbench", "ui"):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            ports[name] = sock.getsockname()[1]
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env["AGENT_URL"] = urls["agent"]
    env.pop("NODE_ENV", None)
    password = secrets.token_urlsafe(24)
    processes = {}
    logs = []
    with httpx.Client(trust_env=False, timeout=60) as http:

        def call(name, method, path, token=None, **kwargs):
            return http.request(
                method,
                urls[name] + path,
                headers={"Authorization": f"Bearer {token}"} if token else {},
                **kwargs,
            )

        def start(name):
            work = directory / name
            work.mkdir(exist_ok=True)
            log = (work / "process.log").open("ab")
            logs.append(log)
            if name == "ui":
                args = [
                    "node",
                    str(ROOT / "ui/node_modules/next/dist/bin/next"),
                    "dev",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(ports[name]),
                ]
                cwd = ROOT / "ui"
            else:
                python = (
                    ROOT
                    / name
                    / ".venv"
                    / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                )
                args = [
                    str(python),
                    str(Path(__file__).with_name("u1-accounts-acceptance.py")),
                    "--serve",
                    name,
                    "--directory",
                    str(work),
                    "--port",
                    str(ports[name]),
                ]
                cwd = work
            processes[name] = subprocess.Popen(
                args,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            deadline = time.perf_counter() + 60
            while time.perf_counter() < deadline:
                try:
                    if (
                        call(
                            name,
                            "GET",
                            "/administration/" if name == "ui" else "/healthz",
                        ).status_code
                        == 200
                    ):
                        return
                except httpx.HTTPError:
                    pass
                if processes[name].poll() is not None:
                    raise RuntimeError(f"{name} stopped; see {work / 'process.log'}")
                time.sleep(0.1)
            raise RuntimeError(f"{name} did not start")

        def sign_in(member, name):
            response = member.get(urls["workbench"] + "/signin")
            code, location = c2.sign_in(
                member, response.headers["location"], name=name, password=password
            )
            assert code == 302, (code, location)
            callback = member.get(location)
            secret = parse_qs(urlsplit(callback.headers["location"]).fragment)["signin"][0]
            member.headers.update({"X-Workbench-Secret": secret, "Origin": urls["workbench"]})

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
            owner = call("control", "POST", "/v1/auth/login", json={"passphrase": password}).json()[
                "sessionToken"
            ]
            join = call(
                "control",
                "POST",
                "/v1/nodes/join-token",
                owner,
                json={"nodeName": "u2-node"},
            ).json()["token"]
            local = call(
                "agent", "POST", "/v1/auth/initialize", json={"passphrase": password}
            ).json()["sessionToken"]
            enrolled = call(
                "agent",
                "POST",
                "/v1/node/enroll",
                local,
                json={"controlUrl": urls["control"], "token": join, "name": "u2-node"},
            )
            assert enrolled.status_code == 200, enrolled.text
            operator = call(
                "agent", "POST", "/v1/auth/login", json={"passphrase": password}
            ).json()["sessionToken"]
            assert (
                call(
                    "agent",
                    "POST",
                    "/v1/components",
                    operator,
                    json={"name": "control", "kind": "control", "url": urls["control"]},
                ).status_code
                == 201
            )
            app = call(
                "control",
                "POST",
                "/v1/oidc/clients",
                owner,
                json={
                    "name": "Workbench",
                    "redirectUris": [urls["workbench"] + "/oidc/callback"],
                },
            ).json()
            ada = call(
                "control",
                "POST",
                "/v1/people",
                owner,
                json={"name": "Ada", "password": password},
            ).json()
            manager = call(
                "control",
                "POST",
                "/v1/people",
                owner,
                json={"name": "Manager", "password": password},
            ).json()
            group = call(
                "control",
                "POST",
                "/v1/permission-groups",
                owner,
                json={"name": "Builders", "apps": [app["client"]["clientId"]]},
            ).json()
            policy = {"managePeople": True, "membershipGroups": [group["id"]]}
            assert (
                call(
                    "control",
                    "PUT",
                    f"/v1/people/{manager['id']}/administration",
                    owner,
                    json=policy,
                ).status_code
                == 200
            )
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
            with (
                httpx.Client(trust_env=False, timeout=30) as ada_app,
                httpx.Client(trust_env=False, timeout=30) as manager_app,
            ):
                sign_in(ada_app, "Ada")
                chat = ada_app.post(
                    urls["workbench"] + "/api/chats",
                    json={"model": "acceptance-no-inference"},
                )
                assert chat.status_code == 201, chat.text
                chat_id = chat.json()["id"]
                sign_in(manager_app, "Manager")
                assert manager_app.get(urls["workbench"] + f"/api/chats/{chat_id}").status_code in (
                    403,
                    404,
                )
                print(
                    "PASS named administrator cannot read another person's real Workbench chat",
                    flush=True,
                )
                processes["control"].terminate()
                processes["control"].wait(timeout=15)
                start("control")
                assert (
                    call(
                        "control",
                        "POST",
                        "/v1/auth/administration/login",
                        json={"name": "Manager", "password": password},
                    ).status_code
                    == 503
                )
                owner = call(
                    "control", "POST", "/v1/auth/login", json={"passphrase": password}
                ).json()["sessionToken"]
                listed = call("control", "GET", "/v1/people", owner).json()["people"]
                restored = next(p for p in listed if p["id"] == manager["id"])
                assert restored["administration"]["membershipGroups"] == [group["id"]]
                assert ada_app.get(urls["workbench"] + f"/api/chats/{chat_id}").status_code == 200
                print(
                    "PASS root restart preserves delegation and private-chat ownership; "
                    "named login cannot unlock",
                    flush=True,
                )
                if production_ui:
                    urls["ui"] = urls["agent"]
                else:
                    start("ui")
                context = directory / "browser-context.json"
                context.write_text(
                    json.dumps(
                        {
                            "url": urls["ui"],
                            "agent": urls["agent"],
                            "control": urls["control"],
                            "owner": owner,
                            "password": password,
                            "manager": manager["id"],
                            "person": ada["id"],
                            "output": str(directory),
                        }
                    )
                )
                subprocess.run(
                    [
                        "node",
                        str(ROOT / "ui/scripts/administration-browser-acceptance.mjs"),
                        str(context),
                    ],
                    cwd=ROOT / "ui",
                    env=env,
                    check=True,
                )
                context.unlink()  # ephemeral login credentials are not evidence
                assert ada_app.get(urls["workbench"] + f"/api/chats/{chat_id}").status_code == 200
            (directory / "result.json").write_text(
                json.dumps(
                    {
                        "passed": True,
                        "privateChatIsolated": True,
                        "restartPreserved": True,
                        "namedCannotUnlock": True,
                        "realProxy": True,
                        "ui": "production export" if production_ui else "development build",
                    },
                    indent=2,
                )
            )
        finally:
            (directory / "browser-context.json").unlink(missing_ok=True)
            for process in processes.values():
                if process.poll() is None:
                    if os.name == "nt":
                        # Next starts a child server; end this harness-owned process tree.
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    else:
                        process.terminate()
                    process.wait(timeout=15)
            for log in logs:
                log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-ui", action="store_true")
    exercise(production_ui=parser.parse_args().production_ui)
