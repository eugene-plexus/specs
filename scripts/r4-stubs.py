#!/usr/bin/env python3
"""Stub agent and stub inference-driver for the R4 live run.

The thing under test is the **gateway's** Anthropic door, so everything
around it is a stub and the gateway is real. That is the opposite of the
usual arrangement here and it is deliberate: this run's question is
whether a real Claude Code can drive a real gateway, and a real engine
would add minutes of model loading to every iteration while answering no
part of that question.

What the stubs implement is only what `RoutingTable` and `DriverClient`
actually read -- `/v1/components`, `/v1/runtimes`, `/v1/node` on the
agent; `/v1/info`, `/v1/generate` and `/v1/generate/stream` on the
driver. The driver **fragments** its tool-call arguments across two
frames, because a stub that emitted a whole call in one frame would pass
every assertion a broken accumulator also passes.

Usage:
    python r4-stubs.py agent  --port 8179 --driver-port 8181
    python r4-stubs.py driver --port 8181 --model local-qwen [--tool]
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE: dict[str, object] = {}


def _json(handler: BaseHTTPRequestHandler, payload: object, status: int = 200) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class AgentHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:  # noqa: D102
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/v1/components":
            _json(
                self,
                {
                    "components": [
                        {
                            "name": "stub-driver",
                            "kind": "inference-driver",
                            "url": f"http://127.0.0.1:{STATE['driver_port']}",
                            "status": "running",
                        }
                    ]
                },
            )
        elif path == "/v1/runtimes":
            # No supervised runtimes. The driver reports `runtime: null`
            # on /v1/info, so nothing needs joining and the readiness
            # gate is the driver's own liveness probe.
            _json(self, {"runtimes": []})
        elif path == "/v1/node":
            _json(self, {"name": "stub-node", "enrolled": False})
        elif path == "/healthz":
            _json(self, {"status": "ok"})
        else:
            _json(self, {"detail": "not found"}, 404)


class DriverHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:  # noqa: D102
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] == "/v1/info":
            _json(
                self,
                {
                    "backend": "openai_compat_http",
                    "modelId": STATE["model"],
                    "runtime": None,
                    "capabilities": {
                        "toolCalling": True,
                        "streaming": True,
                        "maxContextTokens": 32768,
                    },
                    "version": "0.0.0-stub",
                },
            )
            return
        _json(self, {"detail": "not found"}, 404)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        request = self._read_body()
        # Recorded so the run can assert what the GATEWAY sent down --
        # that `thinking` never arrived, that a tool_result became a
        # `tool` role message -- from a file rather than from the
        # client's account of itself.
        with open(STATE["record"], "a", encoding="utf-8") as fh:  # type: ignore[arg-type]
            fh.write(json.dumps({"path": path, "request": request}) + "\n")

        wants_tool = bool(STATE.get("tool")) and not _has_tool_result(request)

        if path == "/v1/generate":
            if wants_tool:
                _json(
                    self,
                    {
                        "content": None,
                        "toolCalls": [
                            {
                                "id": "call_stub_1",
                                "type": "function",
                                "function": {
                                    "name": "Glob",
                                    "arguments": '{"pattern": "*.py"}',
                                },
                            }
                        ],
                        "finishReason": "tool_calls",
                        "backend": "openai_compat_http",
                        "modelId": STATE["model"],
                        "usage": {
                            "promptTokens": 11,
                            "completionTokens": 7,
                            "totalTokens": 18,
                        },
                        "latencyMs": 3,
                    },
                )
                return
            _json(
                self,
                {
                    "content": STATE["answer"],
                    "finishReason": "stop",
                    "backend": "openai_compat_http",
                    "modelId": STATE["model"],
                    "usage": {"promptTokens": 11, "completionTokens": 3, "totalTokens": 14},
                    "latencyMs": 3,
                },
            )
            return

        if path == "/v1/generate/stream":
            self._stream(wants_tool)
            return

        _json(self, {"detail": "not found"}, 404)

    def _stream(self, wants_tool: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def frame(name: str, data: object) -> None:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        if wants_tool:
            args = '{"pattern": "*.py"}'
            half = len(args) // 2
            # **Fragmented on purpose.** A stub that emitted the whole
            # call in one frame would pass every assertion a broken
            # accumulator also passes -- which is exactly the defect
            # step 6's first acceptance run had, one layer down.
            frame(
                "token",
                {
                    "toolCalls": [
                        {
                            "index": 0,
                            "id": "call_stub_1",
                            "type": "function",
                            "function": {"name": "Glob", "arguments": args[:half]},
                        }
                    ]
                },
            )
            frame("token", {"toolCalls": [{"index": 0, "function": {"arguments": args[half:]}}]})
            frame(
                "done",
                {
                    "content": None,
                    "toolCalls": [
                        {
                            "id": "call_stub_1",
                            "type": "function",
                            "function": {"name": "Glob", "arguments": args},
                        }
                    ],
                    "finishReason": "tool_calls",
                    "backend": "openai_compat_http",
                    "modelId": STATE["model"],
                    "usage": {"promptTokens": 11, "completionTokens": 7, "totalTokens": 18},
                    "latencyMs": 3,
                },
            )
            return

        answer = str(STATE["answer"])
        for piece in answer.split(" "):
            frame("token", {"text": piece + " "})
        frame(
            "done",
            {
                "content": answer,
                "finishReason": "stop",
                "backend": "openai_compat_http",
                "modelId": STATE["model"],
                "usage": {"promptTokens": 11, "completionTokens": 3, "totalTokens": 14},
                "latencyMs": 3,
            },
        )


def _has_tool_result(request: dict) -> bool:
    """Whether the conversation already carries a tool result.

    The stub asks for a tool once and then answers, which is what makes
    the loop terminate. Without this it would call the same tool for
    ever, and the run would time out rather than fail.
    """
    for message in request.get("messages") or []:
        if isinstance(message, dict) and message.get("role") == "tool":
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("role", choices=["agent", "driver"])
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--driver-port", type=int, default=0)
    ap.add_argument("--model", default="local-qwen")
    ap.add_argument("--answer", default="ok")
    ap.add_argument("--tool", action="store_true")
    ap.add_argument("--record", default="driver-requests.jsonl")
    args = ap.parse_args()

    STATE.update(
        driver_port=args.driver_port,
        model=args.model,
        answer=args.answer,
        tool=args.tool,
        record=args.record,
    )
    handler = AgentHandler if args.role == "agent" else DriverHandler
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"{args.role} stub on 127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
