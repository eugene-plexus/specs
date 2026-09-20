"""Exercise a real agent and installed llama-bench with disposable state, CPU only.

Requires --server (llama-server path) and --model (a small existing GGUF).
No installed agent, service, runtime, profile or model file is changed.
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
import tempfile
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


def main(args) -> None:
    server, model = args.server.resolve(), args.model.resolve()
    assert server.is_file() and model.is_file()
    with tempfile.TemporaryDirectory(prefix="ep-r6-http-") as directory:
        root = Path(directory)
        (root / "agent.yaml").write_text(yaml.safe_dump({
            "engineBinaryRoots": [str(server.parent)], "securityMode": "prompt_on_startup",
        }), encoding="utf-8")
        from eugene_plexus_agent.library_folders import LibraryFolderCache, FolderRecord, FOLDERS_FILE
        cache = LibraryFolderCache(root / FOLDERS_FILE)
        # The usual folder cache is seeded, so containment is exercised even
        # though this isolated agent has no running Library component.
        cache.update([FolderRecord(str(model.parent))], library_url="http://fixture.invalid")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env["PYTHONUNBUFFERED"] = "1"
        log = (root / "agent.log").open("w", encoding="utf-8")
        process = None
        def boot():
            (root / "stop").unlink(missing_ok=True)
            proc = subprocess.Popen([sys.executable, __file__, "--serve", str(root), "--port", str(port)],
                env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            for _ in range(150):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/healthz", trust_env=False).status_code == 200:
                        return proc
                except httpx.HTTPError:
                    pass
                if proc.poll() is not None:
                    raise AssertionError("agent exited during startup")
                time.sleep(.1)
            proc.kill(); proc.wait()
            raise AssertionError("agent did not start")
        try:
            process = boot()
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
                def check(response, code=200):
                    assert response.status_code == code, response.text
                    return response.json()
                login = check(client.post("/v1/auth/initialize", json={"passphrase": "r6-disposable-passphrase"}))
                client.headers["Authorization"] = f"Bearer {login['sessionToken']}"
                body = dict(modelId="cpu-acceptance", profileId="cpu-profile", profileName="CPU acceptance",
                    repetitions=2, tokens=16, runtime=dict(name="cpu-acceptance", engine="llama_cpp",
                    modelPath=str(model), binary=str(server), flags=dict(contextSize=256, gpuLayers=0, threads=2),
                    env={"CUDA_VISIBLE_DEVICES": "-1", "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1"}))
                first = check(client.post("/v1/benchmarks", json=body), 202)
                for _ in range(300):
                    jobs = check(client.get("/v1/benchmarks"))["benchmarks"]
                    result = next(j for j in jobs if j["id"] == first["id"])
                    if result["state"] != "running":
                        break
                    time.sleep(.1)
                assert result["state"] == "completed", result
                assert [p["depth"] for p in result["points"]] == [0, 120, 240]
                assert all(len(p["samples"]) == 2 for p in result["points"])
                print("PASS real HTTP depth sweep and individual samples", flush=True)
                if args.report:
                    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
                body["runtime"]["flags"]["contextSize"] = 8192
                body["tokens"], body["repetitions"] = 256, 5
                second = check(client.post("/v1/benchmarks", json=body), 202)
                assert client.post("/v1/runtimes", json=body["runtime"]).status_code == 409
                cancelled = check(client.post(f"/v1/benchmarks/{second['id']}/cancel"))
                assert cancelled["state"] == "cancelled"
                print("PASS active launch exclusion and cancellation", flush=True)
                (root / "stop").touch()
                process.wait(timeout=15)
                process = boot()
                login = check(client.post("/v1/auth/login", json={"passphrase": "r6-disposable-passphrase"}))
                client.headers["Authorization"] = f"Bearer {login['sessionToken']}"
                restored = check(client.get("/v1/benchmarks"))["benchmarks"]
                assert next(j for j in restored if j["id"] == first["id"])["points"] == result["points"]
                print("PASS history survives a real agent restart", flush=True)
        except BaseException:
            log.flush()
            print((root / "agent.log").read_text(encoding="utf-8", errors="replace")[-8000:])
            raise
        finally:
            (root / "stop").touch()
            if process and process.poll() is None:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--server", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        if not args.server or not args.model:
            parser.error("--server and --model are required")
        main(args)
