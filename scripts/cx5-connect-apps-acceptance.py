"""CX5: Connect apps renders and manages keys with no model served.

A fresh isolated install from this checkout's installer (the pinned UI
wheel), on claimed ports with every ambient `EUGENE_PLEXUS_*` variable
cleared, set up with no model. The browser half
(`cx5-connect-apps-browser.mjs`) checks Home's line, the page with nothing
served, a key made and turned off, and the old `/#use-from-apps` anchor.
Checked here over HTTP: the key the browser made exists and is revoked.

Shares its install steps with the CX2 harness. Windows only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import yaml

HERE = Path(__file__).resolve().parent
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PASSPHRASE = "cx5-disposable-passphrase"

_spec = importlib.util.spec_from_file_location("cx2", HERE / "cx2-setup-resume-acceptance.py")
assert _spec and _spec.loader
cx2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cx2)


def run(root: Path) -> None:
    assert sys.platform == "win32", "Windows only"
    root.mkdir(parents=True, exist_ok=False)
    prefix = root / "install"
    before = cx2.snapshot_windows()
    base = cx2.claim_ports()
    agent_port = base + 1
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update({"NO_PROXY": "localhost,127.0.0.1,::1", "PYTHONUTF8": "1",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port)})
    result: dict = {"ports": {"agent": agent_port}, "checks": {}}
    agent = None
    logs = []
    try:
        wrapper = root / "install-wrapper.ps1"
        wrapper.write_text("& '" + str(HERE / "install.ps1").replace("'", "''") + "' -Prefix '" +
                           str(prefix).replace("'", "''") + "' -NoService -NoStart -Isolated\n",
                           encoding="utf-8")
        with (root / "installer.log").open("w", encoding="utf-8") as log:
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                           env=env, cwd=root, stdout=log, stderr=log, check=True, timeout=900)
        python = prefix / "venv/Scripts/python.exe"
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
        with httpx.Client(trust_env=False, timeout=10) as client:
            for _ in range(300):
                try:
                    if client.get(url + "/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert agent.poll() is None, "agent exited"
                time.sleep(.2)
            settings = root / "browser-settings.json"
            settings.write_text(json.dumps({"url": url, "output": str(root), "passphrase": PASSPHRASE}),
                                encoding="utf-8")
            with (root / "browser.log").open("w", encoding="utf-8") as blog:
                browser = subprocess.run(["node", str(HERE / "cx5-connect-apps-browser.mjs"), str(settings)],
                                         stdout=blog, stderr=blog, timeout=900)
            report = root / "browser.json"
            if report.exists():
                result["browser"] = json.loads(report.read_text(encoding="utf-8"))
            assert browser.returncode == 0, "browser failed; see browser.log and failure.png"
            seen = result["browser"]
            result["checks"]["homeLineWithNoModel"] = bool(seen.get("homeLine"))
            result["checks"]["addressShown"] = str(seen.get("address", "")).endswith("/v1")
            result["checks"]["keyMadeAndTurnedOff"] = seen.get("keyMade") is True and seen.get("keyTurnedOff") is True
            result["checks"]["oldAnchorRedirects"] = seen.get("oldAnchorRedirects") is True
            # The key the browser made, from the registry itself.
            login = client.post(url + "/v1/auth/login", json={"passphrase": PASSPHRASE})
            token = login.json().get("sessionToken", "") if login.status_code == 200 else ""
            keys = client.get(url + "/v1/auth/client-keys", headers={"Authorization": f"Bearer {token}"})
            made = [k for k in keys.json().get("keys", []) if k.get("name") == "CX5 acceptance key"]
            # Listed as revoked, or no longer listed; the browser saw it made.
            result["checks"]["keyRevokedInRegistry"] = keys.status_code == 200 and all(
                k.get("revokedAt") for k in made
            )
        result["passed"] = all(result["checks"].values()) and len(result["checks"]) == 5
    finally:
        try:
            if agent:
                (prefix / "stop").touch()
                try:
                    agent.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    # A stop takes at most 5 s plus the children's own stops since
                    # agent#20 (a connection Windows reset kept uvicorn waiting for
                    # ever). Past 45 s that fix has failed: say so, and the tree goes.
                    print("the agent did not stop in 45 s (agent#20 again?); killing its process tree",
                          flush=True)
                    subprocess.run(["taskkill", "/PID", str(agent.pid), "/T", "/F"],
                                   capture_output=True, check=False)
        finally:
            for log in logs:
                log.close()
            result["liveInstallUnchanged"] = cx2.snapshot_windows() == before
            (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert result["liveInstallUnchanged"], "live service/account environment changed"
    assert result["passed"], "a CX5 check failed; see result.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="A new disposable directory")
    run(parser.parse_args().output.resolve())
