"""Row 53 acceptance: files kept for their owners only, by the store a root starts.

Real processes on loopback ports the operating system hands out, with temporary
state and every ambient `EUGENE_PLEXUS_*` variable cleared; never the default
ports 8079-8083 and never the live install. A control root (its own process),
and an agent enrolled with it that runs the agent's own start path with the
default topology on: it declares and starts the store by itself, because its
topology names the install's control root. A gateway, an inference-driver and a
scripted backend run beside it, as `row57-responses-tools-acceptance.py` runs
them. Two people sign in to a Workbench-style app (an app key plus each
person's own token); a plain client key has no person.

1. Ann keeps a file in one request and a 40 MiB file through an upload of three
   parts; lists and reads both; a chat naming her text file's id reaches the
   backend with the file's words inline.
2. Ben's list is empty; Ben asking for Ann's file, its content, or its
   deletion gets the same 404 as for an id that does not exist, and Ann's file
   is untouched; Ben's chat with Ann's id is refused the same way.
3. The plain key's files are its own: neither person sees them, it sees no
   person's.
4. Files are kept until deleted, as OpenAI keeps them; an app's
   `expires_after` takes OpenAI's bounds (one hour to 30 days). A file the
   store was told to keep for one second (asked with the gateway's own token,
   as the door would) is gone after the sweep: from the database and the disk.
5. Ann is removed at the root (call R53-REMOVE, Choice 2: row 7's rules). A
   copy of the store is kept beside it, as a migration keeps one. At the next
   sweep her files are hidden: the store answers her ids with the 404 of a
   missing id, to her and to Ben, her token is refused at the gateway, her
   rows and blobs are still on disk, and the console shows her counts with a
   delete date 30 days on. The owner's Delete now deletes them at once: rows,
   blobs and her rows in the copy. Ben's and the key's files stay.
6. The store is stopped: `/v1/files` is a 503 naming the cause, and a chat that
   names no file still answers.
7. `--sabotage`: a store whose listing drops the owner filter, then one whose
   lookup by id (read, content, delete) drops it, serves the install; step 2's
   isolation check must fail against each. Each sabotage is made in that store's
   process only (a method replaced before it starts); no file changes, so
   nothing needs restoring.

Run with a Python that has agent, control, gateway, inference-driver and store
installed (CI's Pinned integration job has them).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import yaml

HERE = Path(__file__).resolve().parent
PASSES: list[str] = []
MODEL = "row53-fixture"
CALLBACK = "http://127.0.0.1:9/callback"
APP_OWNER = "app:workbench@root"
PASSWORD = "row53 member password"
VERIFIER = "v" * 50
MARKER = "ROW53-MARKER: the quartz otter keeps the ledger."
#: The ports a script must never take: the install's defaults.
DEFAULT_PORTS = range(8079, 8084)
MIB = 1024 * 1024


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {message}", flush=True)


@contextmanager
def must_fail(label: str) -> Iterator[None]:
    """The block must raise `AssertionError`: a check the sabotage breaks."""
    try:
        yield
    except AssertionError as caught:
        ok(f"sabotage caught: {label} ({caught})")
        return
    raise AssertionError(f"sabotage NOT caught: {label} passed against a broken store")


def free_port(*taken: int) -> int:
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in DEFAULT_PORTS and port not in taken and port != 8084:
            return port


# --------------------------------------------------------------------------- #
# The processes
# --------------------------------------------------------------------------- #


def fixture_app() -> Any:
    from fastapi import FastAPI

    app = FastAPI()
    seen: list[dict[str, Any]] = []

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {}

    @app.get("/seen")
    async def requests() -> list[dict[str, Any]]:
        return seen

    @app.get("/model/props")
    async def props() -> dict[str, Any]:
        return {"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": False}}

    @app.get("/model/v1/models")
    async def models() -> dict[str, Any]:
        return {"data": [{"id": MODEL, "object": "model"}]}

    @app.post("/model/v1/chat/completions")
    async def complete(body: dict[str, Any]) -> dict[str, Any]:
        seen.append(body)
        return {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ROW53-ANSWER"},
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22},
        }

    return app


def _sabotage_listing() -> None:
    """The listing, without its owner filter: every owner's files."""
    from eugene_plexus_store import keeper

    original = keeper.Keeper.list_files

    def every_owners(self: Any, owner: str, **kw: Any) -> dict[str, Any]:
        with self.database.lock:
            owners = [
                row[0]
                for row in self.database.connection.execute("SELECT DISTINCT owner FROM files")
            ]
        data: list[dict[str, Any]] = []
        for each in owners:
            data.extend(original(self, each, **kw)["data"])
        return {"data": data, "hasMore": False}

    keeper.Keeper.list_files = every_owners  # type: ignore[method-assign]


