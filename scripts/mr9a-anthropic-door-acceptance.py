#!/usr/bin/env python3
"""MR9a: search results and the memory tool, through a real gateway, driver and llama.cpp.

2026-10-18. A real `llama-server` with a real model, behind a recording
proxy, behind the real `eugene-plexus-inference-driver` and the real
`eugene-plexus-gateway`, with `r4-stubs.py agent` in front of the
component list, as in the count_tokens run.

What only a live run shows: that a `search_result` block's words reach the
engine numbered across the request (top level and inside a tool result),
and that a real model answers from them; that the memory tool reaches the
engine as a function with Anthropic's protocol text after the system
prompt, and that a real model's call comes back as a `tool_use` named
`memory` with one of the six commands, and the loop continues after the
caller's own result.

  1. the gateway routes the model
  2. a top-level search result: the engine is sent "[Search result 1: ...]"
  3. a tool's search result is numbered after it: "[Search result 2: ...]"
  4. the model answers with a code word only the search results hold
  5. citations enabled: answered, and `citations` named ignored
  6. mixed citation settings: a 400, and nothing reaches the engine
  7. the memory tool reaches the engine as a function named `memory`
  8. the protocol text follows the request's own system text
  9. the model's call comes back as `tool_use` `memory` with a valid command
 10. the caller's result is taken and the loop continues
 11. count_tokens counts the search result and the memory tool

A 0.6B model may spend the cap of check 9 without a call; the run of record
(docs/acceptance/mr9a-anthropic-door-run.md) used Qwen3.5-4B on the processor.

Safe beside a live install: ports 9480-9484, every ambient EUGENE_PLEXUS_*
variable dropped, teardown by pid. The processor by default (no GPU).

Usage:
    python scripts/mr9a-anthropic-door-acceptance.py
    EP_LLAMA_SERVER=.../llama-server.exe EP_MODEL_FILE=.../model.gguf EP_GPU_LAYERS=0 \\
        python scripts/mr9a-anthropic-door-acceptance.py
"""

from __future__ import annotations

import http.client as httpclient
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TEMP = Path(os.environ.get("TEMP", tempfile.gettempdir()))
LLAMA = Path(
    os.environ.get(
        "EP_LLAMA_SERVER",
        str(Path.home() / ".eugene-plexus/engines/llama_cpp/b10948/llama-server.exe"),
    )
)
MODEL_FILE = Path(
    os.environ.get(
        "EP_MODEL_FILE", str(TEMP / "ep-s9-model" / "Qwen3-0.6B-Q4_K_M.gguf")
    )
)
MODEL = os.environ.get("EP_MODEL_ID", "mr9a-model")
GPU_LAYERS = os.environ.get("EP_GPU_LAYERS", "0")
ENGINE, PROXY, AGENT_PORT, DRIVER_PORT, GATEWAY_PORT = 9480, 9481, 9482, 9483, 9484
GATEWAY = f"http://127.0.0.1:{GATEWAY_PORT}"
GATEWAY_PY = ROOT / "gateway/.venv/Scripts/python.exe"
DRIVER_PY = ROOT / "inference-driver/.venv/Scripts/python.exe"
PROTOCOL_START = (
    "IMPORTANT: ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE."
)
COMMANDS = {"view", "create", "str_replace", "insert", "delete", "rename"}
CODE = "TANGERINE-4417"

RESULTS: list[tuple[str, bool, str]] = []
SENT: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(
        f"{'PASS' if ok else 'FAIL'}  {len(RESULTS):>2}. {name}"
        + (f"  -- {detail}" if detail else "")
    )
    return ok


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def http(
    method: str, url: str, body: Any = None, timeout: float = 900
) -> tuple[int, Any, dict[str, str]]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status, headers = (
                r.read().decode("utf-8", "replace"),
                r.status,
                dict(r.headers),
            )
    except urllib.error.HTTPError as e:
        raw, status, headers = (
            e.read().decode("utf-8", "replace"),
            e.code,
            dict(e.headers),
        )
    try:
        return status, json.loads(raw), headers
    except ValueError:
        return status, raw, headers


