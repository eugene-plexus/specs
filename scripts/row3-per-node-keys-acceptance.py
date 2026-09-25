"""Row 3 acceptance: a leaked key costs one machine, not the install.

Real processes on ephemeral loopback ports with temporary state: one
control root, two enrolled agents (`agent-a` joined with the `gateway`
grant, the way the wizard joins the control host; `agent-b` a worker
joined from `/nodes` with none), and a gateway and a library on
`agent-a`'s machine, started with exactly the environment `agent-a`
hands a child. No model, no engine, no installed service.

Then it steals `agent-b`'s token key out of its `node.yaml` -- what a
compromised worker gives an attacker -- and tries every token that key
can sign against every other process. It records what the key still
buys (the two remote reads D5 allows a member's agent) and asserts it
buys nothing else; then revokes `agent-b` at the root and asserts even
that ends, everywhere, without a restart.

Run with a Python that has agent, control, gateway and library
installed (CI's cross-component job has all five).
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
from pathlib import Path
from typing import Any

import httpx
import yaml

PASSES: list[str] = []


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {message}", flush=True)


# --------------------------------------------------------------------------- #
# The processes
# --------------------------------------------------------------------------- #


def serve(kind: str, directory: Path, port: int, host: str) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app as control_app
        from eugene_plexus_control.settings import Settings as ControlSettings

        app = control_app(
            ControlSettings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    elif kind.startswith("agent"):
        from eugene_plexus_agent.app import create_app as agent_app
        from eugene_plexus_agent.settings import Settings as AgentSettings

        app = agent_app(
            settings=AgentSettings(
                config_file=directory / "agent.yaml", default_topology=False, bind_port=port
            )
        )
    elif kind.startswith("gateway"):
        from eugene_plexus_gateway.app import create_app as gateway_app
        from eugene_plexus_gateway.settings import Settings as GatewaySettings

        child = json.loads((directory / "child.json").read_text(encoding="utf-8"))
        app = gateway_app(
            settings=GatewaySettings(
                config_file=directory / "gateway.yaml",
                metrics_file=directory / "metrics.sqlite3",
                **child,
            )
        )
    elif kind.startswith("library"):
        from eugene_plexus_library.app import create_app as library_app
        from eugene_plexus_library.settings import Settings as LibrarySettings

        child = json.loads((directory / "child.json").read_text(encoding="utf-8"))
        app = library_app(
            settings=LibrarySettings(
                config_file=directory / "library.yaml",
                state_file=directory / "library-state.json",
                **child,
            )
        )
    else:
        raise SystemExit(f"unknown kind {kind}")
    uvicorn.run(app, host=host, port=port, log_level="error", access_log=False)


def child_environment(agent_dir: Path, kind: str, agent_url: str) -> dict[str, Any]:
    """What `agent_dir`'s agent hands a child of `kind` at spawn."""
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    store = NodeIdentityStore(agent_dir / "node.yaml")
    store.load()
    trust = NodeTrust(store, agent_dir / BUNDLE_FILE)
    trust.load()
    token, _ = trust.mint_service(sub=kind, audience=trust.recipient)
    env: dict[str, Any] = {
        "trust_bundle_file": str(trust.bundle_path),
        "trust_authority": trust.authority,
        "auth_recipient": trust.recipient,
        "service_token": token,
    }
    if kind == "gateway":
        env["agent_url"] = agent_url
    return env


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def exercise(directory: Path, lan: str | None) -> None:
    from eugene_plexus_agent import tokens

    names = ("control", "agent-a", "agent-b", "gateway-a", "library-a")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets, strict=True)}
    for sock in sockets:
        sock.close()
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs: list[Any] = []
    client = httpx.Client(timeout=15, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def advertised(name: str) -> str:
        return f"http://{lan}:{ports[name]}" if lan else url(name)

    def call(name: str, method: str, path: str, token: str | None = None, **kw: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, url(name) + path, headers=headers, **kw)

    def code(name: str, method: str, path: str, token: str | None = None, **kw: Any) -> int:
        return call(name, method, path, token, **kw).status_code

    def wait(check: Any, label: str, seconds: float = 20) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise AssertionError("timed out: " + label)

    def start(name: str) -> None:
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes[name] = subprocess.Popen(
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
                "0.0.0.0" if lan and name.startswith("agent") else "127.0.0.1",
            ],
            cwd=work,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: code(name, "GET", "/healthz") == 200, f"{name} healthy")

    def login(name: str) -> str:
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        assert response.status_code == 200, (name, response.text)
        return str(response.json()["sessionToken"])

    def claims_of(token: str) -> dict[str, Any]:
        import jwt

        return dict(jwt.decode(token, options={"verify_signature": False}))

    def bundle_version(name: str) -> int:
        kept = json.loads((directory / name / "trust_bundle.json").read_text(encoding="utf-8"))
        payload = claims_of(kept["jws"])
        return int(payload["version"])

    try:
        # ---------------------------------------------------------------- #
        # An install: a root, the control host's agent, a worker
        # ---------------------------------------------------------------- #
        start("control")
        assert code("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}) == 204
        root_session = login("control")
        assert claims_of(root_session)["aud"] == ["control"]

        for name, grants in (("agent-a", ["gateway"]), ("agent-b", [])):
            work = directory / name
            work.mkdir(exist_ok=True)
            (work / "agent.yaml").write_text(
                yaml.safe_dump(
                    {
                        "firstRunComplete": True,
                        "advertiseUrl": advertised(name),
                        "securityMode": "prompt_on_startup",
                        "components": [],
                    }
                ),
                encoding="utf-8",
            )
            start(name)
            initialized = call(name, "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
            assert initialized.status_code == 200, initialized.text
            standalone = initialized.json()["sessionToken"]
            assert claims_of(standalone)["aud"] == ["node:local"]
            join = call(
                "control", "POST", "/v1/nodes/join-token", root_session, json={"grants": grants}
            )
            assert join.status_code in (200, 201), join.text
            enrolled = call(
                name,
                "POST",
                "/v1/node/enroll",
                standalone,
                json={"controlUrl": url("control"), "token": join.json()["token"], "name": name},
            )
            assert enrolled.status_code == 200, enrolled.text
        ok("two agents enrolled; agent-a with the gateway grant, agent-b with none")

        for name in ("agent-a", "agent-b"):
            identity = yaml.safe_load((directory / name / "node.yaml").read_text(encoding="utf-8"))
            assert identity.get("tokenPrivateKey"), name
            for gone in ("signingKey", "signingKeyId"):
                assert gone not in identity, (name, gone)
        ok("no node.yaml holds an install signing key; each holds only its own token key")

        for kind in ("gateway", "library"):
            work = directory / f"{kind}-a"
            work.mkdir(exist_ok=True)
            env = child_environment(directory / "agent-a", kind, url("agent-a"))
            (work / "child.json").write_text(json.dumps(env), encoding="utf-8")
            start(f"{kind}-a")
            assert "PRIVATE KEY" not in json.dumps(env) and "tokenPrivateKey" not in json.dumps(env)
        ok("a gateway and a library on agent-a's machine, given a bundle path and a token, no key")

        # ---------------------------------------------------------------- #
        # The paths that must work
        # ---------------------------------------------------------------- #
        session_a = login("agent-a")
        session_b = login("agent-b")
        assert claims_of(session_a)["aud"] == ["node:agent-a", "control"]
        assert claims_of(session_b)["aud"] == ["node:agent-b", "control"]
        ok("a sign-in on each agent comes back from the root, addressed to that machine and it")

        for name, path in (
            ("agent-a", "/v1/node"),
            ("gateway-a", "/v1/config"),
            ("library-a", "/v1/models"),
            ("control", "/v1/nodes"),
        ):
            assert code(name, "GET", path, session_a) == 200, (name, path)
        ok("agent-a's session opens agent-a, its gateway, its library and the root")

        for name, path in (
            ("agent-a", "/v1/node"),
            ("gateway-a", "/v1/config"),
            ("library-a", "/v1/models"),
        ):
            assert code(name, "GET", path, session_b) == 401, (name, path)
        assert code("agent-b", "GET", "/v1/node", session_b) == 200
        ok("agent-b's session is refused on agent-a's machine when presented there directly")

        # The exchange agent-b's console performs for a hop to agent-a (RFC
        # 8693), made here the way that agent makes it: its own agent token
        # as the actor, the operator's session as the subject.
        actor_b = child_environment(directory / "agent-b", "agent", url("agent-b"))
        from eugene_plexus_agent.node_identity import NodeIdentityStore
        from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

        store_b = NodeIdentityStore(directory / "agent-b" / "node.yaml")
        store_b.load()
        trust_b = NodeTrust(store_b, directory / "agent-b" / BUNDLE_FILE)
        trust_b.load()
        assert actor_b["auth_recipient"] == "node:agent-b"
        exchanged = call(
            "control",
            "POST",
            "/v1/auth/token",
            trust_b.agent_token("control"),
            json={"subjectToken": session_b, "audience": "node:agent-a"},
        )
        assert exchanged.status_code == 200, exchanged.text
        for_a = str(exchanged.json()["accessToken"])
        payload = claims_of(for_a)
        assert payload["aud"] == ["node:agent-a"] and payload["exp"] - payload["iat"] <= 600
        assert code("agent-a", "GET", "/v1/node", for_a) == 200
        assert code("gateway-a", "GET", "/v1/config", for_a) == 200
        ok("agent-b's session, exchanged at the root, opens agent-a for five minutes and no longer")
        someone_elses = call(
            "control",
            "POST",
            "/v1/auth/token",
            trust_b.agent_token("control"),
            json={"subjectToken": session_a, "audience": "node:agent-a"},
        )
        assert someone_elses.status_code in (401, 403), someone_elses.text
        ok("agent-b cannot exchange a session that was not signed in on agent-b")

        if lan:
            hop = call("agent-b", "GET", "/api/proxy/node:agent-a/v1/node", session_b)
            assert hop.status_code == 200, hop.text
            assert hop.json()["name"] == "agent-a"
            ok("through agent-b's console the same session reaches agent-a, exchanged at the root")
        else:
            print(
                "SKIP the browser hop through agent-b's proxy: it refuses a loopback advertise "
                "address by design; run with --lan to advertise a routable one",
                flush=True,
            )

        # ---------------------------------------------------------------- #
        # A stolen worker key, tried everywhere
        # ---------------------------------------------------------------- #
        identity_b = yaml.safe_load((directory / "agent-b" / "node.yaml").read_text(encoding="utf-8"))
        stolen = tokens.Signer(
            key=tokens.load_private(identity_b["tokenPrivateKey"]), issuer="node:agent-b"
        )

        def forge(typ: str, sub: str, aud: list[str], *, issuer: str | None = None) -> str:
            signer = stolen if issuer is None else tokens.Signer(key=stolen.key, issuer=issuer)
            token, _ = signer.mint(typ=typ, sub=sub, aud=aud, ttl_seconds=300)
            return token

        a = ["node:agent-a"]
        refused: list[tuple[str, str, str, str, str]] = [
            # (label, target, method, path, token)
            ("an operator session for agent-a", "agent-a", "GET", "/v1/node",
             forge(tokens.TYP_SESSION, "operator", a)),
            ("an operator session for the gateway's machine", "gateway-a", "GET", "/v1/config",
             forge(tokens.TYP_SESSION, "operator", a)),
            ("an operator session for the root", "control", "GET", "/v1/nodes",
             forge(tokens.TYP_SESSION, "operator", ["control"])),
            ("a client key", "gateway-a", "GET", "/v1/models",
             forge(tokens.TYP_CLIENT, "app", ["gateway"])),
            ("a gateway token without the grant", "agent-a", "GET", "/v1/runtimes",
             forge(tokens.TYP_SERVICE, "gateway", a)),
            ("a gateway token at the front door", "gateway-a", "GET", "/v1/models",
             forge(tokens.TYP_SERVICE, "gateway", a)),
            ("an agent token reading agent-a", "agent-a", "GET", "/v1/runtimes",
             forge(tokens.TYP_SERVICE, "agent", a)),
            ("a library token", "library-a", "GET", "/v1/models",
             forge(tokens.TYP_SERVICE, "library", a)),
            ("a control token declaring a runtime", "agent-a", "POST", "/v1/runtimes",
             forge(tokens.TYP_SERVICE, "control", a)),
            ("agent-b's key claiming to be agent-a", "agent-a", "GET", "/v1/runtimes",
             forge(tokens.TYP_SERVICE, "gateway", a, issuer="node:agent-a")),
            ("agent-b's key claiming to be the root", "agent-a", "POST", "/v1/runtimes",
             forge(tokens.TYP_SERVICE, "control", a, issuer="control")),
            ("an agent token writing the root's registry", "control", "POST", "/v1/nodes/join-token",
             forge(tokens.TYP_SERVICE, "agent", ["control"])),
        ]
        spec = {"name": "x", "engine": "llama_cpp", "modelPath": "/m.gguf", "autoStart": False}
        for label, target, method, path, token in refused:
            kwargs: dict[str, Any] = {"json": spec} if path == "/v1/runtimes" and method == "POST" else {}
            if path == "/v1/nodes/join-token":
                kwargs = {"json": {}}
            status = code(target, method, path, token, **kwargs)
            assert status == 401, (label, target, path, status)
            ok(f"stolen worker key: {label} is refused ({target} {method} {path})")

        # What the key still buys, by design (D5): a member's agent reads the
        # library and the root. Asserted, so the residue is a fact, not a hope.
        agent_to_library = forge(tokens.TYP_SERVICE, "agent", a)
        agent_to_root = forge(tokens.TYP_SERVICE, "agent", ["control"])
        assert code("library-a", "GET", "/v1/models", agent_to_library) == 200
        assert code("control", "GET", "/v1/nodes", agent_to_root) == 200
        ok("what it still buys, by design: library reads and root reads as agent-b's agent")

        # ---------------------------------------------------------------- #
        # Revoke the worker: the residue ends everywhere, with no restart
        # ---------------------------------------------------------------- #
        before = bundle_version("agent-a")
        revoked = call("control", "DELETE", "/v1/nodes/agent-b", root_session)
        assert revoked.status_code in (200, 202), revoked.text
        wait(lambda: bundle_version("agent-a") > before, "agent-a took the revocation bundle")
        ok("revoking agent-b at the root reached agent-a as a new bundle")

        wait(
            lambda: code("library-a", "GET", "/v1/models", forge(tokens.TYP_SERVICE, "agent", a)) == 401,
            "library refuses the revoked key",
        )
        assert code("control", "GET", "/v1/nodes", forge(tokens.TYP_SERVICE, "agent", ["control"])) == 401
        ok("after revocation agent-b's key buys nothing: library and root refuse it")
        for name in ("control", "agent-a", "gateway-a", "library-a"):
            assert processes[name].poll() is None, f"{name} restarted or exited"
        ok("nothing restarted: the library and gateway reloaded the bundle file")

        # ---------------------------------------------------------------- #
        # A sign-out is the install's
        # ---------------------------------------------------------------- #
        signed_out = call("agent-a", "DELETE", "/v1/auth/sessions/current", session_a)
        assert signed_out.status_code == 204, signed_out.text
        wait(lambda: code("library-a", "GET", "/v1/models", session_a) == 401, "library refuses")
        for name, path in (("agent-a", "/v1/node"), ("gateway-a", "/v1/config"), ("control", "/v1/nodes")):
            assert code(name, "GET", path, session_a) == 401, (name, path)
        ok("a sign-out on agent-a ends that session on the root, agent-a, its gateway and library")
        fresh = login("agent-a")
        assert code("gateway-a", "GET", "/v1/config", fresh) == 200
        ok("signing in again works")
    finally:
        for process in processes.values():
            process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()
        client.close()


def _routable_address() -> str:
    """The address this host would use to reach another; no packet is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    finally:
        probe.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="advertise this host's routable address, so the browser hop runs too "
        "(the agents then bind every interface)",
    )
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port, args.host)
        return 0
    with tempfile.TemporaryDirectory(prefix="ep-row3-", ignore_cleanup_errors=True) as tmp:
        directory = Path(tmp)
        try:
            exercise(directory, _routable_address() if args.lan else None)
        except BaseException:
            for log in sorted(directory.glob("*/process.log")):
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                print(f"--- {log.parent.name} ---", *tail, sep="\n")
            raise
    print(f"{len(PASSES)} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
