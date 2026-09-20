"""Real gateway + Library processes; fixture agent/driver at the HTTP seam.

Uses disposable state and dynamically allocated loopback ports. No engines,
external providers, installed node state, or operator profiles are touched.
Run with a Python environment containing gateway and library (editable or pinned).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

import httpx
import jwt
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def serve(kind: str, root: Path, port: int, agent_url: str) -> None:
    import uvicorn

    if kind == "gateway":
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings
        app = create_app(Settings(config_file=root / "gateway.yaml", agent_url=agent_url))
    else:
        from eugene_plexus_library.app import create_app
        from eugene_plexus_library.settings import Settings
        app = create_app(Settings(config_file=root / "library.yaml", state_file=root / "state.json"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (root / f"{kind}.stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task

    asyncio.run(run())


def main() -> None:
    from eugene_plexus_library._generated.models import LibraryModel
    from eugene_plexus_library.store import StateStore

    with tempfile.TemporaryDirectory(prefix="ep-r8-") as directory:
        root = Path(directory)
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
        issued = int(time.time())
        def token(audience: str) -> str:
            return jwt.encode({"sub": "r8", "aud": audience, "iat": issued, "exp": issued + 600},
                              key, algorithm="EdDSA")
        service = token("service:gateway")
        operator = token("operator")
        model_path = str(root / "model.gguf")
        store = StateStore(root / "state.json")
        store.replace_models([LibraryModel(id="opaque-model", name="fixture", path=model_path,
            format="gguf", status="present", sizeBytes=0, files=[])], scanned_at=datetime.now(UTC))
        (root / "library.yaml").write_text("modelRoots: []\nscanOnStartup: false\n")
        (root / "gateway.yaml").write_text(yaml.safe_dump({"profileCacheSeconds": 0,
            "routingRefreshSeconds": 3600, "defaultMaxTokens": 2048, "defaultTemperature": 0.7}))
        sockets = [socket.socket() for _ in range(2)]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        gateway_port, library_port = [sock.getsockname()[1] for sock in sockets]
        library_url = f"http://127.0.0.1:{library_port}"
        gateway_url = f"http://127.0.0.1:{gateway_port}"
        calls: list[dict] = []
        reads: list[str] = []
        state = {"outage": False}

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def reply(self, data: object, code: int = 200, content_type: str = "application/json") -> None:
                body = json.dumps(data).encode() if content_type == "application/json" else str(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path.startswith("/api/proxy/library/"):
                    assert self.headers.get("Authorization") == f"Bearer {service}"
                    reads.append(self.path)
                    if state["outage"]:
                        self.reply({"error": "fixture Library unavailable"}, 503)
                        return
                    response = httpx.get(library_url + self.path.removeprefix("/api/proxy/library"),
                        headers={"Authorization": self.headers["Authorization"]}, trust_env=False)
                    self.reply(response.json(), response.status_code)
                elif self.path == "/v1/components":
                    self.reply({"components": [{"name": "fixture-driver", "kind": "inference-driver",
                                                "url": agent_url + "/driver"}]})
                elif self.path == "/v1/runtimes":
                    self.reply({"runtimes": [{"name": "fixture-runtime", "modelAlias": "friendly-alias",
                        "modelPath": model_path, "localPath": "/wrong/local-copy.gguf", "status": "ready",
                        "engine": "llama_cpp", "host": "127.0.0.1", "port": 1}]})
                elif self.path.endswith("/v1/info"):
                    self.reply({"backend": "openai_compat_http", "modelId": "friendly-alias",
                                "runtime": "fixture-runtime"})
                elif self.path == "/v1/node":
                    self.reply({"enrolled": False})
                else:
                    self.reply({}, 404)

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(body)
                result = {"content": "profile-ok", "modelId": "friendly-alias",
                          "backend": "openai_compat_http", "finishReason": "stop"}
                if self.path.endswith("/stream"):
                    self.reply('event: token\ndata: {"text":"profile-ok"}\n\nevent: done\ndata: '
                               + json.dumps(result) + '\n\n', content_type="text/event-stream")
                else:
                    self.reply(result)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        agent_url = f"http://127.0.0.1:{server.server_port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        processes: dict[str, subprocess.Popen] = {}
        logs = []
        try:
            for sock in sockets:
                sock.close()
            for kind, port in (("library", library_port), ("gateway", gateway_port)):
                env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
                env[f"EUGENE_PLEXUS_{kind.upper()}_AUTH_VERIFY_KEY"] = base64.b64encode(public).decode()
                env[f"EUGENE_PLEXUS_{kind.upper()}_SERVICE_TOKEN"] = service
                log = (root / f"{kind}.log").open("w", encoding="utf-8")
                logs.append(log)
                processes[kind] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                    "--serve", kind, "--directory", str(root), "--port", str(port),
                    "--agent-url", agent_url], env=env, cwd=root, stdout=log, stderr=subprocess.STDOUT)
                deadline = time.perf_counter() + 30
                while time.perf_counter() < deadline:
                    try:
                        if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1, trust_env=False).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError(f"{kind} did not start")
            with httpx.Client(headers={"Authorization": f"Bearer {operator}"}, trust_env=False, timeout=15) as client:
                url = library_url + "/v1/models/opaque-model/profiles"
                spec = {"name": "tuned", "engine": "llama_cpp", "maxTokens": 111,
                        "temperature": 0, "topP": 0.2}
                response = client.post(url, json=spec)
                response.raise_for_status()
                profile_id = response.json()["id"]

                def generate(endpoint="/v1/chat/completions", stream=False, **extra):
                    body = {"model": "friendly-alias", "messages": [{"role": "user", "content": "hi"}],
                            "stream": stream, **extra}
                    response = client.post(gateway_url + endpoint, json=body)
                    assert response.status_code == 200, response.text
                    assert "profile-ok" in response.text, response.text
                    return calls[-1]

                for endpoint in ("/v1/chat/completions", "/v1/messages"):
                    for stream in (False, True):
                        extra = {"max_tokens": 37} if endpoint.endswith("messages") else {}
                        got = generate(endpoint, stream, **extra)
                        assert (got["maxTokens"], got["temperature"], got["topP"]) == (extra.get("max_tokens", 111), 0, 0.2), got
                print("PASS both protocols and streaming use persisted model defaults", flush=True)
                count = len(reads)
                got = generate(max_tokens=19, temperature=0, top_p=0, seed=0)
                assert (got["maxTokens"], got["temperature"], got["topP"], got["seed"]) == (19, 0, 0, 0)
                assert len(reads) == count
                print("PASS explicit values bypass Library and preserve zeroes", flush=True)
                spec.update(maxTokens=222, temperature=0.5)
                client.put(url + "/" + profile_id, json=spec).raise_for_status()
                assert generate()["maxTokens"] == 222
                # Warm for one second, then make the Library edge unavailable.
                client.patch(gateway_url + "/v1/config", json={"profileCacheSeconds": 1, "profileMaxStaleSeconds": 1}).raise_for_status()
                generate()
                state["outage"] = True
                time.sleep(1.1)
                assert generate()["maxTokens"] == 222
                time.sleep(1.1)
                assert generate()["maxTokens"] == 2048
                print("PASS edits, bounded stale reuse, and outage fallback", flush=True)
                state["outage"] = False
                time.sleep(4.1)  # finish the failed-read retry backoff
                assert generate()["maxTokens"] == 222
                client.patch(gateway_url + "/v1/config", json={"profileCacheSeconds": 0}).raise_for_status()
                second = client.post(url, json={"name": "second", "engine": "llama_cpp",
                    "default": True, "maxTokens": 333})
                second.raise_for_status()
                assert generate()["maxTokens"] == 333
                client.delete(url + "/" + second.json()["id"]).raise_for_status()
                assert generate()["maxTokens"] == 222
                client.delete(url + "/" + profile_id).raise_for_status()
                assert generate()["maxTokens"] == 2048
                print("PASS recovery, default selection/promotion, and deletion", flush=True)
        except BaseException:
            for path in root.glob("*.log"):
                print(path.name, path.read_text(errors="replace")[-5000:])
            raise
        finally:
            for kind in processes:
                (root / f"{kind}.stop").touch()
            for proc in processes.values():
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            for log in logs:
                log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", choices=["gateway", "library"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--agent-url")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port, args.agent_url)
    else:
        main()