class Recorder(BaseHTTPRequestHandler):
    """Forwards to the engine and keeps every chat body it was sent."""

    def log_message(self, *args: Any) -> None:
        pass

    def _forward(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else None
        if body and self.path.endswith("/chat/completions"):
            try:
                SENT.append(json.loads(body))
            except ValueError:
                pass
        upstream = httpclient.HTTPConnection("127.0.0.1", ENGINE, timeout=900)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host",)}
        upstream.request(self.command, self.path, body=body, headers=headers)
        reply = upstream.getresponse()
        data = reply.read()
        self.send_response(reply.status)
        for k, v in reply.getheaders():
            if k.lower() not in ("transfer-encoding", "content-length", "connection"):
                self.send_header(k, v)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        upstream.close()

    do_GET = do_POST = _forward


def clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}


def messages(body: dict[str, Any], **extra: Any) -> tuple[int, Any, dict[str, str]]:
    request = {
        "model": MODEL,
        "max_tokens": 200,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        **body,
        **extra,
    }
    return http("POST", f"{GATEWAY}/v1/messages", request)


def result(n: int, text: str, *, citations: bool | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "search_result",
        "source": f"kb://heron/{n}",
        "title": f"Project Heron note {n}",
        "content": [{"type": "text", "text": text}],
    }
    if citations is not None:
        block["citations"] = {"enabled": citations}
    return block


def text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    for path in (LLAMA, MODEL_FILE, GATEWAY_PY, DRIVER_PY):
        if not path.exists():
            print(f"missing: {path}")
            return 2
    for port in (ENGINE, PROXY, AGENT_PORT, DRIVER_PORT, GATEWAY_PORT):
        if not port_free(port):
            print(f"port {port} is taken; refusing to start")
            return 2

    work = Path(tempfile.mkdtemp(prefix="mr9a-acceptance-"))
    (work / "driver.yaml").write_text(
        f"provider: openai_compat_custom\nbaseUrl: http://127.0.0.1:{PROXY}\nmodelId: {MODEL}\n"
        "requestTimeoutSeconds: 900\n",
        encoding="utf-8",
        newline="\n",
    )
    (work / "gateway.yaml").write_text("requestTimeoutSeconds: 900\n", encoding="utf-8")
    env = clean_env()
    procs: list[subprocess.Popen[bytes]] = []

    def spawn(args: list[str], log: str, extra: dict[str, str]) -> None:
        procs.append(
            subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=open(work / log, "wb"),  # noqa: SIM115 - closed with the process
                stderr=subprocess.STDOUT,
                env={**env, **extra},
            )
        )

    proxy = ThreadingHTTPServer(("127.0.0.1", PROXY), Recorder)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        hide = (
            {}
            if GPU_LAYERS != "0"
            else {"CUDA_VISIBLE_DEVICES": "-1", "GGML_VK_VISIBLE_DEVICES": ""}
        )
        spawn(
            [
                str(LLAMA),
                "-m",
                str(MODEL_FILE),
                "--host",
                "127.0.0.1",
                "--port",
                str(ENGINE),
                "-ngl",
                GPU_LAYERS,
                "-c",
                "8192",
                "-np",
                "1",
                "--jinja",
            ],
            "llama.log",
            hide,
        )
        spawn(
            [
                sys.executable,
                str(ROOT / "specs/scripts/r4-stubs.py"),
                "agent",
                "--port",
                str(AGENT_PORT),
                "--driver-port",
                str(DRIVER_PORT),
            ],
            "agent.log",
            {},
        )
        spawn(
            [str(DRIVER_PY), "-m", "eugene_plexus_inference_driver"],
            "driver.log",
            {
                "EUGENE_PLEXUS_DRIVER_CONFIG_FILE": str(work / "driver.yaml"),
                "EUGENE_PLEXUS_DRIVER_BIND_PORT": str(DRIVER_PORT),
                "EUGENE_PLEXUS_DRIVER_AGENT_URL": f"http://127.0.0.1:{AGENT_PORT}",
            },
        )
        spawn(
            [str(GATEWAY_PY), "-m", "eugene_plexus_gateway"],
            "gateway.log",
            {
                "EUGENE_PLEXUS_GATEWAY_CONFIG_FILE": str(work / "gateway.yaml"),
                "EUGENE_PLEXUS_GATEWAY_METRICS_FILE": str(work / "metrics.sqlite3"),
                "EUGENE_PLEXUS_GATEWAY_BIND_PORT": str(GATEWAY_PORT),
                "EUGENE_PLEXUS_GATEWAY_AGENT_URL": f"http://127.0.0.1:{AGENT_PORT}",
            },
        )
        deadline = time.perf_counter() + 180
        routable = False
        while time.perf_counter() < deadline:
            try:
                s, models, _ = http("GET", f"{GATEWAY}/v1/models", timeout=5)
                engine_up = (
                    http("GET", f"http://127.0.0.1:{ENGINE}/health", timeout=5)[0]
                    == 200
                )
                if (
                    engine_up
                    and s == 200
                    and any(m.get("id") == MODEL for m in models.get("data", []))
                ):
                    routable = True
                    break
            except OSError:
                pass
            time.sleep(1)
        if not check("the gateway routes the model", routable, f"{MODEL_FILE.name}"):
            return 1
        run_checks()
    finally:
        proxy.shutdown()
        # What the engine was sent, for the record.
        with open(work / "engine-requests.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for sent in SENT:
                f.write(json.dumps(sent) + "\n")
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} PASS, {len(failed)} FAIL  (logs in {work})")
    return 0 if not failed else 1


