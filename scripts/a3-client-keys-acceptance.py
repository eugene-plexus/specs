"""A3 isolated process acceptance: one real root, two agents and two gateways.

Uses ephemeral loopback ports and temporary state, no models or installed services.
Run with Python containing editable installs of agent, control and gateway.

Per-node token keys (2026-09-25, `docs/design/per-node-token-keys.md`). Both
agents enroll with join tokens carrying the `gateway` grant, because each runs
a gateway. The gateways are started by this script rather than supervised, so
each is handed exactly what its agent's supervisor would: that node's trust
bundle file, the root's identity key as the authority, `node:<agent>` as the
recipient, and a token minted by that agent's own `NodeTrust` from its
`node.yaml`, addressed to that machine alone. Operator calls to an agent or a
gateway use a session from that machine's own agent login (the root mints it
for `node:<agent>` and `control`); the root's own session is used only at the
root. Only the root can sign a client key, so the expired and unregistered
credentials the last check needs are signed with the root's token key, which
this script opens from the operator-only snapshot with the passphrase it chose.

Removed: legacy client keys signed by the shared install key no longer exist,
so the signed legacy migration check is gone; a key minted before the gateways
start (still accepted) and one revoked before they start (refused from the
first policy) take the two legacy keys' places as the steady baseline.
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

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
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


def node_trust(agent_dir: Path):
    """This node's `NodeTrust`, read from its `node.yaml` and kept bundle."""
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    store = NodeIdentityStore(agent_dir / "node.yaml")
    store.load()
    trust = NodeTrust(store, agent_dir / "trust_bundle.json")
    trust.load()
    assert trust.enrolled and trust.bundle is not None, (
        f"{agent_dir.name} is not enrolled or kept no trust bundle"
    )
    return trust


def gateway_bootstrap(agent_dir: Path, agent_url: str) -> dict:
    """What the agent's supervisor hands a gateway it spawns: no key of any kind.

    The bundle file, the authority it must be signed by, this machine as the
    recipient, and a token addressed to this machine alone. Asserts that none
    of the node's private keys is in it and that the token is worthless on any
    other machine.
    """
    from eugene_plexus_agent import tokens

    trust = node_trust(agent_dir)
    token, _ = trust.mint_service(sub="gateway", audience=trust.recipient)
    bootstrap = {
        "agent_url": agent_url,
        "trust_bundle_file": str(trust.bundle_path),
        "trust_authority": trust.authority,
        "auth_recipient": trust.recipient,
        "service_token": token,
    }
    identity = yaml.safe_load((agent_dir / "node.yaml").read_text(encoding="utf-8"))
    assert "signingKey" not in identity and "signingKeyId" not in identity, sorted(identity)
    rendered = json.dumps(bootstrap)
    for field in ("privateKey", "signingPrivateKey", "tokenPrivateKey"):
        assert identity[field] not in rendered, f"{field} reached the gateway's bootstrap"
    tokens.load_public(bootstrap["trust_authority"])
    claims = tokens.verify(
        token, bundle=trust.bundle, recipient=trust.recipient, classes=(tokens.TYP_SERVICE,)
    )
    assert claims.aud == (trust.recipient,) and claims.iss == trust.recipient, claims
    return bootstrap


def root_signer(snapshot: dict, passphrase: str):
    """The root's token key, opened the way only the passphrase can open it."""
    from eugene_plexus_agent import tokens
    from eugene_plexus_control import security as control_security

    master = control_security.derive_master_key(
        passphrase, base64.b64decode(snapshot["salt"])
    )
    key = tokens.load_private(control_security.open_b64(snapshot["sealedSigningKey"], master))
    assert tokens.public_b64(key) == snapshot["rootTokenPublicKey"], "unsealed the wrong key"
    return tokens.Signer(key=key, issuer=tokens.ISSUER_CONTROL)


