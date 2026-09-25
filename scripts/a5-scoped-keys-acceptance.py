"""A5: durable per-key limits across real control, agents and two gateways.

Only the model-serving HTTP backend is a counting fixture. No installed service,
model, external provider, or operator state is touched. Run with editable/pinned
agent, control and gateway packages in one Python environment.

Per-node token keys (2026-09-25, `docs/design/per-node-token-keys.md`). Both
agents enroll with the `gateway` grant, because each runs a gateway and
gateway-b must reach the drivers declared on agent-a's machine and the root's
node list. Each gateway is handed its own node's bundle, authority, recipient
and a token minted by that node's `NodeTrust` (A3's `gateway_bootstrap`), not
one node's key shared by both. Operator calls to an agent or a gateway use a
session from that machine's own agent login; the root's session only mints
join tokens and unlocks the root after its restart. No check was removed.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import yaml
from fastapi import Request


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()
        modes = {
            m: {"hold": False, "fail": False}
            for m in ("allowed", "excluded", "embedding")
        }
        counts = {m: 0 for m in modes}

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return counts

        @app.post("/mode/{model}")
        async def mode(model: str, request: Request):
            modes[model].update(await request.json())
            return modes[model]

        @app.get("/{model}/healthz")
        async def driver_health(model: str):
            return {"status": "ok"}

        @app.get("/{model}/v1/info")
        async def info(model: str):
            return {
                "backend": "openai_compat_http",
                "modelId": model,
                "capabilities": {"embeddings": model == "embedding", "streaming": True, "supportedSettings": ["maxTokens", "temperature", "topP", "seed", "stop", "tools", "toolChoice", "responseFormat"]},
            }

        @app.post("/{model}/v1/{operation:path}")
        async def generate(model: str, operation: str, request: Request):
            await request.body()
            counts[model] += 1
            if modes[model]["fail"]:
                return JSONResponse(
                    {"type": "about:blank", "title": "Fixture refusal before work", "status": 503, "retryDisposition": "safe"}, status_code=503
                )
            usage = {"promptTokens": 7, "completionTokens": 3, "totalTokens": 10}
            result = {
                "content": "fixture-ok",
                "modelId": model,
                "backend": "openai_compat_http",
                "finishReason": "stop",
                "usage": usage,
            }
            if operation == "generate/stream":

                async def stream():
                    yield 'event: token\ndata: {"text":"fixture"}\n\n'
                    while modes[model]["hold"]:
                        await asyncio.sleep(0.05)
                        yield ": waiting\n\n"
                    yield "event: done\ndata: " + json.dumps(result) + "\n\n"

                return StreamingResponse(stream(), media_type="text/event-stream")
            while modes[model]["hold"]:
                if await request.is_disconnected():
                    return JSONResponse({}, status_code=499)
                await asyncio.sleep(0.05)
            if operation == "embed":
                return {
                    "embeddings": [[0.1, 0.2]],
                    "modelId": model,
                    "backend": "openai_compat_http",
                    "usage": {"promptTokens": 7, "totalTokens": 7},
                }
            return result

        uvicorn.run(
            app, host="127.0.0.1", port=port, log_level="error", access_log=False
        )
    else:
        a3().serve(kind, directory, port)


def a3():
    spec = importlib.util.spec_from_file_location(
        "a3_acceptance", Path(__file__).with_name("a3-client-keys-acceptance.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exercise(directory: Path) -> None:
    for name in [k for k in os.environ if k.startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    from eugene_plexus_gateway.settings import Settings as GatewaySettings

    defaults = GatewaySettings()
    assert (
        defaults.client_key_refresh_seconds,
        defaults.client_key_timeout_seconds,
        defaults.client_key_max_age_seconds,
    ) == (15, 4, 60)
    names = ("control", "agent-a", "agent-b", "gateway-a", "gateway-b", "fixture")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets)}
    for sock in sockets:
        sock.close()
    processes = {}
    logs = []
    client = httpx.Client(timeout=8, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name):
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        return client.request(
            method,
            url(name) + path,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            **kwargs,
        )

    def wait(check, label, seconds=12):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise AssertionError("timed out: " + label)

    def start(name, kind=None):
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
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
                kind or name,
                "--directory",
                str(work),
                "--port",
                str(ports[name]),
            ],
            cwd=work,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    def stop(name):
        process = processes.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        assert response.status_code == 200, response.text
        return response.json()["sessionToken"]

    def status(name, token):
        return call(name, "GET", "/v1/models", token).status_code

    try:
        start("control")
        assert (
            call(
                "control",
                "POST",
                "/v1/auth/initialize",
                json={"passphrase": passphrase},
            ).status_code
            == 204
        )
        # Addressed to the root alone: good at the root, refused by every node.
        root_session = login("control")
        operator = {}
        for name in ("agent-a", "agent-b"):
            work = directory / name
            work.mkdir(exist_ok=True)
            (work / "agent.yaml").write_text(
                yaml.safe_dump(
                    {
                        "firstRunComplete": True,
                        "advertiseUrl": url(name),
                        "securityMode": "prompt_on_startup",
                        "components": [],
                    }
                )
            )
            start(name)
            assert (
                call(
                    name, "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
                ).status_code
                == 200
            )
            # Standalone until it enrolls: this session is the agent's own.
            standalone = login(name)
            join = call(
                "control",
                "POST",
                "/v1/nodes/join-token",
                root_session,
                json={"grants": ["gateway"]},
            )
            assert join.status_code == 201, join.text
            enrolled = call(
                name,
                "POST",
                "/v1/node/enroll",
                standalone,
                json={"controlUrl": url("control"), "token": join.json()["token"], "name": name},
            )
            assert enrolled.status_code == 200, enrolled.text
            # Signed in through the enrolled agent: addressed to this machine
            # and the root, so it opens this agent and this node's gateway.
            operator[name] = login(name)
        # Each gateway is on its agent's machine, so it takes that agent's session.
        operator["gateway-a"], operator["gateway-b"] = operator["agent-a"], operator["agent-b"]

        start("fixture")
        for model in ("allowed", "excluded", "embedding"):
            response = call(
                "agent-a",
                "POST",
                "/v1/components",
                operator["agent-a"],
                json={
                    "name": model + "-driver",
                    "kind": "inference-driver",
                    "url": url("fixture") + "/" + model,
                },
            )
            assert response.status_code == 201, response.text
        for gateway, agent in (("gateway-a", "agent-a"), ("gateway-b", "agent-b")):
            work = directory / gateway
            work.mkdir()
            (work / "bootstrap.json").write_text(
                json.dumps(a3().gateway_bootstrap(directory / agent, url(agent))),
                encoding="utf-8",
            )
            (work / "gateway.yaml").write_text(
                yaml.safe_dump(
                    {
                        "routingRefreshSeconds": 1,
                        "modelSlots": [
                            {"model": "alias", "targets": ["allowed", "excluded"]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            start(gateway)

        def mint(name, allowed, concurrency, rate):
            r = call(
                "agent-a",
                "POST",
                "/v1/auth/client-keys",
                operator["agent-a"],
                json={
                    "name": name,
                    "limits": {
                        "allowedModels": allowed,
                        "maxConcurrentRequests": concurrency,
                        "requestsPerMinute": rate,
                    },
                },
            )
            assert r.status_code == 201, r.text
            return r.json()

        a = mint("App A", ["alias", "allowed"], 1, 4)
        b = mint("App B", ["excluded", "embedding"], 2, 2)

        def chat(gateway, key, model="alias", **kwargs):
            return call(
                gateway,
                "POST",
                "/v1/chat/completions",
                key["token"],
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "A5_PRIVATE_PROMPT"}],
                    "user": "FORGED_USER",
                    **kwargs,
                },
            )

        def mode(model, **values):
            call("fixture", "POST", "/mode/" + model, json=values).raise_for_status()

        for gateway in ("gateway-a", "gateway-b"):
            wait(
                lambda: (
                    len(
                        call(gateway, "GET", "/v1/models", a["token"])
                        .json()
                        .get("data", [])
                    )
                    == 2
                ),
                "scoped discovery",
            )
            ma = call(gateway, "GET", "/v1/models", a["token"])
            mb = call(gateway, "GET", "/v1/models", b["token"])
            assert {m["id"] for m in ma.json()["data"]} == {"allowed", "alias"}
            assert {m["id"] for m in mb.json()["data"]} == {"excluded", "embedding"}
            assert "excluded" not in ma.text and "allowed" not in mb.text
            assert chat(gateway, a, "excluded").status_code == 403
            assert chat(gateway, b, "allowed").status_code == 403
        print(
            "PASS two keys have distinct filtered discovery and direct model permissions",
            flush=True,
        )
        mode("allowed", hold=True)
        stream_client = httpx.Client(timeout=8, trust_env=False)
        try:
            with stream_client.stream(
                "POST",
                url("gateway-a") + "/v1/chat/completions",
                headers={"Authorization": "Bearer " + a["token"]},
                json={
                    "model": "alias",
                    "stream": True,
                    "messages": [{"role": "user", "content": "A5_PRIVATE_PROMPT"}],
                },
            ) as response:
                assert response.status_code == 200, response.status_code
                lines = response.iter_lines()
                for line in lines:
                    if "fixture" in line:
                        break
                refused = chat("gateway-b", a)
                assert (
                    refused.status_code == 429
                    and int(refused.headers["Retry-After"]) > 0
                )
                # Another key has its own allowance, but cannot gain more by changing gateways.
                assert chat("gateway-b", b, "excluded", stream=True).status_code == 200
                embedded = call(
                    "gateway-a",
                    "POST",
                    "/v1/embeddings",
                    b["token"],
                    json={"model": "embedding", "input": "A5_PRIVATE_INPUT"},
                )
                assert embedded.status_code == 200, embedded.text
                assert chat("gateway-a", b, "excluded").status_code == 429
            mode("allowed", hold=False)
            wait(
                lambda: chat("gateway-b", a).status_code == 200,
                "disconnect frees shared slot",
            )
        finally:
            stream_client.close()
            mode("allowed", hold=False)
        print(
            "PASS streamed work occupies a shared slot; disconnect frees it; second key's rate spans gateways",
            flush=True,
        )
        before = call("fixture", "GET", "/stats").json()["excluded"]
        mode("allowed", fail=True)
        failed = chat("gateway-a", a)
        assert failed.status_code == 503, failed.text
        assert call("fixture", "GET", "/stats").json()["excluded"] == before
        # Same bearer, updated by an operator through the other agent.
        changed = call(
            "agent-b",
            "PUT",
            "/v1/auth/client-keys/" + a["key"]["id"] + "/limits",
            operator["agent-b"],
            json={
                "limits": {
                    "allowedModels": ["alias", "allowed", "excluded"],
                    "maxConcurrentRequests": 1,
                    "requestsPerMinute": 4,
                }
            },
        )
        assert changed.status_code == 200, changed.text
        assert chat("gateway-b", a).status_code == 200
        assert call("fixture", "GET", "/stats").json()["excluded"] == before + 1
        assert chat("gateway-a", a).status_code == 429
        print(
            "PASS excluded fallback never called; permitted fallback charges once; policy editing preserves rate",
            flush=True,
        )
        stop("control")
        for gateway in ("gateway-a", "gateway-b"):
            assert call(gateway, "GET", "/v1/models", a["token"]).status_code == 503
            assert chat(gateway, a).status_code == 503
            assert call(gateway, "GET", "/v1/config", operator[gateway]).status_code == 200
        start("control")
        # Unlocks the restarted root; the machines' own sessions stay valid.
        login("control")
        wait(
            lambda: (
                call("gateway-a", "GET", "/v1/models", a["token"]).status_code == 200
            ),
            "authority recovery",
        )
        assert chat("gateway-a", a).status_code == 429
        assert chat("gateway-b", b, "excluded").status_code == 429
        print(
            "PASS coordination outage fails closed, operator repair stays open, restart preserves both rates",
            flush=True,
        )
        totals = {}
        for gateway in ("gateway-a", "gateway-b"):

            def enough_metrics():
                r = call(gateway, "GET", "/v1/metrics/clients", operator[gateway])
                return r.status_code == 200 and len(r.json()["clients"]) == 2

            wait(enough_metrics, "usage persisted")
            report = call(gateway, "GET", "/v1/metrics/clients", operator[gateway]).json()
            history = call(
                gateway, "GET", "/v1/metrics/requests?limit=100", operator[gateway]
            )
            for row in report["clients"]:
                assert row["clientKeyId"] in (a["key"]["id"], b["key"]["id"])
                total = totals.setdefault(
                    row["clientKeyName"],
                    {
                        k: 0
                        for k in (
                            "requests",
                            "served",
                            "failed",
                            "attempts",
                            "promptTokens",
                            "completionTokens",
                            "incompleteUsageRequests",
                        )
                    },
                )
                for key in total:
                    total[key] += row[key]
            for secret in (
                a["token"],
                b["token"],
                "A5_PRIVATE_PROMPT",
                "A5_PRIVATE_INPUT",
                "FORGED_USER",
            ):
                assert secret not in json.dumps(report) + history.text
        assert totals["App A"]["served"] == 2 and totals["App A"]["failed"] >= 4
        assert (
            totals["App A"]["attempts"] >= 5
            and totals["App A"]["incompleteUsageRequests"] >= 2
        )
        assert totals["App B"]["served"] == 2 and totals["App B"]["promptTokens"] == 14
        (directory / "summary.json").write_text(
            json.dumps(totals, indent=2), encoding="utf-8"
        )
        print(
            "PASS attributable usage through fallback, streaming, embeddings, failures; no prompt or credential retained",
            flush=True,
        )
    finally:
        for name in list(processes):
            stop(name)
        client.close()
        for log in logs:
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-a5-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory)
