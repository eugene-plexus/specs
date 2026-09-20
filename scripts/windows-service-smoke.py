"""Opt-in Windows CI service smoke test; never run against an installed node.

Creates a uniquely named service and disposable venv/config. Requires an
already elevated process; never requests UAC. Starts no components or engines.
"""

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
import winreg

import httpx
import win32service
import win32serviceutil
import win32evtlog


def main():
    if (
        os.environ.get("EP_SERVICE_SMOKE") != "1"
        or not ctypes.windll.shell32.IsUserAnAdmin()
    ):
        raise SystemExit("Set EP_SERVICE_SMOKE=1 on an elevated disposable CI runner")
    name = "EPServiceSmoke" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="ep-service-smoke-") as temp:
        root = Path(temp)
        venv = root / "venv"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "venv",
                "--system-site-packages",
                "--without-pip",
                str(venv),
            ],
            check=True,
        )
        python = venv / "Scripts/python.exe"
        subprocess.run(
            [
                str(python),
                "-c",
                "from eugene_plexus_agent.winservice import _prepare_service_host; _prepare_service_host()",
            ],
            check=True,
        )
        config = root / "agent.yaml"
        config.write_text("{}\n", encoding="utf-8")
        port = 18779
        installed = False
        try:
            win32serviceutil.InstallService(
                "eugene_plexus_agent.winservice.EugenePlexusAgentService",
                name,
                name,
                exeName=str(venv / "Scripts/pythonservice.exe"),
            )
            installed = True
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SYSTEM\CurrentControlSet\Services\{name}",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    "Environment",
                    0,
                    winreg.REG_MULTI_SZ,
                    [
                        f"EUGENE_PLEXUS_AGENT_CONFIG_FILE={config}",
                        "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=false",
                        f"EUGENE_PLEXUS_AGENT_BIND_PORT={port}",
                        "EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1",
                        f"PATH={os.environ['SYSTEMROOT']}\\System32",
                    ],
                )
            win32serviceutil.StartService(name)
            with httpx.Client(trust_env=False, timeout=2) as client:
                deadline = time.perf_counter() + 45
                while time.perf_counter() < deadline:
                    try:
                        response = client.get(f"http://127.0.0.1:{port}/healthz")
                        if response.status_code == 200:
                            print(
                                "PASS: LocalSystem service starts from an isolated venv without Python on PATH"
                            )
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.3)
                else:
                    raise AssertionError("service did not answer health check")
            win32serviceutil.StopService(name)
            win32serviceutil.WaitForServiceStatus(
                name, win32service.SERVICE_STOPPED, 45
            )
            print("PASS: service stops cleanly through SCM")
        except BaseException:
            print("SCM status:", win32serviceutil.QueryServiceStatus(name), flush=True)
            for channel in ("Application", "System"):
                handle = win32evtlog.OpenEventLog(None, channel)
                try:
                    events = win32evtlog.ReadEventLog(
                        handle,
                        win32evtlog.EVENTLOG_BACKWARDS_READ
                        | win32evtlog.EVENTLOG_SEQUENTIAL_READ,
                        0,
                    )
                    for event in events[:60]:
                        if event.SourceName in (
                            "Python Service",
                            "EugenePlexusAgent",
                            "Service Control Manager",
                        ):
                            print(
                                channel,
                                event.TimeGenerated,
                                event.EventID,
                                event.StringInserts,
                                flush=True,
                            )
                finally:
                    win32evtlog.CloseEventLog(handle)
            for log in root.rglob("*.log"):
                print(
                    log.name,
                    "\n".join(log.read_text(errors="replace").splitlines()[-35:]),
                )
            raise
        finally:
            if installed:
                try:
                    if (
                        win32serviceutil.QueryServiceStatus(name)[1]
                        != win32service.SERVICE_STOPPED
                    ):
                        win32serviceutil.StopService(name)
                        win32serviceutil.WaitForServiceStatus(
                            name, win32service.SERVICE_STOPPED, 45
                        )
                finally:
                    win32serviceutil.RemoveService(name)
    print(json.dumps({"service": name, "removed": True}))


if __name__ == "__main__":
    main()
