r"""Row 35 acceptance: pause a machine's models, from its tray icon or the console, and keep serving.

Design: `docs/design/rows/row-35.md` section 5. Two parts, each with
real processes on ports the operating system hands out (never 8079-8083),
temporary state, and every `EUGENE_PLEXUS_*` variable of the calling shell
cleared before anything starts.

**The console path** (the default; every OS, CI runs it on Linux in the
pinned integration): a control root, an enrolled agent with a stand-in
engine behind a stub driver, and a gateway.

1. A client key and a gateway token are refused on `POST /v1/node/pause`,
   and the model still answers.
2. The operator's session pauses: the engine's process ends, the runtime
   reads `paused`, and `GET /v1/node` shows the pause.
3. A chat for the model through the gateway is refused, and the body names
   the pause; so is a Start.
4. The agent restarts: the engine stays stopped, still `paused`.
5. Resume with a client key and with a gateway token is refused. With the
   operator's session the engine runs again, and the chat is answered.
6. `--sabotage`: the agent runs with the pause's start guard removed, in its
   own process only. Step 3's refusal check must fail.

**The tray's channel on a real service** (`--windows-service`; Windows, an
elevated disposable runner, `EP_ROW35_SERVICE=1`): a service with a unique
name, a disposable venv and config, a stand-in engine (a Kev interpreter
whose `kev.serve` only answers `/v1/models`), and two standard local
accounts.

1. `eprow35a` gets start and stop with `sc sdset`, as `install.ps1`'s
   `Grant-ServiceControl` does; `eprow35b` gets nothing.
2. As `eprow35a`, unelevated (`IsUserAnAdmin() == 0` first, R2.6's check-6
   lesson), the tray's own call pauses: the engine's process ends and
   `GET /v1/node` shows the pause, `by: tray`. A Start is refused, naming it.
3. As `eprow35b` the same call gets access denied, and nothing changes.
4. `\\127.0.0.1\pipe\...`, the remote path, is refused, where a pipe of the
   script's own answers on that path.
5. The service restarts: the engine stays stopped.
6. `eprow35a`'s grant is removed with `sc sdset` while the pipe still
   admits her: the next connection is refused by the agent's own check.
   `--sabotage` replaces that check (`tray_pipe.may_stop`) with one that
   admits everyone, restores it from a copy afterwards, and expects this
   step to fail.
7. A program of `eprow35b`'s takes the pipe's name before the service
   starts: the agent reports `taken`, and the tray's call refuses that
   program and sends it nothing.
8. Resume with a client key and with a gateway token is refused; with the
   operator's session the engine runs again.

    python specs/scripts/row35-tray-pause-acceptance.py [--sabotage]
    EP_ROW35_SERVICE=1 python specs/scripts/row35-tray-pause-acceptance.py --windows-service [--sabotage]

The console path needs control, the agent and the gateway installed in this
interpreter (the Pinned integration job has them); the service path needs the
agent with its `service` and `tray` extras.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import yaml

DEFAULT_PORTS = range(8079, 8084)


class Failed(AssertionError):
    pass


def ok(message: str) -> None:
    print(f"PASS {message}", flush=True)


def isolated_env(root: Path, source: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v
        for k, v in (os.environ if source is None else source).items()
        if not k.upper().startswith("EUGENE_PLEXUS_")
    }
    env.update(
        TEMP=str(root),
        TMP=str(root),
        TMPDIR=str(root),
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        PYTHONUNBUFFERED="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


def free_ports(count: int) -> list[int]:
    sockets = []
    try:
        while len(sockets) < count:
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            if sock.getsockname()[1] in DEFAULT_PORTS:
                sock.close()
            else:
                sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def wait(read: Any, label: str, seconds: float = 45) -> Any:
    deadline = time.perf_counter() + seconds
    last: Any = None
    while time.perf_counter() < deadline:
        try:
            if answer := read():
                return answer
        except (httpx.HTTPError, OSError, KeyError, ValueError, IndexError, TypeError) as exc:
            last = exc
        time.sleep(0.2)
    raise Failed(f"timed out: {label}: {last}")


def answers(port: int) -> bool:
    """Whether anything accepts a connection on this loopback port now."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def detail_of(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, dict):
        return str(detail.get("detail") or detail)
    return str(detail if detail is not None else body)


# --------------------------------------------------------------------------- #
# The console path: real control, agent and gateway; a stand-in engine
# --------------------------------------------------------------------------- #


def child_settings(root: Path, kind: str, agent_url: str) -> dict[str, Any]:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    identity = NodeIdentityStore(root / "node.yaml")
    identity.load()
    trust = NodeTrust(identity, root / BUNDLE_FILE)
    trust.load()
    token, _ = trust.mint_service(sub=kind, audience=trust.recipient)
    result = dict(
        trust_bundle_file=str(trust.bundle_path),
        trust_authority=trust.authority,
        auth_recipient=trust.recipient,
        service_token=token,
    )
    if kind == "gateway":
        result["agent_url"] = agent_url
    return result


