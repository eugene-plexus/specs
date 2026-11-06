"""agent#43 acceptance: an agent restarted in the container's shape unlocks itself.

The container (the image and the Unraid template) gives the control root a
passphrase file (`EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE`) and gives the agent
none of its own (`EUGENE_PLEXUS_AGENT_PASSPHRASE_FILE` unset). Before the fix a
restart left the root unlocked and the agent locked, so every driver it
supervises started without the master key, and a provider account's sealed
API key read as unset until a person signed in. Troy's rule: a person who gave
Eugene a passphrase file never has to sign in to get service back.

One agent, run through the shared harness's real start path
(`s8-ui-acceptance.py --serve`: its machine port, its client doors, the
children it spawns), in the container's shape: a temporary config folder,
`agent.yaml` with `securityMode: passphrase_file`, the root's variable naming
`<tmp>/passphrase`, the agent's own variable unset. Loopback ports the
operating system hands out (never 8079-8084 or the live install's
8279-8284); every `EUGENE_PLEXUS_*` variable of the calling shell is cleared
before anything starts. No model, no GPU, no cloud service.

The provider is a fake OpenAI-compatible server this script runs on loopback.
It keeps the `Authorization` header of every request it gets, and refuses a
request without the account's key with 401, as a real provider does. The
account is the `openai` provider pointed at it (`baseUrl`): a provider that
needs a key, as OpenRouter does, so a driver without its key comes up degraded,
as it did on the NAS.

Checks, in order:

1. The operator's file is written as the Unraid template says (`printf '%s'`:
   the exact bytes, no newline; mode 0400 on POSIX), and the agent is
   initialized with that passphrase.
2. An inference-driver for the account is declared, and its `apiKey` is set
   with `PATCH /v1/config` through the agent's proxy, as the console does. The
   driver's file on disk holds the key sealed: an envelope, the key nowhere in
   the file, and the envelope opens with the master key derived from the
   passphrase to exactly the key.
3. The agent and its children are stopped, and the agent is started again.
   No sign-in call is made from here to check 5.
4. Without signing in: `/v1/auth/status` says `unlocked: true`; the driver is
   not degraded; and a chat request to the driver, with a token minted from the
   agent's own node files (what a gateway on this machine sends), reaches the
   fake provider carrying `Authorization: Bearer <the exact key>`.
5. One sign-in. The operator's file is still the same file with the same
   bytes, time and mode: the agent read it and never wrote it.
6. `--sabotage` (after 1-5 pass, which is its baseline): the agent is
   restarted twice more, without signing in. (a) In the old container shape,
   the root's variable unset. (b) In the container's shape with the agent's
   fix taken back in the agent's process only (`passphrase_file.unlock_path`
   returns the agent's own file, none here), which is the agent of agent#43.
   Each of check 4's three checks must fail both times: the agent locked, the
   driver degraded, and no request carrying the key reaches the provider.

Needs the agent and the inference-driver installed in this interpreter (the
Pinned integration job has them). Run:
`python scripts/a43-container-unlock-acceptance.py [--sabotage]`. Exits 1
when a check fails, with the end of the agent's log (its children's output is
in it).
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import importlib.util
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve()
HARNESS = HERE.parent / "s8-ui-acceptance.py"
#: Ports this run never takes: the defaults and the live install's (+200).
NEVER = set(range(8079, 8085)) | set(range(8279, 8285))
#: The root's variable: the container's only passphrase file.
ROOT_FILE_VARIABLE = "EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE"
#: The agent's own variable, which the container does not set.
AGENT_FILE_VARIABLE = "EUGENE_PLEXUS_AGENT_PASSPHRASE_FILE"
DRIVER = "a43-account"
MODEL = "gpt-4o-mini"
CHECKS_4 = (
    "4a. the agent is unlocked",
    "4b. the driver is not degraded",
    "4c. the key reaches the provider",
)


def clear_install_settings() -> None:
    """Drop the calling shell's install settings before anything reads them:
    this machine's live agent sets EUGENE_PLEXUS_AGENT_CONFIG_FILE at user
    scope. Only in the process that runs the checks. The agent this script
    serves (`--serve-agent`) keeps what `Run.start_agent` gave it, the root's
    variable included: clearing it there is the old container shape (the first
    CI run of this script did that, and every check after 3 failed)."""
    for key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[key]


class Failed(AssertionError):
    """A check did not hold; the message names what was observed."""


# --------------------------------------------------------------------------- #
# The agent, through the shared harness
# --------------------------------------------------------------------------- #


def serve_agent(directory: Path, port: int, machine_port: int, revert_fix: bool) -> None:
    """One agent through the shared harness's real start path.

    `revert_fix` takes agent#43's fix back in this process only: the agent
    reads its own passphrase file and never the root's, as it did before."""
    if revert_fix:
        from eugene_plexus_agent import passphrase_file

        if not hasattr(passphrase_file, "unlock_path"):
            raise SystemExit("this agent has no passphrase_file.unlock_path to take back")

        def own_file_only(own: Path | None, root: Path | None) -> Path | None:
            return own

        passphrase_file.unlock_path = own_file_only  # type: ignore[assignment]
        print("a43: SABOTAGED: the agent reads its own passphrase file only", flush=True)
    spec = importlib.util.spec_from_file_location("s8_harness", HARNESS)
    assert spec is not None and spec.loader is not None
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    harness.serve(directory, port, machine_port)


