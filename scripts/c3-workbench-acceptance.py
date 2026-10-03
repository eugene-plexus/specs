"""C3 acceptance: Workbench, installed from Eugene's app catalogue.

Design: `docs/design/workbench-v1.md` §5. Real processes on free ports: a
control root, an enrolled agent that supervises a gateway, a model's
inference-driver and a SearXNG search account, a second enrolled agent
that is only a console, and a fixture that plays the engine (it calls
tools), SearXNG, and a page that records any fetch made of it.
**Workbench is installed through the registry** -- by default from the
agent's own catalogue entry, at its pinned `dist` archive, which is what
an install does -- **from the console on the other machine**, through its
`node:` hop, as the console's Apps page does it. Everything after that is
done the way a person's browser does it, against the real sign-in page.

The two agents advertise this host's routable address and bind every
interface, because a console refuses to hop to a loopback address.

What it proves, in order:

- the catalogue offers Workbench and an install started from another
  machine's console runs it, from the pinned archive, with its page
  (before 2026-10-01 that install signed the operator out: the worker
  sent the console's token, addressed to the worker alone, on to the
  root, and the root's 401 came back to the browser);
- the switch is off with the gateway's own reason before a search account
  exists, and on once one does;
- the owner signs in with Eugene's passphrase; a chat streams, Stop keeps
  what arrived, an answer finishes with no tab watching, an image goes to
  the model, a searched answer keeps its sources;
- the gateway records only the app's key;
- a cookie alone opens nothing, and a call from another origin is refused;
- two people each see only their own chats; one turned off in Eugene is
  signed out at the next refresh and the other keeps working;
- `ownerReadsChats`, set from the console's app page, lets the owner read
  people's chats and tells them so;
- a key whose tools leave out search turns the switch off and refuses a
  searched turn with the gateway's reason;
- Workbench's own log lines reach the agent's Logs page;
- revoking the app's key stops the next answer with a sentence saying so;
- uninstalling from the console removes its sign-in at the root, and the
  console stays signed in.

`--browser` adds the system Chrome driving Workbench's page itself
(`c3-workbench-browser.mjs`, Playwright from `ui/node_modules`).

`--source DIR` installs from a working tree as a custom entry instead.
That is for development only and says so: an archive has no gitignored
build output, so only the catalogue's archive proves what installs.

Since C5b, a per-user harness must observe the catalogue's account refusal.
It then tests chat/sign-in against that same archive as a custom, chat-only
entry: no account signal means local processes stay disabled. C5's separate
service-install run proves the actual catalogue install and stdio boundary.

Run in an environment holding every Python component (on this box,
`agent/.venv`). Before C3 this fails at its first check: the catalogue
has no Workbench.
"""

from __future__ import annotations

import argparse
import base64
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
from urllib.parse import parse_qs, urlsplit

import httpx
import yaml
from fastapi import Request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = HERE / "fixtures"
SEARXNG_ANSWER = FIXTURES / "searxng-answer.json"
NODE = "c3-node"
CONSOLE = "c3-console"
MODEL = "c3-local"
ANSWER = "C3-ANSWER: Hello from the fixture model."
SAW_IMAGE = "C3-SAW-IMAGE"
CITED = "C3-CITED"
# What a local model under a forced first search can do: answer, then search,
# then answer again (gateway#4, workbench#1).
DRAFTED = "C3-DRAFT: an answer written before searching."
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

RESULTS: list[tuple[str, str, bool, str]] = []


def check(number: str, claim: str, passed: bool, detail: object = "") -> bool:
    RESULTS.append((number, claim, bool(passed), str(detail)))
    tail = f"  -- {detail}" if detail not in ("", None) else ""
    print(f"  {'PASS' if passed else 'FAIL'}  {number}. {claim}{tail}", flush=True)
    return bool(passed)


class Abort(Exception):
    pass


def must(number: str, claim: str, passed: bool, detail: object = "") -> None:
    if not check(number, claim, passed, detail):
        raise Abort(f"{number}: {claim}")


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


# --------------------------------------------------------------------------- #
# the fixture: an engine that calls tools, SearXNG, and a page that tattles
# --------------------------------------------------------------------------- #


def _text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return ""


def _has_image(message: dict) -> bool:
    content = message.get("content")
    return isinstance(content, list) and any(p.get("type") == "image_url" for p in content)


