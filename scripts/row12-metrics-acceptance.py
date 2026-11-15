"""Row 12, Linux CI: the numbers a scraper and a collector read, through a real install.

A real control root, an enrolled agent, an inference driver and a gateway, with a
stand-in llama-server the agent launches (it serves `/metrics` only when it was
started with `--metrics`, as llama-server does) and a stand-in OTLP/HTTP collector.
Every listener is an OS-assigned loopback port (never 8079-8083), all state is in a
temporary folder, and no `EUGENE_PLEXUS_*` variable reaches a child. Do not run this
against a live install.

Checks (design `docs/design/rows/row-12.md`):
 1. a scrape key made through the real root (purpose `metrics`) reads the gateway's
    and the agent's `/metrics`;
 2. no credential is 401, and a key without the grant is 403, on both;
 3. the scrape key runs no chat and no search (403), and an inference key reads no
    metrics;
 4. after real requests the gateway's page counts them under their model, a made-up
    model makes no series, and the agent's page shows the engine's queue following the
    stand-in, with `--metrics` on the engine's command line though nothing drafts;
 5. a collector set in the console receives the metrics and the spans as OTLP JSON
    with the credential, none of it holding a prompt, a key's name or a person;
 6. with the collector stopped, the export says failing and why, and requests are
    still served;
 7. a revoked scrape key is refused on both.
"""

# No `from __future__ import annotations`: the stand-in's FastAPI routes import
# `Request` inside `engine_app`, and a string annotation of it does not resolve there.
import argparse
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
MODEL = "m"
CANARY = "R12-CANARY-do-not-export-5e1c"
COLLECTOR_SECRET = "Bearer r12-collector-secret"


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the stand-in llama-server -------------------------------------------------


def engine_app(alias: str, metrics_on: bool) -> Any:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, PlainTextResponse

    app = FastAPI()
    state = {"waiting": 0, "served": 0}

    @app.get("/health")
    async def health() -> Any:
        return {"status": "ok"}

    @app.get("/props")
    async def props() -> Any:
        return {"default_generation_settings": {"n_ctx": 32768}, "total_slots": 2}

    @app.get("/v1/models")
    async def models() -> Any:
        return {"object": "list", "data": [{"id": alias, "object": "model"}]}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> Any:
        if not metrics_on:
            # llama-server without --metrics: the endpoint is off.
            return JSONResponse(
                {"error": {"message": "metrics are off"}}, status_code=501
            )
        return (
            "# TYPE llamacpp:requests_deferred gauge\n"
            f"llamacpp:requests_deferred {state['waiting']}\n"
            "# TYPE llamacpp:requests_processing gauge\n"
            "llamacpp:requests_processing 0\n"
            "# TYPE llamacpp:tokens_predicted_total counter\n"
            f"llamacpp:tokens_predicted_total {state['served'] * 8}\n"
        )

    @app.post("/waiting")
    async def waiting(request: Request) -> Any:
        state["waiting"] = int((await request.json())["n"])
        return {}

    @app.post("/v1/chat/completions")
    async def answer(request: Request) -> Any:
        body = await request.json()
        state["served"] += 1
        usage = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
        if body.get("stream"):

            async def stream() -> Any:
                for _ in range(4):
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "id": "standin",
                                "object": "chat.completion.chunk",
                                "created": 1,
                                "model": alias,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": "word "},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                        )
                        + "\n\n"
                    )
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "id": "standin",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": alias,
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": "stop"}
                            ],
                            "usage": usage,
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"

            from fastapi.responses import StreamingResponse

            return StreamingResponse(stream(), media_type="text/event-stream")
        return {
            "id": "standin",
            "object": "chat.completion",
            "created": 1,
            "model": alias,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "word " * 8},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }

    return app


