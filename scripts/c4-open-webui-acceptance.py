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
RESET_WORDS = "connection%20details%20changed"

# --------------------------------------------------------------------------- #
# the fixture model, which records the bearer each request arrived with
# --------------------------------------------------------------------------- #

SEEN: list[dict] = []


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
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        else:
            self._send(200, {})

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
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
        account = owner_of(port)
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
        _, requests = api("GET", f"{AGENT}/api/proxy/gateway/v1/metrics/requests?limit=200", token)
        keys = {r.get("clientKeyName") for r in (requests or {}).get("requests", [])}
        check("51", "the gateway records its requests under the app's key and no other",
              keys == {app.get("keyName")}, sorted(map(str, keys)))

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

        say("uninstall takes it away")
        status, _ = api("DELETE", f"{AGENT}/v1/apps/{APP}?purge=true", token)
        must("70", "uninstalled with its data", status == 204, status)
        _, clients = api("GET", f"{CONTROL}/v1/oidc/clients", ctoken)
        names = [c.get("name") for c in (clients or {}).get("clients", [])]
        check("71", "its sign-in is gone at the root", "Open WebUI" not in names, names)
        check("72", "nothing listens on its port", not owner_of(port), owner_of(port))
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