def fixture_app(state_file: Path):
    # `Request` is imported at the top: with postponed annotations FastAPI
    # resolves a parameter's type in the module's globals, and a local import
    # is not there, so the request would be read as a query parameter.
    from fastapi import FastAPI
    from fastapi.responses import Response, StreamingResponse

    app = FastAPI()
    state: dict = {"mode": "plain", "counts": {}, "seen": {}, "canary": 0}
    answer = json.loads(SEARXNG_ANSWER.read_text(encoding="utf-8"))
    canary_url = json.loads(state_file.read_text(encoding="utf-8"))["canary"]

    def count(name: str, body: object = None) -> None:
        state["counts"][name] = state["counts"].get(name, 0) + 1
        if body is not None:
            state["seen"].setdefault(name, []).append(body)

    @app.get("/healthz")
    async def health():
        return {}

    @app.get("/stats")
    async def stats():
        return {"counts": state["counts"], "canary": state["canary"]}

    @app.get("/seen")
    async def seen(name: str):
        return state["seen"].get(name, [])

    @app.post("/mode")
    async def mode(value: str):
        state["mode"] = value
        return {}

    @app.get("/canary/leak.png")
    async def canary():
        # An answer's image fetched by a page: the leak W5 forbids.
        state["canary"] += 1
        return Response(content=PNG, media_type="image/png")

    @app.get("/searx/search")
    async def searx(request: Request):
        count("searx", dict(request.query_params))
        return answer

    @app.get("/model/props")
    async def props():
        return {"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": True}}

    @app.get("/model/v1/models")
    async def models():
        return {"data": [{"id": MODEL, "object": "model"}]}

    def turn(body: dict) -> tuple[str | None, list[dict] | None]:
        messages = body.get("messages") or []
        tools = [t.get("function", {}).get("name") for t in body.get("tools") or []]
        last = messages[-1] if messages else {}
        if last.get("role") == "tool":
            urls = re.findall(r"https?://\S+", _text(last))
            first = urls[0].rstrip(").,") if urls else "https://example.org"
            return f"{CITED}: the fixture read the results. Source: [the page]({first}).", None
        if "web_search" in tools and last.get("role") == "user":
            calls = [{"name": "web_search", "arguments": {"query": _text(last)[:60]}}]
            return (DRAFTED if state["mode"] == "draft" else None), calls
        # Only the turn being answered: an image earlier in the chat travels
        # in every later request too, and is not what they are about.
        if _has_image(last):
            return f"{SAW_IMAGE}: a picture arrived.", None
        if state["mode"] == "image":
            return f"Here it is: ![a diagram]({canary_url}) and that is all.", None
        return ANSWER, None

    @app.post("/model/v1/chat/completions")
    async def complete(request: Request):
        body = await request.json()
        count("model", {"roles": [m.get("role") for m in body.get("messages") or []],
                        "assistants": [_text(m) for m in body.get("messages") or []
                                       if m.get("role") == "assistant"],
                        "images": sum(_has_image(m) for m in body.get("messages") or []),
                        "tools": [t.get("function", {}).get("name") for t in body.get("tools") or []]})
        text, calls = turn(body)
        slow = state["mode"] == "slow"
        tool_calls = [{"id": f"call_{secrets.token_hex(4)}", "type": "function",
                       "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                      for c in calls or []]
        finish = "tool_calls" if tool_calls else "stop"
        usage = {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}
        if not body.get("stream"):
            return {"model": MODEL, "usage": usage, "choices": [{"index": 0, "finish_reason": finish,
                    "message": {"role": "assistant", "content": text, "tool_calls": tool_calls or None}}]}

        async def frames():
            import asyncio

            for word in (text or "").split(" ") if text else []:
                if slow:
                    await asyncio.sleep(0.5)
                yield "data: " + json.dumps({"model": MODEL, "choices": [
                    {"index": 0, "delta": {"content": word + " "}, "finish_reason": None}]}) + "\n\n"
            for index, call in enumerate(tool_calls):
                yield "data: " + json.dumps({"model": MODEL, "choices": [{"index": 0, "delta": {
                    "tool_calls": [{"index": index, "id": call["id"], "type": "function",
                                    "function": call["function"]}]}, "finish_reason": None}]}) + "\n\n"
            yield "data: " + json.dumps({"model": MODEL, "choices": [
                {"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return app


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    host = "127.0.0.1"
    if kind in ("agent", "console"):
        # A console hops to another node at the address that node
        # advertises, and refuses a loopback one; see the docstring.
        host = "0.0.0.0"
        kind = "agent"
    if kind == "fixture":
        app = fixture_app(directory / "fixture.json")
    elif kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(Settings(config_file=directory / "control.yaml", state_dir=directory / "state"))
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.console_logging import install_console_capture
        from eugene_plexus_agent.settings import Settings

        # As the agent's own entry point does, so its Logs page has a file
        # to read: every supervised child's lines, an app's included.
        install_console_capture(log_dir=directory / "logs")

        app = create_app(settings=Settings(config_file=directory / "agent.yaml", default_topology=False,
                                           bind_port=port))
    else:
        raise SystemExit(f"unknown kind {kind!r}")
    uvicorn.run(app, host=host, port=port, log_level="error", access_log=False)


def routable_address() -> str:
    """The address this host would use to reach another; no packet is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    except OSError as exc:
        raise SystemExit(
            f"this host has no routable address ({exc}), and a console will not hop to a "
            "loopback one; connect a network and run again"
        ) from exc
    finally:
        probe.close()


# --------------------------------------------------------------------------- #
# a person's browser, against the real sign-in page
# --------------------------------------------------------------------------- #


class Browser:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=30, trust_env=False)
        self.secret: str | None = None

    def sign_in(self, password: str, name: str | None = None) -> str:
        """The whole flow; returns where it ended (the page's fragment)."""
        start = self.http.get(self.base + "/signin")
        if start.status_code != 302:
            return f"signin answered {start.status_code}: {start.text[:200]}"
        page = self.http.get(start.headers["location"])
        if page.status_code != 200:
            return f"Eugene's page answered {page.status_code}: {page.text[:200]}"
        fields = {m.group(1): html.unescape(m.group(2))
                  for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page.text)}
        form = {k: v for k, v in fields.items() if k not in ("name", "password")}
        form["password"] = password
        if name is not None:
            form["name"] = name
        posted = self.http.post(urlsplit(start.headers["location"])._replace(query="").geturl(), data=form)
        if posted.status_code not in (302, 303):
            return f"Eugene's page said {posted.status_code}: {re.sub(r'<[^>]+>', ' ', posted.text)[:300]}"
        back = self.http.get(posted.headers["location"])
        location = back.headers.get("location", "")
        if "#signin=" in location:
            self.secret = location.split("#signin=", 1)[1]
        return location

    def _headers(self) -> dict[str, str]:
        out = {"Origin": self.base}
        if self.secret:
            out["X-Workbench-Secret"] = self.secret
        return out

    def get(self, path: str, **kw):
        return self.http.get(self.base + path, headers=self._headers(), **kw)

    def post(self, path: str, **kw):
        return self.http.post(self.base + path, headers=self._headers(), **kw)

    def patch(self, path: str, **kw):
        return self.http.patch(self.base + path, headers=self._headers(), **kw)

    def answer(self, chat: str, seconds: float = 60) -> dict:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            messages = self.get(f"/api/chats/{chat}").json().get("messages", [])
            if messages and messages[-1]["status"] != "running":
                return messages[-1]
            time.sleep(0.2)
        raise Abort("an answer did not finish")

    def ask(self, chat: str, content: str, **extra) -> dict:
        sent = self.post(f"/api/chats/{chat}/messages", json={"content": content, **extra})
        if sent.status_code != 201:
            raise Abort(f"sending failed: {sent.status_code} {sent.text[:300]}")
        return self.answer(chat)


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def free_ports(names: list[str]) -> dict[str, int]:
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {n: s.getsockname()[1] for n, s in zip(names, sockets, strict=True)}
    for sock in sockets:
        sock.close()
    return ports


def uv_binary() -> str:
    name = "uv.exe" if os.name == "nt" else "uv"
    beside = Path(sys.executable).parent / name
    found = str(beside) if beside.is_file() else shutil.which("uv")
    if not found:
        raise SystemExit("uv is needed to install an app; pip install uv into this interpreter")
    return found


def exercise(work: Path, *, source: str | None, browser: bool, engine: str | None = None,
             gguf: str | None = None, searxng: str | None = None) -> None:
    live = engine is not None
    for name in [k for k in os.environ if k.startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    ports = free_ports(["control", "agent", "console", "fixture", "gateway", "model", "searx",
                        "engine"])
    url = {k: f"http://127.0.0.1:{v}" for k, v in ports.items()}
    lan = routable_address()
    client = httpx.Client(timeout=120, trust_env=False)
    processes: list[subprocess.Popen] = []
    passphrase = secrets.token_urlsafe(24)

    def call(name: str, method: str, path: str, token: str | None = None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, url[name] + path, headers=headers, **kw)

    def wait(fn, label: str, seconds: float = 60):
        deadline = time.perf_counter() + seconds
        last = None
        while time.perf_counter() < deadline:
            try:
                if fn():
                    return
            except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError, StopIteration) as e:
                last = e
            time.sleep(0.25)
        raise Abort(f"timed out: {label} ({last!r})")

    def start(name: str) -> None:
        directory = work / name
        directory.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env.pop("OPENAI_API_KEY", None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes.append(subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", name, "--directory",
             str(directory), "--port", str(ports[name])],
            cwd=directory, env=env, stdout=(directory / "process.log").open("ab"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ))
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    try:
        say("an install: a root, an agent that supervises a gateway, a model and a search account")
        (work / "fixture").mkdir()
        (work / "fixture" / "fixture.json").write_text(
            json.dumps({"canary": url["fixture"] + "/canary/leak.png"}), encoding="utf-8")
        start("fixture")
        start("control")
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).raise_for_status()
        root = call("control", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        agent_dir = work / "agent"
        agent_dir.mkdir()
        (agent_dir / "gateway.yaml").write_text(yaml.safe_dump({"routingRefreshSeconds": 2}), encoding="utf-8")
        backend = url["fixture"] + "/model"
        if live:
            # A real engine: llama-server with the model, tools templated by
            # its own chat template, thinking off so answers are prompt.
            log = (work / "engine.log").open("ab")
            processes.append(subprocess.Popen(
                [engine, "-m", gguf, "--host", "127.0.0.1", "--port", str(ports["engine"]),
                 "--alias", MODEL, "--jinja", "-c", "8192", "--reasoning-budget", "0"],
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ))
            wait(lambda: client.get(url["engine"] + "/health").status_code == 200, "llama-server", 180)
            backend = url["engine"]
        (agent_dir / "model.yaml").write_text(yaml.safe_dump({
            "provider": "openai_compat_custom", "baseUrl": backend,
            "modelId": MODEL, "backendLocality": "local"}), encoding="utf-8")
        (agent_dir / "searx.yaml").write_text("{}\n", encoding="utf-8")
        (agent_dir / "agent.yaml").write_text(yaml.safe_dump({
            "firstRunComplete": True,
            "advertiseUrl": f"http://{lan}:{ports['agent']}",
            "securityMode": "prompt_on_startup",
            "uvBinary": uv_binary(),
            "allowCustomApps": source is not None,
            "components": [
                {"name": "gateway", "kind": "gateway", "url": url["gateway"],
                 "spawn": {"configFile": str(agent_dir / "gateway.yaml")}},
                {"name": "model", "kind": "inference-driver", "url": url["model"],
                 "spawn": {"configFile": str(agent_dir / "model.yaml")}},
                {"name": "searx", "kind": "tool-driver", "url": url["searx"],
                 "spawn": {"configFile": str(agent_dir / "searx.yaml")}},
            ],
        }), encoding="utf-8")
        start("agent")
        local = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).json()["sessionToken"]
        join = call("control", "POST", "/v1/nodes/join-token", root,
                    json={"nodeName": NODE, "grants": ["gateway"]}).json()["token"]
        enrolled = call("agent", "POST", "/v1/node/enroll", local, timeout=90,
                        json={"controlUrl": url["control"], "token": join, "name": NODE})
        # A second machine that runs nothing: the console the operator is
        # at, as the NAS is on the live install, acting on c3-node.
        console_dir = work / "console"
        console_dir.mkdir()
        (console_dir / "agent.yaml").write_text(yaml.safe_dump({
            "firstRunComplete": True,
            "advertiseUrl": f"http://{lan}:{ports['console']}",
            "securityMode": "prompt_on_startup",
            "components": [],
        }), encoding="utf-8")
        start("console")
        console_local = call("console", "POST", "/v1/auth/initialize",
                             json={"passphrase": passphrase}).json()["sessionToken"]
        console_join = call("control", "POST", "/v1/nodes/join-token", root,
                            json={"nodeName": CONSOLE}).json()["token"]
        console_enrolled = call("console", "POST", "/v1/node/enroll", console_local, timeout=90,
                                json={"controlUrl": url["control"], "token": console_join,
                                      "name": CONSOLE})
        must("1", "the agent, and a second machine that is only a console, enroll with the root",
             enrolled.status_code == 200 and console_enrolled.status_code == 200,
             (enrolled.text[:200], console_enrolled.text[:200]))
        wait(lambda: call("agent", "GET", "/healthz").status_code == 200, "agent after enrolment")
        wait(lambda: call("console", "GET", "/healthz").status_code == 200, "console after enrolment")
        operator = call("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        # Signed in at the console, as the operator was on the live install;
        # it reaches c3-node only through its proxy's `node:` hop.
        console = call("console", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        hop = f"/api/proxy/node:{NODE}"

        def component_running(name: str) -> bool:
            listed = call("agent", "GET", "/v1/components", operator).json()["components"]
            return next(c for c in listed if c["name"] == name)["status"] == "running"

        for name in ("gateway", "model", "searx"):
            wait(lambda name=name: component_running(name), f"the agent runs {name}", 90)

        say("Workbench from the catalogue")
        catalogue = call("agent", "GET", "/v1/app-catalogue", operator).json()
        entry = next((e for e in catalogue.get("apps", []) if e["manifest"]["id"] == "workbench"), None)
        app_id = "workbench"
        if source is None:
            must("2", "the agent's catalogue offers Workbench at a pinned archive",
                 entry is not None and entry["manifest"]["source"].startswith("https://github.com/"),
                 entry["manifest"]["source"] if entry else "no Workbench in the catalogue")
            check("3", "it declares sign-in, settings and its local-action requirement",
                  entry["manifest"].get("signIn") is True and isinstance(entry["manifest"].get("localActions"), bool)
                  and entry["manifest"].get("configTrio") is True, entry["manifest"])
        if source is not None or (entry and entry["manifest"].get("localActions") is True):
            if source is None:
                refused = call("console", "POST", hop + "/v1/apps/workbench/install", console)
                must("3a", "the real catalogue refuses local actions without an app account",
                     refused.status_code == 409, refused.text[:300])
            app_id = "workbench-chat-check"
            enabled = call("agent", "PATCH", "/v1/config", operator, json={"allowCustomApps": True})
            must("3c", "the disposable harness enables its custom regression entry",
                 enabled.status_code == 200, enabled.text[:300])
            manifest = dict((entry or {}).get("manifest") or {
                "id": "workbench", "name": "Workbench", "package": "eugene-plexus-workbench",
                "entry": "eugene_plexus_workbench", "ui": True, "configTrio": True, "signIn": True,
                "localActions": False})
            manifest.update({"id": app_id, "localActions": False})
            if source is not None:
                manifest.update({"source": source, "version": "dev-" + secrets.token_hex(3)})
            added = call("agent", "POST", "/v1/app-catalogue/custom", operator, json=manifest)
            must("3b", "chat/API regression entry added; local processes must remain disabled",
                 added.status_code == 201, added.text[:300])
        began = call("console", "POST", hop + f"/v1/apps/{app_id}/install", console)
        must("4", "the install starts, from the console on another machine",
             began.status_code == 202, f"{began.status_code} {began.text[:300]}")

        def installed() -> bool:
            progress = call("console", "GET", hop + f"/v1/apps/{app_id}/install", console).json()
            if progress["state"] == "failed":
                raise Abort("the install failed: " + str(progress.get("error"))[-1500:])
            return progress["state"] == "done"

        wait(installed, "the install", 600)
        wait(lambda: call("agent", "GET", f"/v1/apps/{app_id}", operator).json()["status"] == "running",
             "Workbench running", 90)
        app = call("agent", "GET", f"/v1/apps/{app_id}", operator).json()
        ui = app["uiUrl"].rstrip("/")
        page = client.get(ui + "/")
        must("5", "Workbench runs, and its page is the built front end",
             page.status_code == 200 and 'id="root"' in page.text and "/assets/" in page.text,
             f"{app['status']} at {ui}, isolation {app.get('isolation')}")
        check("6", "its key is the app's own, and it is registered to sign people in",
              app.get("keyName") == f"app:{app_id}@{NODE}" and bool(app.get("oidcClientId")),
              {"key": app.get("keyName"), "client": app.get("oidcClientId")})

        say("before a search account: the switch says why")
        owner = Browser(ui)
        ended = owner.sign_in(passphrase)
        must("7", "the owner signs in on Eugene's page with the passphrase and lands back signed in",
             ended.startswith("/#signin="), ended[:200])
        me = owner.get("/api/me").json()
        check("8", "Workbench knows the owner as the owner", me.get("owner") is True, me)
        if app_id == "workbench-chat-check":
            local = owner.get("/api/tools/servers").json()["localProcesses"]
            check("8a", "without the launcher signal local process execution is disabled",
                  local["available"] is False and bool(local["reason"]), local)
        wait(lambda: any(m["id"] == MODEL for m in owner.get("/api/models").json()["models"]),
             "the model is listed", 60)
        listing = owner.get("/api/models").json()
        check("9", "with no search account set up, search is off in the gateway's own words",
              listing["webSearch"]["available"] is False
              and "search account" in (listing["webSearch"]["reason"] or ""), listing["webSearch"])

        patched = call("agent", "PATCH", "/api/proxy/searx/v1/config", operator,
                       json={"provider": "searxng", "baseUrl": searxng or url["fixture"] + "/searx",
                             "probeMinutes": 0})
        assert patched.status_code == 200, patched.text
        wait(lambda: owner.get("/api/models").json()["webSearch"]["available"] is True,
             "the gateway sees the search account", 60)
        check("10", "once a search account is set up, search is on", True)

        say("chats" + (" (a real model)" if live else ""))
        chat = owner.post("/api/chats", json={"model": MODEL}).json()["id"]
        answered = owner.ask(chat, "Say hello in one short sentence.")
        check("11", "a chat streams an answer from the model through the gateway",
              answered["status"] == "done" and (answered["content"].strip() == ANSWER if not live
                                                else bool(answered["content"].strip())),
              answered["content"][:80])

        up = owner.post(f"/api/chats/{chat}/files", files={"file": ("dot.png", PNG, "image/png")})
        seen = owner.ask(chat, "What is this?", attachments=[up.json()["id"]]) if up.status_code == 201 else {}
        if not live:
            check("12", "an image goes to the model as content it can see",
                  up.status_code == 201 and seen.get("content", "").startswith(SAW_IMAGE), up.text[:120])
        else:
            # This small model takes no images: the gateway says so, and
            # Workbench passes its words on rather than its own.
            check("12", "an image sent to a model that cannot see is refused in the gateway's words",
                  seen.get("status") == "failed" and "image" in (seen.get("error") or "").lower(),
                  (seen.get("error") or "")[:160])

        searched_chat = owner.post("/api/chats", json={"model": MODEL}).json()["id"]
        searched = owner.ask(searched_chat, "What is Eugene Plexus? Search the web, then answer "
                             "in two sentences and cite the page you used.", search=True)
        stats = call("fixture", "GET", "/stats").json()
        check("13", "a searched answer runs on the search account and keeps its sources"
              + (" (the WSL SearXNG)" if live else ""),
              searched["status"] == "done" and searched.get("searches", 0) >= 1
              and (searched["content"].startswith(CITED) and stats["counts"].get("searx", 0) >= 1
                   if not live else bool(searched["content"].strip())),
              {"sources": searched.get("sources"), "searches": searched.get("searches"),
               "answer": searched["content"][:120]})

        if not live:
            # The model answers, then searches, then answers again, through the
            # real gateway: the reply keeps both, marks where the answer after
            # the search begins, and only that answer goes back as history.
            call("fixture", "POST", "/mode?value=draft")
            drafted_chat = owner.post("/api/chats", json={"model": MODEL}).json()["id"]
            drafted = owner.ask(drafted_chat, "What is Eugene Plexus?", search=True)
            call("fixture", "POST", "/mode?value=plain")
            at = drafted.get("answerFrom")
            after = drafted["content"][at:].lstrip() if isinstance(at, int) else ""
            owner.ask(drafted_chat, "Thanks.", search=False)
            history = call("fixture", "GET", "/seen?name=model").json()[-1]["assistants"]
            check("13b", "text written before a search is marked as a draft, and only the "
                  "answer after it goes back as history",
                  drafted["status"] == "done" and drafted["content"].startswith(DRAFTED)
                  and isinstance(at, int) and at > 0 and after.startswith(CITED)
                  and len(history) == 1 and history[0].startswith(CITED)
                  and DRAFTED not in history[0],
                  {"answerFrom": at, "content": drafted["content"][:160], "history": history})

        call("fixture", "POST", "/mode?value=slow")
        slow = owner.post("/api/chats", json={"model": MODEL}).json()["id"]
        owner.post(f"/api/chats/{slow}/messages", json={
            "content": "Take your time" if not live else "Write a long story about a carpenter."})
        if live:
            wait(lambda: owner.get(f"/api/chats/{slow}").json()["messages"][-1]["content"],
                 "a first word", 60)
        time.sleep(1.6)
        owner.post(f"/api/chats/{slow}/stop")
        stopped = owner.answer(slow)
        check("14", "Stop ends an answer and keeps what had arrived",
              stopped["status"] == "stopped" and 0 < len(stopped["content"])
              and (len(stopped["content"]) < len(ANSWER) if not live else True),
              repr(stopped["content"][:80]))
        orphan = owner.post("/api/chats", json={"model": MODEL}).json()["id"]
        owner.post(f"/api/chats/{orphan}/messages", json={"content": "Nobody is watching. Say hi."})
        finished = owner.answer(orphan, 180)
        check("15", "an answer with no tab watching it finishes and is kept",
              finished["status"] == "done" and (finished["content"].strip() == ANSWER if not live
                                                else bool(finished["content"].strip())),
              finished["status"])
        call("fixture", "POST", "/mode?value=plain")

        requests = call("agent", "GET", "/api/proxy/gateway/v1/metrics/requests", operator,
                        params={"limit": 200}).json()
        rows = requests.get("requests") or []
        keys = {r.get("clientKeyName") for r in rows}
        check("16", "the gateway records Workbench's requests under the app's key and no other",
              keys == {f"app:{app_id}@{NODE}"}, sorted(map(str, keys)))

        say("a session needs its cookie and its secret")
        cookie_only = owner.http.get(ui + "/api/me")
        elsewhere = owner.http.post(ui + "/api/chats", json={}, headers={
            "Origin": "http://evil.example", "X-Workbench-Secret": owner.secret or ""})
        check("17", "a cookie alone opens nothing, and a call from another origin is refused",
              cookie_only.status_code == 401 and elsewhere.status_code == 403,
              (cookie_only.status_code, elsewhere.status_code))

        say("two people")
        made = {}
        for name in ("ada", "bo"):
            response = call("control", "POST", "/v1/people", root,
                            json={"name": name, "displayName": name.title(), "password": f"{name}-password-12"})
            assert response.status_code == 201, response.text
            made[name] = response.json()
        ada, bo = Browser(ui), Browser(ui)
        check("18", "two people sign in with their own names and passwords",
              ada.sign_in("ada-password-12", "ada").startswith("/#signin=")
              and bo.sign_in("bo-password-12", "bo").startswith("/#signin="))
        mine = ada.post("/api/chats", json={"model": MODEL}).json()["id"]
        ada.ask(mine, "Ada's own question")
        theirs = bo.get(f"/api/chats/{mine}")
        check("19", "each sees only their own chats",
              theirs.status_code == 404 and bo.get("/api/chats").json()["chats"] == []
              and [c["id"] for c in ada.get("/api/chats").json()["chats"]] == [mine])

        reads = call("console", "PATCH", hop + f"/v1/apps/{app_id}/config", console,
                     json={"ownerReadsChats": True})
        told = ada.get("/api/me").json().get("ownerReadsChats")
        read = owner.get(f"/api/chats/{mine}")
        check("20", "with ownerReadsChats set from the console, the owner reads Ada's chat, "
              "read-only, and Ada is told",
              reads.status_code == 200 and told is True and read.status_code == 200
              and read.json()["chat"]["readOnly"] is True
              and owner.post(f"/api/chats/{mine}/messages", json={"content": "x"}).status_code == 404,
              reads.text[:200])
        call("console", "PATCH", hop + f"/v1/apps/{app_id}/config", console, json={"ownerReadsChats": None})
        check("21", "turned back off, the owner cannot", owner.get(f"/api/chats/{mine}").status_code == 404)

        person_id = made["ada"]["id"]
        call("control", "PATCH", f"/v1/people/{person_id}", root, json={"disabled": True}).raise_for_status()
        # Ten minutes is the ID token's life (C2 D6); stand in for it by
        # making Ada's session due for its refresh now.
        database = agent_dir / "apps" / app_id / "data" / "workbench.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("UPDATE sessions SET access_expires_at = 0 WHERE sub = ?", (person_id,))
        refused = ada.get("/api/me")
        check("22", "Ada, turned off in Eugene, is signed out at her next refresh, saying why",
              refused.status_code == 401 and "no longer accepts" in refused.text, refused.text[:200])
        check("23", "and Bo keeps working", bo.get("/api/me").status_code == 200)

        say("a key that may not search")
        key_id = app["keyId"]
        keys = call("agent", "GET", "/v1/auth/client-keys", operator).json()
        current = next(k for k in keys.get("keys", []) if k["id"] == key_id).get("limits") or {}

        def set_limits(limits: dict) -> None:
            answer = call("agent", "PUT", f"/v1/auth/client-keys/{key_id}/limits", operator,
                          json={"limits": limits})
            assert answer.status_code == 200, answer.text

        set_limits({**current, "allowedTools": []})
        wait(lambda: owner.get("/api/models").json()["webSearch"]["available"] is False,
             "the gateway reads the narrowed key", 60)
        off = owner.get("/api/models").json()["webSearch"]
        refused_search = owner.ask(searched_chat, "Search again", search=True)
        check("24", "a key whose tools leave out search turns the switch off and refuses a "
              "searched turn with the gateway's reason",
              "tool scope" in (off["reason"] or "") and refused_search["status"] == "failed"
              and "tool scope" in (refused_search.get("error") or ""),
              {"switch": off, "answer": refused_search.get("error")})
        set_limits(current)

        say("logs, and a revoked key")
        lines = call("agent", "GET", "/v1/logs", operator, params={"contains": "signed in", "tail": 50}).json()
        found = [f"{line['source']}: {line['text']}" for line in lines.get("lines", [])
                 if "ada signed in" in line["text"].lower()]
        check("25", "Workbench's own log lines reach the agent's Logs page", bool(found), found[-2:])

        if browser:
            say("the system Chrome")
            browser_run(work, ui=ui, passphrase=passphrase, fixture=url["fixture"],
                        call=call, live=live)

        revoked = call("agent", "DELETE", f"/v1/auth/client-keys/{key_id}", operator)
        assert revoked.status_code in (200, 204), revoked.text
        time.sleep(3)
        after = owner.ask(chat, "Are you there?")
        check("26", "with the app's key revoked, the next answer says the key was refused",
              after["status"] == "failed" and "refused the key" in (after.get("error") or ""),
              after.get("error"))

        say("uninstalled from the console")
        gone = call("console", "DELETE", hop + f"/v1/apps/{app_id}", console)
        clients = call("control", "GET", "/v1/oidc/clients", root).json()["clients"]
        still = call("console", "GET", "/v1/auth/client-keys", console)
        check("27", "uninstalled from the console, its sign-in is gone at the root, and the "
              "console is still signed in",
              gone.status_code == 204 and app["oidcClientId"] not in {c["clientId"] for c in clients}
              and still.status_code == 200,
              {"uninstall": f"{gone.status_code} {gone.text[:200]}", "console": still.status_code})
    except Abort as exc:
        print(f"\nABORTED: {exc}", flush=True)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()


def browser_run(work: Path, *, ui: str, passphrase: str, fixture: str, call, live: bool) -> None:
    cfg = work / "browser.json"
    result = work / "browser-result.json"
    shots = work / "shots"
    shots.mkdir(exist_ok=True)
    cfg.write_text(json.dumps({"ui": ui, "passphrase": passphrase, "fixture": fixture, "live": live,
                               "result": str(result), "shots": str(shots),
                               "playwright": str(ROOT / "ui" / "node_modules" / "playwright-core")}),
                   encoding="utf-8")
    run = subprocess.run(["node", str(HERE / "c3-workbench-browser.mjs"), str(cfg)],
                         capture_output=True, text=True, timeout=600)
    if not result.is_file():
        check("B0", "Chrome ran the page", False, (run.stdout + run.stderr)[-1500:])
        return
    out = json.loads(result.read_text(encoding="utf-8"))
    for number, claim, passed, detail in out.get("checks", []):
        check(number, claim, passed, detail)
    canary = call("fixture", "GET", "/stats").json()["canary"]
    check("B9", "the image an answer named was never fetched", canary == 0, f"{canary} fetches")
    if out.get("error"):
        check("B0", "Chrome ran every step", False, out["error"][:600])
    expected = {"B1", "B2", "B5", "B6", "B7", "B8", "B10"} | (set() if live else {"B3", "B4"})
    missing = expected - {number for number, *_ in out.get("checks", [])}
    if missing:
        check("B11", "every browser step reported", False, sorted(missing))
    print(f"  screenshots in {shots}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory")
    parser.add_argument("--port", type=int)
    parser.add_argument("--source", help="install from this working tree (development only)")
    parser.add_argument("--browser", action="store_true", help="also drive the system Chrome")
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    parser.add_argument("--engine", help="a llama-server to run a real model with (live)")
    parser.add_argument("--gguf", help="the model file for --engine")
    parser.add_argument("--searxng", help="a real SearXNG to search with, e.g. http://127.0.0.1:8888")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, Path(args.directory), args.port)
        return
    work = Path(tempfile.mkdtemp(prefix="ep-c3-"))
    print(f"working in {work}")
    try:
        exercise(work, source=args.source, browser=args.browser, engine=args.engine,
                 gguf=args.gguf, searxng=args.searxng)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    failed = [r for r in RESULTS if not r[2]]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    finished = any(r[0] == "27" for r in RESULTS)
    sys.exit(1 if failed or not finished else 0)


if __name__ == "__main__":
    main()
