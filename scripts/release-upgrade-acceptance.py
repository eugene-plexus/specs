"""In-place UPGRADE acceptance on Windows: an installed release, then the candidate over it.

Installs the FROM release into a fresh prefix, sets Eugene up as the root, installs
Workbench, seeds a second person, a chat with a real model reply, a memory note and a
document through the FROM release's own APIs, stops the agent, runs the TO installer
over the SAME prefix, starts the candidate agent with the same config and checks that
everything survived and that every installed commit equals release/manifest.json.

Needs httpx and PyYAML. Isolated: a contiguous port range claimed by binding, no proxy,
no EUGENE_PLEXUS_* variable, the CPU/ports fixture of s10, and an app port range off 8190.
The live service (EugenePlexusAgent) and the account's environment are snapshotted
before and after. Windows only; nothing is elevated.
"""

from __future__ import annotations

import argparse
import hashlib
import html
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
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

HERE = Path(__file__).resolve().parent
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
COMPONENTS = (
    "agent",
    "control",
    "gateway",
    "inference-driver",
    "library",
    "tool-driver",
    "ui",
)
PASSPHRASE = "upgrade-acceptance-" + secrets.token_urlsafe(12)
SECOND = {
    "name": "morgan",
    "password": "morgan-" + secrets.token_urlsafe(12),
    "displayName": "Morgan Upgrade",
}
NOTE = "The upgrade acceptance note: my favourite colour is teal."
DOC_NAME = "upgrade-acceptance.md"
DOC_BODY = (
    "# Upgrade acceptance document\n\nThe lighthouse keeper logged forty-two ships on "
    "Tuesday.\n\nSecond paragraph about the tide tables and the harbour bell.\n"
) * 3
TITLE = "Upgrade acceptance chat"
PROMPT = "Name one colour of the rainbow in a single short sentence."
FOLLOWUP = "Now name a different colour in a single short sentence."

OUT: Path
LOG = None
CHECKS: list[dict] = []
RESULT: dict = {"checks": CHECKS}


def say(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    if LOG:
        LOG.write(line + "\n")
        LOG.flush()


def check(name: str, ok: bool, detail=None) -> bool:
    CHECKS.append({"name": name, "passed": bool(ok), "detail": detail})
    say(
        f"{'PASS' if ok else 'FAIL'}: {name}"
        + ("" if detail is None else f"  [{detail}]")
    )
    return bool(ok)


def wait(predicate, label: str, seconds: float = 120, step: float = 1.0):
    deadline = time.perf_counter() + seconds
    last = None
    while time.perf_counter() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (httpx.HTTPError, AssertionError, KeyError, ValueError) as exc:
            last = exc
        time.sleep(step)
    raise AssertionError(
        f"Timed out ({seconds:.0f}s): {label}" + (f" ({last})" if last else "")
    )


def powershell(command: str) -> str:
    return subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-Command", command],
        text=True,
        stdin=subprocess.DEVNULL,
    )


def snapshot_live() -> dict:
    command = """
    $result = @{env=@{}; service=@()}
    foreach ($scope in @('User','Machine')) {
      $result.env[$scope] = @{}
      [Environment]::GetEnvironmentVariables($scope).GetEnumerator() |
        Where-Object { $_.Key -like 'EUGENE_PLEXUS_*' } |
        ForEach-Object { $result.env[$scope][$_.Key] = $_.Value }
    }
    $result.service = @(Get-CimInstance Win32_Service -Filter "Name='EugenePlexusAgent'" |
      Select-Object Name,State,ProcessId,PathName)
    $result | ConvertTo-Json -Depth 5 -Compress
    """
    return json.loads(powershell(command))