def serve(kind: str, root: Path, port: int, model: str | None) -> None:
    assert port not in DEFAULT_PORTS
    if kind == "engine":
        assert model is not None

        class Engine(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass

            def reply(self, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self.reply(
                    {"n_ctx": 128, "total_slots": 1} if self.path == "/props" else {"status": "ok"}
                )

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers["Content-Length"]))
                self.reply(
                    {
                        "content": "still serving",
                        "modelId": "fixture",
                        "backend": "openai_compat_http",
                        "finishReason": "stop",
                    }
                )

        ThreadingHTTPServer(("127.0.0.1", port), Engine).serve_forever()
        return

    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(config_file=root / "control.yaml", state_dir=root / "control-state")
        )
    elif kind == "agent":
        from eugene_plexus_agent._generated.models import EngineKind, Origin
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.engines import ADAPTERS
        from eugene_plexus_agent.engines.base import DiscoveredBinary
        from eugene_plexus_agent.engines.llama_cpp import LlamaCppAdapter
        from eugene_plexus_agent.settings import Settings

        class StandIn(LlamaCppAdapter):
            def discover(self, *, configured: Any = None) -> DiscoveredBinary:
                return DiscoveredBinary(Path(sys.executable), Origin.configured, "fixture")

            def build_argv(self, spec: Any, binary: Any, port: int) -> list[str]:
                return [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--serve",
                    "engine",
                    "--directory",
                    str(root),
                    "--port",
                    str(port),
                    "--model",
                    spec.modelPath,
                ]

        ADAPTERS[EngineKind.llama_cpp] = StandIn()
        if os.environ.get("ROW35_SABOTAGE") == "guard":
            # The sabotage: the pause's start guard removed, in this process only.
            from eugene_plexus_agent import pause

            pause.refusal = lambda app: None  # type: ignore[assignment]
            print("SABOTAGE: the pause's start guard is removed", flush=True)
        os.environ["EUGENE_PLEXUS_AGENT_ENGINE_ROOT"] = str(root / "engines")
        app = create_app(
            settings=Settings(
                config_file=root / "agent.yaml",
                bind_port=port,
                machine_port=free_ports(1)[0],
                default_topology=False,
            )
        )
    else:
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings

        child = json.loads((root / "gateway-child.json").read_text(encoding="utf-8"))
        app = create_app(
            Settings(config_file=root / "gateway.yaml", metrics_file=root / "metrics.sqlite3", **child)
        )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
    )

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (root / f"{kind}.stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task

    asyncio.run(run())


def write_model(path: Path) -> None:
    def string(value: str) -> bytes:
        data = value.encode()
        return struct.pack("<Q", len(data)) + data

    kv: dict[str, Any] = {
        "general.architecture": "llama",
        "general.name": "fixture",
        "llama.context_length": 128,
    }
    data = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv))
    for key, value in kv.items():
        data += string(key)
        data += (
            struct.pack("<I", 8) + string(value)
            if isinstance(value, str)
            else struct.pack("<II", 4, value)
        )
    path.write_bytes(data)


