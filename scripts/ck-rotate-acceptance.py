"""Row 24: client keys rotate and record last use, across real processes.

One real control root, one enrolled agent, one gateway and the A5 counting
fixture as the model backend. Loopback ports are OS-assigned, state is in a
temporary folder, and every `EUGENE_PLEXUS_*` variable is cleared. Run with
editable or pinned agent, control and gateway packages in one environment.

Checks:
 1. A request and a model listing set `lastUsedAt`, to the minute, and a
    listing loop writes at most a few log entries.
 2. A held stream runs on the old token while the key is rotated with a
    5-second overlap. Both tokens work, and with a limit of 1 the new token
    is refused while the old one streams.
 3. After the overlap, the old token is refused as replaced on both doors,
    and the stream finishes through lease renewals (two or more, past the
    retirement).
 4. A root restart keeps every one of these fields and the replacement.
 5. A key rotated with "Stop now" is refused at once, and the old token of a
    revoked key cannot be rotated back.

The installed-app key file (mode 0600, restart of an app that fills
`{clientKey}`) is covered by the agent's `test_apps.py`, which asserts the
mode on POSIX in CI; an app needs an installed environment this script does
not build.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml

HELD_SECONDS = 24.0
OVERLAP_SECONDS = 5


def a5():
    spec = importlib.util.spec_from_file_location(
        "a5_acceptance", Path(__file__).with_name("a5-scoped-keys-acceptance.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def a3():
    spec = importlib.util.spec_from_file_location(
        "a3_acceptance", Path(__file__).with_name("a3-client-keys-acceptance.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exercise(directory: Path) -> None:
    for name in [k for k in os.environ if k.startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    names = ("control", "agent", "gateway", "fixture")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets)}
    for sock in sockets:
        sock.close()
    processes: dict[str, subprocess.Popen] = {}
    logs = []
    client = httpx.Client(timeout=10, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name):
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, headers=None, **kwargs):
        merged = {"Authorization": f"Bearer {token}"} if token else {}
        merged.update(headers or {})
        return client.request(method, url(name) + path, headers=merged, **kwargs)

    def wait(check, label, seconds=15):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, AssertionError):
                pass
            time.sleep(0.1)
        raise AssertionError("timed out: " + label)

    def start(name, kind=None):
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                kind or name,
                "--directory",
                str(work),
                "--port",
                str(ports[name]),
            ],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    def stop(name):
        process = processes.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        assert response.status_code == 200, response.text
        return response.json()["sessionToken"]

    try:
        start("control")
        init = call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        assert init.status_code == 204, init.text
        root_session = login("control")
        work = directory / "agent"
        work.mkdir(exist_ok=True)
        (work / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": url("agent"),
                    "securityMode": "prompt_on_startup",
                    "components": [],
                }
            )
        )
        start("agent")
        init = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        assert init.status_code == 200, init.text
        standalone = login("agent")
        join = call(
            "control", "POST", "/v1/nodes/join-token", root_session, json={"grants": ["gateway"]}
        )
        assert join.status_code == 201, join.text
        enrolled = call(
            "agent",
            "POST",
            "/v1/node/enroll",
            standalone,
            json={"controlUrl": url("control"), "token": join.json()["token"], "name": "agent"},
        )
        assert enrolled.status_code == 200, enrolled.text
        operator = login("agent")

        start("fixture")
        driver = call(
            "agent",
            "POST",
            "/v1/components",
            operator,
            json={
                "name": "allowed-driver",
                "kind": "inference-driver",
                "url": url("fixture") + "/allowed",
            },
        )
        assert driver.status_code == 201, driver.text
        gateway_dir = directory / "gateway"
        gateway_dir.mkdir()
        (gateway_dir / "bootstrap.json").write_text(
            json.dumps(a3().gateway_bootstrap(directory / "agent", url("agent"))),
            encoding="utf-8",
        )
        (gateway_dir / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        start("gateway")

        def mint(name, **limits):
            response = call(
                "agent",
                "POST",
                "/v1/auth/client-keys",
                operator,
                # maxQueuedRequests 0: a request past the shared limit is refused at
                # once, as before the gateway's queue (row 11), which this checks.
                json={
                    "name": name,
                    "limits": {
                        "maxConcurrentRequests": 1,
                        "requestsPerMinute": 60,
                        "maxQueuedRequests": 0,
                        **limits,
                    },
                },
            )
            assert response.status_code == 201, response.text
            return response.json()

        def keys():
            response = call("agent", "GET", "/v1/auth/client-keys", operator)
            assert response.status_code == 200, response.text
            return {k["id"]: k for k in response.json()["keys"]}

        def revision():
            response = call("agent", "GET", "/v1/auth/client-keys/policy", operator)
            assert response.status_code == 200, response.text
            return response.json()["revision"]

        def models(token):
            return call("gateway", "GET", "/v1/models", token)

        def chat(token, **extra):
            return call(
                "gateway",
                "POST",
                "/v1/chat/completions",
                token,
                json={
                    "model": "allowed",
                    "messages": [{"role": "user", "content": "CK_PRIVATE_PROMPT"}],
                    **extra,
                },
            )

        def messages(token):
            return call(
                "gateway",
                "POST",
                "/v1/messages",
                headers={"x-api-key": token},
                json={
                    "model": "allowed",
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "CK_PRIVATE_PROMPT"}],
                },
            )

        # 1. last use -------------------------------------------------------
        old = mint("App")
        old_id = old["key"]["id"]
        assert "lastUsedAt" not in keys()[old_id]
        wait(lambda: models(old["token"]).status_code == 200, "listing works")
        wait(lambda: "lastUsedAt" in keys()[old_id], "lastUsedAt set by a listing")
        used = datetime.fromisoformat(keys()[old_id]["lastUsedAt"].replace("Z", "+00:00"))
        assert used.second == 0 and used.microsecond == 0, used
        before = revision()
        for _ in range(30):
            assert models(old["token"]).status_code == 200
        grown = revision() - before
        assert grown <= 3, f"30 model listings wrote {grown} log entries"
        print(f"PASS a listing sets lastUsedAt to the minute; 30 listings wrote {grown} entries", flush=True)

        # 2. rotate under a running stream ----------------------------------
        call("fixture", "POST", "/mode/allowed", json={"hold": True}).raise_for_status()
        outcome: dict[str, object] = {}

        def stream_old():
            with httpx.Client(timeout=HELD_SECONDS + 30, trust_env=False) as streamer:
                with streamer.stream(
                    "POST",
                    url("gateway") + "/v1/chat/completions",
                    headers={"Authorization": "Bearer " + old["token"]},
                    json={
                        "model": "allowed",
                        "stream": True,
                        "messages": [{"role": "user", "content": "CK_PRIVATE_PROMPT"}],
                    },
                ) as response:
                    outcome["status"] = response.status_code
                    outcome["lines"] = [line for line in response.iter_lines()]

        thread = threading.Thread(target=stream_old, daemon=True)
        began = time.perf_counter()
        thread.start()
        wait(lambda: call("fixture", "GET", "/stats").json()["allowed"] >= 1, "stream reached the backend")
        rotated = call(
            "agent",
            "POST",
            f"/v1/auth/client-keys/{old_id}/rotate",
            operator,
            json={"overlapSeconds": OVERLAP_SECONDS},
        )
        assert rotated.status_code == 201, rotated.text
        new = rotated.json()
        new_id = new["key"]["id"]
        assert new["token"] != old["token"] and new["key"]["replaces"] == old_id
        assert new["key"]["name"] == "App" and new["key"]["limits"] == old["key"]["limits"]
        listed = keys()
        assert listed[old_id]["replacedBy"] == new_id and "retiresAt" in listed[old_id]
        assert old["token"] not in json.dumps(listed) and new["token"] not in json.dumps(listed)
        wait(lambda: models(new["token"]).status_code == 200, "new token registered")
        assert models(old["token"]).status_code == 200, "old token works in the overlap"
        refused = chat(new["token"])
        assert refused.status_code == 429, (refused.status_code, refused.text)
        print("PASS both tokens work in the overlap and share one concurrency limit", flush=True)

        # 3. after the overlap ----------------------------------------------
        def old_replaced():
            response = models(old["token"])
            return response.status_code == 401 and "replaced" in response.text

        wait(old_replaced, "old token refused as replaced", seconds=OVERLAP_SECONDS + 20)
        anthropic = messages(old["token"])
        assert anthropic.status_code == 403 and "was replaced" in anthropic.text, anthropic.text
        assert chat(old["token"]).status_code == 401
        assert models(new["token"]).status_code == 200
        assert thread.is_alive(), "the stream must still be running"
        remaining = HELD_SECONDS - (time.perf_counter() - began)
        if remaining > 0:
            time.sleep(remaining)
        call("fixture", "POST", "/mode/allowed", json={"hold": False}).raise_for_status()
        thread.join(timeout=20)
        assert not thread.is_alive(), "stream did not finish"
        assert outcome["status"] == 200, outcome
        assert any("[DONE]" in line for line in outcome["lines"]), outcome["lines"][-3:]
        wait(lambda: chat(new["token"]).status_code == 200, "new token serves after the stream")
        print("PASS the old token is refused as replaced at both doors; the stream finished through renewals", flush=True)

        # 4. a root restart keeps the fields --------------------------------
        snapshot = keys()
        stop("control")
        start("control")
        login("control")
        wait(lambda: new_id in keys(), "root back", seconds=20)
        after = keys()
        for field in ("retiresAt", "replacedBy"):
            assert after[old_id][field] == snapshot[old_id][field], field
        assert after[new_id]["replaces"] == old_id
        assert after[new_id]["limits"] == new["key"]["limits"]
        assert "lastUsedAt" in after[old_id]
        wait(lambda: models(new["token"]).status_code == 200, "new token works after restart", seconds=20)
        assert models(old["token"]).status_code == 401
        print("PASS a root restart keeps retirement, replacement, limits and last use", flush=True)

        # 5. Stop now, and no way back from off ------------------------------
        other = mint("Phone")
        wait(lambda: models(other["token"]).status_code == 200, "second key registered")
        stopped = call(
            "agent",
            "POST",
            f"/v1/auth/client-keys/{other['key']['id']}/rotate",
            operator,
            json={"overlapSeconds": 0},
        )
        assert stopped.status_code == 201, stopped.text
        wait(
            lambda: models(other["token"]).status_code == 401
            and "replaced" in models(other["token"]).text,
            "Stop now refuses the old token",
            seconds=10,
        )
        gone = mint("Gone")
        assert (
            call("agent", "DELETE", "/v1/auth/client-keys/" + gone["key"]["id"], operator).status_code
            == 204
        )
        back = call("agent", "POST", f"/v1/auth/client-keys/{gone['key']['id']}/rotate", operator, json={})
        assert back.status_code == 409 and "turned off" in back.text, back.text
        again = call("agent", "POST", f"/v1/auth/client-keys/{old_id}/rotate", operator, json={})
        assert again.status_code == 409 and "already replaced" in again.text, again.text
        print("PASS Stop now refuses at once; a turned-off or replaced key cannot be rotated", flush=True)
    finally:
        try:
            call("fixture", "POST", "/mode/allowed", json={"hold": False})
        except Exception:
            pass
        for name in list(processes):
            stop(name)
        client.close()
        for log in logs:
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        a5().serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-ck-rotate-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory)
