"""Migrate the disposable NAS acceptance container to one HTTPS port.

The legacy Workbench check ran first on the same temporary volume. This verifies
the shipped app, real OIDC provider, real proxy and existing chat data together.

Since 2026-10-05 nobody restarts Workbench after the move: the agent moves its
sign-in return address at boot, with the same client, and this checks that.
The proxy phase leaves out the node name, so the control root keeps its
direct port for enrolled machines while every other backend stays private.
"""
from __future__ import annotations

import html
import contextlib
import json
import os
import re
import socket
import ssl
import subprocess
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
    if "--prepare-proxy" in sys.argv:
        path = Path("/data/entrypoint.json")
        config = json.loads(path.read_text())
        config.update(listen_port=8088, internal_ca=False,
                      proxy={"addresses": ["127.0.0.2"], "transport": "http"},
                      trusted_ca="/data/entrypoint/tls/pki/authorities/local/root.crt")
        # Two names, as the setup page makes by default.
        config.pop("inference", None)
        config.pop("nodes", None)
        path.write_text(json.dumps(config))
        return
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
        if "--proxy" in sys.argv:
            assert "nodesUrl" not in identity["entrypoint"]
        else:
            assert identity["entrypoint"]["nodesUrl"].rstrip("/") == "https://nodes.home.arpa:18443"
        # Nobody restarts Workbench: the agent moved its return address at boot,
        # with its own token, and kept the client it had (2026-10-05).
        app = wait(
            lambda: (found := call(CONSOLE, "GET", "/v1/apps/workbench", token))
            and "sign-in address" not in (found.get("detail") or "")
            and found,
            "Workbench's sign-in address moved at boot",
        )
        assert app["uiUrl"] == WORKBENCH + "/"
        assert app["oidcClientId"] == fixture["oidcClientId"], "the same client, not a new one"
        wait(lambda: client.get(WORKBENCH + "/healthz").status_code == 200, "proxied Workbench")
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
        if "--proxy" in sys.argv:
            # Names that were left out are not served at all.
            assert client.get("https://inference.home.arpa:18443/v1/models").status_code == 421
            assert client.get("https://nodes.home.arpa:18443/v1/nodes").status_code == 421
        else:
            assert client.get("https://inference.home.arpa:18443/v1/config").status_code == 403
            assert client.get("https://nodes.home.arpa:18443/v1/nodes").status_code == 401

        address = socket.gethostbyname(socket.gethostname())
        assert address != "127.0.0.1"
        private = [8079, 8080, 8082, app["port"]]
        if "--proxy" in sys.argv:
            # No node name: enrolled machines keep the control root's own port.
            with socket.socket() as probe:
                probe.settimeout(1)
                assert probe.connect_ex((address, 8083)) == 0, "control root lost its direct port"
        else:
            private.append(8083)
        for port in private:
            with socket.socket() as probe:
                probe.settimeout(1)
                assert probe.connect_ex((address, port)) != 0, f"backend port {port} escaped loopback"
        assert Path("/data/entrypoint").stat().st_mode & 0o777 == 0o700
        print("PASS: existing NAS Workbench migrates to HTTPS with no restart and the same client; exact callbacks, Secure cookies, CSRF, chat preservation and private backend ports", flush=True)

        call(CONSOLE, "POST", "/v1/apps/workbench/stop", token)
        wait(lambda: client.get(WORKBENCH + "/").status_code == 503, "stopped app route")
        call(CONSOLE, "POST", "/v1/apps/workbench/start", token)
        wait(lambda: client.get(WORKBENCH + "/api/me", headers=headers).status_code == 200, "session after app restart")
        current = call(CONSOLE, "GET", "/v1/apps/workbench", token)
        assert current["oidcClientId"] == app["oidcClientId"]
        print("PASS: stopping and starting Workbench refreshes the proxy and preserves its new sign-in", flush=True)


@contextlib.contextmanager
def front_proxy():
    """Disposable second Caddy, with real verified browser TLS and private HTTP."""
    if "--proxy" not in sys.argv:
        yield
        return
    hosts = [f"{name}.home.arpa" for name in ("eugene", "workbench", "inference", "nodes")]
    document = {
        "admin": {"disabled": True},
        "storage": {"module": "file_system", "root": "/data/entrypoint/tls"},
        "apps": {
            "pki": {"certificate_authorities": {"local": {"install_trust": False}}},
            "tls": {"automation": {"policies": [{"subjects": hosts, "issuers": [{"module": "internal"}]}]}},
            "http": {"servers": {"front": {
                "listen": [":18443"], "protocols": ["h1", "h2"], "strict_sni_host": True,
                "automatic_https": {"disable_redirects": True},
                "tls_connection_policies": [{"match": {"sni": hosts}}],
                "routes": [{"match": [{"host": hosts}], "handle": [{
                    "handler": "reverse_proxy", "upstreams": [{"dial": "127.0.0.1:8088"}],
                    "transport": {"protocol": "http", "local_address": "127.0.0.2"},
                    "flush_interval": -1,
                }]}],
            }}},
        },
    }
    path = Path("/data/.acceptance-front.json")
    path.write_text(json.dumps(document))
    with Path("/data/.acceptance-front.log").open("w+") as log:
        process = subprocess.Popen(["caddy", "run", "--config", str(path)], stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        try:
            yield
        except BaseException:
            log.flush()
            log.seek(0)
            print(log.read()[-4000:])
            raise
        finally:
            process.terminate()
            process.wait(timeout=15)


if __name__ == "__main__":
    with front_proxy():
        main()
