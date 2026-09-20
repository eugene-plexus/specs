"""Serve the installed UI wheel through a disposable agent and run S8 browser checks.

Uses the active interpreter's agent and UI packages. No installed service or
operator config is changed. Output (including disposable session) stays in --output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import yaml


def serve(root: Path, port: int) -> None:
    import uvicorn
    from eugene_plexus_agent.app import create_app
    from eugene_plexus_agent.settings import Settings

    app = create_app(settings=Settings(config_file=root / "agent.yaml", bind_port=port,
                                      default_topology=False))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (root / "stop").exists():
            await asyncio.sleep(.1)
        server.should_exit = True
        await task
    asyncio.run(run())


def check(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "agent.yaml").write_text(yaml.safe_dump({
        "firstRunComplete": True, "securityMode": "prompt_on_startup",
    }), encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    with (root / "agent.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, __file__, "--serve", str(root), "--port", str(port)],
                                env=env, stdout=log, stderr=log,
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
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        assert args.output, "--output must name a new disposable directory"
        check(args.output.resolve())