def _sabotage_lookup() -> None:
    """Read, content and delete by id, without the owner filter."""
    from eugene_plexus_store import keeper

    def anyones(self: Any, owner: str, file_id: str) -> Any:
        row = self.database.connection.execute(
            "SELECT * FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if row is None:
            raise keeper.not_found("file", file_id)
        return row

    keeper.Keeper._owned_file = anyones  # type: ignore[method-assign]


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    assert port not in DEFAULT_PORTS and port != 8084, "default ports are forbidden"
    if kind == "agent":
        serve_agent(directory, port)
        return
    if kind == "control":
        from eugene_plexus_control.app import create_app as control_app
        from eugene_plexus_control.settings import Settings as ControlSettings

        app = control_app(
            ControlSettings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    elif kind == "fixture":
        app = fixture_app()
    else:
        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        if kind == "model":
            from eugene_plexus_inference_driver.app import create_app as driver_app
            from eugene_plexus_inference_driver.settings import Settings as DriverSettings

            app = driver_app(
                settings=DriverSettings(config_file=directory / "driver.yaml", **bootstrap)
            )
        elif kind == "gateway":
            from eugene_plexus_gateway.app import create_app as gateway_app
            from eugene_plexus_gateway.settings import Settings as GatewaySettings

            app = gateway_app(
                settings=GatewaySettings(
                    config_file=directory / "gateway.yaml",
                    metrics_file=directory / "metrics.sqlite3",
                    **bootstrap,
                )
            )
        elif kind.startswith("store-sabotaged-"):
            {"listing": _sabotage_listing, "lookup": _sabotage_lookup}[kind.rsplit("-", 1)[1]]()
            from eugene_plexus_store.app import create_app as store_app
            from eugene_plexus_store.settings import Settings as StoreSettings

            app = store_app(
                settings=StoreSettings(config_file=directory / "store.yaml", **bootstrap)
            )
        else:
            raise SystemExit(f"unknown kind {kind}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


def serve_agent(directory: Path, port: int) -> None:
    """The agent's own start path, as row 2's harness runs it, with the default
    topology on: an install's agent declares its defaults by itself."""
    import importlib

    agent = importlib.import_module("eugene_plexus_agent.__main__")
    from eugene_plexus_agent.settings import Settings

    machine = int((directory / "machine-port").read_text(encoding="utf-8"))
    settings = Settings(
        config_file=directory / "agent.yaml",
        bind_port=port,
        default_topology=True,
        machine_port=machine,
    )
    stop = lambda: (directory / "stop").exists()  # noqa: E731
    agent.serve(settings, unattended=True, should_stop=stop)


def node_trust(agent_dir: Path) -> Any:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    store = NodeIdentityStore(agent_dir / "node.yaml")
    store.load()
    trust = NodeTrust(store, agent_dir / BUNDLE_FILE)
    trust.load()
    return trust


def bootstrap_for(agent_dir: Path, agent_url: str, sub: str) -> dict[str, str]:
    """What the agent hands a child of kind `sub` at spawn."""
    trust = node_trust(agent_dir)
    token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
    return {
        "agent_url": agent_url,
        "trust_bundle_file": str(trust.bundle_path),
        "trust_authority": trust.authority,
        "auth_recipient": trust.recipient,
        "service_token": str(token),
    }


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class Install:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.client = httpx.Client(timeout=120, trust_env=False, follow_redirects=False)
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.logs: list[Any] = []
        self.passphrase = secrets.token_urlsafe(24)
        self.ports: dict[str, int] = {}
        for name in (
            "control", "agent", "machine", "fixture", "model", "gateway", "listing", "lookup"
        ):
            self.ports[name] = free_port(*self.ports.values())

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def call(
        self, name: str, method: str, path: str, token: str | None = None, **kw: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        headers.update(kw.pop("headers", {}))
        return self.client.request(method, self.url(name) + path, headers=headers, **kw)

    def wait(self, check: Callable[[], bool], label: str, seconds: float = 60) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, OSError, KeyError, ValueError):
                pass
            time.sleep(0.2)
        raise AssertionError("timed out: " + label)

    def start(self, name: str, kind: str | None = None) -> None:
        work = self.directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        self.logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        self.processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                kind or name,
                "--directory",
                str(work),
                "--port",
                str(self.ports[name]),
            ],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.wait(lambda: self.call(name, "GET", "/healthz").status_code == 200, f"{name} up")

    def close(self) -> None:
        (self.directory / "agent" / "stop").touch()
        agent = self.processes.get("agent")
        if agent is not None:
            try:
                agent.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self.processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in self.logs:
            log.close()
        self.client.close()

    # --- the root ---------------------------------------------------------

    def sign_in(self, app: dict[str, Any], person: str) -> str:
        """The Authorization Code flow with PKCE, as an app runs it."""
        client_id = app["client"]["clientId"]
        page = self.call(
            "control",
            "GET",
            "/oidc/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": CALLBACK,
                "scope": "openid profile offline_access",
                "state": "row53",
                "nonce": secrets.token_urlsafe(8),
                "code_challenge": _challenge(VERIFIER),
                "code_challenge_method": "S256",
            },
        )
        assert page.status_code == 200, page.text
        found = re.search(r'name="request" value="([^"]+)"', page.text)
        assert found, page.text
        approved = self.call(
            "control",
            "POST",
            "/oidc/authorize",
            data={"request": found.group(1), "name": person, "password": PASSWORD},
        )
        assert approved.status_code == 302, approved.text
        code = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
        exchanged = self.client.post(
            self.url("control") + "/oidc/token",
            auth=(client_id, app["clientSecret"]),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": VERIFIER,
                "redirect_uri": CALLBACK,
            },
        )
        assert exchanged.status_code == 200, exchanged.text
        return str(exchanged.json()["access_token"])


