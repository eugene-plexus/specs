"""CX4: one context for fit, on a real disposable install.

The same disposable install as CX3 (`cx3-ask-first-acceptance.py`: this
checkout's installer, the pinned UI wheel, claimed ports, ambient
`EUGENE_PLEXUS_*` cleared, its own engine folder). Then:

1. Over HTTP: the library's "Context to plan for" defaults to 16,384, and
   after a PATCH to 32,768 a fit asked without a context is judged at
   32,768, and so is the starter set.
2. The browser half (`cx4-planned-context-browser.mjs`) sets up the install,
   PATCHes the setting, and reads Home's note and Discover's control (and
   that a try there is not kept), each at 32k. The Library's fit is read
   over HTTP: judged at 32k.
3. A run of `Qwen/Qwen2.5-0.5B-Instruct-GGUF` (Q4_K_M, about 400 MB, 32k
   trained context) with the install agreed at the click reaches `ready`,
   and the runtime reports the context it serves: at least the planned
   32k, capped at the model's own.

Not covered (no card here is small enough): a model that fits wholly only
below the planned context, started at the planned one with layers in
system memory. That case is the agent's unit test
(`test_llama_cpp_never_starts_below_the_planned_context`).

Requires httpx and PyYAML, Node and Chrome, the sibling UI's Node
dependencies, and the internet. Windows only.
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
PASSPHRASE = "cx4-disposable-passphrase"
PLANNED = 32768
QWEN = {"repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF", "files": ["qwen2.5-0.5b-instruct-q4_k_m.gguf"]}


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cx2 = _load("cx2", "cx2-setup-resume-acceptance.py")
cx3 = _load("cx3", "cx3-ask-first-acceptance.py")


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
        with httpx.Client(trust_env=False, timeout=60) as client:
            cx3.wait_for(client, url, agent)
            cx3.wait_for(client, f"http://127.0.0.1:{base + 2}")
            settings = root / "browser-settings.json"
            settings.write_text(
                json.dumps(
                    {"url": url, "output": str(root), "passphrase": PASSPHRASE,
                     "planned": PLANNED}
                ),
                encoding="utf-8",
            )
            with (root / "browser.log").open("w", encoding="utf-8") as blog:
                browser = subprocess.run(
                    ["node", str(HERE / "cx4-planned-context-browser.mjs"), str(settings)],
                    stdout=blog, stderr=blog, timeout=1800,
                )
            report = root / "browser.json"
            if report.exists():
                result["browser"] = json.loads(report.read_text(encoding="utf-8"))
            assert browser.returncode == 0, "browser failed; see browser.log and failure.png"
            seen = result["browser"]
            result["checks"]["defaultIs16k"] = seen.get("defaultPlanned") == 16384
            result["checks"]["homeSaysPlanned"] = "32k" in (seen.get("homeNote") or "")
            result["checks"]["discoverStartsAtPlanned"] = seen.get("discoverContext") == str(PLANNED)
            result["checks"]["discoverTryNotKept"] = seen.get("discoverAfterReload") == str(PLANNED)

            token = client.post(url + "/v1/auth/login", json={"passphrase": PASSPHRASE}).json()[
                "sessionToken"
            ]
            auth = {"Authorization": f"Bearer {token}"}
            library = url + "/api/proxy/library"
            starter = client.get(library + "/v1/catalogue/starter", headers=auth).json()
            judged = {
                (m.get("fit") or {}).get("contextLength") for m in starter.get("models", [])
            } - {None}
            result["checks"]["starterJudgedAtPlanned"] = judged == {PLANNED}

            node = client.get(url + "/v1/node", headers=auth).json().get("name")
            run_id = f"dl_cx4-{uuid.uuid4().hex[:8]}"
            intent = {"node": node, "download": QWEN, "installEngine": "llama_cpp"}
            submitted = client.put(f"{library}/v1/run-operations/{run_id}", json=intent, headers=auth)
            assert submitted.status_code == 202, submitted.text
            record: dict = {}
            deadline = time.perf_counter() + 1800
            while time.perf_counter() < deadline:
                record = client.get(f"{library}/v1/run-operations/{run_id}", headers=auth).json()
                if record["step"] in {"ready", "failed", "cancelled", "skipped"}:
                    break
                time.sleep(1)
            result["run"] = {k: record.get(k) for k in ("step", "runtime", "error")}
            model_id = (record.get("model") or {}).get("id")
            fit = client.get(f"{library}/v1/models/{model_id}/fit", headers=auth).json()
            result["checks"]["libraryFitJudgedAtPlanned"] = (
                (fit.get("fit") or {}).get("contextLength") == PLANNED
            )
            served = None
            if record.get("runtime"):
                runtime = client.get(f"{url}/v1/runtimes/{record['runtime']}", headers=auth).json()
                served = (runtime.get("capabilities") or {}).get("contextLength")
            own = (record.get("model") or {}).get("contextLength") or PLANNED
            result["served"] = served
            result["checks"]["servesAtLeastPlanned"] = (
                record.get("step") == "ready"
                and isinstance(served, int)
                and served >= min(PLANNED, own)
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
    assert result["passed"], "a CX4 check failed; see result.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="A new disposable directory")
    run(parser.parse_args().output.resolve())