def run_checks() -> None:
    lookup = {
        "name": "search_notes",
        "description": "Search the project notes.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    conversation = [
        {
            "role": "user",
            "content": [
                result(1, "Project Heron moved its weekly meeting to Thursdays."),
                {
                    "type": "text",
                    "text": "Look up the access phrase for Project Heron.",
                },
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "search_notes",
                    "input": {"query": "Project Heron access phrase"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": [
                        result(2, f"The access phrase for Project Heron is {CODE}.")
                    ],
                },
                {
                    "type": "text",
                    "text": "What is the access phrase? Reply with the phrase only.",
                },
            ],
        },
    ]
    before = len(SENT)
    status, out, _ = messages({"messages": conversation, "tools": [lookup]})
    sent = SENT[before:]
    engine_body = sent[-1] if sent else {}
    chat = engine_body.get("messages", [])
    user_first = next((text_of(m) for m in chat if m.get("role") == "user"), "")
    tool_text = next((text_of(m) for m in chat if m.get("role") == "tool"), "")
    check(
        "a top-level search result reaches the engine numbered 1",
        "[Search result 1: Project Heron note 1 (kb://heron/1)]" in user_first
        and "weekly meeting" in user_first,
        user_first[:90].replace("\n", " | "),
    )
    check(
        "a tool's search result is numbered after it",
        "[Search result 2: Project Heron note 2 (kb://heron/2)]" in tool_text
        and CODE in tool_text,
        tool_text[:90].replace("\n", " | "),
    )
    answer = "".join(
        b.get("text", "")
        for b in (out.get("content", []) if isinstance(out, dict) else [])
        if b.get("type") == "text"
    )
    check(
        "the model answers with the code word only the search results hold",
        status == 200 and CODE in answer.replace(" ", ""),
        f"{status}: {answer[:80]!r}",
    )

    cited = [
        {
            "role": "user",
            "content": [
                result(
                    1, f"The access phrase for Project Heron is {CODE}.", citations=True
                ),
                {
                    "type": "text",
                    "text": "What is the access phrase? Reply with the phrase only.",
                },
            ],
        }
    ]
    status, out, headers = messages({"messages": cited})
    ignored = {k.lower(): v for k, v in headers.items()}.get(
        "x-eugene-plexus-ignored-settings", ""
    )
    check(
        "citations enabled: answered, and `citations` named ignored",
        status == 200 and "citations" in [s.strip() for s in ignored.split(",")],
        f"{status}; ignored: {ignored!r}",
    )

    before = len(SENT)
    mixed = [
        {
            "role": "user",
            "content": [
                result(1, "one", citations=True),
                result(2, "two"),
                {"type": "text", "text": "hi"},
            ],
        }
    ]
    status, out, _ = messages({"messages": mixed})
    message = (
        (out.get("error", {}) or {}).get("message", "") if isinstance(out, dict) else ""
    )
    check(
        "mixed citation settings: a 400, and nothing reaches the engine",
        status == 400 and "citations" in message and len(SENT) == before,
        f"{status}: {message[:80]!r}",
    )

    memory = {"type": "memory_20250818", "name": "memory"}
    ask = [{"role": "user", "content": "Check your memory directory before you start."}]
    before = len(SENT)
    status, out, _ = messages(
        {
            "messages": ask,
            "system": "You are a careful assistant.",
            "tools": [memory],
            "tool_choice": {"type": "any"},
            "max_tokens": 600,
        }
    )
    sent = SENT[before:]
    engine_body = sent[-1] if sent else {}
    tools = engine_body.get("tools") or []
    names = [t.get("function", {}).get("name") for t in tools]
    enum = (
        tools[0]
        .get("function", {})
        .get("parameters", {})
        .get("properties", {})
        .get("command", {})
        .get("enum")
        if tools
        else None
    )
    check(
        "the memory tool reaches the engine as a function named `memory`",
        names == ["memory"] and set(enum or []) == COMMANDS,
        f"tools {names}, commands {enum}",
    )
    system = next(
        (
            text_of(m)
            for m in engine_body.get("messages", [])
            if m.get("role") == "system"
        ),
        "",
    )
    check(
        "the protocol text follows the request's own system text",
        system.startswith("You are a careful assistant.\n\n" + PROTOCOL_START),
        system[:80].replace("\n", " | "),
    )
    blocks = out.get("content", []) if isinstance(out, dict) else []
    use = next((b for b in blocks if b.get("type") == "tool_use"), None)
    command = (use or {}).get("input", {}).get("command")
    check(
        "the model's call comes back as `tool_use` `memory` with a valid command",
        status == 200
        and out.get("stop_reason") == "tool_use"
        and use is not None
        and use.get("name") == "memory"
        and command in COMMANDS,
        f"{status}; stop {out.get('stop_reason') if isinstance(out, dict) else None}; "
        f"input {(use or {}).get('input')}",
    )
    if use is not None:
        listing = (
            "Here're the files and directories up to 2 levels deep in /memories, excluding "
            "hidden items and node_modules:\n4.0K\t/memories\n1.0K\t/memories/heron.md"
        )
        follow = ask + [
            {"role": "assistant", "content": blocks},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": use["id"],
                        "content": listing,
                    }
                ],
            },
        ]
        before = len(SENT)
        status, out, _ = messages({"messages": follow, "tools": [memory]})
        sent = SENT[before:]
        tool_message = next(
            (
                m
                for m in (sent[-1] if sent else {}).get("messages", [])
                if m.get("role") == "tool"
            ),
            {},
        )
        check(
            "the caller's result is taken and the loop continues",
            status == 200
            and tool_message.get("tool_call_id") == use["id"]
            and "/memories/heron.md" in text_of(tool_message),
            f"{status}; stop {out.get('stop_reason') if isinstance(out, dict) else None}",
        )
    else:
        check(
            "the caller's result is taken and the loop continues",
            False,
            "no call to answer",
        )

    def count(body: dict[str, Any]) -> int:
        s, c, _ = http(
            "POST", f"{GATEWAY}/v1/messages/count_tokens", {"model": MODEL, **body}
        )
        return (
            int(c.get("input_tokens", -1)) if s == 200 and isinstance(c, dict) else -1
        )

    bare = count({"messages": [{"role": "user", "content": "hi"}]})
    with_result = count(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        result(
                            1, "Project Heron moved its weekly meeting to Thursdays."
                        ),
                        {"type": "text", "text": "hi"},
                    ],
                }
            ]
        }
    )
    with_memory = count(
        {"messages": [{"role": "user", "content": "hi"}], "tools": [memory]}
    )
    check(
        "count_tokens counts the search result and the memory tool",
        bare > 0 and with_result > bare + 10 and with_memory > bare + 50,
        f"bare {bare}, with a result {with_result}, with the memory tool {with_memory}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