# --------------------------------------------------------------------------- #
# The fake provider
# --------------------------------------------------------------------------- #


class FakeProvider:
    """An OpenAI-compatible provider on loopback that keeps every request's
    `Authorization` header and refuses any but the account's key."""

    def __init__(self, key: str) -> None:
        self.key = key
        self._lock = threading.Lock()
        self._seen: list[dict[str, Any]] = []
        provider = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
                self._handle("GET")

            def do_POST(self) -> None:  # noqa: N802 - the stdlib's name
                self._handle("POST")

            def _send(self, status: int, data: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _json(self, status: int, body: dict[str, Any]) -> None:
                self._send(status, json.dumps(body).encode("utf-8"), "application/json")

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                authorization = self.headers.get("Authorization")
                path = self.path.split("?", 1)[0]
                provider.record(method, path, authorization, raw)
                if authorization != f"Bearer {provider.key}":
                    self._json(
                        401,
                        {
                            "error": {
                                "message": "Incorrect API key provided.",
                                "type": "invalid_request_error",
                                "code": "invalid_api_key",
                            }
                        },
                    )
                    return
                if method == "GET" and path == "/v1/models":
                    self._json(
                        200,
                        {
                            "object": "list",
                            "data": [
                                {"id": MODEL, "object": "model", "created": 0, "owned_by": "a43"}
                            ],
                        },
                    )
                    return
                if method == "POST" and path == "/v1/chat/completions":
                    self._chat(raw)
                    return
                self._json(404, {"error": {"message": f"no {method} {path} here"}})

            def _chat(self, raw: bytes) -> None:
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                messages = body.get("messages") or [{}]
                said = str(messages[-1].get("content") or "")
                text = f"a43 heard: {said}"
                usage = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
                if body.get("stream"):
                    chunks = [
                        {
                            "id": "chatcmpl-a43",
                            "object": "chat.completion.chunk",
                            "created": 0,
                            "model": MODEL,
                            "choices": [
                                {"index": 0, "delta": {"role": "assistant", "content": text}}
                            ],
                        },
                        {
                            "id": "chatcmpl-a43",
                            "object": "chat.completion.chunk",
                            "created": 0,
                            "model": MODEL,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            "usage": usage,
                        },
                    ]
                    stream = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
                    self._send(200, (stream + "data: [DONE]\n\n").encode(), "text/event-stream")
                    return
                self._json(
                    200,
                    {
                        "id": "chatcmpl-a43",
                        "object": "chat.completion",
                        "created": 0,
                        "model": MODEL,
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": text},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": usage,
                    },
                )

        while True:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            if int(server.server_address[1]) not in NEVER:
                break
            server.server_close()
        server.daemon_threads = True
        self.server = server
        self.port = int(server.server_address[1])
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def record(self, method: str, path: str, authorization: str | None, raw: bytes) -> None:
        with self._lock:
            self._seen.append(
                {
                    "method": method,
                    "path": path,
                    "authorization": authorization,
                    "body": raw.decode("utf-8", errors="replace"),
                }
            )

    def seen(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._seen)

    def forget(self) -> None:
        with self._lock:
            self._seen.clear()

    def describe(self, authorization: str | None) -> str:
        """A header as a log may show it: never the key itself."""
        if authorization is None:
            return "no Authorization header"
        if authorization == f"Bearer {self.key}":
            return "Bearer <the account's key>"
        return f"another Authorization header ({len(authorization)} characters)"

    def summary(self) -> str:
        seen = self.seen()
        if not seen:
            return "the provider got no request"
        return "the provider got " + "; ".join(
            f"{r['method']} {r['path']} with {self.describe(r['authorization'])}" for r in seen
        )

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def free_ports(names: list[str]) -> dict[str, int]:
    """Distinct loopback ports the OS says are free now, none of the forbidden."""
    held: list[socket.socket] = []
    ports: dict[str, int] = {}
    try:
        while len(ports) < len(names):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            held.append(sock)
            port = int(sock.getsockname()[1])
            if port in NEVER or port in ports.values():
                continue
            ports[names[len(ports)]] = port
        return ports
    finally:
        for sock in held:
            sock.close()


def fingerprint(path: Path) -> dict[str, Any]:
    """What a write of the file would change: its bytes, its time, the file
    itself (a write replaces it) and its mode."""
    status = path.stat()
    return {
        "bytes": path.read_bytes(),
        "mtime_ns": status.st_mtime_ns,
        "inode": status.st_ino,
        "mode": oct(status.st_mode & 0o777),
    }


class Run:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.agent_dir = root / "agent"
        self.home = root / "home"
        for directory in (self.agent_dir, self.home):
            directory.mkdir()
        self.operators_file = root / "passphrase"
        # A % and a backslash: what `printf '%s'` keeps and a bare printf rewrites.
        self.passphrase = f"a43 {secrets.token_urlsafe(9)} 100% \\ok"
        self.key = f"sk-a43-{secrets.token_urlsafe(24)}"
        self.ports = free_ports(["agent", "machine", "driver"])
        self.provider = FakeProvider(self.key)
        self.client = httpx.Client(trust_env=False, timeout=60)
        self.process: subprocess.Popen[bytes] | None = None
        self.log: Any = None
        self.session: str | None = None
        self.written: dict[str, Any] = {}
        self.passed: list[str] = []

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def ok(self, message: str) -> None:
        self.passed.append(message)
        print(f"PASS {message}", flush=True)

    # ---- the agent's process -------------------------------------------------

    def start_agent(self, *, container_shape: bool = True, revert_fix: bool = False) -> None:
        (self.agent_dir / "stop").unlink(missing_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        # The provider's key reaches the driver from its config or not at all.
        env.pop("OPENAI_API_KEY", None)
        env.update(
            HOME=str(self.home),
            USERPROFILE=str(self.home),
            NO_PROXY="localhost,127.0.0.1,::1",
            PYTHONUTF8="1",
            PYTHONUNBUFFERED="1",
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        )
        if container_shape:
            env[ROOT_FILE_VARIABLE] = str(self.operators_file)
        assert AGENT_FILE_VARIABLE not in env
        argv = [
            sys.executable,
            str(HERE),
            "--serve-agent",
            str(self.agent_dir),
            "--port",
            str(self.ports["agent"]),
            "--machine-port",
            str(self.ports["machine"]),
            *(["--revert-fix"] if revert_fix else []),
        ]
        self.log = (self.root / "agent.log").open("ab")
        self.process = subprocess.Popen(
            argv,
            cwd=self.agent_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.wait(lambda: self.get("agent", "/healthz").status_code == 200, "the agent", 120)

    def stop_agent(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        (self.agent_dir / "stop").touch()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            kill_tree(process)
            raise Failed("the agent did not stop within 60 s of its stop file") from None
        finally:
            if self.log is not None:
                self.log.close()
                self.log = None
        self.wait_released(["agent", "machine", "driver"])

    def wait_released(self, names: list[str]) -> None:
        """Until nothing listens on these ports: a stopped agent's children too."""

        def released() -> bool:
            for name in names:
                with socket.socket() as probe:
                    probe.settimeout(1)
                    if probe.connect_ex(("127.0.0.1", self.ports[name])) == 0:
                        return False
            return True

        self.wait(released, f"{', '.join(names)} to stop listening", 60, needs_agent=False)

    def close(self) -> None:
        if self.process is not None:
            try:
                self.stop_agent()
            except Failed as exc:
                print(f"while closing: {exc}", file=sys.stderr)
        self.provider.close()
        self.client.close()

    def dump_logs(self) -> None:
        if self.log is not None:
            self.log.flush()
        print(self.provider.summary(), file=sys.stderr)
        path = self.root / "agent.log"
        if path.exists():
            tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-150:]
            print("--- the agent's log (last 150 lines) ---", *tail, sep="\n", file=sys.stderr)

    # ---- calls -----------------------------------------------------------------

    def call(
        self, method: str, name: str, path: str, token: str | None = None, **kw: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, self.url(name) + path, headers=headers, **kw)

    def get(self, name: str, path: str, token: str | None = None) -> httpx.Response:
        return self.call("GET", name, path, token)

    def wait(
        self,
        check: Callable[[], Any],
        label: str,
        timeout: float = 60.0,
        *,
        needs_agent: bool = True,
    ) -> float:
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
            if needs_agent and (self.process is None or self.process.poll() is not None):
                code = None if self.process is None else self.process.returncode
                raise Failed(f"the agent exited (code {code}) while waiting for {label}")
            time.sleep(0.3)
        raise Failed(f"timed out after {timeout:.0f} s waiting for {label} (last: {last!r})")

    def driver_health(self) -> dict[str, Any]:
        """The driver's /healthz, once it answers at all."""
        answer: dict[str, Any] = {}

        def answered() -> bool:
            got = self.get("driver", "/healthz")
            if got.status_code != 200:
                return False
            answer.update(got.json())
            return True

        self.wait(answered, "the driver's /healthz", 120)
        return answer

    def service_token(self) -> str:
        """What a gateway on this machine sends its driver, minted from the
        agent's own node files: no sign-in, no session."""
        from eugene_plexus_agent.node_identity import NODE_FILE, NodeIdentityStore
        from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

        store = NodeIdentityStore(self.agent_dir / NODE_FILE)
        store.load()
        trust = NodeTrust(store, self.agent_dir / BUNDLE_FILE)
        token, _ = trust.mint_service(sub="gateway", audience=trust.recipient)
        return str(token)

    def master_key(self) -> bytes:
        """The master key, derived from the passphrase and the salt in agent.yaml."""
        from eugene_plexus_agent import security as agent_security

        state = yaml.safe_load((self.agent_dir / "agent.yaml").read_text(encoding="utf-8"))
        auth = state.get("auth") or {}
        if auth.get("wrappedMasterKey"):
            raise Failed("agent.yaml holds a wrapped master key; this run changed no passphrase")
        salt = auth.get("masterSalt")
        if not isinstance(salt, str):
            raise Failed(f"agent.yaml holds no master-key salt: auth is {sorted(auth)}")
        return bytes(agent_security.derive_master_key(self.passphrase, base64.b64decode(salt)))


def kill_tree(process: subprocess.Popen[bytes]) -> None:
    """A run that could not stop its agent must not leave it or its children."""
    import psutil

    with contextlib.suppress(psutil.Error, OSError):
        for child in psutil.Process(process.pid).children(recursive=True):
            with contextlib.suppress(psutil.Error, OSError):
                child.kill()
    with contextlib.suppress(OSError):
        process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


def step_initialize(run: Run) -> None:
    """1. The operator's file as the template says, and the agent initialized."""
    # printf '%s' 'the passphrase' > /data/passphrase: these bytes, no newline.
    with run.operators_file.open("wb") as stream:
        stream.write(run.passphrase.encode("utf-8"))
    if os.name != "nt":
        os.chmod(run.operators_file, 0o400)
    run.written = fingerprint(run.operators_file)
    (run.agent_dir / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "securityMode": "passphrase_file",
                "components": [],
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    run.start_agent()
    before = run.get("agent", "/v1/auth/status").json()
    if before.get("initialized") is not False:
        raise Failed(f"a new agent's /v1/auth/status says {before}")
    initialized = run.call(
        "POST", "agent", "/v1/auth/initialize", json={"passphrase": run.passphrase}
    )
    if initialized.status_code != 200:
        raise Failed(f"initialize answered {initialized.status_code}: {initialized.text[:300]}")
    run.session = str(initialized.json()["sessionToken"])
    after = run.get("agent", "/v1/auth/status").json()
    if after.get("unlocked") is not True:
        raise Failed(f"just initialized, /v1/auth/status says {after}")
    mode = run.written["mode"] if os.name != "nt" else "not set on Windows"
    run.ok(
        f"1. the operator's file holds the passphrase's {len(run.written['bytes'])} bytes and "
        f"no newline (mode {mode}); the agent is initialized with it and unlocked"
    )


def step_sealed_key(run: Run) -> None:
    """2. The account's key set through the console's path, sealed on disk."""
    config_file = run.agent_dir / f"{DRIVER}.yaml"
    config_file.write_text(
        yaml.safe_dump({"provider": "openai", "baseUrl": run.provider.url}),
        encoding="utf-8",
        newline="\n",
    )
    declared = run.call(
        "POST",
        "agent",
        "/v1/components",
        run.session,
        json={
            "name": DRIVER,
            "kind": "inference-driver",
            "url": run.url("driver"),
            "spawn": {"configFile": str(config_file)},
        },
    )
    if declared.status_code != 201:
        raise Failed(f"declaring {DRIVER}: {declared.status_code} {declared.text[:300]}")
    run.driver_health()
    patched = run.call(
        "PATCH",
        "agent",
        f"/api/proxy/{DRIVER}/v1/config",
        run.session,
        json={"apiKey": run.key},
    )
    if patched.status_code != 200 or "apiKey" not in (patched.json().get("applied") or []):
        raise Failed(f"PATCH apiKey through the proxy: {patched.status_code} {patched.text[:300]}")
    text = config_file.read_text(encoding="utf-8")
    if run.key in text:
        raise Failed(f"{config_file.name} holds the API key in plain text")
    from eugene_plexus_inference_driver import security as driver_security

    value = (yaml.safe_load(text) or {}).get("apiKey")
    if not driver_security.is_envelope(value):
        raise Failed(f"{config_file.name} holds apiKey as {type(value).__name__}, not sealed")
    try:
        opened = driver_security.open_envelope(
            driver_security.Envelope.from_dict(value), run.master_key()
        )
    except ValueError as exc:
        raise Failed(f"the sealed apiKey does not open with the master key: {exc}") from exc
    if opened != run.key:
        raise Failed("the sealed apiKey opens with the master key to another value")
    run.ok(
        f"2. {DRIVER}'s apiKey, set with PATCH /v1/config through the agent's proxy, is sealed "
        f"on disk ({value['alg']}), is nowhere in the file in plain text, and opens with the "
        "master key to exactly the key"
    )


def restart(run: Run, *, container_shape: bool = True, revert_fix: bool = False) -> None:
    """3. The agent and its children stopped and started again; no sign-in."""
    run.stop_agent()
    run.provider.forget()
    run.start_agent(container_shape=container_shape, revert_fix=revert_fix)


def check_unlocked(run: Run) -> str:
    status = run.get("agent", "/v1/auth/status").json()
    if status.get("initialized") is not True or status.get("unlocked") is not True:
        raise Failed(f"with no sign-in, /v1/auth/status says {status}")
    return "/v1/auth/status says initialized and unlocked"


def check_driver_built(run: Run) -> str:
    # The driver builds its engine before it serves, so its first answer is
    # its state until something restarts it, and nothing here does.
    health = run.driver_health()
    if health.get("status") != "ok":
        details = health.get("details") or {}
        raise Failed(f"the driver says {health.get('status')!r}: {details.get('adapter_error')!r}")
    return "the driver's /healthz says ok"


def check_key_reaches_provider(run: Run) -> str:
    canary = f"a43-{secrets.token_hex(6)}"
    token = run.service_token()
    last: dict[str, Any] = {}

    def answered() -> bool:
        got = run.call(
            "POST",
            "driver",
            "/v1/generate",
            token,
            json={"model": MODEL, "messages": [{"role": "user", "content": canary}]},
        )
        last["response"] = got
        if got.status_code == 200:
            return True
        # A degraded driver stays so until it restarts: stop waiting on it.
        health = run.get("driver", "/healthz").json()
        if health.get("status") != "ok":
            raise Failed(
                f"the chat request answered {got.status_code} and the driver is "
                f"{health.get('status')}: {(health.get('details') or {}).get('adapter_error')!r}"
            )
        return False

    try:
        run.wait(answered, "a chat request through the driver", 60)
    except Failed as exc:
        response = last.get("response")
        said = f"{response.status_code} {response.text[:300]}" if response is not None else "-"
        raise Failed(f"{exc}; the driver last answered {said}; {run.provider.summary()}") from None
    chats = [
        r
        for r in run.provider.seen()
        if r["method"] == "POST" and r["path"] == "/v1/chat/completions" and canary in r["body"]
    ]
    if not chats:
        raise Failed(
            "the driver answered 200 but no chat with the canary reached the provider; "
            + run.provider.summary()
        )
    headers = {run.provider.describe(r["authorization"]) for r in chats}
    if headers != {"Bearer <the account's key>"}:
        raise Failed(f"the chat reached the provider with {sorted(headers)}")
    listed = [
        r
        for r in run.provider.seen()
        if r["path"] == "/v1/models" and r["authorization"] == f"Bearer {run.key}"
    ]
    also = f", as did {len(listed)} model list read(s)" if listed else ""
    return (
        f"a chat request through the driver reached the provider with Authorization: "
        f"Bearer <the exact key>{also}"
    )


CHECKS: dict[str, Callable[[Run], str]] = {
    CHECKS_4[0]: check_unlocked,
    CHECKS_4[1]: check_driver_built,
    CHECKS_4[2]: check_key_reaches_provider,
}


def step_restarted(run: Run) -> None:
    restart(run)
    run.ok("3. the agent and its driver stopped and started again; no sign-in since")
    for name, check in CHECKS.items():
        run.ok(f"{name}: {check(run)}")


def step_sign_in_keeps_the_file(run: Run) -> None:
    """5. One sign-in, and the operator's file is the same file, unwritten."""
    signed_in = run.call("POST", "agent", "/v1/auth/login", json={"passphrase": run.passphrase})
    if signed_in.status_code != 200:
        raise Failed(f"the sign-in answered {signed_in.status_code}: {signed_in.text[:300]}")
    now = fingerprint(run.operators_file)
    changed = sorted(k for k in now if now[k] != run.written[k])
    if changed:
        raise Failed(f"the operator's file changed after the initialize and a sign-in: {changed}")
    run.ok(
        "5. after the initialize and one sign-in the operator's file has the same bytes, time, "
        "file and mode: read, never written"
    )


def step_sabotage(run: Run, label: str, *, container_shape: bool, revert_fix: bool) -> None:
    """6. Restarted as before the fix: each of check 4's checks must fail."""
    restart(run, container_shape=container_shape, revert_fix=revert_fix)
    held: list[str] = []
    caught: list[str] = []
    for name, check in CHECKS.items():
        try:
            check(run)
        except Failed as exc:
            caught.append(f"{name.split('.')[0]} failed ({exc})")
        else:
            held.append(name)
    if held:
        raise Failed(f"sabotage NOT caught ({label}): {', '.join(held)} still passed")
    keyed = [r for r in run.provider.seen() if r["authorization"] == f"Bearer {run.key}"]
    if keyed:
        raise Failed(
            f"sabotage NOT caught ({label}): {len(keyed)} request(s) still reached the provider "
            "with the account's key"
        )
    run.ok(
        f"6. sabotage caught ({label}): no request with the key reached the provider; "
        + "; ".join(caught)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--serve-agent", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--machine-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--revert-fix", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sabotage",
        action="store_true",
        help="after the checks pass, restart as before the fix; check 4 must fail",
    )
    args = parser.parse_args()
    if args.serve_agent:
        serve_agent(args.serve_agent, args.port, args.machine_port, args.revert_fix)
        return 0
    clear_install_settings()
    expected = 7 + (2 if args.sabotage else 0)
    with tempfile.TemporaryDirectory(prefix="ep-a43-", ignore_cleanup_errors=True) as tmp:
        run = Run(Path(tmp))
        try:
            step_initialize(run)
            step_sealed_key(run)
            step_restarted(run)
            step_sign_in_keeps_the_file(run)
            if args.sabotage:
                step_sabotage(
                    run,
                    f"the old container shape: {ROOT_FILE_VARIABLE} unset",
                    container_shape=False,
                    revert_fix=False,
                )
                step_sabotage(
                    run,
                    "the container's shape, the agent's fix taken back",
                    container_shape=True,
                    revert_fix=True,
                )
        except Failed as exc:
            print(f"FAIL {exc}", flush=True)
            run.dump_logs()
        except BaseException:
            run.dump_logs()
            raise
        finally:
            run.close()
    print(f"{len(run.passed)}/{expected} checks passed", flush=True)
    return 0 if len(run.passed) == expected else 1


if __name__ == "__main__":
    sys.exit(main())
