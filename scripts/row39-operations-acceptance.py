"""Row 39 acceptance: operations rights for a person who is not the owner.

`docs/design/rows/row-39.md` section 5. Real processes on loopback ports the
operating system hands out (never 8079-8083 or the live install's 8279-8283),
temporary state, and every `EUGENE_PLEXUS_*` variable of the calling shell
cleared before anything starts. No model, no GPU, no cloud service.

- A control root, its own process.
- Agent A through its own start path (row 2's harness: `agent.serve`), with
  a library, a gateway and an inference-driver over a stub engine that
  echoes, and one declared runtime `r39` that is never started.
- Agent B, a second machine, with nothing on it.

The owner gives Dana the Models power (`operateModels`) on machine A only.

1. Dana signs in with her own name and password, exchanges her session at the
   root for an operations token for A, stops `r39` on A and changes its
   auto-start, and re-scans A's library through A's proxy: each is taken,
   and A's operations log names Dana for each, the library's row included.
2. Dana's exchange for B is refused, naming B and her machines. Her token
   for A, sent to B, is refused (401). The hop to B through A's proxy is
   not run: on one host A's proxy refuses B's loopback address by design
   (row 3 runs it with --lan); the agent's unit test covers the strip toward
   another machine.
3. On A, Dana tries an engine install (403, naming Updates and restarts),
   `PATCH /v1/config` on the agent, the gateway and the library (403, only
   the owner), a client key (403), a provider key on the driver (refused),
   the logs (403, naming Updates and restarts) and the root's people list
   (403). Nothing changed.
4. The owner removes Dana's power: her token for A is refused at A within
   seconds (the root pushes the revocation; the bound is one bundle pull),
   and her session cannot exchange again. The power given back, a new
   session's token works until she signs out, and then is refused at A.
5. `--sabotage`: A is started again with `PATCH /v1/config` added to the
   operations table by mistake, in A's process only. Step 3's check of the
   agent's config must fail.

Needs the agent, control, gateway, library and inference-driver installed in
this interpreter (the Pinned integration job has them). Run:
`python scripts/row39-operations-acceptance.py [--sabotage]`.
"""

from __future__ import annotations

