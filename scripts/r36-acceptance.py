"""R3.6: real agent API, real child processes, no real model or live install.

Run with the agent dev interpreter. Port 8179 is the agent; 8199 is a
llama.cpp-shaped stand-in (both movable: `--port`, `--engine-port`).
Ambient install settings are removed, state is temporary, ports must be
free, and only owned PIDs are stopped.

Credentials (per-node token keys, 2026-09-25): the agent is standalone,
so it is its own authority, `node:local`. The run sets the passphrase
through the agent's real first-run `POST /v1/auth/initialize` and uses
the session that call returns (an `ep-session+jwt` addressed to
`node:local`, asserted before any runtime check), instead of
pre-populating the agent's auth state with a script-made HS256 signing
key, which no longer exists.

Last run, 2026-09-25, from `specs/scripts`, beside other acceptance runs
holding 81xx and 82xx:
    <xvenv>/Scripts/python.exe r36-acceptance.py --port 8379 --engine-port 8399
-> 6 PASS; runtime API and real child exits.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import jwt
import yaml


def engine(work: Path, port: int) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    with (work / "starts.txt").open("a", encoding="utf-8") as record:
        record.write(f"{os.getpid()}\n")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/crash":
                print("simulated model failure: engine exited", flush=True)
                os._exit(1)
            loading = (work / "model-mode.txt").read_text(encoding="utf-8") == "loading"
            code = 200
            if self.path == "/health":
                code = 503 if loading else 200
                body = {"status": "loading model" if loading else "ok"}
            elif self.path == "/props":
                body = {
                    "default_generation_settings": {"n_ctx": 4096},
                    "total_slots": 1,
                }
            else:
                code, body = 404, {"error": "unknown path"}
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    class Server(HTTPServer):
        allow_reuse_address = os.name != "nt"

        def server_bind(self) -> None:
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    Server(("127.0.0.1", port), Handler).serve_forever()


def serve_agent(work: Path, port: int) -> None:
    import uvicorn

    from eugene_plexus_agent import runtimes
    from eugene_plexus_agent._generated.models import EngineKind, Origin, RuntimeSpec
    from eugene_plexus_agent.app import create_app
    from eugene_plexus_agent.engines.base import DiscoveredBinary
    from eugene_plexus_agent.engines.llama_cpp import LlamaCppAdapter
    from eugene_plexus_agent.settings import Settings

    class Adapter(LlamaCppAdapter):
        def resolve_binary(
            self, spec: RuntimeSpec, *, configured: str | None = None
        ) -> DiscoveredBinary:
            return DiscoveredBinary(
                path=Path(sys.executable),
                origin=Origin.configured,
                version="r36-stand-in",
            )

        def build_argv(self, spec: RuntimeSpec, binary: DiscoveredBinary, port: int) -> list[str]:
            return [
                sys.executable,
                __file__,
                "--engine",
                "--work",
                str(work),
                "--port",
                str(port),
            ]

        def working_directory(self, spec: RuntimeSpec, binary: DiscoveredBinary) -> str:
            return str(work)

    runtimes.ADAPTERS[EngineKind.llama_cpp] = Adapter()
    # The agent builds its own trust in its lifespan: a standalone node
    # signs with the token key it writes to `node.yaml` beside agent.yaml,
    # as `node:local`. The parent signs in through the real API.
    app = create_app(
        Settings(config_file=work / "agent.yaml", default_topology=False, bind_port=port)
    )
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)


def acceptance(agent_port: int, engine_port: int) -> None:
    from eugene_plexus_agent import process_signals

    for port in (agent_port, engine_port):
        with socket.socket() as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))

    checks = 0

    def passed(label: str) -> None:
        nonlocal checks
        checks += 1
        print(f"PASS {checks}: {label}", flush=True)

    with tempfile.TemporaryDirectory(prefix="ep-r36-") as temporary:
        work = Path(temporary)
        mode = work / "model-mode.txt"
        mode.write_text("loading", encoding="utf-8")
        (work / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "components": [],
                    "runtimes": [
                        {
                            "name": "r36-engine",
                            "engine": "llama_cpp",
                            "modelPath": str(mode),
                            "port": engine_port,
                            "autoDriver": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("EUGENE_PLEXUS_")
        }
        env["PYTHONUTF8"] = "1"
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "agent" / "src")
        with (
            (work / "agent.log").open("wb") as log,
            httpx.Client(
                base_url=f"http://127.0.0.1:{agent_port}", timeout=2, trust_env=False
            ) as client,
            httpx.Client(
                base_url=f"http://127.0.0.1:{engine_port}", timeout=2, trust_env=False
            ) as backend,
        ):
            process = subprocess.Popen(
                [
                    sys.executable,
                    __file__,
                    "--serve",
                    "--work",
                    str(work),
                    "--port",
                    str(agent_port),
                ],
                cwd=work,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                **process_signals.spawn_kwargs(),
            )

            def sign_in() -> None:
                """The agent's own first-run setup, which returns its session."""
                deadline = time.perf_counter() + 20
                while True:
                    assert process.poll() is None, "agent exited"
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert time.perf_counter() < deadline, "agent never became healthy"
                    time.sleep(0.1)
                response = client.post(
                    "/v1/auth/initialize",
                    json={"passphrase": secrets.token_urlsafe(24)},
                    timeout=30,
                )
                assert response.status_code == 200, response.text
                session = response.json()["sessionToken"]
                header = jwt.get_unverified_header(session)
                claims = jwt.decode(session, options={"verify_signature": False})
                assert header["typ"] == "ep-session+jwt" and header["alg"] == "EdDSA", header
                assert claims["aud"] == ["node:local"], claims
                assert claims["iss"] == "node:local" and claims["sub"] == "operator", claims
                client.headers["Authorization"] = f"Bearer {session}"
                refused = httpx.get(
                    f"http://127.0.0.1:{agent_port}/v1/runtimes/r36-engine",
                    timeout=2,
                    trust_env=False,
                )
                assert refused.status_code == 401, refused.text

            def runtime(wanted: str, *, after_pid: int | None = None) -> dict:
                deadline = time.perf_counter() + 20
                while time.perf_counter() < deadline:
                    assert process.poll() is None, "agent exited"
                    try:
                        response = client.get("/v1/runtimes/r36-engine")
                    except httpx.TransportError:
                        continue
                    if response.status_code == 200:
                        body = response.json()
                        if body["status"] == wanted and (
                            after_pid is None or body.get("pid") != after_pid
                        ):
                            return body
                raise AssertionError(f"runtime did not become {wanted}")

            def crash() -> None:
                with contextlib.suppress(httpx.TransportError):
                    backend.get("/crash")

            def starts() -> list[str]:
                return (work / "starts.txt").read_text(encoding="utf-8").splitlines()

            try:
                sign_in()
                runtime("loading")
                passed(
                    "real runtime observed loading through the agent API, with the "
                    "node:local session the standalone agent's own setup returned"
                )
                crash()
                failed = runtime("crashed")
                deadline = time.perf_counter() + 3
                while time.perf_counter() < deadline:
                    failed = client.get("/v1/runtimes/r36-engine").json()
                    assert failed["status"] == "crashed"
                    assert len(starts()) == 1, "automatic load retry occurred"
                assert "before becoming ready" in failed["lastError"]
                assert "restart" in failed["lastError"]
                passed("one failed load stays stopped past the original 2s retry delay")
                mode.write_text("ready", encoding="utf-8")
                response = client.post("/v1/runtimes/r36-engine/restart")
                assert response.status_code == 202, response.text
                ready = runtime("ready")
                assert len(starts()) == 2
                assert ready.get("lastError") is None
                passed("operator Restart after fixing the cause starts a new engine")
                crash()
                replacement = runtime("ready", after_pid=ready["pid"])
                assert len(starts()) == 3
                passed("a previously ready engine still recovers automatically")
                response = client.post("/v1/runtimes/r36-engine/stop")
                assert response.status_code == 202, response.text
                stopped = runtime("stopped")
                assert stopped.get("pid") is None
                assert replacement["pid"] != ready["pid"]
                passed("operator Stop releases the replacement process")
                process_signals.request_stop(process, name="r36-agent")
                process.wait(timeout=10)
                passed("isolated agent stopped; no live service or model was touched")
            except BaseException:
                print((work / "agent.log").read_text(encoding="utf-8", errors="replace")[-6000:])
                raise
            finally:
                if process.poll() is None:
                    with contextlib.suppress(httpx.HTTPError):
                        client.post("/v1/runtimes/r36-engine/stop")
                    process_signals.request_stop(process, name="r36-agent")
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    print(f"{checks} PASS; runtime API and real child exits")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--engine", action="store_true")
    parser.add_argument("--work", type=Path)
    parser.add_argument("--port", type=int, default=8179)
    parser.add_argument("--engine-port", type=int, default=8199)
    args = parser.parse_args()
    if args.engine:
        engine(args.work, args.port)
    elif args.serve:
        serve_agent(args.work, args.port)
    else:
        acceptance(args.port, args.engine_port)
