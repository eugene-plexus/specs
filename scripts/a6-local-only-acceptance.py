"""A6: real signed root/agent/gateway/drivers, counting upstream HTTP fixture.

No live service, model or external provider is touched. Run in an environment
containing all five Python components. Logs and state stay in a temporary tree.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import io
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
        counts = {model: 0 for model in ("local", "cloud", "unknown", "embedding")}
        failures = set()

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return counts

        @app.post("/failure/{model}")
        async def failure(model: str, request: Request):
            enabled = (await request.json())["enabled"]
            failures.add(model) if enabled else failures.discard(model)
            return {}

        @app.get("/{model}/v1/models")
        async def models(model: str):
            return {"data": [{"id": model, "object": "model"}]}

        @app.get("/{model}/props")
        async def props(model: str):
            return {"default_generation_settings": {"n_ctx": 4096}}

        @app.post("/{model}/v1/{operation:path}")
        async def inference(model: str, operation: str, request: Request):
            body = await request.json()
            # Separate the driver's content-free, one-character capability
            # probe from application input. Never store the supplied content.
            if "A6_PRIVATE" in json.dumps(body):
                counts[model] += 1
            if model in failures:
                return JSONResponse(
                    {"error": {"message": "fixture refused before execution"}}, status_code=429
                )
            usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
            if operation == "embeddings":
                if model != "embedding":
                    return JSONResponse(
                        {"error": {"message": "not embedding"}}, status_code=400
                    )
                inputs = body["input"]
                return {
                    "model": model,
                    "data": [
                        {"index": i, "embedding": [0.1, 0.2]}
                        for i in range(len(inputs))
                    ],
                    "usage": usage,
                }
            if body.get("stream"):

                async def stream():
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "model": model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": "fixture-ok"},
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
                                "model": model,
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
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "fixture-ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }
    elif kind in ("local", "cloud", "unknown", "embedding"):
        from eugene_plexus_inference_driver.app import create_app
        from eugene_plexus_inference_driver.settings import Settings

        bootstrap = json.loads(
            (directory / "bootstrap.json").read_text(encoding="utf-8")
        )
        app = create_app(
            settings=Settings(config_file=directory / "driver.yaml", **bootstrap)
        )
    else:
        spec = importlib.util.spec_from_file_location(
            "a3_acceptance", Path(__file__).with_name("a3-client-keys-acceptance.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.serve(kind, directory, port)
        return
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(directory: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from eugene_plexus_agent import security
    from PIL import Image

    picture = io.BytesIO()
    Image.new("RGB", (8, 8), "purple").save(picture, format="PNG")
    image_url = "data:image/png;base64," + base64.b64encode(picture.getvalue()).decode()

    names = (
        "control",
        "agent",
        "gateway",
        "fixture",
        "local",
        "cloud",
        "unknown",
        "embedding",
    )
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(zip(names, [sock.getsockname()[1] for sock in sockets]))
    for sock in sockets:
        sock.close()
    processes = {}
    logs = []
    client = httpx.Client(timeout=10, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name):
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        return client.request(
            method,
            url(name) + path,
            headers={"Authorization": "Bearer " + token} if token else {},
            **kwargs,
        )

    def write(name, filename, data):
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(data) if filename.endswith("json") else yaml.safe_dump(data),
            encoding="utf-8",
        )

    def wait(check, label, seconds=20):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise AssertionError("timed out: " + label)

    def start(name):
        work = directory / name
        work.mkdir(exist_ok=True)
        output = (work / "process.log").open("ab")
        logs.append(output)
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
                str(work),
                "--port",
                str(ports[name]),
            ],
            cwd=work,
            env=env,
            stdout=output,
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
        response.raise_for_status()
        return response.json()["sessionToken"]

    try:
        start("control")
        call(
            "control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
        ).raise_for_status()
        operator = login("control")
        write(
            "agent",
            "agent.yaml",
            {
                "firstRunComplete": True,
                "advertiseUrl": url("agent"),
                "securityMode": "prompt_on_startup",
                "components": [],
            },
        )
        start("agent")
        call(
            "agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
        ).raise_for_status()
        local_operator = login("agent")
        join = call("control", "POST", "/v1/nodes/join-token", operator).json()["token"]
        call(
            "agent",
            "POST",
            "/v1/node/enroll",
            local_operator,
            json={"controlUrl": url("control"), "token": join, "name": "a6-agent"},
        ).raise_for_status()
        identity = yaml.safe_load(
            (directory / "agent/node.yaml").read_text(encoding="utf-8")
        )
        private = base64.b64decode(identity["signingKey"])
        public = (
            serialization.load_pem_private_key(private, password=None)
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        bootstrap = {
            "agent_url": url("agent"),
            "auth_verify_key": base64.b64encode(public).decode(),
        }
        start("fixture")
        for model, locality in (
            ("local", "local"),
            ("cloud", "external"),
            ("unknown", "unknown"),
            ("embedding", "local"),
        ):
            write(
                model,
                "bootstrap.json",
                {
                    **bootstrap,
                    "service_token": security.issue_service_token(
                        signing_key=private, kind="inference-driver"
                    ),
                },
            )
            write(
                model,
                "driver.yaml",
                {
                    "provider": "openai_compat_custom",
                    "modelId": model,
                    "baseUrl": url("fixture") + "/" + model,
                    "backendLocality": locality,
                },
            )
            start(model)
            call(
                "agent",
                "POST",
                "/v1/components",
                operator,
                json={
                    "name": model + "-driver",
                    "kind": "inference-driver",
                    "url": url(model),
                },
            ).raise_for_status()
        write(
            "gateway",
            "bootstrap.json",
            {
                **bootstrap,
                "service_token": security.issue_service_token(
                    signing_key=private, kind="gateway"
                ),
            },
        )
        write(
            "gateway",
            "gateway.yaml",
            {
                "routingRefreshSeconds": 3600,
                "modelSlots": [
                    {"model": "alias", "targets": ["local", "cloud", "unknown"]}
                ],
            },
        )
        start("gateway")

        def mint(local_only):
            response = call(
                "agent",
                "POST",
                "/v1/auth/client-keys",
                operator,
                json={
                    "name": "Protected" if local_only else "Unrestricted",
                    "limits": {"localOnly": local_only, "requestsPerMinute": 1000},
                },
            )
            response.raise_for_status()
            return response.json()["token"]

        protected, unrestricted = mint(True), mint(False)
        wait(
            lambda: (
                len(
                    call("gateway", "GET", "/v1/models", unrestricted)
                    .json()
                    .get("data", [])
                )
                == 5
            ),
            "all backends discovered",
        )
        models = call("gateway", "GET", "/v1/models", protected).json()["data"]
        assert {m["id"] for m in models} == {"alias", "local", "embedding"}
        message = [{"role": "user", "content": "A6_PRIVATE_PROMPT"}]
        for path, extra in (
            ("/v1/chat/completions", {}),
            ("/v1/chat/completions", {"stream": True}),
            ("/v1/messages", {"max_tokens": 8}),
            ("/v1/messages", {"max_tokens": 8, "stream": True}),
        ):
            response = call(
                "gateway",
                "POST",
                path,
                protected,
                json={"model": "alias", "messages": message, **extra},
            )
            assert response.status_code == 200, response.text
            assert "fixture-ok" in response.text
        response = call(
            "gateway",
            "POST",
            "/v1/embeddings",
            protected,
            json={"model": "embedding", "input": "A6_PRIVATE_INPUT"},
        )
        assert response.status_code == 200, response.text
        print(
            "PASS signed local-only key: discovery, both chat APIs, streams and embeddings",
            flush=True,
        )

        for model in ("cloud", "unknown"):
            for content in (
                "A6_PRIVATE_PROMPT",
                [
                    {"type": "text", "text": "A6_PRIVATE_IMAGE"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            ):
                response = call(
                    "gateway",
                    "POST",
                    "/v1/chat/completions",
                    protected,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": content}],
                    },
                )
                assert response.status_code == 403, response.text
                assert "A6_PRIVATE" not in response.text
        call(
            "fixture", "POST", "/failure/local", json={"enabled": True}
        ).raise_for_status()
        response = call(
            "gateway",
            "POST",
            "/v1/chat/completions",
            protected,
            json={"model": "alias", "messages": message},
        )
        assert response.status_code == 502, response.text
        counts = call("fixture", "GET", "/stats").json()
        assert counts["cloud"] == counts["unknown"] == 0
        response = call(
            "gateway",
            "POST",
            "/v1/chat/completions",
            unrestricted,
            json={"model": "alias", "messages": message},
        )
        assert response.status_code == 200, response.text
        assert call("fixture", "GET", "/stats").json()["cloud"] == 1
        print(
            "PASS zero external/unknown application requests through rejection and alias outage; permitted cloud fallback works",
            flush=True,
        )

        # Keep the gateway's old routing snapshot while replacing the driver's
        # active endpoint and trust classification on the same address.
        stop("local")
        write(
            "local",
            "driver.yaml",
            {
                "provider": "openai_compat_custom",
                "modelId": "local",
                "baseUrl": url("fixture") + "/cloud",
                "backendLocality": "external",
            },
        )
        start("local")
        response = call(
            "gateway",
            "POST",
            "/v1/chat/completions",
            protected,
            json={"model": "alias", "messages": message},
        )
        assert response.status_code == 403, response.text
        # Also bypass the gateway's metadata check: the real driver must refuse
        # the stale protected request before invoking its replacement endpoint.
        response = call(
            "local",
            "POST",
            "/v1/generate",
            operator,
            json={"messages": message, "localOnly": True},
        )
        assert response.status_code == 403, response.text
        final_counts = call("fixture", "GET", "/stats").json()
        assert final_counts["cloud"] == 1 and final_counts["unknown"] == 0
        (directory / "summary.json").write_text(
            json.dumps(final_counts, indent=2), encoding="utf-8"
        )
        print(
            "PASS stale routing and active-engine replacement preserve policy; no private content in refusals",
            flush=True,
        )
    finally:
        for name in reversed(list(processes)):
            stop(name)
        client.close()
        for output in logs:
            output.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-a6-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory)
