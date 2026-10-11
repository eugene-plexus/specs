#!/usr/bin/env python3
"""MR0: the embeddings door names what it ignores, through real processes.

2026-10-11. `POST /v1/embeddings` accepted `dimensions` and `user`, passed
neither to any backend and said nothing: the contract called `dimensions`
"passed through", so an application that asked for 256 got the model's full
width with a 200 and no sign of it. The door now answers with
`x-eugene-plexus-ignored-settings` naming each one the request carried.

What runs, all of it real except the engine and the agent's component list:

* the real `eugene-plexus-gateway` and the real `eugene-plexus-inference-driver`
  (`openai_compat_custom`), each its own process on a port the OS chose;
* `r4-stubs.py agent` in front of the component list, as in the count-tokens and
  reasoning runs (the live agent is never read);
* an engine: a fixture playing `llama-server` started with `--embedding`, as
  measured on b10948 and b11552 on 2026-10-11 (`/props`, `/v1/models`,
  `/v1/embeddings`; chat and completions are a 500). **It records every body it
  is sent**, so "ignored" is checked on the wire and not only in the header.

`--llama-server PATH --embedding-model GGUF` adds a real `llama-server` on that
model, on the CPU, behind a second driver: asked for 256 dimensions, a real
`nomic-embed-text-v1.5` still answers 768, with the header saying so, and the
vector is the one it gives when nothing is asked.

The script does not touch the live install: every port is chosen by the OS, every
ambient EUGENE_PLEXUS_* variable is dropped from what a component sees, and the
processes are stopped by handle. Needs the gateway's and the inference-driver's
virtualenvs (`.venv`), and nothing else; the script itself is standard library.

Usage:
    python scripts/mr0-embeddings-honest-acceptance.py
    python scripts/mr0-embeddings-honest-acceptance.py --llama-server PATH --embedding-model GGUF
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent

HEADER = "x-eugene-plexus-ignored-settings"
FIXTURE_MODEL = "mr0-fixture-embed"
REAL_MODEL = "nomic-embed-text-v1.5"
#: The fixture engine's own width. Neither a request's `dimensions` nor anything
#: else in this run may change it.
WIDTH = 8
REAL_WIDTH = 768
#: What llama-server answers on chat and completions when started with
#: `--embedding` (b11552, 2026-10-11).
NO_LOGITS = {
    "error": {
        "code": 500,
        "message": "the current context does not support logits computation. skipping",
        "type": "server_error",
    }
}

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {len(RESULTS):>2}. {name}" + (f"  -- {detail}" if detail else ""))
    return ok


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch(
    method: str, url: str, body: Any = None, timeout: float = 120
) -> tuple[int, http.client.HTTPMessage, Any]:
    """One request, with no proxy in the way. The headers are returned whole so a
    header that arrived twice is seen twice."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("content-type", "application/json")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status, headers, raw = response.status, response.headers, response.read()
    except urllib.error.HTTPError as e:
        status, headers, raw = e.code, e.headers, e.read()
    text = raw.decode("utf-8", "replace")
    try:
        return status, headers, json.loads(text)
    except ValueError:
        return status, headers, text


def named(headers: http.client.HTTPMessage) -> list[str]:
    """Every value the ignored-settings header arrived with (none, or one)."""
    return headers.get_all(HEADER) or []


def venv_python(repo: str) -> Path:
    base = ROOT / repo / ".venv"
    for candidate in (base / "Scripts" / "python.exe", base / "bin" / "python"):
        if candidate.exists():
            return candidate
    raise SystemExit(f"no virtualenv for {repo} at {base}")


def free_ports(count: int) -> list[int]:
    held = [socket.socket() for _ in range(count)]
    try:
        for sock in held:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in held]
    finally:
        for sock in held:
            sock.close()


def wait_until(what: str, probe: Any, seconds: float) -> Any:
    """Wait for the subject itself: `probe()` returns something truthy, or None."""
    deadline = time.perf_counter() + seconds
    last = None
    while time.perf_counter() < deadline:
        try:
            last = probe()
        except OSError:
            last = None
        if last:
            return last
        time.sleep(0.5)
    print(f"  never saw: {what}")
    return None


def vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    raw = [(b - 127.5) / 127.5 for b in digest[:WIDTH]]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


