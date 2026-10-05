"""Apply one HTTPS port from Settings, in a real container, and go back by itself.

Runs inside a disposable container started with no entry point variable and
`EUGENE_PLEXUS_AGENT_ENTRYPOINT_CONFIRM_SECONDS` short. It drives the agent's
own API the way the setup page does (2026-10-05):

1. Direct ports to start with; Apply writes /data/entrypoint.json and the
   agent restarts in place (same process id, the container never stops).
2. While on approval, an operator session through the new HTTPS address
   confirms it; nothing else does.
3. A second Apply that nobody signs in through goes back to the first, after
   the window, by itself, and says why.
4. Turning it off restarts on the direct ports and keeps the file.

The proxy is the real bundled Caddy with its local CA; nothing is mocked.
"""

from __future__ import annotations

import json
import os
import secrets
import ssl
import time
from pathlib import Path

import httpx

AGENT = "http://127.0.0.1:8079"
CONSOLE = "https://eugene.home.arpa:18443"
FILE = Path("/data/entrypoint.json")
ROOT = Path("/data/entrypoint/tls/pki/authorities/local/root.crt")


def wait(predicate, label: str, seconds: float = 120):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (httpx.HTTPError, OSError, ValueError):
            pass
        time.sleep(0.5)
    raise AssertionError(f"Timed out: {label}")


def setup(networks: list[str]) -> dict:
    service = lambda name: {  # noqa: E731
        "origin": f"https://{name}.home.arpa:18443",
        "networks": networks,
    }
    return {
        "listen_port": 18443,
        "internal_ca": True,
        "console": service("eugene"),
        "workbench": service("workbench"),
    }


def agent_pid() -> int:
    """The agent's pid: an in-place restart keeps it. Not the init process,
    whose command line names the agent too."""
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                cmdline = (entry / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if b"python" in cmdline[0] and any(
                part.endswith(b"eugene-plexus-agent") for part in cmdline[1:2]
            ):
                found.append(int(entry.name))
    assert len(found) == 1, found
    return found[0]


def main() -> None:
    assert os.environ.get("EUGENE_CONTAINER_ACCEPTANCE") == "1"
    assert Path("/.dockerenv").exists()
    assert "EUGENE_PLEXUS_AGENT_ENTRYPOINT_CONFIG" not in os.environ
    window = int(os.environ["EUGENE_PLEXUS_AGENT_ENTRYPOINT_CONFIRM_SECONDS"])
    password = secrets.token_urlsafe(24)
    with httpx.Client(timeout=30, trust_env=False) as plain:

        def call(method, path, token=None, body=None, expected=200, client=plain, base=AGENT):
            response = client.request(
                method,
                base + path,
                json=body,
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            assert response.status_code == expected, (
                method,
                path,
                response.status_code,
                response.text[:400],
            )
            return response.json() if response.content else None

        wait(lambda: plain.get(AGENT + "/healthz").status_code == 200, "agent")
        call("POST", "/v1/auth/initialize", body={"passphrase": password})
        token = call("POST", "/v1/auth/login", body={"passphrase": password})["sessionToken"]
        status = call("GET", "/v1/entrypoint", token)
        assert status == {"available": True, "path": str(FILE), "active": False}, status
        pid = agent_pid()

        # 1. Apply: saved, on approval, restarted in place.
        first = setup(["127.0.0.1/32", "172.16.0.0/12"])
        bad = {**first, "console": {**first["console"], "networks": ["0.0.0.0/0"]}}
        call("POST", "/v1/entrypoint/apply", token, {"configuration": bad}, expected=400)
        assert not FILE.exists()
        answer = call(
            "POST", "/v1/entrypoint/apply", token, {"configuration": first}, expected=202
        )
        assert answer["restarting"] is True and answer["confirmBy"]
        assert json.loads(FILE.read_text())["console"] == first["console"]
        wait(ROOT.is_file, "local CA after restart")
        context = ssl.create_default_context(cafile=str(ROOT))
        with httpx.Client(timeout=30, trust_env=False, verify=context) as tls:
            wait(lambda: tls.get(CONSOLE + "/healthz").status_code == 200, "HTTPS console")
            assert agent_pid() == pid, "the agent restarted in place"
            pending = call("GET", "/v1/entrypoint", token)
            assert pending["active"] is True and pending["confirmBy"], pending
            # A direct request is not someone reaching the new address.
            assert call("GET", "/v1/entrypoint", token)["confirmBy"]
            through = call("GET", "/v1/entrypoint", token, client=tls, base=CONSOLE)
            assert through["active"] is True
            assert "confirmBy" not in call("GET", "/v1/entrypoint", token)
            assert not Path("/data/entrypoint/pending.json").exists()
            print("PASS: Apply saves, restarts in place, and an operator through the new address confirms it", flush=True)

            # 2. A second Apply nobody signs in through goes back to the first.
            second = setup(["127.0.0.1/32"])
            call(
                "POST",
                "/v1/entrypoint/apply",
                token,
                {"configuration": second},
                client=tls,
                base=CONSOLE,
                expected=202,
            )
            wait(
                lambda: json.loads(FILE.read_text())["console"]["networks"] == ["127.0.0.1/32"],
                "second setup saved",
            )
            # Wait out the window without signing in through it.
            time.sleep(window + 3)

            def reverted():
                body = call("GET", "/v1/entrypoint", token)
                return body if body.get("reverted") else None

            body = wait(reverted, "the unconfirmed setup going back", seconds=window + 90)
            assert "nobody signed in" in body["reverted"], body
            assert json.loads(FILE.read_text())["console"] == first["console"]
            assert json.loads(Path(str(FILE) + ".reverted").read_text())["console"] == second["console"]
            wait(lambda: tls.get(CONSOLE + "/healthz").status_code == 200, "first setup back")
            assert agent_pid() == pid
            print("PASS: an applied setup nobody signs in through goes back by itself, and says why", flush=True)

            # 3. Turn off: direct ports again, file kept.
            call("DELETE", "/v1/entrypoint", token, client=tls, base=CONSOLE, expected=202)
        wait(lambda: Path(str(FILE) + ".disabled").is_file(), "file kept as .disabled")

        def direct():
            body = call("GET", "/v1/entrypoint", token)
            return body if body["active"] is False else None

        wait(direct, "direct ports after turning off")
        assert not FILE.exists() and agent_pid() == pid
        print("PASS: turning it off restarts on the direct ports and keeps the file", flush=True)


if __name__ == "__main__":
    main()