def prefix_processes(prefix: Path) -> list[dict]:
    """Processes whose executable or command line is under the prefix (for stragglers)."""
    needle = str(prefix).replace("'", "''")
    command = (
        "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -like '*"
        + needle
        + "*' -or $_.ExecutablePath -like '"
        + needle
        + "*') } | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    text = powershell(command).strip()
    if not text:
        return []
    found = json.loads(text)
    return found if isinstance(found, list) else [found]


GUARD = re.compile(
    r"    if \(Test-Path -LiteralPath \$Prefix\) \{\r?\n"
    r'        Die "-Isolated requires a new prefix; the target already exists"\r?\n    \}\r?\n'
)


def in_place_installer(source: Path, target: Path) -> Path:
    """The candidate installer with ONE guard removed: -Isolated refuses an existing prefix.

    -Update (the agent's own upgrade path) refuses when this machine's autostart runs a
    different install, and an ordinary run changes the account's persistent environment;
    neither may be used beside the live service. Every other line is the shipped text.
    """
    text = source.read_text(encoding="utf-8")
    patched, count = GUARD.subn("", text)
    assert count == 1, "the -Isolated new-prefix guard was not found exactly once"
    target.write_text(patched, encoding="utf-8", newline="")
    return target


def claim_ports() -> int:
    held: list[socket.socket] = []
    for base in range(19000, 29000, 100):
        try:
            for port in range(base, base + 24):
                sock = socket.socket()
                held.append(sock)
                sock.bind(("127.0.0.1", port))
            break
        except OSError:
            for sock in held:
                sock.close()
            held = []
    assert held, "no free test port range"
    for sock in held:
        sock.close()
    return base


class Install:
    """One isolated prefix and the environment everything in it runs with."""

    def __init__(self, root: Path, base: int):
        self.root, self.base = root, base
        self.prefix = root / "install"
        self.agent_port = base + 1
        self.urls = {
            "agent": f"http://127.0.0.1:{base + 1}",
            "control": f"http://127.0.0.1:{base + 2}",
            "gateway": f"http://127.0.0.1:{base + 3}",
            "library": f"http://127.0.0.1:{base + 4}",
        }
        self.python = self.prefix / "venv/Scripts/python.exe"
        self.proc: subprocess.Popen | None = None
        self.install_env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith("EUGENE_PLEXUS_")
            and k.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
        }
        self.install_env.update(
            {
                "NO_PROXY": "localhost,127.0.0.1,::1",
                "UV_NO_CACHE": "1",
                "PYTHONUTF8": "1",
            }
        )
        self.env = dict(self.install_env)
        self.env.update(
            {
                "HOME": str(self.prefix),
                "USERPROFILE": str(self.prefix),
                "PYTHONPATH": str(root / "fixture"),
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(self.prefix / "engines"),
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(self.prefix / "agent.yaml"),
                "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(self.agent_port),
                "CUDA_VISIBLE_DEVICES": "-1",
            }
        )

    def run_installer(self, installer: Path, tag: str) -> float:
        started = time.perf_counter()
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer),
            "-Prefix", str(self.prefix), "-NoService", "-NoStart", "-Isolated",
        ]  # fmt: skip
        with (self.root / f"installer-{tag}.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                command, env=self.install_env, cwd=self.root, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, check=True, timeout=1500,
            )  # fmt: skip
        return time.perf_counter() - started

    def write_fixture(self) -> None:
        fixture = self.root / "fixture"
        fixture.mkdir(exist_ok=True)
        base = self.base
        # s10's CPU fixture, plus the app port range moved off 8190. A Workbench
        # process inherits PYTHONPATH too, but has no agent package: it skips this.
        (fixture / "sitecustomize.py").write_text(
            """
try:
    from eugene_plexus_agent.engines import host, devices
except ModuleNotFoundError:
    host = None
if host is not None:
    from eugene_plexus_agent.engines import gpu_probe as agent_gpu_probe
    from eugene_plexus_agent import state, apps
    from eugene_plexus_library import hardware
    from eugene_plexus_library import gpu_probe as library_gpu_probe
    agent_gpu_probe.adapters = lambda *args, **kw: []
    library_gpu_probe.adapters = lambda *args, **kw: []
    host._detect_accelerator = lambda *args: (host.Accelerator.none, None)
    _detect = devices.detect_devices
    devices.detect_devices = lambda **kw: _detect(run=lambda argv: None)
    hardware._nvidia_gpus = lambda warnings: []
    hardware._amd_gpus = lambda warnings: []
    hardware._intel_gpus = lambda warnings: []
"""
            + f"    state._RUNTIME_PORT_BASE = {base + 10}\n    state._RUNTIME_PORT_SPAN = 10\n"
            + f"    apps.APP_PORT_BASE = {base + 20}\n    apps.APP_PORT_SPAN = 4\n",
            encoding="utf-8",
            newline="\n",
        )
        (self.prefix / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "components": [
                        {
                            "name": name,
                            "kind": name,
                            "url": self.urls[name],
                            "spawn": {"configFile": str(self.prefix / f"{name}.yaml")},
                        }  # fmt: skip
                        for name in ("control", "gateway", "library")
                    ]
                }
            ),
            encoding="utf-8",
            newline="\n",
        )

    def start_agent(self, tag: str) -> None:
        (self.prefix / "stop").unlink(missing_ok=True)
        log = (self.root / f"agent-{tag}.log").open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(self.python), str(HERE / "s8-ui-acceptance.py"), "--serve", str(self.prefix),
             "--port", str(self.agent_port)],
            cwd=self.prefix, env=self.env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=FLAGS,
        )  # fmt: skip
        with httpx.Client(trust_env=False, timeout=5) as client:

            def up() -> bool:
                assert self.proc and self.proc.poll() is None, "agent exited"
                return client.get(self.urls["agent"] + "/healthz").status_code == 200

            wait(up, "agent healthz", 120, 0.3)

    def stop_agent(self) -> dict:
        """Stop through the stop file; report processes still under the prefix afterwards."""
        assert self.proc
        (self.prefix / "stop").touch()
        try:
            self.proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None
        time.sleep(3)
        left = prefix_processes(self.prefix)
        for process in left:
            subprocess.run(
                ["taskkill", "/PID", str(process["ProcessId"]), "/T", "/F"],
                capture_output=True,
            )
        if left:
            time.sleep(2)
        (self.prefix / "stop").unlink(missing_ok=True)
        return {"stragglersKilled": [(p["ProcessId"], p["Name"]) for p in left]}

    def commits(self) -> dict[str, str]:
        found = {}
        site = self.prefix / "venv/Lib/site-packages"
        for name in COMPONENTS:
            for info in site.glob(
                f"eugene_plexus_{name.replace('-', '_')}-*.dist-info"
            ):
                data = json.loads(
                    (info / "direct_url.json").read_text(encoding="utf-8")
                )
                match = re.search(r"/archive/([0-9a-f]{40})\.tar\.gz", data["url"])
                found[name] = match.group(1) if match else data["url"]
        return found

    def workbench_db(self) -> Path | None:
        found = sorted(self.prefix.rglob("workbench.sqlite3"))
        return found[0] if found else None

    def workbench_schema(self) -> int | None:
        db = self.workbench_db()
        if db is None:
            return None
        copy = Path(tempfile.mkdtemp(prefix="wbdb-"))
        try:
            for part in db.parent.glob(db.name + "*"):
                if part.name == db.name or part.name.endswith(("-wal", "-shm")):
                    shutil.copy2(part, copy / part.name)
            with sqlite3.connect(copy / db.name) as conn:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = 'schema'"
                ).fetchone()
            return int(row[0]) if row else None
        finally:
            shutil.rmtree(copy, ignore_errors=True)


