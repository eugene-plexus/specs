"""CX2: setup resumes where it stopped, on a real disposable install.

A fresh isolated install from this checkout's installer (the pinned UI
wheel, never `EUGENE_PLEXUS_AGENT_UI_DIR`), on a claimed port range away
from the live worker, with every ambient `EUGENE_PLEXUS_*` variable
cleared. The browser half (`cx2-setup-resume-browser.mjs`) sets the
passphrase, has the control root's initialize fail, and then reopens setup
in a new browser context, tries a wrong passphrase, and finishes.

Checked here over HTTP against the processes themselves, not the UI: the
root stayed uninitialized after the failure and after the wrong
passphrase, and at the end it is initialized with the right passphrase and
this agent is enrolled with it.

The one seam: the root's initialize is failed by the browser's request
routing (a 500 from `/api/proxy/control/v1/auth/initialize`), so the
install is left exactly as a real failure there leaves it. Requires httpx
and PyYAML, Node and Chrome, and the sibling UI's Node dependencies.
Windows only.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import yaml

HERE = Path(__file__).resolve().parent
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PASSPHRASE = "cx2-disposable-passphrase"


def snapshot_windows() -> dict:
    command = """
    $result = @{env=@{}; service=@()}
    foreach ($scope in @('User','Machine')) {
      $result.env[$scope] = @{}
      [Environment]::GetEnvironmentVariables($scope).GetEnumerator() |
        Where-Object { $_.Key -like 'EUGENE_PLEXUS_*' } |
        ForEach-Object { $result.env[$scope][$_.Key] = $_.Value }
    }
    $result.service = @(Get-CimInstance Win32_Service -Filter "Name='EugenePlexusAgent'" |
      Select-Object Name,State,ProcessId,PathName)
    $result | ConvertTo-Json -Depth 5 -Compress
    """
    return json.loads(subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", command], text=True))


def claim_ports() -> int:
    held: list[socket.socket] = []
    for base in range(19000, 29000, 100):
        try:
            for port in range(base, base + 12):
                sock = socket.socket()
                held.append(sock)
                sock.bind(("127.0.0.1", port))
            for sock in held:
                sock.close()
            return base
        except OSError:
            for sock in held:
                sock.close()
            held = []
    raise AssertionError("no free test port range")


def control_state(client: httpx.Client, control: str) -> bool:
    return client.get(control + "/v1/auth/status").json()["initialized"] is True


def run(root: Path) -> None:
    assert sys.platform == "win32", "Windows only"
    root.mkdir(parents=True, exist_ok=False)
    prefix = root / "install"
    before = snapshot_windows()
    base = claim_ports()
    agent_port = base + 1
    control = f"http://127.0.0.1:{base + 2}"
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update({"NO_PROXY": "localhost,127.0.0.1,::1", "PYTHONUTF8": "1",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port)})
    result: dict = {"ports": {"agent": agent_port, "control": base + 2}, "checks": {}}
    agent = None
    logs = []
    try:
        wrapper = root / "install-wrapper.ps1"
        installer = HERE / "install.ps1"
        wrapper.write_text("& '" + str(installer).replace("'", "''") + "' -Prefix '" +
                           str(prefix).replace("'", "''") + "' -NoService -NoStart -Isolated\n",
                           encoding="utf-8")
        with (root / "installer.log").open("w", encoding="utf-8") as log:
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                           env=env, cwd=root, stdout=log, stderr=log, check=True, timeout=900)
        python = prefix / "venv/Scripts/python.exe"
        versions = subprocess.check_output([str(python), "-c",
            "from importlib.metadata import version as v; import json; "
            "print(json.dumps({p: v(p) for p in ('eugene-plexus-ui', 'eugene-plexus-agent', "
            "'eugene-plexus-control')}))"], env=env, text=True)
        result["versions"] = json.loads(versions)
        # Only ports differ from first-boot defaults; auth state stays fresh.
        (prefix / "agent.yaml").write_text(yaml.safe_dump({"components": [
            {"name": name, "kind": name, "url": f"http://127.0.0.1:{base + offset}",
             "spawn": {"configFile": str(prefix / f"{name}.yaml")}}
            for name, offset in (("control", 2), ("gateway", 3), ("library", 4))]}), encoding="utf-8")
        env.update({"HOME": str(prefix), "USERPROFILE": str(prefix),
                    "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(prefix / "engines"),
                    "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(prefix / "agent.yaml"),
                    "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1"})
        log = (root / "agent.log").open("w", encoding="utf-8"); logs.append(log)
        agent = subprocess.Popen([str(python), str(HERE / "s8-ui-acceptance.py"), "--serve", str(prefix),
                                  "--port", str(agent_port)], cwd=prefix, env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=FLAGS)
        url = f"http://127.0.0.1:{agent_port}"
        with httpx.Client(trust_env=False, timeout=5) as client:
            for _ in range(300):
                try:
                    if client.get(url + "/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert agent.poll() is None, "agent exited"
                time.sleep(.2)
            # The root is spawned by the agent; wait for it to answer.
            for _ in range(300):
                try:
                    if client.get(control + "/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            assert control_state(client, control) is False, "root already initialized before setup"

            settings = root / "browser-settings.json"
            settings.write_text(json.dumps({"url": url, "output": str(root), "passphrase": PASSPHRASE,
                                            "control": control}), encoding="utf-8")
            with (root / "browser.log").open("w", encoding="utf-8") as blog:
                browser = subprocess.run(["node", str(HERE / "cx2-setup-resume-browser.mjs"), str(settings)],
                                         stdout=blog, stderr=blog, timeout=900)
            report = root / "browser.json"
            if report.exists():
                result["browser"] = json.loads(report.read_text(encoding="utf-8"))
            assert browser.returncode == 0, "browser failed; see browser.log and failure.png"

            # The browser read the root's own `/v1/auth/status` directly (not
            # through the UI) at each pause; then the end state, read here.
            seen = result["browser"]["controlInitialized"]
            result["checks"]["rootUninitializedAfterFailure"] = seen["afterFailure"] is False
            result["checks"]["rootUninitializedAfterWrongPassphrase"] = seen["afterWrongPassphrase"] is False
            result["checks"]["rootInitializedAtEnd"] = control_state(client, control)
            login = client.post(control + "/v1/auth/login", json={"passphrase": PASSPHRASE})
            result["checks"]["rootTakesThePassphrase"] = login.status_code == 200
            # Signed in at the agent, which forwards to the root once enrolled.
            agent_login = client.post(url + "/v1/auth/login", json={"passphrase": PASSPHRASE})
            token = agent_login.json().get("sessionToken") if agent_login.status_code == 200 else ""
            node = client.get(url + "/v1/node", headers={"Authorization": f"Bearer {token}"})
            result["checks"]["agentEnrolled"] = node.status_code == 200 and node.json().get("enrolled") is True
            result["checks"]["agentInitializedOnce"] = result["browser"]["agentInitializeCalls"] == 1
            result["checks"]["reachedHome"] = result["browser"].get("reachedHome") is True
            # CX2-C1: straight to setup, and the passphrase asked for once.
            result["checks"]["noSignInDetour"] = result["browser"].get("visitedLogin") is not True
            result["checks"]["askedOnce"] = result["browser"].get("askedAgain") is False
        result["passed"] = all(result["checks"].values()) and len(result["checks"]) == 9
    finally:
        try:
            if agent:
                (prefix / "stop").touch()
                agent.wait(timeout=45)
        finally:
            for log in logs:
                log.close()
            result["liveInstallUnchanged"] = snapshot_windows() == before
            (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert result["liveInstallUnchanged"], "live service/account environment changed"
    assert result["passed"], "a CX2 check failed; see result.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="A new disposable directory")
    run(parser.parse_args().output.resolve())
