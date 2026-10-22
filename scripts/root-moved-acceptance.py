"""Row 4 acceptance: agents learn a promoted root's address.

`docs/design/rows/row-04.md` section 5. Four machines, each an agent run
through the shared harness's real start path (`s8-ui-acceptance.py --serve`:
its machine port, its client doors, the children it spawns), on this host's
routable address and on ports the OS picks, never 8079-8083 or 8279-8283.
Each agent's address differs from the others' by port, so every call
between them is a call between machines: carried by each one's machine
table to the other's machine port, over TLS to the key the root signed for
it. Temporary state only; no `EUGENE_PLEXUS_*` variable from the calling
shell reaches any process. No model, no cloud service.

- A, the root's machine: its topology declares the control root, which A
  spawns behind its machine port.
- B, the machine made the standby.
- C, joined with the gateway grant: a gateway and an inference-driver over
  a stub engine.
- D, a worker.

Checks, in order:

1.  B is made the standby and follows. The root reports it on the root's own
    version, caught up, its copy matching the root's (row 4b).
2.  B's copy is made to differ as a pre-LT1 standby's did: the same index,
    and no machine key on any node (LT-OLDSB). B's agent is stopped for it
    and started again. With no new entry at the root, the copy holds every
    node's keys again: it took a fresh snapshot by itself. The root reports
    it matching.
3.  With D and A stopped, B is promoted with the passphrase. Within 60 s C
    names B as its root, at the new epoch. A sign-in through C works. C's
    gateway reads its routing from B, and a prompt through C is answered by
    the stub. B's signed machine list names B at the new epoch and carries
    C's key. B's agent says it runs the root, and its copy kept running.
4.  D, started again, names B as its root within 2 minutes.
5.  A, started again, is refused: the bundle and the machine list it last
    signed are answered 409 by C, D and A's own agent, which moves to B too.

Needs the agent, control, gateway and inference-driver installed in this
interpreter (the Pinned integration job has them). Run:
`python scripts/root-moved-acceptance.py`. Exits 1 when a check fails,
with the end of every agent's log. On Amish_Station (a worker of the live
install) it is run only in CI.
"""

from __future__ import annotations

import argparse
import importlib.util
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
import jwt
import yaml

HERE = Path(__file__).resolve()
HARNESS = HERE.parent / "s8-ui-acceptance.py"
MODEL = "r4-stub"
AGENTS = ("a", "b", "c", "d")
NODES = {name: f"agent-{name}" for name in AGENTS}
#: Ports this run never takes: the defaults and the live install's (+200).
NEVER = set(range(8079, 8084)) | set(range(8279, 8284))
#: How long a node waits for its own pull or a push, and then some.
PULL_BOUND = 90.0
#: What a standby whose copy differs from the root's logs (control, row 4b).
DIFFERS = "this copy differs from the root at index"

# Drop the calling shell's install settings before anything reads them: this
# machine's live agent sets EUGENE_PLEXUS_AGENT_CONFIG_FILE at user scope, and
# every process below inherits this process's environment.
for _key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
    del os.environ[_key]


# --------------------------------------------------------------------------- #
# The processes
# --------------------------------------------------------------------------- #


def serve_agent(
    directory: Path, port: int, machine_port: int, standby_port: int
) -> None:
    """One agent through the shared harness's real start path. A standby it
    starts walks up from `standby_port`, never from the default 8084."""
    from eugene_plexus_agent import standby

    standby.CONTROL_PORT = standby_port
    spec = importlib.util.spec_from_file_location("s8_harness", HARNESS)
    assert spec is not None and spec.loader is not None
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    harness.serve(directory, port, machine_port)


def stub_engine(port: int) -> None:
    """An OpenAI-compatible engine that echoes the last user message."""
    import uvicorn
    from fastapi import Body, FastAPI

    app = FastAPI()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models() -> dict:
        return {
            "object": "list",
            "data": [{"id": MODEL, "object": "model", "created": 0}],
        }

    @app.post("/v1/chat/completions")
    async def completions(body: dict = Body(...)) -> dict:  # noqa: B008 - FastAPI's idiom
        said = str((body.get("messages") or [{}])[-1].get("content") or "")
        return {
            "id": "chatcmpl-r4",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"echo: {said}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6},
        }

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


