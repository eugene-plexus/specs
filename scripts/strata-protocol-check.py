"""Exercise a pinned, isolated Strata install with upstream's mock engine.

Run with Eugene's development Python and the managed build's serve/server.py.
No GPU, model download, live installation or fixed application port is used.
Example: python scripts/strata-protocol-check.py C:/Temp/.../serve/server.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import httpx

from eugene_plexus_agent.engines.base import Ready
from eugene_plexus_agent.engines.strata import StrataAdapter
from eugene_plexus_inference_driver._generated.models import (
    GenerateRequest,
    Message,
    Role,
)
from eugene_plexus_inference_driver.engines.strata_http import StrataHttpEngine


async def check(server: Path) -> None:
    root = server.resolve().parent.parent
    python = (
        root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    with tempfile.TemporaryDirectory(prefix="eugene-strata-protocol-") as directory:
        fixture = Path(directory)
        config = fixture / "mock.json"
        config.write_text(
            json.dumps({"model_name": "strata-fixture"}), encoding="utf-8"
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        with (fixture / "server.log").open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [
                    str(python),
                    str(server),
                    "--engine",
                    "mock",
                    "--config",
                    str(config),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--script",
                    "Thinking.</think>\n\nHello from Strata.",
                ],
                cwd=root,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            engine = StrataHttpEngine(
                base_url=url, model_id="strata-fixture", auth_required=False
            )
            try:
                async with httpx.AsyncClient(trust_env=False) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError((fixture / "server.log").read_text())
                        try:
                            health = (await client.get(url + "/health")).json()
                            if health.get("loaded"):
                                break
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.1)
                    else:
                        raise RuntimeError("Strata fixture did not become ready")
                assert isinstance(await StrataAdapter().probe_readiness(url), Ready)
                assert await engine.context_window() == health["max_context"]
                assert not await engine._answers_as_llama_cpp()
                request = GenerateRequest(
                    messages=[Message(role=Role.user, content="Hello")], maxTokens=128
                )
                answer = await engine.generate(request)
                assert answer.content == "Hello from Strata.", answer
                frames = [frame async for frame in engine.stream(request)]
                assert len(frames) > 3, frames
                assert "Hello from Strata." == "".join(f.text for f in frames), frames
                assert any(f.reasoning for f in frames)
                print(
                    json.dumps(
                        {
                            "passed": True,
                            "engine": "upstream mock (no GPU)",
                            "health": health,
                            "response": answer.model_dump(mode="json"),
                            "stream_frames": len(frames),
                        },
                        indent=2,
                    )
                )
            finally:
                await engine.aclose()
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        check=False,
                    )
                else:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                output.close()
                # Windows can release inherited handles just after the parent
                # PID becomes signalled. Check completion before removing the fixture.
                for attempt in range(50):
                    try:
                        (fixture / "server.log").unlink()
                        break
                    except PermissionError:
                        if attempt == 49:
                            raise
                        await asyncio.sleep(0.1)


if __name__ == "__main__":
    asyncio.run(check(Path(sys.argv[1])))
