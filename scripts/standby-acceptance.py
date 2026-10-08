"""The warm standby, live: granted, following, revoked, and promoted.

`docs/design/warm-standby.md` (control#5), calls SB1-SB4. An owner makes one
machine the install's standby at the control root; that machine's agent
starts a standby control root, which follows the active one with its own
`sub: standby` token, and nothing else reads the replication surface.

Real processes from the installed packages: a control root, agent A on the
root's machine (its topology lists the root, so it reports `hostsControl`),
and agent B, the machine that becomes the standby. Temporary state only,
loopback ports the OS picks at start (never a default port, the standby's
included), and no `EUGENE_PLEXUS_*` variable from the calling shell reaches
any process. No model, backend, keyring or cloud service.

Checks, in order:

1.  Before any grant nothing follows: B runs no standby, and B's
    `sub: standby` token, B's and A's `agent` tokens are refused at the
    log and the snapshot, which an operator session still reads.
2.  The root refuses to make its own machine the standby (A reports
    `hostsControl`), naming why.
3.  Making B the standby: B's agent starts a standby control root by
    itself, which follows; the root's status names B, up to date, heard
    from recently.
4.  At the log and the snapshot, B's standby token is accepted, and B's
    `agent` token, A's standby token (no grant) and A's `gateway` token
    (granted gateway) are refused.
5.  A change on the root reaches the standby: signed in there with the
    passphrase, it reports the root's applied index, as a standby.
6.  Removing the grant refuses the next pull at once, though the token has
    minutes left; B's agent stops the standby and deletes its copy of the
    replication set.
7.  Failover, end to end: B is made the standby again and catches up; the
    root is stopped; the standby, signed in with the passphrase, promotes.
    It serves sign-in and the node list, names B the root, and B holds no
    standby grant. B's agent takes the new root's bundle and keeps the
    promoted copy running.
8.  The old root, started again, is fenced: its bundle is refused by B.
"""

from __future__ import annotations

import argparse
import asyncio
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

NODE_A = "sb-a"
NODE_B = "sb-b"
PROCESSES = ("control", "agent-a", "agent-b")
PORT_NAMES = ("control", "agent-a", "agent-b", "standby")
REPLICATION = ("/v1/control/log?after=0", "/v1/control/snapshot")

# Drop the calling shell's install settings before anything reads them: this
# machine's live agent sets EUGENE_PLEXUS_AGENT_CONFIG_FILE at user scope, and
# every process below inherits this process's environment.
for _key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
    del os.environ[_key]


def serve(kind: str, directory: Path, port: int, standby_port: int | None) -> None:
    """One control root or one agent, until `directory/stop` appears."""
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
        from eugene_plexus_agent import standby
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        if standby_port is not None:
            # Never the default control port on a developer's machine: the
            # standby this agent starts walks from here instead of 8083.
            standby.CONTROL_PORT = standby_port
        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml",
                bind_port=port,
                default_topology=False,
            )
        )
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="info", access_log=False
        )
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
        return {
            name: s.getsockname()[1]
            for name, s in zip(PORT_NAMES, sockets, strict=True)
        }
    finally:
        for sock in sockets:
            sock.close()


def claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def node_signer(node_dir: Path):
    """The node's own token signer, read from its files as its agent reads them."""
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    store = NodeIdentityStore(node_dir / "node.yaml")
    store.load()
    trust = NodeTrust(store, node_dir / BUNDLE_FILE)
    trust.load()
    return trust.signer()


def held_epoch(node_dir: Path) -> int:
    import json

    from eugene_plexus_agent import tokens

    pinned = yaml.safe_load((node_dir / "node.yaml").read_text(encoding="utf-8"))
    document = json.loads((node_dir / "trust_bundle.json").read_text(encoding="utf-8"))
    return tokens.parse_bundle(
        str(document["jws"]), authority=pinned["controlPublicKey"]
    ).epoch