def console(root: Path, *, sabotage: bool = False) -> None:
    control_port, agent_port, gateway_port, engine_port, driver_port = free_ports(5)
    urls = {
        name: f"http://127.0.0.1:{port}"
        for name, port in (
            ("control", control_port),
            ("agent", agent_port),
            ("gateway", gateway_port),
            ("engine", engine_port),
        )
    }
    model = root / "fixture.gguf"
    write_model(model)
    (root / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "advertiseUrl": urls["agent"],
                "securityMode": "prompt_on_startup",
                "components": [
                    {"name": "gateway", "kind": "gateway", "url": urls["gateway"]},
                    {
                        "name": "driver",
                        "kind": "inference-driver",
                        "url": f"http://127.0.0.1:{driver_port}",
                    },
                ],
                "runtimes": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "gateway.yaml").write_text(
        yaml.safe_dump(
            {
                "profileCacheSeconds": 1,
                "routingRefreshSeconds": 1,
                "metricsEnabled": False,
                "idleCheckSeconds": 3600,
            }
        ),
        encoding="utf-8",
    )
    (root / "control.yaml").write_text("{}\n", encoding="utf-8")

    class Driver(BaseHTTPRequestHandler):
        """A stub inference-driver in front of the stand-in engine."""

        def log_message(self, *_: Any) -> None:
            pass

        def reply(self, data: Any, status: int = 200) -> None:
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self.reply(
                {
                    "backend": "openai_compat_http",
                    "runtime": "fixture",
                    "models": [
                        {
                            "id": "fixture",
                            "surfaces": ["chat"],
                            "capabilities": {"supportedSettings": ["temperature", "maxTokens"]},
                        }
                    ],
                }
            )

        def do_POST(self) -> None:
            data = self.rfile.read(int(self.headers["Content-Length"]))
            try:
                response = httpx.post(urls["engine"] + "/generate", content=data, trust_env=False)
                self.reply(response.json(), response.status_code)
            except httpx.HTTPError as exc:
                self.reply({"error": str(exc)}, 502)

    driver = ThreadingHTTPServer(("127.0.0.1", driver_port), Driver)
    threading.Thread(target=driver.serve_forever, daemon=True).start()
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs: list[Any] = []
    client = httpx.Client(timeout=30, trust_env=False)

    def call(name: str, method: str, path: str, token: str | None = None, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, urls[name] + path, headers=headers, **kwargs)

    def start(kind: str, port: int) -> None:
        (root / f"{kind}.stop").unlink(missing_ok=True)
        log = (root / f"{kind}.log").open("ab")
        logs.append(log)
        env = isolated_env(root)
        if kind == "agent" and sabotage:
            env["ROW35_SABOTAGE"] = "guard"
        processes[kind] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                kind,
                "--directory",
                str(root),
                "--port",
                str(port),
            ],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(kind, "GET", "/healthz").status_code == 200, f"{kind} ready")

    def stop(kind: str) -> None:
        (root / f"{kind}.stop").touch()
        processes[kind].wait(timeout=30)

    try:
        start("control", control_port)
        passphrase = secrets.token_urlsafe(24)
        response = call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        assert response.status_code == 204, response.text
        root_token = call(
            "control", "POST", "/v1/auth/login", json={"passphrase": passphrase}
        ).json()["sessionToken"]
        start("agent", agent_port)
        response = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        token = response.json()["sessionToken"]
        join = call(
            "control", "POST", "/v1/nodes/join-token", root_token, json={"grants": ["gateway"]}
        ).json()["token"]
        enrolled = call(
            "agent",
            "POST",
            "/v1/node/enroll",
            token,
            json={"controlUrl": urls["control"], "token": join, "name": "pause-node"},
        )
        assert enrolled.status_code == 200, enrolled.text

        def login() -> str:
            return str(
                call("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()[
                    "sessionToken"
                ]
            )

        token = login()
        (root / "gateway-child.json").write_text(
            json.dumps(child_settings(root, "gateway", urls["agent"])), encoding="utf-8"
        )
        start("gateway", gateway_port)
        created = call(
            "agent",
            "POST",
            "/v1/runtimes",
            token,
            json={
                "name": "fixture",
                "engine": "llama_cpp",
                "modelPath": str(model),
                "modelAlias": "fixture",
                "port": engine_port,
                "autoDriver": False,
                "startOnDemand": True,
                "flags": {"gpuLayers": 0, "contextSize": 128},
            },
        )
        assert created.status_code in (200, 201), created.text

        def runtime() -> dict[str, Any]:
            return dict(call("agent", "GET", "/v1/runtimes/fixture", token).json())

        def ready() -> dict[str, Any] | None:
            view = runtime()
            return view if view.get("status") == "ready" else None

        def chat() -> httpx.Response:
            return call(
                "gateway",
                "POST",
                "/v1/chat/completions",
                token,
                json={"model": "fixture", "messages": [{"role": "user", "content": "hello"}]},
            )

        wait(ready, "the stand-in engine ready")
        wait(lambda: chat().status_code == 200, "the gateway answers the model")

        # 1. Only an operator's session pauses.
        made = call("agent", "POST", "/v1/auth/client-keys", token, json={"name": "row35"})
        assert made.status_code in (200, 201), made.text
        key = made.json()["token"]
        gateway_token = child_settings(root, "gateway", urls["agent"])["service_token"]
        for who, credential in (("a client key", key), ("a gateway token", gateway_token)):
            refused = call("agent", "POST", "/v1/node/pause", credential)
            if refused.status_code not in (401, 403):
                raise Failed(f"{who} paused the models: {refused.status_code} {refused.text}")
        if not ready() or not answers(engine_port):
            raise Failed("a refused pause stopped the engine")
        if call("agent", "GET", "/v1/node", token).json()["pause"]["paused"] is not False:
            raise Failed("a refused pause left the machine paused")
        ok("a client key and a gateway token are refused on Pause, and the model still answers")

        # 2. The operator pauses.
        paused = call("agent", "POST", "/v1/node/pause", token)
        assert paused.status_code == 200, paused.text
        results = {r["name"]: r["state"] for r in paused.json()["results"]}
        assert results == {"fixture": "stopped"}, paused.text
        wait(lambda: not answers(engine_port), "the engine's process ends", 30)
        view = runtime()
        assert view["status"] == "stopped" and view["stopReason"] == "paused", view
        node = call("agent", "GET", "/v1/node", token).json()["pause"]
        assert node["paused"] is True and node["by"] == "console", node
        assert node["runtimes"] == ["fixture"], node
        ok("the operator's Pause stops the engine; the runtime reads paused and the machine shows it")

        # 3. Nothing starts it: a chat through the gateway, and a Start.
        check_refused(chat, call, token, engine_port)
        ok("a chat through the gateway is refused and names the pause; so is a Start")

        # 4. A restart leaves it stopped.
        stop("agent")
        start("agent", agent_port)
        token = login()
        time.sleep(5)
        view = runtime()
        assert view["status"] == "stopped" and view["stopReason"] == "paused", view
        if answers(engine_port):
            raise Failed("the agent's restart started the paused engine")
        node = call("agent", "GET", "/v1/node", token).json()["pause"]
        assert node["paused"] is True and node["runtimes"] == ["fixture"], node
        ok("after the agent restarts the engine stays stopped, still paused")

        # 5. Resume: only the operator's session.
        for who, credential in (("a client key", key), ("a gateway token", gateway_token)):
            refused = call("agent", "POST", "/v1/node/resume", credential)
            if refused.status_code not in (401, 403):
                raise Failed(f"{who} resumed the models: {refused.status_code} {refused.text}")
        if answers(engine_port):
            raise Failed("a refused resume started the engine")
        resumed = call("agent", "POST", "/v1/node/resume", token)
        assert resumed.status_code == 200, resumed.text
        assert [(r["name"], r["state"]) for r in resumed.json()["results"]] == [
            ("fixture", "started")
        ], resumed.text
        assert resumed.json()["pause"]["paused"] is False, resumed.text
        wait(ready, "the engine runs again after Resume")
        wait(lambda: chat().status_code == 200, "the gateway answers the model again")
        ok("Resume with a client key or a gateway token is refused; the operator's starts the engine")
    except BaseException:
        for log in logs:
            log.flush()
        if not sabotage:
            for path in root.glob("*.log"):
                text = path.read_text(encoding="utf-8", errors="replace")[-5000:]
                print(f"{path.name}:\n{text}", flush=True)
        raise
    finally:
        for kind in reversed(list(processes)):
            if processes[kind].poll() is None:
                try:
                    stop(kind)
                except (subprocess.TimeoutExpired, OSError):
                    processes[kind].kill()
                    processes[kind].wait(timeout=10)
        driver.shutdown()
        driver.server_close()
        client.close()
        for log in logs:
            log.close()


