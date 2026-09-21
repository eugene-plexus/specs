"""Isolated real gateway/drivers plus counting HTTP and CLI failure fixtures.

No installed service, GPU, subscription CLI or external provider is contacted.
Signed authority/policy coverage is supplied by the companion A5/A6 instruments.
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
from fastapi import Request


def serve(kind, directory, ports):
    import uvicorn

    def url(name):
        return f"http://127.0.0.1:{ports[name]}"

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()
        state = {
            name: {"mode": "ok", "calls": 0, "accepted": 0, "cancelled": 0, "ids": []}
            for name in ("primary", "backup")
        }

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return state

        @app.post("/mode/{name}/{mode}")
        async def mode(name: str, mode: str):
            state[name]["mode"] = mode
            return {}

        @app.get("/v1/components")
        async def components():
            return {
                "components": [
                    {"name": name, "kind": "inference-driver", "url": url(name)}
                    for name in ("primary", "backup", "cli")
                ]
            }

        @app.get("/v1/runtimes")
        async def runtimes():
            return {"runtimes": []}

        @app.get("/v1/node")
        async def node():
            return {"enrolled": False}

        @app.get("/{name}/v1/models")
        async def models(name: str):
            return {"data": [{"id": name}]}

        @app.get("/{name}/props")
        async def props(name: str):
            return {"default_generation_settings": {"n_ctx": 4096}}

        @app.post("/{name}/v1/{operation:path}")
        async def inference(name: str, operation: str, request: Request):
            body = await request.json()
            record = state[name]
            application = "A6B_INPUT" in json.dumps(body)
            mode = record["mode"] if application else "ok"
            if application:
                record["calls"] += 1
                record["ids"].append(request.headers.get("x-request-id"))
                if mode != "overload":
                    record["accepted"] += 1
            if mode == "overload":
                return JSONResponse(
                    {"error": {"message": "capacity refusal"}},
                    status_code=429,
                    headers={"Retry-After": "3"},
                )
            if mode == "ambiguous":
                return JSONResponse(
                    {"error": {"message": "acted then failed"}}, status_code=503
                )
            if mode == "malformed":
                return JSONResponse({"wrong": "accepted but lost result"})
            if mode == "hang":
                while not await request.is_disconnected():
                    await asyncio.sleep(0.02)
                record["cancelled"] += 1
                return {}
            usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
            if operation == "embeddings":
                return JSONResponse(
                    {"error": {"message": "chat-only fixture"}}, status_code=400
                )
            if body.get("stream"):

                async def stream():
                    delta = {
                        "content": "primary-only"
                        if name == "primary"
                        else "backup-only"
                    }
                    if mode == "partial-tool":
                        delta = {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "act", "arguments": "{"},
                                }
                            ]
                        }
                    yield (
                        "data: "
                        + json.dumps({"choices": [{"index": 0, "delta": delta}]})
                        + "\n\n"
                    )
                    if mode in ("partial-text", "partial-tool"):
                        return
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "choices": [
                                    {"index": 0, "delta": {}, "finish_reason": "stop"}
                                ],
                                "usage": usage,
                            }
                        )
                        + "\n\n"
                    )
                    yield "data: [DONE]\n\n"

                return StreamingResponse(stream(), media_type="text/event-stream")
            return {
                "model": name,
                "choices": [
                    {
                        "message": {"role": "assistant", "content": name + "-only"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }
    elif kind == "gateway":
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings

        app = create_app(
            Settings(
                config_file=directory / "gateway.yaml",
                agent_url=url("fixture"),
                metrics_file=directory / "metrics.sqlite3",
            )
        )
    else:
        import eugene_plexus_inference_driver.app as driver_app
        from eugene_plexus_inference_driver.settings import Settings

        if kind == "cli":
            from eugene_plexus_inference_driver.engines.codex_cli import CodexCliEngine

            engine = CodexCliEngine()
            effect = directory / "effect.txt"
            code = "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text(p.read_text()+'acted\\n' if p.exists() else 'acted\\n'); sys.exit(2)"
            engine._build_argv = lambda prompt: [
                sys.executable,
                "-c",
                code,
                str(effect),
            ]
            driver_app.build_engine = lambda *args, **kwargs: engine
        app = driver_app.create_app(
            Settings(config_file=directory / (kind + ".yaml"), agent_url=url("fixture"))
        )
    uvicorn.run(
        app, host="127.0.0.1", port=ports[kind], log_level="error", access_log=False
    )


def exercise(directory):
    names = ("fixture", "primary", "backup", "cli", "gateway")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(zip(names, [sock.getsockname()[1] for sock in sockets]))
    for sock in sockets:
        sock.close()
    processes, logs = {}, []
    client = httpx.Client(timeout=8, trust_env=False)

    def url(name):
        return f"http://127.0.0.1:{ports[name]}"

    def wait(check, seconds=15):
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise AssertionError("condition timed out")

    def start(name):
        log = (directory / (name + ".log")).open("ab")
        logs.append(log)
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")
        }
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                name,
                "--directory",
                str(directory),
                "--ports",
                json.dumps(ports),
            ],
            cwd=directory,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: client.get(url(name) + "/healthz").status_code == 200)

    def stop(name):
        proc = processes.pop(name, None)
        if proc:
            proc.terminate()
            try:
                proc.wait(8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)

    def mode(value):
        client.post(url("fixture") + "/mode/primary/" + value).raise_for_status()

    def stats():
        return client.get(url("fixture") + "/stats").json()

    def chat(model="alias", stream=False, **extra):
        return client.post(
            url("gateway") + "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "A6B_INPUT"}],
                "stream": stream,
                **extra,
            },
        )

    def reset_gateway():
        stop("gateway")
        start("gateway")

    try:
        for name in ("primary", "backup", "cli"):
            (directory / (name + ".yaml")).write_text(
                yaml.safe_dump(
                    {
                        "provider": "openai_compat_custom",
                        "modelId": name,
                        "baseUrl": url("fixture") + "/" + name,
                        "backendLocality": "local",
                    }
                ),
                encoding="utf-8",
            )
        (directory / "gateway.yaml").write_text(
            yaml.safe_dump(
                {
                    "requestTimeoutSeconds": 1,
                    "routingRefreshSeconds": 3600,
                    "modelSlots": [
                        {"model": "alias", "targets": ["primary", "backup"]},
                        {"model": "cli-alias", "targets": ["cli", "backup"]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        for name in names:
            start(name)
        initial = chat()
        assert initial.status_code == 200, initial.text
        mode("overload")
        before = stats()
        response = chat()
        assert response.status_code == 200 and "backup-only" in response.text, (
            response.text
        )
        after = stats()
        assert after["primary"]["accepted"] == before["primary"]["accepted"]
        trace = response.headers["x-request-id"]
        assert after["primary"]["ids"][-1] == after["backup"]["ids"][-1] == trace
        for _ in range(3):
            initial = chat()
        assert initial.status_code == 200, initial.text
        assert stats()["primary"]["calls"] == after["primary"]["calls"]
        mode("ok")
        time.sleep(3.1)
        count = stats()["primary"]["calls"]
        assert "primary-only" in chat().text
        assert "backup-only" in chat().text
        assert stats()["primary"]["calls"] == count + 1
        time.sleep(1.1)
        assert "primary-only" in chat().text
        assert "primary-only" in chat().text
        print(
            "PASS explicit overload, request-ID continuity, cooldown and controlled recovery",
            flush=True,
        )

        for failure in ("ambiguous", "malformed", "partial-text", "partial-tool"):
            mode(failure)
            reset_gateway()
            before = stats()
            response = chat(stream=failure.startswith("partial"))
            assert response.status_code == (
                200 if failure.startswith("partial") else 502
            ), response.text
            assert (
                "error" in response.text.lower() and "backup-only" not in response.text
            )
            assert stats()["backup"]["calls"] == before["backup"]["calls"]
            assert stats()["primary"]["accepted"] == before["primary"]["accepted"] + 1
        print(
            "PASS accepted-but-failed responses and partial text/tool streams are never replayed",
            flush=True,
        )

        mode("ok")
        reset_gateway()
        before = stats()["backup"]["calls"]
        response = chat("cli-alias")
        assert response.status_code == 502 and "unknown" in response.text.lower(), (
            response.text
        )
        assert (directory / "effect.txt").read_text().splitlines() == ["acted"]
        assert stats()["backup"]["calls"] == before
        print(
            "PASS CLI performed an action before failure; fallback count stayed zero",
            flush=True,
        )

        mode("hang")
        reset_gateway()
        before = stats()
        began = time.perf_counter()
        response = chat()
        assert response.status_code == 504 and time.perf_counter() - began < 3, (
            response.text
        )
        wait(lambda: stats()["primary"]["cancelled"] > before["primary"]["cancelled"])
        assert stats()["backup"]["calls"] == before["backup"]["calls"]
        print(
            "PASS total deadline cancels HTTP work without starting fallback",
            flush=True,
        )

        # Disconnect after the provider accepts the body, while no response exists.
        reset_gateway()
        before = stats()["primary"]["cancelled"]
        try:
            client.post(
                url("gateway") + "/v1/chat/completions",
                json={
                    "model": "alias",
                    "messages": [{"role": "user", "content": "A6B_INPUT"}],
                },
                timeout=0.2,
            )
            raise AssertionError("fixture should still be working")
        except httpx.ReadTimeout:
            pass
        wait(lambda: stats()["primary"]["cancelled"] > before)
        print("PASS caller disconnect cancels the driver's owned HTTP call", flush=True)

        mode("ok")
        reset_gateway()
        configuration = yaml.safe_load((directory / "gateway.yaml").read_text())
        configuration["requestTimeoutSeconds"] = 10
        (directory / "gateway.yaml").write_text(yaml.safe_dump(configuration))
        reset_gateway()
        stop("primary")
        response = chat()
        assert response.status_code == 200 and "backup-only" in response.text, (
            response.text
        )
        start("primary")
        wait(
            lambda: any(
                r.get("requestId") == response.headers["x-request-id"]
                for r in client.get(url("gateway") + "/v1/metrics/requests").json()[
                    "requests"
                ]
            )
        )
        rows = client.get(url("gateway") + "/v1/metrics/requests").json()["requests"]
        row = next(
            r for r in rows if r.get("requestId") == response.headers["x-request-id"]
        )
        assert row["elapsedMs"] >= row["totalMs"]
        assert row["tries"][0]["retryDisposition"] == "safe"
        assert row["tries"][0]["usageKnown"] is False
        assert row["tries"][1]["usageKnown"] is True
        assert any(
            r["outcome"] == "error"
            and any(t.get("retryDisposition") == "indeterminate" for t in r["tries"])
            for r in rows
        )
        print(
            "PASS connection refusal rescues safely; retained usage and uncertain attempts survive restarts",
            flush=True,
        )
        (directory / "result.json").write_text(
            json.dumps({"passed": True, "stats": stats()}, indent=2)
        )
    finally:
        for name in reversed(list(processes)):
            stop(name)
        client.close()
        for log in logs:
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--ports")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, json.loads(args.ports))
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-a6b-acceptance-"))
        print("Evidence:", directory, flush=True)
        exercise(directory)
