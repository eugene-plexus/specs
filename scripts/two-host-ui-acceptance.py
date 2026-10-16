"""Production UI against a disposable real root/agent; no live settings change."""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    directory = Path(tempfile.mkdtemp(prefix="ep-two-host-ui-"))
    print(f"Artifacts: {directory}", flush=True)
    urls = {}
    processes = []
    logs = []
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env["EUGENE_PLEXUS_CONTROL_AGENT_PUBLIC_ORIGIN"] = "https://eugene.example.org"
    password = secrets.token_urlsafe(24)
    context = directory / "browser-context.json"
    try:
        with httpx.Client(trust_env=False, timeout=30) as http:
            def call(name, method, path, token=None, **kw):
                return http.request(method, urls[name] + path, headers={"Authorization": f"Bearer {token}"} if token else {}, **kw)

            for name in ("control", "agent"):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                urls[name] = f"http://127.0.0.1:{port}"
                work = directory / name
                work.mkdir()
                log = (work / "process.log").open("wb")
                logs.append(log)
                python = ROOT / name / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                processes.append(subprocess.Popen([
                    str(python), str(Path(__file__).with_name("u1-accounts-acceptance.py")),
                    "--serve", name, "--directory", str(work), "--port", str(port),
                ], cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
                deadline = time.perf_counter() + 45
                while True:
                    try:
                        if call(name, "GET", "/healthz").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    assert time.perf_counter() < deadline and processes[-1].poll() is None, work
                    time.sleep(.1)
            assert call("control", "POST", "/v1/auth/initialize", json={"passphrase": password}).status_code == 204
            owner = call("control", "POST", "/v1/auth/login", json={"passphrase": password}).json()["sessionToken"]
            join = call("control", "POST", "/v1/nodes/join-token", owner, json={"nodeName": "two-host-test"}).json()["token"]
            local = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": password}).json()["sessionToken"]
            enrolled = call("agent", "POST", "/v1/node/enroll", local, json={"controlUrl": urls["control"], "token": join, "name": "two-host-test"})
            assert enrolled.status_code == 200, enrolled.text
            operator = call("agent", "POST", "/v1/auth/login", json={"passphrase": password}).json()["sessionToken"]
            assert call("agent", "POST", "/v1/components", operator, json={"name": "control", "kind": "control", "url": urls["control"]}).status_code == 201
            context.write_text(json.dumps({"agent": urls["agent"], "password": password, "output": str(directory)}), encoding="utf-8")
            subprocess.run(["node", str(ROOT / "ui/scripts/two-host-browser-acceptance.mjs"), str(context)], cwd=ROOT / "ui", env=env, check=True)
            assert call("control", "GET", "/v1/config", owner).json().get("oidcIssuer") is None
            assert call("agent", "GET", "/v1/entrypoint", operator).json()["active"] is False
            print("PASS production setup, derived SSO, explicit override/reset, mobile layout; preview made no running changes", flush=True)
    finally:
        context.unlink(missing_ok=True)
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
