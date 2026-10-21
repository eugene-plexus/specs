#!/usr/bin/env python3
"""C4 (docs/design/c4-open-webui.md): Open WebUI from the app registry.

Runs on a GitHub runner, never on a developer's box, for the reason C1's run
does: Open WebUI runs Python its admin pastes in, so it installs only where
apps get an account of their own, and that is a service install. This run
installs Eugene as the machine's service (C1's own steps), adds a fixture
model behind the gateway the way the console's *Add an app you already run*
does, installs Open WebUI from the catalogue, and signs people in through
Eugene's real sign-in page the way a browser does: cookies, redirects and
the form, over plain HTTP.

**What it proves:** the third-party entry's shape works end to end -- a PyPI
pin, a console-script start, its own variables, `/ready` -- in an account of
its own, writing only to its data directory and downloading no model; the
owner arrives as its admin and each person as a user, with the email Eugene
gives or Open WebUI's placeholder; a chat answers through the gateway on the
app's key; a new key after a reinstall is taken (the one-start reset), and a
plain restart keeps what its admin set; uninstall takes everything away.

**Row 34 adds** (specs docs/design/rows/row-34.md): web search through the
gateway's `/v1/web_search` door on the app's key, with the result pages never
fetched; images through the gateway's images door from a model added after
the first start (Reset on Windows; a refusal that names its cause on a Linux
system install, where the new key at the reinstall carries the model
instead); and an update that copies Open WebUI's database first, shows the
cause of a start that fails, and goes back. The update runs on Windows. A
Linux system install keeps the app's data in systemd's private state, which
the install helper cannot copy, so there the update is refused and the run
checks that it names the cause and changes nothing. The two versions come
from the agent's catalogue file, edited for the run.

Try candidates before pinning them: EP_PIN_AGENT, EP_PIN_CONTROL and the
other EP_PIN_* take full SHAs, as C1's run does.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("c1", HERE / "c1-app-accounts-acceptance.py")
assert _SPEC and _SPEC.loader
c1 = importlib.util.module_from_spec(_SPEC)
sys.modules["c1"] = c1
_SPEC.loader.exec_module(c1)

api, check, must, fact, say, Abort = c1.api, c1.check, c1.must, c1.fact, c1.say, c1.Abort
wait_for, healthy = c1.wait_for, c1.healthy
AGENT, CONTROL, PASSPHRASE, WINDOWS = c1.AGENT, c1.CONTROL, c1.PASSPHRASE, c1.WINDOWS
APP = "open-webui"
MODEL = "c4-local"
ANSWER = "C4-ANSWER: hello from the fixture model."
FIXTURE_PORT = 18990
PERSON_PASSWORD = "a-person-password-1"
#: What the owner signs in with once the install has people (C2, D4).
OWNER_NAME = "operator"
#: The words the launcher prints when it resets an app's settings for one start.
RESET_WORDS = "What%20Eugene%20gives%20this%20app%20changed"
SEARX_PORT = 18991
ROUTER_PORT = 18992
PAINTER = "acme/painter"
OLD_VERSION = "0.11.4"
#: A 1x1 PNG, the image the stand-in makes.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
SEARX_ANSWER = HERE / "fixtures" / "searxng-answer.json"

# --------------------------------------------------------------------------- #
# the fixture model, which records the bearer each request arrived with
# --------------------------------------------------------------------------- #

SEEN: list[dict] = []
#: What the stand-in search engine was asked, the result pages anyone fetched, and the
#: prompts the stand-in image model was given.
SEARCHED: list[dict] = []
PAGES: list[str] = []
PAINTED: list[dict] = []


class Model(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:  # quiet
        pass

    def _send(self, status: int, body: object, content_type: str = "application/json") -> None:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path == "/searx/search":
            # SearXNG's JSON answer as measured; every result page is this server's own, so
            # a fetch of one shows (Open WebUI must use the snippets and fetch none).
            answer = json.loads(SEARX_ANSWER.read_text(encoding="utf-8"))
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            SEARCHED.append(query)
            for i, result in enumerate(answer.get("results", [])):
                result["url"] = f"http://127.0.0.1:{FIXTURE_PORT}/pages/{i}"
            self._send(200, answer)
        elif path.startswith("/pages/"):
            PAGES.append(path)
            self._send(200, b"<html>a result page</html>", "text/html")
        elif path == "/or/v1/models/user":
            self._send(200, {"data": [{
                "id": PAINTER, "name": PAINTER, "context_length": 4096,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
                "supported_parameters": [],
            }]})
        elif path == "/or/v1/images/models":
            self._send(200, {"data": [{"id": PAINTER, "supports_streaming": False,
                                       "supported_parameters": {
                "output_format": {"type": "enum", "values": ["png", "jpeg"]},
                "n": {"type": "range", "min": 1, "max": 1},
                "input_references": {"type": "range", "min": 0, "max": 0}}}]})
        elif path == "/or/v1/videos/models":
            self._send(200, {"data": []})
        elif self.path.rstrip("/").endswith("/models"):
            self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        else:
            self._send(200, {})

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.split("?")[0].rstrip("/") in ("/or/v1/images", "/or/v1/images/generations"):
            PAINTED.append(body)
            self._send(200, {"created": int(time.time()),
                             "data": [{"b64_json": PNG_B64, "media_type": "image/png"}],
                             "usage": {"prompt_tokens": 6, "completion_tokens": 4096,
                                       "total_tokens": 4102}})
            return
        SEEN.append({"path": self.path, "stream": bool(body.get("stream"))})
        message = {"role": "assistant", "content": ANSWER}
        usage = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
        if not body.get("stream"):
            self._send(200, {"id": "c", "object": "chat.completion", "model": MODEL, "usage": usage,
                             "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]})
            return
        chunks = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ANSWER},
                          "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage},
        ]
        raw = b"".join(
            b"data: " + json.dumps({"id": "c", "object": "chat.completion.chunk", "model": MODEL,
                                    **c}).encode() + b"\n\n" for c in chunks
        ) + b"data: [DONE]\n\n"
        self._send(200, raw, "text/event-stream")


def serve_fixture() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", FIXTURE_PORT), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()


# --------------------------------------------------------------------------- #
# a browser: cookies, redirects, and Eugene's sign-in form
# --------------------------------------------------------------------------- #


class Browser:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.jar)
        )

    def get(self, url: str) -> tuple[int, str, str]:
        try:
            with self.opener.open(url, timeout=120) as r:
                return r.status, r.geturl(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.geturl(), e.read().decode("utf-8", "replace")

    def post_form(self, url: str, fields: dict[str, str]) -> tuple[int, str, str]:
        data = urllib.parse.urlencode(fields).encode()
        try:
            with self.opener.open(urllib.request.Request(url, data=data), timeout=120) as r:
                return r.status, r.geturl(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.geturl(), e.read().decode("utf-8", "replace")

    def token(self) -> str | None:
        for cookie in self.jar:
            if cookie.name == "token":
                return cookie.value
        return None


def sign_in(app_url: str, password: str, name: str | None = None) -> dict:
    """Open WebUI's 'Continue with Eugene', Eugene's page, and back. Returns
    who Open WebUI says signed in, or what stopped it."""
    browser = Browser()
    status, at, page = browser.get(f"{app_url}/oauth/oidc/login")
    found = re.search(r'name="request" value="([^"]+)"', page)
    if status != 200 or not found or "/oidc/authorize" not in at:
        return {"error": f"no sign-in page: {status} at {at}", "page": page[:300]}
    fields = {"request": found.group(1), "password": password}
    if name is not None:
        fields["name"] = name
    status, at, page = browser.post_form(at.split("?")[0], fields)
    token = browser.token()
    if not token:
        return {"error": f"not signed in: {status} at {at}", "page": page[:300]}
    status, me = api("GET", f"{app_url}/api/v1/auths/", token)
    return {"token": token, "status": status, "me": me if isinstance(me, dict) else {"raw": me}}


def chat(app_url: str, token: str) -> tuple[int | None, object]:
    return api("POST", f"{app_url}/api/chat/completions", token, {
        "model": MODEL, "stream": False,
        "messages": [{"role": "user", "content": "Say hello."}],
    }, timeout=180)


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def add_model(token: str) -> None:
    say("a model behind the gateway, the way the console adds one")
    name = "fixture"
    status, body = api("POST", f"{AGENT}/v1/components", token, {
        "name": name, "kind": "inference-driver", "url": "http://127.0.0.1:8086",
        "spawn": {"configFile": f"{name}.yaml"},
    })
    must("20", "the driver is declared", status in (200, 201), body)
    proxy = f"{AGENT}/api/proxy/{name}/v1/config"
    patch = {"provider": "openai_compat_custom", "baseUrl": f"http://127.0.0.1:{FIXTURE_PORT}/v1",
             "modelId": MODEL}
    ok = wait_for(lambda: api("PATCH", proxy, token, patch)[0] == 200, 60, 2)
    must("21", "its settings are saved", bool(ok))
    api("POST", f"{AGENT}/v1/components/{name}/restart", token)

    def listed():
        status, body = api("GET", f"{AGENT}/api/proxy/gateway/v1/models", token)
        ids = [m.get("id") for m in (body or {}).get("data", [])] if status == 200 else []
        return MODEL in ids or None

    must("22", "the gateway routes the fixture model", bool(wait_for(listed, 120, 3)))


def add_search(token: str) -> None:
    say("a search account behind the gateway, the way the console adds one")
    status, body = api("POST", f"{AGENT}/v1/components", token, {
        "name": "searx", "kind": "tool-driver", "url": f"http://127.0.0.1:{SEARX_PORT}",
        "spawn": {"configFile": "searx.yaml"},
    })
    must("23", "the search account is declared", status in (200, 201), body)
    patch = {"provider": "searxng", "baseUrl": f"http://127.0.0.1:{FIXTURE_PORT}/searx",
             "probeMinutes": 0}
    proxy = f"{AGENT}/api/proxy/searx/v1/config"
    ok = wait_for(lambda: api("PATCH", proxy, token, patch)[0] == 200, 90, 2)
    must("24", "its settings are saved", bool(ok))

    def searched():
        status, _ = api("POST", f"{AGENT}/api/proxy/gateway/v1/web_search", token,
                        {"query": "readiness", "count": 1})
        return status == 200 or None

    must("25", "the gateway searches through it", bool(wait_for(searched, 180, 3)))


def add_router(token: str) -> None:
    say("an image model added after Open WebUI first started")
    status, body = api("POST", f"{AGENT}/v1/components", token, {
        "name": "router", "kind": "inference-driver", "url": f"http://127.0.0.1:{ROUTER_PORT}",
        "spawn": {"configFile": "router.yaml"},
    })
    must("80", "the image backend is declared", status in (200, 201), body)
    patch = {"provider": "openrouter", "baseUrl": f"http://127.0.0.1:{FIXTURE_PORT}/or",
             "apiKey": "fixture-not-a-key"}
    ok = wait_for(lambda: api("PATCH", f"{AGENT}/api/proxy/router/v1/config", token, patch)[0] == 200,
                  90, 2)
    must("81", "its settings are saved", bool(ok))
    api("POST", f"{AGENT}/v1/components/router/restart", token)

    def listed():
        status, body = api("GET", f"{AGENT}/api/proxy/gateway/v1/models", token)
        ids = [m.get("id", "") for m in (body or {}).get("data", [])] if status == 200 else []
        return any(i.endswith("painter") for i in ids) or None

    must("82", "the gateway lists the stand-in image model", bool(wait_for(listed, 180, 3)))


def gateway_rows(token: str) -> list[dict]:
    _, body = api("GET", f"{AGENT}/api/proxy/gateway/v1/metrics/requests?limit=500", token)
    return (body or {}).get("requests", [])


def images_config(app_url: str, token: str | None) -> dict:
    _, config = api("GET", f"{app_url}/api/v1/images/config", token)
    return config if isinstance(config, dict) else {}


def paint(app_url: str, token: str | None) -> tuple[int | None, object]:
    return api("POST", f"{app_url}/api/v1/images/generations", token,
               {"prompt": "a red fox in snow", "n": 1, "size": "512x512"}, timeout=180)


def wait_running(token: str) -> dict | None:
    time.sleep(3)

    def running():
        _, app = api("GET", f"{AGENT}/v1/apps/{APP}", token)
        return app if (app or {}).get("status") == "running" else None

    return wait_for(running, 600, 3)


# --- the update run: the catalogue file is edited, so one install can hold two versions ---


def catalogue_file() -> Path:
    if WINDOWS:
        found = sorted((c1.PREFIX / "venv").glob("**/eugene_plexus_agent/apps_catalogue.yaml"))
    else:
        # The service's venv is closed to this account.
        out = subprocess.run(
            ["sudo", "find", str(c1.PREFIX / "venv"), "-path", "*/eugene_plexus_agent/apps_catalogue.yaml"],
            capture_output=True, text=True, check=True)
        found = [Path(p) for p in sorted(out.stdout.split())]
    assert found, "the installed agent's catalogue file"
    return found[0]


def read_catalogue() -> str:
    path = catalogue_file()
    if WINDOWS:
        return path.read_text(encoding="utf-8")
    return subprocess.run(["sudo", "cat", str(path)], capture_output=True, text=True,
                          check=True).stdout


def put_catalogue(text: str) -> None:
    path = catalogue_file()
    if WINDOWS:
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(text)
    subprocess.run(["sudo", "cp", f.name, str(path)], check=True)
    subprocess.run(["sudo", "chmod", "644", str(path)], check=True)


def variant(original: str, *, version: str | None = None, old_env: bool = False,
            broken: bool = False) -> str:
    """The open-webui entry at `version`, with the variables an older entry lacked, or with a
    variable that stops Open WebUI starting."""
    start = original.index("- id: open-webui")
    end = original.find("\n- id:", start + 1)
    end = len(original) if end == -1 else end
    block = original[start:end]
    if version:
        block, n = re.subn(r"^  version: \S+$", f"  version: {version}", block, count=1, flags=re.M)
        assert n == 1
    if old_env:
        block = re.sub(r"^    AUDIO_REALTIME_[A-Z_]+: .*\n", "", block, flags=re.M)
    if broken:
        block = block.replace('    ENABLE_PLUGINS: "true"\n',
                              '    ENABLE_PLUGINS: "true"\n    DATABASE_URL: "nosuchdialect://x"\n', 1)
        assert "nosuchdialect" in block
    return original[:start] + block + original[end:]


def restart_agent() -> str:
    if WINDOWS:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        "Restart-Service EugenePlexusAgent -Force"], check=True)
    else:
        subprocess.run(["sudo", "systemctl", "restart", "eugene-plexus-agent"], check=True)
    time.sleep(5)
    must("90", "the agent comes back after a restart", bool(wait_for(healthy(AGENT), 240)))
    wait_for(healthy(CONTROL), 240)
    token = wait_for(lambda: (api("POST", f"{AGENT}/v1/auth/login",
                                  body={"passphrase": PASSPHRASE})[1] or {}).get("sessionToken"),
                     240, 3)
    must("91", "a session after the restart", bool(token))
    return token


def catalogue_entry(token: str) -> dict:
    _, catalogue = api("GET", f"{AGENT}/v1/app-catalogue", token)
    return next((a for a in (catalogue or {}).get("apps", []) if a["manifest"]["id"] == APP), {})


def chat_titles(app_url: str, token: str | None) -> str:
    _, chats = api("GET", f"{app_url}/api/v1/chats/", token)
    return json.dumps(chats)


def new_chat(app_url: str, token: str | None, title: str) -> int | None:
    status, _ = api("POST", f"{app_url}/api/v1/chats/new", token, {"chat": {
        "title": title, "models": [MODEL], "messages": [],
        "history": {"messages": {}, "currentId": None},
    }})
    return status


def update_run(token: str) -> None:
    say("an update that copies Open WebUI's data first")
    shipped = read_catalogue()
    new_version = re.search(r"^  version: (\S+)$", shipped[shipped.index("- id: open-webui"):],
                            flags=re.M).group(1)

    def finished():
        _, state = api("GET", f"{AGENT}/v1/apps/{APP}/install", token)
        return state if (state or {}).get("state") in ("done", "failed", "cancelled") else None

    try:
        put_catalogue(variant(shipped, version=OLD_VERSION, old_env=True))
        token = restart_agent()
        must("92", "the catalogue offers the old version",
             catalogue_entry(token).get("manifest", {}).get("version") == OLD_VERSION)
        app = install_app(token)
        app_url = f"http://127.0.0.1:{int(app.get('port') or 0)}"
        owner = sign_in(app_url, PASSPHRASE, OWNER_NAME)
        must("93", "the old version runs and its owner signs in", "token" in owner,
             owner.get("error"))
        must("94", "a chat is made on it",
             new_chat(app_url, owner["token"], "C4 before update") == 200)

        put_catalogue(variant(shipped, broken=True) if WINDOWS else shipped)
        token = restart_agent()
        entry = catalogue_entry(token)
        check("95", "the catalogue says the update resets Open WebUI's settings",
              entry.get("installedVersion") == OLD_VERSION and entry.get("resetsSettings") is True,
              {k: entry.get(k) for k in ("installedVersion", "resetsSettings")})
        status, body = api("POST", f"{AGENT}/v1/apps/{APP}/install", token)
        must("96", "the update starts", status in (200, 202), body)
        state = wait_for(finished, 1800, 5) or {}
        if not WINDOWS:
            text = json.dumps(state)
            check("97", "on a Linux system install the update is refused and names its cause",
                  state.get("state") == "failed" and "systemd account of its own" in text, text[:500])
            _, now = api("GET", f"{AGENT}/v1/apps/{APP}", token)
            check("98", "and nothing changed: the old version still runs",
                  (now or {}).get("version") == OLD_VERSION and (now or {}).get("status") == "running",
                  {k: (now or {}).get(k) for k in ("version", "status")})
            status, body = api("POST", f"{AGENT}/v1/apps/{APP}/rollback", token)
            check("99", "Go back is refused with the same cause",
                  status == 409 and "systemd account of its own" in json.dumps(body), body)
            return
        must("97", "the new version installs", state.get("state") == "done", state)

        def failed():
            _, view = api("GET", f"{AGENT}/v1/apps/{APP}", token)
            view = view or {}
            return view if view.get("status") != "running" and (
                view.get("lastError") or view.get("detail")) else None

        view = wait_for(failed, 600, 5) or api("GET", f"{AGENT}/v1/apps/{APP}", token)[1] or {}
        check("98", "its start fails and the app page names the cause",
              view.get("status") != "running" and bool(view.get("lastError") or view.get("detail")),
              {k: view.get(k) for k in ("status", "lastError", "detail")})
        check("99", "a backup of the old version is kept",
              view.get("previousVersion") == OLD_VERSION
              and (view.get("updateBackup") or {}).get("version") == OLD_VERSION,
              {k: view.get(k) for k in ("previousVersion", "updateBackup")})
        database = c1.PREFIX / "apps" / APP / "data" / "webui.db"
        try:
            database.write_bytes(b"the new version damaged this")
            fact("database damaged before Go back", True)
        except OSError as exc:
            fact("database damaged before Go back", f"no: {exc}")
        status, body = api("POST", f"{AGENT}/v1/apps/{APP}/rollback", token, timeout=300)
        must("100", "Go back is accepted", status == 200, body)
        back = wait_running(token)
        check("101", "the old version runs again", bool(back) and back.get("version") == OLD_VERSION,
              {k: (back or {}).get(k) for k in ("version", "status")})
        owner = sign_in(app_url, PASSPHRASE, OWNER_NAME)
        check("102", "and the earlier chat is back",
              "C4 before update" in chat_titles(app_url, owner.get("token")), owner.get("error"))

        put_catalogue(shipped)
        token = restart_agent()
        status, body = api("POST", f"{AGENT}/v1/apps/{APP}/install", token)
        must("103", "the update, with nothing broken, starts", status in (200, 202), body)
        state = wait_for(finished, 1800, 5) or {}
        must("104", "it installs", state.get("state") == "done", state)
        now = wait_running(token)
        check("105", f"it runs on {new_version}", bool(now) and now.get("version") == new_version,
              {k: (now or {}).get(k) for k in ("version", "status")})
        owner = sign_in(app_url, PASSPHRASE, OWNER_NAME)
        check("106", "the chat made on the old version is there after the update",
              "C4 before update" in chat_titles(app_url, owner.get("token")), owner.get("error"))
        check("107", "the update left a backup to go back to",
              ((api("GET", f"{AGENT}/v1/apps/{APP}", token)[1] or {}).get("updateBackup") or {})
              .get("version") == OLD_VERSION)
    finally:
        put_catalogue(shipped)
        api("DELETE", f"{AGENT}/v1/apps/{APP}?purge=true", token)


def install_app(token: str) -> dict:
    status, body = api("POST", f"{AGENT}/v1/apps/{APP}/install", token)
    must("31", "Open WebUI's install starts", status in (200, 202), body)
    started = time.perf_counter()

    def finished():
        _, state = api("GET", f"{AGENT}/v1/apps/{APP}/install", token)
        return state if (state or {}).get("state") in ("done", "failed", "cancelled") else None

    state = wait_for(finished, 1800, 5) or {}
    fact("install seconds", round(time.perf_counter() - started, 1))
    must("32", "it installs from PyPI at the pinned version", state.get("state") == "done", state)

    def ready():
        _, app = api("GET", f"{AGENT}/v1/apps/{APP}", token)
        return app if (app or {}).get("status") == "running" else None

    started = time.perf_counter()
    app = wait_for(ready, 600, 3)
    fact("seconds to ready", round(time.perf_counter() - started, 1))
    must("33", "it runs and answers /ready", bool(app), api("GET", f"{AGENT}/v1/apps/{APP}", token)[1])
    return app


def data_dir() -> Path:
    if WINDOWS:
        return c1.PREFIX / "apps" / APP / "data"
    return Path("/var/lib/private/eugene-plexus-apps") / APP


def sudo_ls(path: Path) -> list[str]:
    if WINDOWS:
        return [p.name for p in path.iterdir()] if path.is_dir() else []
    out = subprocess.run(["sudo", "ls", "-A", str(path)], capture_output=True, text=True)
    return out.stdout.split() if out.returncode == 0 else []


def owner_of(port: int) -> str:
    """The account of the process listening on the app's port."""
    if WINDOWS:
        script = (
            f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object -First 1; "
            "(Get-Process -Id $c.OwningProcess -IncludeUserName).UserName"
        )
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                             capture_output=True, text=True)
        return out.stdout.strip()
    out = subprocess.run(["sudo", "ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True)
    found = re.search(r"pid=(\d+)", out.stdout)
    if not found:
        return ""
    user = subprocess.run(["ps", "-o", "user=", "-p", found.group(1)], capture_output=True, text=True)
    return user.stdout.strip()


def account_of(pid: int) -> str:
    """The account of the app's own process. Since LT2 the agent's door holds
    the app's port and the app listens on loopback behind it, so the port's
    listener is the agent by design; the process is what runs as the app."""
    if WINDOWS:
        script = f"(Get-Process -Id {pid} -IncludeUserName).UserName"
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                             capture_output=True, text=True)
        return out.stdout.strip()
    user = subprocess.run(["ps", "-o", "user=", "-p", str(pid)], capture_output=True, text=True)
    return user.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="ep-c4-"))
    try:
        serve_fixture()
        c1.phase_install(c1.installer_copy(work))
        token = c1.phase_onboard()
        add_model(token)
        add_search(token)

        say("Open WebUI in the catalogue")
        _, catalogue = api("GET", f"{AGENT}/v1/app-catalogue", token)
        entry = next((a for a in (catalogue or {}).get("apps", []) if a["manifest"]["id"] == APP), None)
        manifest = (entry or {}).get("manifest") or {}
        must("30", "the catalogue offers it from PyPI, with its licence, needing an account of its own",
             manifest.get("source") == "pypi" and bool(manifest.get("licenseUrl"))
             and manifest.get("localActions") is True and (catalogue or {}).get("ownAccounts") is True,
             {k: manifest.get(k) for k in ("source", "version", "licenseUrl", "localActions")})
        fact("Open WebUI version", manifest.get("version"))
        app = install_app(token)
        port = int(app.get("port") or 0)
        app_url = f"http://127.0.0.1:{port}"
        account = account_of(int(app["pid"])) if app.get("pid") else owner_of(port)
        fact("account", account)
        check("34", "it runs in an account of its own, not the agent's",
              app.get("isolation") == "own_account" and bool(account)
              and account.lower() != c1.AGENT_ACCOUNT,
              {"isolation": app.get("isolation"), "reported": app.get("account"), "os": account})
        hf = sudo_ls(data_dir() / "hf")
        check("35", "no model was downloaded: embeddings and transcription go to the gateway",
              not any(name.startswith("models--") for name in hf + sudo_ls(data_dir() / "hf" / "hub")), hf)
        check("36", "its writes are in its data directory: static files and its secret are there",
              "static" in sudo_ls(data_dir()), sudo_ls(data_dir()))

        say("signing in through Eugene")
        owner = sign_in(app_url, PASSPHRASE)
        me = owner.get("me") or {}
        must("40", "the owner signs in with the passphrase and arrives as Open WebUI's admin",
             me.get("role") == "admin", owner.get("error") or me)
        check("41", "the owner, who has no email in Eugene, gets Open WebUI's placeholder",
              str(me.get("email", "")).endswith(".local"), me.get("email"))
        _, clogin = api("POST", f"{CONTROL}/v1/auth/login", body={"passphrase": PASSPHRASE})
        ctoken = (clogin or {}).get("sessionToken")
        status, ada = api("POST", f"{CONTROL}/v1/people", ctoken,
                          {"name": "ada", "password": PERSON_PASSWORD, "email": "ada@example.org"})
        must("42", "the owner adds a person with an email", status == 201, ada)
        status, bo = api("POST", f"{CONTROL}/v1/people", ctoken, {"name": "bo", "password": PERSON_PASSWORD})
        must("43", "and one without", status == 201, bo)
        signed = sign_in(app_url, PERSON_PASSWORD, "ada")
        me = signed.get("me") or {}
        check("44", "a person arrives as a user, known by the email Eugene gave",
              me.get("role") == "user" and me.get("email") == "ada@example.org", signed.get("error") or me)
        signed = sign_in(app_url, PERSON_PASSWORD, "bo")
        me = signed.get("me") or {}
        check("45", "a person without an email arrives as a user with the placeholder",
              me.get("role") == "user" and str(me.get("email", "")).endswith(".local"),
              signed.get("error") or me)
        api("PATCH", f"{CONTROL}/v1/people/{bo['id']}", ctoken, {"disabled": True})
        refused = sign_in(app_url, PERSON_PASSWORD, "bo")
        check("46", "a person turned off in Eugene cannot sign in", "token" not in refused, refused)

        say("a chat through the gateway, on the app's key")
        status, answer = chat(app_url, owner["token"])
        text = json.dumps(answer)
        must("50", "a chat answers from the fixture model", status == 200 and "C4-ANSWER" in text, text[:300])
        # The operator's readiness search (step 25) is the install's own, not the app's.
        keys = {r.get("clientKeyName") for r in gateway_rows(token)
                if not (r.get("door") == "web_search" and not r.get("clientKeyName"))}
        check("51", "the gateway records its requests under the app's key and no other",
              keys == {app.get("keyName")}, sorted(map(str, keys)))

        say("web search through the gateway, on the app's key")
        searched_before = len(SEARCHED)
        status, found = api("POST", f"{app_url}/api/v1/retrieval/process/web/search",
                            owner["token"], {"queries": ["eugene plexus fixture"]}, timeout=180)
        text = json.dumps(found)
        check("52", "Open WebUI's web search returns the stand-in engine's results",
              status == 200 and f"127.0.0.1:{FIXTURE_PORT}/pages/" in text, text[:300])
        check("53", "the engine was asked once through the install's search account",
              len(SEARCHED) > searched_before, SEARCHED[-3:])
        rows = [r for r in gateway_rows(token) if r.get("door") == "web_search"
                and r.get("clientKeyName") == app.get("keyName")]
        check("54", "the gateway records the search under the app's key", bool(rows),
              [(r.get("door"), r.get("clientKeyName")) for r in gateway_rows(token)][-5:])
        check("55", "no result page was fetched: Open WebUI used the snippets", not PAGES, PAGES)

        say("images: none until a model is served, then Reset")
        new_chat(app_url, owner["token"], "C4 before reset")
        before = images_config(app_url, owner["token"])
        check("56", "with no image model at the first start, image generation is off",
              before.get("ENABLE_IMAGE_GENERATION") is False, {k: before.get(k) for k in (
                  "ENABLE_IMAGE_GENERATION", "IMAGE_GENERATION_MODEL")})
        if not WINDOWS:
            _, given = api("GET", f"{AGENT}/v1/apps/{APP}", token)
            check("57", "the app page does not claim settings it cannot read here",
                  not (given or {}).get("givenSettings"), (given or {}).get("givenSettings"))
        else:
            _, given = api("GET", f"{AGENT}/v1/apps/{APP}", token)
            check("57", "the app page says what Eugene gave: search on, no image model",
                  ((given or {}).get("givenSettings") or {}).get("webSearchEnabled") is True
                  and not ((given or {}).get("givenSettings") or {}).get("imageModel"),
                  (given or {}).get("givenSettings"))
        add_router(token)
        _, offered = api("GET", f"{AGENT}/v1/apps/{APP}", token)
        check("58", "the app page offers the image model Open WebUI was not given",
              str((offered or {}).get("availableImageModel") or "").endswith("painter"),
              (offered or {}).get("availableImageModel"))
        status, body = api("POST", f"{AGENT}/v1/apps/{APP}/restart", token, {"resetSettings": True},
                           timeout=180)
        if WINDOWS:
            must("59", "Reset restarts it once", status == 200, body)
            wait_running(token)
            owner = sign_in(app_url, PASSPHRASE, OWNER_NAME)
            after = images_config(app_url, owner.get("token"))
            check("66", "after Reset the image model is on",
                  after.get("ENABLE_IMAGE_GENERATION") is True
                  and str(after.get("IMAGE_GENERATION_MODEL", "")).endswith("painter"),
                  {k: after.get(k) for k in ("ENABLE_IMAGE_GENERATION", "IMAGE_GENERATION_MODEL")})
            check("67", "and the earlier chat is still there",
                  "C4 before reset" in chat_titles(app_url, owner.get("token")), owner.get("error"))
            status, image = paint(app_url, owner.get("token"))
            check("68", "an image request is answered by the stand-in model through the gateway",
                  status == 200 and bool(PAINTED), (status, str(image)[:200], PAINTED[-1:]))
        else:
            check("59", "on a Linux system install Reset is refused and names its cause",
                  status == 409 and "systemd account of its own" in json.dumps(body), (status, body))

        say("what its admin sets survives a restart; a new key is taken")
        banner = {"id": "c4", "type": "info", "title": "", "content": "C4 banner",
                  "dismissible": True, "timestamp": int(time.time())}
        status, _ = api("POST", f"{app_url}/api/v1/configs/banners", owner["token"], {"banners": [banner]})
        must("60", "its admin sets a banner", status == 200, status)
        api("POST", f"{AGENT}/v1/apps/{APP}/restart", token)
        time.sleep(3)
        wait_for(lambda: api("GET", f"{AGENT}/v1/apps/{APP}", token)[1].get("status") == "running" or None,
                 300, 3)
        owner = sign_in(app_url, PASSPHRASE, OWNER_NAME)
        _, banners = api("GET", f"{app_url}/api/v1/configs/banners", owner.get("token"))
        check("61", "a restart with nothing changed keeps it",
              "C4 banner" in json.dumps(banners), banners)
        old_key = app.get("keyId")
        status, _ = api("DELETE", f"{AGENT}/v1/apps/{APP}", token)
        must("62", "uninstalled, keeping its data", status == 204, status)
        app = install_app(token)
        port = int(app.get("port") or port)
        app_url = f"http://127.0.0.1:{port}"
        owner = sign_in(app_url, PASSPHRASE, OWNER_NAME)
        status, answer = chat(app_url, owner.get("token") or "")
        check("63", "reinstalled with a new key, it chats on the new key (a one-start reset)",
              status == 200 and "C4-ANSWER" in json.dumps(answer), json.dumps(answer)[:300])
        _, logs = api("GET", f"{AGENT}/v1/logs?contains={RESET_WORDS}", token)
        said = json.dumps(logs)
        check("64", "and its log says why its settings were reset",
              RESET_WORDS.replace("%20", " ") in said, said[-400:])
        check("65", "the reinstall minted a different key", bool(old_key) and old_key != app.get("keyId"),
              [old_key, app.get("keyId")])

        status, image = paint(app_url, owner.get("token"))
        now = images_config(app_url, owner.get("token"))
        check("69", "the reinstall's new key carries the image model too: images work",
              now.get("ENABLE_IMAGE_GENERATION") is True and status == 200 and bool(PAINTED),
              {"config": now.get("ENABLE_IMAGE_GENERATION"), "status": status,
               "painted": len(PAINTED), "body": str(image)[:200]})
        rows = [r for r in gateway_rows(token) if r.get("clientKeyName") == app.get("keyName")
                and (r.get("door") or "") in ("images", "generations", "edits")]
        check("73", "the gateway records the image request under the app's key", bool(rows),
              sorted({str(r.get("door")) for r in gateway_rows(token)}))

        say("uninstall takes it away")
        status, _ = api("DELETE", f"{AGENT}/v1/apps/{APP}?purge=true", token)
        must("70", "uninstalled with its data", status == 204, status)
        _, clients = api("GET", f"{CONTROL}/v1/oidc/clients", ctoken)
        names = [c.get("name") for c in (clients or {}).get("clients", [])]
        check("71", "its sign-in is gone at the root", "Open WebUI" not in names, names)
        check("72", "nothing listens on its port", not owner_of(port), owner_of(port))

        update_run(token)
    except Abort as stop:
        print(f"\nstopped: {stop}", flush=True)
    finally:
        if args.report:
            args.report.write_text(json.dumps({"results": c1.RESULTS, "facts": c1.FACTS}, indent=2),
                                   encoding="utf-8")
    failed = [r for r in c1.RESULTS if not r["passed"]]
    print(f"\n{len(c1.RESULTS) - len(failed)} of {len(c1.RESULTS)} passed", flush=True)
    finished = any(r["check"] == "72" for r in c1.RESULTS)
    return 1 if failed or not finished else 0


if __name__ == "__main__":
    sys.exit(main())
