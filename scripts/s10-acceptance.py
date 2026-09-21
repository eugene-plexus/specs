"""Install-to-first-token instrument for Windows and WSL, with real downloads.

Requires httpx and PyYAML in the driving interpreter, Node/Chrome on Windows,
and the sibling UI's Node dependencies. Run inside the target OS. WSL uses the
Windows browser over localhost forwarding, as the original S10 instrument did.

This is a CPU workload fixture, not a GPU hardware certification. Its only
runtime seams are hiding accelerators and relocating the runtime port range;
the 8B row is copied unchanged from the installed starter set. Downloads,
engine acquisition, launch, auth, UI, routing and replies are the real product.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import httpx
import yaml

HERE = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def windows_path(path: Path) -> str:
    if WINDOWS:
        return str(path)
    return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()


def snapshot_windows() -> dict:
    if not WINDOWS:
        return {}
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


def run(root: Path, download: bool, seed: Path | None, installer_source: Path | None = None) -> None:
    installer_source = installer_source or HERE / ("install.ps1" if WINDOWS else "install.sh")
    assert installer_source.is_file(), "installer source does not exist"
    root.mkdir(parents=True, exist_ok=False)
    prefix = root / "install"
    before = snapshot_windows()
    # Claim a complete contiguous range before starting anything. This avoids
    # the live worker's companion ports (8090 onward) as well as its UI port.
    held = []
    for base in range(19000 if WINDOWS else 23000, 29000, 100):
        try:
            for port in range(base, base + 24):
                sock = socket.socket()
                held.append(sock)
                sock.bind(("127.0.0.1", port))
            break
        except OSError:
            for sock in held:
                sock.close()
            held = []
    assert held, "no free test port range"
    proxy_port, agent_port = base, base + 1
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update({"HTTP_PROXY": f"http://127.0.0.1:{proxy_port}", "HTTPS_PROXY": f"http://127.0.0.1:{proxy_port}",
                "NO_PROXY": "localhost,127.0.0.1,::1", "UV_NO_CACHE": "1",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port), "PYTHONUTF8": "1"})
    proxy = agent = None
    logs = []
    result = {"target": "windows" if WINDOWS else "wsl", "download": download,
              "networkCapMbps": 100, "fixture": "CPU only; shipped 8B starter row; isolated ports"}
    for sock in held:
        sock.close()
    try:
        log = (root / "proxy.log").open("w", encoding="utf-8"); logs.append(log)
        proxy = subprocess.Popen([sys.executable, str(HERE / "s10-network.py"), "--port", str(proxy_port),
                                  "--output", str(root)], stdout=log, stderr=log, creationflags=FLAGS)
        for _ in range(100):
            if (root / "proxy-ready").exists():
                break
            assert proxy.poll() is None
            time.sleep(.1)
        assert (root / "proxy-ready").exists()
        if WINDOWS:
            def ps(value):
                return "'" + str(value).replace("'", "''") + "'"
            # WinPS 5.1's web cmdlets use .NET's proxy, while uv/httpx use env.
            wrapper = root / "install-wrapper.ps1"
            wrapper.write_text("[Net.WebRequest]::DefaultWebProxy = New-Object Net.WebProxy(" +
                               ps(env["HTTPS_PROXY"]) + ")\n& " + ps(installer_source) +
                               " -Prefix " + ps(prefix) + " -NoService -NoStart -Isolated\n", encoding="utf-8")
            command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)]
        else:
            # A Windows checkout can have CRLF; GitHub's raw installer is LF.
            installer = root / "install-source.sh"
            installer.write_text(installer_source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            command = ["sh", str(installer), "--prefix", str(prefix), "--no-service", "--no-start"]
        started = time.monotonic()
        result["startedEpochMs"] = time.time_ns() // 1_000_000
        with (root / "installer.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, env=env, cwd=root, stdout=log, stderr=log, check=True, timeout=600)
        result["installSeconds"] = time.monotonic() - started
        python = prefix / ("venv/Scripts/python.exe" if WINDOWS else "venv/bin/python")
        # Take the precise shipped 8B workload without silently testing a 4B or
        # 27B recommendation. It is an explicit workload condition in the record.
        data = subprocess.check_output([str(python), "-c",
            "from eugene_plexus_library.starter import PACKAGED_FILE; print(PACKAGED_FILE.read_text())"], env=env)
        starters = yaml.safe_load(data)
        starters["classes"] = [row for row in starters["classes"] if row["class"] == "8B"]
        assert len(starters["classes"]) == 1
        result["workload"] = starters["classes"][0]
        (prefix / "starter-8b.yaml").write_text(yaml.safe_dump(starters), encoding="utf-8")
        (prefix / "library.yaml").write_text(yaml.safe_dump({"starterModelsFile": str(prefix / "starter-8b.yaml")}), encoding="utf-8")
        # Only ports differ from first-boot defaults. Wizard/auth state stays fresh.
        (prefix / "agent.yaml").write_text(yaml.safe_dump({"components": [
            {"name": name, "kind": name, "url": f"http://127.0.0.1:{base + offset}",
             "spawn": {"configFile": str(prefix / f"{name}.yaml")}}
            for name, offset in (("control", 2), ("gateway", 3), ("library", 4))]}), encoding="utf-8")
        fixture = root / "fixture"; fixture.mkdir()
        (fixture / "sitecustomize.py").write_text('''
from eugene_plexus_agent.engines import host, devices
from eugene_plexus_agent import state
from eugene_plexus_library import hardware
host._detect_accelerator = lambda *args: (host.Accelerator.none, None)
_detect = devices.detect_devices
devices.detect_devices = lambda **kw: _detect(run=lambda argv: None)
hardware._nvidia_gpus = lambda warnings: []
hardware._amd_gpus = lambda warnings: []
hardware._intel_gpus = lambda warnings: []
''' + f"state._RUNTIME_PORT_BASE = {base + 10}\nstate._RUNTIME_PORT_SPAN = 10\n", encoding="utf-8")
        env.update({"HOME": str(prefix), "USERPROFILE": str(prefix), "PYTHONPATH": str(fixture),
                    "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(prefix / "engines"),
                    "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(prefix / "agent.yaml"),
                    "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1", "CUDA_VISIBLE_DEVICES": "-1"})
        if not download:
            assert seed and seed.is_file(), "seeded mode requires --model"
            models = prefix / "Eugene Models"; models.mkdir()
            shutil.copyfile(seed, models / seed.name)
        log = (root / "agent.log").open("w", encoding="utf-8"); logs.append(log)
        agent = subprocess.Popen([str(python), str(HERE / "s8-ui-acceptance.py"), "--serve", str(prefix),
                                  "--port", str(agent_port)], cwd=prefix, env=env,
                                 stdout=log, stderr=log, creationflags=FLAGS)
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
        settings = root / "browser-settings.json"
        settings.write_text(json.dumps({**result, "url": url, "output": windows_path(root)}), encoding="utf-8")
        node = "node" if WINDOWS else "/mnt/c/Program Files/nodejs/node.exe"
        with (root / "browser.log").open("w", encoding="utf-8") as log:
            browser = subprocess.run([node, windows_path(HERE / "s10-browser-acceptance.mjs"), windows_path(settings)],
                                     stdout=log, stderr=log, timeout=1500)
        report_path = root / "browser.json"
        if report_path.exists():
            result["browser"] = json.loads(report_path.read_text(encoding="utf-8"))
        assert browser.returncode == 0, "browser failed; see browser.log and failure.png"
        connection = json.loads((root / "connection.json").read_text(encoding="utf-8"))
        # Plain curl using exactly Home's three strings, no session token/proxy.
        body = root / "curl-request.json"
        body.write_text(json.dumps({"model": connection["model"], "messages": [{"role": "user", "content": "Say hello in five words. /no_think"}], "max_tokens": 1024}), encoding="utf-8")
        curl = subprocess.run(["curl.exe" if WINDOWS else "curl", "--noproxy", "*", "--silent", "--show-error", "--fail-with-body", "--max-time", "180",
                               connection["address"] + "/chat/completions", "-H", "Content-Type: application/json",
                               "-H", "Authorization: Bearer " + connection["key"], "--data-binary", "@" + str(body)],
                              capture_output=True, text=True, encoding="utf-8", check=True)
        completion = json.loads(curl.stdout)
        result["curlAnswer"] = completion["choices"][0]["message"]["content"]
        assert result["curlAnswer"].strip()
        if download:
            result["withinTenMinutes"] = result["browser"]["firstReply"]["installToFirstTokenSeconds"] < 600
        result["passed"] = not download or result["withinTenMinutes"]
    finally:
        try:
            if agent:
                (prefix / "stop").touch()
                agent.wait(timeout=45)
        finally:
            try:
                if proxy:
                    (root / "stop-proxy").touch()
                    proxy.wait(timeout=10)
            finally:
                for log in logs:
                    log.close()
                # No Windows service/registry snapshot exists on the WSL path.
                result["liveInstallUnchanged"] = snapshot_windows() == before if WINDOWS else None
                (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                assert result["liveInstallUnchanged"] is not False, "live service/account environment changed"
    print(json.dumps({k: result[k] for k in ("target", "installSeconds", "passed", "liveInstallUnchanged")}))
    assert result["passed"], "install-to-first-token exceeded 600 seconds; keep the failed measurement"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--installer", type=Path, help="Downloaded release installer to exercise instead of the checkout")
    args = parser.parse_args()
    run(args.output.resolve(), args.download, args.model, args.installer)
