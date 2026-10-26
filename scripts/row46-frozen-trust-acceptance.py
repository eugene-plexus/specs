"""Row 46 acceptance: a machine cut off from the root takes no changes from others.

`docs/design/rows/row-46.md` section 5. Real processes on loopback ports the
operating system hands out (never 8079-8083 or the live install's 8279-8283),
temporary state, and every `EUGENE_PLEXUS_*` variable of the calling shell
cleared before anything starts. No model, no GPU, no cloud service.

- A control root, its own process.
- Agent B, the machine that loses its root. It runs the agent's own start
  path, as row 2's harness does (`agent.serve`: its machine port, its client
  doors, the children it spawns), and spawns a gateway and an
  inference-driver over a stub engine that echoes. It declares one runtime,
  `r46`, which is never started.
- Agent C, another machine, joined with the `gateway` grant: the machine
  whose gateway would start and stop runtimes on B. Its token key, read from
  its own `node.yaml`, signs "another machine's stop request".

Checks, in order:

1. In time, C's stop request for `r46` on B is taken, and B says it heard
   from the root a moment ago, under the default limit of 24 hours.
2. The root is stopped. B's limit is set to 1 hour (`PATCH /v1/config`), B is
   stopped, its kept bundle's time is set back 2 hours, and B is started
   again with the root still stopped. B says it refuses changes from other
   machines (`trustBundleFrozen`), and so does the setting's status line.
   C's stop request is refused with 403, naming the 2 hours. A prompt
   through B's gateway is still answered. The root's own session, and a
   token B's key signs for itself, still stop `r46` on B.
3. The root is started again. Within B's next pull (every minute) B hears
   from it, and C's stop request is taken again.
4. `--sabotage`: the root is stopped again, and B is started with the age
   check in `refuse_when_frozen` skipped, in B's process only (no file
   changes, so nothing needs restoring). Step 2's refusal check must fail.

Needs the agent, control, gateway and inference-driver installed in this
interpreter (the Pinned integration job has them). Run:
`python scripts/row46-frozen-trust-acceptance.py [--sabotage]`.
"""

from __future__ import annotations

import argparse
import importlib
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

HERE = Path(__file__).resolve()
MODEL = "r46-stub"
RUNTIME = "r46"
#: Ports this run never takes: the defaults and the live install's (+200).
NEVER = set(range(8079, 8085)) | set(range(8279, 8285))
#: The agent pulls the root's bundle every minute; and some to spare.
PULL_BOUND = 100.0
LIMIT_HOURS = 1
SILENT_HOURS = 2
REFUSAL = (
    f"This machine has not heard from the root for {SILENT_HOURS} hours, so it takes no "
    "changes from other machines. Check its network to the root."
)

# This machine's live agent sets EUGENE_PLEXUS_AGENT_CONFIG_FILE at user scope,
# and every process below inherits this process's environment.
for _key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
    del os.environ[_key]


class Failed(AssertionError):
    """A check did not hold; the message names what was observed."""


# --------------------------------------------------------------------------- #
# The processes
# --------------------------------------------------------------------------- #


def serve_agent(directory: Path, port: int, machine_port: int, sabotage: bool) -> None:
    """One agent through its own start path, as row 2's harness runs it."""
    agent = importlib.import_module("eugene_plexus_agent.__main__")
    from eugene_plexus_agent.settings import Settings

    if sabotage:
        from eugene_plexus_agent import dependencies

        if not hasattr(dependencies, "refuse_when_frozen"):
            raise SystemExit("this agent has no refuse_when_frozen to sabotage (pre row 46)")
        # The age check skipped: every token passes, whatever the silence.
        dependencies.refuse_when_frozen = lambda request, claims: None  # type: ignore[assignment]
        print("row46: SABOTAGED: refuse_when_frozen skips the age check", flush=True)
    settings = Settings(
        config_file=directory / "agent.yaml",
        bind_port=port,
        default_topology=False,
        machine_port=machine_port,
    )
    agent.serve(settings, unattended=True, should_stop=lambda: (directory / "stop").exists())


