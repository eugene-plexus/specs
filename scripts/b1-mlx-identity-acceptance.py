"""B1: the model identity split, through real gateway and driver processes.

The MLX shape without a Mac: two backend fixtures that both answer ONLY
to upstream's `default_model` sentinel (the one thing `mlx_lm.server`
resolves besides an absolute path), fronted by REAL inference-driver
processes advertising two different public aliases, joined by a REAL
gateway across a REAL two-node install (control + two enrolled agents).
**Every backend here is a fixture and the results are simulated MLX** —
the engine adapter itself is exercised by the agent's own suite, and the
physical Apple silicon checks stay pending (docs/design/mlx-engine.md).

What this run proves that no unit test can: the identity split holds
across process boundaries — the sentinel never leaks into a public model
list or a response, two aliases over one sentinel reach the right
backend in streaming and non-streaming modes, replicas of one alias on
two nodes stay one model, scopes and discovery filter on the public
alias, and a pre-split configuration (no upstreamModelId) still works
byte-identically.

Safe beside a live install: ephemeral ports, ambient EUGENE_PLEXUS_*
cleared, teardown by pid, everything under a temp directory.
"""

from __future__ import annotations

import argparse
import base64
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
import yaml

# At module level, not inside `serve`: `from __future__ import annotations`
# makes every annotation a string, and FastAPI resolves them against the
# handler's GLOBALS — a Request imported inside a function is invisible
# there, and the parameter silently degrades to a required query param.
from fastapi import Request  # noqa: E402

SENTINEL = "default_model"
FAKE_MODEL_PATH = "/Users/nobody/models/mlx-community/Qwen3-0.6B-4bit"