def engine() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--alias", default=MODEL)
    parser.add_argument("--metrics", action="store_true")
    args, _ = parser.parse_known_args()
    import uvicorn

    uvicorn.run(
        engine_app(args.alias, args.metrics),
        host=args.host,
        port=args.port,
        log_level="error",
        access_log=False,
    )


# --- the stand-in collector -----------------------------------------------------


class Collector:
    """An OTLP/HTTP endpoint that keeps every post it takes."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, str], bytes]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                owner.posts.append(
                    (
                        self.path,
                        {k.lower(): v for k, v in self.headers.items()},
                        self.rfile.read(length),
                    )
                )
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def bodies(self, path: str) -> list[bytes]:
        return [body for p, _, body in self.posts if p == path]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


# --- reading a page -------------------------------------------------------------


def samples(page: str, name: str) -> list[dict[str, str]]:
    """The label sets of every sample of `name` on a Prometheus page."""
    out = []
    for line in page.splitlines():
        if line.startswith(name + "{") or line.startswith(name + " "):
            labels = re.search(r"\{(.*)\}", line)
            out.append(
                dict(
                    re.findall(
                        r'(\w+)="((?:[^"\\]|\\.)*)"', labels.group(1) if labels else ""
                    )
                )
            )
    return out


def value_of(page: str, name: str, **want: str) -> float | None:
    for line in page.splitlines():
        if not (line.startswith(name + "{") or line.startswith(name + " ")):
            continue
        labels = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', line))
        if all(labels.get(k) == v for k, v in want.items()):
            return float(line.rsplit(" ", 1)[1])
    return None


# --- the run --------------------------------------------------------------------


def exercise(directory: Path) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    sweep = load("serving-sweep-acceptance.py")
    for name in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    names = ("control", "agent", "machine", "engine", "local", "gateway")
    ports = dict(zip(names, sweep.free_ports(len(names)), strict=True))
    assert not set(ports.values()) & set(range(8079, 8084))

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    client = httpx.Client(timeout=60, trust_env=False)
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs: list[Any] = []
    passphrase = secrets.token_urlsafe(24)
    collector = Collector()

    def write(name: str, filename: str, body: Any) -> None:
        root = directory / name
        root.mkdir(exist_ok=True)
        (root / filename).write_text(
            json.dumps(body) if filename.endswith(".json") else yaml.safe_dump(body),
            encoding="utf-8",
        )

    def start(name: str) -> None:
        root = directory / name
        root.mkdir(exist_ok=True)
        log = (root / "process.log").open("ab")
        logs.append(log)
        command = (
            sweep.agent_command(root, ports[name], ports["machine"])
            if name == "agent"
            else [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                name,
                "--directory",
                str(root),
                "--port",
                str(ports[name]),
            ]
        )
        processes[name] = subprocess.Popen(
            command,
            env=sweep.child_environment(directory),
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        sweep.wait(
            lambda: client.get(url(name) + "/healthz").status_code == 200, f"{name} up"
        )

    def call(
        name: str, method: str, path: str, token: str | None = None, **kwargs: Any
    ) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = "Bearer " + token
        return client.request(method, url(name) + path, headers=headers, **kwargs)

    def good(
        name: str, method: str, path: str, token: str | None = None, **kwargs: Any
    ) -> Any:
        response = call(name, method, path, token, **kwargs)
        assert response.is_success, (path, response.status_code, response.text)
        return response.json() if response.content else {}

    def ok(label: str) -> None:
        print(f"PASS {label}", flush=True)

    def chat(
        token: str, text: str, *, model: str = MODEL, stream: bool = False
    ) -> httpx.Response:
        return call(
            "gateway",
            "POST",
            "/v1/chat/completions",
            token,
            json={
                "model": model,
                "stream": stream,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": text}],
            },
        )

    try:
        # --- an install: root, an enrolled agent, a runtime, a driver, a gateway ----
        start("control")
        good("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        root_token = good(
            "control", "POST", "/v1/auth/login", json={"passphrase": passphrase}
        )["sessionToken"]
        write(
            "agent",
            "agent.yaml",
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "securityMode": "prompt_on_startup",
                "advertiseUrl": url("agent"),
                "engineBinaryRoots": [str(directory)],
                "components": [],
                "runtimes": [],
            },
        )
        start("agent")
        standalone = good(
            "agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
        )["sessionToken"]
        join = good(
            "control",
            "POST",
            "/v1/nodes/join-token",
            root_token,
            json={"grants": ["gateway"]},
        )
        good(
            "agent",
            "POST",
            "/v1/node/enroll",
            standalone,
            json={
                "controlUrl": url("control"),
                "token": join["token"],
                "name": "tower",
            },
        )
        operator = good(
            "agent", "POST", "/v1/auth/login", json={"passphrase": passphrase}
        )["sessionToken"]
        identity = NodeIdentityStore(directory / "agent/node.yaml")
        identity.load()
        trust = NodeTrust(identity, directory / "agent/trust_bundle.json")
        trust.load()

        def bootstrap(sub: str) -> dict[str, Any]:
            token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
            return {
                "agent_url": url("agent"),
                "trust_bundle_file": str(trust.bundle_path),
                "trust_authority": trust.authority,
                "auth_recipient": trust.recipient,
                "service_token": token,
            }

        launcher = directory / "llama-server"
        launcher.write_text(
            f"""#!{sys.executable}