def exercise(directory: Path) -> None:
    for name in [k for k in os.environ if k.startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    from eugene_plexus_agent import tokens
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

    def mint(agent, name):
        response = call(
            agent, "POST", "/v1/auth/client-keys", sessions[agent], json={"name": name}
        )
        assert response.status_code == 201, response.text
        return response.json()

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
        # Addressed to the root alone: good at the root, refused by every node.
        root_session = login("control")
        sessions = {}
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
            # Standalone until it enrolls: this session is the agent's own.
            standalone = login(name)
            join = call(
                "control",
                "POST",
                "/v1/nodes/join-token",
                root_session,
                json={"grants": ["gateway"]},
            )
            assert join.status_code == 201, join.text
            enrolled = call(
                name,
                "POST",
                "/v1/node/enroll",
                standalone,
                json={"controlUrl": url("control"), "token": join.json()["token"], "name": name},
            )
            assert enrolled.status_code == 200, enrolled.text
            # Signed in through the enrolled agent: the root mints it for
            # this machine and itself, so it opens this agent, this node's
            # gateway, and whatever the agent forwards to the root.
            sessions[name] = login(name)

        steady = mint("agent-b", "steady")
        early = mint("agent-a", "revoked-early")
        assert (
            call(
                "agent-a",
                "DELETE",
                "/v1/auth/client-keys/" + early["key"]["id"],
                sessions["agent-a"],
            ).status_code
            == 204
        )

        for gateway, agent in (("gateway-a", "agent-a"), ("gateway-b", "agent-b")):
            work = directory / gateway
            work.mkdir()
            (work / "bootstrap.json").write_text(
                json.dumps(gateway_bootstrap(directory / agent, url(agent))),
                encoding="utf-8",
            )
            start(gateway)
        key = mint("agent-a", "cross-node")
        for gateway in ("gateway-a", "gateway-b"):
            wait(lambda: status(gateway, key["token"]) == 200, "new key registered")
            assert status(gateway, steady["token"]) == 200
            assert status(gateway, early["token"]) == 401
        revoked_at = time.perf_counter()
        assert (
            call(
                "agent-b",
                "DELETE",
                "/v1/auth/client-keys/" + key["key"]["id"],
                sessions["agent-b"],
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
            lambda: status("gateway-a", steady["token"]) == 503,
            "local-agent cache expires",
            6,
        )
        assert call("gateway-a", "GET", "/v1/config", sessions["agent-a"]).status_code == 200
        # The repair needs this machine's session: another console's is not addressed here.
        assert call("gateway-a", "GET", "/v1/config", sessions["agent-b"]).status_code == 401
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
                pool.map(lambda _: status("gateway-a", steady["token"]), range(24))
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
            lambda: status("gateway-a", steady["token"]) == 200,
            "agent recovery",
        )

        stop("control")
        wait(
            lambda: all(
                status(g, steady["token"]) == 503 for g in ("gateway-a", "gateway-b")
            ),
            "control outage policy expires",
            6,
        )
        for gateway in ("gateway-a", "gateway-b"):
            assert status(gateway, key["token"]) == 401
            stop(gateway)
            start(gateway)
            assert status(gateway, steady["token"]) == 503
            assert status(gateway, key["token"]) == 401
        print(
            "PASS control outage and stale persisted-cache restarts fail closed at both gateways",
            flush=True,
        )
        start("control")
        root_session = login("control")
        wait(
            lambda: all(
                status(g, steady["token"]) == 200 for g in ("gateway-a", "gateway-b")
            ),
            "control recovery",
        )
        snapshot = call("control", "GET", "/v1/control/snapshot", root_session)
        assert snapshot.status_code == 200, snapshot.text
        root = root_signer(snapshot.json(), passphrase)
        for agent in ("agent-a", "agent-b"):
            trust = node_trust(directory / agent)
            entry = trust.bundle.keys.get(root.kid)
            assert entry is not None and entry.issuer == "control", "root key not in bundle"
            assert tokens.GRANT_AUTHORITY in entry.grants and trust.signer().kid != root.kid
            # Signed by this node's own key, under a registered id: the grant
            # refuses it, so a leaked node.yaml cannot mint a client key.
            forged, _ = trust.signer().mint(
                typ=tokens.TYP_CLIENT,
                sub="forged",
                aud=[tokens.RECIPIENT_GATEWAY],
                ttl_seconds=3600,
                jti=steady["key"]["id"],
            )
            for gateway in ("gateway-a", "gateway-b"):
                refused = call(gateway, "GET", "/v1/models", forged)
                assert refused.status_code == 401, refused.text
                assert "may not issue" in refused.text, refused.text
        for gateway in ("gateway-a", "gateway-b"):
            assert status(gateway, key["token"]) == 401
            assert status(gateway, steady["token"]) == 200
            expired, _ = root.mint(
                typ=tokens.TYP_CLIENT,
                sub="expired",
                aud=[tokens.RECIPIENT_GATEWAY],
                now=int(time.time()) - 4000,
                ttl_seconds=1,
                jti="expired",
            )
            assert status(gateway, expired) == 401
            assert status(gateway, "invalid") == 401
            # Signed by the authority but never registered: what a key minted
            # into a log tail a forced promotion discarded would look like.
            unknown, _ = root.mint(
                typ=tokens.TYP_CLIENT,
                sub="unknown",
                aud=[tokens.RECIPIENT_GATEWAY],
                ttl_seconds=3600,
                jti="unregistered",
            )
            unregistered = call(gateway, "GET", "/v1/models", unknown)
            assert unregistered.status_code == 401, unregistered.text
            assert "not registered" in unregistered.text.lower(), unregistered.text
        print(
            "PASS recovery keeps revocations; invalid, expired, unregistered and node-forged credentials are refused",
            flush=True,
        )
        print(
            "PASS default bounds 15s refresh / 4s timeout / 60s age; gateway bootstrap holds no key, only a token for its own machine",
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
