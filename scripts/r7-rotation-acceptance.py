"""Live rotation of the control root's token key, under per-node token keys.

`POST /v1/control/rotate-key` replaces only the control root's own token
key and publishes a trust bundle naming the new one
(`docs/design/per-node-token-keys.md`, D10). Every session and client key
the old key signed must stop verifying on every machine; every node's own
token key, and everything it signed, must not change at all.

Real processes, all from the installed packages: a control root and two
agents enrolled with it. Node A supervises a gateway, a library and an
inference-driver (the agent hands them the bundle, authority and recipient
itself); node B supervises nothing. Temporary state only, loopback ports the
OS picks at start (never a default port), and no `EUGENE_PLEXUS_*` variable
from the calling shell reaches any process. No model, backend or keyring.

Checks, in order:

1.  Both nodes enroll with their own token keys; a session each node's
    login got from the root works on that node, its children and the root,
    and not on the other node.
2.  A service token signed with a node's own key (A's for its own machine,
    B's `agent` token for the root) works, and a client key minted before
    rotation opens A's gateway.
3.  After rotation, with both nodes up: every session and the client key
    minted before it is refused by the root, both agents and all three of
    A's children (a bounded wait covers the push and, failing that, the
    agent's pull interval). The bundle each node keeps advanced to the
    rotation's version, it names a new root key and the same two node keys,
    and `node.yaml` on each node is byte-for-byte what it was.
4.  The node-signed service tokens minted before rotation still verify;
    signing in again works everywhere, and a new client key opens the
    gateway.
5.  The driver's sealed backend credential is untouched by rotation.
6.  No child's environment holds any of its node's private keys, and an
    HS256 token keyed on the root's public key, with a real session's
    header and claims, is refused by every process.
7.  A node stopped during a second rotation missed the push (its kept
    bundle still names the old key), and when it starts again it pulls the
    new bundle within its pull interval: the old session is refused, a new
    one works, and its `node.yaml` is unchanged.
8.  The control root restarts sealed, and on sign-in comes back with the
    rotated key, so a session minted before the restart still verifies:
    rotation sealed and logged the key rather than holding it in memory.

Removed, because their premise no longer exists:

* The HS256 install and its migration to Ed25519 (`seed_legacy_root`):
  there is no shared install key left to seed or upgrade.
* `signingKey`/`signingKeyId` in `node.yaml` and their generation bump on
  rotation: a node holds no install key, so its `node.yaml` must not change.
* Polling `GET /v1/control/rotate-key` for progress: rotation has no
  per-node state any more, only a bundle version each node must reach.
* Children receiving the shared key's public half, and a public key failing
  to mint (`security.verification_key`, `issue_operator_token`): both
  functions are gone; check 6 asserts the stronger property that no private
  key reaches a child at all.
* Restarting without `/v1/node/rekey`: nothing is re-keyed now; check 7
  covers a node catching up by pulling the bundle instead.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import jwt
import yaml

NODE_A = "r7-a"
NODE_B = "r7-b"
CHILDREN = ("gateway", "library", "inference-driver")
PROCESSES = ("control", "agent-a", "agent-b")
PORT_NAMES = ("control", "agent-a", "agent-b", *CHILDREN)

# Drop the calling shell's install settings before anything reads them: this
# machine's live agent sets EUGENE_PLEXUS_AGENT_CONFIG_FILE at user scope, and
# every process below inherits this process's environment.
for _key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
    del os.environ[_key]


def serve(kind: str, directory: Path, port: int) -> None:
    """One control root or one agent, until `directory/stop` appears."""
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    else:
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml",
                bind_port=port,
                default_topology=False,
            )
        )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", access_log=False)
    )

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (directory / "stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task

    asyncio.run(run())


def free_ports() -> dict[str, int]:
    """Distinct loopback ports the OS says are free right now."""
    sockets = []
    try:
        for _ in PORT_NAMES:
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return {name: s.getsockname()[1] for name, s in zip(PORT_NAMES, sockets, strict=True)}
    finally:
        for sock in sockets:
            sock.close()


def header(token: str) -> dict:
    return jwt.get_unverified_header(token)


def claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def held_bundle(node_dir: Path):
    """The bundle a node keeps beside `node.yaml`, verified against its pinned root."""
    from eugene_plexus_agent import tokens

    pinned = read_yaml(node_dir / "node.yaml")["controlPublicKey"]
    document = json.loads((node_dir / "trust_bundle.json").read_text(encoding="utf-8"))
    return tokens.parse_bundle(str(document["jws"]), authority=pinned)


def node_trust(node_dir: Path):
    """The node's own signer, read from its files the way its agent reads them."""
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    store = NodeIdentityStore(node_dir / "node.yaml")
    store.load()
    trust = NodeTrust(store, node_dir / BUNDLE_FILE)
    trust.load()
    return trust