def exercise(root: Path) -> int:
    from eugene_plexus_agent import tokens
    from eugene_plexus_agent.app import TRUST_PULL_INTERVAL_SECONDS

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

    (dir_a / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "advertiseUrl": base("agent-a"),
                "securityMode": "prompt_on_startup",
                # The root runs on A's machine: A's topology lists it.
                "components": [
                    {"name": "control", "kind": "control", "url": base("control")}
                ],
            }
        ),
        encoding="utf-8",
    )
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
        argv = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--serve",
            "control" if name == "control" else "agent",
            "--directory",
            str(directory),
            "--port",
            str(ports[name]),
        ]
        if name == "agent-b":
            argv += ["--standby-port", str(ports["standby"])]
        processes[name] = subprocess.Popen(
            argv,
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
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
            raise AssertionError(
                f"{name} did not shut down its owned processes"
            ) from None
        finally:
            logs.pop(name).close()

    def ok(message: str) -> None:
        passed.append(message)
        print(f"PASS {message}", flush=True)

    with httpx.Client(trust_env=False, timeout=20) as client:

        def call(name: str, method: str, path: str, token: str | None = None, **kwargs):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            return client.request(method, base(name) + path, headers=headers, **kwargs)

        def code(name: str, path: str, token: str) -> int:
            try:
                return call(name, "GET", path, token).status_code
            except httpx.HTTPError:
                return -1

        def wait_for(check, label: str, timeout: float = 45.0) -> float:
            """Poll `check` until it holds; returns the seconds it took."""
            started = time.perf_counter()
            deadline = started + timeout
            last: object = None
            while time.perf_counter() < deadline:
                try:
                    last = check()
                    if last:
                        return time.perf_counter() - started
                except httpx.HTTPError as exc:
                    last = exc
                dead = [n for n, p in processes.items() if p.poll() is not None]
                if dead:
                    raise AssertionError(f"{dead} exited while waiting for {label}")
                time.sleep(0.25)
            raise AssertionError(
                f"timed out after {timeout:.0f} s waiting for {label} ({last!r})"
            )

        def healthy(name: str) -> None:
            wait_for(
                lambda: call(name, "GET", "/healthz").status_code == 200,
                f"{name} health",
            )

        def login(name: str) -> str:
            response = call(
                name, "POST", "/v1/auth/login", json={"passphrase": passphrase}
            )
            assert response.status_code == 200, (
                f"{name} login: {response.status_code} {response.text}"
            )
            return response.json()["sessionToken"]

        def mint(node_dir: Path, sub: str, ttl: int = 900) -> str:
            token, _ = node_signer(node_dir).mint(
                typ=tokens.TYP_SERVICE,
                sub=sub,
                aud=[tokens.RECIPIENT_CONTROL],
                ttl_seconds=ttl,
            )
            return token

        def standby_of(session_b: str) -> dict | None:
            response = call("agent-b", "GET", "/v1/node", session_b)
            assert response.status_code == 200, f"B /v1/node: {response.status_code}"
            return response.json().get("standby")

        def reported(session: str) -> list[dict]:
            response = call("control", "GET", "/v1/control/status", session)
            assert response.status_code == 200, f"status: {response.status_code}"
            return response.json().get("standbys") or []

        def dump_logs() -> None:
            for name in PROCESSES:
                handle = logs.get(name)
                if handle is not None:
                    handle.flush()
                path = root / f"{name}.log"
                if path.exists():
                    tail = path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()[-60:]
                    print(f"{name} log tail:\n" + "\n".join(tail), file=sys.stderr)

        try:
            # ---- setup: a root, A on its machine, B ---------------------------
            start("control")
            healthy("control")
            response = call(
                "control",
                "POST",
                "/v1/auth/initialize",
                json={"passphrase": passphrase},
            )
            assert response.status_code == 204, (
                f"root initialize: {response.status_code}"
            )
            session_root = login("control")
            patched = call(
                "control",
                "PATCH",
                "/v1/config",
                session_root,
                json={"nodePollIntervalSeconds": 2},
            )
            assert patched.json().get("applied") == ["nodePollIntervalSeconds"], (
                patched.text
            )
            joins = {}
            for name, grants in (("agent-a", ["gateway"]), ("agent-b", None)):
                response = call(
                    "control",
                    "POST",
                    "/v1/nodes/join-token",
                    session_root,
                    json={"grants": grants} if grants else {},
                )
                assert response.status_code == 201, (
                    f"join token: {response.status_code}"
                )
                joins[name] = response.json()["token"]
            for name, node in (("agent-a", NODE_A), ("agent-b", NODE_B)):
                start(name)
                healthy(name)
                response = call(
                    name, "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
                )
                assert response.status_code == 200, (
                    f"{name} initialize: {response.status_code}"
                )
                standalone = response.json()["sessionToken"]
                response = call(
                    name,
                    "POST",
                    "/v1/node/enroll",
                    standalone,
                    json={
                        "controlUrl": base("control"),
                        "token": joins[name],
                        "name": node,
                    },
                )
                assert response.status_code == 200, (
                    f"{name} enroll: {response.status_code} {response.text}"
                )
            session_b = login("agent-b")

            def probed() -> bool:
                listed = call("control", "GET", "/v1/nodes", session_root).json()[
                    "nodes"
                ]
                return all(n.get("reachable") for n in listed) and len(listed) == 2

            wait_for(probed, "the root's first probe of both nodes")

            # ---- 1. before any grant, nothing follows ------------------------
            assert standby_of(session_b) is None, "B runs a standby before any grant"
            refused = {
                "B's standby token": mint(dir_b, "standby"),
                "B's agent token": mint(dir_b, "agent"),
                "A's agent token": mint(dir_a, "agent"),
            }
            for label, token in refused.items():
                for path in REPLICATION:
                    got = code("control", path, token)
                    assert got == 401, (
                        f"{label} at {path} answered {got} before any grant"
                    )
            for path in REPLICATION:
                assert code("control", path, session_root) == 200, path
            ok(
                "before any grant nothing follows: B runs no standby, and B's standby token "
                "and both agents' tokens are refused at the log and the snapshot"
            )

            # ---- 2. never the root's own machine -----------------------------
            own = call("control", "PUT", f"/v1/nodes/{NODE_A}/standby", session_root)
            assert own.status_code == 409 and "runs this control root" in own.text, (
                own.text
            )
            ok("the root refuses to make its own machine the standby, and says why")

            # ---- 3. B is made the standby, and follows by itself ---------------
            made = call("control", "PUT", f"/v1/nodes/{NODE_B}/standby", session_root)
            assert made.status_code == 202, made.text
            assert made.json()["standbyNode"] == NODE_B
            took = wait_for(
                lambda: (standby_of(session_b) or {}).get("status") == "running",
                "B's agent to start the standby",
                bundle_bound,
            )

            def caught_up() -> bool:
                [report] = reported(session_root) or [{}]
                return bool(
                    report.get("node") == NODE_B
                    and report.get("reachable")
                    and report.get("lagEntries") == 0
                )

            wait_for(caught_up, "the standby to catch up", 60)
            local = standby_of(session_b) or {}
            assert str(local.get("following", "")).rstrip("/") == base("control"), local
            ok(
                f"B's agent started a standby {took:.1f} s after the grant, and the root's "
                "status names B, up to date, heard from just now"
            )

            # ---- 4. who opens the replication surface -------------------------
            standby_token = mint(dir_b, "standby")
            for path in REPLICATION:
                got = code("control", path, standby_token)
                assert got == 200, f"B's standby token at {path} answered {got}"
            refused = {
                "B's agent token": mint(dir_b, "agent"),
                "A's standby token": mint(dir_a, "standby"),
                "A's gateway token": mint(dir_a, "gateway"),
            }
            for label, token in refused.items():
                for path in REPLICATION:
                    got = code("control", path, token)
                    assert got == 401, f"{label} at {path} answered {got}"
            ok(
                "B's standby token reads the log and the snapshot; B's agent token, A's "
                "standby token and A's gateway token are refused"
            )

            # ---- 5. a change reaches the standby -------------------------------
            changed = call(
                "control", "PATCH", "/v1/config", session_root, json={"uiTheme": "dark"}
            )
            assert changed.json().get("applied") == ["uiTheme"], changed.text
            root_index = call(
                "control", "GET", "/v1/control/status", session_root
            ).json()["appliedIndex"]
            session_standby = login("standby")

            def standby_at_root() -> bool:
                body = call(
                    "standby", "GET", "/v1/control/status", session_standby
                ).json()
                return (
                    body.get("role") == "standby"
                    and body.get("appliedIndex") == root_index
                )

            wait_for(standby_at_root, "the change to reach the standby")
            ok(
                f"a change on the root reached the standby, which reports index {root_index}"
            )

            # ---- 6. the grant is removed ----------------------------------------
            copy = dir_b / "standby-state"
            assert copy.is_dir(), "the standby keeps its copy beside B's agent.yaml"
            stopped = call(
                "control", "DELETE", f"/v1/nodes/{NODE_B}/standby", session_root
            )
            assert stopped.status_code == 202, stopped.text
            for path in REPLICATION:
                got = code("control", path, standby_token)
                assert got == 401, f"the old standby token at {path} answered {got}"
            left = claims(standby_token)["exp"] - time.time()
            gone = wait_for(
                lambda: standby_of(session_b) is None and not copy.exists(),
                "B's agent to stop the standby and delete its copy",
                bundle_bound,
            )
            ok(
                f"removing the grant refused the next pull with {left / 60:.0f} min left on the "
                f"token, and B's agent stopped the standby and deleted its copy ({gone:.1f} s)"
            )

            # ---- 7. failover, end to end ---------------------------------------
            again = call("control", "PUT", f"/v1/nodes/{NODE_B}/standby", session_root)
            assert again.status_code == 202, again.text
            wait_for(
                lambda: (standby_of(session_b) or {}).get("status") == "running",
                "the standby to start again",
                bundle_bound,
            )
            wait_for(caught_up, "the standby to catch up again", 60)
            epoch = call("control", "GET", "/v1/control/status", session_root).json()[
                "epoch"
            ]
            stop("control")
            session_standby = login("standby")
            promoted = call(
                "standby",
                "POST",
                "/v1/control/promote",
                session_standby,
                json={"passphrase": passphrase},
            )
            assert promoted.status_code == 200, promoted.text
            assert promoted.json()["role"] == "control"
            assert promoted.json()["epoch"] == epoch + 1
            fresh = login("standby")
            listed = call("standby", "GET", "/v1/nodes", fresh)
            assert listed.status_code == 200, listed.text
            record = next(n for n in listed.json()["nodes"] if n["name"] == NODE_B)
            assert record["role"] == "control" and "standby" not in (
                record.get("grants") or []
            )
            wait_for(
                lambda: held_epoch(dir_b) == epoch + 1,
                "B to take the new root's bundle",
                bundle_bound,
            )
            time.sleep(3)
            kept = standby_of(session_b) or {}
            assert kept.get("status") == "running", kept
            assert (copy / "log.jsonl").exists() or any(copy.iterdir()), (
                "the copy was kept"
            )
            ok(
                "the standby promoted with the passphrase: it signs people in, lists the "
                "nodes, names B the root with no standby grant, and B's agent kept it running"
            )

            # ---- 8. the old root is fenced -------------------------------------
            start("control")
            healthy("control")
            old = call("control", "GET", "/v1/trust/bundle").json()["jws"]
            pushed = call("agent-b", "POST", "/v1/node/trust-bundle", json={"jws": old})
            assert pushed.status_code in (401, 409), pushed.text
            assert held_epoch(dir_b) == epoch + 1
            ok("the old root, started again, is fenced: B refuses its bundle")
        except BaseException:
            dump_logs()
            raise
        finally:
            for name in ("agent-b", "agent-a", "control"):
                if name in processes:
                    stop(name)
    return len(passed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", choices=("agent", "control"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--standby-port", type=int)
    args = parser.parse_args()
    if args.serve:
        assert args.directory is not None and args.port is not None
        serve(args.serve, args.directory, args.port, args.standby_port)
        return
    with tempfile.TemporaryDirectory(prefix="ep-standby-") as directory:
        count = exercise(Path(directory))
    print(f"{count}/{count} checks passed", flush=True)


if __name__ == "__main__":
    main()
