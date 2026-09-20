"""Isolated live HS256 -> Ed25519 rotation, using all five installed components.

Install the five local projects into one disposable environment, then run this
script with its Python. Uses temporary state and loopback ports 8179-8183 only;
refuses occupied ports. No real model, backend, keyring, or installed config.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import httpx
import jwt
import yaml

PORTS = {
    "agent": 8179,
    "gateway": 8180,
    "inference-driver": 8181,
    "library": 8182,
    "control": 8183,
}


def url(kind: str) -> str:
    return f"http://127.0.0.1:{PORTS[kind]}"


def serve(kind: str, directory: Path) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(
                config_file=directory / "control.yaml",
                state_dir=directory / "root-state",
            )
        )
    else:
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml",
                bind_port=PORTS["agent"],
                default_topology=False,
            )
        )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=PORTS[kind],
            log_level="warning",
            access_log=False,
        )
    )

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (directory / f"{kind}.stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task

    asyncio.run(run())


def seed_legacy_root(directory: Path, passphrase: str) -> None:
    from fastapi.testclient import TestClient
    from eugene_plexus_control import security
    from eugene_plexus_control.app import create_app
    from eugene_plexus_control.settings import Settings

    app = create_app(
        Settings(
            config_file=directory / "control.yaml", state_dir=directory / "root-state"
        )
    )
    with (
        patch.object(security, "generate_signing_key", return_value=b"L" * 32),
        TestClient(app) as client,
    ):
        response = client.post("/v1/auth/initialize", json={"passphrase": passphrase})
        assert response.status_code == 204, "legacy root initialization failed"


def exercise(directory: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from eugene_plexus_agent import security
    from eugene_plexus_agent._generated.models import ComponentEntry
    from eugene_plexus_agent.auth_state import AuthState
    from eugene_plexus_agent.supervisor import _ComponentPlanner

    # Refuse before creating processes if any acceptance port is occupied.
    sockets = []
    try:
        for port in PORTS.values():
            sock = socket.socket()
            sockets.append(sock)
            sock.bind(("127.0.0.1", port))
    finally:
        for sock in sockets:
            sock.close()

    passphrase = secrets.token_urlsafe(24)
    seed_legacy_root(directory, passphrase)
    entries = []
    for kind in ("gateway", "library", "inference-driver"):
        env = {}
        if kind == "gateway":
            env["EUGENE_PLEXUS_GATEWAY_METRICS_FILE"] = str(
                directory / "metrics.sqlite3"
            )
        entries.append(
            {
                "name": kind,
                "kind": kind,
                "url": url(kind),
                "spawn": {"configFile": str(directory / f"{kind}.yaml"), "env": env},
            }
        )
    entries.append({"name": "control", "kind": "control", "url": url("control")})
    (directory / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "advertiseUrl": url("agent"),
                "securityMode": "prompt_on_startup",
                "components": entries,
            }
        ),
        encoding="utf-8",
    )
    (directory / "library.yaml").write_text("modelRoots: []\n", encoding="utf-8")
    # Point discovery at this harness's agent, never a real provider. No inference runs.
    (directory / "inference-driver.yaml").write_text(
        yaml.safe_dump(
            {
                "provider": "custom",
                "baseUrl": url("agent"),
                "modelId": "acceptance-only",
            }
        ),
        encoding="utf-8",
    )
    (directory / "gateway.yaml").write_text("{}\n", encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("EUGENE_PLEXUS_")
    }
    env["PYTHONUNBUFFERED"] = "1"
    processes = {}
    logs = {}

    def start(kind: str) -> None:
        (directory / f"{kind}.stop").unlink(missing_ok=True)
        logs[kind] = (directory / f"{kind}.log").open("a", encoding="utf-8")
        processes[kind] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                kind,
                "--directory",
                str(directory),
            ],
            cwd=directory,
            env=env,
            stdout=logs[kind],
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def stop(kind: str) -> None:
        proc = processes.pop(kind)
        (directory / f"{kind}.stop").touch()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                proc.kill()
            proc.wait(timeout=10)
            raise AssertionError(f"{kind} did not shut down its owned processes")
        finally:
            logs.pop(kind).close()

    with httpx.Client(trust_env=False, timeout=20) as client:

        def call(kind, method, path, token=None, **kwargs):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            return client.request(method, url(kind) + path, headers=headers, **kwargs)

        def wait_for(check, label):
            deadline = time.perf_counter() + 45
            while time.perf_counter() < deadline:
                try:
                    if check():
                        return
                except httpx.HTTPError:
                    pass
                if any(proc.poll() is not None for proc in processes.values()):
                    raise AssertionError(f"server exited while waiting for {label}")
                time.sleep(0.2)
            raise AssertionError(f"timed out waiting for {label}")

        def login(kind):
            response = call(
                kind, "POST", "/v1/auth/login", json={"passphrase": passphrase}
            )
            assert response.status_code == 200, f"{kind} login failed"
            return response.json()["sessionToken"]

        def all_children_accept(token):
            return all(
                call(kind, "GET", "/v1/config", token).status_code == 200
                for kind in ("gateway", "library", "inference-driver")
            )

        try:
            start("control")
            wait_for(
                lambda: call("control", "GET", "/healthz").status_code == 200, "root"
            )
            old_token = login("control")
            assert jwt.get_unverified_header(old_token)["alg"] == "HS256"
            start("agent")
            wait_for(
                lambda: call("agent", "GET", "/healthz").status_code == 200, "agent"
            )
            assert (
                call(
                    "agent",
                    "POST",
                    "/v1/auth/initialize",
                    json={"passphrase": passphrase},
                ).status_code
                == 200
            )
            agent_token = login("agent")
            join = call("control", "POST", "/v1/nodes/join-token", old_token).json()[
                "token"
            ]
            response = call(
                "agent",
                "POST",
                "/v1/node/enroll",
                agent_token,
                json={"controlUrl": url("control"), "token": join, "name": "r7-node"},
            )
            assert response.status_code == 200, "legacy enrollment failed"
            wait_for(lambda: all_children_accept(old_token), "legacy children")
            before = yaml.safe_load(
                (directory / "node.yaml").read_text(encoding="utf-8")
            )
            assert len(base64.b64decode(before["signingKey"])) == 32
            print(
                "PASS existing HS256 enrollment and all three live verifier children",
                flush=True,
            )

            saved_secret = secrets.token_urlsafe(24)
            result = call(
                "inference-driver",
                "PATCH",
                "/v1/config",
                old_token,
                json={"apiKey": saved_secret},
            ).json()
            assert result["rejected"] == [], "driver secret was not saved"
            sealed_before = yaml.safe_load(
                (directory / "inference-driver.yaml").read_text(encoding="utf-8")
            )["apiKey"]
            assert isinstance(sealed_before, dict), "driver secret was not encrypted"

            assert (
                call("control", "POST", "/v1/control/rotate-key", old_token).status_code
                == 202
            )
            new_token = login("control")
            assert jwt.get_unverified_header(new_token)["alg"] == "EdDSA"
            wait_for(
                lambda: (
                    call("control", "GET", "/v1/control/rotate-key", new_token)
                    .json()
                    .get("state")
                    == "done"
                ),
                "signed rotation",
            )
            wait_for(lambda: all_children_accept(new_token), "Ed25519 children")
            after = yaml.safe_load(
                (directory / "node.yaml").read_text(encoding="utf-8")
            )
            for field in ("name", "privateKey", "controlPublicKey", "enrolledAt"):
                assert after[field] == before[field], f"rotation changed {field}"
            assert after["signingKeyId"] != before["signingKeyId"]
            private = base64.b64decode(after["signingKey"])
            public = security.verification_key(private)
            assert public.startswith(b"-----BEGIN PUBLIC KEY-----")
            for kind in PORTS:
                assert call(kind, "GET", "/v1/config", old_token).status_code == 401, (
                    f"{kind} accepted the old token"
                )
            print(
                "PASS signed live rotation preserves node enrollment and invalidates old tokens everywhere",
                flush=True,
            )

            # Exercise the compromised verifier's available signing material.
            for entry in entries[:3]:
                plan = _ComponentPlanner(
                    ComponentEntry.model_validate(entry),
                    logging.getLogger("r7"),
                    AuthState(signing_key=private),
                ).plan()
                assert plan is not None
                assert base64.b64encode(private).decode() not in plan.env.values()
                assert base64.b64encode(public).decode() in plan.env.values()
            try:
                security.issue_operator_token(signing_key=public)
            except ValueError:
                pass
            else:
                raise AssertionError("a verifier public key minted an operator session")
            raw_public = serialization.load_pem_public_key(public).public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            now = int(time.time())
            forged = jwt.encode(
                {"sub": "operator", "aud": "operator", "iat": now, "exp": now + 60},
                raw_public,
                algorithm="HS256",
            )
            for kind in PORTS:
                assert call(kind, "GET", "/v1/config", forged).status_code == 401, (
                    f"{kind} accepted algorithm confusion"
                )
            print(
                "PASS verifier public material cannot mint or forge operator access",
                flush=True,
            )

            assert (
                yaml.safe_load(
                    (directory / "inference-driver.yaml").read_text(encoding="utf-8")
                )["apiKey"]
                == sealed_before
            )
            agent_state = yaml.safe_load(
                (directory / "agent.yaml").read_text(encoding="utf-8")
            )
            master = security.derive_master_key(
                passphrase, base64.b64decode(agent_state["auth"]["masterSalt"])
            )
            assert (
                security.open_envelope(
                    security.Envelope.from_dict(sealed_before), master
                )
                == saved_secret
            )
            print(
                "PASS signing-key rotation preserves the separately encrypted backend credential",
                flush=True,
            )

            stop("agent")
            stop("control")
            start("control")
            wait_for(
                lambda: call("control", "GET", "/healthz").status_code == 200,
                "restarted root",
            )
            restarted_token = login("control")
            assert jwt.get_unverified_header(restarted_token)["alg"] == "EdDSA"
            assert (
                security.decode_token(token=restarted_token, signing_key=public).aud
                == "operator"
            )
            start("agent")
            wait_for(
                lambda: call("agent", "GET", "/healthz").status_code == 200,
                "restarted agent",
            )
            login("agent")  # restores its separate master key and restarts children
            wait_for(
                lambda: all_children_accept(restarted_token),
                "restarted verifier children",
            )
            assert (
                yaml.safe_load((directory / "node.yaml").read_text(encoding="utf-8"))[
                    "signingKey"
                ]
                == after["signingKey"]
            )
            print(
                "PASS root, agent, and all verifier children restart without re-enrollment or re-key",
                flush=True,
            )
        except BaseException:
            for kind, handle in logs.items():
                handle.flush()
                print(
                    f"{kind} log tail:\n"
                    + "\n".join(
                        (directory / f"{kind}.log")
                        .read_text(encoding="utf-8", errors="replace")
                        .splitlines()[-35:]
                    ),
                    file=sys.stderr,
                )
            raise
        finally:
            for kind in ("agent", "control"):
                if kind in processes:
                    stop(kind)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", choices=("agent", "control"))
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.serve:
        assert args.directory is not None
        serve(args.serve, args.directory)
    else:
        with tempfile.TemporaryDirectory(prefix="ep-r7-rotation-") as directory:
            exercise(Path(directory))


if __name__ == "__main__":
    main()