def check_refused(chat: Any, call: Any, token: str, engine_port: int) -> None:
    """Step 3, apart so the sabotage run can expect it to fail."""
    refused = chat()
    if refused.status_code == 200:
        raise Failed("a chat was answered while the models were paused")
    if "paused" not in refused.text or "Resume" not in refused.text:
        raise Failed(f"the chat's refusal does not name the pause: {refused.text}")
    started = call("agent", "POST", "/v1/runtimes/fixture/start", token)
    if started.status_code != 409 or "paused" not in detail_of(started):
        raise Failed(f"a Start while paused answered {started.status_code} {started.text}")
    time.sleep(2)
    if answers(engine_port):
        raise Failed("the engine started while the models were paused")


# --------------------------------------------------------------------------- #
# The tray's channel on a real Windows service
# --------------------------------------------------------------------------- #

KEV_SERVE = '''"""A stand-in for kev.serve: it answers /v1/models, and nothing else."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

parser = argparse.ArgumentParser()
parser.add_argument("--run")
parser.add_argument("--port", type=int)
parser.add_argument("--fallback")
args, _ = parser.parse_known_args()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"id": "standin"}]}).encode()
        self.send_response(200 if self.path.startswith("/v1/models") else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
'''

#: Run as another account: its own unelevated sign-in, the tray's own call.
AS_USER = '''import contextlib, ctypes, io, json, sys
out = sys.argv[1]
result = {"is_admin": bool(ctypes.windll.shell32.IsUserAnAdmin())}
try:
    import win32api, win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    result["sid"] = win32security.ConvertSidToStringSid(user)
    if result["is_admin"]:
        raise SystemExit("an administrator proves nothing here")
    from eugene_plexus_agent import tray
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        result["exit"] = tray.main(sys.argv[2:])
    result["answer"] = json.loads(printed.getvalue() or "null")
except BaseException as exc:
    result["error"] = repr(exc)
with open(out, "w", encoding="utf-8") as fh:
    json.dump(result, fh)
'''

#: Takes the pipe's name first, with a DACL anyone may open, as a program
#: luring the tray would; writes down anything a client sends it.
SQUATTER = '''import os, sys, threading, win32file, win32pipe, win32security
name, ready, heard = sys.argv[1], sys.argv[2], sys.argv[3]
attributes = win32security.SECURITY_ATTRIBUTES()
attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
    "D:(A;;GA;;;WD)", win32security.SDDL_REVISION_1)
held = []
def listen(handle):
    try:
        while True:
            _, data = win32file.ReadFile(handle, 4096)
            with open(heard, "ab") as fh:
                fh.write(data)
    except Exception:
        pass
while len(held) < 200:
    held.append(win32pipe.CreateNamedPipe(name, 3, 0, 255, 4096, 4096, 0, attributes))
    if len(held) == 1:
        with open(ready, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    try:
        win32pipe.ConnectNamedPipe(held[-1], None)
    except Exception:
        pass
    threading.Thread(target=listen, args=(held[-1],), daemon=True).start()
'''


