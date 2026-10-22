"""CX3: one-click run asks first, on a real disposable install.

A fresh isolated install from this checkout's installer (the pinned UI
wheel), on a claimed port range away from the live worker, every ambient
`EUGENE_PLEXUS_*` variable cleared, and its own engine folder, so llama.cpp
starts out not installed. The browser half (`cx3-ask-first-browser.mjs`)
sets up the install, then:

1. presses Home's "Download and run" and sees "Install llama.cpp too?"
   before any run operation is submitted; Escape submits nothing;
2. on a run left waiting at `awaiting-install` (submitted here without the
   agreement), Escape and Later close the dialog and the run keeps waiting;
   its tray row opens the question again; Cancel the run cancels it.

Then, over HTTP: a download-and-run of a tiny GGUF with `installEngine`
set installs llama.cpp and reaches `ready` with no answer posted, and is
never seen at `awaiting-install`.

Downloads `ggml-org/models` `tinyllamas/stories15M-q4_0.gguf` (about 20 MB)
and one llama.cpp build into the disposable folder. Requires httpx and
PyYAML, Node and Chrome, the sibling UI's Node dependencies, and the
internet. Windows only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PASSPHRASE = "cx3-disposable-passphrase"
TINY = {"repo": "ggml-org/models", "files": ["tinyllamas/stories15M-q4_0.gguf"]}

_spec = importlib.util.spec_from_file_location("cx2", HERE / "cx2-setup-resume-acceptance.py")
assert _spec and _spec.loader
cx2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cx2)


def wait_for(client: httpx.Client, url: str, agent: subprocess.Popen | None = None) -> None:
    for _ in range(300):
        try:
            if client.get(url + "/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        assert agent is None or agent.poll() is None, "agent exited"
        time.sleep(0.2)
    raise AssertionError(f"{url} did not answer")


def run(root: Path) -> None:
    assert sys.platform == "win32", "Windows only"
    root.mkdir(parents=True, exist_ok=False)
    prefix = root / "install"
    before = cx2.snapshot_windows()
    base = cx2.claim_ports()
    agent_port = base + 1
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update(
        {
            "NO_PROXY": "localhost,127.0.0.1,::1",
            "PYTHONUTF8": "1",
            "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port),
        }
    )
    result: dict = {"ports": {"agent": agent_port}, "checks": {}}
    agent = None
    logs = []
    try:
        wrapper = root / "install-wrapper.ps1"
        wrapper.write_text(
            "& '"
            + str(HERE / "install.ps1").replace("'", "''")
            + "' -Prefix '"
            + str(prefix).replace("'", "''")
            + "' -NoService -NoStart -Isolated\n",
            encoding="utf-8",
        )
        with (root / "installer.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                env=env, cwd=root, stdout=log, stderr=log, check=True, timeout=900,
            )
        python = prefix / "venv/Scripts/python.exe"
        (prefix / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "components": [
                        {
                            "name": name,
                            "kind": name,
                            "url": f"http://127.0.0.1:{base + offset}",
                            "spawn": {"configFile": str(prefix / f"{name}.yaml")},
                        }
                        for name, offset in (("control", 2), ("gateway", 3), ("library", 4))
                    ]
                }
            ),
            encoding="utf-8",
        )
        env.update(
            {
                "HOME": str(prefix),
                "USERPROFILE": str(prefix),
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(prefix / "engines"),
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(prefix / "agent.yaml"),
                "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
                # The machine port is off until agent#27 is fixed: with it on, the wizard joins the root at
                # control's moved URL, which is plain HTTP, and the join token expects TLS.
                "EUGENE_PLEXUS_AGENT_MACHINE_PORT_ENABLED": "0",
            }
        )
        log = (root / "agent.log").open("w", encoding="utf-8")
        logs.append(log)
        agent = subprocess.Popen(
            [str(python), str(HERE / "s8-ui-acceptance.py"), "--serve", str(prefix),
             "--port", str(agent_port)],
            cwd=prefix, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=FLAGS,
        )
        url = f"http://127.0.0.1:{agent_port}"
        with httpx.Client(trust_env=False, timeout=30) as client:
            wait_for(client, url, agent)
            wait_for(client, f"http://127.0.0.1:{base + 2}")
            settings = root / "browser-settings.json"
            waiting = f"cx3-waiting-{uuid.uuid4().hex[:8]}"
            settings.write_text(
                json.dumps(
                    {"url": url, "output": str(root), "passphrase": PASSPHRASE,
                     "waiting": waiting, "tiny": TINY}
                ),
                encoding="utf-8",
            )
            with (root / "browser.log").open("w", encoding="utf-8") as blog:
                browser = subprocess.run(
                    ["node", str(HERE / "cx3-ask-first-browser.mjs"), str(settings)],
                    stdout=blog, stderr=blog, timeout=1800,
                )
            report = root / "browser.json"
            if report.exists():
                result["browser"] = json.loads(report.read_text(encoding="utf-8"))
            assert browser.returncode == 0, "browser failed; see browser.log and failure.png"
            seen = result["browser"]
            result["checks"]["askedAtTheClick"] = seen.get("askedAtTheClick") is True
            result["checks"]["escapeSubmittedNothing"] = seen.get("submitsAfterEscape") == 0
            result["checks"]["laterKeptTheRunWaiting"] = seen.get("stepAfterLater") == "awaiting-install"
            result["checks"]["trayReopenedTheQuestion"] = seen.get("trayReopened") is True
            result["checks"]["cancelTheRunCancelled"] = seen.get("stepAfterCancel") == "cancelled"

            # The chain itself, with the agreement recorded at the click.
            token = client.post(url + "/v1/auth/login", json={"passphrase": PASSPHRASE}).json()[
                "sessionToken"
            ]
            auth = {"Authorization": f"Bearer {token}"}
            node = client.get(url + "/v1/node", headers=auth).json().get("name")
            library = url + "/api/proxy/library/v1/run-operations/"
            run_id = f"dl_cx3-{uuid.uuid4().hex[:8]}"
            intent = {"node": node, "download": TINY, "installEngine": "llama_cpp"}
            submitted = client.put(library + run_id, json=intent, headers=auth)
            assert submitted.status_code == 202, submitted.text
            steps: list[str] = []
            deadline = time.perf_counter() + 1800
            record: dict = {}
            while time.perf_counter() < deadline:
                record = client.get(library + run_id, headers=auth).json()
                if not steps or steps[-1] != record["step"]:
                    steps.append(record["step"])
                if record["step"] in {"ready", "failed", "cancelled", "skipped"}:
                    break
                time.sleep(0.5)
            result["steps"] = steps
            result["final"] = {k: record.get(k) for k in ("step", "answer", "engine", "error")}
            result["checks"]["readyWithNoQuestion"] = (
                record.get("step") == "ready" and "awaiting-install" not in steps
            )
            result["checks"]["installedOnTheAgreement"] = (
                "installing" in steps and record.get("answer") == "install"
            )
        result["passed"] = all(result["checks"].values()) and len(result["checks"]) == 7
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
    assert result["passed"], "a CX3 check failed; see result.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="A new disposable directory")
    run(parser.parse_args().output.resolve())
