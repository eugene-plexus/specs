"""Row 57: unchanged OpenAI Python SDK through row 2's signed-process harness.

A disposable standalone agent supervises discovery for a real gateway and a real
inference-driver over a scripted local backend. Both whole and streamed Responses
round-trip all four client-run tools, then compact and expand a conversation.
No tools execute. No models or live services are contacted. Run in CI's shared
acceptance environment; the agent starts through s8-ui-acceptance.py --serve.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
MODEL = "row57-fixture"
SUMMARY = "ROW57-SUMMARY: edited hello.txt; tests pending; continue testing."
FINAL = "ROW57-FINAL: tool result received."
EXPANDED = "ROW57-EXPANDED: summary received as an instruction."
PATCH = "*** Begin Patch\n*** Add File: hello.txt\n+hello\n*** End Patch"
ARGUMENTS = {
    "write": {"input": "hello\n世界"},
    "local_shell": {
        "command": ["echo", "hello"],
        "workdir": "/tmp",
        "timeout_ms": 1000,
        "env": {},
    },
    "shell": {
        "commands": ["echo hello", "pwd"],
        "timeout_ms": 1000,
        "max_output_length": 1024,
    },
    "apply_patch": {"input": PATCH},
}
TOOLS = [
    {
        "type": "custom",
        "name": "write",
        "format": {"type": "grammar", "syntax": "regex", "definition": "hello.*"},
    },
    {"type": "local_shell"},
    {"type": "shell", "environment": {"type": "local"}},
    {"type": "apply_patch"},
]


def harness():
    spec = importlib.util.spec_from_file_location(
        "row57_harness", HERE / "s8-ui-acceptance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answer(body: dict) -> tuple[str | None, list[dict] | None]:
    messages = body["messages"]
    if "Write at most 4,000 tokens." in str(messages[-1].get("content")):
        assert body.get("max_tokens", body.get("max_completion_tokens")) == 4000, body
        return SUMMARY, None
    if any(m.get("role") == "system" and m.get("content") == SUMMARY for m in messages):
        return EXPANDED, None
    if messages[-1]["role"] == "tool":
        assert "ROW57-TOOL-RESULT" in messages[-1]["content"], messages
        assert messages[-1]["tool_call_id"] == messages[-2]["tool_calls"][0]["id"], (
            messages
        )
        return FINAL, None
    [tool] = body["tools"]
    name = tool["function"]["name"]
    return None, [
        {
            "id": "call_row57",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(ARGUMENTS[name], ensure_ascii=False),
            },
        }
    ]


def fixture_app():
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    seen = []

    @app.get("/healthz")
    async def health():
        return {}

    @app.get("/seen")
    async def requests():
        return seen

    @app.get("/model/props")
    async def props():
        return {
            "default_generation_settings": {"n_ctx": 32768},
            "modalities": {"vision": False},
        }

    @app.get("/model/v1/models")
    async def models():
        return {"data": [{"id": MODEL, "object": "model"}]}

    @app.post("/model/v1/chat/completions")
    async def complete(body: dict):
        seen.append(body)
        text, calls = answer(body)
        usage = {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48}
        finish = "tool_calls" if calls else "stop"
        if not body.get("stream"):
            return {
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": finish,
                        "message": {
                            "role": "assistant",
                            "content": text,
                            "tool_calls": calls,
                        },
                    }
                ],
                "usage": usage,
            }

        async def frames():
            def frame(delta, reason=None, usage=None):
                return (
                    "data: "
                    + json.dumps(
                        {
                            "id": "chatcmpl-row57",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": MODEL,
                            "choices": [
                                {"index": 0, "delta": delta, "finish_reason": reason}
                            ],
                            "usage": usage,
                        }
                    )
                    + "\n\n"
                )

            yield frame({"role": "assistant"})
            for call in calls or []:
                yield frame(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["function"]["name"],
                                    "arguments": "",
                                },
                            }
                        ]
                    }
                )
                # Split escapes, newlines and non-ASCII text across adapter fragments.
                for char in call["function"]["arguments"]:
                    yield frame(
                        {"tool_calls": [{"index": 0, "function": {"arguments": char}}]}
                    )
            if text:
                yield frame({"content": text})
            yield frame({}, finish, usage)
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return app


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        app = fixture_app()
    else:
        bootstrap = json.loads(
            (directory / "bootstrap.json").read_text(encoding="utf-8")
        )
        if kind == "model":
            from eugene_plexus_inference_driver.app import create_app
            from eugene_plexus_inference_driver.settings import Settings

            app = create_app(
                settings=Settings(config_file=directory / "driver.yaml", **bootstrap)
            )
        else:
            from eugene_plexus_gateway.app import create_app
            from eugene_plexus_gateway.settings import Settings

            app = create_app(
                settings=Settings(
                    config_file=directory / "gateway.yaml",
                    metrics_file=directory / "metrics.sqlite3",
                    **bootstrap,
                )
            )
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)


def sdk_checks(base: str, token: str, client: httpx.Client, fixture: str) -> None:
    import openai

    sdk = openai.OpenAI(base_url=base + "/v1", api_key=token, max_retries=0, timeout=60)
    try:
        for tool in TOOLS:
            kind = tool["type"]
            expected = "custom_tool_call" if kind == "custom" else kind + "_call"
            for streaming in (False, True):
                kwargs = {
                    "model": MODEL,
                    "input": "Run the requested tool.",
                    "tools": [tool],
                }
                if streaming:
                    names, final = [], None
                    for event in sdk.responses.create(**kwargs, stream=True):
                        names.append(event.type)
                        if event.type == "response.completed":
                            final = event.response
                    assert final is not None, names
                    assert "response.function_call_arguments.delta" not in names, names
                    if kind == "custom":
                        assert "response.custom_tool_call_input.delta" in names, names
                    if kind == "shell":
                        assert "response.shell_call_command.delta" in names, names
                else:
                    raw = sdk.responses.with_raw_response.create(**kwargs)
                    if kind == "custom":
                        assert (
                            "tools[0].format"
                            in raw.headers["x-eugene-plexus-ignored-settings"]
                        )
                    final = raw.parse()
                [item] = final.output
                assert item.type == expected, item
                call = item.model_dump(exclude_none=True)
                result = {
                    "type": expected + "_output",
                    "call_id": item.call_id,
                    "output": "ROW57-TOOL-RESULT",
                }
                if kind == "shell":
                    result["output"] = [
                        {
                            "stdout": "ROW57-TOOL-RESULT",
                            "stderr": "",
                            "outcome": {"type": "exit", "exit_code": 0},
                        }
                    ]
                elif kind == "apply_patch":
                    result["status"] = "completed"
                    assert call["operation"] == {
                        "type": "create_file",
                        "path": "hello.txt",
                        "diff": "+hello",
                    }, call
                elif kind == "custom":
                    assert item.input == ARGUMENTS["write"]["input"], item
                else:
                    assert call["action"]["working_directory"] == "/tmp", call
                history = [
                    {"role": "user", "content": "Run the requested tool."},
                    call,
                    result,
                ]
                final = sdk.responses.create(model=MODEL, input=history, tools=[tool])
                assert final.output_text == FINAL, final
                print(
                    f"PASS {kind}, stream={streaming}, call and output round trip",
                    flush=True,
                )
        compacted = sdk.responses.compact(
            model=MODEL,
            input=[{"role": "user", "content": "Edit hello.txt then test it."}],
        )
        assert compacted.object == "response.compaction", compacted
        assert compacted.output[-1].type == "compaction", compacted
        window = [i.model_dump(exclude_none=True) for i in compacted.output]
        continued = sdk.responses.create(
            model=MODEL, input=[*window, {"role": "user", "content": "continue"}]
        )
        assert continued.output_text == EXPANDED, continued
        observed = client.get(fixture + "/seen").json()[-1]["messages"]
        # The Responses edge expands to developer. The frozen shared driver
        # contract normalizes developer to system for local chat templates.
        assert observed[0] == {"role": "system", "content": SUMMARY}, observed
        print(
            "PASS compact sealed an opaque item and expanded its summary through the driver",
            flush=True,
        )
        bad = dict(window[-1], encrypted_content="tampered")
        try:
            sdk.responses.create(model=MODEL, input=[bad])
        except openai.BadRequestError as exc:
            assert "This compaction was made elsewhere" in str(exc), exc
        else:
            raise AssertionError("tampered compaction was accepted")
        print(
            f"PASS tampered compaction refused; OpenAI SDK {openai.__version__}",
            flush=True,
        )
    finally:
        sdk.close()


def exercise(directory: Path) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    shared = harness()
    ports = {}
    for name in ("agent", "machine", "fixture", "model", "gateway"):
        ports[name] = shared.free_port(*ports.values())
    assert not set(ports.values()) & set(range(8079, 8084)), ports
    processes, logs = [], []
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith("EUGENE_PLEXUS_")
    }
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env["PYTHONPYCACHEPREFIX"] = str(directory / "pycache")
    client = httpx.Client(timeout=60, trust_env=False)
    base = lambda name: f"http://127.0.0.1:{ports[name]}"

    def write(name, filename, body):
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(body) if filename.endswith(".json") else yaml.safe_dump(body),
            encoding="utf-8",
        )

    def wait(check, label):
        deadline = time.perf_counter() + 45
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise AssertionError("timed out: " + label)

    def start(name):
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        if name == "agent":
            command = [
                sys.executable,
                str(HERE / "s8-ui-acceptance.py"),
                "--serve",
                str(work),
                "--port",
                str(ports[name]),
                "--machine-port",
                str(ports["machine"]),
            ]
        else:
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                name,
                "--directory",
                str(work),
                "--port",
                str(ports[name]),
            ]
        processes.append(
            subprocess.Popen(
                command,
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        )
        wait(lambda: client.get(base(name) + "/healthz").status_code == 200, name)

    try:
        write(
            "agent",
            "agent.yaml",
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "securityMode": "prompt_on_startup",
                "components": [],
            },
        )
        start("agent")
        passphrase = secrets.token_urlsafe(24)
        client.post(
            base("agent") + "/v1/auth/initialize", json={"passphrase": passphrase}
        ).raise_for_status()
        operator = client.post(
            base("agent") + "/v1/auth/login", json={"passphrase": passphrase}
        ).json()["sessionToken"]
        headers = {"Authorization": "Bearer " + operator}
        identity = NodeIdentityStore(directory / "agent/node.yaml")
        identity.load()
        trust = NodeTrust(identity, directory / "agent/trust_bundle.json")
        trust.load()

        def bootstrap(kind):
            token, _ = trust.mint_service(sub=kind, audience=trust.recipient)
            return {
                "agent_url": base("agent"),
                "trust_bundle_file": str(trust.bundle_path),
                "trust_authority": trust.authority,
                "auth_recipient": trust.recipient,
                "service_token": token,
            }

        start("fixture")
        write("model", "bootstrap.json", bootstrap("inference-driver"))
        write(
            "model",
            "driver.yaml",
            {
                "provider": "openai_compat_custom",
                "baseUrl": base("fixture") + "/model",
                "modelId": MODEL,
                "backendLocality": "local",
            },
        )
        start("model")
        client.post(
            base("agent") + "/v1/components",
            headers=headers,
            json={
                "name": "row57-model",
                "kind": "inference-driver",
                "url": base("model"),
            },
        ).raise_for_status()
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 1})
        start("gateway")
        made = client.post(
            base("agent") + "/v1/auth/client-keys",
            headers=headers,
            json={
                "name": "row57-sdk",
                "limits": {
                    "allowedModels": [MODEL],
                    "localOnly": True,
                    "requestsPerMinute": 1000,
                },
            },
        )
        made.raise_for_status()
        token = made.json()["token"]
        wait(
            lambda: (
                MODEL
                in {
                    m["id"]
                    for m in client.get(
                        base("gateway") + "/v1/models",
                        headers={"Authorization": "Bearer " + token},
                    )
                    .json()
                    .get("data", [])
                }
            ),
            "fixture model discovery",
        )
        sdk_checks(base("gateway"), token, client, base("fixture"))
    finally:
        (directory / "agent/stop").touch()
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", choices=["fixture", "model", "gateway"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        assert args.port not in range(8079, 8084), "default ports are forbidden"
        serve(args.serve, args.directory, args.port)
        return 0
    temporary = HERE.parent.parent / ".codex-tmp"
    temporary.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="row57-", dir=temporary) as tmp:
        directory = Path(tmp)
        try:
            exercise(directory)
        except BaseException:
            for log in directory.glob("*/process.log"):
                print(
                    log,
                    log.read_text(encoding="utf-8", errors="replace")[-6000:],
                    flush=True,
                )
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
