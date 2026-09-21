"""A3 isolated process acceptance: one real root, two agents and two gateways.

Uses ephemeral loopback ports and temporary state, no models or installed services.
Run with Python containing editable installs of agent, control and gateway.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
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
    elif kind.startswith("agent"):
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml",
                default_topology=False,
                bind_port=port,
            )
        )
    elif kind == "hung":
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/v1/auth/client-keys/policy")
        async def hang():
            with (directory / "reads.txt").open("a") as output:
                output.write("read\n")
            await asyncio.sleep(30)
            return {}
    else:
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text())
        assert (
            "PRIVATE KEY" not in base64.b64decode(bootstrap["auth_verify_key"]).decode()
        )
        app = create_app(
            settings=Settings(
                config_file=directory / "gateway.yaml",
                metrics_file=directory / "metrics.sqlite3",
                client_key_refresh_seconds=0.15,
                client_key_max_age_seconds=3.5,
                client_key_timeout_seconds=0.4,
                client_key_retry_seconds=0.1,
                **bootstrap,
            )
        )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(directory: Path) -> None:
    from eugene_plexus_agent import security
    from eugene_plexus_agent.client_keys import ClientKeyStore, ClientKeyRecord
    from cryptography.hazmat.primitives import serialization
    from eugene_plexus_gateway.settings import Settings as GatewaySettings

    defaults = GatewaySettings()
    assert (
        defaults.client_key_refresh_seconds,
        defaults.client_key_timeout_seconds,
        defaults.client_key_max_age_seconds,
    ) == (15, 4, 60)
    names = ("control", "agent-a", "agent-b", "gateway-a", "gateway-b")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets)}
    for sock in sockets:
        sock.close()
    processes = {}
    logs = []
    client = httpx.Client(timeout=8, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name):
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        return client.request(
            method,
            url(name) + path,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            **kwargs,
        )

    def wait(check, label, seconds=12):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise AssertionError("timed out: " + label)

    def start(name, kind=None):
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")
        }
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                kind or name,
                "--directory",
                str(work),
                "--port",
                str(ports[name]),
            ],
            cwd=work,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    def stop(name):
        process = processes.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        assert response.status_code == 200, response.text
        return response.json()["sessionToken"]

    def status(name, token):
        return call(name, "GET", "/v1/models", token).status_code

    try:
        start("control")
        assert (
            call(
                "control",
                "POST",
                "/v1/auth/initialize",
                json={"passphrase": passphrase},
            ).status_code
            == 204
        )
        operator = login("control")
        for name in ("agent-a", "agent-b"):
            work = directory / name
            work.mkdir(exist_ok=True)
            (work / "agent.yaml").write_text(
                yaml.safe_dump(
                    {
                        "firstRunComplete": True,
                        "advertiseUrl": url(name),
                        "securityMode": "prompt_on_startup",
                        "components": [],
                    }
                )
            )
            start(name)
            assert (
                call(
                    name, "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
                ).status_code
                == 200
            )
            local_operator = login(name)
            join = call("control", "POST", "/v1/nodes/join-token", operator).json()[
                "token"
            ]
            enrolled = call(
                name,
                "POST",
                "/v1/node/enroll",
                local_operator,
                json={"controlUrl": url("control"), "token": join, "name": name},
            )
            assert enrolled.status_code == 200, enrolled.text

        # Simulate the legacy issuer's existing file, preserving both active and revoked keys.
        stop("agent-a")
        identity = yaml.safe_load((directory / "agent-a/node.yaml").read_text())
        private = base64.b64decode(identity["signingKey"])
        public = (
            serialization.load_pem_private_key(private, password=None)
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        store = ClientKeyStore(directory / "agent-a/client_keys.json")
        legacy = {}
        for key_id in ("legacy-active", "legacy-revoked"):
            token, exp = security.issue_client_token(
                signing_key=private, key_id=key_id, name=key_id
            )
            legacy[key_id] = token
            store.add(ClientKeyRecord(key_id, key_id, token[-6:], time.time(), exp))
        store.revoke("legacy-revoked")
        start("agent-a")
        listed = call("agent-a", "GET", "/v1/auth/client-keys", operator)
        assert listed.status_code == 200, listed.text
        assert listed.json()["migration"] == "complete", listed.text
        assert {key["id"] for key in listed.json()["keys"]} == set(legacy)
        assert all(
            key["migrated"] and key["originNode"] == "agent-a"
            for key in listed.json()["keys"]
        )
        print(
            "PASS signed legacy migration preserves active/revoked IDs and reports origin",
            flush=True,
        )

        for gateway, agent in (("gateway-a", "agent-a"), ("gateway-b", "agent-b")):
            work = directory / gateway
            work.mkdir()
            (work / "bootstrap.json").write_text(
                json.dumps(
                    {
                        "agent_url": url(agent),
                        "auth_verify_key": base64.b64encode(public).decode(),
                        "service_token": security.issue_service_token(
                            signing_key=private, kind="gateway"
                        ),
                    }
                )
            )
            start(gateway)
        minted = call(
            "agent-a",
            "POST",
            "/v1/auth/client-keys",
            operator,
            json={"name": "cross-node"},
        )
        assert minted.status_code == 201, minted.text
        key = minted.json()
        for gateway in ("gateway-a", "gateway-b"):
            wait(lambda: status(gateway, key["token"]) == 200, "new key registered")
            assert status(gateway, legacy["legacy-active"]) == 200
            assert status(gateway, legacy["legacy-revoked"]) == 401
        revoked_at = time.perf_counter()
        assert (
            call(
                "agent-b",
                "DELETE",
                "/v1/auth/client-keys/" + key["key"]["id"],
                operator,
            ).status_code
            == 204
        )
        wait(
            lambda: all(
                status(g, key["token"]) == 401 for g in ("gateway-a", "gateway-b")
            ),
            "both revoke",
            2,
        )
        print(
            f"PASS mint via A, use at both gateways, revoke via B: {time.perf_counter() - revoked_at:.3f}s",
            flush=True,
        )

        # A5's current admission check can refuse a revoked key before A3's
        # periodic policy refresh has persisted it. Establish the cache state
        # explicitly before testing that it survives an offline restart.
        def cached_revocation(gateway):
            if status(gateway, key["token"]) != 401:
                return False
            saved = json.loads(
                (directory / gateway / "gateway.client-keys.json").read_text(encoding="utf-8")
            )
            return any(
                record["id"] == key["key"]["id"] and record.get("revokedAt")
                for record in saved["policy"]["keys"]
            )

        wait(
            lambda: all(cached_revocation(g) for g in ("gateway-a", "gateway-b")),
            "revocation persisted in both authentication caches",
            2,
        )

        stop("agent-a")
        stop("gateway-a")
        start("gateway-a")
        assert status("gateway-a", key["token"]) == 401
        wait(
            lambda: status("gateway-a", legacy["legacy-active"]) == 503,
            "local-agent cache expires",
            6,
        )
        assert call("gateway-a", "GET", "/v1/config", operator).status_code == 200
        print(
            "PASS gateway restart retains revocation; local-agent outage expires permission; operator repair works",
            flush=True,
        )

        # Empty-cache concurrent requests to a real hung HTTP process share one timeout.
        stop("gateway-a")
        (directory / "gateway-a/gateway.client-keys.json").rename(
            directory / "gateway-a/saved-policy.json"
        )
        start("agent-a", "hung")
        start("gateway-a")
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=24) as pool:
            codes = list(
                pool.map(
                    lambda _: status("gateway-a", legacy["legacy-active"]), range(24)
                )
            )
        elapsed = time.perf_counter() - started
        assert set(codes) == {503}, codes
        reads = len((directory / "agent-a/reads.txt").read_text().splitlines())
        assert reads <= 2 and elapsed < 2.5, (reads, elapsed)
        print(
            f"PASS 24 simultaneous cold-cache requests: {elapsed:.3f}s, {reads} policy read(s), all 503",
            flush=True,
        )
        stop("agent-a")
        start("agent-a")
        wait(
            lambda: status("gateway-a", legacy["legacy-active"]) == 200,
            "agent recovery",
        )

        stop("control")
        wait(
            lambda: all(
                status(g, legacy["legacy-active"]) == 503
                for g in ("gateway-a", "gateway-b")
            ),
            "control outage policy expires",
            6,
        )
        for gateway in ("gateway-a", "gateway-b"):
            assert status(gateway, key["token"]) == 401
            stop(gateway)
            start(gateway)
            assert status(gateway, legacy["legacy-active"]) == 503
            assert status(gateway, key["token"]) == 401
        print(
            "PASS control outage and stale persisted-cache restarts fail closed at both gateways",
            flush=True,
        )
        start("control")
        operator = login("control")
        wait(
            lambda: all(
                status(g, legacy["legacy-active"]) == 200
                for g in ("gateway-a", "gateway-b")
            ),
            "control recovery",
        )
        for gateway in ("gateway-a", "gateway-b"):
            assert status(gateway, key["token"]) == 401
            expired, _ = security.issue_client_token(
                signing_key=private,
                key_id="expired",
                name="expired",
                now=int(time.time()) - 4000,
                ttl_seconds=1,
            )
            assert status(gateway, expired) == 401
            assert status(gateway, "invalid") == 401
            unknown, _ = security.issue_client_token(
                signing_key=private, key_id="unregistered", name="unknown"
            )
            assert (
                "not registered"
                in call(gateway, "GET", "/v1/models", unknown).text.lower()
            )
        print(
            "PASS recovery keeps revocations; invalid, expired and unregistered credentials are refused",
            flush=True,
        )
        print(
            "PASS default bounds 15s refresh / 4s timeout / 60s age; all gateway bootstrap material is public-only",
            flush=True,
        )
    finally:
        for name in list(processes):
            stop(name)
        client.close()
        for log in logs:
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-a3-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory)