def _sc(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sc.exe", *args], capture_output=True, text=True, timeout=60)


def _icacls(path: Path, *args: str) -> None:
    done = subprocess.run(
        ["icacls", str(path), *args], capture_output=True, text=True, timeout=300
    )
    if done.returncode != 0:
        raise Failed(f"icacls {path} {' '.join(args)}: {done.stdout} {done.stderr}")


def _grant_sddl(sid: str | None) -> str:
    """`install.ps1`'s Grant-ServiceControl descriptor, with SID's ACE or none."""
    default = (
        "D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)"
        "(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)"
    )
    mine = f"(A;;CCLCSWRPWPDTLOCRRC;;;{sid})" if sid else ""
    return default + mine + "S:(AU;FA;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;WD)"


def _run_as(user: str, password: str, argv: list[str], cwd: Path, env: dict[str, str], *,
            wait_seconds: float | None = 240) -> Any:
    """Start ARGV as USER, signed in on its own and unelevated
    (CreateProcessWithLogonW). Returns the exit code, or with
    `wait_seconds=None` the process handle, unwaited."""
    import ctypes
    from ctypes import wintypes

    class StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class ProcessInformation(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = advapi.CreateProcessWithLogonW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(StartupInfo),
        ctypes.POINTER(ProcessInformation),
    ]
    create.restype = wintypes.BOOL
    command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    block = "".join(f"{k}={v}\0" for k, v in sorted(env.items())) + "\0"
    environment = ctypes.create_unicode_buffer(block, len(block) + 1)
    startup = StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    started = ProcessInformation()
    logon_with_profile, no_window, unicode_environment = 0x1, 0x08000000, 0x400
    if not create(
        user,
        ".",
        password,
        logon_with_profile,
        None,
        command,
        no_window | unicode_environment,
        ctypes.cast(environment, ctypes.c_void_p),
        str(cwd),
        ctypes.byref(startup),
        ctypes.byref(started),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.CloseHandle(started.hThread)
    if wait_seconds is None:
        return started
    if kernel.WaitForSingleObject(started.hProcess, int(wait_seconds * 1000)) != 0:
        kernel.TerminateProcess(started.hProcess, 1)
        kernel.CloseHandle(started.hProcess)
        raise Failed(f"{user}'s process did not finish in {wait_seconds:.0f} s: {argv}")
    code = wintypes.DWORD()
    kernel.GetExitCodeProcess(started.hProcess, ctypes.byref(code))
    kernel.CloseHandle(started.hProcess)
    return int(code.value)


def windows_service(*, sabotage: bool) -> None:  # noqa: C901 - one scenario, in order
    import ctypes

    import win32security
    import win32service
    import win32serviceutil
    import winreg

    if os.environ.get("EP_ROW35_SERVICE") != "1" or not ctypes.windll.shell32.IsUserAnAdmin():
        raise SystemExit("Set EP_ROW35_SERVICE=1 on an elevated, disposable Windows runner")

    import eugene_plexus_agent
    from eugene_plexus_agent import tray_pipe

    name = "EPRow35" + uuid.uuid4().hex[:10]
    tag = uuid.uuid4().hex[:8]
    users = {"a": f"eprow35a{tag[:4]}", "b": f"eprow35b{tag[:4]}"}
    passwords = {k: "Ep#" + secrets.token_urlsafe(18) for k in users}
    sids: dict[str, str] = {}
    root = Path(os.environ.get("SystemDrive", "C:") + "\\") / f"ep-row35-{tag}"
    port, machine_port, engine_port = free_ports(3)
    service_dir = root / "service"
    results = root / "results"
    venv = root / "venv"
    standin = root / "standin"
    checkpoint = root / "checkpoint"
    tray_source = Path(tray_pipe.__file__)
    sabotage_copy = root / "tray_pipe.py.orig"
    installed = False
    squatter: Any = None
    client = httpx.Client(timeout=30, trust_env=False)
    base = f"http://127.0.0.1:{port}"
    passphrase = secrets.token_urlsafe(24)

    def run(*command: str) -> None:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            raise Failed(f"{' '.join(command)}: {done.stdout} {done.stderr}")

    def service_state() -> int:
        return int(win32serviceutil.QueryServiceStatus(name)[1])

    def start_service() -> None:
        win32serviceutil.StartService(name)
        wait(lambda: client.get(base + "/healthz").status_code == 200, "the service answers", 90)

    def stop_service() -> None:
        if service_state() != win32service.SERVICE_STOPPED:
            win32serviceutil.StopService(name)
            win32serviceutil.WaitForServiceStatus(name, win32service.SERVICE_STOPPED, 90)

    def login() -> str:
        response = client.post(base + "/v1/auth/login", json={"passphrase": passphrase})
        if response.status_code != 200:
            raise Failed(f"login: {response.status_code} {response.text}")
        return str(response.json()["sessionToken"])

    def get(path: str, token: str) -> Any:
        response = client.get(base + path, headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 200:
            raise Failed(f"GET {path}: {response.status_code} {response.text}")
        return response.json()

    def post(path: str, token: str, **kwargs: Any) -> httpx.Response:
        return client.post(base + path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

    def user_env() -> dict[str, str]:
        system = os.environ.get("SystemRoot", r"C:\Windows")
        return {
            "SystemRoot": system,
            "windir": system,
            "SystemDrive": os.environ.get("SystemDrive", "C:"),
            "PATH": f"{system}\\System32;{system}",
            "TEMP": str(results),
            "TMP": str(results),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }

    def tray_as(who: str, verb: str) -> dict[str, Any]:
        """The tray's own call (`eugene-plexus-tray --call VERB`), as WHO."""
        out = results / f"{who}-{verb}-{uuid.uuid4().hex[:6]}.json"
        code = _run_as(
            users[who],
            passwords[who],
            [
                str(venv / "Scripts" / "python.exe"),
                str(root / "as_user.py"),
                str(out),
                "--port",
                str(port),
                "--service",
                name,
                "--call",
                verb,
            ],
            results,
            user_env(),
        )
        if not out.exists():
            raise Failed(f"{users[who]}'s call wrote nothing (exit {code})")
        result = json.loads(out.read_text(encoding="utf-8"))
        if result.get("is_admin") is not False:
            raise Failed(f"{users[who]}'s process is elevated or unread: {result}")
        if result.get("sid") != sids[who]:
            raise Failed(f"the call ran as {result.get('sid')}, not {users[who]}: {result}")
        if "error" in result:
            raise Failed(f"{users[who]}'s call failed: {result['error']}")
        return dict(result["answer"] or {})

    def pause_of(token: str) -> dict[str, Any]:
        return dict(get("/v1/node", token)["pause"])

    def runtime(token: str) -> dict[str, Any]:
        return dict(get("/v1/runtimes/standin", token))

    try:
        # --- 1. two accounts, a disposable install, a service of its own -------
        for key, user in users.items():
            run("net", "user", user, passwords[key], "/add", "/y")
            sids[key] = win32security.ConvertSidToStringSid(
                win32security.LookupAccountName(None, user)[0]
            )
        root.mkdir()
        _icacls(
            root,
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
            f"*{sids['a']}:(OI)(CI)RX",
            f"*{sids['b']}:(OI)(CI)RX",
        )
        service_dir.mkdir()
        _icacls(
            service_dir, "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"
        )
        results.mkdir()
        _icacls(results, "/grant", f"*{sids['a']}:(OI)(CI)M", f"*{sids['b']}:(OI)(CI)M")
        # The accounts read the agent's code, as the tray does from the install.
        package = Path(eugene_plexus_agent.__file__).resolve().parent
        _icacls(
            package, "/grant", f"*{sids['a']}:(OI)(CI)RX", f"*{sids['b']}:(OI)(CI)RX", "/T", "/Q"
        )
        run(sys.executable, "-m", "venv", "--system-site-packages", "--without-pip", str(venv))
        run(
            str(venv / "Scripts" / "python.exe"),
            "-c",
            "from eugene_plexus_agent.winservice import _prepare_service_host; _prepare_service_host()",
        )
        run(sys.executable, "-m", "venv", "--without-pip", str(standin))
        kev = standin / "Lib" / "site-packages" / "kev"
        kev.mkdir(parents=True)
        (kev / "__init__.py").write_text("", encoding="utf-8")
        (kev / "serve.py").write_text(KEV_SERVE, encoding="utf-8")
        checkpoint.mkdir()
        (checkpoint / "adapter.json").write_text("{}", encoding="utf-8")
        (root / "as_user.py").write_text(AS_USER, encoding="utf-8")
        (root / "squatter.py").write_text(SQUATTER, encoding="utf-8")
        (service_dir / "agent.yaml").write_text(
            json.dumps(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "kevPython": str(standin / "Scripts" / "python.exe"),
                    "components": [],
                    "runtimes": [
                        {
                            "name": "standin",
                            "engine": "kev",
                            "modelPath": str(checkpoint),
                            "modelAlias": "standin",
                            "host": "127.0.0.1",
                            "port": engine_port,
                            "autoDriver": False,
                            "autoStart": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        win32serviceutil.InstallService(
            "eugene_plexus_agent.winservice.EugenePlexusAgentService",
            name,
            name,
            exeName=str(venv / "Scripts" / "pythonservice.exe"),
        )
        installed = True
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SYSTEM\CurrentControlSet\Services\{name}",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                "Environment",
                0,
                winreg.REG_MULTI_SZ,
                [
                    f"EUGENE_PLEXUS_AGENT_CONFIG_FILE={service_dir / 'agent.yaml'}",
                    "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=false",
                    f"EUGENE_PLEXUS_AGENT_BIND_PORT={port}",
                    "EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1",
                    f"EUGENE_PLEXUS_AGENT_MACHINE_PORT={machine_port}",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring",
                    f"PATH={os.environ['SystemRoot']}\\System32",
                ],
            )
        granted = _sc("sdset", name, _grant_sddl(sids["a"]))
        if granted.returncode != 0:
            raise Failed(f"sc sdset: {granted.stdout} {granted.stderr}")
        start_service()
        initialized = client.post(base + "/v1/auth/initialize", json={"passphrase": passphrase})
        if initialized.status_code != 200:
            raise Failed(f"initialize: {initialized.status_code} {initialized.text}")
        token = initialized.json()["sessionToken"]
        wait(lambda: runtime(token)["status"] == "ready", "the stand-in engine ready", 120)
        if not answers(engine_port):
            raise Failed("the stand-in engine is ready and does not answer")
        first = pause_of(token)
        if first != {"paused": False, "trayChannel": "serving"}:
            raise Failed(f"before any pause the machine says {first}")
        ok(f"service {name}: {users['a']} may stop it, {users['b']} may not; the tray's channel is served")

        # --- 2. the tray's call, as an account that may stop the service ------
        answer = tray_as("a", "pause")
        if answer.get("status") != "ok":
            raise Failed(f"{users['a']}'s pause: {answer}")
        wait(lambda: not answers(engine_port), "the engine's process ends", 30)
        pause = pause_of(token)
        if not (pause.get("paused") and pause.get("by") == "tray" and pause.get("runtimes") == ["standin"]):
            raise Failed(f"after the tray's pause the machine says {pause}")
        view = runtime(token)
        if view["status"] != "stopped" or view.get("stopReason") != "paused":
            raise Failed(f"after the tray's pause the runtime says {view}")
        started = post("/v1/runtimes/standin/start", token)
        if started.status_code != 409 or "paused from its tray icon" not in detail_of(started):
            raise Failed(f"a Start while paused: {started.status_code} {started.text}")
        since = pause["since"]
        ok(f"{users['a']}, unelevated, pauses with the tray's call: the engine ends, a Start is refused")

        # --- 3. an account that may not ------------------------------------------
        for verb in ("pause", "state", "resume"):
            refused = tray_as("b", verb)
            if refused.get("status") != "denied" or refused.get("body"):
                raise Failed(f"{users['b']}'s {verb}: {refused}")
        if pause_of(token).get("since") != since or answers(engine_port):
            raise Failed("a refused account changed the pause")
        ok(f"{users['b']}, unelevated, is refused at the pipe, and nothing changes")

        # --- 4. the remote path ---------------------------------------------------
        remote_check(tray_pipe.pipe_name(port))
        ok("the remote path \\\\127.0.0.1\\pipe\\... is refused, where a pipe of this script's answers on it")

        # --- 5. the service restarts ---------------------------------------------
        if sabotage:
            shutil.copy2(tray_source, sabotage_copy)
            text = tray_source.read_text(encoding="utf-8")
            marker = '    """Windows\' own `AccessCheck`: may this token stop a service with this DACL?"""\n'
            if marker not in text:
                raise Failed("tray_pipe.may_stop is not where the sabotage expects it")
            tray_source.write_text(
                text.replace(marker, marker + "    return True  # SABOTAGE\n"), encoding="utf-8"
            )
            for cache in tray_source.parent.glob("__pycache__/tray_pipe*"):
                cache.unlink()
            print("SABOTAGE: tray_pipe.may_stop admits everyone", flush=True)
        stop_service()
        start_service()
        token = login()
        time.sleep(8)
        view = runtime(token)
        if view["status"] != "stopped" or view.get("stopReason") != "paused" or answers(engine_port):
            raise Failed(f"after the service restarts the runtime says {view}")
        if pause_of(token).get("since") != since:
            raise Failed("the pause did not outlive the restart")
        ok("after the service restarts the engine stays stopped, still paused")

        # --- 6. a grant removed takes effect at the next connection --------------
        removed = _sc("sdset", name, _grant_sddl(None))
        if removed.returncode != 0:
            raise Failed(f"sc sdset: {removed.stdout} {removed.stderr}")
        answer = tray_as("a", "state")
        if answer.get("status") != "denied" or not (answer.get("body") or {}).get("denied"):
            raise Failed(
                f"with her grant removed, the pipe still admitting her, {users['a']} was "
                f"answered: {answer}"
            )
        answer = tray_as("a", "state")
        if answer.get("status") != "denied":
            raise Failed(f"with her grant removed, {users['a']} was answered: {answer}")
        _sc("sdset", name, _grant_sddl(sids["a"]))
        ok("a grant removed with sc sdset is refused at the next connection, by the agent's own check")
        if sabotage:
            raise Failed(
                "sabotage NOT caught: the removed grant was refused with the check admitting everyone"
            )

        # --- 7. a program that takes the pipe's name first -----------------------
        stop_service()
        ready, heard = results / "squatter.ready", results / "squatter.heard"
        squatter = _run_as(
            users["b"],
            passwords["b"],
            [
                str(venv / "Scripts" / "python.exe"),
                str(root / "squatter.py"),
                tray_pipe.pipe_name(port),
                str(ready),
                str(heard),
            ],
            results,
            user_env(),
            wait_seconds=None,
        )
        holder = int(wait(lambda: ready.read_text(encoding="utf-8").strip(), "the squatter holds the name", 60))
        start_service()
        token = login()
        channel = pause_of(token).get("trayChannel")
        if channel != "taken":
            raise Failed(f"with the name held by process {holder} the agent says {channel}")
        answer = tray_as("a", "pause")
        if answer.get("status") != "imposter":
            raise Failed(f"the tray's call to the squatter: {answer}")
        if heard.exists() and heard.read_bytes():
            raise Failed(f"the tray sent the squatter {heard.read_bytes()!r}")
        ok(f"a program holding the pipe's name (process {holder}) is reported taken, and the tray sends it nothing")
        ctypes.windll.kernel32.TerminateProcess(squatter.hProcess, 1)
        ctypes.windll.kernel32.CloseHandle(squatter.hProcess)
        squatter = None
        # A venv's python.exe starts the interpreter as a child: end both.
        subprocess.run(
            ["taskkill", "/F", "/FI", f"USERNAME eq {users['b']}"], capture_output=True, timeout=60
        )
        # The agent tries the name again every 30 seconds, and takes it back.
        wait(
            lambda: pause_of(token).get("trayChannel") == "serving",
            "the agent takes its channel back once the name is free",
            75,
        )
        ok("once the program ends, the agent takes its channel back by itself")

        # --- 8. Resume -------------------------------------------------------------
        made = post("/v1/auth/client-keys", token, json={"name": "row35"})
        if made.status_code not in (200, 201):
            raise Failed(f"client key: {made.status_code} {made.text}")
        key = made.json()["token"]
        gateway = gateway_token(service_dir)
        for who, credential in (("a client key", key), ("a gateway token", gateway)):
            refused = post("/v1/node/resume", credential)
            if refused.status_code not in (401, 403):
                raise Failed(f"{who} resumed: {refused.status_code} {refused.text}")
        if answers(engine_port):
            raise Failed("a refused resume started the engine")
        resumed = post("/v1/node/resume", token)
        if resumed.status_code != 200:
            raise Failed(f"resume: {resumed.status_code} {resumed.text}")
        states = [(r["name"], r["state"]) for r in resumed.json()["results"]]
        if states != [("standin", "started")]:
            raise Failed(f"resume: {resumed.text}")
        wait(lambda: runtime(token)["status"] == "ready", "the engine runs again", 120)
        if not answers(engine_port):
            raise Failed("the engine is ready again and does not answer")
        ok("Resume with a client key or a gateway token is refused; the operator's starts the engine")
    except BaseException:
        if installed and not sabotage:
            for log in sorted(service_dir.rglob("*.log")):
                text = log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
                print(f"{log.name}:\n" + "\n".join(text), flush=True)
        raise
    finally:
        client.close()
        if squatter is not None:
            ctypes.windll.kernel32.TerminateProcess(squatter.hProcess, 1)
        if sabotage_copy.exists():
            shutil.copy2(sabotage_copy, tray_source)
            for cache in tray_source.parent.glob("__pycache__/tray_pipe*"):
                cache.unlink()
            print("sabotage restored from its copy", flush=True)
        if installed:
            try:
                stop_service()
            finally:
                win32serviceutil.RemoveService(name)
        for user in users.values():
            subprocess.run(["taskkill", "/F", "/FI", f"USERNAME eq {user}"], capture_output=True)
            subprocess.run(["net", "user", user, "/delete"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


def gateway_token(directory: Path) -> str:
    """A `gateway` service token this machine's own key signs."""
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    identity = NodeIdentityStore(directory / "node.yaml")
    identity.load()
    trust = NodeTrust(identity, directory / BUNDLE_FILE)
    trust.load()
    token, _ = trust.mint_service(sub="gateway", audience=trust.recipient)
    return str(token)


def remote_check(name: str) -> None:
    """`\\\\127.0.0.1\\pipe\\...` reaches a pipe of this script's own, and not the agent's."""
    import pywintypes
    import win32file
    import win32pipe
    import win32security

    control = f"eugene-plexus-row35-control-{uuid.uuid4().hex[:8]}"
    attributes = win32security.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = (
        win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            "D:(A;;GA;;;WD)", win32security.SDDL_REVISION_1
        )
    )
    handle = win32pipe.CreateNamedPipe(
        "\\\\.\\pipe\\" + control, 3, 0, 1, 4096, 4096, 0, attributes
    )

    def remote(pipe: str) -> int:
        try:
            opened = win32file.CreateFile(
                "\\\\127.0.0.1\\pipe\\" + pipe,
                win32file.GENERIC_READ | 0x0002,
                0,
                None,
                win32file.OPEN_EXISTING,
                0x00100000 | win32file.SECURITY_IDENTIFICATION,
                None,
            )
        except pywintypes.error as exc:
            return int(exc.winerror)
        opened.Close()
        return 0

    try:
        reached = remote(control)
        if reached != 0:
            raise Failed(
                f"the remote path does not reach a pipe on this runner (error {reached}), so "
                "it cannot show the agent's pipe refuses it"
            )
        refused = remote(name.rsplit("\\", 1)[-1])
        if refused == 0:
            raise Failed("the agent's pipe answered on the remote path")
        print(f"  the remote path to the agent's pipe: error {refused}", flush=True)
    finally:
        handle.Close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", choices=["control", "agent", "gateway", "engine"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--model")
    parser.add_argument("--windows-service", action="store_true")
    parser.add_argument("--sabotage", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port, args.model)
        return
    if args.windows_service:
        if not args.sabotage:
            windows_service(sabotage=False)
            print("ALL PASS (the tray's channel on a real service)", flush=True)
            return
        try:
            windows_service(sabotage=True)
        except Failed as caught:
            # Only step 6's own check counts: a failure anywhere else is not this one.
            if "with her grant removed" not in str(caught):
                raise
            ok(f"sabotage caught: with the identity check admitting everyone, step 6 fails ({caught})")
            return
        raise Failed("sabotage NOT caught: the run passed with the identity check admitting everyone")
    temporary = Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix="row35-", dir=temporary) as directory:
        console(Path(directory).resolve())
    print("ALL PASS (the console path)", flush=True)
    if args.sabotage:
        with tempfile.TemporaryDirectory(prefix="row35-sabotage-", dir=temporary) as directory:
            try:
                console(Path(directory).resolve(), sabotage=True)
            except Failed as caught:
                # Only step 3's own checks count: a failure anywhere else is not this one.
                if not any(
                    words in str(caught)
                    for words in ("while the models were paused", "does not name the pause")
                ):
                    raise
                ok(f"sabotage caught: with the start guard removed, step 3 fails ({caught})")
                return
        raise Failed("sabotage NOT caught: the console path passed with the start guard removed")


if __name__ == "__main__":
    main()
