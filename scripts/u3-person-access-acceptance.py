"""Disposable real root, agent, gateway and Workbench; only inference is a fixture.

Run with control/.venv Python. Each server uses its own checkout/environment.
No installed services, default ports, real models or external providers are used.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def serve(kind, directory, port):
    if kind == "fixture":
        return load("a5-scoped-keys-acceptance").serve(kind, directory, port)
    if kind != "gateway":
        return load("u1-accounts-acceptance").serve(kind, directory, port)
    import uvicorn
    from eugene_plexus_gateway.app import create_app
    from eugene_plexus_gateway.settings import Settings

    bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
    app = create_app(
        settings=Settings(
            config_file=directory / "gateway.yaml",
            metrics_file=directory / "metrics.sqlite3",
            **bootstrap,
        )
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise():
    directory = Path(tempfile.mkdtemp(prefix="ep-u3-acceptance-"))
    print(f"Acceptance artifacts: {directory}", flush=True)
    names = ["control", "agent", "fixture", "gateway", "workbench", "ui"]
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets, strict=True)}
    for sock in sockets:
        sock.close()
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env["AGENT_URL"] = urls["agent"]
    env.pop("NODE_ENV", None)
    password = secrets.token_urlsafe(24)
    processes, logs = {}, []

    def python(repo):
        return str(
            ROOT / repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )

    with (
        httpx.Client(trust_env=False, timeout=30) as http,
        httpx.Client(trust_env=False, timeout=30) as member,
    ):

        def call(name, method, path, token=None, **kwargs):
            headers = kwargs.pop("headers", {})
            if token:
                headers["Authorization"] = "Bearer " + token
            return http.request(method, urls[name] + path, headers=headers, **kwargs)

        def wait(check, seconds=30):
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                try:
                    found = check()
                    if found:
                        return found
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            raise AssertionError("Timed out waiting for an acceptance condition")

        def stop(name):
            proc = processes.pop(name, None)
            if proc and proc.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    proc.terminate()
                proc.wait(timeout=15)

        def start(name):
            work = directory / name
            work.mkdir(exist_ok=True)
            log = (work / "process.log").open("ab")
            logs.append(log)
            args = (
                [
                    "node",
                    str(ROOT / "ui/node_modules/next/dist/bin/next"),
                    "dev",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(ports[name]),
                ]
                if name == "ui"
                else [
                    python("gateway" if name == "fixture" else name),
                    str(Path(__file__).resolve()),
                    "--serve",
                    name,
                    "--directory",
                    str(work),
                    "--port",
                    str(ports[name]),
                ]
            )
            processes[name] = subprocess.Popen(
                args,
                cwd=ROOT / "ui" if name == "ui" else work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            wait(
                lambda: (
                    call(name, "GET", "/login/" if name == "ui" else "/healthz").status_code == 200
                ),
                60,
            )

        def login(name):
            r = call(name, "POST", "/v1/auth/login", json={"passphrase": password})
            assert r.status_code == 200, r.text
            return r.json()["sessionToken"]

        def sign_in():
            response = member.get(urls["workbench"] + "/signin")
            code, location = load("c2-sign-in-acceptance").sign_in(
                member, response.headers["location"], name="Ada", password=password
            )
            assert code == 302
            callback = member.get(location)
            secret = parse_qs(urlsplit(callback.headers["location"]).fragment)["signin"][0]
            member.headers.update({"X-Workbench-Secret": secret, "Origin": urls["workbench"]})

        try:
            start("control")
            assert (
                call(
                    "control", "POST", "/v1/auth/initialize", json={"passphrase": password}
                ).status_code
                == 204
            )
            owner = login("control")
            start("agent")
            local = call(
                "agent", "POST", "/v1/auth/initialize", json={"passphrase": password}
            ).json()["sessionToken"]
            join = call(
                "control",
                "POST",
                "/v1/nodes/join-token",
                owner,
                json={"nodeName": "u3-node", "grants": ["gateway"]},
            ).json()["token"]
            enrolled = call(
                "agent",
                "POST",
                "/v1/node/enroll",
                local,
                json={"controlUrl": urls["control"], "token": join, "name": "u3-node"},
            )
            assert enrolled.status_code == 200, enrolled.text
            operator = login("agent")
            start("fixture")
            for name, kind, url in [
                ("control", "control", urls["control"]),
                *[
                    (m + "-driver", "inference-driver", urls["fixture"] + "/" + m)
                    for m in ("allowed", "excluded", "embedding")
                ],
            ]:
                r = call(
                    "agent",
                    "POST",
                    "/v1/components",
                    operator,
                    json={"name": name, "kind": kind, "url": url},
                )
                assert r.status_code == 201, r.text
            gateway = directory / "gateway"
            gateway.mkdir()
            # Ask the enrolled disposable node to make exactly its normal gateway bootstrap.
            code = (
                "import runpy,json,sys; from pathlib import Path; "
                "m=runpy.run_path(sys.argv[1]); "
                "b=m['gateway_bootstrap'](Path(sys.argv[2]),sys.argv[3]); "
                "Path(sys.argv[4]).write_text(json.dumps(b),encoding='utf-8')"
            )
            subprocess.run(
                [
                    python("agent"),
                    "-c",
                    code,
                    str(Path(__file__).with_name("a3-client-keys-acceptance.py")),
                    str(directory / "agent"),
                    urls["agent"],
                    str(gateway / "bootstrap.json"),
                ],
                env=env,
                check=True,
            )
            (gateway / "gateway.yaml").write_text(
                json.dumps(
                    {
                        "routingRefreshSeconds": 1,
                        "modelSlots": [{"model": "alias", "targets": ["allowed", "excluded"]}],
                    }
                ),
                encoding="utf-8",
            )
            start("gateway")
            app_owner = "app:workbench@u3-node"
            app = call(
                "control",
                "POST",
                "/v1/oidc/clients",
                owner,
                json={
                    "name": "Workbench",
                    "owner": app_owner,
                    "redirectUris": [urls["workbench"] + "/oidc/callback"],
                },
            ).json()
            key = call(
                "control",
                "POST",
                "/v1/auth/client-keys",
                owner,
                json={
                    "name": app_owner,
                    "limits": {
                        "allowedModels": ["alias", "allowed", "embedding"],
                        "requestsPerMinute": 1000,
                    },
                },
            ).json()
            group = call(
                "control",
                "POST",
                "/v1/permission-groups",
                owner,
                json={"name": "Builders", "apps": [app["client"]["clientId"]]},
            ).json()
            ada = call(
                "control",
                "POST",
                "/v1/people",
                owner,
                json={"name": "Ada", "password": password, "groups": [group["id"]]},
            ).json()
            work = directory / "workbench"
            work.mkdir()
            (work / "secret").write_text(app["clientSecret"], encoding="utf-8")
            (work / "key").write_text(key["token"], encoding="utf-8")
            (work / "settings.json").write_text(
                json.dumps(
                    {
                        "oidc_issuer": urls["agent"] + "/oidc",
                        "oidc_client_id": app["client"]["clientId"],
                        "oidc_secret_file": str(work / "secret"),
                        "key_file": str(work / "key"),
                        "gateway_url": urls["gateway"],
                    }
                ),
                encoding="utf-8",
            )
            start("workbench")
            sign_in()
            models = member.get(urls["workbench"] + "/api/models")
            assert (
                models.status_code == 200
                and "allowed" in models.text
                and "excluded" not in models.text
            ), models.text
            assert call("gateway", "GET", "/v1/models", key["token"]).status_code == 401
            assert (
                call(
                    "gateway",
                    "GET",
                    "/v1/models",
                    key["token"],
                    headers={"X-Eugene-App-Operation": "catalog"},
                ).status_code
                == 200
            )
            with sqlite3.connect(work / "workbench.sqlite3") as db:
                proof = db.execute("SELECT access_token FROM sessions LIMIT 1").fetchone()[0]
            proof_headers = {"X-Eugene-Person-Token": proof}
            embedded = call(
                "gateway",
                "POST",
                "/v1/embeddings",
                key["token"],
                headers=proof_headers,
                json={"model": "embedding", "input": "acceptance text"},
            )
            assert embedded.status_code == 200, embedded.text
            call("fixture", "POST", "/mode/allowed", json={"hold": True}).raise_for_status()
            chat = member.post(urls["workbench"] + "/api/chats", json={"model": "alias"}).json()[
                "id"
            ]
            r = member.post(
                urls["workbench"] + f"/api/chats/{chat}/messages",
                json={"content": "acceptance prompt"},
            )
            assert r.status_code == 201, r.text
            wait(lambda: call("fixture", "GET", "/stats").json()["allowed"] > 0)
            began = time.perf_counter()
            assert (
                call(
                    "control", "PATCH", f"/v1/people/{ada['id']}", owner, json={"groups": []}
                ).status_code
                == 200
            )
            ended = wait(
                lambda: (
                    (
                        rows := member.get(urls["workbench"] + f"/api/chats/{chat}").json()[
                            "messages"
                        ]
                    )
                    and rows[-1]["status"] != "running"
                    and rows[-1]
                ),
                18,
            )
            elapsed = time.perf_counter() - began
            assert ended["status"] == "failed" and elapsed < 15, ended
            assert member.get(urls["workbench"] + "/api/models").status_code == 403
            assert call("fixture", "GET", "/stats").json()["excluded"] == 0
            print(
                f"PASS real Workbench stream stopped after withdrawal in {elapsed:.2f}s; "
                "excluded fallback untouched",
                flush=True,
            )
            rows = wait(
                lambda: (
                    (
                        r := call("gateway", "GET", "/v1/metrics/requests", operator).json()[
                            "requests"
                        ]
                    )
                    and len(r) >= 2
                    and r
                )
            )
            assert all(row.get("personId") == ada["id"] for row in rows)
            audit = call("control", "GET", "/v1/auth/audit", owner).json()
            assert (
                audit["events"][0]["actor"] == "operator"
                and audit["events"][0]["target"] == ada["id"]
            )
            stop("control")
            start("control")
            owner = login("control")
            assert call("control", "GET", "/v1/auth/audit", owner).json() == audit
            assert member.get(urls["workbench"] + "/api/models").status_code == 403
            assert member.get(urls["workbench"] + f"/api/chats/{chat}").status_code == 200
            print(
                "PASS root restart retains revocation and audit; "
                "existing private chat remains owned by Ada",
                flush=True,
            )
            # Root outage must not revive app-only inference from a cached key registry.
            call(
                "control", "PATCH", f"/v1/people/{ada['id']}", owner, json={"groups": [group["id"]]}
            ).raise_for_status()
            stop("control")
            assert (
                call(
                    "gateway",
                    "POST",
                    "/v1/embeddings",
                    key["token"],
                    headers=proof_headers,
                    json={"model": "embedding", "input": "must not run"},
                ).status_code
                == 503
            )
            start("control")
            owner = login("control")
            sign_in()
            assert member.post(urls["workbench"] + "/api/signout").status_code == 204
            # Sign-out revokes precisely this app session at the root.
            with sqlite3.connect(work / "workbench.sqlite3") as db:
                assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
            start("ui")
            context = directory / "browser-context.json"
            context.write_text(
                json.dumps({"url": urls["ui"], "token": operator, "output": str(directory)}),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "node",
                    str(ROOT / "ui/scripts/access-audit-browser-acceptance.mjs"),
                    str(context),
                ],
                cwd=ROOT / "ui",
                env=env,
                check=True,
            )
            context.unlink()
            result = {
                "passed": True,
                "streamRevocationSeconds": round(elapsed, 3),
                "realComponents": ["control", "agent", "gateway", "workbench"],
                "fixture": "inference only",
                "fallbackDenied": True,
                "rootOutageDenied": True,
                "restartAuditPreserved": True,
                "personMetrics": True,
                "privateChatPreserved": True,
            }
            (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print("PASS U3 real-service acceptance", flush=True)
        finally:
            (directory / "browser-context.json").unlink(missing_ok=True)
            for name in list(processes):
                stop(name)
            for log in logs:
                log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    serve(args.serve, args.directory, args.port) if args.serve else exercise()
