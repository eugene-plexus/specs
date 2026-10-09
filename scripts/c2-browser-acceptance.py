"""C2 in the system Chrome: the sign-in page and the console's People page.

Run with the agent's own venv, which serves the UI (`eugene-plexus-ui`
installed editable from the sibling `ui` checkout, built with
`npm run build:python`):

    ../agent/.venv/Scripts/python.exe scripts/c2-browser-acceptance.py

An agent on free ports supervises the control root, as on a real control
host, so the console's proxy finds `control` where an install declares it.
Playwright comes from `ui/node_modules`; Chrome is the system one. What a
real browser adds to c2-sign-in-acceptance.py: the page's own CSP applied,
including `form-action` on the redirect after the post, and the People page
driven by clicks.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ACCEPT = HERE / "c2-sign-in-acceptance.py"
RESULTS: list[tuple[str, bool, object]] = []


def check(claim: str, ok: bool, detail: object = "") -> None:
    RESULTS.append((claim, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {claim}  -- {detail}", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return verifier, challenge.decode()


def claims_of(id_token: str) -> dict:
    body = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="ep-c2-browser-"))
    shots = work / "shots"
    shots.mkdir()
    ports = {"control": free_port(), "agent": free_port(), "callback": free_port()}
    callback = f"http://127.0.0.1:{ports['callback']}/callback"

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"signed in")

        def log_message(self, *_: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", ports["callback"]), Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    # The agent supervises the control root, as on a real control host, so
    # the console's proxy finds `control` where an install declares it.
    import yaml

    agent_dir = work / "agent"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text(yaml.safe_dump({
        "firstRunComplete": True,
        "updateChecks": False,
        "securityMode": "prompt_on_startup",
        "components": [{
            "name": "control", "kind": "control",
            "url": f"http://127.0.0.1:{ports['control']}",
            "spawn": {"configFile": str(agent_dir / "control.yaml")},
        }],
    }), encoding="utf-8")
    procs = {
        "agent": subprocess.Popen(
            [sys.executable, str(ACCEPT), "--serve", "agent", "--directory", str(agent_dir),
             "--port", str(ports["agent"])],
            cwd=agent_dir, env=env, stdin=subprocess.DEVNULL, stdout=(agent_dir / "process.log").open("wb"),
            stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    }
    client = httpx.Client(timeout=30, trust_env=False)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, url(name) + path, headers=headers, **kw)

    def wait(name: str) -> None:
        for _ in range(300):
            try:
                if call(name, "GET", "/healthz").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise SystemExit(f"{name} did not start")

    try:
        wait("agent")
        wait("control")
        passphrase = secrets.token_urlsafe(24)
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        root = call("control", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        join = call("control", "POST", "/v1/nodes/join-token", root, json={"nodeName": "c2-browser"}).json()["token"]
        local = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).json()["sessionToken"]
        enrolled = call("agent", "POST", "/v1/node/enroll", local, timeout=60,
                        json={"controlUrl": url("control"), "token": join, "name": "c2-browser"})
        assert enrolled.status_code == 200, enrolled.text
        wait("agent")
        operator = call("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        made = call("control", "POST", "/v1/oidc/clients", root,
                    json={"name": "Acceptance app", "redirectUris": [callback]}).json()
        client_id, secret = made["client"]["clientId"], made["clientSecret"]
        issuer = url("agent") + "/oidc"

        def authorize() -> tuple[str, str]:
            verifier, challenge = pkce()
            q = {"response_type": "code", "client_id": client_id, "redirect_uri": callback,
                 "scope": "openid profile", "state": secrets.token_urlsafe(8),
                 "nonce": secrets.token_urlsafe(8), "code_challenge": challenge,
                 "code_challenge_method": "S256"}
            return f"{issuer}/authorize?{urlencode(q)}", verifier

        owner_url, owner_verifier = authorize()
        handoff = work / "handoff.json"
        result = work / "result.json"
        cfg = {"ownerUrl": owner_url, "passphrase": passphrase, "callback": callback,
               "console": url("agent"), "operatorToken": operator, "adaFirst": "adas-first-password",
               "adaOwn": "a-password-ada-chose", "shots": str(shots), "handoff": str(handoff),
               "result": str(result), "ui": str(ROOT / "ui")}
        (work / "cfg.json").write_text(json.dumps(cfg))
        node = subprocess.Popen(
            ["node", str(HERE / "c2-browser-acceptance.mjs"), str(work / "cfg.json")], stdin=subprocess.DEVNULL
        )
        ada_verifier = None
        while node.poll() is None:
            if ada_verifier is None and handoff.is_file():
                ada_url, ada_verifier = authorize()
                handoff.write_text(json.dumps({"ready": True, "adaUrl": ada_url}))
            time.sleep(0.1)
        out = json.loads(result.read_text())
        if out.get("error"):
            print(out["error"])

        def trade(final: str, verifier: str) -> dict:
            code = parse_qs(urlsplit(final).query).get("code", [""])[0]
            answer = httpx.post(issuer + "/token", trust_env=False, auth=(client_id, secret), data={
                "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                "redirect_uri": callback})
            return answer.json() if answer.status_code == 200 else {"error": answer.text}

        steps = out.get("steps", {})
        owner = steps.get("owner", {})
        check("the sign-in page renders with its own styles under its CSP",
              owner.get("styled") == "380px", owner.get("styled"))
        tokens = trade(owner.get("final", ""), owner_verifier) if owner else {}
        check("Chrome posts the passphrase and follows the redirect to the app with a code",
              claims_of(tokens["id_token"]).get("sub") == "operator" if "id_token" in tokens else False,
              owner.get("final", "")[:90])
        people = steps.get("people", {})
        check("the People page gives this page's address as the sign-in address",
              people.get("address") == issuer, people.get("address"))
        check("adding an app there shows its secret once, and closing the panel removes it",
              people.get("secretShown") is True and people.get("secretGone") is True, people)
        ada = steps.get("ada", {})
        tokens = trade(ada.get("final", ""), ada_verifier) if ada and ada_verifier else {}
        listed = call("control", "GET", "/v1/people", root).json()["people"]
        person = next((p for p in listed if p["name"] == "Ada"), {})
        check("Ada, added on the People page, signs in from Chrome and changes her password there",
              "id_token" in tokens and claims_of(tokens["id_token"]).get("sub") == person.get("id")
              and person.get("passwordChangedAt", "") > person.get("createdAt", ""),
              {"sub": claims_of(tokens["id_token"]).get("sub") if "id_token" in tokens else tokens,
               "changed": person.get("passwordChangedAt")})
        check("no CSP violation, page error or failed sign-in or People request",
              not out.get("console"), out.get("console"))
        print("  (other failed requests: the gateway and library this harness does not run,"
              " and Next's segment prefetches, which 404 on every page of the export:",
              sorted(set(x.split(": ", 1)[1] for x in out.get("elsewhere", []))), ")")
    finally:
        for p in procs.values():
            p.terminate()
        server.shutdown()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; shots in {shots}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
