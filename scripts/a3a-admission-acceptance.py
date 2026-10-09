"""A3a acceptance: admission asks the real llama-server whether it places models itself.

A disposable agent (own port, own folder, ambient EUGENE_PLEXUS_* dropped)
answers admission dry runs against this machine's REAL devices and a REAL
llama-server build, for a model larger than the free graphics memory. It
launches nothing. docs/design/moe-aware-fit.md call A:

* unset gpuLayers on a build whose help lists --fit  -> `split`, admitted
* the same with `--fit off` in extraArgs             -> refused
* an explicit gpuLayers: 99                           -> refused
* a model larger than the card and RAM together        -> refused

    python a3a-admission-acceptance.py --server DIR/llama-server(.exe) --model BIG.gguf
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml


def serve(root: Path, port: int) -> None:
    import uvicorn
    from eugene_plexus_agent.app import create_app
    from eugene_plexus_agent.settings import Settings

    app = create_app(
        settings=Settings(config_file=root / "agent.yaml", bind_port=port, default_topology=False)
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (root / "stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task

    asyncio.run(run())


def main(args: argparse.Namespace) -> None:
    server, model = args.server.resolve(), args.model.resolve()
    with tempfile.TemporaryDirectory(prefix="ep-a3a-") as directory:
        root = Path(directory)
        (root / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "engineBinaryRoots": [str(server.parent)],
                    "updateChecks": False,
                    "securityMode": "prompt_on_startup",
                    # `--fit off` is a raw extraArg, which is an expert setting.
                    "allowUnrestrictedEngineLaunch": True,
                }
            ),
            encoding="utf-8",
        )
        from eugene_plexus_agent.library_folders import (
            FOLDERS_FILE,
            FolderRecord,
            LibraryFolderCache,
        )

        LibraryFolderCache(root / FOLDERS_FILE).update(
            [FolderRecord(str(model.parent))], library_url="http://fixture.invalid"
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        log = (root / "agent.log").open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, __file__, "--serve", str(root), "--port", str(port)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            for _ in range(300):
                try:
                    url = f"http://127.0.0.1:{port}/healthz"
                    if httpx.get(url, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=60, trust_env=False
            ) as client:
                login = client.post("/v1/auth/initialize", json={"passphrase": "a3a-disposable-passphrase"})
                client.headers["Authorization"] = f"Bearer {login.json()['sessionToken']}"

                def ask(**spec_extra):  # type: ignore[no-untyped-def]
                    spec = {
                        "name": "big",
                        "engine": "llama_cpp",
                        "modelPath": str(model),
                        "binary": str(server),
                        "flags": {"contextSize": 16384},
                    }
                    for key, value in spec_extra.items():
                        if key == "flags":
                            spec["flags"] |= value
                        else:
                            spec[key] = value
                    answer = client.post("/v1/runtimes/admission", json=spec)
                    assert answer.status_code == 200, answer.text
                    return answer.json()

                placed = ask()
                print(f"     {placed['reason'][:220]}")
                # `tight` (inside the card's total, not its free memory) and
                # `split` (needs host memory too) are decided alike: refused
                # for a full offload, admitted for a partial one.
                spill = placed["fit"]
                assert spill in ("tight", "split"), (
                    f"needs a model larger than free graphics memory; got {spill}"
                )
                assert placed["decision"] == "admit", placed["reason"]
                assert "left to llama.cpp" in placed["reason"], placed["reason"]
                print(f"PASS unset gpuLayers on a build with --fit: {spill}, admitted, and says why")

                off = ask(extraArgs=["--fit", "off"])
                assert off["fit"] == spill and off["decision"] == "refuse", off["reason"]
                print("PASS the same with --fit off: refused")

                explicit = ask(flags={"gpuLayers": 99})
                assert explicit["decision"] == "refuse", explicit["reason"]
                print("PASS an explicit full offload: refused")

                huge = ask(flags={"contextSize": 262144 * 8})
                if huge["fit"] == "no":
                    assert huge["decision"] == "refuse", huge["reason"]
                    print("PASS more than the card and RAM together: refused")
                else:
                    print(f"NOT CHECKED the `no` refusal: this machine scored it {huge['fit']}")
        except BaseException:
            log.flush()
            print((root / "agent.log").read_text(encoding="utf-8", errors="replace")[-4000:])
            raise
        finally:
            (root / "stop").touch()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--server", type=Path)
    parser.add_argument("--model", type=Path)
    parsed = parser.parse_args()
    if parsed.serve:
        serve(parsed.serve, parsed.port)
    else:
        main(parsed)
