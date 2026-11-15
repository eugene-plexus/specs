"""Row 13, Linux CI: checked engine updates and the drains they need, through a
real root, agent, two drivers and a gateway.

The engine is a stand-in llama-server installed as three managed llama.cpp
builds in the agent's own engine store: b1 and b2 serve, b3 exits at start
("unknown tensor type"), as a build that cannot load a model does. Each build
answers `--version` with its own name, so the agent's `engineVersion` is the
build a runtime really runs. Every listener is an OS-assigned loopback port
(never 8079-8083), all state is in a temporary folder, and no ambient
`EUGENE_PLEXUS_*` variable reaches a child. Do not run this against a live
install.

Checks (design `docs/design/rows/row-13.md` §5, with Troy's answers of
2026-10-21: the numbers never block, a build that cannot run a model is not
used for it, one copy switches at once):
 1. two copies of a model on b1, updated to b2 one at a time: each leaves
    routing (`draining`), every stream open meanwhile finishes whole, and both
    end on b2, which is the build in use, with b1 kept for the way back;
 2. a build that cannot start any model is kept off: the runtimes start on the
    build in use again, and the update says why;
 3. a model with one copy switches at once ("Use b1 again", no download): the
    requests that arrive meanwhile wait in line, none is refused;
 4. the gateway's drain takes this machine's own agent token and nothing else
    of a component's;
 5. a gateway restart finishes the streams in flight, refuses new requests
    `shutting_down`, and exits 0.
"""

# No `from __future__ import annotations`: the stand-in's FastAPI routes import
# `Request` inside `engine_app`, and a string annotation of it does not resolve.
import argparse
import importlib.util
import json
import os
import secrets
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
MODEL = "m"
#: How long the stand-in takes over one answer unless told otherwise.
ANSWER_SECONDS = 3.0
WORDS = 8
GOOD_BUILDS = ("b1", "b2")
BAD_BUILD = "b3"
ENDED = {"done", "kept", "failed", "cancelled"}


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the stand-in llama-server -------------------------------------------------


def engine_app(alias: str, build: str) -> Any:
    import asyncio

    from fastapi import FastAPI, Request
    from fastapi.responses import PlainTextResponse, StreamingResponse

    app = FastAPI()
    slots = asyncio.Semaphore(2)
    state: dict[str, Any] = {"seconds": ANSWER_SECONDS}

    @app.get("/health")
    @app.get("/healthz")
    async def health() -> Any:
        return {"status": "ok"}

    @app.get("/props")
    async def props() -> Any:
        return {
            "default_generation_settings": {"n_ctx": 32768},
            "total_slots": 2,
            "build": build,
        }

    @app.get("/v1/models")
    async def models() -> Any:
        return {"object": "list", "data": [{"id": alias, "object": "model"}]}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> str:
        return "llamacpp:requests_processing 0\n"

    @app.post("/mode")
    async def mode(request: Request) -> Any:
        state["seconds"] = float((await request.json())["seconds"])
        return {}

    @app.post("/completion")
    async def completion(request: Request) -> Any:
        return {"content": "word word", "stop": True}

    @app.post("/v1/chat/completions")
    async def answer(request: Request) -> Any:
        body = await request.json()
        seconds = float(state["seconds"])
        usage = {
            "prompt_tokens": 12,
            "completion_tokens": WORDS,
            "total_tokens": 12 + WORDS,
        }

        def chunk(delta: dict[str, Any], finish: Any = None, **extra: Any) -> str:
            return (
                "data: "
                + json.dumps(
                    {
                        "id": "standin",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": alias,
                        "choices": [
                            {"index": 0, "delta": delta, "finish_reason": finish}
                        ],
                        **extra,
                    }
                )
                + "\n\n"
            )

        if body.get("stream"):

            async def stream() -> Any:
                async with slots:
                    for _ in range(WORDS):
                        yield chunk({"content": "word "})
                        await asyncio.sleep(seconds / WORDS)
                    yield chunk({}, "stop", usage=usage)
                    yield "data: [DONE]\n\n"

            return StreamingResponse(stream(), media_type="text/event-stream")
        async with slots:
            await asyncio.sleep(seconds / 4)
        return {
            "id": "standin",
            "object": "chat.completion",
            "created": 1,
            "model": alias,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "word " * WORDS},
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
    parser.add_argument("--build", default="b0")
    args, _ = parser.parse_known_args()
    import uvicorn

    uvicorn.run(
        engine_app(args.alias, args.build),
        host=args.host,
        port=args.port,
        log_level="error",
        access_log=False,
    )


