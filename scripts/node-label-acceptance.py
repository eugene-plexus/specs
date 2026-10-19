"""Node labels, isolated processes (docs/design/node-labels.md §4).

One real control root and two real agents on ephemeral loopback ports, with
temporary state; no models, no installed services, never the default ports.
Run with a Python that has editable installs of agent and control.

1. an agent enrolled with a label (the wizard's path, agent -> root) is
   listed under its name with that label;
2. an enrollment whose label another machine already has is refused before
   its join token is spent;
3. a label set at the root is shown, and the `node:<name>` hop between the
   agents still resolves by name -- the label is never a key;
4. the label survives a control-root restart.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import yaml


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    else:
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml", default_topology=False, bind_port=port
            )
        )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(directory: Path) -> None:
    names = ("control", "agent-a", "agent-b")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets)}
    for sock in sockets:
        sock.close()
    processes: dict[str, subprocess.Popen] = {}
    logs = []
    client = httpx.Client(timeout=15, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, url(name) + path, headers=headers, **kwargs)

    def wait(check, what: str, seconds: float = 20) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise AssertionError("timed out: " + what)

    def start(name: str) -> None:
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes[name] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", name,
             "--directory", str(work), "--port", str(ports[name])],
            cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    def stop(name: str) -> None:
        process = processes.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def login(name: str) -> str:
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        assert response.status_code == 200, response.text
        return response.json()["sessionToken"]

    def roster(token: str) -> dict[str, dict]:
        listed = call("control", "GET", "/v1/nodes", token)
        assert listed.status_code == 200, listed.text
        return {n["name"]: n for n in listed.json()["nodes"]}

    try:
        start("control")
        assert call("control", "POST", "/v1/auth/initialize",
                    json={"passphrase": passphrase}).status_code == 204
        root = login("control")

        def join_token() -> str:
            minted = call("control", "POST", "/v1/nodes/join-token", root, json={})
            assert minted.status_code == 201, minted.text
            return minted.json()["token"]

        standalone = {}
        for name in ("agent-a", "agent-b"):
            work = directory / name
            work.mkdir(exist_ok=True)
            (work / "agent.yaml").write_text(yaml.safe_dump({
                "firstRunComplete": True, "updateChecks": False, "advertiseUrl": url(name),
                "securityMode": "prompt_on_startup", "components": [],
            }))
            start(name)
            assert call(name, "POST", "/v1/auth/initialize",
                        json={"passphrase": passphrase}).status_code == 200
            standalone[name] = login(name)

        # 1. The wizard's path: the agent carries the label to the root.
        enrolled = call("agent-a", "POST", "/v1/node/enroll", standalone["agent-a"], json={
            "controlUrl": url("control"), "token": join_token(), "name": "agent-a",
            "label": "  Studio PC  ",
        })
        assert enrolled.status_code == 200, enrolled.text
        assert enrolled.json()["name"] == "agent-a", enrolled.text
        listed = roster(root)
        assert listed["agent-a"]["label"] == "Studio PC", listed
        print("PASS 1 an agent enrolled with a label is listed under its name with it", flush=True)

        # 2. A label another machine has is refused, and the token survives.
        token = join_token()
        clash = call("agent-b", "POST", "/v1/node/enroll", standalone["agent-b"], json={
            "controlUrl": url("control"), "token": token, "name": "agent-b",
            "label": "studio pc",
        })
        assert clash.status_code >= 400, clash.text
        assert "already called" in clash.text, clash.text
        assert "agent-b" not in roster(root)
        retried = call("agent-b", "POST", "/v1/node/enroll", standalone["agent-b"], json={
            "controlUrl": url("control"), "token": token, "name": "agent-b",
        })
        assert retried.status_code == 200, retried.text
        assert roster(root)["agent-b"]["label"] is None
        print("PASS 2 a taken label is refused before the join token is spent", flush=True)

        # 3. Labelled at the root; the hop between agents still goes by name.
        named = call("control", "PUT", "/v1/nodes/agent-b/label", root, json={"label": "Demo Rig"})
        assert named.status_code == 200 and named.json()["label"] == "Demo Rig", named.text
        # The agent proxy refuses a hop to a loopback address, which is all
        # one machine can offer, so the name's key surfaces are checked
        # where they are spent: a sign-in through agent-b is a session the
        # root mints for `node:agent-b` and that machine's trust bundle
        # accepts, and the root still probes the node it records by name.
        session_b = login("agent-b")
        own = call("agent-b", "GET", "/v1/node", session_b)
        assert own.status_code == 200 and own.json()["name"] == "agent-b", own.text
        assert call("control", "GET", "/v1/nodes/agent-b", root).status_code == 200
        by_label = call("control", "GET", "/v1/nodes/Demo%20Rig", root)
        assert by_label.status_code == 404, "a label must never resolve as a node"
        wait(lambda: roster(root)["agent-b"]["reachable"] is True, "the root probes agent-b", 90)
        print("PASS 3 a label is shown and node:<name> still signs in and probes by name", flush=True)

        # 4. In the log, so in the state a restarted root replays.
        stop("control")
        start("control")
        root = login("control")
        after = roster(root)
        assert (after["agent-a"]["label"], after["agent-b"]["label"]) == ("Studio PC", "Demo Rig")
        print("PASS 4 labels survive a control-root restart", flush=True)
    finally:
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
        serve(args.serve, args.directory, args.port)
    else:
        for key in [k for k in os.environ if k.startswith("EUGENE_PLEXUS_")]:
            del os.environ[key]
        directory = Path(tempfile.mkdtemp(prefix="ep-node-label-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory)