import sys, runpy
if '--version' in sys.argv:
    print('version: 12001 (r12r12r1)')
    raise SystemExit
if '--help' in sys.argv:
    print('--host --port --model --alias --ctx-size --parallel --n-gpu-layers '
          '--fit --metrics --flash-attn')
    raise SystemExit
sys.argv.insert(1, '--engine')
runpy.run_path({str(Path(__file__).resolve())!r}, run_name='__main__')
""",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        model_file = directory / "standin.gguf"
        model_file.write_bytes(b"GGUF" + b"\0" * 128)
        good(
            "agent",
            "POST",
            "/v1/runtimes",
            operator,
            json={
                "name": "r",
                "engine": "llama_cpp",
                "binary": str(launcher),
                "modelPath": str(model_file),
                "modelAlias": MODEL,
                "port": ports["engine"],
                "autoStart": True,
                "autoDriver": False,
                "flags": {"contextSize": 32768, "parallelSlots": 2, "gpuLayers": 0},
            },
        )
        sweep.wait(
            lambda: (
                next(
                    r
                    for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
                    if r["name"] == "r"
                )["status"]
                == "ready"
            ),
            "the stand-in runtime is ready",
            seconds=60,
        )
        write("local", "bootstrap.json", bootstrap("inference-driver"))
        write(
            "local",
            "driver.yaml",
            {
                "provider": "openai_compat_custom",
                "modelId": MODEL,
                "backendLocality": "local",
                "runtimeName": "r",
            },
        )
        start("local")
        good(
            "agent",
            "POST",
            "/v1/components",
            operator,
            json={"name": "local", "kind": "inference-driver", "url": url("local")},
        )
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write(
            "gateway",
            "gateway.yaml",
            {"routingRefreshSeconds": 1, "telemetryOtlpIntervalSeconds": 5},
        )
        start("gateway")

        def mint(name: str, **limits: Any) -> dict[str, Any]:
            return good(
                "agent",
                "POST",
                "/v1/auth/client-keys",
                operator,
                json={"name": name, "limits": limits},
            )

        # The key the console's "Make a scrape key" makes: numbers, no model, no tool.
        scrape_made = mint(
            "Prometheus", allowedModels=[], allowedTools=[], readMetrics=True
        )
        scrape = str(scrape_made["token"])
        scrape_id = str(scrape_made["key"]["id"])
        plain = str(mint("An app")["token"])
        sweep.wait(
            lambda: any(
                m["id"] == MODEL
                for m in call("gateway", "GET", "/v1/models", plain)
                .json()
                .get("data", [])
            ),
            "the gateway routes the stand-in",
            seconds=30,
        )

        # --- 1 and 2: who may read ---------------------------------------------------
        for where in ("gateway", "agent"):
            read = call(where, "GET", "/metrics", scrape)
            assert read.status_code == 200, (where, read.status_code, read.text[:300])
            assert call(where, "GET", "/metrics").status_code == 401, where
            refused = call(where, "GET", "/metrics", plain)
            assert refused.status_code == 403 and "May read metrics" in refused.text, (
                where,
                refused.status_code,
                refused.text[:300],
            )
            # An operator session reads them too.
            assert call(where, "GET", "/metrics", operator).status_code == 200, where
        ok(
            "1-2. a scrape key reads the gateway and the agent; no key is 401; no grant is 403"
        )

        # --- 3: the grant opens nothing else, and inference opens no metrics ----------
        denied = chat(scrape, "may I?")
        assert denied.status_code == 403, (denied.status_code, denied.text[:300])
        searched = call(
            "gateway", "POST", "/v1/web_search", scrape, json={"query": "anything"}
        )
        assert searched.status_code == 403, (searched.status_code, searched.text[:300])
        assert call("gateway", "GET", "/v1/metrics", scrape).status_code == 401
        assert call("gateway", "GET", "/v1/config", scrape).status_code == 401
        ok("3. the scrape key runs no chat and no search, and opens no operator path")

        # --- 4: the numbers are the traffic -------------------------------------------
        for text in ("one", "two"):
            assert chat(plain, text).status_code == 200
        assert chat(plain, "streamed", stream=True).status_code == 200
        assert chat(plain, "nobody", model="zz-made-up-model").status_code in (400, 404)
        page = good_text(call("gateway", "GET", "/metrics", scrape))
        assert (
            value_of(
                page,
                "eugene_requests_total",
                door="chat",
                outcome="served",
                model=MODEL,
            )
            == 3
        ), page[:2000]
        assert "zz-made-up" not in page
        assert value_of(page, "eugene_build_info", component="gateway") == 1
        assert (
            value_of(page, "eugene_time_to_first_token_seconds_count", model=MODEL) == 1
        )
        client.post(url("engine") + "/waiting", json={"n": 3}).raise_for_status()
        engine_page = good_text(call("agent", "GET", "/metrics", scrape))
        assert (
            value_of(
                engine_page,
                "eugene_engine_requests_waiting",
                node="tower",
                runtime="r",
                model=MODEL,
                engine="llama_cpp",
            )
            == 3
        ), engine_page[:2000]
        assert value_of(engine_page, "eugene_engine_scrape_ok", runtime="r") == 1, (
            "the engine did not answer /metrics: --metrics was not on its command line"
        )
        assert not samples(engine_page, "eugene_engine_draft_tokens_total"), (
            engine_page[:2000]
        )
        client.post(url("engine") + "/waiting", json={"n": 0}).raise_for_status()
        ok(
            "4. requests are counted under their model; no made-up series; the engine's queue follows"
        )

        # --- 5: a collector set in the console ------------------------------------------
        good(
            "gateway",
            "PATCH",
            "/v1/config",
            operator,
            json={
                "telemetryOtlpEndpoint": f"http://127.0.0.1:{collector.port}",
                "telemetryOtlpAuthorization": COLLECTOR_SECRET + "  ",
            },
        )
        assert (
            chat(plain, f"please keep this private {CANARY}", stream=True).status_code
            == 200
        )
        sweep.wait(
            lambda: collector.bodies("/v1/metrics") and collector.bodies("/v1/traces"),
            "the collector received metrics and traces",
            seconds=40,
        )
        for path, headers, body in collector.posts:
            assert headers.get("authorization") == COLLECTOR_SECRET, (path, headers)
            text = body.decode("utf-8")
            json.loads(text)
            assert CANARY not in text, path
            assert "An app" not in text and "Prometheus" not in text, path
            assert (
                "eugene_client_key_info" not in text and "person" not in text.lower()
            ), path
        names = {
            m["name"]
            for post in collector.bodies("/v1/metrics")
            for rm in json.loads(post)["resourceMetrics"]
            for sm in rm["scopeMetrics"]
            for m in sm["metrics"]
        }
        assert "eugene_requests_total" in names and "eugene_build_info" in names, names
        spans = [
            s
            for post in collector.bodies("/v1/traces")
            for rs in json.loads(post)["resourceSpans"]
            for ss in rs["scopeSpans"]
            for s in ss["spans"]
        ]
        assert any(
            a["key"] == "gen_ai.request.model" and a["value"]["stringValue"] == MODEL
            for s in spans
            for a in s["attributes"]
        ), spans[:2]
        export = good("gateway", "GET", "/v1/metrics/export", scrape)
        assert export["otlp"]["state"] == "ok" and export["otlp"]["lastSuccessAt"], (
            export
        )
        assert export["otlp"]["endpoint"] == f"http://127.0.0.1:{collector.port}", (
            export
        )
        assert export["prometheus"]["lastScrapeKeyName"], export
        assert COLLECTOR_SECRET not in json.dumps(export)
        assert good("gateway", "GET", "/v1/config", operator)[
            "telemetryOtlpAuthorization"
        ] == ("<redacted>")
        ok(
            "5. a collector set in the console gets metrics and spans, with the credential, no prompt"
        )

        # --- 6: a collector that is down costs nothing but its own state -----------------
        collector.stop()

        def failing() -> Any:
            found = good("gateway", "GET", "/v1/metrics/export", scrape)["otlp"]
            return found if found["state"] == "failing" else None

        failed = sweep.wait(failing, "the export says failing", seconds=40)
        assert failed["lastError"] and "could not connect" in failed["lastError"], (
            failed
        )
        assert "secret" not in failed["lastError"].lower(), failed
        assert chat(plain, "still served").status_code == 200
        ok("6. a collector that is down is named, and requests are still served")

        # --- 7: a revoked scrape key ---------------------------------------------------------
        assert client.request(
            "DELETE",
            url("agent") + f"/v1/auth/client-keys/{scrape_id}",
            headers={"Authorization": "Bearer " + operator},
        ).status_code in (200, 204)
        for where in ("gateway", "agent"):
            sweep.wait(
                lambda where=where: (
                    call(where, "GET", "/metrics", scrape).status_code in (401, 403)
                ),
                f"{where} refuses the revoked scrape key",
                seconds=40,
            )
        ok("7. a revoked scrape key is refused on both")
        print("All row 12 checks passed", flush=True)
    finally:
        if collector.thread.is_alive():
            collector.stop()
        for process in processes.values():
            process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()
        client.close()


def good_text(response: Any) -> str:
    assert response.status_code == 200, (response.status_code, response.text[:300])
    return str(response.text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--engine", action="store_true")
    args, _ = parser.parse_known_args()
    if args.engine:
        engine()
    elif args.serve == "gateway":
        load("ld1-fair-queue-acceptance.py").serve_gateway(args.directory, args.port)
    elif args.serve == "local":
        load("a6-local-only-acceptance.py").serve("local", args.directory, args.port)
    elif args.serve == "control":
        load("a6-local-only-acceptance.py").serve("control", args.directory, args.port)
    else:
        if os.name == "nt":
            raise SystemExit("Linux only: the stand-in engine is an executable script.")
        root = HERE.parents[1] / ".codex-tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="r12-", dir=root) as tmp:
            try:
                exercise(Path(tmp))
            except BaseException:
                for log in sorted(Path(tmp).glob("*/process.log")):
                    print(
                        f"--- {log.parent.name}",
                        log.read_text(encoding="utf-8", errors="replace")[-6000:],
                    )
                raise


if __name__ == "__main__":
    main()