# --------------------------------------------------------------------------- #
# What a caller does
# --------------------------------------------------------------------------- #


class Caller:
    """An app at the gateway's door: a key, and for a person their own token."""

    def __init__(self, install: Install, key: str, person_token: str | None = None) -> None:
        self.install = install
        self.headers = {"Authorization": f"Bearer {key}"}
        if person_token is not None:
            self.headers["X-Eugene-Person-Token"] = person_token

    def files(self, method: str, path: str = "", **kw: Any) -> httpx.Response:
        return self.install.client.request(
            method, self.install.url("gateway") + "/v1/files" + path, headers=self.headers, **kw
        )

    def keep(self, name: str, content: bytes, **form: str) -> httpx.Response:
        return self.files(
            "POST",
            files={"file": (name, content, "application/octet-stream")},
            data={"purpose": "user_data", **form},
        )

    def post(self, path: str, **kw: Any) -> httpx.Response:
        return self.install.client.post(
            self.install.url("gateway") + path, headers=self.headers, **kw
        )

    def listed(self) -> list[str]:
        answer = self.files("GET")
        assert answer.status_code == 200, answer.text
        return [f["id"] for f in answer.json()["data"]]

    def chat(self, file_id: str | None = None) -> httpx.Response:
        content: Any = "Say hello."
        if file_id is not None:
            content = [
                {"type": "text", "text": "Read the file."},
                {"type": "file", "file": {"file_id": file_id}},
            ]
        return self.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": [{"role": "user", "content": content}]},
        )


def without(text: str, ident: str) -> str:
    return text.replace(ident, "<id>")