class Api:
    """Thin httpx wrapper that names what a failed call said."""

    def __init__(self):
        self.client = httpx.Client(timeout=120, trust_env=False, follow_redirects=False)

    def call(self, base, method, path, token=None, body=None, expected=(200,), **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        headers.update(kw.pop("headers", {}))
        response = self.client.request(
            method, base + path, headers=headers, json=body, **kw
        )
        if response.status_code not in expected:
            raise AssertionError(
                f"{method} {path}: {response.status_code} {response.text[:600]}"
            )
        if response.content and "json" in response.headers.get("content-type", ""):
            return response.json()
        return response


def setup_root(ctx: Install, api: Api) -> str:
    """Wizard order: agent passphrase, control passphrase, enroll this agent as root."""
    agent, control = ctx.urls["agent"], ctx.urls["control"]
    api.call(agent, "POST", "/v1/auth/initialize", body={"passphrase": PASSPHRASE})
    wait(
        lambda: api.client.get(control + "/healthz").status_code in (200, 503),
        "control up",
        120,
    )
    wait(
        lambda: api.call(control, "POST", "/v1/auth/initialize", body={"passphrase": PASSPHRASE}, expected=(204, 409)),
        "control initialize", 120,
    )  # fmt: skip
    control_token = wait(
        lambda: api.call(control, "POST", "/v1/auth/login", body={"passphrase": PASSPHRASE})["sessionToken"],
        "control login", 60,
    )  # fmt: skip
    join = api.call(
        control, "POST", "/v1/nodes/join-token", control_token,
        {"nodeName": "upgrade-root", "grants": ["gateway"]}, expected=(201,),
    )["token"]  # fmt: skip
    token = api.call(agent, "POST", "/v1/auth/login", body={"passphrase": PASSPHRASE})[
        "sessionToken"
    ]
    api.call(
        agent,
        "POST",
        "/v1/node/enroll",
        token,
        {"controlUrl": control, "token": join, "name": "upgrade-root"},
    )
    for base in (agent, control):
        wait(
            lambda b=base: api.client.get(b + "/healthz").status_code == 200,
            base + " after enrol",
            120,
        )
    token = wait(
        lambda: api.call(agent, "POST", "/v1/auth/login", body={"passphrase": PASSPHRASE})["sessionToken"], "agent login", 60
    )  # fmt: skip
    api.call(
        agent,
        "PATCH",
        "/v1/config",
        token,
        {"firstRunComplete": True, "updateChecks": False},
    )
    return token


def sign_in(api: Api, base: str) -> dict:
    """Eugene sign-in as the operator; returns the headers Workbench's API wants."""
    start = api.client.get(base + "/signin")
    assert start.status_code == 302, f"/signin {start.status_code} {start.text[:200]}"
    provider = api.client.get(start.headers["location"])
    assert provider.status_code == 200, f"provider page {provider.status_code}"
    fields = {
        m.group(1): html.unescape(m.group(2))
        for m in re.finditer(
            r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', provider.text
        )
    }
    fields.update(name="operator", password=PASSPHRASE)
    approved = api.client.post(
        urlsplit(start.headers["location"])._replace(query="").geturl(), data=fields
    )
    assert approved.status_code in (302, 303), (
        f"approve {approved.status_code} {approved.text[:200]}"
    )
    location = api.client.get(approved.headers["location"]).headers.get("location", "")
    assert "#signin=" in location, location
    return {"Origin": base, "X-Workbench-Secret": location.split("#signin=", 1)[1]}


def workbench_up(
    ctx: Install, api: Api, token: str, seconds: float = 900
) -> tuple[dict, str]:
    def running():
        app = api.call(ctx.urls["agent"], "GET", "/v1/apps/workbench", token)
        return app if app["status"] == "running" else None

    app = wait(running, "Workbench running", seconds, 2)
    base = f"http://127.0.0.1:{app['port']}"
    wait(
        lambda: api.client.get(base + "/healthz").status_code == 200,
        "Workbench healthz",
        60,
    )
    return app, base


def wait_install(ctx: Install, api: Api, token: str, seconds: float = 900) -> dict:
    def finished():
        progress = api.call(
            ctx.urls["agent"], "GET", "/v1/apps/workbench/install", token
        )
        return (
            progress if progress["state"] in {"done", "failed", "cancelled"} else None
        )

    return wait(finished, "Workbench installation", seconds, 2)


def launch_model(ctx: Install, api: Api, token: str, model: Path) -> str:
    """The console's Run: the Library's run-operation for the model; answer the engine question."""
    library = ctx.urls["library"]
    api.call(library, "PATCH", "/v1/config", token, {"modelRoots": [str(model.parent)]})
    api.call(library, "POST", "/v1/scan", token, {}, expected=(200, 202))
    found = wait(
        lambda: next(
            (m for m in api.call(library, "GET", "/v1/models", token)["models"] if m["path"].endswith(model.name)), None
        ),
        "library finds the seed model", 120, 2,
    )  # fmt: skip
    # An enrolled node runs the operations assigned to its own name.
    node = api.call(ctx.urls["agent"], "GET", "/v1/node", token)["name"]
    op_id = "upgrade-run-" + secrets.token_hex(4)
    api.call(
        library,
        "PUT",
        f"/v1/run-operations/{op_id}",
        token,
        {"node": node, "modelId": found["id"]},
        expected=(202,),
    )
    answered = False
    started = time.perf_counter()
    while True:
        op = api.call(library, "GET", f"/v1/run-operations/{op_id}", token)
        if op["step"] == "awaiting-install" and not answered:
            api.call(
                library,
                "POST",
                f"/v1/run-operations/{op_id}/answer",
                token,
                {"answer": "install"},
            )
            answered = True
        if op["step"] in ("ready", "failed", "skipped", "cancelled"):
            break
        assert time.perf_counter() - started < 1500, (
            f"run operation stuck at {op['step']}"
        )
        time.sleep(2)
    RESULT["runOperation"] = {
        k: op.get(k)
        for k in ("step", "engine", "runtime", "runtimeStatus", "error", "failedStep")
    }
    assert op["step"] == "ready", f"run operation ended {op['step']}: {op.get('error')}"
    return op["runtime"]


def ready_model_id(
    wb: httpx.Client, base: str, headers: dict, seconds: float = 300
) -> str:
    def find():
        models = wb.get(base + "/api/models", headers=headers).json()["models"]
        return next((m["id"] for m in models if m["ready"] or m["onDemand"]), None)

    return wait(find, "a ready model in Workbench", seconds, 3)


def ask(
    api: Api, base: str, headers: dict, chat_id: str, model: str, text: str
) -> dict:
    sent = api.call(base, "POST", f"/api/chats/{chat_id}/messages", None, {"content": text, "model": model},
                    expected=(201,), headers=headers)  # fmt: skip

    def finished():
        detail = api.call(base, "GET", f"/api/chats/{chat_id}", headers=headers)
        last = detail["messages"][-1]
        return (
            detail
            if last["role"] == "assistant"
            and last["status"] not in ("streaming", "running", "pending")
            else None
        )

    detail = wait(finished, "the model's reply", 900, 3)
    detail["sent"] = sent
    return detail


def chat_fingerprint(detail: dict) -> dict:
    return {
        "title": detail["chat"]["title"],
        "messages": [
            {k: m[k] for k in ("id", "role", "content", "status", "model")}
            for m in detail["messages"]
        ],
    }


def collect_state(
    api: Api, base: str, headers: dict, chat_id: str, note_id: str, doc_id: str
) -> dict:
    detail = api.call(base, "GET", f"/api/chats/{chat_id}", headers=headers)
    memory = api.call(base, "GET", "/api/memory", headers=headers)
    notes = [n for section in memory["sections"].values() for n in section]
    note = next((n for n in notes if n["id"] == note_id), None)
    documents = api.call(base, "GET", "/api/documents", headers=headers)["documents"]
    doc = next((d for d in documents if d["id"] == doc_id), None)
    original = api.client.get(
        base + f"/api/documents/{doc_id}/original", headers=headers
    )
    text = api.client.get(base + f"/api/documents/{doc_id}/text", headers=headers)
    return {
        "chat": chat_fingerprint(detail),
        "note": note and {k: note[k] for k in ("id", "text", "kind", "pinned")},
        "document": doc and {k: doc[k] for k in ("id", "name", "size", "mediaType")},
        "documentSha256": hashlib.sha256(original.content).hexdigest()
        if original.status_code == 200
        else None,
        "documentText": text.text if text.status_code == 200 else None,
        "me": api.call(base, "GET", "/api/me", headers=headers),
    }


def seed(ctx: Install, api: Api, token: str, model: Path) -> dict:
    agent, control = ctx.urls["agent"], ctx.urls["control"]
    control_token = api.call(
        control, "POST", "/v1/auth/login", body={"passphrase": PASSPHRASE}
    )["sessionToken"]
    person = api.call(
        control, "POST", "/v1/people", control_token, SECOND, expected=(201,)
    )
    check(
        "FROM: second person created in control",
        bool(person.get("id")),
        person.get("name"),
    )
    catalogue = api.call(agent, "GET", "/v1/app-catalogue", token)
    entry = next(
        row for row in catalogue["apps"] if row["manifest"]["id"] == "workbench"
    )
    RESULT["fromCatalogueWorkbench"] = entry["manifest"]["version"]
    api.call(agent, "POST", "/v1/apps/workbench/install", token, expected=(202,))
    progress = wait_install(ctx, api, token)
    assert progress["state"] == "done", progress
    app, base = workbench_up(ctx, api, token)
    check(
        "FROM: Workbench installed and running",
        True,
        f"{app.get('version')} on port {app['port']}",
    )
    RESULT["fromWorkbenchVersion"] = app.get("version")
    headers = sign_in(api, base)
    me = api.call(base, "GET", "/api/me", headers=headers)
    check("FROM: operator signs in to Workbench", True, me)

    runtime = launch_model(ctx, api, token, model)
    say(f"model runtime {runtime} ready")
    model_id = ready_model_id(api.client, base, headers)
    chat = api.call(
        base,
        "POST",
        "/api/chats",
        None,
        {"model": model_id},
        expected=(201,),
        headers=headers,
    )
    api.call(
        base,
        "PATCH",
        f"/api/chats/{chat['id']}",
        None,
        {"title": TITLE},
        headers=headers,
    )
    reply = None
    try:
        detail = ask(api, base, headers, chat["id"], model_id, PROMPT)
        last = detail["messages"][-1]
        reply = last["content"].strip() or None
        check(
            "FROM: the model completed an exchange",
            last["status"] == "done" and bool(reply),
            f"{last['status']}: {last['content'][:120]!r}",
        )
    except AssertionError as exc:
        check("FROM: the model completed an exchange", False, str(exc))
    note = api.call(base, "POST", "/api/memory/notes", None, {"text": NOTE, "kind": "fact", "pinned": True},
                    expected=(201,), headers=headers)["note"]  # fmt: skip
    uploaded = api.call(base, "POST", "/api/documents", None, expected=(201,), headers=headers,
                        files={"files": (DOC_NAME, DOC_BODY.encode(), "text/markdown")})  # fmt: skip
    doc_id = uploaded["documents"][0]["id"]
    wait(lambda: next((d for d in api.call(base, "GET", "/api/documents", headers=headers)["documents"]
                       if d["id"] == doc_id and d["state"] in ("searchable", "ready")), None), "document read", 180, 2)  # fmt: skip
    schema = ctx.workbench_schema()
    check("FROM: Workbench store is schema 17", schema == 17, schema)
    state = collect_state(api, base, headers, chat["id"], note["id"], doc_id)
    check("FROM: seeded chat, note and document read back", bool(state["note"] and state["document"]) and len(state["chat"]["messages"]) >= 2,
          {"messages": len(state["chat"]["messages"]), "title": state["chat"]["title"]})  # fmt: skip
    return {
        "personId": person["id"], "chatId": chat["id"], "noteId": note["id"], "docId": doc_id,
        "modelId": model_id, "runtime": runtime, "reply": reply, "schema": schema, "state": state,
        "operatorSub": me.get("sub") or me.get("id"),
    }  # fmt: skip


def verify(
    ctx: Install, api: Api, token: str, seeded: dict, manifest: dict, update: dict
) -> None:
    agent, control = ctx.urls["agent"], ctx.urls["control"]
    installed = ctx.commits()
    RESULT["toCommits"] = installed
    for name in COMPONENTS:
        check(f"TO: {name} commit equals manifest", installed.get(name) == manifest["components"][name],
              f"{(installed.get(name) or '-')[:12]} vs {manifest['components'][name][:12]}")  # fmt: skip
    app, base = workbench_up(ctx, api, token)
    version = app.get("version")
    # The Workbench the candidate's own catalogue names, not one written here.
    catalogue = api.call(agent, "GET", "/v1/app-catalogue", token)
    named = next(
        r["manifest"]["version"]
        for r in catalogue["apps"]
        if r["manifest"]["id"] == "workbench"
    )
    check("TO: Workbench is the catalogue's", version == named, f"{version} vs {named}")
    schema = ctx.workbench_schema()
    check("TO: Workbench store is schema 21", schema == 21, schema)
    RESULT["schemaAfter"] = schema
    backup = sorted(
        p.name for p in ctx.workbench_db().parent.glob("workbench.sqlite3.schema-*.bak")
    )
    check(
        "TO: migration kept a schema-17 backup",
        "workbench.sqlite3.schema-17.bak" in backup,
        backup,
    )
    control_token = api.call(
        control, "POST", "/v1/auth/login", body={"passphrase": PASSPHRASE}
    )["sessionToken"]
    check("TO: operator control login works without re-initialize", bool(control_token))
    people = api.call(control, "GET", "/v1/people", control_token)
    listed = [
        p
        for p in people.get("people", people if isinstance(people, list) else [])
        if p["id"] == seeded["personId"]
    ]
    check(
        "TO: second person still listed",
        len(listed) == 1 and listed[0]["name"] == SECOND["name"],
        listed and listed[0]["name"],
    )
    headers = sign_in(api, base)
    me = api.call(base, "GET", "/api/me", headers=headers)
    check("TO: operator signs in to Workbench again", True, me)
    before = seeded["state"]
    after = collect_state(
        api, base, headers, seeded["chatId"], seeded["noteId"], seeded["docId"]
    )
    check(
        "TO: same Workbench person (sub)",
        (me.get("sub") or me.get("id")) == seeded["operatorSub"],
        me.get("sub") or me.get("id"),
    )
    check("TO: chat title and every message identical", after["chat"] == before["chat"],
          {"before": len(before["chat"]["messages"]), "after": len(after["chat"]["messages"]), "title": after["chat"]["title"]})  # fmt: skip
    check("TO: memory note identical", after["note"] == before["note"], after["note"])
    check(
        "TO: document record identical",
        after["document"] == before["document"],
        after["document"],
    )
    check(
        "TO: document original bytes identical",
        after["documentSha256"] == before["documentSha256"],
        after["documentSha256"],
    )
    check(
        "TO: document text identical", after["documentText"] == before["documentText"]
    )
    RESULT["after"] = after
    if seeded["reply"]:
        try:
            runtimes = api.call(agent, "GET", "/v1/runtimes", token)["runtimes"]
            say(
                "runtimes after upgrade: "
                + json.dumps([(r["name"], r["status"]) for r in runtimes])
            )
            for r in runtimes:
                if r["status"] != "ready":
                    api.call(
                        agent,
                        "POST",
                        f"/v1/runtimes/{r['name']}/start",
                        token,
                        {},
                        expected=(200, 202, 409),
                    )
            model_id = ready_model_id(api.client, base, headers, 600)
            detail = ask(api, base, headers, seeded["chatId"], model_id, FOLLOWUP)
            last = detail["messages"][-1]
            old = [m["id"] for m in before["chat"]["messages"]]
            check("TO: a new message on the old chat gets a reply",
                  last["status"] == "done" and bool(last["content"].strip()) and [m["id"] for m in detail["messages"]][: len(old)] == old,
                  f"{last['status']}: {last['content'][:120]!r}")  # fmt: skip
        except AssertionError as exc:
            check("TO: a new message on the old chat gets a reply", False, str(exc))
    else:
        check("TO: new reply (skipped: FROM produced no reply)", True, "not verified")
    RESULT["update"] = update


def unlock(ctx: Install, api: Api) -> str:
    """A restarted agent and root are sealed under the default security mode: sign in, as a person does."""
    token = wait(
        lambda: api.call(ctx.urls["agent"], "POST", "/v1/auth/login", body={"passphrase": PASSPHRASE})["sessionToken"],
        "agent sign-in after restart", 120, 2,
    )  # fmt: skip
    wait(lambda: api.call(ctx.urls["control"], "POST", "/v1/auth/login", body={"passphrase": PASSPHRASE})["sessionToken"],
         "control sign-in after restart", 120, 2)  # fmt: skip
    return token


def run(args: argparse.Namespace) -> None:
    global OUT, LOG
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    assert not any(OUT.iterdir()), f"{OUT} is not empty"
    LOG = (OUT / "run.log").open("w", encoding="utf-8")
    manifest = json.loads(
        (HERE.parent / "release/manifest.json").read_text(encoding="utf-8")
    )
    assert sys.platform == "win32", "Windows only"
    before = snapshot_live()
    base = claim_ports()
    ctx = Install(OUT, base)
    api = Api()
    timings: dict[str, float] = {}
    RESULT.update({"ports": f"{base}-{base + 23}", "fromInstaller": str(args.from_installer),
                   "toInstaller": str(args.to_installer), "manifest": manifest["components"]})  # fmt: skip
    say(f"ports {base}-{base + 23}; agent {ctx.agent_port}; apps from {base + 20}")
    seeded: dict = {}
    try:
        # The seed model is copied into the run's own folder: nothing outside it is scanned.
        models = OUT / "models"
        models.mkdir()
        shutil.copyfile(args.model, models / args.model.name)
        model = models / args.model.name

        timings["installFromSeconds"] = ctx.run_installer(args.from_installer, "from")
        ctx.write_fixture()
        RESULT["fromCommits"] = ctx.commits()
        say(
            f"FROM installed in {timings['installFromSeconds']:.0f}s: "
            + json.dumps({k: v[:7] for k, v in RESULT["fromCommits"].items()})
        )
        ctx.start_agent("from")
        token = setup_root(ctx, api)
        check("FROM: root set up (agent and control initialised, node enrolled)", True)
        seeded = seed(ctx, api, token, model)
        RESULT["seeded"] = {k: v for k, v in seeded.items() if k != "state"}
        RESULT["schemaBefore"] = seeded["schema"]
        (OUT / "seeded-state.json").write_text(
            json.dumps(seeded["state"], indent=2), encoding="utf-8", newline="\n"
        )

        started = time.perf_counter()
        RESULT["stopFrom"] = ctx.stop_agent()
        check(
            "FROM agent stopped cleanly (no processes left under the prefix)",
            not RESULT["stopFrom"]["stragglersKilled"],
            RESULT["stopFrom"],
        )
        patched = in_place_installer(args.to_installer, OUT / "install-to-in-place.ps1")
        RESULT["installerDeviation"] = (
            "the -Isolated new-prefix guard removed from the candidate installer; "
            "nothing else changed"
        )
        timings["upgradeInstallSeconds"] = ctx.run_installer(patched, "to")
        say(f"TO installer ran in place in {timings['upgradeInstallSeconds']:.0f}s")
        check(
            "TO: agent.yaml kept by the installer",
            (ctx.prefix / "agent.yaml").is_file(),
        )
        ctx.start_agent("to")
        token = unlock(ctx, api)
        timings["stopToAgentUpSeconds"] = time.perf_counter() - started

        update = {"automatic": False, "route": None}
        catalogue = api.call(ctx.urls["agent"], "GET", "/v1/app-catalogue", token)
        target = next(
            r for r in catalogue["apps"] if r["manifest"]["id"] == "workbench"
        )["manifest"]["version"]
        RESULT["toCatalogueWorkbench"] = target
        try:
            wait(lambda: api.call(ctx.urls["agent"], "GET", "/v1/apps/workbench", token).get("version") == target
                 and api.call(ctx.urls["agent"], "GET", "/v1/apps/workbench", token)["status"] == "running",
                 "agent updates Workbench by itself", 60, 3)  # fmt: skip
            update["automatic"] = True
        except AssertionError:
            current = api.call(
                ctx.urls["agent"], "GET", "/v1/apps/workbench", token
            ).get("version")
            say(
                f"agent did not update Workbench by itself (still {current}); using POST /v1/apps/workbench/install"
            )
            api.call(
                ctx.urls["agent"],
                "POST",
                "/v1/apps/workbench/install",
                token,
                expected=(202,),
            )
            progress = wait_install(ctx, api, token)
            update["route"] = (
                "POST /v1/apps/workbench/install (the console's app update)"
            )
            update["progress"] = progress
            assert progress["state"] == "done", progress
        check(
            "TO: Workbench updated to the catalogue version",
            True,
            update.get("route") or "automatic",
        )
        timings["upgradeToWorkbenchUpdatedSeconds"] = time.perf_counter() - started
        verify(ctx, api, token, seeded, manifest, update)
    except Exception as exc:  # noqa: BLE001 - recorded, then the finally block cleans up
        check("harness ran to completion", False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            if ctx.proc:
                RESULT["stopFinal"] = ctx.stop_agent()
        finally:
            after = snapshot_live()
            check(
                "live service EugenePlexusAgent and account EUGENE_PLEXUS_* unchanged",
                after == before,
                {"before": before, "after": after},
            )
            RESULT["timings"] = timings
            RESULT["passed"] = all(c["passed"] for c in CHECKS)
            (OUT / "result.json").write_text(
                json.dumps(RESULT, indent=2, default=str),
                encoding="utf-8",
                newline="\n",
            )
            say(
                f"RESULT {'PASS' if RESULT['passed'] else 'FAIL'}: {sum(c['passed'] for c in CHECKS)}/{len(CHECKS)} checks; {OUT / 'result.json'}"
            )
            LOG.close()
    sys.exit(0 if RESULT["passed"] else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-installer", type=Path, required=True)
    parser.add_argument("--to-installer", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