def routable_address() -> str:
    """The address this host would use to reach another; no packet is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    finally:
        probe.close()


def free_ports(names: list[str]) -> dict[str, int]:
    """Distinct ports the OS says are free on every interface right now."""
    held: list[socket.socket] = []
    ports: dict[str, int] = {}
    try:
        while len(ports) < len(names):
            sock = socket.socket()
            sock.bind(("0.0.0.0", 0))
            port = int(sock.getsockname()[1])
            held.append(sock)
            if port in NEVER or port in ports.values():
                continue
            ports[names[len(ports)]] = port
        return ports
    finally:
        for sock in held:
            sock.close()


def claims_of(jws: str) -> dict[str, Any]:
    return dict(jwt.decode(jws, options={"verify_signature": False}))


class Failed(AssertionError):
    """A check did not hold; the message names what was observed."""


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


class Run:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lan = routable_address()
        names = [f"agent-{a}" for a in AGENTS] + [f"machine-{a}" for a in AGENTS]
        names += ["control", "standby", "gateway", "driver", "stub"]
        self.ports = free_ports(names)
        self.dirs = {a: root / a for a in AGENTS}
        for directory in self.dirs.values():
            directory.mkdir()
        self.passphrase = secrets.token_urlsafe(24)
        self.processes: dict[str, subprocess.Popen] = {}
        self.logs: dict[str, Any] = {}
        self.passed: list[str] = []
        self.client = httpx.Client(trust_env=False, timeout=30)

    # ---- addresses -----------------------------------------------------------

    def local(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def agent(self, a: str) -> str:
        return self.local(f"agent-{a}")

    def advertised(self, a: str) -> str:
        return f"http://{self.lan}:{self.ports[f'agent-{a}']}"

    def door(self, a: str) -> str:
        """The plain form of a machine's port: what a node joins at, and
        what a promoted root's list names (`MachineList.control.url`)."""
        return f"http://{self.lan}:{self.ports[f'machine-{a}']}"

    # ---- processes -----------------------------------------------------------

    def write_agent_yaml(self) -> None:
        a, c = self.dirs["a"], self.dirs["c"]
        components = {
            "a": [
                {
                    "name": "control",
                    "kind": "control",
                    "url": self.local("control"),
                    "spawn": {
                        "configFile": str(a / "control.yaml"),
                        "env": {
                            "EUGENE_PLEXUS_CONTROL_STATE_DIR": str(a / "control-state")
                        },
                    },
                }
            ],
            "c": [
                {
                    "name": "gateway",
                    "kind": "gateway",
                    "url": self.local("gateway"),
                    "spawn": {"configFile": str(c / "gateway.yaml")},
                },
                {
                    "name": "r4-driver",
                    "kind": "inference-driver",
                    "url": self.local("driver"),
                    "spawn": {"configFile": str(c / "inference-driver.yaml")},
                },
            ],
        }
        (a / "control.yaml").write_text("{}\n", encoding="utf-8")
        (c / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        (c / "inference-driver.yaml").write_text(
            yaml.safe_dump(
                {
                    "provider": "openai_compat_custom",
                    "baseUrl": self.local("stub"),
                    "modelId": MODEL,
                    "backendLocality": "local",
                }
            ),
            encoding="utf-8",
        )
        for name, directory in self.dirs.items():
            (directory / "agent.yaml").write_text(
                yaml.safe_dump(
                    {
                        "firstRunComplete": True,
                        "updateChecks": False,
                        "advertiseUrl": self.advertised(name),
                        "securityMode": "prompt_on_startup",
                        "components": components.get(name, []),
                    }
                ),
                encoding="utf-8",
            )

    def start(self, a: str) -> None:
        directory = self.dirs[a]
        (directory / "stop").unlink(missing_ok=True)
        self.logs[a] = (self.root / f"agent-{a}.log").open("a", encoding="utf-8")
        argv = [
            sys.executable,
            str(HERE),
            "--serve-agent",
            str(directory),
            "--port",
            str(self.ports[f"agent-{a}"]),
            "--machine-port",
            str(self.ports[f"machine-{a}"]),
            "--standby-port",
            str(self.ports["standby"]),
        ]
        self.processes[a] = subprocess.Popen(
            argv,
            cwd=directory,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdin=subprocess.DEVNULL,
            stdout=self.logs[a],
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.wait(
            lambda: self.get(self.agent(a), "/healthz").status_code == 200, f"agent {a}"
        )

    def stop(self, a: str) -> None:
        process = self.processes.pop(a)
        (self.dirs[a] / "stop").touch()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                process.kill()
            process.wait(timeout=10)
            raise Failed(f"agent {a} did not stop within 60 s") from None
        finally:
            self.logs.pop(a).close()

    def stub(self) -> None:
        self.logs["stub"] = (self.root / "stub.log").open("a", encoding="utf-8")
        self.stub_process = subprocess.Popen(
            [
                sys.executable,
                str(HERE),
                "--serve-stub",
                "--port",
                str(self.ports["stub"]),
            ],
            cwd=self.root,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdin=subprocess.DEVNULL,
            stdout=self.logs["stub"],
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.wait(
            lambda: self.get(self.local("stub"), "/health").status_code == 200, "stub"
        )

    # ---- calls ---------------------------------------------------------------

    def call(
        self, method: str, base: str, path: str, token: str | None = None, **kwargs: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, base + path, headers=headers, **kwargs)

    def get(self, base: str, path: str, token: str | None = None) -> httpx.Response:
        return self.call("GET", base, path, token)

    def wait(self, check: Any, label: str, timeout: float = 60.0) -> float:
        """Poll `check` until it holds; returns the seconds it took."""
        started = time.perf_counter()
        last: object = None
        while time.perf_counter() - started < timeout:
            try:
                last = check()
                if last:
                    return time.perf_counter() - started
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last = exc
            dead = [a for a, p in self.processes.items() if p.poll() is not None]
            stub = getattr(self, "stub_process", None)
            if stub is not None and stub.poll() is not None:
                dead.append("stub")
            if dead:
                raise Failed(f"agent(s) {dead} exited while waiting for {label}")
            time.sleep(0.5)
        raise Failed(
            f"timed out after {timeout:.0f} s waiting for {label} (last: {last!r})"
        )

    def login(self, base: str) -> str:
        def attempt() -> str | None:
            got = self.call(
                "POST", base, "/v1/auth/login", json={"passphrase": self.passphrase}
            )
            return str(got.json()["sessionToken"]) if got.status_code == 200 else None

        token: Any = None

        def ok() -> bool:
            nonlocal token
            token = attempt()
            return token is not None

        self.wait(ok, f"sign-in at {base}", 60)
        return str(token)

    def node(self, a: str, session: str) -> dict[str, Any]:
        got = self.get(self.agent(a), "/v1/node", session)
        if got.status_code != 200:
            raise Failed(
                f"agent {a} GET /v1/node answered {got.status_code}: {got.text[:300]}"
            )
        return dict(got.json())

    def ok(self, message: str) -> None:
        self.passed.append(message)
        print(f"PASS {message}", flush=True)

    def dump_logs(self) -> None:
        for a in AGENTS:
            handle = self.logs.get(a)
            if handle is not None:
                handle.flush()
            path = self.root / f"agent-{a}.log"
            if path.exists():
                tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[
                    -80:
                ]
                print(f"--- agent {a} log tail ---", *tail, sep="\n", file=sys.stderr)

    def close(self) -> None:
        for a in list(self.processes):
            try:
                self.stop(a)
            except Failed as exc:
                print(f"while closing: {exc}", file=sys.stderr)
        stub = getattr(self, "stub_process", None)
        if stub is not None:
            stub.kill()
            stub.wait(timeout=10)
        for handle in self.logs.values():
            handle.close()
        self.client.close()


def strip_machine_keys(state_dir: Path) -> tuple[int, int]:
    """Make a standby's copy what a pre-LT1 standby's was: the same index,
    and no machine key or machine URL on any node. Written as a snapshot at
    that index with the log compacted through it, as the copy keeps itself.
    Returns `(index, nodes that had keys)`."""
    from eugene_plexus_control.applied import to_canonical
    from eugene_plexus_control.log_store import LogStore
    from eugene_plexus_control.state_machine import ROLE_STANDBY, StateMachine

    machine = StateMachine(LogStore(state_dir), role=ROLE_STANDBY)
    machine.load()
    document = to_canonical(machine.state)
    had = 0
    for node in document["nodes"]:
        had += bool(node.get("tlsPins"))
        node["tlsPins"] = []
        node["tlsNextPin"] = None
        node["machineUrl"] = None
    LogStore(state_dir).write_snapshot(document, compact_through=machine.state.index)
    return machine.state.index, had


def exercise(run: Run) -> None:
    run.write_agent_yaml()
    run.stub()
    passphrase = run.passphrase

    # ---- the install: A runs the root, B, C and D join it --------------------
    run.start("a")
    control = run.local("control")
    run.wait(lambda: run.get(control, "/healthz").status_code == 200, "the root", 90)
    got = run.call(
        "POST", control, "/v1/auth/initialize", json={"passphrase": passphrase}
    )
    if got.status_code != 204:
        raise Failed(f"root initialize answered {got.status_code}: {got.text}")
    version = run.get(control, "/healthz").json()["version"]
    session_root = run.login(control)
    patched = run.call(
        "PATCH",
        control,
        "/v1/config",
        session_root,
        json={"nodePollIntervalSeconds": 2},
    )
    if patched.json().get("applied") != ["nodePollIntervalSeconds"]:
        raise Failed(f"poll interval: {patched.text}")

    def join(a: str, at: str, grants: list[str] | None = None) -> None:
        token = run.call(
            "POST",
            control,
            "/v1/nodes/join-token",
            session_root,
            json={"grants": grants} if grants else {},
        )
        if token.status_code != 201:
            raise Failed(f"join token for {a}: {token.status_code} {token.text}")
        initialized = run.call(
            "POST", run.agent(a), "/v1/auth/initialize", json={"passphrase": passphrase}
        )
        if initialized.status_code != 200:
            raise Failed(f"agent {a} initialize: {initialized.status_code}")
        enrolled = run.call(
            "POST",
            run.agent(a),
            "/v1/node/enroll",
            initialized.json()["sessionToken"],
            json={"controlUrl": at, "token": token.json()["token"], "name": NODES[a]},
        )
        if enrolled.status_code != 200:
            raise Failed(f"agent {a} enroll: {enrolled.status_code} {enrolled.text}")

    # A joins its own root through its own machine port, on this machine.
    join("a", f"http://127.0.0.1:{run.ports['machine-a']}")
    for a, grants in (("b", None), ("c", ["gateway"]), ("d", None)):
        run.start(a)
        join(a, run.door("a"), grants)
    sessions = {a: run.login(run.agent(a)) for a in AGENTS}

    def every_node_keyed() -> bool:
        listed = run.get(control, "/v1/nodes", session_root).json()["nodes"]
        return len(listed) == 4 and all(
            n.get("reachable") and (n.get("machineTls") or {}).get("state") != "no_key"
            for n in listed
        )

    run.wait(
        every_node_keyed, "the root to reach all four machines with their keys", 120
    )

    # ---- 1. B follows, on the root's version, matching -----------------------
    made = run.call("PUT", control, f"/v1/nodes/{NODES['b']}/standby", session_root)
    if made.status_code != 202:
        raise Failed(f"make B the standby: {made.status_code} {made.text}")

    def standby_report() -> dict[str, Any]:
        status = run.get(control, "/v1/control/status", session_root).json()
        return dict((status.get("standbys") or [{}])[0])

    def matching() -> bool:
        report = standby_report()
        return bool(
            report.get("node") == NODES["b"]
            and report.get("reachable")
            and report.get("lagEntries") == 0
            and report.get("version") == version
            and report.get("matches") is True
        )

    took = run.wait(
        matching, "B's standby to follow and match the root", PULL_BOUND + 60
    )
    run.ok(
        f"B's standby follows ({took:.0f} s after the grant); the root reports it on its own "
        f"version {version}, caught up and matching"
    )

    # ---- 2. a copy that differs takes a fresh one by itself ------------------
    copy_dir = run.dirs["b"] / "standby-state"
    log_b = run.root / "agent-b.log"
    run.stop("b")
    said_before = log_b.read_text(encoding="utf-8", errors="replace").count(DIFFERS)
    index, had = strip_machine_keys(copy_dir)
    if had < 4:
        raise Failed(
            f"only {had} of 4 nodes had machine keys in B's copy to begin with"
        )
    restarted = time.time()
    run.start("b")

    def standby_url() -> str:
        local = run.node("b", sessions["b"]).get("standby") or {}
        return str(local.get("url") or "").rstrip("/")

    run.wait(lambda: standby_url(), "B's agent to start its standby again", PULL_BOUND)
    copy = standby_url()
    session_copy = run.login(copy)

    def keys_of(base: str, session: str) -> dict[str, list[str]]:
        snapshot = run.get(base, "/v1/control/snapshot", session).json()
        return {n["name"]: sorted(n.get("tlsPins") or []) for n in snapshot["nodes"]}

    def fresh_copy() -> bool:
        report = standby_report()
        heard = report.get("lastContactAt")
        said = log_b.read_text(encoding="utf-8", errors="replace").count(DIFFERS)
        return bool(
            said > said_before
            and keys_of(copy, session_copy) == keys_of(control, session_root)
            and report.get("matches") is True
            and heard
            and _seconds(heard) > restarted
        )

    took = run.wait(fresh_copy, "B's copy to take a fresh snapshot", 90)
    run.ok(
        f"a copy at index {index} holding no machine key ({had} nodes stripped) said "
        f"it differs and took a fresh snapshot by itself in {took:.0f} s: it holds "
        "every node's keys, and the root reports it matching"
    )

    # ---- 3. A and D stop; B is promoted; C follows within 60 s ---------------
    epoch = run.get(control, "/v1/control/status", session_root).json()["epoch"]
    machine_c = run.node("c", sessions["c"])["machine"]
    run.stop("d")
    run.stop("a")
    session_copy = run.login(copy)
    promoted = run.call(
        "POST",
        copy,
        "/v1/control/promote",
        session_copy,
        json={"passphrase": passphrase},
    )
    if promoted.status_code != 200 or promoted.json().get("epoch") != epoch + 1:
        raise Failed(f"promote: {promoted.status_code} {promoted.text}")
    at_b = run.door("b")

    def follows_b(a: str) -> bool:
        body = run.node(a, sessions[a])
        return bool(
            str(body.get("controlUrl") or "").rstrip("/") == at_b
            and body.get("controlUrlEpoch") == epoch + 1
            and body.get("epoch") == epoch + 1
        )

    moved = run.wait(lambda: follows_b("c"), "C to name B as its root", 60)
    signed_in = run.call(
        "POST", run.agent("c"), "/v1/auth/login", json={"passphrase": passphrase}
    )
    if signed_in.status_code != 200:
        raise Failed(
            f"sign-in through C after the move: {signed_in.status_code} {signed_in.text}"
        )
    operator = str(signed_in.json()["sessionToken"])
    gateway = run.local("gateway")

    def routes_from_b() -> bool:
        table = run.get(gateway, "/v1/admin/routing", operator).json()
        root_view = table.get("control_root") or {}
        return bool(
            str(root_view.get("url") or "").rstrip("/") == at_b
            and root_view.get("reachable")
        )

    run.wait(routes_from_b, "C's gateway to read its routing from B", 60)
    canary = "R4CANARY" + secrets.token_hex(6)
    answered = run.call(
        "POST",
        gateway,
        "/v1/chat/completions",
        operator,
        json={"model": MODEL, "messages": [{"role": "user", "content": canary}]},
        timeout=60,
    )
    if answered.status_code != 200 or canary not in answered.text:
        raise Failed(
            f"a prompt through C: {answered.status_code} {answered.text[:400]}"
        )
    listed = run.get(copy, "/v1/trust/machines").json()["jws"]
    named = claims_of(listed)
    if named.get("control") != {"epoch": epoch + 1, "node": NODES["b"], "url": at_b}:
        raise Failed(f"B's list names {named.get('control')}")
    c_entry = next((n for n in named["nodes"] if n["name"] == NODES["c"]), {})
    if machine_c["pin"] not in (c_entry.get("pins") or []):
        raise Failed(f"B's list does not carry C's key {machine_c['pin']}: {c_entry}")

    def b_runs_the_root() -> bool:
        body = run.node("b", sessions["b"])
        return body.get("hostsControl") is True and not body.get("standby")

    run.wait(b_runs_the_root, "B's agent to take its copy for the root", 60)
    if run.get(copy, "/healthz").json()["details"]["role"] != "control":
        raise Failed("B's copy is not the root after the promotion")
    run.ok(
        f"B promoted with the passphrase; C named B ({at_b}) at epoch {epoch + 1} in "
        f"{moved:.0f} s, signs in and answers a prompt with its routing read from B; B's "
        "list names B and carries C's key; B's agent runs its copy as the root"
    )

    # ---- 4. D, started again, follows within 2 minutes -----------------------
    # The session D was given at the start: a sign-in through D would go to
    # the root D still names, which is stopped.
    run.start("d")
    moved = run.wait(lambda: follows_b("d"), "D to name B as its root", 120)
    run.ok(f"D, started again, named B as its root in {moved:.0f} s")

    # ---- 5. A, started again, is refused --------------------------------------
    run.start("a")
    run.wait(
        lambda: run.get(control, "/healthz").status_code == 200, "the old root", 90
    )
    health = run.get(control, "/healthz").json()["details"]
    if health.get("epoch") != epoch:
        raise Failed(f"the old root came back at epoch {health.get('epoch')}")
    old_bundle = run.get(control, "/v1/trust/bundle").json()["jws"]
    old_list = run.get(control, "/v1/trust/machines").json()["jws"]
    # No sign-in through A: it would unlock the old root. The session A was
    # given at the start still verifies (the root's token key did not change).
    run.wait(lambda: follows_b("a"), "A's own agent to name B as its root", 120)
    for a in ("c", "d", "a"):
        for path, jws in (
            ("/v1/node/trust-bundle", old_bundle),
            ("/v1/node/machine-list", old_list),
        ):
            pushed = run.call("POST", run.agent(a), path, json={"jws": jws})
            if pushed.status_code != 409:
                raise Failed(
                    f"agent {a} answered {pushed.status_code} to the old root's {path}"
                )
        if not follows_b(a):
            raise Failed(f"agent {a} no longer follows B")
    run.ok(
        f"the old root, started again at epoch {epoch}, is refused: C, D and A's own agent "
        "answer 409 to its bundle and its list, and all three follow B"
    )


def _seconds(stamp: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve-agent", type=Path)
    parser.add_argument("--serve-stub", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--machine-port", type=int)
    parser.add_argument("--standby-port", type=int)
    args = parser.parse_args()
    if args.serve_agent:
        serve_agent(args.serve_agent, args.port, args.machine_port, args.standby_port)
        return 0
    if args.serve_stub:
        stub_engine(args.port)
        return 0
    with tempfile.TemporaryDirectory(
        prefix="ep-r4-", ignore_cleanup_errors=True
    ) as tmp:
        run = Run(Path(tmp))
        try:
            exercise(run)
        except BaseException:
            run.dump_logs()
            raise
        finally:
            run.close()
    print(f"{len(run.passed)}/5 checks passed", flush=True)
    return 0 if len(run.passed) == 5 else 1


if __name__ == "__main__":
    sys.exit(main())
