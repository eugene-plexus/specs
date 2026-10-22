"""Serve the installed UI wheel through a disposable agent and run S8 browser checks.

Uses the active interpreter's agent and UI packages. No installed service or
operator config is changed. Output (including disposable session) stays in --output.
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


#: Ports the harness never picks: the defaults (8079-8083) and the live install's
#: (+200). OS-assigned ports are far above both; the check is belt and braces.
NEVER = set(range(8079, 8084)) | set(range(8279, 8284))

#: Set in the environment before the agent starts, so that a process the agent
#: replaces with itself (a restart from Settings) can say it was restarted.
RESTARTS = "S8_HARNESS_RESTARTS"


def free_port(*avoid: int) -> int:
    """A port the OS hands out, that is none of the ports a live install or a default uses."""
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in NEVER and port not in avoid:
            return port


def harness_settings(settings_class, root: Path, port: int, machine_port: int | None = None):
    """The agent's `Settings` as an install's variables make them, plus free ports.

    The machine port and the client doors are left for `build_server` to turn
    on, as an install gets them. `machine_port` is passed only to an agent that
    has the field: an older one refuses a field it does not know.
    """
    fields = {"config_file": root / "agent.yaml", "bind_port": port, "default_topology": False}
    if "machine_port" in settings_class.model_fields:
        fields["machine_port"] = machine_port or free_port(port)
    return settings_class(**fields)


def run_until_stop(server, stop) -> None:
    """For an agent without `serve(should_stop=)`: its own server, stopped by the file."""
    import threading

    done = threading.Event()

    def watch() -> None:
        while not done.wait(.1):
            if stop():
                server.should_exit = True
                return
    threading.Thread(target=watch, daemon=True).start()
    try:
        server.run()
    finally:
        done.set()


def serve(root: Path, port: int, machine_port: int | None = None) -> None:
    """Run the agent's own start path, so a check through this tests the product.

    Never builds an app or a server here: whatever the agent does at boot (the
    console log copy, the entry point, the machine port, the client doors, a
    restart from Settings) happens, because the agent does it. The `stop` file
    in `root` ends it.
    """
    import importlib
    import importlib.metadata

    agent = importlib.import_module("eugene_plexus_agent.__main__")
    from eugene_plexus_agent.settings import Settings

    try:
        version = importlib.metadata.version("eugene-plexus-agent")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    if not hasattr(agent, "build_server"):
        raise SystemExit(f"agent {version} predates build_server; v0.2.0 is the oldest supported.")
    restarts = int(os.environ.get(RESTARTS, "0"))
    if restarts:
        print("harness: agent restarted in place (entry point)", flush=True)
    os.environ[RESTARTS] = str(restarts + 1)

    settings = harness_settings(Settings, root, port, machine_port)
    stop = lambda: (root / "stop").exists()  # noqa: E731
    if hasattr(agent, "serve"):
        agent.serve(settings, unattended=True, should_stop=stop)
    else:
        print(f"harness: agent {version} has no serve(should_stop); running its build_server",
              flush=True)
        run_until_stop(agent.build_server(settings, unattended=True), stop)


def check(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "agent.yaml").write_text(yaml.safe_dump({
        "firstRunComplete": True, "updateChecks": False,
        "securityMode": "prompt_on_startup",
    }), encoding="utf-8")
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    with (root / "agent.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, __file__, "--serve", str(root), "--port", str(port)],
                                env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            url = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=url, trust_env=False, timeout=10) as client:
                for _ in range(200):
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    assert proc.poll() is None, "isolated agent exited"
                    time.sleep(.1)
                login = client.post("/v1/auth/initialize", json={"passphrase": "s8-disposable-passphrase"})
                login.raise_for_status()
                session = root / "session.json"
                session.write_text(json.dumps({"url": url, "token": login.json()["sessionToken"]}))
            subprocess.run(["node", str(Path(__file__).with_name("s8-browser-acceptance.mjs")),
                            str(session), str(root)], check=True)
        finally:
            (root / "stop").touch()
            proc.wait(timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--machine-port", type=int,
                        help="the machine port; for scripts that run two agents on one host "
                             "(default: a free one)")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port, args.machine_port)
    else:
        assert args.output, "--output must name a new disposable directory"
        check(args.output.resolve())