import argparse
import importlib
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
sys.path.insert(0, str(HERE.parent))
import acceptance_logs  # noqa: E402
MODEL = "r39-stub"
RUNTIME = "r39"
#: Ports this run never takes: the defaults and the live install's (+200).
NEVER = set(range(8079, 8085)) | set(range(8279, 8285))
#: A pushed revocation lands in seconds; a pull is once a minute.
REVOKE_BOUND = 100.0

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
    if sabotage:
        # Before the app is imported, so every route module takes these.
        from eugene_plexus_agent import dependencies, operations

        original = dependencies.require_operator_session
        operations.OPERATIONS_ROUTES[("PATCH", "/v1/config")] = (
            operations.MODELS,
            "change settings",
        )
        dependencies.require_operator_session = operations.operation(  # type: ignore[assignment]
            operations.MODELS, original
        )
        print(
            "row39: SABOTAGED: PATCH /v1/config is in the operations table", flush=True
        )
    agent = importlib.import_module("eugene_plexus_agent.__main__")
    from eugene_plexus_agent.settings import Settings

    settings = Settings(
        config_file=directory / "agent.yaml",
        bind_port=port,
        default_topology=False,
        machine_port=machine_port,
    )
    agent.serve(
        settings, unattended=True, should_stop=lambda: (directory / "stop").exists()
    )


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
        return {
            "object": "list",
            "data": [{"id": MODEL, "object": "model", "created": 0}],
        }

    @app.post("/v1/chat/completions")
    async def completions(body: dict = Body(...)) -> dict[str, Any]:  # noqa: B008
        said = str((body.get("messages") or [{}])[-1].get("content") or "")
        return {
            "id": "chatcmpl-r39",
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
    """Distinct loopback ports nothing holds now, below the range the OS hands out, so
    no agent's own pick and no client's source port can take one before its process
    binds it (specs#130)."""
    return dict(zip(names, acceptance_logs.quiet_ports(len(names)), strict=True))


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


class Run:
    def __init__(self, root: Path) -> None:
        self.root = root
        names = ["control", "stub", "agent-a", "machine-a", "agent-b", "machine-b"]
        names += ["gateway", "library", "driver"]
        self.ports = free_ports(names)
        self.dirs = {name: root / name for name in ("control", "a", "b")}
        for directory in self.dirs.values():
            directory.mkdir()
        self.passphrase = secrets.token_urlsafe(24)
        self.password = secrets.token_urlsafe(18)
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.logs: dict[str, Any] = {}
        self.passed: list[str] = []
        self.client = httpx.Client(trust_env=False, timeout=60)
        self.root_session = ""
        self.owner_a = ""
        self.dana_id = ""

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    # ---- processes -----------------------------------------------------------

    def spawn(self, name: str, argv: list[str], cwd: Path) -> None:
        log = (self.root / f"{name}.log").open("ab")
        self.logs[name] = log
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith("EUGENE_PLEXUS_")
        }
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
            lambda: self.call("GET", "control", "/healthz").status_code == 200,
            "the root",
            90,
        )

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
        self.spawn(
            f"agent-{a}", [*argv, *(["--sabotage"] if sabotage else [])], directory
        )
        self.wait(
            lambda: self.call("GET", f"agent-{a}", "/healthz").status_code == 200,
            f"agent {a}",
            90,
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
        for a in ("a", "b"):
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
        raise Failed(
            f"timed out after {timeout:.0f} s waiting for {label} (last: {last!r})"
        )

    def wait_settled(
        self,
        a: str,
        parts: list[str],
        since: int = 0,
        probed: tuple[str, ...] = ("library", "gateway"),
    ) -> None:
        """Until agent `a`'s parts are up and have stopped restarting (specs#132).

        The agent restarts every child it spawned after sign-in and again after
        enrollment, and a gateway drains first, so on a slow runner the restart lands
        seconds after the install returned. A check in that gap meets a gateway between
        two processes ("Server disconnected without sending a response"). The library and
        the gateway must answer through A's proxy, the agent's log (from byte `since`) must
        show each part's latest event as a start, and the count of spawns, exits and starts
        must not move for 2 s.
        """
        log = self.root / f"agent-{a}.log"
        seen: dict[str, Any] = {"events": None, "at": 0.0}

        def settled() -> bool:
            text = log.read_bytes()[since:].decode("utf-8", errors="replace")
            events = tuple(acceptance_logs.part_events(text, part) for part in parts)
            if events != seen["events"]:
                seen["events"], seen["at"] = events, time.perf_counter()
            if not all(acceptance_logs.part_is_up(text, part) for part in parts):
                return False
            for part in (p for p in parts if p in probed):
                if self.call("GET", f"agent-{a}", f"/api/proxy/{part}/healthz").status_code != 200:
                    return False
            return time.perf_counter() - seen["at"] >= 2.0

        self.wait(settled, f"A's {', '.join(parts)} to finish restarting", 90)

    def login(self, name: str) -> str:
        token: Any = None

        def signed_in() -> bool:
            nonlocal token
            got = self.call(
                "POST", name, "/v1/auth/login", json={"passphrase": self.passphrase}
            )
            token = got.json().get("sessionToken") if got.status_code == 200 else None
            return token is not None

        self.wait(signed_in, f"sign-in at {name}", 60)
        return str(token)

    def ok(self, message: str) -> None:
        self.passed.append(message)
        print(f"PASS {message}", flush=True)

    # ---- Dana ----------------------------------------------------------------

    def dana_signs_in(self) -> str:
        got = self.call(
            "POST",
            "control",
            "/v1/auth/administration/login",
            json={"name": "Dana", "password": self.password},
        )
        if got.status_code != 200:
            raise Failed(f"Dana's sign-in: {got.status_code} {got.text[:300]}")
        return str(got.json()["sessionToken"])

    def exchange(self, session: str, machine: str) -> httpx.Response:
        return self.call(
            "POST",
            "control",
            "/v1/auth/operations-token",
            session,
            json={"machine": machine},
        )

    def token_for_a(self, session: str) -> str:
        got = self.exchange(session, "agent-a")
        if got.status_code != 200:
            raise Failed(f"Dana's exchange for A: {got.status_code} {got.text[:300]}")
        body = got.json()
        if body.get("powers") != ["operate-models"] or body.get("machine") != "agent-a":
            raise Failed(f"Dana's token for A says {body}")
        return str(body["token"])

    def grant(self, grants: dict[str, Any]) -> None:
        got = self.call(
            "PUT",
            "control",
            f"/v1/people/{self.dana_id}/administration",
            self.root_session,
            json=grants,
        )
        if got.status_code != 200:
            raise Failed(
                f"the owner's grant {grants}: {got.status_code} {got.text[:300]}"
            )

    def stop_r39(self, token: str) -> httpx.Response:
        return self.call(
            "POST", "agent-a", f"/v1/runtimes/{RUNTIME}/stop", token, json={}
        )

    def log_of_a(self) -> list[dict[str, Any]]:
        got = self.call("GET", "agent-a", "/v1/node/operations-log", self.owner_a)
        if got.status_code != 200:
            raise Failed(f"A's operations log: {got.status_code} {got.text[:300]}")
        return list(got.json()["entries"])

    # ---- the install ----------------------------------------------------------

    def write_agent_yaml(self) -> None:
        a = self.dirs["a"]
        models = a / "models"
        models.mkdir()
        (models / "r39.gguf").write_bytes(b"GGUF")
        (a / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        (a / "library.yaml").write_text(
            yaml.safe_dump({"modelRoots": [str(models)]}), encoding="utf-8"
        )
        (a / "inference-driver.yaml").write_text(
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
            "a": [
                {
                    "name": "gateway",
                    "kind": "gateway",
                    "url": self.url("gateway"),
                    "spawn": {"configFile": str(a / "gateway.yaml")},
                },
                {
                    "name": "library",
                    "kind": "library",
                    "url": self.url("library"),
                    "spawn": {"configFile": str(a / "library.yaml")},
                },
                {
                    "name": "r39-driver",
                    "kind": "inference-driver",
                    "url": self.url("driver"),
                    "spawn": {"configFile": str(a / "inference-driver.yaml")},
                },
            ],
            "b": [],
        }
        for name, entries in components.items():
            (self.dirs[name] / "agent.yaml").write_text(
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

    def join(self, a: str) -> None:
        token = self.call(
            "POST",
            "control",
            "/v1/nodes/join-token",
            self.root_session,
            json={"grants": []},
        )
        if token.status_code not in (200, 201):
            raise Failed(f"join token for {a}: {token.status_code} {token.text}")
        initialized = self.call(
            "POST",
            f"agent-{a}",
            "/v1/auth/initialize",
            json={"passphrase": self.passphrase},
        )
        if initialized.status_code != 200:
            raise Failed(
                f"agent {a} initialize: {initialized.status_code} {initialized.text}"
            )
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


def install(run: Run) -> None:
    """The root, A and B joined; A's runtime declared; Dana made and given Models on A."""
    run.write_agent_yaml()
    run.spawn("stub", ["--serve-stub", "--port", str(run.ports["stub"])], run.root)
    run.wait(
        lambda: run.call("GET", "stub", "/health").status_code == 200, "the stub engine"
    )
    run.start_control()
    got = run.call(
        "POST", "control", "/v1/auth/initialize", json={"passphrase": run.passphrase}
    )
    if got.status_code != 204:
        raise Failed(f"root initialize answered {got.status_code}: {got.text}")
    run.root_session = run.login("control")
    for a in ("a", "b"):
        run.start_agent(a)
        run.join(a)
    run.owner_a = run.login("agent-a")
    declared = run.call(
        "POST",
        "agent-a",
        "/v1/runtimes",
        run.owner_a,
        json={
            "name": RUNTIME,
            "engine": "llama_cpp",
            "modelPath": str(run.dirs["a"] / "models" / "r39.gguf"),
            "autoStart": False,
            "autoDriver": False,
        },
    )
    if declared.status_code != 201:
        raise Failed(
            f"A declares {RUNTIME}: {declared.status_code} {declared.text[:400]}"
        )
    made = run.call(
        "POST",
        "control",
        "/v1/people",
        run.root_session,
        json={"name": "Dana", "password": run.password},
    )
    if made.status_code != 201:
        raise Failed(f"the owner makes Dana: {made.status_code} {made.text[:300]}")
    run.dana_id = str(made.json()["id"])
    run.grant({"operateModels": True, "operationsMachines": ["agent-a"]})
    run.wait_settled("a", ["library", "gateway", "r39-driver"])


def step_runs_a(run: Run) -> str:
    session = run.dana_signs_in()
    token = run.token_for_a(session)
    stopped = run.stop_r39(token)
    if stopped.status_code != 202:
        raise Failed(
            f"Dana stops {RUNTIME} on A: {stopped.status_code} {stopped.text[:300]}"
        )
    changed = run.call(
        "PUT",
        "agent-a",
        f"/v1/runtimes/{RUNTIME}/auto-start",
        token,
        json={"autoStart": True},
    )
    if changed.status_code != 200:
        raise Failed(
            f"Dana changes {RUNTIME}'s auto-start: {changed.status_code} {changed.text}"
        )
    scanned = run.call("POST", "agent-a", "/api/proxy/library/v1/scan", token, json={})
    if scanned.status_code not in (202, 409):
        raise Failed(
            f"Dana re-scans A's library: {scanned.status_code} {scanned.text[:300]}"
        )
    run.ok(
        f"Dana, signed in with her own account, stops {RUNTIME} on A (202), changes its "
        f"auto-start (200) and re-scans A's library through A's proxy ({scanned.status_code})"
    )

    wanted = {
        ("Dana", run.dana_id, "agent", "stop runtime", RUNTIME),
        ("Dana", run.dana_id, "agent", "change runtime auto-start", RUNTIME),
        ("Dana", run.dana_id, "library", "re-scan models", ""),
        ("Owner", "operator", "agent", "create runtime", RUNTIME),
    }
    seen: set[tuple[str, ...]] = set()

    def recorded() -> bool:
        seen.clear()
        seen.update(
            (e["name"], e["personId"], e["component"], e["action"], e["target"])
            for e in run.log_of_a()
        )
        return wanted <= seen

    try:
        run.wait(recorded, "A's operations log to name Dana for each change", 30)
    except Failed as exc:
        raise Failed(
            f"{exc}; missing {sorted(wanted - seen)}; it holds {sorted(seen)}"
        ) from None
    run.ok(
        "A's operations log names Dana for each change, the library's too, and the owner's"
    )
    return session


def step_scope(run: Run, session: str) -> None:
    refused = run.exchange(session, "agent-b")
    detail = _detail(refused)
    if (
        refused.status_code != 403
        or "agent-b" not in detail
        or "machines" not in detail
    ):
        raise Failed(
            f"Dana's exchange for B: {refused.status_code} {refused.text[:300]}"
        )
    run.ok(f"Dana's exchange for B is refused (403): {detail!r}")
    token = run.token_for_a(session)
    # The hop to B through A's proxy is not run here: on one host A's proxy
    # refuses B's loopback address by design (row 3 runs it with --lan), and
    # this harness's root is not a component A's proxy can name. The strip
    # toward another machine is the agent's unit test
    # (test_an_operations_token_for_another_machine_is_stripped).
    direct = run.call("GET", "agent-b", "/v1/runtimes", token)
    if direct.status_code != 401 or "node:agent-a" not in _detail(direct):
        raise Failed(
            f"Dana's token for A at B: {direct.status_code} ({direct.text[:400]})"
        )
    run.ok(
        f"Dana's token for A goes no further: B refuses it (401: {_detail(direct)!r})"
    )


def check_owner_routes(run: Run, token: str, session: str) -> None:
    """Step 3, apart so the sabotage run can expect it to fail."""
    tries: list[tuple[str, httpx.Response, tuple[int, ...], str]] = [
        (
            "engine install",
            run.call(
                "POST", "agent-a", "/v1/engines/llama_cpp/install", token, json={}
            ),
            (403,),
            "Updates and restarts",
        ),
        (
            "the agent's settings",
            run.call(
                "PATCH",
                "agent-a",
                "/v1/config",
                token,
                json={"maxTrustBundleAgeHours": 5},
            ),
            (403,),
            "Only the owner",
        ),
        (
            "the gateway's settings",
            run.call(
                "PATCH",
                "agent-a",
                "/api/proxy/gateway/v1/config",
                token,
                json={"logLevel": "DEBUG"},
            ),
            (403,),
            "Only the owner",
        ),
        (
            "the library's settings",
            run.call(
                "PATCH",
                "agent-a",
                "/api/proxy/library/v1/config",
                token,
                json={"logLevel": "DEBUG"},
            ),
            (403,),
            "Only the owner",
        ),
        (
            "a client key",
            run.call(
                "POST",
                "agent-a",
                "/v1/auth/client-keys",
                token,
                json={"name": "dana-key"},
            ),
            (403,),
            "Only the owner",
        ),
        (
            "a provider key",
            run.call(
                "PATCH",
                "agent-a",
                "/api/proxy/r39-driver/v1/config",
                token,
                json={"apiKey": "sk-r39-not-a-key"},
            ),
            (401, 403),
            "",
        ),
        (
            "a runtime that reads a file outside the Library",
            run.call(
                "POST",
                "agent-a",
                "/v1/runtimes",
                token,
                json={
                    "name": "r39-template",
                    "engine": "llama_cpp",
                    "modelPath": str(run.dirs["a"] / "models" / "r39.gguf"),
                    "autoStart": False,
                    "autoDriver": False,
                    "flags": {"chatTemplateFile": str(run.dirs["a"] / "node.yaml")},
                },
            ),
            (403,),
            "(flags.chatTemplateFile)",
        ),
        (
            "the logs",
            run.call("GET", "agent-a", "/v1/logs", token),
            (403,),
            "Updates and restarts",
        ),
        (
            "the root's people",
            run.call("GET", "control", "/v1/people", session),
            (403,),
            "not people and groups",
        ),
    ]
    wrong = [
        f"{what}: {got.status_code} {got.text[:400]}"
        for what, got, codes, says in tries
        if got.status_code not in codes or says not in _detail(got)
    ]
    if wrong:
        raise Failed("Dana reached what is not hers: " + "; ".join(wrong))


def step_owners(run: Run, session: str) -> None:
    token = run.token_for_a(session)
    check_owner_routes(run, token, session)
    config = run.call("GET", "agent-a", "/v1/config", run.owner_a).json()
    if config.get("maxTrustBundleAgeHours") == 5:
        raise Failed("A's settings changed under Dana's token")
    run.ok(
        "on A Dana is refused an engine install (403, Updates and restarts), the agent's, "
        "gateway's and library's settings and a client key (403, only the owner), a provider "
        "key on the driver, the logs (403), and the root's people (403); nothing changed"
    )


def step_revoked(run: Run, session: str) -> None:
    token = run.token_for_a(session)
    if run.stop_r39(token).status_code != 202:
        raise Failed(
            "Dana's token for A did not work before the owner removed her power"
        )
    run.grant({})
    took = run.wait(
        lambda: run.stop_r39(token).status_code == 401,
        "A to refuse Dana's token",
        REVOKE_BOUND,
    )
    said = _detail(run.stop_r39(token))
    if "signed out" not in said:
        raise Failed(f"A refuses Dana's token saying {said!r}")
    again = run.exchange(session, "agent-a")
    if again.status_code != 401:
        raise Failed(
            f"Dana's old session exchanges again: {again.status_code} {again.text[:200]}"
        )
    run.ok(
        f"the owner removes Dana's power: A refuses her token {took:.1f} s later ({said!r}) "
        "and her session exchanges no more (401)"
    )
    run.grant({"operateModels": True, "operationsMachines": ["agent-a"]})
    fresh = run.dana_signs_in()
    token = run.token_for_a(fresh)
    if run.stop_r39(token).status_code != 202:
        raise Failed("Dana's new token for A did not work")
    out = run.call("DELETE", "control", "/v1/auth/administration/session", fresh)
    if out.status_code != 204:
        raise Failed(f"Dana's sign-out: {out.status_code} {out.text[:200]}")
    took = run.wait(
        lambda: run.stop_r39(token).status_code == 401,
        "A to refuse a token from a signed-out session",
        REVOKE_BOUND,
    )
    run.ok(f"Dana signs out: A refuses the token from that session {took:.1f} s later")


def step_sabotage(run: Run) -> None:
    run.stop_agent("a")
    run.wait_released(["agent-a", "machine-a", "gateway", "library", "driver"])
    began = (run.root / "agent-a.log").stat().st_size
    run.start_agent("a", sabotage=True)
    # Review S2: the sabotaged A answers for its library and gateway as well
    # before step 3 runs, so a refusal there is the gate's and not a gap.
    run.wait_settled("a", ["library", "gateway"], since=began)
    run.grant({"operateModels": True, "operationsMachines": ["agent-a"]})
    session = run.dana_signs_in()
    token = run.token_for_a(session)
    try:
        check_owner_routes(run, token, session)
    except Failed as caught:
        # Review S2: only the sabotaged check counts; any other failure is
        # a failure of the run.
        said = str(caught)
        if (
            "reached what is not hers: the agent's settings:" not in said
            or "; " in said.split("the agent's settings:", 1)[1].split("}", 1)[-1]
        ):
            raise
        run.ok(
            f"sabotage caught: with PATCH /v1/config in the table, step 3 fails ({caught})"
        )
        return
    raise Failed("sabotage NOT caught: step 3 held with PATCH /v1/config in the table")


def _detail(got: httpx.Response) -> str:
    try:
        body = got.json()
    except ValueError:
        return got.text[:200]
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("detail") or detail.get("title") or "")
    return str(detail or "")


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
    checks = 7 + (1 if args.sabotage else 0)
    with tempfile.TemporaryDirectory(
        prefix="ep-r39-", ignore_cleanup_errors=True
    ) as tmp:
        run = Run(Path(tmp))
        try:
            install(run)
            session = step_runs_a(run)
            step_scope(run, session)
            step_owners(run, session)
            step_revoked(run, session)
            if args.sabotage:
                step_sabotage(run)
        except BaseException:
            run.dump_logs()
            raise
        finally:
            run.close()
    print(f"{len(run.passed)}/{checks} checks passed", flush=True)
    return 0 if len(run.passed) == checks else 1


if __name__ == "__main__":
    sys.exit(main())