def check_isolation(
    outsider: Caller, others: dict[str, str], missing: str = "file-" + "0" * 24
) -> None:
    """Step 2's assertion, apart so the sabotage run can expect it to fail:
    `outsider` lists none of `others` (id -> whose), and asking for one, its
    content, or its deletion is the same 404 as asking for an id that does not
    exist."""
    seen = outsider.listed()
    foreign = [ident for ident in seen if ident in others]
    assert not foreign, f"listed another owner's files: {[others[i] for i in foreign]}"
    for method, suffix in (("GET", ""), ("GET", "/content"), ("DELETE", "")):
        none = outsider.files(method, f"/{missing}{suffix}")
        for ident in others:
            theirs = outsider.files(method, f"/{ident}{suffix}")
            assert theirs.status_code == none.status_code == 404, (
                f"{method} {suffix or 'file'} of {others[ident]}'s: {theirs.status_code}"
            )
            assert without(theirs.text, ident) == without(none.text, missing), theirs.text


def store_rows(
    store_dir: Path, owner: str | None = None, name: str = "store.sqlite3"
) -> list[tuple[str, str, str]]:
    path = store_dir / name
    # Read-only, beside the running store; `as_uri` spells a Windows path too.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        query = "SELECT id, owner, sha256 FROM files"
        rows = connection.execute(
            query + (" WHERE owner = ?" if owner else ""), (owner,) if owner else ()
        ).fetchall()
    finally:
        connection.close()
    return [tuple(row) for row in rows]