def exercise(root: Path) -> int:
    from eugene_plexus_agent import security, tokens
    from eugene_plexus_agent._generated.models import ComponentEntry
    from eugene_plexus_agent.app import TRUST_PULL_INTERVAL_SECONDS
    from eugene_plexus_agent.auth_state import AuthState
    from eugene_plexus_agent.supervisor import _ComponentPlanner

    ports = free_ports()
    dirs = {"control": root / "root", "agent-a": root / "a", "agent-b": root / "b"}
    for directory in dirs.values():
        directory.mkdir()
    dir_a, dir_b = dirs["agent-a"], dirs["agent-b"]
    passphrase = secrets.token_urlsafe(24)
    # Push is the fast path; the pull (at boot, then every interval) is the
    # one that cannot miss. Every wait for a bundle is bounded by the pull.
    bundle_bound = TRUST_PULL_INTERVAL_SECONDS + 20.0

    def base(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    child_entries = []
    for kind in CHILDREN:
        env: dict[str, str] = {}
        if kind == "gateway":
            env["EUGENE_PLEXUS_GATEWAY_METRICS_FILE"] = str(dir_a / "metrics.sqlite3")
            # Poll the client-key policy every second, so a key minted here is
            # admitted in a second or two rather than the default fifteen.
            env["EUGENE_PLEXUS_GATEWAY_CLIENT_KEY_REFRESH_SECONDS"] = "1"
        child_entries.append(
            {
                "name": kind,
                "kind": kind,
                "url": base(kind),
                "spawn": {"configFile": str(dir_a / f"{kind}.yaml"), "env": env},
            }
        )
    (dir_a / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "advertiseUrl": base("agent-a"),
                "securityMode": "prompt_on_startup",
                "components": [
                    *child_entries,
                    {"name": "control", "kind": "control", "url": base("control")},
                ],
            }
        ),
        encoding="utf-8",
    )
    (dir_a / "library.yaml").write_text("modelRoots: []\n", encoding="utf-8")
    # A real provider entry, so the driver builds its engine and `/v1/info`
    # answers; its backend is this harness's own agent, never a real provider,
    # and no inference runs.
    (dir_a / "inference-driver.yaml").write_text(
        yaml.safe_dump(
            {
                "provider": "openai_compat_custom",
                "baseUrl": base("agent-a"),
                "modelId": "acceptance-only",
            }
        ),
        encoding="utf-8",
    )
    (dir_a / "gateway.yaml").write_text("{}\n", encoding="utf-8")
    (dir_b / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "advertiseUrl": base("agent-b"),
                "securityMode": "prompt_on_startup",
                "components": [],
            }
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    processes: dict[str, subprocess.Popen] = {}
    logs: dict[str, object] = {}
    passed: list[str] = []

    def start(name: str) -> None:
        directory = dirs[name]
        (directory / "stop").unlink(missing_ok=True)
        logs[name] = (root / f"{name}.log").open("a", encoding="utf-8")
        processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                "control" if name == "control" else "agent",
                "--directory",
                str(directory),
                "--port",
                str(ports[name]),
            ],
            cwd=directory,
            env=env,
            stdout=logs[name],
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def stop(name: str) -> None:
        proc = processes.pop(name)
        (dirs[name] / "stop").touch()
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
            raise AssertionError(f"{name} did not shut down its owned processes") from None
        finally:
            logs.pop(name).close()

    def ok(message: str) -> None:
        passed.append(message)
        print(f"PASS {message}", flush=True)

    with httpx.Client(trust_env=False, timeout=20) as client:

        def call(name: str, method: str, path: str, token: str | None = None, **kwargs):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            return client.request(method, base(name) + path, headers=headers, **kwargs)

        def status(name: str, path: str, token: str) -> int:
            try:
                return call(name, "GET", path, token).status_code
            except httpx.HTTPError as exc:
                return -1 if not isinstance(exc, httpx.TimeoutException) else -2

        def wait_for(check, label: str, timeout: float = 45.0) -> float:
            """Poll `check` until it holds; returns the seconds it took."""
            started = time.perf_counter()
            deadline = started + timeout
            while time.perf_counter() < deadline:
                try:
                    if check():
                        return time.perf_counter() - started
                except httpx.HTTPError:
                    pass
                dead = [n for n, p in processes.items() if p.poll() is not None]
                if dead:
                    raise AssertionError(f"{dead} exited while waiting for {label}")
                time.sleep(0.2)
            raise AssertionError(f"timed out after {timeout:.0f} s waiting for {label}")

        def wait_statuses(
            label: str, checks: list[tuple[str, str, str]], want: int, timeout: float = 45.0
        ) -> float:
            """Every (process, path, token) answers `want`, within a bounded wait."""
            seen: dict[str, int] = {}

            def all_match() -> bool:
                seen.clear()
                for name, path, token in checks:
                    seen[f"{name} {path}"] = status(name, path, token)
                return all(code == want for code in seen.values())

            try:
                return wait_for(all_match, label, timeout)
            except AssertionError as exc:
                raise AssertionError(f"{exc}; last answers: {seen}") from None

        def healthy(name: str) -> None:
            wait_for(lambda: call(name, "GET", "/healthz").status_code == 200, f"{name} health")

        def login(name: str) -> str:
            response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
            assert response.status_code == 200, (
                f"{name} login: {response.status_code} {response.text}"
            )
            return response.json()["sessionToken"]

        def root_bundle():
            response = call("control", "GET", "/v1/trust/bundle")
            assert response.status_code == 200, f"root bundle: {response.status_code}"
            pinned = read_yaml(dir_a / "node.yaml")["controlPublicKey"]
            return tokens.parse_bundle(response.json()["jws"], authority=pinned)

        def root_kid(bundle) -> str:
            owned = [k.kid for k in bundle.keys.values() if k.issuer == tokens.ISSUER_CONTROL]
            assert len(owned) == 1, f"the bundle names {len(owned)} root keys"
            return owned[0]

        def node_kids(bundle) -> dict[str, str]:
            return {k.issuer: k.kid for k in bundle.keys.values() if k.issuer.startswith("node:")}

        def session_surfaces(token: str, node: str) -> list[tuple[str, str, str]]:
            """Where a session a node's login got must work: the root, that node, its children."""
            names = ["control", node] + (list(CHILDREN) if node == "agent-a" else [])
            return [(name, "/v1/config", token) for name in names]

        def client_key(session: str, name: str) -> str:
            response = call("agent-a", "POST", "/v1/auth/client-keys", session, json={"name": name})
            assert response.status_code == 201, (
                f"client key: {response.status_code} {response.text}"
            )
            token = response.json()["token"]
            assert header(token)["typ"] == tokens.TYP_CLIENT
            assert claims(token)["iss"] == tokens.ISSUER_CONTROL
            return token

        def dump_logs() -> None:
            for name in PROCESSES:
                handle = logs.get(name)
                if handle is not None:
                    handle.flush()
                path = root / f"{name}.log"
                if path.exists():
                    tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                    print(f"{name} log tail:\n" + "\n".join(tail), file=sys.stderr)

        try:
            # ---- 1. a root and two enrolled nodes --------------------------------
            start("control")
            healthy("control")
            response = call(
                "control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
            )
            assert response.status_code == 204, f"root initialize: {response.status_code}"
            session_root = login("control")
            assert claims(session_root)["aud"] == [tokens.RECIPIENT_CONTROL]
            joins = {}
            for name, grants in (("agent-a", ["gateway"]), ("agent-b", None)):
                response = call(
                    "control",
                    "POST",
                    "/v1/nodes/join-token",
                    session_root,
                    json={"grants": grants} if grants else {},
                )
                assert response.status_code == 201, f"join token: {response.status_code}"
                joins[name] = response.json()["token"]

            for name, node in (("agent-a", NODE_A), ("agent-b", NODE_B)):
                start(name)
                healthy(name)
                response = call(
                    name, "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
                )
                assert response.status_code == 200, f"{name} initialize: {response.status_code}"
                standalone = response.json()["sessionToken"]
                assert claims(standalone)["aud"] == ["node:local"]
                response = call(
                    name,
                    "POST",
                    "/v1/node/enroll",
                    standalone,
                    json={"controlUrl": base("control"), "token": joins[name], "name": node},
                )
                assert response.status_code == 200, (
                    f"{name} enroll: {response.status_code} {response.text}"
                )

            session_a = login("agent-a")
            session_b = login("agent-b")
            for token, node in ((session_a, NODE_A), (session_b, NODE_B)):
                assert header(token)["typ"] == tokens.TYP_SESSION
                assert header(token)["alg"] == "EdDSA"
                assert claims(token)["iss"] == tokens.ISSUER_CONTROL
                assert claims(token)["aud"] == [f"node:{node}", tokens.RECIPIENT_CONTROL]
            old_kid = header(session_root)["kid"]
            assert header(session_a)["kid"] == header(session_b)["kid"] == old_kid
            wait_statuses(
                "the sessions to open their nodes",
                [
                    *session_surfaces(session_a, "agent-a"),
                    *session_surfaces(session_b, "agent-b"),
                    ("control", "/v1/config", session_root),
                ],
                200,
                timeout=60,
            )
            assert status("agent-a", "/v1/config", session_b) == 401, "A took B's session"
            assert status("agent-b", "/v1/config", session_a) == 401, "B took A's session"
            node_a_before = (dir_a / "node.yaml").read_bytes()
            node_b_before = (dir_b / "node.yaml").read_bytes()
            for node_dir in (dir_a, dir_b):
                record = read_yaml(node_dir / "node.yaml")
                assert record.get("tokenPrivateKey"), f"{node_dir.name} has no token key"
                assert "signingKey" not in record and "signingKeyId" not in record
            bundle_0 = root_bundle()
            assert root_kid(bundle_0) == old_kid
            nodes_0 = node_kids(bundle_0)
            assert set(nodes_0) == {f"node:{NODE_A}", f"node:{NODE_B}"}, nodes_0
            for node_dir in (dir_a, dir_b):
                # A took its first bundle at enrollment and B's enrollment by push.
                wait_for(
                    lambda d=node_dir: held_bundle(d).version == bundle_0.version,
                    f"{node_dir.name} to keep bundle {bundle_0.version}",
                    bundle_bound,
                )
            ok(
                "two nodes enroll with their own token keys; each node's root-minted session "
                "opens that node, its children and the root, and not the other node"
            )

            # ---- 2. node-signed tokens and a client key, before rotation ------------
            trust_a, trust_b = node_trust(dir_a), node_trust(dir_b)
            local_a, _ = trust_a.mint_service(sub="gateway", audience=trust_a.recipient)
            b_to_root = trust_b.agent_token(tokens.RECIPIENT_CONTROL)
            assert header(local_a)["kid"] == nodes_0[f"node:{NODE_A}"]
            assert header(b_to_root)["kid"] == nodes_0[f"node:{NODE_B}"]
            node_signed = [
                ("agent-a", "/v1/components", local_a),
                ("library", "/v1/models", local_a),
                ("inference-driver", "/v1/info", local_a),
                ("control", "/v1/nodes", b_to_root),
            ]
            wait_statuses("node-signed service tokens", node_signed, 200)
            key_before = client_key(session_a, "r7-before-rotation")
            wait_statuses(
                "the gateway to admit the client key", [("gateway", "/v1/models", key_before)], 200
            )
            ok(
                "service tokens signed by each node's own key and a root-minted client key "
                "are accepted before rotation"
            )

            saved_secret = secrets.token_urlsafe(24)
            response = call(
                "inference-driver", "PATCH", "/v1/config", session_a, json={"apiKey": saved_secret}
            )
            assert response.status_code == 200 and response.json()["rejected"] == [], response.text
            sealed_before = read_yaml(dir_a / "inference-driver.yaml")["apiKey"]
            assert isinstance(sealed_before, dict), "the driver secret was not encrypted"

            # ---- 3. rotate with both nodes up -----------------------------------
            response = call("control", "POST", "/v1/control/rotate-key", session_root)
            assert response.status_code == 202, f"rotate: {response.status_code} {response.text}"
            change = response.json()
            assert change["reason"] == "rotation", change
            version_1 = int(change["version"])
            assert version_1 > bundle_0.version, (version_1, bundle_0.version)
            bundle_1 = root_bundle()
            assert bundle_1.version == version_1
            new_kid = root_kid(bundle_1)
            assert new_kid != old_kid, "rotation kept the root key"
            assert old_kid not in bundle_1.keys, "the old root key is still trusted"
            assert node_kids(bundle_1) == nodes_0, "rotation changed a node's key in the bundle"

            refused = [
                *session_surfaces(session_a, "agent-a"),
                *session_surfaces(session_b, "agent-b"),
                ("control", "/v1/config", session_root),
                ("gateway", "/v1/models", key_before),
            ]
            took = wait_statuses(
                "every surface to refuse what the old key signed", refused, 401, bundle_bound
            )
            for node_dir in (dir_a, dir_b):
                wait_for(
                    lambda d=node_dir: held_bundle(d).version == version_1,
                    f"{node_dir.name} to keep bundle {version_1}",
                    bundle_bound,
                )
                assert new_kid in held_bundle(node_dir).keys
            assert (dir_a / "node.yaml").read_bytes() == node_a_before, (
                "rotation changed A's node.yaml"
            )
            assert (dir_b / "node.yaml").read_bytes() == node_b_before, (
                "rotation changed B's node.yaml"
            )
            ok(
                f"after rotation every old session and the old client key are refused by the "
                f"root, both nodes and A's three children ({took:.1f} s); each node keeps bundle "
                f"{version_1}, which names a new root key and the same node keys; node.yaml "
                "is unchanged on both"
            )

            # ---- 4. node keys untouched; signing in again works --------------------
            wait_statuses("node-signed tokens after rotation", node_signed, 200)
            session_root = login("control")
            session_a = login("agent-a")
            session_b = login("agent-b")
            for token in (session_root, session_a, session_b):
                assert header(token)["kid"] == new_kid, (
                    "a new session was not signed by the new key"
                )
            wait_statuses(
                "new sessions everywhere",
                [
                    *session_surfaces(session_a, "agent-a"),
                    *session_surfaces(session_b, "agent-b"),
                    ("control", "/v1/config", session_root),
                ],
                200,
            )
            key_after = client_key(session_a, "r7-after-rotation")
            wait_statuses(
                "the gateway to admit the new client key",
                [("gateway", "/v1/models", key_after)],
                200,
            )
            ok(
                "node-signed service tokens minted before rotation still verify; signing in "
                "again gives sessions that work everywhere, and a new client key opens the gateway"
            )

            # ---- 5. the node's at-rest secret -----------------------------------
            assert read_yaml(dir_a / "inference-driver.yaml")["apiKey"] == sealed_before
            master = security.derive_master_key(
                passphrase, base64.b64decode(read_yaml(dir_a / "agent.yaml")["auth"]["masterSalt"])
            )
            opened = security.open_envelope(security.Envelope.from_dict(sealed_before), master)
            assert opened == saved_secret, "the sealed driver credential no longer opens"
            ok("rotation leaves the driver's separately sealed backend credential untouched")

            # ---- 6. no private key reaches a child; algorithm confusion ------------
            record_a = read_yaml(dir_a / "node.yaml")
            private_values = [
                record_a[field] for field in ("tokenPrivateKey", "signingPrivateKey", "privateKey")
            ]
            trust_a = node_trust(dir_a)
            for entry in child_entries:
                plan = _ComponentPlanner(
                    ComponentEntry.model_validate(entry),
                    logging.getLogger("r7"),
                    AuthState(trust=trust_a),
                ).plan()
                assert plan is not None
                for value in plan.env.values():
                    for private in private_values:
                        assert private not in value, f"{entry['kind']} was handed a private key"
                authority = [v for k, v in plan.env.items() if k.endswith("_TRUST_AUTHORITY")]
                recipient = [v for k, v in plan.env.items() if k.endswith("_AUTH_RECIPIENT")]
                service = [v for k, v in plan.env.items() if k.endswith("_SERVICE_TOKEN")]
                assert authority == [record_a["controlPublicKey"]], entry["kind"]
                assert recipient == [f"node:{NODE_A}"], entry["kind"]
                verified = tokens.verify(
                    service[0],
                    bundle=trust_a.bundle,
                    recipient=trust_a.recipient,
                    classes=(tokens.TYP_SERVICE,),
                )
                assert verified.is_local_service(trust_a.recipient), entry["kind"]
            root_public = base64.b64decode(tokens.public_b64(bundle_1.keys[new_kid].public))
            forgeries = []
            for token, names in (
                (session_a, ["control", "agent-a", *CHILDREN]),
                (session_b, ["agent-b"]),
            ):
                forged = jwt.encode(
                    claims(token),
                    root_public,
                    algorithm="HS256",
                    headers={"typ": tokens.TYP_SESSION, "kid": new_kid},
                )
                forgeries += [(name, "/v1/config", forged) for name in names]
            codes = {f"{name} {path}": status(name, path, token) for name, path, token in forgeries}
            assert all(code == 401 for code in codes.values()), f"forgery accepted: {codes}"
            ok(
                "no child's environment holds a node private key, and an HS256 forgery keyed "
                "on the root's public key is refused by all six processes"
            )

            # ---- 7. a node that was down catches up by pulling ------------------------
            b_held = held_bundle(dir_b)
            assert b_held.version == version_1 and new_kid in b_held.keys
            stop("agent-b")
            response = call("control", "POST", "/v1/control/rotate-key", session_root)
            assert response.status_code == 202, f"second rotate: {response.status_code}"
            version_2 = int(response.json()["version"])
            assert version_2 > version_1
            bundle_2 = root_bundle()
            newest_kid = root_kid(bundle_2)
            assert newest_kid not in (new_kid, old_kid)
            wait_statuses(
                "A to take the second rotation",
                [("agent-a", "/v1/config", session_a), ("control", "/v1/config", session_a)],
                401,
                bundle_bound,
            )
            b_stale = held_bundle(dir_b)
            assert b_stale.version == version_1, "B's kept bundle moved while B was down"
            # So B, left alone, would still accept B's current session.
            assert header(session_b)["kid"] == new_kid
            assert new_kid in b_stale.keys, "B's kept bundle no longer names the key it missed"
            start("agent-b")
            healthy("agent-b")
            took = wait_for(
                lambda: (
                    held_bundle(dir_b).version == version_2
                    and status("agent-b", "/v1/config", session_b) == 401
                ),
                "B to pull the bundle it missed",
                bundle_bound,
            )
            session_b = login("agent-b")
            assert header(session_b)["kid"] == newest_kid
            wait_statuses("B's new session", session_surfaces(session_b, "agent-b"), 200)
            # A start announces this node's address, which claims the next
            # `advertiseSequence`; that counter is the one field a restart may move.
            before_b = yaml.safe_load(node_b_before)
            after_b = read_yaml(dir_b / "node.yaml")
            assert after_b["tokenPrivateKey"] == before_b["tokenPrivateKey"], (
                "B's token key changed"
            )
            assert after_b.get("advertiseSequence", 0) >= before_b.get("advertiseSequence", 0)
            for record in (before_b, after_b):
                record.pop("advertiseSequence", None)
            changed = sorted(
                k for k in before_b.keys() | after_b.keys() if before_b.get(k) != after_b.get(k)
            )
            assert not changed, f"B's node.yaml changed across rotation and restart: {changed}"
            ok(
                f"a node stopped during rotation kept the stale bundle {version_1} and, "
                f"restarted, pulled bundle {version_2} within {took:.1f} s (pull interval "
                f"{TRUST_PULL_INTERVAL_SECONDS:.0f} s): the old session is refused, a new one "
                "works, and its node.yaml keeps every key and field but its announcement counter"
            )

            # ---- 8. the rotated key survives a root restart ------------------------
            session_a = login("agent-a")
            assert header(session_a)["kid"] == newest_kid
            stop("control")
            start("control")
            healthy("control")
            locked = status("control", "/v1/config", session_a)
            assert locked == 503, f"a restarted root answered {locked} before sign-in, not 503"
            session_root = login("control")
            assert header(session_root)["kid"] == newest_kid, "the root came back with another key"
            assert root_kid(root_bundle()) == newest_kid
            wait_statuses(
                "sessions across the root restart",
                [
                    ("control", "/v1/config", session_a),
                    ("agent-a", "/v1/config", session_a),
                    ("control", "/v1/config", session_root),
                ],
                200,
            )
            ok(
                "the control root restarts sealed and, on sign-in, comes back with the rotated "
                "key: a session minted before the restart still verifies"
            )
        except BaseException:
            dump_logs()
            raise
        finally:
            for name in ("agent-a", "agent-b", "control"):
                if name in processes:
                    stop(name)
    return len(passed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", choices=("agent", "control"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        assert args.directory is not None and args.port is not None
        serve(args.serve, args.directory, args.port)
        return
    with tempfile.TemporaryDirectory(prefix="ep-r7-rotation-") as directory:
        count = exercise(Path(directory))
    print(f"{count}/{count} checks passed", flush=True)


if __name__ == "__main__":
    main()
