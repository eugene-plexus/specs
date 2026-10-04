"""Install and sign into Workbench in Compose acceptance's disposable NAS container.

Runs inside ep-uid-check as uid 99, without a passwd entry, with HOME=/.
The containing harness publishes the app port and checks it from outside too.
"""

from __future__ import annotations

import html
import os
import pwd
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

AGENT = "http://127.0.0.1:8079"
CONTROL = "http://127.0.0.1:8083"


def wait(predicate, label: str, seconds: float = 120):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError(f"Timed out: {label}")


def main() -> None:
    assert os.environ.get("EUGENE_CONTAINER_ACCEPTANCE") == "1"
    assert Path("/.dockerenv").exists() and os.getuid() == 99
    assert os.environ.get("HOME") == "/"
    try:
        pwd.getpwuid(99)
    except KeyError:
        pass
    else:
        raise AssertionError("NAS test uid unexpectedly has a passwd entry")

    password = secrets.token_urlsafe(24)
    with httpx.Client(timeout=120, trust_env=False, follow_redirects=False) as client:

        def call(base, method, path, token=None, body=None, expected=200):
            response = client.request(
                method,
                base + path,
                headers={"Authorization": f"Bearer {token}"} if token else {},
                json=body,
            )
            assert response.status_code == expected, (
                f"{method} {path}: {response.status_code} {response.text[:500]}"
            )
            return response.json() if response.content else None

        for base in (AGENT, CONTROL):
            wait(lambda: client.get(base + "/healthz").status_code == 200, base)
        call(
            CONTROL,
            "POST",
            "/v1/auth/initialize",
            body={"passphrase": password},
            expected=204,
        )
        call(AGENT, "POST", "/v1/auth/initialize", body={"passphrase": password})
        wait(
            lambda: client.get(CONTROL + "/healthz").status_code == 200,
            "control after initialization",
        )
        control_token = call(
            CONTROL, "POST", "/v1/auth/login", body={"passphrase": password}
        )["sessionToken"]
        join = call(
            CONTROL,
            "POST",
            "/v1/nodes/join-token",
            control_token,
            {"nodeName": "nas-acceptance", "grants": ["gateway"]},
            expected=201,
        )["token"]
        token = call(AGENT, "POST", "/v1/auth/login", body={"passphrase": password})[
            "sessionToken"
        ]
        call(
            AGENT,
            "POST",
            "/v1/node/enroll",
            token,
            {"controlUrl": CONTROL, "token": join, "name": "nas-acceptance"},
        )
        for base in (AGENT, CONTROL):
            wait(lambda: client.get(base + "/healthz").status_code == 200, base)
        token = call(AGENT, "POST", "/v1/auth/login", body={"passphrase": password})[
            "sessionToken"
        ]
        catalogue = call(AGENT, "GET", "/v1/app-catalogue", token)
        assert catalogue["ownAccounts"] is False
        entry = next(
            row for row in catalogue["apps"] if row["manifest"]["id"] == "workbench"
        )
        assert entry["manifest"]["localActions"] is False
        call(AGENT, "POST", "/v1/apps/workbench/install", token, expected=202)

        def installed():
            progress = call(AGENT, "GET", "/v1/apps/workbench/install", token)
            return (
                progress
                if progress["state"] in {"done", "failed", "cancelled"}
                else None
            )

        progress = wait(installed, "Workbench installation", 900)
        assert progress["state"] == "done", progress
        assert Path("/data/apps/.cache/uv").is_dir()
        assert not Path("/.cache/uv").exists()
        print(
            "PASS: Workbench installs as uid 99 with HOME=/; uv cache stays on /data",
            flush=True,
        )

        def running():
            app = call(AGENT, "GET", "/v1/apps/workbench", token)
            return app if app["status"] == "running" else None

        app = wait(running, "Workbench startup")
        assert app["port"] == 8190, app["port"]
        base = f"http://127.0.0.1:{app['port']}"
        assert client.get(base + "/healthz").status_code == 200
        page = client.get(base + "/")
        assert page.status_code == 200 and "<!doctype html>" in page.text.lower()

        start = client.get(base + "/signin")
        assert start.status_code == 302
        provider = client.get(start.headers["location"])
        assert provider.status_code == 200
        fields = {
            match.group(1): html.unescape(match.group(2))
            for match in re.finditer(
                r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', provider.text
            )
        }
        fields.update(name="operator", password=password)
        approved = client.post(
            urlsplit(start.headers["location"])._replace(query="").geturl(), data=fields
        )
        assert approved.status_code in (302, 303)
        callback = client.get(approved.headers["location"])
        location = callback.headers.get("location", "")
        assert "#signin=" in location, location
        headers = {
            "Origin": base,
            "X-Workbench-Secret": location.split("#signin=", 1)[1],
        }
        assert client.get(base + "/api/me", headers=headers).status_code == 200
        print(
            "PASS: the installed Workbench serves its page and completes Eugene sign-in",
            flush=True,
        )

        call(AGENT, "POST", "/v1/apps/workbench/restart", token)
        wait(
            lambda: (
                (current if current and current.get("pid") != app.get("pid") else None)
                if (current := running())
                else None
            ),
            "Workbench restart",
        )
        wait(
            lambda: client.get(base + "/healthz").status_code == 200,
            "Workbench health after restart",
        )
        assert client.get(base + "/api/me", headers=headers).status_code == 200
        print("PASS: Workbench restarts and keeps the person's sign-in", flush=True)


if __name__ == "__main__":
    main()
