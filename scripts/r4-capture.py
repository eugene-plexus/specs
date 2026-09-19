#!/usr/bin/env python3
"""R4 step one: capture what a real Claude Code sends, and how it reacts.

This is an instrument, not a test. It stands up a throwaway listener on
loopback that speaks just enough of the Anthropic Messages wire for a real
`claude` CLI to complete a turn, and records every request byte for byte --
the request line, every header in the order and casing the client chose, and
the body. Nothing is normalised, because the premise under test is exactly
which header carries the key.

Why an instrument and not reasoning: the roadmap's R4 rests on *upstream
client* behaviour, and this project has a long record of reasoning about
somebody else's wire and being wrong about it (the hub's 401-for-missing-repo,
llama.cpp's asset naming, Ollama's resolved context window). Point it at the
real thing and read the answer.

Modes
-----
    capture   record requests, answer with a plain text turn
    toolloop  answer the first turn with a streamed tool_use for a read-only
              tool, so the follow-up request carries a real `tool_result`
    <status>  answer /v1/messages with that HTTP status and an Anthropic-shaped
              error body, and record how many times the client tries again

Usage
-----
    python r4-capture.py --port 8931 --out capture.txt --mode capture

    # then, against it, with a config dir that holds no OAuth credential:
    CLAUDE_CONFIG_DIR=/tmp/cleancfg \
    ANTHROPIC_BASE_URL=http://127.0.0.1:8931 \
    ANTHROPIC_API_KEY=<key approved in that config dir> \
        claude -p "reply with the single word ok" --model qwen3-8b

**An ambient OAuth login beats `ANTHROPIC_API_KEY`**, so a capture run taken
without an isolated `CLAUDE_CONFIG_DIR` records the operator's real
`sk-ant-oat01-...` subscription token instead of the key under test. This
script redacts what it recognises on the way to disk; the isolation is still
the thing that makes the reading true.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import socketserver
import threading
import time
from pathlib import Path

# A live Anthropic credential must never reach the record, whoever's it is.
_SECRET = re.compile(r"sk-ant-(oat01|api03)-[A-Za-z0-9_-]{20,}")

_READ_ONLY_TOOL = "Glob"
_READ_ONLY_INPUT = '{"pattern": "*.py"}'


def _redact(text: str) -> str:
    return _SECRET.sub(r"sk-ant-\1-<REDACTED-LIVE-CREDENTIAL>", text)


class Recorder:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._started = time.time()
        self._requests = 0
        self._messages = 0
        path.write_text("", encoding="utf-8")

    def write(self, text: str) -> None:
        with self._lock:
            with self._path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(_redact(text))
                fh.flush()

    def next_request(self) -> tuple[int, float]:
        with self._lock:
            self._requests += 1
            return self._requests, time.time() - self._started

    def next_message(self) -> int:
        with self._lock:
            self._messages += 1
            return self._messages


def _sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(
        f"event: {name}\r\ndata: {json.dumps(data)}\r\n\r\n" for name, data in events
    ).encode("utf-8")


def _message_start(model: str) -> tuple[str, dict]:
    return (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_r4_capture",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 11, "output_tokens": 1},
            },
        },
    )


def _text_turn(model: str, text: str) -> bytes:
    return _sse(
        [
            _message_start(model),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 4},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


def _tool_use_turn(model: str) -> bytes:
    """A tool call, fragmented, because that is what a real backend does."""
    half = len(_READ_ONLY_INPUT) // 2
    return _sse(
        [
            _message_start(model),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Looking."},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_r4_capture_0001",
                        "name": _READ_ONLY_TOOL,
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": _READ_ONLY_INPUT[:half],
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": _READ_ONLY_INPUT[half:],
                    },
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 1}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 9},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    409: "invalid_request_error",
    429: "rate_limit_error",
    500: "api_error",
    503: "overloaded_error",
}

_REASONS = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _trim(body: dict) -> list:
    """The message list, with the 120 KB of system prompt cut out of it."""
    out = []
    for m in body.get("messages", []):
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": m["role"], "content": f"<str len {len(content)}>"})
            continue
        blocks = []
        for b in content:
            copy = dict(b)
            text = copy.get("text")
            if isinstance(text, str) and len(text) > 200:
                copy["text"] = text[:200] + f"...<truncated, {len(text)} chars>"
            inner = copy.get("content")
            if isinstance(inner, str) and len(inner) > 200:
                copy["content"] = inner[:200] + "..."
            blocks.append(copy)
        out.append({"role": m["role"], "content": blocks})
    return out


def build_handler(rec: Recorder, mode: str):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:  # noqa: C901
            conn: socket.socket = self.request
            conn.settimeout(60)
            buf = b""
            try:
                while b"\r\n\r\n" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buf += chunk
            except OSError:
                return

            head, _, rest = buf.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            request_line = lines[0].decode("latin-1")
            headers = []
            for raw in lines[1:]:
                name, _, value = raw.decode("latin-1").partition(":")
                headers.append((name, value.strip()))
            lookup = {n.lower(): v for n, v in headers}

            body = rest
            if "content-length" in lookup:
                want = int(lookup["content-length"])
                while len(body) < want:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    body += chunk

            seq, elapsed = rec.next_request()
            method, path = (request_line.split(" ") + ["", ""])[:2]

            parts = [
                f"\n\n################ REQUEST {seq}  (+{elapsed:.2f}s)\n",
                f"REQUEST-LINE: {request_line}\n",
                "HEADERS (verbatim, in the order sent):\n",
            ]
            parts += [f"  {n}: {v}\n" for n, v in headers]
            parts.append(f"BODY-BYTES: {len(body)}\n")

            parsed: dict = {}
            try:
                parsed = json.loads(body.decode("utf-8"))
            except Exception:  # noqa: BLE001
                if body:
                    parts.append("BODY (not JSON):\n")
                    parts.append(body.decode("utf-8", "replace")[:2000])
                    parts.append("\n")

            if parsed:
                shape = {k: parsed[k] for k in parsed if k not in {"messages", "system", "tools"}}
                parts.append("BODY SHAPE (messages/system/tools summarised):\n")
                parts.append(json.dumps(shape, indent=2, ensure_ascii=False))
                parts.append("\n")
                sysv = parsed.get("system")
                if isinstance(sysv, list):
                    parts.append(f"SYSTEM: {len(sysv)} blocks\n")
                    for i, b in enumerate(sysv):
                        parts.append(
                            f"  [{i}] keys={sorted(b.keys())} "
                            f"cache_control={b.get('cache_control')} "
                            f"len={len(b.get('text', ''))} "
                            f"head={b.get('text', '')[:70]!r}\n"
                        )
                tools = parsed.get("tools") or []
                parts.append(f"TOOLS: {len(tools)} -> {[t.get('name') for t in tools]}\n")
                parts.append(f"MESSAGES:\n{json.dumps(_trim(parsed), indent=2, ensure_ascii=False)}\n")

            rec.write("".join(parts))

            model = parsed.get("model", "r4-capture-model")

            if method == "HEAD" or "/v1/messages" not in path:
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
                return

            if mode.isdigit():
                status = int(mode)
                doc = {
                    "type": "error",
                    "error": {
                        "type": _ERROR_TYPES.get(status, "api_error"),
                        "message": f"r4-capture refusal with status {status}",
                    },
                }
                payload = json.dumps(doc).encode()
                conn.sendall(
                    f"HTTP/1.1 {status} {_REASONS.get(status, 'Error')}\r\n".encode()
                    + b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                    + payload
                )
                return

            turn = rec.next_message()
            if mode == "toolloop" and turn == 1:
                payload = _tool_use_turn(model)
            else:
                payload = _text_turn(model, f"{mode}-ok")

            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                b"Cache-Control: no-cache\r\n"
                + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                + payload
            )

    return Handler


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8931)
    ap.add_argument("--out", type=Path, default=Path("r4-capture.txt"))
    ap.add_argument(
        "--mode",
        default="capture",
        help="capture | toolloop | an HTTP status such as 400, 401, 403, 404, 429, 500, 503",
    )
    args = ap.parse_args()

    rec = Recorder(args.out)
    with Server(("127.0.0.1", args.port), build_handler(rec, args.mode)) as srv:
        print(f"r4-capture mode={args.mode} on 127.0.0.1:{args.port} -> {args.out}", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