def blob_names(store_dir: Path) -> set[str]:
    root = store_dir / "blobs"
    return {p.name for p in root.rglob("*") if p.is_file()} if root.is_dir() else set()


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def exercise(directory: Path, sabotage: bool) -> None:
    install = Install(directory)
    store_dir = directory / "agent" / "store"
    try:
        # ---------------------------------------------------------------- #
        # A root, its people, an app and its key, and a plain key
        # ---------------------------------------------------------------- #
        install.start("control")
        assert install.call(
            "control", "POST", "/v1/auth/initialize", json={"passphrase": install.passphrase}
        ).status_code == 204
        login = install.call(
            "control", "POST", "/v1/auth/login", json={"passphrase": install.passphrase}
        )
        assert login.status_code == 200, login.text
        root = str(login.json()["sessionToken"])
        app = install.call(
            "control",
            "POST",
            "/v1/oidc/clients",
            root,
            json={"name": "Workbench", "owner": APP_OWNER, "redirectUris": [CALLBACK]},
        )
        assert app.status_code == 201, app.text
        limits = {"allowedModels": [MODEL], "requestsPerMinute": 1000, "maxConcurrentRequests": 8}
        app_key = install.call(
            "control",
            "POST",
            "/v1/auth/client-keys",
            root,
            json={"name": APP_OWNER, "limits": limits},
        )
        assert app_key.status_code == 201, app_key.text
        plain_key = install.call(
            "control", "POST", "/v1/auth/client-keys", root, json={"name": "Open WebUI", "limits": limits}
        )
        assert plain_key.status_code == 201, plain_key.text
        people = {}
        for name in ("Ann", "Ben"):
            made = install.call(
                "control",
                "POST",
                "/v1/people",
                root,
                json={
                    "name": name,
                    "password": PASSWORD,
                    "apps": [app.json()["client"]["clientId"]],
                },
            )
            assert made.status_code == 201, made.text
            people[name] = made.json()

        # ---------------------------------------------------------------- #
        # The root's agent: it declares and starts the store by itself
        # ---------------------------------------------------------------- #
        agent_dir = directory / "agent"
        agent_dir.mkdir(exist_ok=True)
        (agent_dir / "machine-port").write_text(str(install.ports["machine"]), encoding="utf-8")
        (agent_dir / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": install.url("agent"),
                    "securityMode": "prompt_on_startup",
                    # The install's control root, which this agent runs beside:
                    # a root set up before the store existed.
                    "components": [
                        {
                            "name": "control",
                            "kind": "control",
                            "url": install.url("control"),
                            "safeMode": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        install.start("agent")
        initialized = install.call(
            "agent", "POST", "/v1/auth/initialize", json={"passphrase": install.passphrase}
        )
        assert initialized.status_code == 200, initialized.text
        join = install.call(
            "control", "POST", "/v1/nodes/join-token", root, json={"grants": ["gateway"]}
        )
        assert join.status_code in (200, 201), join.text
        enrolled = install.call(
            "agent",
            "POST",
            "/v1/node/enroll",
            initialized.json()["sessionToken"],
            json={
                "controlUrl": install.url("control"),
                "token": join.json()["token"],
                "name": "root",
            },
        )
        assert enrolled.status_code == 200, enrolled.text
        install.wait(lambda: (agent_dir / "trust_bundle.json").is_file(), "the agent's bundle")
        operator = install.call(
            "agent", "POST", "/v1/auth/login", json={"passphrase": install.passphrase}
        )
        assert operator.status_code == 200, operator.text
        session = str(operator.json()["sessionToken"])

        def components() -> dict[str, dict[str, Any]]:
            listed = install.call("agent", "GET", "/v1/components", session).json()
            return {c["name"]: c for c in listed["components"]}

        install.wait(lambda: components()["store"]["kind"] == "store", "the store declared")
        store = components()["store"]
        assert store["spawn"]["configFile"].endswith("store.yaml"), store
        install.wait(
            lambda: install.call("agent", "GET", "/api/proxy/store/healthz").status_code == 200,
            "the store answering through the agent",
        )
        ok("the root's agent declared the store by itself and started it, on loopback")

        # ---------------------------------------------------------------- #
        # A backend, its driver and the gateway, beside the agent
        # ---------------------------------------------------------------- #
        install.start("fixture")
        model_dir = directory / "model"
        model_dir.mkdir(exist_ok=True)
        (model_dir / "bootstrap.json").write_text(
            json.dumps(bootstrap_for(agent_dir, install.url("agent"), "inference-driver")),
            encoding="utf-8",
        )
        (model_dir / "driver.yaml").write_text(
            yaml.safe_dump(
                {
                    "provider": "openai_compat_custom",
                    "baseUrl": install.url("fixture") + "/model",
                    "modelId": MODEL,
                    "backendLocality": "local",
                }
            ),
            encoding="utf-8",
        )
        install.start("model")
        declared = install.call(
            "agent",
            "POST",
            "/v1/components",
            session,
            json={"name": "row53-model", "kind": "inference-driver", "url": install.url("model")},
        )
        assert declared.status_code == 201, declared.text
        gateway_dir = directory / "gateway"
        gateway_dir.mkdir(exist_ok=True)
        (gateway_dir / "bootstrap.json").write_text(
            json.dumps(bootstrap_for(agent_dir, install.url("agent"), "gateway")),
            encoding="utf-8",
        )
        (gateway_dir / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        install.start("gateway")
        tokens = {name: install.sign_in(app.json(), name) for name in ("Ann", "Ben")}
        ann = Caller(install, app_key.json()["token"], tokens["Ann"])
        ben = Caller(install, app_key.json()["token"], tokens["Ben"])
        key = Caller(install, plain_key.json()["token"])
        install.wait(lambda: key.chat().status_code == 200, "the model routable", seconds=90)

        # ---------------------------------------------------------------- #
        # 1. Ann keeps two files and uses one in a chat
        # ---------------------------------------------------------------- #
        small = ann.keep("notes.txt", MARKER.encode())
        assert small.status_code == 200, small.text
        notes = small.json()
        assert notes["object"] == "file" and notes["bytes"] == len(MARKER.encode()), notes
        assert notes["expires_at"] is None, notes  # kept until deleted, as OpenAI keeps
        big = os.urandom(40 * MIB)
        upload = ann.post(
            "/v1/uploads",
            json={
                "bytes": len(big),
                "filename": "big.bin",
                "mime_type": "application/octet-stream",
                "purpose": "batch",
            },
        )
        assert upload.status_code == 200, upload.text
        upload_id = upload.json()["id"]
        parts = []
        for start, end in ((0, 16 * MIB), (16 * MIB, 32 * MIB), (32 * MIB, 40 * MIB)):
            added = ann.post(
                f"/v1/uploads/{upload_id}/parts", files={"data": ("part", big[start:end])}
            )
            assert added.status_code == 200, added.text
            parts.append(added.json()["id"])
        done = ann.post(
            f"/v1/uploads/{upload_id}/complete",
            json={"part_ids": parts, "md5": hashlib.md5(big, usedforsecurity=False).hexdigest()},
        )
        assert done.status_code == 200, done.text
        large = done.json()["file"]
        assert done.json()["status"] == "completed" and large["bytes"] == 40 * MIB, done.text
        assert set(ann.listed()) == {notes["id"], large["id"]}
        read_small = ann.files("GET", f"/{notes['id']}/content")
        read_large = ann.files("GET", f"/{large['id']}/content")
        assert read_small.content == MARKER.encode(), read_small.text[:200]
        assert hashlib.sha256(read_large.content).digest() == hashlib.sha256(big).digest()
        ok("step 1: Ann kept a file in one request and 40 MiB in three parts, listed and read both")

        before = len(install.client.get(install.url("fixture") + "/seen").json())
        chatted = ann.chat(notes["id"])
        assert chatted.status_code == 200, chatted.text
        seen = install.client.get(install.url("fixture") + "/seen").json()
        assert len(seen) == before + 1, seen
        assert MARKER in json.dumps(seen[-1]["messages"]), seen[-1]
        assert notes["id"] not in json.dumps(seen[-1]), "the id reached the backend"
        ok("step 1: a chat naming Ann's file reached the backend with its words inline")

        # ---------------------------------------------------------------- #
        # 2. Ben sees nothing of Ann's
        # ---------------------------------------------------------------- #
        missing = "file-" + "0" * 24
        anns = {notes["id"]: "Ann", large["id"]: "Ann"}
        assert ben.listed() == []
        check_isolation(ben, anns)
        assert set(ann.listed()) == set(anns), "Ben's delete reached Ann's files"
        assert ann.files("GET", f"/{notes['id']}/content").content == MARKER.encode()
        asked = len(install.client.get(install.url("fixture") + "/seen").json())
        theirs, none = ben.chat(notes["id"]), ben.chat(missing)
        assert theirs.status_code == none.status_code == 400, (theirs.text, none.text)
        assert without(theirs.text, notes["id"]) == without(none.text, missing), theirs.text
        assert MARKER not in theirs.text
        # Refused before any backend was asked.
        assert len(install.client.get(install.url("fixture") + "/seen").json()) == asked
        ok("step 2: Ben's list is empty, and Ann's ids read to him as ids that do not exist")

        # ---------------------------------------------------------------- #
        # 3. The plain key's files are its own
        # ---------------------------------------------------------------- #
        kept = key.keep("key.txt", b"the key's own words")
        assert kept.status_code == 200, kept.text
        keys = {kept.json()["id"]: "the plain key"}
        assert key.listed() == [kept.json()["id"]]
        check_isolation(key, anns)
        check_isolation(ann, keys)
        check_isolation(ben, keys)
        owners = {o["owner"] for o in install.call("agent", "GET", "/api/proxy/store/v1/owners", session).json()["owners"]}
        assert owners == {
            f"person:{people['Ann']['id']}",
            f"key:{plain_key.json()['key']['id']}",
        }, owners
        ok("step 3: the plain key's files are its own, and each person's are theirs")

        # ---------------------------------------------------------------- #
        # 4. A file kept for one second is gone after the sweep
        # ---------------------------------------------------------------- #
        too_short = key.keep(
            "short.txt",
            b"x",
            **{"expires_after[anchor]": "created_at", "expires_after[seconds]": "1"},
        )
        assert too_short.status_code == 400, too_short.text
        hour = key.keep(
            "hour.txt",
            b"an hour " + secrets.token_bytes(8),
            **{"expires_after[anchor]": "created_at", "expires_after[seconds]": "3600"},
        )
        assert hour.status_code == 200, hour.text
        assert hour.json()["expires_at"] == hour.json()["created_at"] + 3600
        # The store's own end, as the gateway would ask it, in one second.
        gateway_token = bootstrap_for(agent_dir, install.url("agent"), "gateway")["service_token"]
        brief = install.client.post(
            install.url("agent") + "/api/proxy/store/v1/files",
            params={"filename": "brief.txt", "purpose": "user_data", "expiresAfterSeconds": 1},
            content=b"gone in a second " + secrets.token_bytes(16),
            headers={
                "Authorization": f"Bearer {gateway_token}",
                "X-Eugene-Plexus-Owner": f"key:{plain_key.json()['key']['id']}",
                "Content-Type": "application/octet-stream",
            },
        )
        assert brief.status_code == 201, brief.text
        brief_id = brief.json()["id"]
        brief_blob = next(sha for ident, _, sha in store_rows(store_dir) if ident == brief_id)
        assert brief_blob in blob_names(store_dir)
        time.sleep(2.2)
        assert key.files("GET", f"/{brief_id}").status_code == 404
        swept = install.call("agent", "POST", "/api/proxy/store/v1/sweep", session)
        assert swept.status_code == 200, swept.text
        assert swept.json()["files"] >= 1, swept.text
        assert brief_id not in {ident for ident, _, _ in store_rows(store_dir)}
        assert brief_blob not in blob_names(store_dir)
        ok(
            "step 4: files are kept until deleted; expires_after takes OpenAI's bounds; a file "
            "kept for one second is gone after the sweep, from the database and the disk"
        )

        # ---------------------------------------------------------------- #
        # 5. Ann is removed: hidden at the next sweep, then deleted now
        # ---------------------------------------------------------------- #
        ann_owner = f"person:{people['Ann']['id']}"
        ann_rows = store_rows(store_dir, ann_owner)
        ann_blobs = {sha for _, _, sha in ann_rows}
        assert len(ann_blobs) == 2 and ann_blobs <= blob_names(store_dir)
        ben_kept = ben.keep("ben.txt", b"Ben's own words " + secrets.token_bytes(8))
        assert ben_kept.status_code == 200, ben_kept.text
        # A copy beside the store, as a migration keeps one (`schema-N.bak`).
        copy = "store.sqlite3.schema-1.bak"
        shutil.copyfile(store_dir / "store.sqlite3", store_dir / copy)
        assert len(store_rows(store_dir, ann_owner, copy)) == 2
        removed = install.call("control", "DELETE", f"/v1/people/{people['Ann']['id']}", root)
        assert removed.status_code == 204, removed.text
        swept = install.call("agent", "POST", "/api/proxy/store/v1/sweep", session)
        assert swept.status_code == 200, swept.text
        assert swept.json()["removal"]["hidden"] == 1, swept.text
        assert swept.json()["removal"]["deleted"] == 0, swept.text
        # Hidden, not deleted: on disk, and answered as ids that do not exist.
        assert store_rows(store_dir, ann_owner) == ann_rows
        assert ann_blobs <= blob_names(store_dir)

        def as_store(owner: str, path: str) -> httpx.Response:
            return install.client.get(
                install.url("agent") + "/api/proxy/store/v1/files" + path,
                headers={"Authorization": f"Bearer {gateway_token}", "X-Eugene-Plexus-Owner": owner},
            )

        absent = as_store(ann_owner, f"/{missing}")
        for ident, _, _ in ann_rows:
            for suffix in ("", "/content"):
                hers = as_store(ann_owner, f"/{ident}{suffix}")
                assert hers.status_code == absent.status_code == 404, hers.text
                assert without(hers.text, ident) == without(absent.text, missing), hers.text
        assert as_store(ann_owner, "").json()["data"] == []
        check_isolation(ben, anns)
        install.wait(
            lambda: ann.files("GET").status_code == 401, "Ann's token refused at the gateway"
        )
        listed = install.call("agent", "GET", "/api/proxy/store/v1/owners", session).json()
        entry = next(o for o in listed["owners"] if o["owner"] == ann_owner)
        assert entry["files"] == 2 and entry["deleteAt"] - entry["removedAt"] == 30 * 86400, entry
        assert "removedAt" not in next(
            o for o in listed["owners"] if o["owner"] == f"person:{people['Ben']['id']}"
        )
        ok(
            "step 5: Ann removed at the root: her files are hidden from her and from Ben, still "
            "on disk, and the console shows her delete date 30 days on"
        )
        deleted = install.call(
            "agent",
            "POST",
            "/api/proxy/store/v1/removals/delete",
            session,
            json={"owner": ann_owner},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["files"] == 2 and deleted.json()["removal"]["deleted"] == 1
        assert store_rows(store_dir, ann_owner) == []
        assert store_rows(store_dir, ann_owner, copy) == [], "the copy still holds Ann's rows"
        assert not ann_blobs & blob_names(store_dir), "a removed person's blob is still on disk"
        assert ben.listed() == [ben_kept.json()["id"]]
        assert set(key.listed()) == {kept.json()["id"], hour.json()["id"]}
        ok("step 5: Delete now: Ann's rows, blobs and copy rows are gone; Ben's and the key's stay")

        # ---------------------------------------------------------------- #
        # 6. The store stopped: files are a 503 naming the cause; chat answers
        # ---------------------------------------------------------------- #
        stopped = install.call("agent", "DELETE", "/v1/components/store", session)
        assert stopped.status_code in (200, 204), stopped.text
        install.wait(
            lambda: install.call("agent", "GET", "/api/proxy/store/healthz").status_code != 200,
            "the store gone",
        )
        down = key.files("GET")
        assert down.status_code == 503, down.text
        message = down.json()["error"]["message"]
        assert message.startswith("Eugene's store is not answering: "), message
        assert "store" in message.split(": ", 1)[1], message
        assert key.chat().status_code == 200
        ok(f"step 6: with the store stopped, files are a 503 naming the cause ({message[:120]}...)")

        if not sabotage:
            return

        # ---------------------------------------------------------------- #
        # 7. Sabotage: a store whose listing drops the owner filter
        # ---------------------------------------------------------------- #
        for broken, what in (
            ("listing", "a listing without its owner filter"),
            ("lookup", "a read, content and delete by id without the owner filter"),
        ):
            sabotaged_dir = directory / broken
            sabotaged_dir.mkdir(exist_ok=True)
            (sabotaged_dir / "bootstrap.json").write_text(
                json.dumps(bootstrap_for(agent_dir, install.url("agent"), "store")),
                encoding="utf-8",
            )
            install.start(broken, f"store-sabotaged-{broken}")
            declared = install.call(
                "agent",
                "POST",
                "/v1/components",
                session,
                json={"name": "store", "kind": "store", "url": install.url(broken)},
            )
            assert declared.status_code == 201, declared.text
            install.wait(lambda: key.files("GET").status_code == 200, f"the {broken} sabotage in use")
            planted = key.keep("planted.txt", b"the key's planted words")
            assert planted.status_code == 200, planted.text
            with must_fail(f"step 2's isolation check against {what}"):
                check_isolation(ben, {planted.json()["id"]: "the plain key"})
            removed = install.call("agent", "DELETE", "/v1/components/store", session)
            assert removed.status_code in (200, 204), removed.text
            install.processes[broken].terminate()
            install.processes[broken].wait(timeout=15)
    finally:
        install.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--sabotage", action="store_true", help="also run step 7 against a broken listing"
    )
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
        return 0
    with tempfile.TemporaryDirectory(prefix="ep-row53-", ignore_cleanup_errors=True) as tmp:
        directory = Path(tmp)
        try:
            exercise(directory, args.sabotage)
        except BaseException:
            for log in sorted(directory.glob("**/process.log")):
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                print(f"--- {log.parent.name} ---", *tail, sep="\n")
            store_log = directory / "agent" / "logs"
            for log in sorted(store_log.glob("*.log")) if store_log.is_dir() else []:
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                print(f"--- {log.name} ---", *tail, sep="\n")
            raise
    print(f"{len(PASSES)} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