def component_python(repo: str, env_override: str) -> str:
    """The interpreter a component's process runs under.

    The gateway and the driver have dependencies (Pillow, for image
    content parts) that the agent's venv does not carry, so one
    interpreter cannot run every component the way the earlier A-series
    harnesses assumed. Default to the sibling checkout's venv;
    `EP_GATEWAY_PYTHON` / `EP_DRIVER_PYTHON` override.
    """
    override = os.environ.get(env_override)
    if override:
        return override
    root = Path(__file__).resolve().parents[2] / repo / ".venv"
    candidate = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not candidate.is_file():
        raise SystemExit(
            f"no interpreter at {candidate}; set {env_override} to a Python with "
            f"the {repo} package installed"
        )
    return str(candidate)


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml",
                default_topology=False,
                bind_port=port,
            )
        )
    elif kind == "gateway":
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(
            settings=Settings(
                config_file=directory / "gateway.yaml",
                metrics_file=directory / "metrics.sqlite3",
                **bootstrap,
            )
        )
    elif kind == "driver":
        from eugene_plexus_inference_driver.app import create_app
        from eugene_plexus_inference_driver.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(
            Settings(config_file=directory / "driver.yaml", **bootstrap)
        )
    elif kind == "mlxstub":
        # A simulated mlx_lm.server, shaped by the v0.31.3 claims: /health
        # is a hardcoded 200 ok, /v1/models publishes an absolute path,
        # and a completion resolves ONLY the name in `expected.txt`
        # (default_model for the MLX-shaped stubs; a plain alias for the
        # pre-split control case). Everything else is a served 400 and a
        # counted violation.
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()
        expected = (directory / "expected.txt").read_text(encoding="utf-8").strip()
        answer = (directory / "answer.txt").read_text(encoding="utf-8").strip()
        stats = {"served": 0, "violations": 0}

        @app.get("/healthz")
        async def harness_health():
            return {}

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        @app.get("/stats")
        async def stub_stats():
            return stats

        @app.get("/v1/models")
        async def models():
            return {
                "object": "list",
                "data": [{"id": FAKE_MODEL_PATH, "object": "model", "created": 0}],
            }

        @app.post("/v1/chat/completions")
        async def completions(request: Request):
            body = await request.json()
            if body.get("model") != expected:
                stats["violations"] += 1
                return JSONResponse(
                    {"error": f"model {body.get('model')!r} not found"}, status_code=400
                )
            stats["served"] += 1
            if body.get("stream"):

                def frames():
                    def chunk(delta, finish=None):
                        return (
                            "data: "
                            + json.dumps(
                                {
                                    "id": "chatcmpl-stub",
                                    "object": "chat.completion.chunk",
                                    "model": expected,
                                    "choices": [
                                        {"index": 0, "delta": delta, "finish_reason": finish}
                                    ],
                                }
                            )
                            + "\n\n"
                        )

                    yield chunk({"role": "assistant"})
                    yield chunk({"content": answer[: len(answer) // 2]})
                    yield chunk({"content": answer[len(answer) // 2 :]}, finish="stop")
                    yield "data: [DONE]\n\n"

                return StreamingResponse(frames(), media_type="text/event-stream")
            return {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 0,
                "model": expected,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": answer},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
            }
    else:
        raise SystemExit(f"unknown serve kind {kind!r}")

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(directory: Path) -> None:
    from cryptography.hazmat.primitives import serialization

    from eugene_plexus_agent import security

    passed = 0

    def ok(label: str) -> None:
        nonlocal passed
        passed += 1
        print(f"PASS {passed:02d} {label}", flush=True)

    names = (
        "control",
        "agent-a",
        "agent-b",
        "gateway",
        "driver-a1",
        "driver-b1",
        "driver-b2",
        "driver-c",
        "stub-a",
        "stub-b",
        "stub-a2",
        "stub-c",
    )
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets)}
    for sock in sockets:
        sock.close()

    processes: dict[str, subprocess.Popen] = {}
    logs = []
    client = httpx.Client(timeout=15, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name: str, method: str, path: str, token: str | None = None, **kwargs):
        return client.request(
            method,
            url(name) + path,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            **kwargs,
        )

    def wait(check, label: str, seconds: float = 20) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise AssertionError("timed out: " + label)

    def start(name: str, kind: str) -> None:
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        interpreter = {
            "driver": lambda: component_python("inference-driver", "EP_DRIVER_PYTHON"),
            "gateway": lambda: component_python("gateway", "EP_GATEWAY_PYTHON"),
        }.get(kind, lambda: sys.executable)()
        processes[name] = subprocess.Popen(
            [
                interpreter,
                str(Path(__file__).resolve()),
                "--serve",
                kind,
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
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name + " healthz")

    def stop(name: str) -> None:
        process = processes.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def login(name: str) -> str:
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        assert response.status_code == 200, response.text
        return response.json()["sessionToken"]

    def stub_dir(name: str, expected: str, answer: str) -> None:
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / "expected.txt").write_text(expected, encoding="utf-8")
        (work / "answer.txt").write_text(answer, encoding="utf-8")

    def chat(token: str, model: str, **kwargs):
        return call(
            "gateway",
            "POST",
            "/v1/chat/completions",
            token,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "say the answer"}],
                **kwargs,
            },
        )

    def model_ids(token: str) -> set[str]:
        response = call("gateway", "GET", "/v1/models", token)
        assert response.status_code == 200, response.text
        return {m["id"] for m in response.json().get("data", [])}

    try:
        # --- the install: control + two enrolled agents -------------------
        start("control", "control")
        assert (
            call(
                "control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
            ).status_code
            == 204
        )
        operator = login("control")
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
                ),
                encoding="utf-8",
            )
            start(name, "agent")
            assert (
                call(
                    name, "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
                ).status_code
                == 200
            )
            local_operator = login(name)
            join = call("control", "POST", "/v1/nodes/join-token", operator).json()["token"]
            enrolled = call(
                name,
                "POST",
                "/v1/node/enroll",
                local_operator,
                json={"controlUrl": url("control"), "token": join, "name": name},
            )
            assert enrolled.status_code == 200, enrolled.text

        identity = yaml.safe_load((directory / "agent-a/node.yaml").read_text(encoding="utf-8"))
        private = base64.b64decode(identity["signingKey"])
        public = (
            serialization.load_pem_private_key(private, password=None)
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        verify_key = base64.b64encode(public).decode()

        # --- four simulated backends, four REAL drivers -------------------
        # a1/b1/a2 are MLX-shaped: they resolve only the sentinel. c is
        # the pre-split control case: no upstreamModelId, the backend
        # resolves the public alias itself.
        stub_dir("stub-a", SENTINEL, "answer from model-a")
        stub_dir("stub-a2", SENTINEL, "answer from model-a")
        stub_dir("stub-b", SENTINEL, "answer from model-b")
        stub_dir("stub-c", "alias-c", "answer from model-c")
        for stub in ("stub-a", "stub-b", "stub-a2", "stub-c"):
            start(stub, "mlxstub")

        def driver_dir(name: str, stub: str, alias: str, upstream: str | None) -> None:
            work = directory / name
            work.mkdir(exist_ok=True)
            config = {
                "provider": "openai_compat_custom",
                "baseUrl": url(stub),
                "modelId": alias,
                "backendLocality": "local",
            }
            if upstream is not None:
                config["upstreamModelId"] = upstream
            (work / "driver.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            (work / "bootstrap.json").write_text(
                json.dumps({"auth_verify_key": verify_key}), encoding="utf-8"
            )
            start(name, "driver")

        driver_dir("driver-a1", "stub-a", "alias-a", SENTINEL)
        driver_dir("driver-b1", "stub-b", "alias-b", SENTINEL)
        driver_dir("driver-c", "stub-c", "alias-c", None)

        def declare(agent: str, driver: str) -> None:
            response = call(
                agent,
                "POST",
                "/v1/components",
                operator,
                json={"name": driver, "kind": "inference-driver", "url": url(driver)},
            )
            assert response.status_code == 201, response.text

        declare("agent-a", "driver-a1")
        declare("agent-a", "driver-c")
        declare("agent-b", "driver-b1")

        # --- the gateway, finding the control root through its agent ------
        work = directory / "gateway"
        work.mkdir(exist_ok=True)
        (work / "bootstrap.json").write_text(
            json.dumps(
                {
                    "agent_url": url("agent-a"),
                    "auth_verify_key": verify_key,
                    "service_token": security.issue_service_token(
                        signing_key=private, kind="gateway"
                    ),
                }
            ),
            encoding="utf-8",
        )
        (work / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        start("gateway", "gateway")

        # --- 1: the driver advertises both halves of the split ------------
        info = call("driver-a1", "GET", "/v1/info", operator)
        assert info.status_code == 200, info.text
        body = info.json()
        assert body["modelId"] == "alias-a", body
        assert body["upstreamModelId"] == SENTINEL, body
        plain = call("driver-c", "GET", "/v1/info", operator).json()
        assert plain["modelId"] == "alias-c", plain
        assert plain.get("upstreamModelId") in (None, ""), plain
        ok("a real driver advertises modelId=alias and upstreamModelId=sentinel on /v1/info")

        # --- 2: the public model list is aliases, never the sentinel ------
        wait(
            lambda: model_ids(operator) == {"alias-a", "alias-b", "alias-c"},
            "three aliases routable across two nodes",
            seconds=30,
        )
        listing = call("gateway", "GET", "/v1/models", operator).text
        assert SENTINEL not in listing, listing
        assert FAKE_MODEL_PATH not in listing, listing
        ok("the model list is the three public aliases; sentinel and absolute path appear nowhere")

        # --- 3/4: two aliases over one sentinel reach the right backend ---
        response = chat(operator, "alias-a")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["choices"][0]["message"]["content"] == "answer from model-a", body
        assert body["model"] == "alias-a", body
        ok("alias-a serves from its own backend and the response names alias-a")

        response = chat(operator, "alias-b")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["choices"][0]["message"]["content"] == "answer from model-b", body
        assert body["model"] == "alias-b", body
        ok("alias-b serves from the OTHER backend behind the same sentinel, on the other node")

        # --- 5: streaming keeps the public identity on every frame --------
        collected: list[dict] = []
        with client.stream(
            "POST",
            url("gateway") + "/v1/chat/completions",
            headers={"Authorization": f"Bearer {operator}"},
            json={
                "model": "alias-b",
                "stream": True,
                "messages": [{"role": "user", "content": "say the answer"}],
            },
        ) as stream:
            assert stream.status_code == 200
            for line in stream.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                collected.append(json.loads(line[len("data: ") :]))
        text = "".join(
            c["choices"][0]["delta"].get("content", "")
            for c in collected
            if c.get("choices")
        )
        assert text == "answer from model-b", text
        stream_models = {c.get("model") for c in collected}
        assert stream_models == {"alias-b"}, stream_models
        ok("a streamed reply assembles correctly and every frame names the public alias")

        # --- 6: asking for the backend's own names is a 404 ---------------
        assert chat(operator, SENTINEL).status_code == 404
        assert chat(operator, FAKE_MODEL_PATH).status_code == 404
        ok("the sentinel and the absolute path are not models anyone can select")

        # --- 7: replicas of one alias on two nodes stay one model ---------
        driver_dir("driver-b2", "stub-a2", "alias-a", SENTINEL)
        declare("agent-b", "driver-b2")

        def replica_ready() -> bool:
            served = call("stub-a2", "GET", "/stats").json()["served"]
            if served > 0:
                return True
            chat(operator, "alias-a")
            return False

        wait(replica_ready, "second replica of alias-a takes traffic", seconds=30)
        assert model_ids(operator) == {"alias-a", "alias-b", "alias-c"}
        served_a = call("stub-a", "GET", "/stats").json()["served"]
        served_a2 = call("stub-a2", "GET", "/stats").json()["served"]
        assert served_a >= 1 and served_a2 >= 1, (served_a, served_a2)
        ok("alias-a on two nodes is one model with two balanced backends, not two models")

        # --- 8: a pre-split configuration still works ----------------------
        response = chat(operator, "alias-c")
        assert response.status_code == 200, response.text
        assert response.json()["choices"][0]["message"]["content"] == "answer from model-c"
        stats_c = call("stub-c", "GET", "/stats").json()
        assert stats_c["served"] >= 1 and stats_c["violations"] == 0, stats_c
        ok("a driver with no upstreamModelId still sends its public modelId verbatim")

        # --- 9: scopes and discovery filter on the public alias -----------
        minted = call(
            "agent-a",
            "POST",
            "/v1/auth/client-keys",
            operator,
            json={"name": "B1 scoped", "limits": {"allowedModels": ["alias-a"]}},
        )
        assert minted.status_code == 201, minted.text
        key = minted.json()["token"]
        wait(
            lambda: model_ids(key) == {"alias-a"},
            "scoped discovery settles",
            seconds=20,
        )
        refused = chat(key, "alias-b")
        assert refused.status_code == 403, refused.text
        allowed = chat(key, "alias-a")
        assert allowed.status_code == 200, allowed.text
        ok("a client key scoped to alias-a sees only it, is refused alias-b, and serves alias-a")

        # --- 10: a restarted driver process comes back routable -----------
        stop("driver-b1")
        wait(
            lambda: chat(operator, "alias-b").status_code in (404, 502, 503),
            "alias-b loses its only backend",
            seconds=30,
        )
        start("driver-b1", "driver")
        wait(
            lambda: chat(operator, "alias-b").status_code == 200,
            "alias-b routable again after the driver restart",
            seconds=30,
        )
        ok("alias-b survives its driver process being stopped and started")

        # --- 11: the wire never carried anything but the expected name ----
        for stub in ("stub-a", "stub-b", "stub-a2", "stub-c"):
            stats = call(stub, "GET", "/stats").json()
            assert stats["violations"] == 0, (stub, stats)
        ok("every backend was only ever asked for the one name it resolves — zero violations")

        print(f"\nALL {passed} CHECKS PASSED", flush=True)
    finally:
        for name in list(processes):
            stop(name)
        for log in logs:
            log.close()
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, Path(args.directory), args.port)
        return
    if args.directory:
        # Debugging: keep the workdirs (and their process logs) around.
        work = Path(args.directory)
        work.mkdir(parents=True, exist_ok=True)
        exercise(work)
        return
    with tempfile.TemporaryDirectory(prefix="ep-b1-") as tmp:
        exercise(Path(tmp))


if __name__ == "__main__":
    main()