def serve_control(directory: Path, port: int) -> None:
    import uvicorn
    from eugene_plexus_control.app import create_app
    from eugene_plexus_control.settings import Settings

    app = create_app(
        Settings(config_file=directory / "control.yaml", state_dir=directory / "state")
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


def serve_stub(port: int) -> None:
    """An OpenAI-compatible engine that echoes the last user message."""
    import uvicorn
    from fastapi import Body, FastAPI

    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": MODEL, "object": "model", "created": 0}]}

    @app.post("/v1/chat/completions")
    async def completions(body: dict = Body(...)) -> dict[str, Any]:  # noqa: B008
        said = str((body.get("messages") or [{}])[-1].get("content") or "")
        return {
            "id": "chatcmpl-r46",
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


def free_ports(names: list[str]) -> dict[str, int]:
    """Distinct loopback ports the OS says are free now, none of the forbidden."""
    held: list[socket.socket] = []
    ports: dict[str, int] = {}
    try:
        while len(ports) < len(names):
            sock = socket.socket()
            sock.bind(("0.0.0.0", 0))
            held.append(sock)
            port = int(sock.getsockname()[1])
            if port in NEVER or port in ports.values():
                continue
            ports[names[len(ports)]] = port
        return ports
    finally:
        for sock in held:
            sock.close()


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


class Run:
    def __init__(self, root: Path) -> None:
        self.root = root
        names = ["control", "stub", "agent-b", "machine-b", "agent-c", "machine-c"]
        names += ["gateway", "driver"]
        self.ports = free_ports(names)
        self.dirs = {name: root / name for name in ("control", "b", "c")}
        for directory in self.dirs.values():
            directory.mkdir()
        self.passphrase = secrets.token_urlsafe(24)
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.logs: dict[str, Any] = {}
        self.passed: list[str] = []
        self.client = httpx.Client(trust_env=False, timeout=60)

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    # ---- processes -----------------------------------------------------------

    def spawn(self, name: str, argv: list[str], cwd: Path) -> None:
        log = (self.root / f"{name}.log").open("ab")
        self.logs[name] = log
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        env["PYTHONUNBUFFERED"] = "1"
        self.processes[name] = subprocess.Popen(
            [sys.executable, str(HERE), *argv],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def start_control(self) -> None:
        directory = self.dirs["control"]
        self.spawn(
            "control",
            ["--serve-control", str(directory), "--port", str(self.ports["control"])],
            directory,
        )
        self.wait(
            lambda: self.call("GET", "control", "/healthz").status_code == 200, "the root", 90
        )

    def stop_control(self) -> None:
        process = self.processes.pop("control")
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        self.logs.pop("control").close()
        try:
            self.call("GET", "control", "/healthz")
        except httpx.HTTPError:
            return
        raise Failed("the root still answers after it was stopped")

    def start_agent(self, a: str, *, sabotage: bool = False) -> None:
        directory = self.dirs[a]
        (directory / "stop").unlink(missing_ok=True)
        argv = [
            "--serve-agent",
            str(directory),
            "--port",
            str(self.ports[f"agent-{a}"]),
            "--machine-port",
            str(self.ports[f"machine-{a}"]),
        ]
        self.spawn(f"agent-{a}", [*argv, *(["--sabotage"] if sabotage else [])], directory)
        self.wait(
            lambda: self.call("GET", f"agent-{a}", "/healthz").status_code == 200, f"agent {a}", 90
        )

    def stop_agent(self, a: str) -> None:
        process = self.processes.pop(f"agent-{a}")
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
            self.logs.pop(f"agent-{a}").close()

    def close(self) -> None:
        for a in ("b", "c"):
            if f"agent-{a}" in self.processes:
                try:
                    self.stop_agent(a)
                except Failed as exc:
                    print(f"while closing: {exc}", file=sys.stderr)
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self.processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in self.logs.values():
            log.close()
        self.client.close()

    def dump_logs(self) -> None:
        for log in self.logs.values():
            log.flush()
        for path in sorted(self.root.glob("*.log")):
            tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
            print(f"--- {path.stem} log tail ---", *tail, sep="\n", file=sys.stderr)

    # ---- calls ---------------------------------------------------------------

    def call(
        self, method: str, name: str, path: str, token: str | None = None, **kw: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, self.url(name) + path, headers=headers, **kw)

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
            dead = [n for n, p in self.processes.items() if p.poll() is not None]
            if dead:
                raise Failed(f"{dead} exited while waiting for {label}")
            time.sleep(0.5)
        raise Failed(f"timed out after {timeout:.0f} s waiting for {label} (last: {last!r})")

    def login(self, name: str) -> str:
        token: Any = None

        def signed_in() -> bool:
            nonlocal token
            got = self.call("POST", name, "/v1/auth/login", json={"passphrase": self.passphrase})
            token = got.json().get("sessionToken") if got.status_code == 200 else None
            return token is not None

        self.wait(signed_in, f"sign-in at {name}", 60)
        return str(token)

    def trust_of(self, a: str) -> Any:
        from eugene_plexus_agent.node_identity import NODE_FILE, NodeIdentityStore
        from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

        store = NodeIdentityStore(self.dirs[a] / NODE_FILE)
        store.load()
        trust = NodeTrust(store, self.dirs[a] / BUNDLE_FILE)
        trust.load()
        return trust

    def own_token(self, a: str, sub: str = "agent") -> str:
        """What agent `a` gives its own child: its own key, addressed to it alone."""
        trust = self.trust_of(a)
        token, _ = trust.mint_service(sub=sub, audience=trust.recipient, ttl_seconds=600)
        return str(token)

    def from_c(self) -> str:
        """C's gateway token for B: what C's gateway sends to stop a runtime on B.

        Read from C's own files. C rewrites its bundle at every pull, and on
        Windows a read during that replace is refused for an instant, which
        leaves the copy read here holding no bundle; the next read sees it."""
        from eugene_plexus_agent.trust import MintRefused

        for _ in range(20):
            try:
                token, _ = self.trust_of("c").mint_service(sub="gateway", audience="node:agent-b")
                return str(token)
            except MintRefused:
                time.sleep(0.2)
        raise Failed("C's own files never gave a gateway token for B")

    def wait_released(self, names: list[str]) -> None:
        """Until nothing listens on these ports: a stopped agent's children too."""

        def released() -> bool:
            for name in names:
                with socket.socket() as probe:
                    probe.settimeout(1)
                    if probe.connect_ex(("127.0.0.1", self.ports[name])) == 0:
                        return False
            return True

        self.wait(released, f"{', '.join(names)} to stop listening", 60)

    def node(self, a: str) -> dict[str, Any]:
        got = self.call("GET", f"agent-{a}", "/v1/node", self.own_token(a))
        if got.status_code != 200:
            raise Failed(f"agent {a} GET /v1/node answered {got.status_code}: {got.text[:300]}")
        return dict(got.json())

    def setting(self, session: str) -> dict[str, Any]:
        schema = self.call("GET", "agent-b", "/v1/config/schema", session).json()
        return next(f for f in schema["fields"] if f["key"] == "maxTrustBundleAgeHours")

    def stop_from(self, token: str) -> httpx.Response:
        return self.call(
            "POST", "agent-b", f"/v1/runtimes/{RUNTIME}/stop", token, json={"reason": "idle"}
        )

    def prompt(self, session: str, canary: str) -> httpx.Response:
        return self.call(
            "POST",
            "gateway",
            "/v1/chat/completions",
            session,
            json={"model": MODEL, "messages": [{"role": "user", "content": canary}]},
        )

    def answered(self, session: str, label: str) -> None:
        canary = secrets.token_hex(6)
        self.wait(
            lambda: (got := self.prompt(session, canary)).status_code == 200 and canary in got.text,
            f"a prompt through B's gateway ({label})",
            120,
        )

    def ok(self, message: str) -> None:
        self.passed.append(message)
        print(f"PASS {message}", flush=True)

    # ---- the install ----------------------------------------------------------

    def write_agent_yaml(self) -> None:
        b = self.dirs["b"]
        (b / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        (b / "inference-driver.yaml").write_text(
            yaml.safe_dump(
                {
                    "provider": "openai_compat_custom",
                    "baseUrl": self.url("stub"),
                    "modelId": MODEL,
                    "backendLocality": "local",
                }
            ),
            encoding="utf-8",
        )
        components = {
            "b": [
                {
                    "name": "gateway",
                    "kind": "gateway",
                    "url": self.url("gateway"),
                    "spawn": {"configFile": str(b / "gateway.yaml")},
                },
                {
                    "name": "r46-driver",
                    "kind": "inference-driver",
                    "url": self.url("driver"),
                    "spawn": {"configFile": str(b / "inference-driver.yaml")},
                },
            ],
            "c": [],
        }
        for a, entries in components.items():
            (self.dirs[a] / "agent.yaml").write_text(
                yaml.safe_dump(
                    {
                        "firstRunComplete": True,
                        "updateChecks": False,
                        "securityMode": "prompt_on_startup",
                        "components": entries,
                    }
                ),
                encoding="utf-8",
            )

    def join(self, a: str, root_session: str, grants: list[str]) -> None:
        token = self.call(
            "POST", "control", "/v1/nodes/join-token", root_session, json={"grants": grants}
        )
        if token.status_code not in (200, 201):
            raise Failed(f"join token for {a}: {token.status_code} {token.text}")
        initialized = self.call(
            "POST", f"agent-{a}", "/v1/auth/initialize", json={"passphrase": self.passphrase}
        )
        if initialized.status_code != 200:
            raise Failed(f"agent {a} initialize: {initialized.status_code} {initialized.text}")
        enrolled = self.call(
            "POST",
            f"agent-{a}",
            "/v1/node/enroll",
            initialized.json()["sessionToken"],
            json={
                "controlUrl": self.url("control"),
                "token": token.json()["token"],
                "name": f"agent-{a}",
            },
        )
        if enrolled.status_code != 200:
            raise Failed(f"agent {a} enroll: {enrolled.status_code} {enrolled.text}")


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


def install(run: Run) -> str:
    """The root, B and C joined; B's runtime declared. Returns B's session."""
    run.write_agent_yaml()
    run.spawn("stub", ["--serve-stub", "--port", str(run.ports["stub"])], run.root)
    run.wait(lambda: run.call("GET", "stub", "/health").status_code == 200, "the stub engine")
    run.start_control()
    got = run.call("POST", "control", "/v1/auth/initialize", json={"passphrase": run.passphrase})
    if got.status_code != 204:
        raise Failed(f"root initialize answered {got.status_code}: {got.text}")
    root_session = run.login("control")
    for a, grants in (("b", []), ("c", ["gateway"])):
        run.start_agent(a)
        run.join(a, root_session, grants)
    session_b = run.login("agent-b")
    model = run.dirs["b"] / "models" / "r46.gguf"
    model.parent.mkdir()
    model.write_bytes(b"GGUF")
    declared = run.call(
        "POST",
        "agent-b",
        "/v1/runtimes",
        session_b,
        json={
            "name": RUNTIME,
            "engine": "llama_cpp",
            "modelPath": str(model),
            "autoStart": False,
            "autoDriver": False,
        },
    )
    if declared.status_code != 201:
        raise Failed(f"B declares {RUNTIME}: {declared.status_code} {declared.text[:400]}")
    return session_b


def step_in_time(run: Run, session_b: str) -> None:
    node = run.node("b")
    if (
        node.get("trustBundleFrozen") is not False
        or node.get("trustBundleMaxAgeSeconds") != 24 * 3600
    ):
        raise Failed(f"B in time says {_said(node)}")
    stopped = run.stop_from(run.from_c())
    if stopped.status_code != 202:
        raise Failed(f"C's stop request in time: {stopped.status_code} {stopped.text[:300]}")
    run.answered(session_b, "in time")
    run.ok(
        f"in time C's stop request for {RUNTIME} on B is taken (202), B says it heard from the "
        f"root {node.get('trustBundleAgeSeconds')} s ago under the default 24 hours, and B's "
        "gateway answers"
    )


def silence_b(run: Run, session_b: str, *, sabotage: bool = False) -> dict[str, Any]:
    """The root stopped, B restarted on a kept bundle 2 hours old."""
    if "control" in run.processes:
        run.stop_control()
    run.stop_agent("b")
    run.wait_released(["agent-b", "machine-b", "gateway", "driver"])
    kept = run.dirs["b"] / "trust_bundle.json"
    then = time.time() - SILENT_HOURS * 3600
    os.utime(kept, (then, then))
    run.start_agent("b", sabotage=sabotage)
    return run.node("b")


def step_frozen(run: Run, session_b: str) -> None:
    patched = run.call(
        "PATCH", "agent-b", "/v1/config", session_b, json={"maxTrustBundleAgeHours": LIMIT_HOURS}
    )
    if patched.json().get("applied") != ["maxTrustBundleAgeHours"]:
        raise Failed(f"B's limit: {patched.status_code} {patched.text[:300]}")
    node = silence_b(run, session_b)
    age = int(node.get("trustBundleAgeSeconds") or 0)
    if not (
        node.get("trustBundleFrozen") is True
        and node.get("trustBundleMaxAgeSeconds") == LIMIT_HOURS * 3600
        and age >= SILENT_HOURS * 3600
    ):
        raise Failed(f"B with the root silent says {_said(node)}")
    status = run.setting(session_b).get("status") or {}
    if status != {"level": "warning", "text": REFUSAL}:
        raise Failed(f"B's setting says {status}")
    run.ok(
        f"the root stopped and B restarted on a bundle kept {age} s ago: B says it refuses "
        f"changes from other machines under a {LIMIT_HOURS}-hour limit, and so does the setting"
    )

    check_refused(run)
    run.ok(f"C's stop request is refused with 403: {REFUSAL!r}")

    run.answered(session_b, "the root stopped")
    run.ok("with the root stopped and B refusing changes, a prompt through B's gateway is answered")

    by_root = run.stop_from(session_b)
    by_itself = run.stop_from(run.own_token("b", sub="gateway"))
    if (by_root.status_code, by_itself.status_code) != (202, 202):
        raise Failed(
            f"the root's session answered {by_root.status_code} ({by_root.text[:200]}) and B's "
            f"own token {by_itself.status_code} ({by_itself.text[:200]})"
        )
    run.ok("the root's own session, and a token B's key signs for itself, still stop it (202)")


def check_refused(run: Run) -> None:
    """Step 2's refusal, apart so the sabotage run can expect it to fail."""
    refused = run.stop_from(run.from_c())
    try:
        problem = refused.json().get("detail")
    except (ValueError, AttributeError):
        problem = None
    if refused.status_code != 403 or not isinstance(problem, dict):
        raise Failed(f"C's stop request past the limit: {refused.status_code} {refused.text[:300]}")
    if problem.get("title") != "Root not heard" or problem.get("detail") != REFUSAL:
        raise Failed(f"the refusal says {problem}")


def step_root_returns(run: Run, session_b: str) -> None:
    run.start_control()
    run.login("control")
    took = run.wait(
        lambda: run.node("b").get("trustBundleFrozen") is False,
        "B to hear from the root again",
        PULL_BOUND,
    )
    stopped = run.stop_from(run.from_c())
    if stopped.status_code != 202:
        raise Failed(
            f"C's stop request after the root returned: {stopped.status_code} {stopped.text[:300]}"
        )
    run.ok(
        f"the root started again; B heard from it {took:.0f} s later and takes C's stop "
        "request (202)"
    )


def step_sabotage(run: Run, session_b: str) -> None:
    node = silence_b(run, session_b, sabotage=True)
    if node.get("trustBundleFrozen") is not True:
        raise Failed(f"the sabotaged B with the root silent says {_said(node)}")
    try:
        check_refused(run)
    except Failed as caught:
        run.ok(f"sabotage caught: with the age check skipped, step 2's refusal fails ({caught})")
        return
    raise Failed("sabotage NOT caught: C's stop request was refused with the age check skipped")


def _said(node: dict[str, Any]) -> str:
    keys = ("trustBundleAgeSeconds", "trustBundleMaxAgeSeconds", "trustBundleFrozen")
    return json.dumps({k: node.get(k) for k in keys})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve-agent", type=Path)
    parser.add_argument("--serve-control", type=Path)
    parser.add_argument("--serve-stub", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--machine-port", type=int)
    parser.add_argument("--sabotage", action="store_true")
    args = parser.parse_args()
    if args.serve_agent:
        serve_agent(args.serve_agent, args.port, args.machine_port, args.sabotage)
        return 0
    if args.serve_control:
        serve_control(args.serve_control, args.port)
        return 0
    if args.serve_stub:
        serve_stub(args.port)
        return 0
    checks = 6 + (1 if args.sabotage else 0)
    with tempfile.TemporaryDirectory(prefix="ep-r46-", ignore_cleanup_errors=True) as tmp:
        run = Run(Path(tmp))
        try:
            session_b = install(run)
            step_in_time(run, session_b)
            step_frozen(run, session_b)
            step_root_returns(run, session_b)
            if args.sabotage:
                step_sabotage(run, session_b)
        except BaseException:
            run.dump_logs()
            raise
        finally:
            run.close()
    print(f"{len(run.passed)}/{checks} checks passed", flush=True)
    return 0 if len(run.passed) == checks else 1


if __name__ == "__main__":
    sys.exit(main())