class QuietServer(ThreadingHTTPServer):
    """A driver that is stopped resets its keep-alive connection; that is the
    end of the run, not a failure of the fixture."""

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], OSError):
            return
        super().handle_error(request, client_address)


class FixtureEngine:
    """`llama-server --embedding`, as measured, recording what it is sent."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.seen: list[dict[str, Any]] = []
        lock = threading.Lock()
        seen = self.seen

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:
                return

            def _send(self, payload: object, status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?")[0]
                if path == "/health":
                    self._send({"status": "ok"})
                elif path == "/props":
                    self._send(
                        {
                            "default_generation_settings": {"n_ctx": 2048},
                            "total_slots": 1,
                            "model_alias": FIXTURE_MODEL,
                            "modalities": {"vision": False, "video": False, "audio": False},
                        }
                    )
                elif path == "/v1/models":
                    self._send(
                        {"object": "list", "data": [{"id": FIXTURE_MODEL, "object": "model"}]}
                    )
                else:
                    self._send({"error": {"code": 404, "message": "File Not Found"}}, 404)

            def do_POST(self) -> None:  # noqa: N802
                path = self.path.split("?")[0]
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                if path == "/v1/embeddings":
                    with lock:
                        seen.append(body)
                    given = body.get("input")
                    texts = [given] if isinstance(given, str) else list(given or [])
                    tokens = sum(len(str(t).split()) or 1 for t in texts)
                    self._send(
                        {
                            "model": FIXTURE_MODEL,
                            "object": "list",
                            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
                            "data": [
                                {"embedding": vector(str(t)), "index": i, "object": "embedding"}
                                for i, t in enumerate(texts)
                            ],
                        }
                    )
                elif path in ("/v1/chat/completions", "/v1/completions"):
                    self._send(NO_LOGITS, 500)
                else:
                    self._send({"error": {"code": 404, "message": "File Not Found"}}, 404)

        self.server = QuietServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Stack:
    def __init__(self, work: Path) -> None:
        self.work = work
        # No ambient EUGENE_PLEXUS_* variable reaches a component: the live install's
        # config-file variable is set for the whole account.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        self.procs: list[subprocess.Popen[bytes]] = []

    def spawn(self, name: str, args: list[str], extra: dict[str, str]) -> None:
        log = open(self.work / f"{name}.log", "wb")  # noqa: SIM115 - closed with the process
        self.procs.append(
            subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**self.env, **extra},
            )
        )

    def stop(self) -> None:
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def embed(gateway: str, model: str, text: Any, **extra: Any) -> tuple[int, Any, Any]:
    return fetch("POST", f"{gateway}/v1/embeddings", {"model": model, "input": text, **extra})


def first_vector(body: Any) -> list[float] | str:
    return body["data"][0]["embedding"]


def listed_as_embedder(gateway: str, model: str) -> Any:
    def probe() -> Any:
        status, _h, body = fetch("GET", f"{gateway}/v1/models", timeout=10)
        if status != 200 or not isinstance(body, dict):
            return None
        for entry in body.get("data", []):
            if entry.get("id") == model:
                surfaces = (entry.get("x_eugene_plexus") or {}).get("surfaces")
                return surfaces == ["embeddings"]
        return None

    return probe


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--llama-server", type=Path, help="a real llama-server binary")
    parser.add_argument("--embedding-model", type=Path, help="an embedding GGUF for it")
    args = parser.parse_args()
    real = args.llama_server is not None or args.embedding_model is not None
    if real and not (
        args.llama_server and args.llama_server.is_file()
        and args.embedding_model and args.embedding_model.is_file()
    ):
        print("--llama-server and --embedding-model must both name files that exist")
        return 2

    work = Path(tempfile.mkdtemp(prefix="mr0-embeddings-acceptance-"))
    stack = Stack(work)
    run_id = uuid.uuid4().hex[:8]

    ports = free_ports(6 if real else 4)
    agent_port, gateway_port, fixture_port, fixture_driver_port = ports[:4]
    real_engine_port, real_driver_port = (ports[4], ports[5]) if real else (0, 0)
    gateway = f"http://127.0.0.1:{gateway_port}"
    engine = FixtureEngine(fixture_port)

    drivers = [fixture_driver_port] + ([real_driver_port] if real else [])
    (work / "fixture-driver.yaml").write_text(
        f"provider: openai_compat_custom\nbaseUrl: http://127.0.0.1:{fixture_port}\n"
        f"modelId: {FIXTURE_MODEL}\nrequestTimeoutSeconds: 60\n",
        encoding="utf-8",
    )
    (work / "real-driver.yaml").write_text(
        f"provider: openai_compat_custom\nbaseUrl: http://127.0.0.1:{real_engine_port}\n"
        f"modelId: {REAL_MODEL}\nrequestTimeoutSeconds: 120\n",
        encoding="utf-8",
    )
    (work / "gateway.yaml").write_text(
        "requestTimeoutSeconds: 120\nroutingRefreshSeconds: 2\n", encoding="utf-8"
    )

    print(f"ports: agent {agent_port}, gateway {gateway_port}, engine {fixture_port}, "
          f"driver(s) {drivers}; work {work}")
    try:
        leaked = sorted(k for k in stack.env if k.startswith("EUGENE_PLEXUS_"))
        if not check("no ambient EUGENE_PLEXUS_* variable reaches a component", not leaked,
                     ", ".join(leaked)):
            return 1

        engine.start()
        stack.spawn(
            "agent",
            [sys.executable, str(SCRIPTS / "r4-stubs.py"), "agent", "--port", str(agent_port),
             "--driver-port", *map(str, drivers)],
            {},
        )
        driver_py = str(venv_python("inference-driver"))
        for name, port, config in (
            ("driver-fixture", fixture_driver_port, "fixture-driver.yaml"),
            *((("driver-real", real_driver_port, "real-driver.yaml"),) if real else ()),
        ):
            stack.spawn(
                name,
                [driver_py, "-m", "eugene_plexus_inference_driver"],
                {
                    "EUGENE_PLEXUS_DRIVER_CONFIG_FILE": str(work / config),
                    "EUGENE_PLEXUS_DRIVER_BIND_PORT": str(port),
                    "EUGENE_PLEXUS_DRIVER_AGENT_URL": f"http://127.0.0.1:{agent_port}",
                },
            )
        if real:
            stack.spawn(
                "llama-server",
                [str(args.llama_server), "-m", str(args.embedding_model), "--embedding",
                 "--pooling", "mean", "--alias", REAL_MODEL, "--host", "127.0.0.1",
                 "--port", str(real_engine_port), "-c", "2048", "-t", "8", "--no-webui"],
                # The live install holds the GPU; a real engine here runs on the CPU.
                {"CUDA_VISIBLE_DEVICES": "-1"},
            )
        stack.spawn(
            "gateway",
            [str(venv_python("gateway")), "-m", "eugene_plexus_gateway"],
            {
                "EUGENE_PLEXUS_GATEWAY_CONFIG_FILE": str(work / "gateway.yaml"),
                "EUGENE_PLEXUS_GATEWAY_METRICS_FILE": str(work / "metrics.sqlite3"),
                "EUGENE_PLEXUS_GATEWAY_BIND_PORT": str(gateway_port),
                "EUGENE_PLEXUS_GATEWAY_AGENT_URL": f"http://127.0.0.1:{agent_port}",
            },
        )

        routable = wait_until(
            f"{FIXTURE_MODEL} on the embeddings surface",
            listed_as_embedder(gateway, FIXTURE_MODEL),
            120,
        )
        if not check("the gateway routes the fixture engine's model as an embedder", bool(routable),
                     f"{FIXTURE_MODEL} via the real driver"):
            return 1
        run_fixture_checks(gateway, engine, run_id)

        if real:
            routable = wait_until(
                f"{REAL_MODEL} on the embeddings surface",
                listed_as_embedder(gateway, REAL_MODEL),
                240,
            )
            if check("the gateway routes a real llama-server --embedding as an embedder",
                     bool(routable), f"{REAL_MODEL} on {args.embedding_model.name}"):
                run_real_checks(gateway, run_id)
    finally:
        stack.stop()
        engine.stop()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} PASS, {len(failed)} FAIL  (logs in {work})")
    return 0 if not failed else 1


def run_fixture_checks(gateway: str, engine: FixtureEngine, run_id: str) -> None:
    sent = 0

    def ask(label: str, **extra: Any) -> tuple[int, Any, Any]:
        nonlocal sent
        sent += 1
        return embed(gateway, FIXTURE_MODEL, f"mr0 {run_id} {label}", **extra)

    # 1. Neither setting: the header does not appear, so it means something when it does.
    status, headers, body = ask("plain")
    plain = first_vector(body) if status == 200 else None
    check(
        "neither setting sent: a plain 200 with the model's own width and no header",
        status == 200 and named(headers) == [] and isinstance(plain, list) and len(plain) == WIDTH,
        f"HTTP {status}, header {named(headers)}, width {len(plain) if isinstance(plain, list) else '-'}",
    )

    # 2. `dimensions` smaller than the model's width: named, and not acted on.
    status, headers, body = ask("dimensions", dimensions=4)
    got = first_vector(body) if status == 200 else None
    check(
        "dimensions: named as ignored, and the vector is not truncated to it",
        status == 200 and named(headers) == ["dimensions"] and isinstance(got, list)
        and len(got) == WIDTH,
        f"HTTP {status}, header {named(headers)}, asked for 4, got width "
        f"{len(got) if isinstance(got, list) else '-'}",
    )

    # 3. `user` alone.
    status, headers, _ = ask("user", user="mr0-person")
    check("user: named as ignored", status == 200 and named(headers) == ["user"],
          f"HTTP {status}, header {named(headers)}")

    # 4. Both, `user` sent first: one header, one stable order.
    status, headers, _ = ask("both", user="mr0-person", dimensions=4)
    check(
        "both: one header naming each, in the door's order whatever the request's",
        status == 200 and named(headers) == ["dimensions, user"],
        f"HTTP {status}, header {named(headers)}",
    )

    # 5. base64 is what the OpenAI SDKs ask for; the header rides it, and it is still whole.
    status, headers, body = ask("base64", dimensions=4, encoding_format="base64")
    decoded: list[float] = []
    if status == 200 and isinstance(first_vector(body), str):
        raw = base64.b64decode(first_vector(body))
        decoded = list(struct.unpack(f"<{len(raw) // 4}f", raw))
    check(
        "base64 with dimensions: named, and still the model's whole vector",
        status == 200 and named(headers) == ["dimensions"] and len(decoded) == WIDTH,
        f"HTTP {status}, header {named(headers)}, {len(decoded)} floats",
    )

    # 6. An SDK that sends every field as null is not asking for anything.
    status, headers, _ = ask("nulls", dimensions=None, user=None)
    check("null settings are not settings: no header", status == 200 and named(headers) == [],
          f"HTTP {status}, header {named(headers)}")

    # 7. What the engine was sent. A header that says "ignored" is only true if
    #    nothing downstream acted on it, and the engine's own record is the evidence.
    mine = [b for b in list(engine.seen) if f"mr0 {run_id}" in json.dumps(b.get("input"))]
    keys = sorted({k for b in mine for k in b})
    check(
        "the engine was sent neither setting, on any request",
        len(mine) == sent and keys == ["input", "model"],
        f"{len(mine)} of {sent} requests reached it, body keys {keys}",
    )


def run_real_checks(gateway: str, run_id: str) -> None:
    text = f"the cat sat on the mat {run_id}"
    status, headers, body = embed(gateway, REAL_MODEL, text)
    plain = first_vector(body) if status == 200 else None
    check(
        "a real embedder, nothing asked: its own width, and no header",
        status == 200 and named(headers) == [] and isinstance(plain, list) and len(plain) == REAL_WIDTH,
        f"HTTP {status}, header {named(headers)}, width {len(plain) if isinstance(plain, list) else '-'}",
    )
    status, headers, body = embed(gateway, REAL_MODEL, text, dimensions=256, user="mr0-person")
    got = first_vector(body) if status == 200 else None
    check(
        "a real embedder asked for 256 dimensions answers its own width, and the header says so",
        status == 200 and named(headers) == ["dimensions, user"] and isinstance(got, list)
        and len(got) == REAL_WIDTH,
        f"HTTP {status}, header {named(headers)}, asked for 256, got width "
        f"{len(got) if isinstance(got, list) else '-'}",
    )
    same = (
        isinstance(plain, list) and isinstance(got, list) and len(plain) == len(got)
        and max(abs(a - b) for a, b in zip(plain, got, strict=True)) < 1e-5
    )
    norm = math.sqrt(sum(x * x for x in got)) if isinstance(got, list) else 0.0
    check(
        "ignored means ignored: the vector is the one it gives when nothing is asked",
        bool(same) and abs(norm - 1.0) < 1e-3,
        f"L2 norm {norm:.6f}",
    )


if __name__ == "__main__":
    sys.exit(main())
