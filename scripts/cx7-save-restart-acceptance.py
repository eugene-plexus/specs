"""CX7: Save says it restarts, and Save all restarts a process once.

A fresh isolated install from this checkout's installer (the pinned UI
wheel), on claimed ports with every ambient `EUGENE_PLEXUS_*` variable
cleared, set up with no model and left with its gateway running. The browser
half (`cx7-save-restart-browser.mjs`) finds two gateway fields that carry
`requiresRestart: true` and that Settings files under two different topic
sections, edits both, and checks the wording before the click: each
section's button reads "Save and restart" with its `restart-note`, and the
save-all bar reads "Save all and restart" and names the gateway. It then
clicks Save all and checks that the gateway restarted exactly once, that
both new values are in effect with nothing pending a restart, and that the
page shows no "Restart needed" line, also after a reload. It then puts the
original values back the same way and checks the same again.

How "exactly once" is observed: from before the click until twenty seconds
after the gateway answers again, the browser half reads the agent's
`GET /v1/components` every 100 ms and records the gateway entry's `pid` and
`lastRestart` (the supervisor stamps `lastRestart` on every spawn). One
restart is one new (pid, lastRestart) pair. The limit: this is sampling. A
second restart is seen unless it begins and ends between two samples, which
a gateway start cannot do, and one that happens later than the settle
window is out of scope. The browser half reports the longest gap between
samples; if it exceeds 3 s, the count is recorded as null (not checked),
never as a pass.

Checked here over HTTP: the gateway's saved config, read through the agent's
proxy, holds the original values once the browser half is done, and no
field is pending a restart.

Not checked, and recorded as such in `result.json` under `notChecked`: that
the restart ends an answer an app is reading (no model is served here), and
which of the two saves a restart followed (only that one restart followed
both, since both values are in effect after it).

Shares its install steps with the CX2 harness. Windows only. Never run on
the default ports on Amish_Station: it claims its own.
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
PASSPHRASE = "cx7-disposable-passphrase"

_spec = importlib.util.spec_from_file_location("cx2", HERE / "cx2-setup-resume-acceptance.py")
assert _spec and _spec.loader
cx2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cx2)

CHECKS = (
    "twoFieldsInTwoSections",
    "sectionButtonSaysSaveAndRestart",
    "sectionNoteShown",
    "saveAllBarSaysSaveAllAndRestart",
    "saveAllNamesGateway",
    "saveAllRestartedOnce",
    "newValuesInEffect",
    "noRestartNeededLine",
    "restoreRestartedOnce",
    "originalsRestoredInBrowser",
    "originalsRestoredInRegistry",
)


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
    result: dict = {"ports": {"agent": agent_port}, "checks": {}, "notChecked": [
        "that the restart ends an answer an app is reading (no model is served)",
        "which save a restart followed; only that one restart followed both saves",
    ]}
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
        log = (root / "agent.log").open("w", encoding="utf-8")
        logs.append(log)
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
                browser = subprocess.run(["node", str(HERE / "cx7-save-restart-browser.mjs"), str(settings)],
                                         stdout=blog, stderr=blog, timeout=1800)
            report = root / "browser.json"
            if report.exists():
                result["browser"] = json.loads(report.read_text(encoding="utf-8"))
            assert browser.returncode == 0, "browser failed; see browser.log and failure.png"
            seen = result["browser"]
            changed = seen.get("change") or {}
            restored = seen.get("restore") or {}
            checks = result["checks"]
            checks["twoFieldsInTwoSections"] = seen.get("twoFieldsInTwoSections") is True
            checks["sectionButtonSaysSaveAndRestart"] = changed.get("sectionButton") == "Save and restart"
            checks["sectionNoteShown"] = changed.get("sectionNoteShown") is True
            checks["saveAllBarSaysSaveAllAndRestart"] = changed.get("saveAllButton") == "Save all and restart"
            checks["saveAllNamesGateway"] = changed.get("saveAllNamesGateway") is True
            # `None` (sampling gaps) is not a pass.
            checks["saveAllRestartedOnce"] = changed.get("restartedOnce") is True
            checks["newValuesInEffect"] = changed.get("valuesInEffect") is True
            checks["noRestartNeededLine"] = (
                changed.get("noRestartNeededLine") is True and changed.get("nothingPending") is True
            )
            checks["restoreRestartedOnce"] = restored.get("restartedOnce") is True
            checks["originalsRestoredInBrowser"] = restored.get("valuesInEffect") is True
            # The registry itself, through the agent's proxy, once the browser is done.
            login = client.post(url + "/v1/auth/login", json={"passphrase": PASSPHRASE})
            token = login.json().get("sessionToken", "") if login.status_code == 200 else ""
            auth = {"Authorization": f"Bearer {token}"}
            doc = client.get(url + "/api/proxy/gateway/v1/config", headers=auth)
            schema = client.get(url + "/api/proxy/gateway/v1/config/schema", headers=auth)
            originals = seen.get("originals") or {}
            same = doc.status_code == 200 and bool(originals) and all(
                str(doc.json().get(k)) == str(v) for k, v in originals.items()
            )
            pending = schema.status_code != 200 or any(
                f.get("pendingRestart") for f in schema.json().get("fields", [])
            )
            result["finalGatewayValues"] = {k: doc.json().get(k) for k in originals} if doc.status_code == 200 else None
            checks["originalsRestoredInRegistry"] = same and not pending
        result["passed"] = all(result["checks"].values()) and set(result["checks"]) == set(CHECKS)
    finally:
        try:
            if agent:
                (prefix / "stop").touch()
                try:
                    agent.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    # Its shutdown can wait on an open connection for ever
                    # (agent#20); a disposable install's whole tree goes.
                    print("the agent did not stop in 45 s; killing its process tree", flush=True)
                    subprocess.run(["taskkill", "/PID", str(agent.pid), "/T", "/F"],
                                   capture_output=True, check=False)
        finally:
            for log in logs:
                log.close()
            result["liveInstallUnchanged"] = cx2.snapshot_windows() == before
            (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert result["liveInstallUnchanged"], "live service/account environment changed"
    assert result["passed"], "a CX7 check failed; see result.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="A new disposable directory")
    run(parser.parse_args().output.resolve())