def install_builds(engines: Path) -> None:
    """Three managed builds of the stand-in, as an install leaves them, and b1
    recorded as the build in use."""
    from eugene_plexus_agent._generated.models import EngineKind
    from eugene_plexus_agent.engines.acquisition import ManagedStore

    store = ManagedStore(engines, EngineKind.llama_cpp)
    for build in (*GOOD_BUILDS, BAD_BUILD):
        directory = store.build_dir(build)
        directory.mkdir(parents=True)
        binary = directory / "llama-server"
        refuse = (
            "print('llama_model_load: error loading model: unknown tensor type', file=sys.stderr)\n"
            "raise SystemExit(3)\n"
            if build == BAD_BUILD
            else ""
        )
        binary.write_text(
            f"""#!{sys.executable}
import sys, runpy
if '--version' in sys.argv:
    print('version: {build[1:]} ({build})')
    raise SystemExit
if '--help' in sys.argv:
    print('--host --port --model --alias --ctx-size --parallel --n-gpu-layers '
          '--fit --metrics --flash-attn')
    raise SystemExit
{refuse}sys.argv[1:1] = ['--engine', '--build', {build!r}]
runpy.run_path({str(Path(__file__).resolve())!r}, run_name='__main__')
""",
            encoding="utf-8",
        )
        binary.chmod(0o700)
        store.write_metadata(
            directory, version=build, variant="ubuntu-x64", binary=binary
        )
        time.sleep(0.01)  # distinct install times: the newest is b3
    store.set_in_use("b1")


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
        "engine-1",
        "engine-2",
        "local-1",
        "local-2",
        "gateway",
    )
    ports = dict(zip(names, sweep.free_ports(len(names)), strict=True))
    assert not set(ports.values()) & set(range(8079, 8084))

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    client = httpx.Client(
        timeout=90, trust_env=False, limits=httpx.Limits(max_connections=100)
    )
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs: list[Any] = []
    passphrase = secrets.token_urlsafe(24)
    passed: list[str] = []
    engines = directory / "engines"
    install_builds(engines)

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
        env = sweep.child_environment(directory)
        if name == "agent":
            command = sweep.agent_command(root, ports[name], ports["machine"])
            # This run's own engine store, never the account's.
            env["EUGENE_PLEXUS_AGENT_ENGINE_ROOT"] = str(engines)
        else:
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                name,
                "--directory",
                str(root),
                "--port",
                str(ports[name]),
            ]
        processes[name] = subprocess.Popen(
            command,
            env=env,
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
        passed.append(label)
        print(f"PASS {label}", flush=True)

    try:
        # --- an install: root, an enrolled agent, two copies of one model ------
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

        def service(sub: str) -> str:
            token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
            return str(token)

        def bootstrap(sub: str) -> dict[str, Any]:
            return {
                "agent_url": url("agent"),
                "trust_bundle_file": str(trust.bundle_path),
                "trust_authority": trust.authority,
                "auth_recipient": trust.recipient,
                "service_token": service(sub),
            }

        model_file = directory / "standin.gguf"
        model_file.write_bytes(b"GGUF" + b"\0" * 128)
        for index in (1, 2):
            good(
                "agent",
                "POST",
                "/v1/runtimes",
                operator,
                json={
                    "name": f"r{index}",
                    "engine": "llama_cpp",
                    "modelPath": str(model_file),
                    "modelAlias": MODEL,
                    "port": ports[f"engine-{index}"],
                    "autoDriver": False,
                    "flags": {"contextSize": 32768, "parallelSlots": 2, "gpuLayers": 0},
                },
            )

        def runtimes() -> dict[str, dict[str, Any]]:
            listed = good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
            return {r["name"]: r for r in listed}

        def on(build: str, *names: str) -> bool:
            now = runtimes()
            return all(
                now[n]["status"] == "ready" and now[n].get("engineVersion") == build
                for n in names
            )

        sweep.wait(lambda: on("b1", "r1", "r2"), "both copies ready on b1", seconds=90)
        for index in (1, 2):
            name = f"local-{index}"
            write(name, "bootstrap.json", bootstrap("inference-driver"))
            write(
                name,
                "driver.yaml",
                {
                    "provider": "openai_compat_custom",
                    "modelId": MODEL,
                    "backendLocality": "local",
                    "runtimeName": f"r{index}",
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
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 1})
        start("gateway")
        made = good(
            "agent",
            "POST",
            "/v1/auth/client-keys",
            operator,
            json={
                "name": "Row 13",
                "limits": {"maxConcurrentRequests": 16, "requestsPerMinute": 10000},
            },
        )
        key = str(made["token"])

        def chat(text: str, *, stream: bool, timeout: float = 120) -> httpx.Response:
            return call(
                "gateway",
                "POST",
                "/v1/chat/completions",
                key,
                json={
                    "model": MODEL,
                    "stream": stream,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": text}],
                },
                timeout=timeout,
            )

        def whole(response: httpx.Response) -> bool:
            return (
                response.status_code == 200
                and response.text.count("word ") == WORDS
                and "[DONE]" in response.text
            )

        sweep.wait(
            lambda: whole(chat("R13:warm", stream=True)),
            "the gateway serves",
            seconds=60,
        )

        def rollout(version: str) -> dict[str, Any]:
            good(
                "agent",
                "POST",
                "/v1/engines/llama_cpp/rollout",
                operator,
                json={"version": version},
            )
            ended: dict[str, Any] = {}

            def over() -> bool:
                nonlocal ended
                ended = good("agent", "GET", "/v1/engines/llama_cpp/rollout", operator)
                return ended["state"] in ENDED

            sweep.wait(over, f"the update to {version} ends", seconds=300)
            return ended

        def managed() -> dict[str, Any]:
            """The build in use, as the agent's own record on disk says it
            (`<engine>/in-use.json`). Read there rather than through
            `GET /v1/engines`, which also asks GitHub for the newest build."""
            from eugene_plexus_agent._generated.models import EngineKind
            from eugene_plexus_agent.engines.acquisition import ManagedStore

            record = ManagedStore(engines, EngineKind.llama_cpp).in_use()
            return {"version": record.version, "previousVersion": record.previous}

        class Load:
            """Requests sent all the while, `width` at a time, and what came back."""

            def __init__(self, *, stream: bool, width: int, pause: float = 0.0) -> None:
                self.stream, self.width, self.pause = stream, width, pause
                self.answers: list[httpx.Response] = []
                self.stopping = threading.Event()
                self.pool = ThreadPoolExecutor(width)
                self.futures = [self.pool.submit(self._run, n) for n in range(width)]

            def _run(self, lane: int) -> None:
                count = 0
                while not self.stopping.is_set():
                    count += 1
                    self.answers.append(chat(f"R13:{lane}-{count}", stream=self.stream))
                    time.sleep(self.pause)

            def stop(self) -> list[httpx.Response]:
                self.stopping.set()
                for future in self.futures:
                    future.result(timeout=180)
                self.pool.shutdown()
                return self.answers

        seen: dict[str, set[str]] = {"r1": set(), "r2": set()}
        watching = threading.Event()

        def watch() -> None:
            while not watching.is_set():
                try:
                    for name, runtime in runtimes().items():
                        seen.setdefault(name, set()).add(runtime["status"])
                except (httpx.HTTPError, AssertionError):
                    pass
                time.sleep(0.2)

        # --- 1: two copies move one at a time; every open stream finishes ------
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        load_1 = Load(stream=True, width=2)
        time.sleep(2)
        first = rollout("b2")
        answers = load_1.stop()
        watching.set()
        watcher.join(timeout=5)
        assert first["state"] == "done", first
        assert {r["name"]: r["state"] for r in first["runtimes"]} == {
            "r1": "moved",
            "r2": "moved",
        }, first
        assert on("b2", "r1", "r2"), runtimes()
        broken = [(r.status_code, r.text[-300:]) for r in answers if not whole(r)]
        assert answers and not broken, broken[:3]
        assert "draining" in seen["r1"] and "draining" in seen["r2"], seen
        build = managed()
        assert build["version"] == "b2" and build.get("previousVersion") == "b1", build
        ok(
            f"1. two copies moved to b2 one at a time ({len(answers)} streams, every one whole); "
            "b2 is in use and b1 is kept"
        )

        # --- 2: a build that cannot start the model is kept off ---------------
        second = rollout(BAD_BUILD)
        assert second["state"] == "kept", second
        assert f"{BAD_BUILD} could not run" in (second.get("message") or ""), second
        assert "unknown tensor type" in json.dumps(second) or "exit" in json.dumps(
            second
        ), second
        sweep.wait(lambda: on("b2", "r1", "r2"), "both copies back on b2", seconds=90)
        assert managed()["version"] == "b2"
        ok(
            f"2. {BAD_BUILD} could not start the model, so b2 stays in use: {second['message']}"
        )

        # --- 3: one copy switches at once; its requests wait in line ----------
        good("agent", "POST", "/v1/runtimes/r2/stop", operator)
        sweep.wait(lambda: runtimes()["r2"]["status"] == "stopped", "r2 stopped")
        time.sleep(2.5)  # the gateway's table has seen it stopped
        load_3 = Load(stream=False, width=2, pause=0.1)
        time.sleep(1)
        third = rollout("b1")
        answers = load_3.stop()
        assert third["state"] == "done", third
        assert on("b1", "r1"), runtimes()
        refused = [
            (r.status_code, r.text[:300]) for r in answers if r.status_code != 200
        ]
        assert answers and not refused, refused[:3]
        [check] = [m for m in third["check"]["models"] if m["runtime"] == "r1"]
        assert check["passes"] and not check.get("measured"), check
        assert "only copy" in (check.get("reason") or ""), check
        ok(
            f"3. the only copy switched to b1 at once; {len(answers)} requests meanwhile, "
            "none refused"
        )

        # --- 4: the gateway's drain takes this machine's agent, no other ------
        own = trust.agent_token(trust.recipient)
        view = good("gateway", "GET", "/v1/admin/drain", own)
        assert view["state"] == "serving", view
        for sub in ("inference-driver", "gateway"):
            refused_drain = call("gateway", "GET", "/v1/admin/drain", service(sub))
            assert refused_drain.status_code == 401, (sub, refused_drain.text)
        ok(
            "4. the gateway's drain takes this machine's agent token, and not a driver's or a gateway's"
        )

        # --- 5: a gateway restart finishes its streams -------------------------
        # Only r1 runs now (check 3 stopped r2), with two slots: two streams
        # fill it, so neither waits in the gateway's line, which a drain refuses.
        client.post(url("engine-1") + "/mode", json={"seconds": 5}).raise_for_status()
        process = processes["gateway"]
        with ThreadPoolExecutor(3) as pool:
            streams = [
                pool.submit(chat, f"R13:restart-{n}", stream=True) for n in range(2)
            ]
            time.sleep(1.5)
            restarted = good("gateway", "POST", "/v1/admin/restart", operator)
            assert restarted["scheduled"], restarted
            late = chat("R13:late", stream=False, timeout=10)
            assert late.status_code == 503, late.text
            assert late.json()["error"]["code"] == "shutting_down", late.text
            finished = [f.result(timeout=60) for f in streams]
        assert all(whole(r) for r in finished), [r.text[-300:] for r in finished]
        code = process.wait(timeout=30)
        assert code == 0, code
        processes.pop("gateway")
        ok(
            "5. a gateway restart finished its 2 open streams, refused a new one, and exited 0"
        )

        assert len(passed) == 5, passed
        print(f"ALL {len(passed)} CHECKS PASSED", flush=True)
    finally:
        (directory / "agent" / "stop").touch()
        for name, process in list(processes.items()):
            if process.poll() is None:
                if name != "agent":
                    process.terminate()
                try:
                    process.wait(timeout=30)
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
    elif args.serve == "gateway":
        load("ld1-fair-queue-acceptance.py").serve_gateway(args.directory, args.port)
    elif args.serve:
        load("a6-local-only-acceptance.py").serve(
            "local" if args.serve.startswith("local") else args.serve,
            args.directory,
            args.port,
        )
    else:
        if os.name == "nt":
            raise SystemExit("Linux only: the stand-in engine is an executable script.")
        root = HERE.parents[1] / ".codex-tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="r13-", dir=root) as tmp:
            try:
                exercise(Path(tmp))
            except BaseException:
                for log in sorted(Path(tmp).glob("*/process.log")):
                    print(
                        f"--- {log.parent.name}",
                        log.read_text(encoding="utf-8", errors="replace")[-8000:],
                    )
                raise


if __name__ == "__main__":
    main()
