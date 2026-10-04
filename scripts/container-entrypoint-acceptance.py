"""Migrate the disposable NAS acceptance container to one HTTPS port.

The legacy Workbench check ran first on the same temporary volume. This verifies
the shipped app, real OIDC provider, real proxy and existing chat data together.
"""
from __future__ import annotations

import html
import json
import os
import re
import socket
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

AGENT = "http://127.0.0.1:8079"
CONTROL = "http://127.0.0.1:8083"
CONSOLE = "https://eugene.home.arpa:18443"
WORKBENCH = "https://workbench.home.arpa:18443"


def wait(predicate, label, seconds=120):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            found = predicate()
            if found:
                return found
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(0.5)
    raise AssertionError("Timed out: " + label)


def main():
    assert os.environ.get("EUGENE_CONTAINER_ACCEPTANCE") == "1"
    assert Path("/.dockerenv").exists() and os.getuid() == 99
    fixture = json.loads(Path("/data/.entrypoint-acceptance.json").read_text())
    if "--prepare" in sys.argv:
        # Public test names resolve to this container only (--add-host). The
        # separate adversarial harness checks public users cannot reach admin.
        config = {"listen_port": 18443, "internal_ca": True}
        for service, name in (("console", "eugene"), ("workbench", "workbench"),
                              ("inference", "inference"), ("nodes", "nodes")):
            config[service] = {"origin": f"https://{name}.home.arpa:18443",
                               "networks": ["127.0.0.1/32", "172.16.0.0/12"]}
        Path("/data/entrypoint.json").write_text(json.dumps(config))
        return

    root = Path("/data/entrypoint/tls/pki/authorities/local/root.crt")
    wait(root.is_file, "local CA generation")
    context = ssl.create_default_context(cafile=str(root))
    with httpx.Client(verify=context, timeout=35, trust_env=False, follow_redirects=False) as client:
        def call(base, method, path, token=None, body=None, expected=200):
            response = client.request(method, base + path, json=body,
                                      headers={"Authorization": f"Bearer {token}"} if token else {})
            assert response.status_code == expected, (method, path, response.status_code, response.text[:300])
            return response.json() if response.content else None

        wait(lambda: client.get(CONSOLE + "/healthz").status_code == 200, "HTTPS console")
        wait(lambda: client.get(CONTROL + "/healthz").status_code == 200, "control root")
        call(CONTROL, "POST", "/v1/auth/login", body={"passphrase": fixture["password"]})
        token = call(CONSOLE, "POST", "/v1/auth/login", body={"passphrase": fixture["password"]})["sessionToken"]
        identity = call(CONSOLE, "GET", "/v1/node", token)
        assert identity["entrypoint"]["workbenchUrl"].rstrip("/") == WORKBENCH
        assert identity["entrypoint"]["nodesUrl"].rstrip("/") == "https://nodes.home.arpa:18443"
        app = call(CONSOLE, "GET", "/v1/apps/workbench", token)
        assert app["uiUrl"] == WORKBENCH + "/"
        assert "Restart" in app["detail"]
        call(CONSOLE, "POST", "/v1/apps/workbench/restart", token)
        wait(lambda: client.get(WORKBENCH + "/healthz").status_code == 200, "proxied Workbench")
        app = call(CONSOLE, "GET", "/v1/apps/workbench", token)
        assert app["oidcClientId"] != fixture["oidcClientId"]
        assert "Restart" not in (app.get("detail") or "")
        assert "<!doctype html>" in client.get(WORKBENCH + "/").text.lower()

        start = client.get(WORKBENCH + "/signin")
        assert start.status_code == 302, start.text
        assert start.headers["location"].startswith(CONSOLE + "/oidc/authorize?")
        signin_cookie = start.headers["set-cookie"]
        assert signin_cookie.startswith("__Host-workbench_signin=")
        assert "Secure" in signin_cookie and "HttpOnly" in signin_cookie and "Domain=" not in signin_cookie
        provider = client.get(start.headers["location"])
        assert provider.status_code == 200
        fields = {m.group(1): html.unescape(m.group(2)) for m in re.finditer(
            r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', provider.text)}
        fields.update(name="operator", password=fixture["password"])
        approved = client.post(urlsplit(start.headers["location"])._replace(query="").geturl(), data=fields)
        assert approved.status_code in (302, 303)
        assert approved.headers["location"].startswith(WORKBENCH + "/oidc/callback?")
        callback = client.get(approved.headers["location"])
        location = callback.headers.get("location", "")
        assert "#signin=" in location, location
        cookies = callback.headers.get_list("set-cookie")
        assert all("Secure" in cookie and "Domain=" not in cookie for cookie in cookies)
        headers = {"Origin": WORKBENCH, "X-Workbench-Secret": location.split("#signin=", 1)[1]}
        me = client.get(WORKBENCH + "/api/me", headers=headers)
        assert me.status_code == 200 and me.json()["consoleUrl"] == CONSOLE
        assert client.get(WORKBENCH + "/api/me").status_code == 401
        assert client.get(WORKBENCH + f"/api/chats/{fixture['chat']}", headers=headers).status_code == 200
        assert client.post(WORKBENCH + "/api/chats", json={}, headers={**headers, "Origin": CONSOLE}).status_code == 403
        assert client.get("https://inference.home.arpa:18443/v1/config").status_code == 403
        assert client.get("https://nodes.home.arpa:18443/v1/nodes").status_code == 401

        address = socket.gethostbyname(socket.gethostname())
        assert address != "127.0.0.1"
        for port in (8079, 8080, 8082, 8083, app["port"]):
            with socket.socket() as probe:
                probe.settimeout(1)
                assert probe.connect_ex((address, port)) != 0, f"backend port {port} escaped loopback"
        assert Path("/data/entrypoint").stat().st_mode & 0o777 == 0o700
        print("PASS: existing NAS Workbench migrates to HTTPS; exact callbacks, Secure cookies, CSRF, chat preservation and private backend ports", flush=True)

        call(CONSOLE, "POST", "/v1/apps/workbench/stop", token)
        wait(lambda: client.get(WORKBENCH + "/").status_code == 503, "stopped app route")
        call(CONSOLE, "POST", "/v1/apps/workbench/start", token)
        wait(lambda: client.get(WORKBENCH + "/api/me", headers=headers).status_code == 200, "session after app restart")
        current = call(CONSOLE, "GET", "/v1/apps/workbench", token)
        assert current["oidcClientId"] == app["oidcClientId"]
        print("PASS: stopping and starting Workbench refreshes the proxy and preserves its new sign-in", flush=True)


if __name__ == "__main__":
    main()
