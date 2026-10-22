"""Row 10, Linux CI: real root, shared-harness agent, gateway and drivers.

The executable engine is a two-slot HTTP fixture. All listeners are OS-assigned
loopback ports, all state is disposable, and no inherited install variables survive.
Do not run this against a live install or a GPU.
"""

import argparse
import asyncio
import importlib.util
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

HERE = Path(__file__).resolve().parent
CHECKS = {"streams", "agents", "replicas-cloud", "foreign", "cancel-revoke", "restart-stale"}


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_ports(count):
    ports = []
    while len(ports) < count:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in ports and port not in range(8079, 8084):
            ports.append(port)
    return ports


def child_environment(directory):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update(
        TEMP=str(directory),
        TMP=str(directory),
        TMPDIR=str(directory),
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        PYTHONUNBUFFERED="1",
    )
    return env


def agent_command(directory, port, machine_port):
    return [
        sys.executable,
        str(HERE / "s8-ui-acceptance.py"),
        "--serve",
        str(directory),
        "--port",
        str(port),
        "--machine-port",
        str(machine_port),
    ]


def fixture_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import PlainTextResponse, StreamingResponse

    app = FastAPI()
    slots = asyncio.Semaphore(2)
    counter = 0
    cloud = 0
    prefixes = {}

    @app.get("/health")
    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/props")
    async def props():
        return {"default_generation_settings": {"n_ctx": 65536}, "total_slots": 2}

    @app.get("/v1/models")
    @app.get("/cloud/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": "m", "object": "model"}]}

    @app.get("/stats")
    async def stats():
        return {"requests": counter, "cloud": cloud}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics():
        # A fixture request counter: real engines without one remain unknown.
        return f"llamacpp:requests_total {counter}\n"

    @app.post("/cloud/v1/chat/completions")
    async def cloud_answer(request: Request):
        nonlocal cloud
        body = await request.json()
        if "Session " in json.dumps(body):
            cloud += 1
        return {
            "id": "cloud",
            "object": "chat.completion",
            "created": 1,
            "model": "cloud",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "probe"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    @app.post("/v1/chat/completions")
    async def answer(request: Request):
        nonlocal counter
        body = await request.json()
        prompt = json.dumps(body.get("messages", []), ensure_ascii=False)
        prompt_tokens = max(1, len(prompt) // 4)
        cached = max(
            (len(os.path.commonprefix([old, prompt])) // 4 for old in prefixes.values()), default=0
        )
        key = prompt.split("Session ", 1)[-1].split(".", 1)[0]
        prefixes[key] = prompt
        count = min(80, body.get("max_tokens") or 80)
        counter += 1
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": count,
            "total_tokens": prompt_tokens + count,
            "prompt_tokens_details": {"cached_tokens": min(cached, prompt_tokens)},
        }

        async def content():
            async with slots:
                await asyncio.sleep(0.025 + min(0.25, (prompt_tokens - cached) / 100000))
                for index in range(count):
                    if index:
                        await asyncio.sleep(0.02)
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "id": "fixture",
                                "object": "chat.completion.chunk",
                                "created": 1,
                                "model": "m",
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
                            "id": "fixture",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": "m",
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            "usage": usage,
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"

        if body.get("stream"):
            return StreamingResponse(content(), media_type="text/event-stream")
        return {
            "id": "fixture",
            "object": "chat.completion",
            "created": 1,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "word " * count},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }

    return app


def engine():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    args, _ = parser.parse_known_args()
    import uvicorn

    uvicorn.run(fixture_app(), host=args.host, port=args.port, log_level="error", access_log=False)


def wait(predicate, label, seconds=30):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError(f"Timed out: {label}")


def exercise(directory):
    import psutil
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    names = ("control", "agent", "machine", "gateway", "local", "cloud", "engine", "copy")
    ports = dict(zip(names, free_ports(len(names))))

    def url(name):
        return f"http://127.0.0.1:{ports[name]}"

    client = httpx.Client(timeout=10, trust_env=False)
    processes, logs = {}, []
    passed = set()
    passphrase = secrets.token_urlsafe(24)

    def write(name, filename, body):
        root = directory / name
        root.mkdir(exist_ok=True)
        (root / filename).write_text(
            json.dumps(body) if filename.endswith(".json") else yaml.safe_dump(body),
            encoding="utf-8",
        )

    def start(name):
        root = directory / name
        root.mkdir(exist_ok=True)
        (root / "stop").unlink(missing_ok=True)
        log = (root / "process.log").open("ab")
        logs.append(log)
        command = (
            agent_command(root, ports[name], ports["machine"])
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
            env=child_environment(directory),
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        wait(lambda: client.get(url(name) + "/healthz").status_code == 200, f"{name} healthy")

    def call(name, method, path, token=None, **kwargs):
        response = client.request(
            method,
            url(name) + path,
            headers={"Authorization": "Bearer " + token} if token else {},
            **kwargs,
        )
        return response

    def good(name, method, path, token=None, **kwargs):
        response = call(name, method, path, token, **kwargs)
        assert response.is_success, (path, response.status_code, response.text)
        return response.json() if response.content else {}

    def jobs():
        return good("agent", "GET", "/v1/serving-measurements", operator)["measurements"]

    def finished(job_id):
        job = next(j for j in jobs() if j["id"] == job_id)
        return job if job["state"] != "running" and not job["keyLive"] else None

    def measure(workload, **extra):
        return good(
            "agent",
            "POST",
            "/v1/serving-measurements",
            operator,
            json={
                "runtime": "r",
                "workload": workload,
                "maxPeople": 4,
                "windowSeconds": 10,
                **extra,
            },
        )

    try:
        start("control")
        good("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        root_token = good("control", "POST", "/v1/auth/login", json={"passphrase": passphrase})[
            "sessionToken"
        ]
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
        standalone = good("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})[
            "sessionToken"
        ]
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

        def bootstrap(sub):
            token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
            return {
                "agent_url": url("agent"),
                "trust_bundle_file": str(trust.bundle_path),
                "trust_authority": trust.authority,
                "auth_recipient": trust.recipient,
                "service_token": token,
            }

        launcher = directory / "llama-server"

        def engine_version(number):
            launcher.write_text(
                f"""#!{sys.executable}
import sys, runpy
if '--version' in sys.argv:
    print('version: {number} (abcdef12)')
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

        engine_version(11001)
        model = directory / "fixture.gguf"
        model.write_bytes(b"GGUF" + b"\0" * 128)
        for name in ("r", "copy"):
            good(
                "agent",
                "POST",
                "/v1/runtimes",
                operator,
                json={
                    "name": name,
                    "engine": "llama_cpp",
                    "binary": str(launcher),
                    "modelPath": str(model),
                    "modelAlias": "m",
                    "port": ports["engine" if name == "r" else "copy"],
                    "autoStart": True,
                    "autoDriver": False,
                    "flags": {"contextSize": 131072, "parallelSlots": 2, "gpuLayers": 0},
                },
            )
        wait(
            lambda: all(
                r["status"] == "ready"
                for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
            ),
            "two ready fixture runtimes",
        )
        for name, locality in (("local", "local"), ("cloud", "external")):
            write(name, "bootstrap.json", bootstrap("inference-driver"))
            config = (
                {
                    "provider": "openai_compat_custom",
                    "modelId": "m" if name == "local" else "cloud",
                    "backendLocality": locality,
                    "runtimeName": "r",
                }
                if name == "local"
                else {
                    "provider": "openai_compat_custom",
                    "modelId": "cloud",
                    "backendLocality": locality,
                    "baseUrl": url("engine") + "/cloud",
                }
            )
            write(name, "driver.yaml", config)
            start(name)
            good(
                "agent",
                "POST",
                "/v1/components",
                operator,
                json={"name": name, "kind": "inference-driver", "url": url(name)},
            )
        # A second real driver follows the other ready replica.
        replica_root = directory / "replica"
        replica_root.mkdir()
        write("replica", "bootstrap.json", bootstrap("inference-driver"))
        write(
            "replica",
            "driver.yaml",
            {
                "provider": "openai_compat_custom",
                "modelId": "m",
                "runtimeName": "copy",
                "backendLocality": "local",
            },
        )
        ports["replica"] = free_ports(1)[0]
        start("replica")
        good(
            "agent",
            "POST",
            "/v1/components",
            operator,
            json={"name": "replica", "kind": "inference-driver", "url": url("replica")},
        )
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write(
            "gateway",
            "gateway.yaml",
            {"routingRefreshSeconds": 2, "modelSlots": [{"model": "m", "targets": ["cloud"]}]},
        )
        start("gateway")
        good(
            "agent",
            "POST",
            "/v1/components",
            operator,
            json={"name": "gateway", "kind": "gateway", "url": url("gateway")},
        )
        check = wait(
            lambda: (
                c
                if (
                    c := good(
                        "agent",
                        "POST",
                        "/v1/serving-measurements/preflight",
                        operator,
                        json={"runtime": "r", "windowSeconds": 10},
                    )
                )["otherReplicas"]
                else None
            ),
            "replica named by preflight",
        )
        assert check["otherReplicas"] == [{"node": "tower", "runtime": "copy", "model": "m"}], check
        refused = call("agent", "POST", "/v1/serving-measurements", operator, json={"runtime": "r"})
        assert refused.status_code == 409, refused.text
        streams = measure("streams", stopReplicas=check["otherReplicas"])
        stream_id = streams["id"]
        # A real, second key's request reaches the same engine during level 1.
        foreign_key = good(
            "agent",
            "POST",
            "/v1/auth/client-keys",
            operator,
            json={
                "name": "Acceptance foreign",
                "limits": {"localOnly": True, "allowedModels": ["m"]},
            },
        )["token"]
        wait(lambda: any("people:" in j["detail"] for j in jobs()), "first measurement level")
        good(
            "gateway",
            "POST",
            "/v1/chat/completions",
            foreign_key,
            json={
                "model": "m",
                "messages": [{"role": "user", "content": "foreign check"}],
                "max_tokens": 2,
            },
        )
        result = wait(lambda: finished(stream_id), "streams completed", 100)
        assert result["state"] == "completed", result
        assert result["knee"]["found"] and result["knee"]["people"] == 2, result
        assert abs(result["levels"][0]["tokensPerSecondEachP50"] / 50 - 1) <= 0.1, result
        assert any((level["foreignRequests"] or 0) >= 1 for level in result["levels"]), result
        passed.update(("streams", "foreign"))
        assert result["restarts"][0]["state"] == "restarted", result
        assert client.get(url("engine") + "/stats").json()["cloud"] == 0
        passed.add("replicas-cloud")
        wait(
            lambda: (
                next(
                    r
                    for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
                    if r["name"] == "copy"
                )["status"]
                == "ready"
            ),
            "replica restarted",
        )
        agents = measure(
            "agents", maxPeople=8, stopReplicas=check["otherReplicas"], ttftThresholdMs=60000
        )
        result = wait(lambda: finished(agents["id"]), "agents completed", 120)
        assert result["state"] == "completed" and result["knee"], result
        assert result["levels"][0]["promptReuse"] > 0.9, result
        assert result["levels"][-1]["ttftP50Ms"] > result["levels"][0]["ttftP50Ms"], result
        assert load("serving-sweep.py").sentence(result)
        passed.add("agents")
        wait(
            lambda: (
                next(
                    r
                    for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
                    if r["name"] == "copy"
                )["status"]
                == "ready"
            ),
            "copy ready again",
        )
        run = measure("streams", stopReplicas=check["otherReplicas"])
        began = time.perf_counter()
        cancelled = good("agent", "POST", f"/v1/serving-measurements/{run['id']}/cancel", operator)
        assert (
            time.perf_counter() - began < 5
            and cancelled["state"] == "cancelled"
            and not cancelled["keyLive"]
        ), cancelled
        keys = good("agent", "GET", "/v1/auth/client-keys", operator)["keys"]
        assert all(k["revokedAt"] for k in keys if k["name"].startswith("Measurement ")), keys
        passed.add("cancel-revoke")
        wait(
            lambda: (
                next(
                    r
                    for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
                    if r["name"] == "copy"
                )["status"]
                == "ready"
            ),
            "copy ready for crash",
        )
        run = measure("streams", stopReplicas=check["otherReplicas"])
        process = processes.pop("agent")
        children = psutil.Process(process.pid).children(recursive=True)
        process.kill()
        process.wait(timeout=10)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        engine_version(11002)
        start("agent")
        operator = good("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase})[
            "sessionToken"
        ]
        wait(
            lambda: (
                next(
                    r
                    for r in good("agent", "GET", "/v1/runtimes", operator)["runtimes"]
                    if r["name"] == "r"
                )["status"]
                == "ready"
            ),
            "engine after agent restart",
        )
        records = jobs()
        crashed = next(j for j in records if j["id"] == run["id"])
        assert crashed["state"] == "failed" and "agent restarted" in crashed["detail"].lower(), (
            crashed
        )
        assert crashed["keyLive"], crashed
        stale = next(j for j in records if j["id"] == stream_id)
        assert not stale["current"] and any(
            "engine" in reason or "binaryHash" in reason for reason in stale["staleBecause"]
        ), stale
        assert not good("agent", "POST", f"/v1/serving-measurements/{run['id']}/cancel", operator)[
            "keyLive"
        ]
        passed.add("restart-stale")
        assert passed == CHECKS, passed
        print("PASS " + ", ".join(sorted(passed)))
    finally:
        for name, process in processes.items():
            if name == "agent":
                (directory / name / "stop").touch()
            else:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()
        client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--engine", action="store_true")
    args, _ = parser.parse_known_args()
    if args.engine:
        engine()
    elif args.serve:
        load("a6-local-only-acceptance.py").serve(
            "local" if args.serve == "replica" else args.serve, args.directory, args.port
        )
    else:
        root = HERE.parents[1] / ".codex-tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="serving-", dir=root) as tmp:
            try:
                exercise(Path(tmp))
            except BaseException:
                for log in Path(tmp).glob("*/process.log"):
                    print(
                        log.parent.name, log.read_text(encoding="utf-8", errors="replace")[-5000:]
                    )
                raise


if __name__ == "__main__":
    main()
