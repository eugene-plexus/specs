"""Row 11 (LD1), Linux CI: one fair queue, through a real root, agent, driver and two gateways.

The engine is a stand-in llama-server the real agent launches as a `llama_cpp`
runtime: it answers `--version`, `--help`, `/health` and `/props` (two slots),
streams each answer over a fixed time, queues anything past two in arrival
order, and counts how many it holds at once. Every listener is an OS-assigned
loopback port (never 8079-8083), all state is in a temporary folder, and no
`EUGENE_PLEXUS_*` variable reaches a child. Do not run this against a live
install.

Checks (design `docs/design/rows/row-11.md` §5):
 1. a key with limit 2 sends 10 requests at once: all 200, the engine sees at
    most 2 at a time, and the rows carry `queuedMs`;
 2. the 11th is refused `key_queue_full` with `Retry-After`;
 3. key A (limit raised) sends 51, key B sends 1 half a second later: B's first
    token comes within 3 s;
 4. a background key waits behind interactive requests, and its
    `X-Eugene-Band: interactive` is ignored;
 5. with the line's wait at 5 s, a request is refused `queue_timeout` on the
    OpenAI and Anthropic doors, whole and streamed;
 6. four requests that meet a starting runtime are all served, none a 503;
 7. two gateways share one key with limit 2: the engine never sees more than 2,
    and the second gateway's waiter leaves when the first releases;
 8. a client that disconnects while waiting frees its place at once;
 9. a gateway stopped with waiters refuses them `shutting_down` and does not hang;
10. a v13 metrics store is moved to v14 in place.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import secrets
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
MODEL, WAKE = "m", "w"
#: How long the stand-in takes over one answer unless told otherwise.
ANSWER_SECONDS = 2.0
#: How long the on-demand runtime takes to become healthy.
START_SECONDS = 4.0


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the stand-in llama-server -------------------------------------------------


def engine_app(alias: str) -> Any:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

    app = FastAPI()
    slots = asyncio.Semaphore(2)
    born = time.perf_counter()
    state: dict[str, Any] = {"now": 0, "most": 0, "order": [], "seconds": ANSWER_SECONDS}

    def ready() -> bool:
        return alias != WAKE or time.perf_counter() - born >= START_SECONDS

    @app.get("/health")
    @app.get("/healthz")
    async def health() -> Any:
        if not ready():
            return JSONResponse({"error": {"message": "Loading model"}}, status_code=503)
        return {"status": "ok"}

    @app.get("/props")
    async def props() -> Any:
        return {"default_generation_settings": {"n_ctx": 32768}, "total_slots": 2}

    @app.get("/v1/models")
    async def models() -> Any:
        return {"object": "list", "data": [{"id": alias, "object": "model"}]}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> str:
        return "llamacpp:requests_processing 0\n"

    @app.get("/stats")
    async def stats() -> Any:
        return {k: state[k] for k in ("now", "most", "order")}

    @app.post("/stats/reset")
    async def reset() -> Any:
        state["most"], state["order"] = state["now"], []
        return {}

    @app.post("/mode")
    async def mode(request: Request) -> Any:
        state["seconds"] = float((await request.json())["seconds"])
        return {}

    @app.post("/v1/chat/completions")
    async def answer(request: Request) -> Any:
        body = await request.json()
        messages = body.get("messages") or []
        text = str(messages[-1].get("content") if messages else "")
        seconds = float(state["seconds"])
        usage = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}

        def chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> str:
            return "data: " + json.dumps(
                {
                    "id": "standin",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": alias,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                    **extra,
                }
            ) + "\n\n"

        async def take() -> None:
            await slots.acquire()
            state["now"] += 1
            state["most"] = max(state["most"], state["now"])
            state["order"].append(text)

        def leave() -> None:
            state["now"] -= 1
            slots.release()

        if body.get("stream"):

            async def stream() -> Any:
                await take()
                try:
                    for index in range(8):
                        yield chunk({"content": "word "})
                        await asyncio.sleep(seconds / 8)
                    yield chunk({}, "stop", usage=usage)
                    yield "data: [DONE]\n\n"
                finally:
                    leave()

            return StreamingResponse(stream(), media_type="text/event-stream")
        await take()
        try:
            await asyncio.sleep(seconds)
        finally:
            leave()
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
    args, _ = parser.parse_known_args()
    import uvicorn

    uvicorn.run(
        engine_app(args.alias), host=args.host, port=args.port, log_level="error", access_log=False
    )


# --- the gateway, through its own server (row 11's stop) ------------------------


def serve_gateway(directory: Path, port: int) -> None:
    import uvicorn
    from eugene_plexus_gateway.__main__ import _Server
    from eugene_plexus_gateway.app import create_app
    from eugene_plexus_gateway.settings import Settings

    bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
    app = create_app(
        settings=Settings(
            config_file=directory / "gateway.yaml",
            metrics_file=directory / "metrics.sqlite3",
            client_key_refresh_seconds=0.15,
            client_key_max_age_seconds=3.5,
            client_key_timeout_seconds=0.4,
            client_key_retry_seconds=0.1,
            **bootstrap,
        )
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    _Server(config, app).run()


def v13_store(path: Path) -> None:
    """A metrics store as schema 13 left it, with one row of history (check 10)."""
    from eugene_plexus_gateway.metrics import _DDL

    ddl = _DDL
    for column in ("queued_ms", "band", "refusal", "tier_moves", "outran_reserve"):
        lines = [line for line in ddl.split("\n") if not line.strip().startswith(column + " ")]
        ddl = "\n".join(lines)
    ddl = ddl.replace("    affinity          TEXT,\n);", "    affinity          TEXT\n);")
    assert "queued_ms" not in ddl and "affinity          TEXT\n);" in ddl, "v13 DDL"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(ddl)
        conn.execute("INSERT INTO meta VALUES ('schema_version', '13')")
        conn.execute(
            "INSERT INTO request (started_at, requested_model, attempts, total_ms, outcome)"
            " VALUES (?, 'ld1-old-history', 1, 9, 'served')",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),),
        )


# --- the run --------------------------------------------------------------------


def exercise(directory: Path) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    sweep = load("serving-sweep-acceptance.py")
    for name in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    names = (
        "control",
        "agent",
        "machine",
        "engine",
        "wake-engine",
        "local",
        "wake",
        "gateway-a",
        "gateway-b",
    )
    ports = dict(zip(names, sweep.free_ports(len(names)), strict=True))
    assert not set(ports.values()) & set(range(8079, 8084))

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    client = httpx.Client(
        timeout=90, trust_env=False, limits=httpx.Limits(max_connections=200)
    )
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs: list[Any] = []
    passphrase = secrets.token_urlsafe(24)
    passed: list[str] = []

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
        sweep.wait(lambda: client.get(url(name) + "/healthz").status_code == 200, f"{name} up")

    def call(name: str, method: str, path: str, token: str | None = None, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = "Bearer " + token
        return client.request(method, url(name) + path, headers=headers, **kwargs)

    def good(name: str, method: str, path: str, token: str | None = None, **kwargs: Any) -> Any:
        response = call(name, method, path, token, **kwargs)
        assert response.is_success, (path, response.status_code, response.text)
        return response.json() if response.content else {}

    def ok(label: str) -> None:
        passed.append(label)
        print(f"PASS {label}", flush=True)

    def chat(
        gateway: str,
        token: str,
        text: str,
        *,
        model: str = MODEL,
        stream: bool = False,
        headers: dict[str, str] | None = None,
        timeout: float = 90,
    ) -> httpx.Response:
        return call(
            gateway,
            "POST",
            "/v1/chat/completions",
            token,
            json={
                "model": model,
                "stream": stream,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": text}],
            },
            headers=headers,
            timeout=timeout,
        )

    def messages(gateway: str, token: str, text: str, *, stream: bool = False) -> httpx.Response:
        return call(
            gateway,
            "POST",
            "/v1/messages",
            token,
            json={
                "model": MODEL,
                "stream": stream,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": text}],
            },
        )

    def engine_stats() -> dict[str, Any]:
        return client.get(url("engine") + "/stats").json()

    def engine_reset() -> None:
        client.post(url("engine") + "/stats/reset")

    def answer_seconds(seconds: float) -> None:
        client.post(url("engine") + "/mode", json={"seconds": seconds}).raise_for_status()

    try:
        # --- an install: root, an enrolled agent, two runtimes, drivers --------
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
            "control", "POST", "/v1/nodes/join-token", root_token, json={"grants": ["gateway"]}
        )
        good(
            "agent",
            "POST",
            "/v1/node/enroll",
            standalone,
            json={"controlUrl": url("control"), "token": join["token"], "name": "tower"},
        )
        operator = good("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase})[
            "sessionToken"
        ]
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
    print('version: 12001 (ld1ld1ld)')
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
        for name, alias, port, on_demand in (
            ("r", MODEL, ports["engine"], False),
            ("rw", WAKE, ports["wake-engine"], True),
        ):
            good(
                "agent",
                "POST",
                "/v1/runtimes",
                operator,
                json={
                    "name": name,
                    "engine": "llama_cpp",
                    "binary": str(launcher),
                    "modelPath": str(model_file),
                    "modelAlias": alias,
                    "port": port,
                    "autoStart": not on_demand,
                    "startOnDemand": on_demand,
                    "autoDriver": False,
                    "flags": {"contextSize": 32768, "parallelSlots": 2, "gpuLayers": 0},
                },
            )
        sweep.wait(
            lambda: next(
                r
                for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
                if r["name"] == "r"
            )["status"]
            == "ready",
            "the stand-in runtime is ready",
            seconds=60,
        )
        runtime = next(
            r for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"] if r["name"] == "r"
        )
        slots = (runtime.get("capabilities") or {}).get("parallelSlots")
        assert slots == 2, f"the agent reports parallelSlots {slots!r}, so nothing is slot-gated"
        for name, runtime_name, model in (("local", "r", MODEL), ("wake", "rw", WAKE)):
            write(name, "bootstrap.json", bootstrap("inference-driver"))
            write(
                name,
                "driver.yaml",
                {
                    "provider": "openai_compat_custom",
                    "modelId": model,
                    "backendLocality": "local",
                    "runtimeName": runtime_name,
                },
            )
            start(name)
            good(
                "agent",
                "POST",
                "/v1/components",
                operator,
                json={"name": name, "kind": "inference-driver", "url": url(name)},
            )
        # Check 10's store is in place before gateway-a first opens it.
        v13_store(directory / "gateway-a" / "metrics.sqlite3")
        for gateway in ("gateway-a", "gateway-b"):
            write(gateway, "bootstrap.json", bootstrap("gateway"))
            write(gateway, "gateway.yaml", {"routingRefreshSeconds": 1})
            start(gateway)

        def mint(name: str, **limits: Any) -> str:
            made = good(
                "agent",
                "POST",
                "/v1/auth/client-keys",
                operator,
                json={"name": name, "limits": limits},
            )
            return str(made["token"])

        two = mint("Two at once", maxConcurrentRequests=2, requestsPerMinute=1000)
        sweep.wait(
            lambda: any(
                m["id"] == MODEL
                for m in call("gateway-a", "GET", "/v1/models", two).json().get("data", [])
            ),
            "gateway-a routes the stand-in",
            seconds=30,
        )
        sweep.wait(
            lambda: chat("gateway-b", two, "LD1:warm").status_code == 200,
            "gateway-b serves",
            seconds=30,
        )

        def rows(gateway: str, count: int = 1) -> list[dict[str, Any]]:
            """The gateway's newest request rows, once at least `count` are written."""
            found: list[dict[str, Any]] = []

            def enough() -> bool:
                nonlocal found
                found = good(gateway, "GET", "/v1/metrics/requests?limit=500", operator)[
                    "requests"
                ]
                return len(found) >= count

            sweep.wait(enough, f"{count} rows on {gateway}", seconds=20)
            return found

        def keyed(gateway: str, name: str, count: int) -> list[dict[str, Any]]:
            """The rows of key `name`, once `count` of them are written."""
            found: list[dict[str, Any]] = []

            def enough() -> bool:
                nonlocal found
                found = [r for r in rows(gateway) if r.get("clientKeyName") == name]
                return len(found) >= count

            sweep.wait(enough, f"{count} rows of {name}", seconds=20)
            return found

        # --- 10: the v13 store moved to v14 in place, its history kept ---------
        history = rows("gateway-a", 1)
        assert any(r["requestedModel"] == "ld1-old-history" for r in history), history[:3]
        with sqlite3.connect(directory / "gateway-a" / "metrics.sqlite3") as conn:
            version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert version == ("14",), version
        ok("10. a v13 metrics store is moved to v14 in place, its history kept")

        # --- 1 and 2: over the limit waits; past the line, key_queue_full ------
        engine_reset()
        with ThreadPoolExecutor(10) as pool:
            ten = list(pool.map(lambda n: chat("gateway-a", two, f"LD1:ten-{n}"), range(10)))
        assert [r.status_code for r in ten] == [200] * 10, [
            r.text for r in ten if r.status_code != 200
        ]
        assert engine_stats()["most"] <= 2, engine_stats()
        waited = [r["queuedMs"] or 0 for r in keyed("gateway-a", "Two at once", 10)]
        assert max(waited) >= 1500, waited
        ok("1. a key with limit 2 sends 10 at once: all 200, the engine held at most 2, rows carry queuedMs")

        engine_reset()
        with ThreadPoolExecutor(10) as pool:
            futures = [pool.submit(chat, "gateway-a", two, f"LD1:fill-{n}") for n in range(10)]
            sweep.wait(
                lambda: sum(
                    sum(q["waiting"].values())
                    for q in good("gateway-a", "GET", "/v1/metrics", operator).get("queue") or []
                )
                >= 8,
                "two running and eight waiting",
            )
            eleventh = chat("gateway-a", two, "LD1:eleventh")
            assert eleventh.status_code == 429, eleventh.text
            assert int(eleventh.headers["Retry-After"]) > 0
            assert eleventh.headers["X-Eugene-Refusal-Reason"] == "key_queue_full"
            assert eleventh.json()["error"]["code"] == "key_queue_full"
            assert "its most" in eleventh.json()["error"]["message"]
            assert [f.result().status_code for f in futures] == [200] * 10
        ok("2. the 11th request is refused key_queue_full with Retry-After")

        # --- 3: one key's burst does not hold back another ---------------------
        burst = mint("Burst", maxConcurrentRequests=64, maxQueuedRequests=64, requestsPerMinute=10000)
        other = mint("Other", maxConcurrentRequests=2, requestsPerMinute=1000)
        engine_reset()
        with ThreadPoolExecutor(52) as pool:
            a_side = [pool.submit(chat, "gateway-a", burst, f"LD1:a-{n}") for n in range(51)]
            time.sleep(0.5)
            began = time.perf_counter()
            first_token: float | None = None
            with client.stream(
                "POST",
                url("gateway-a") + "/v1/chat/completions",
                headers={"Authorization": "Bearer " + other},
                json={
                    "model": MODEL,
                    "stream": True,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "LD1:b"}],
                },
            ) as streamed:
                assert streamed.status_code == 200
                for line in streamed.iter_lines():
                    if '"content"' in line and first_token is None:
                        first_token = time.perf_counter() - began
            assert first_token is not None and first_token <= 3.0, first_token
            assert [f.result().status_code for f in a_side] == [200] * 51
        assert engine_stats()["most"] <= 2
        ok(f"3. key B's first token came {first_token:.2f} s after A's 51-request burst began")

        # --- 4: background waits behind interactive; a header cannot raise it --
        fast = mint("Interactive", maxConcurrentRequests=8, requestsPerMinute=1000)
        slow = mint("Background", band="background", maxConcurrentRequests=8, requestsPerMinute=1000)
        engine_reset()
        with ThreadPoolExecutor(4) as pool:
            # The two slots free one at a time, so the first freed decides the order.
            fills = [pool.submit(chat, "gateway-a", fast, "LD1:hold-0")]
            time.sleep(1.0)
            fills.append(pool.submit(chat, "gateway-a", fast, "LD1:hold-1"))
            time.sleep(0.2)
            raised = pool.submit(
                chat, "gateway-a", slow, "LD1:bg", headers={"X-Eugene-Band": "interactive"}
            )
            time.sleep(0.2)
            plain = pool.submit(chat, "gateway-a", fast, "LD1:int")
            assert [f.result().status_code for f in (*fills, raised, plain)] == [200] * 4
        order = [t for t in engine_stats()["order"] if t in ("LD1:bg", "LD1:int")]
        assert order == ["LD1:int", "LD1:bg"], engine_stats()["order"]
        [background] = keyed("gateway-a", "Background", 1)
        assert background["band"] == "background", background
        ok("4. a background key waits behind interactive, and its X-Eugene-Band: interactive is ignored")

        # --- 5: the line's wait ends in queue_timeout on both doors ------------
        good("gateway-a", "PATCH", "/v1/config", operator, json={"queueWaitSeconds": 5})
        answer_seconds(9)
        probe = mint("Probe", maxConcurrentRequests=8, requestsPerMinute=1000)
        with ThreadPoolExecutor(6) as pool:
            holds = [pool.submit(chat, "gateway-a", fast, f"LD1:long-{n}") for n in range(2)]
            time.sleep(0.5)
            whole = pool.submit(chat, "gateway-a", probe, "LD1:p1")
            streamed_probe = pool.submit(chat, "gateway-a", probe, "LD1:p2", stream=True)
            anthropic_whole = pool.submit(messages, "gateway-a", probe, "LD1:p3")
            anthropic_streamed = pool.submit(messages, "gateway-a", probe, "LD1:p4", stream=True)
            refused = whole.result()
            assert refused.status_code == 503, refused.text
            assert refused.headers["X-Eugene-Refusal-Reason"] == "queue_timeout"
            assert refused.json()["error"]["code"] == "queue_timeout"
            assert "Waited 5 s for room on m on tower" in refused.json()["error"]["message"]
            frames = streamed_probe.result()
            assert frames.status_code == 200 and '"queue_timeout"' in frames.text, frames.text
            assert "Retry after 10 s." in frames.text
            message = anthropic_whole.result()
            assert message.status_code == 503 and message.json()["error"]["type"] == "overloaded_error"
            event = anthropic_streamed.result()
            assert "event: error" in event.text and "overloaded_error" in event.text, event.text
            assert "Waited 5 s for room" in event.text
            assert [f.result().status_code for f in holds] == [200, 200]
        good("gateway-a", "PATCH", "/v1/config", operator, json={"queueWaitSeconds": 60})
        answer_seconds(ANSWER_SECONDS)
        ok("5. a request that waited 5 s is refused queue_timeout on the OpenAI and Anthropic doors, whole and streamed")

        # --- 6: a starting runtime is waited for -------------------------------
        sweep.wait(
            lambda: any(
                m["id"] == WAKE
                for m in call("gateway-a", "GET", "/v1/models", fast).json().get("data", [])
            ),
            "the on-demand model is listed",
            seconds=30,
        )
        with ThreadPoolExecutor(4) as pool:
            woken = [pool.submit(chat, "gateway-a", fast, "LD1:w0", model=WAKE)]
            sweep.wait(
                lambda: next(
                    r
                    for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
                    if r["name"] == "rw"
                )["status"]
                in ("starting", "loading"),
                "the on-demand runtime is starting",
            )
            time.sleep(1.5)  # gateway-a's table has seen it starting
            woken += [
                pool.submit(chat, "gateway-a", fast, f"LD1:w{n}", model=WAKE) for n in (1, 2, 3)
            ]
            statuses = [f.result().status_code for f in woken]
        assert statuses == [200] * 4, [f.result().text for f in woken]
        ok("6. four requests that met a starting runtime were all served, none a 503")

        # --- 7: two gateways share one key ------------------------------------
        shared = mint("Shared", maxConcurrentRequests=2, requestsPerMinute=1000)
        engine_reset()
        with ThreadPoolExecutor(3) as pool:
            on_a = [pool.submit(chat, "gateway-a", shared, f"LD1:a{n}") for n in range(2)]
            time.sleep(0.5)
            began = time.perf_counter()
            on_b = pool.submit(chat, "gateway-b", shared, "LD1:b")
            assert [f.result().status_code for f in on_a] == [200, 200]
            released = time.perf_counter()
            answer = on_b.result()
            assert answer.status_code == 200, answer.text
        assert engine_stats()["most"] <= 2, engine_stats()
        tail = time.perf_counter() - released
        assert tail <= ANSWER_SECONDS + 2.0, f"gateway-b's waiter left {tail:.2f} s after A released"
        assert time.perf_counter() - began >= 1.0, "gateway-b's request waited for A's lease"
        ok("7. two gateways sharing one key: the engine saw at most 2, and B's waiter left when A released")

        # --- 8: a client that disconnects frees its place at once ---------------
        def waiting(gateway: str) -> int:
            queue = good(gateway, "GET", "/v1/metrics", operator).get("queue") or []
            return sum(sum(q["waiting"].values()) for q in queue)

        with ThreadPoolExecutor(3) as pool:
            hold = [pool.submit(chat, "gateway-a", two, f"LD1:hold{n}") for n in range(2)]
            time.sleep(0.4)
            with httpx.Client(timeout=1.0, trust_env=False) as impatient:
                try:
                    impatient.post(
                        url("gateway-a") + "/v1/chat/completions",
                        headers={"Authorization": "Bearer " + two},
                        json={"model": MODEL, "messages": [{"role": "user", "content": "LD1:gone"}]},
                    )
                    raise AssertionError("the impatient request was answered while it waited")
                except httpx.ReadTimeout:
                    pass
            gone_at = time.perf_counter()
            sweep.wait(lambda: waiting("gateway-a") == 0, "the place was freed", seconds=1.0)
            assert time.perf_counter() - gone_at < 1.0
            assert [f.result().status_code for f in hold] == [200, 200]
        assert "LD1:gone" not in engine_stats()["order"]
        ok("8. a client that disconnected while waiting freed its place at once")

        # --- 9: a gateway stopped with waiters refuses them, and stops ---------
        stopper = mint("Stopper", maxConcurrentRequests=8, requestsPerMinute=1000)
        answer_seconds(4)
        with ThreadPoolExecutor(5) as pool:
            running = [pool.submit(chat, "gateway-b", stopper, f"LD1:run{n}") for n in range(2)]
            time.sleep(0.5)
            waiters = [pool.submit(chat, "gateway-b", stopper, f"LD1:wait{n}") for n in range(2)]
            sweep.wait(lambda: waiting("gateway-b") == 2, "two wait on gateway-b")
            process = processes.pop("gateway-b")
            stopped = time.perf_counter()
            process.send_signal(signal.SIGTERM)
            for waiter in waiters:
                answer = waiter.result(timeout=10)
                assert answer.status_code == 503, answer.text
                assert answer.json()["error"]["code"] == "shutting_down"
                assert answer.headers["X-Eugene-Refusal-Reason"] == "shutting_down"
            assert time.perf_counter() - stopped < 3.0, "the waiters were refused at once"
            process.wait(timeout=15)
            assert time.perf_counter() - stopped < 15.0
            for run in running:
                try:
                    run.result(timeout=15)
                except httpx.HTTPError:
                    pass  # a running request is row 13's to drain; this row refuses waiters
        answer_seconds(ANSWER_SECONDS)
        ok("9. a gateway stopped with waiters refused them shutting_down and stopped")

        assert len(passed) == 10, passed
        print(f"ALL {len(passed)} CHECKS PASSED", flush=True)
    finally:
        for name, process in list(processes.items()):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--engine", action="store_true")
    args, _ = parser.parse_known_args()
    if args.engine:
        engine()
    elif args.serve in ("gateway-a", "gateway-b"):
        serve_gateway(args.directory, args.port)
    elif args.serve:
        load("a6-local-only-acceptance.py").serve(
            "local" if args.serve in ("local", "wake") else args.serve, args.directory, args.port
        )
    else:
        if os.name == "nt":
            raise SystemExit("Linux only: the stand-in engine is an executable script.")
        root = HERE.parents[1] / ".codex-tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ld1-", dir=root) as tmp:
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
