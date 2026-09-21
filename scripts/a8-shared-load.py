"""A8 real-client CPU load instrument. See docs/acceptance/a8-workload-plan.md.

Windows controller, native Claude Code, existing WSL Open WebUI Python. New
private state, identities and ports; existing model/engine files are read only.
No live service/GPU changes. Raw public measurements contain no credentials.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse


MODEL = "a8-gemma"


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def wait(check, label, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (httpx.HTTPError, KeyError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Timed out: " + label)


def wsl_path(path):
    path = Path(path).resolve()
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def serve_agent(root, port):
    from eugene_plexus_agent.__main__ import build_server
    from eugene_plexus_agent.settings import Settings

    server = build_server(
        Settings(
            config_file=root / "agent.yaml", bind_port=port, default_topology=False
        ),
        unattended=True,
    )

    def stop():
        while not (root / "stop").exists():
            time.sleep(0.1)
        server.should_exit = True

    threading.Thread(target=stop, daemon=True).start()
    server.run()


def serve_webui(config_path):
    config = json.loads(config_path.read_text())
    Path(config["environment"]["DATA_DIR"]).mkdir(mode=0o700)
    os.environ.update(config["environment"])
    server = uvicorn.Server(
        uvicorn.Config(
            "open_webui.main:app",
            host="127.0.0.1",
            port=config["port"],
            log_level="warning",
            access_log=False,
        )
    )

    def stop():
        while not Path(config["stop"]).exists():
            time.sleep(0.2)
        server.should_exit = True

    threading.Thread(target=stop, daemon=True).start()
    server.run()


class Observer:
    def __init__(self, target, root):
        self.target, self.root = target, root
        self.phase = "setup"
        self.labels = {}
        self.rows = []

    def app(self):
        @asynccontextmanager
        async def lifespan(app):
            async with httpx.AsyncClient(
                base_url=self.target, timeout=650, trust_env=False
            ) as client:
                app.state.client = client
                yield

        app = FastAPI(lifespan=lifespan)

        @app.api_route("/{path:path}", methods=["GET", "POST"])
        async def forward(path: str, request: Request):
            raw = await request.body()
            body = json.loads(raw) if raw else {}
            token = request.headers.get("x-api-key") or request.headers.get(
                "authorization", ""
            ).removeprefix("Bearer ")
            row = {
                "id": str(uuid.uuid4()),
                "phase": self.phase,
                "client": self.labels.get(token, "unknown"),
                "path": path,
                "started": time.perf_counter(),
                "status": None,
                "inputChars": len(
                    json.dumps(
                        {
                            k: body[k]
                            for k in ("messages", "system", "tools")
                            if k in body
                        }
                    )
                ),
                "maxTokens": body.get("max_tokens"),
                "ttft": None,
                "outputChars": 0,
                "promptTokens": None,
                "completionTokens": None,
                "streamError": False,
                "cancelled": False,
                "finished": False,
            }
            headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower()
                in {
                    "authorization",
                    "x-api-key",
                    "content-type",
                    "accept",
                    "anthropic-version",
                    "anthropic-beta",
                }
            }
            upstream = await app.state.client.send(
                app.state.client.build_request(
                    request.method,
                    "/" + path + ("?" + request.url.query if request.url.query else ""),
                    content=raw,
                    headers=headers,
                ),
                stream=True,
            )
            row["status"] = upstream.status_code
            row["requestId"] = upstream.headers.get("x-request-id")

            def event(data):
                if data == "[DONE]":
                    row["finished"] = True
                    return
                try:
                    obj = json.loads(data)
                except ValueError:
                    return
                row["streamError"] |= "error" in obj or obj.get("type") == "error"
                usage = obj.get("usage") or obj.get("message", {}).get("usage") or {}
                for source, dest in (
                    ("prompt_tokens", "promptTokens"),
                    ("input_tokens", "promptTokens"),
                    ("completion_tokens", "completionTokens"),
                    ("output_tokens", "completionTokens"),
                ):
                    if source in usage:
                        row[dest] = usage[source]
                text = ""
                for choice in obj.get("choices", []):
                    delta = choice.get("delta") or {}
                    text += delta.get("content") or ""
                    for tool in delta.get("tool_calls", []):
                        text += tool.get("function", {}).get("name", "") + tool.get(
                            "function", {}
                        ).get("arguments", "")
                delta = obj.get("delta") or {}
                text += delta.get("text", "") + delta.get("partial_json", "")
                if obj.get("content_block", {}).get("type") == "tool_use":
                    text += obj["content_block"].get("name", "")
                if text:
                    row["outputChars"] += len(text)
                    if row["ttft"] is None:
                        row["ttft"] = time.perf_counter() - row["started"]
                if obj.get("type") == "message_stop":
                    row["finished"] = True

            async def chunks():
                pending = b""
                try:
                    async for chunk in upstream.aiter_raw():
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            if line.startswith(b"data:"):
                                event(line[5:].strip().decode("utf-8"))
                        yield chunk
                except asyncio.CancelledError:
                    row["cancelled"] = True
                    raise
                finally:
                    await upstream.aclose()
                    row["elapsed"] = time.perf_counter() - row["started"]
                    if request.method == "POST":
                        self.rows.append(row)
                        with (self.root / "requests.jsonl").open(
                            "a", encoding="utf-8"
                        ) as file:
                            file.write(json.dumps(row) + "\n")

            return StreamingResponse(
                chunks(),
                status_code=upstream.status_code,
                headers={
                    k: v
                    for k, v in upstream.headers.items()
                    if k.lower() in {"content-type", "retry-after", "x-request-id"}
                },
            )

        return app


def exercise(args):
    root = args.directory.resolve()
    root.mkdir()  # Never overwrite evidence or an installation.
    if os.name == "nt":
        sid = (
            subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
            .strip()
            .split(",")[-1]
            .strip('"')
        )
        subprocess.run(
            [
                "icacls",
                str(root),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
        )
    ports = {}
    sockets = []
    for name in ("agent", "gateway", "driver", "engine", "observer", "webui"):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sockets.append(sock)
        ports[name] = sock.getsockname()[1]
    for sock in sockets:
        sock.close()
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    observer = Observer(urls["gateway"], root)
    processes, logs = {}, []
    servers = []
    results = []
    phase_times = {}
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("EUGENE_PLEXUS_", "ANTHROPIC_", "CLAUDE_"))
    }
    env.update(
        PYTHONUTF8="1",
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        CUDA_VISIBLE_DEVICES="-1",
        HIP_VISIBLE_DEVICES="-1",
        ROCR_VISIBLE_DEVICES="-1",
    )
    client = httpx.Client(timeout=90, trust_env=False)
    operator = None

    def call(method, path, **kwargs):
        response = client.request(
            method,
            urls["agent"] + path,
            headers={"Authorization": "Bearer " + operator} if operator else {},
            **kwargs,
        )
        if response.is_error:
            raise RuntimeError(
                f"{method} {path}: {response.status_code} {response.text}"
            )
        return response

    def start(name, command, cwd=None):
        log = (root / (name + ".log")).open("ab")
        logs.append(log)
        processes[name] = subprocess.Popen(
            command,
            cwd=cwd or root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def phase(name):
        observer.phase = name
        phase_times[name] = {"start": time.perf_counter()}
        print("PHASE", name, flush=True)

    def end_phase(name):
        phase_times[name]["elapsed"] = time.perf_counter() - phase_times[name]["start"]
        write(root / "phase-times.json", phase_times)

    try:
        (root / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "securityMode": "prompt_on_startup",
                    "components": [],
                    "engineBinaryRoots": [str(args.engine.resolve().parent)],
                }
            ),
            encoding="utf-8",
        )
        start(
            "agent",
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve-agent",
                str(root),
                str(ports["agent"]),
            ],
        )
        wait(lambda: client.get(urls["agent"] + "/healthz").status_code == 200, "agent")
        phrase = secrets.token_urlsafe(24)
        operator = call(
            "POST", "/v1/auth/initialize", json={"passphrase": phrase}
        ).json()["sessionToken"]
        keys = {}
        for name, concurrent in (("webui", 3), ("claude-1", 1), ("claude-2", 1)):
            keys[name] = call(
                "POST",
                "/v1/auth/client-keys",
                json={
                    "name": "A8 " + name,
                    "limits": {
                        "allowedModels": [MODEL],
                        "maxConcurrentRequests": concurrent,
                        "requestsPerMinute": 120,
                        "localOnly": True,
                    },
                },
            ).json()["token"]
            observer.labels[keys[name]] = name
        write(
            root / "private-run.json",
            {"urls": urls, "keys": keys, "operator": operator},
        )
        call(
            "POST",
            "/v1/runtimes?force=true",
            json={
                "name": MODEL,
                "modelAlias": MODEL,
                "engine": "llama_cpp",
                "binary": str(args.engine.resolve()),
                "modelPath": str(args.model.resolve()),
                "port": ports["engine"],
                "autoStart": False,
                "startOnDemand": True,
                "autoDriver": False,
                "flags": {
                    "contextSize": 81920,
                    "parallelSlots": 5,
                    "threads": 8,
                    "gpuLayers": 0,
                    "batchSize": 256,
                    "ubatchSize": 128,
                },
            },
        )
        for name, kind, config in (
            (
                "driver",
                "inference-driver",
                {
                    "provider": "openai_compat_custom",
                    "backendLocality": "local",
                    "runtimeName": MODEL,
                    "modelId": MODEL,
                    "requestTimeoutSeconds": 660,
                },
            ),
            (
                "gateway",
                "gateway",
                {
                    "routingRefreshSeconds": 1,
                    "defaultMaxTokens": 1024,
                    "defaultTemperature": 0,
                    "requestTimeoutSeconds": 600,
                },
            ),
        ):
            file = root / (name + ".yaml")
            file.write_text(yaml.safe_dump(config), encoding="utf-8")
            call(
                "POST",
                "/v1/components",
                json={
                    "name": "a8-" + name,
                    "kind": kind,
                    "url": urls[name],
                    "spawn": {"configFile": str(file)},
                },
            )
            wait(lambda: client.get(urls[name] + "/healthz").status_code == 200, name)
        wait(
            lambda: (
                client.get(
                    urls["gateway"] + "/v1/models",
                    headers={"Authorization": "Bearer " + keys["webui"]},
                )
                .json()
                .get("data")
            ),
            "routes",
        )
        assert client.get(urls["gateway"] + "/v1/models").status_code == 401
        # Only this observer is reachable from the WSL guest, on its host interface.
        server = uvicorn.Server(
            uvicorn.Config(
                observer.app(),
                host=args.wsl_host,
                port=ports["observer"],
                access_log=False,
                log_level="warning",
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        servers.append((server, thread))
        observed_url = f"http://{args.wsl_host}:{ports['observer']}"
        wait(
            lambda: (
                client.get(
                    observed_url + "/v1/models",
                    headers={"Authorization": "Bearer " + keys["webui"]},
                ).status_code
                == 200
            ),
            "observer",
        )
        webui_data = "/home/tcorbin/.cache/" + root.name + "-webui"
        webui_env = {
            "DATA_DIR": webui_data,
            "WEBUI_SECRET_KEY": secrets.token_urlsafe(32),
            "WEBUI_AUTH": "True",
            "ENABLE_SIGNUP": "True",
            "ENABLE_OLLAMA_API": "False",
            "OPENAI_API_BASE_URL": observed_url + "/v1",
            "OPENAI_API_KEY": keys["webui"],
            "OFFLINE_MODE": "True",
            "HF_HUB_OFFLINE": "1",
            "ENABLE_VERSION_UPDATE_CHECK": "False",
            "SCARF_NO_ANALYTICS": "true",
            "DO_NOT_TRACK": "true",
        }
        webui_config = root / "private-webui.json"
        write(
            webui_config,
            {
                "port": ports["webui"],
                "environment": webui_env,
                "stop": wsl_path(root / "stop-webui"),
            },
        )
        start(
            "webui",
            [
                "wsl",
                "-e",
                args.webui_python,
                wsl_path(__file__),
                "--serve-webui",
                wsl_path(webui_config),
            ],
        )
        wait(
            lambda: client.get(urls["webui"] + "/health").status_code == 200,
            "Open WebUI",
            240,
        )
        signup = client.post(
            urls["webui"] + "/api/v1/auths/signup",
            json={
                "name": "A8 isolated operator",
                "email": "a8@example.invalid",
                "password": secrets.token_urlsafe(24),
            },
        )
        signup.raise_for_status()
        webui_token = signup.json()["token"]
        write(
            root / "private-webui-login.json",
            {"token": webui_token, "url": urls["webui"]},
        )
        versions = {
            "python": sys.version,
            "engine": subprocess.check_output(
                [str(args.engine), "--version"], text=True, stderr=subprocess.STDOUT
            ),
            "claude": subprocess.check_output(
                [str(args.claude), "--version"], text=True
            ),
            "modelSha256": hashlib.file_digest(
                args.model.open("rb"), "sha256"
            ).hexdigest(),
        }
        write(root / "versions.json", versions)

        async def chat(label, index, long=False, cancel_event=None, ready=None):
            started = time.perf_counter()
            row = {
                "phase": observer.phase,
                "client": label,
                "index": index,
                "started": started,
                "ttft": None,
                "status": None,
                "cancelled": False,
            }
            prompt = (
                "Write a detailed numbered list of 200 tips for organizing a small office. Keep writing until all 200 are done."
                if long
                else f"What is {17 + index} plus 25? Answer in one short sentence."
            )
            async with httpx.AsyncClient(timeout=620, trust_env=False) as async_client:
                async with async_client.stream(
                    "POST",
                    urls["webui"] + "/api/chat/completions",
                    headers={"Authorization": "Bearer " + webui_token},
                    json={
                        "model": MODEL,
                        "stream": True,
                        "messages": [{"role": "user", "content": prompt}],
                        "params": {"max_tokens": 512 if long else 96, "temperature": 0},
                    },
                ) as response:
                    row["status"] = response.status_code
                    response.raise_for_status()
                    content = ""
                    async for line in response.aiter_lines():
                        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                            continue
                        obj = json.loads(line[5:])
                        assert "error" not in obj, obj.get("error")
                        for choice in obj.get("choices", []):
                            part = (choice.get("delta") or {}).get("content") or ""
                            if part:
                                if row["ttft"] is None:
                                    row["ttft"] = time.perf_counter() - started
                                    if ready:
                                        ready.set()
                                content += part
                        if cancel_event and cancel_event.is_set():
                            row["cancelled"] = True
                            break
                    row["outputChars"] = len(content)
                    expected = 42 + index
                    tens = {4: "forty", 5: "fifty", 6: "sixty", 7: "seventy"}
                    units = [
                        "",
                        "one",
                        "two",
                        "three",
                        "four",
                        "five",
                        "six",
                        "seven",
                        "eight",
                        "nine",
                    ]
                    words = tens[expected // 10] + (
                        " " + units[expected % 10] if expected % 10 else ""
                    )
                    normalized = content.lower().replace("-", " ")
                    row["correct"] = (
                        None
                        if long
                        else bool(re.search(rf"\b{expected}\b|\b{words}\b", normalized))
                    )
                    with (root / "private-answers.jsonl").open(
                        "a", encoding="utf-8"
                    ) as file:
                        file.write(
                            json.dumps(
                                {
                                    "phase": row["phase"],
                                    "client": label,
                                    "index": index,
                                    "content": content,
                                }
                            )
                            + "\n"
                        )
            row["elapsed"] = time.perf_counter() - started
            results.append(row)
            write(root / "clients.json", results)
            print("CHAT", label, index, round(row["elapsed"], 3), "seconds", flush=True)
            return row

        def claude(label):
            task = root / (observer.phase + "-" + label)
            task.mkdir()
            subprocess.run(["git", "init", "--quiet", str(task)], check=True)
            (task / "clamp.py").write_text(
                "def clamp(value, low, high):\n    return min(value, high)\n"
            )
            check = "from clamp import clamp\nassert clamp(-2, 0, 10) == 0\nassert clamp(12, 0, 10) == 10\nassert clamp(4, 0, 10) == 4\nprint('All clamp checks passed.')\n"
            (task / "check.py").write_text(check)
            task_env = dict(env)
            task_env.update(
                {
                    "CLAUDE_CONFIG_DIR": str(task / "config"),
                    "ANTHROPIC_API_KEY": keys[label],
                    "ANTHROPIC_BASE_URL": observed_url,
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "DISABLE_TELEMETRY": "1",
                    "ANTHROPIC_CUSTOM_MODEL_OPTION": MODEL,
                    "ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES": "thinking",
                    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "16384",
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "2048",
                    "MAX_THINKING_TOKENS": "0",
                    "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1",
                    "CLAUDE_CODE_EFFORT_LEVEL": "unset",
                }
            )
            cmd = [
                str(args.claude),
                "--bare",
                "--disable-slash-commands",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--setting-sources",
                "",
                "--model",
                MODEL,
                "--tools",
                "Read,Edit,Bash",
                "--allowedTools",
                "Read(./clamp.py)",
                "Read(./check.py)",
                "Edit(./clamp.py)",
                "Bash(python check.py)",
                "--system-prompt",
                "Complete the small coding task. Read only clamp.py and check.py, edit only clamp.py, and run only python check.py. Explain your change and check result.",
                "--output-format",
                "stream-json",
                "--verbose",
                "--max-turns",
                "10",
                "-p",
                "Inspect clamp.py and check.py. Explain the smallest fix, apply it only to clamp.py, and run python check.py. Do not edit check.py.",
            ]
            started = time.perf_counter()
            with (task / "transcript.jsonl").open("wb") as file:
                process = subprocess.run(
                    cmd,
                    cwd=task,
                    env=task_env,
                    stdout=file,
                    stderr=subprocess.STDOUT,
                    timeout=620,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            rows = [
                json.loads(line)
                for line in (task / "transcript.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.startswith("{")
            ]
            result = next(
                (row for row in reversed(rows) if row.get("type") == "result"), {}
            )
            checked = (
                subprocess.run(
                    [sys.executable, "check.py"], cwd=task, capture_output=True
                ).returncode
                == 0
            )
            tools = [
                block.get("name")
                for row in rows
                if row.get("type") == "assistant"
                for block in row.get("message", {}).get("content", [])
                if block.get("type") == "tool_use"
            ]
            row = {
                "phase": observer.phase,
                "client": label,
                "started": started,
                "elapsed": time.perf_counter() - started,
                "exitCode": process.returncode,
                "isError": result.get("is_error", True),
                "turns": result.get("num_turns"),
                "tools": tools,
                "checkPassed": checked,
                "checkUnchanged": (task / "check.py").read_text() == check,
                "permissionDenials": len(result.get("permission_denials", [])),
            }
            results.append(row)
            print("CODING", label, json.dumps(row), flush=True)
            return row

        async def loads():
            phase("cold")
            await chat("webui-1", 0)
            end_phase("cold")
            phase("single-chat")
            for i in range(12):
                await chat("webui-1", i)
            end_phase("single-chat")
            phase("single-code")
            await asyncio.to_thread(claude, "claude-1")
            end_phase("single-code")
            phase("mixed")

            async def worker(number):
                for i in range(4):
                    await chat("webui-" + str(number), number * 10 + i)
                    if i < 3:
                        await asyncio.sleep(1)

            await asyncio.gather(
                *(worker(i) for i in range(1, 4)),
                asyncio.to_thread(claude, "claude-1"),
                asyncio.to_thread(claude, "claude-2"),
            )
            end_phase("mixed")
            phase("saturation")
            tasks = [
                asyncio.create_task(chat("webui-" + str(i + 1), i, True))
                for i in range(3)
            ]
            try:
                # Reasoning models may emit no visible text before their entire
                # cap. Cancel real decoding work, not a role-only stream header,
                # without requiring the model to finish its reasoning first.
                deadline = time.perf_counter() + 90
                while True:
                    slots = client.get(urls["engine"] + "/slots").json()
                    decoding = [
                        s
                        for s in slots
                        if s.get("is_processing")
                        and any(
                            t.get("n_decoded", 0) >= 8 for t in s.get("next_token", [])
                        )
                    ]
                    if len(decoding) >= 3:
                        break
                    assert not any(t.done() for t in tasks), (
                        "long streams ended before saturation"
                    )
                    assert time.perf_counter() < deadline, (
                        "three engine slots did not start decoding"
                    )
                    await asyncio.sleep(0.2)
                active_slots = len(decoding)
                async with httpx.AsyncClient(
                    timeout=15, trust_env=False
                ) as async_client:
                    started = time.perf_counter()
                    response = await async_client.post(
                        observed_url + "/v1/chat/completions",
                        headers={"Authorization": "Bearer " + keys["webui"]},
                        json={
                            "model": MODEL,
                            "messages": [{"role": "user", "content": "Say hello."}],
                            "max_tokens": 16,
                        },
                    )
                    refusal = {
                        "status": response.status_code,
                        "elapsed": time.perf_counter() - started,
                        "retryAfter": response.headers.get("retry-after"),
                        "errorType": response.json().get("error", {}).get("type"),
                    }
                cancel_started = time.perf_counter()
                for task in tasks:
                    task.cancel()
                cancellations = await asyncio.gather(*tasks, return_exceptions=True)
                assert all(isinstance(r, asyncio.CancelledError) for r in cancellations)
                await asyncio.to_thread(
                    wait,
                    lambda: all(
                        not s.get("is_processing")
                        for s in client.get(urls["engine"] + "/slots").json()
                    ),
                    "idle slots after cancellation",
                    10,
                )
                cleanup = time.perf_counter() - cancel_started
                fresh = await chat("webui-after-cancel", 0)
                write(
                    root / "saturation.json",
                    {
                        "refusal": refusal,
                        "cancelToIdleSeconds": cleanup,
                        "activeSlotsBeforeCancel": active_slots,
                        "cancelToFreshFirstContentSeconds": fresh["started"]
                        + fresh["ttft"]
                        - cancel_started,
                        "freshRequest": fresh,
                    },
                )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            end_phase("saturation")

        asyncio.run(loads())
        write(root / "clients.json", results)
        write(root / "engine-props.json", client.get(urls["engine"] + "/props").json())
        print("COMPLETE measurements retained at", root, flush=True)
    finally:
        (root / "stop-webui").touch()
        (root / "stop").touch()
        for server, thread in servers:
            server.should_exit = True
            thread.join(timeout=15)
        for name, process in processes.items():
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=15)
                print("Forced controller cleanup:", name, flush=True)
        for log in logs:
            log.close()
        client.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve-agent":
        serve_agent(Path(sys.argv[2]), int(sys.argv[3]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--serve-webui":
        serve_webui(Path(sys.argv[2]))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--directory", required=True, type=Path)
        parser.add_argument("--engine", required=True, type=Path)
        parser.add_argument("--model", required=True, type=Path)
        parser.add_argument("--claude", required=True, type=Path)
        parser.add_argument(
            "--webui-python", default="/home/tcorbin/.cache/ep-a4-openwebui/bin/python"
        )
        parser.add_argument("--wsl-host", required=True)
        exercise(parser.parse_args())
