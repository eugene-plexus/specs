#!/usr/bin/env python3
"""Capture a real client's multi-turn session, to see what a prompt cache sees.

An instrument, not a test (2026-10-02, behind the prompt-cache measurement).
A prompt cache can only reuse what is the same, token for token, from the
start of the prompt. So the first question about caching through Eugene is
not about Eugene at all: does the client send the same prefix twice? This
listener answers a real Claude Code (Anthropic Messages) or Codex (OpenAI
Responses) with a scripted run of read-only tool calls, so one session makes
several requests, each a strict continuation of the last if the client is
cache-friendly, and records every request body whole to JSONL.

    python prompt-cache-capture.py --port 9311 --out run.jsonl --turns 4 \\
        --read-dir <a directory of files for the tools to read>

It answers by state, not by count: the reply to a request is chosen from how
many tool results the request already carries, so a side request (a title, a
quota probe) gets a plain text answer and does not advance the script.

Credentials are redacted on the way to disk. The bodies hold the client's
own system prompt, which is the vendor's text: keep the JSONL out of the repo.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SECRET = re.compile(r"(sk-ant-(?:oat01|api03)-|sk-(?:proj|or-v1)-)[A-Za-z0-9_-]{16,}")
_LOCK = threading.Lock()
_STARTED = time.perf_counter()
_N = 0


def _redact(text: str) -> str:
    return _SECRET.sub(r"\1<REDACTED>", text)


def _record(out: Path, path: str, headers: dict, body: bytes) -> int:
    global _N
    with _LOCK:
        _N += 1
        n = _N
        line = {
            "n": n,
            "t": round(time.perf_counter() - _STARTED, 3),
            "path": path,
            "headers": {k: (v[:12] + "..." if k.lower() in ("authorization", "x-api-key") else v)
                        for k, v in headers.items()},
            "body": json.loads(body) if body else None,
        }
        with out.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(_redact(json.dumps(line)) + "\n")
    return n


# ----------------------------------------------------------- Anthropic side


def _a_sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(f"event: {k}\ndata: {json.dumps(v)}\n\n" for k, v in events).encode()


def _a_start(model: str, n: int) -> tuple[str, dict]:
    return ("message_start", {"type": "message_start", "message": {
        "id": f"msg_cap_{n}", "type": "message", "role": "assistant", "model": model,
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 1}}})


def _a_text(model: str, n: int, text: str) -> bytes:
    return _a_sse([
        _a_start(model, n),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 4}}),
        ("message_stop", {"type": "message_stop"}),
    ])


def _a_tool(model: str, n: int, step: int, name: str, args: dict) -> bytes:
    raw = json.dumps(args)
    return _a_sse([
        _a_start(model, n),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": f"Step {step}."}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {
            "type": "tool_use", "id": f"toolu_cap_{step:04d}", "name": name, "input": {}}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
                                 "delta": {"type": "input_json_delta", "partial_json": raw}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                           "usage": {"output_tokens": 9}}),
        ("message_stop", {"type": "message_stop"}),
    ])


def _a_results(body: dict) -> int:
    count = 0
    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, list):
            count += sum(1 for p in content if isinstance(p, dict) and p.get("type") == "tool_result")
    return count


def _a_script(read_dir: Path, turns: int) -> list[tuple[str, dict]]:
    files = sorted(p for p in read_dir.iterdir() if p.is_file())
    steps: list[tuple[str, dict]] = [("Glob", {"pattern": "*", "path": str(read_dir)})]
    for path in files:
        steps.append(("Read", {"file_path": str(path)}))
    steps.append(("Grep", {"pattern": "def ", "path": str(read_dir), "output_mode": "content"}))
    return steps[:turns]


# ----------------------------------------------------------- Responses side


def _r_sse(events: list[dict]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _r_completed(rid: str, output: list) -> dict:
    return {"type": "response.completed", "response": {
        "id": rid, "object": "response", "status": "completed", "output": output,
        "usage": {"input_tokens": 100, "output_tokens": 5, "total_tokens": 105}}}


def _r_text(rid: str, text: str) -> bytes:
    item = {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}
    return _r_sse([
        {"type": "response.created", "response": {"id": rid, "object": "response",
                                                  "status": "in_progress", "output": []}},
        {"type": "response.output_item.added", "output_index": 0,
         "item": {**item, "status": "in_progress", "content": []}},
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0,
         "content_index": 0, "delta": text},
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        _r_completed(rid, [item]),
    ])


def _r_tool(rid: str, step: int, name: str, args: dict) -> bytes:
    call = {"id": f"fc_{step}", "type": "function_call", "status": "completed",
            "call_id": f"call_cap_{step}", "name": name, "arguments": json.dumps(args)}
    return _r_sse([
        {"type": "response.created", "response": {"id": rid, "object": "response",
                                                  "status": "in_progress", "output": []}},
        {"type": "response.output_item.added", "output_index": 0,
         "item": {**call, "status": "in_progress", "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "item_id": call["id"],
         "output_index": 0, "delta": call["arguments"]},
        {"type": "response.function_call_arguments.done", "item_id": call["id"],
         "output_index": 0, "arguments": call["arguments"]},
        {"type": "response.output_item.done", "output_index": 0, "item": call},
        _r_completed(rid, [call]),
    ])


def _r_results(body: dict) -> int:
    items = body.get("input")
    if not isinstance(items, list):
        return 0
    return sum(1 for i in items if isinstance(i, dict) and i.get("type") == "function_call_output")


def _r_shell(body: dict, command: str) -> tuple[str, dict]:
    """Whatever shell tool this client version offers, called with `command`."""
    names = {t.get("name") for t in body.get("tools") or [] if isinstance(t, dict)}
    if "shell_command" in names:
        return "shell_command", {"command": command}
    if "exec_command" in names:
        return "exec_command", {"cmd": command}
    return "shell", {"command": ["cmd", "/c", command]}


def _r_script(read_dir: Path, turns: int) -> list[str]:
    files = sorted(p for p in read_dir.iterdir() if p.is_file())
    steps = [f'dir /b "{read_dir}"'] + [f'type "{p}"' for p in files]
    steps.append(f'findstr /n "def " "{read_dir}\\*"')
    return steps[:turns]


# ------------------------------------------------------------------ server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--turns", type=int, default=4, help="tool calls before the final answer")
    ap.add_argument("--read-dir", type=Path, required=True)
    args = ap.parse_args()
    if 8079 <= args.port <= 8290:
        raise SystemExit("ports 8079-8290 belong to the live install on this box")
    args.out.write_text("", encoding="utf-8")
    a_steps = _a_script(args.read_dir.resolve(), args.turns)
    r_steps = _r_script(args.read_dir.resolve(), args.turns)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # noqa: D401 -- silence the default log
            pass

        def _send(self, status: int, payload: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            # Anthropic names every response; a client that echoes the
            # previous one into its next prompt can only do so if it has one.
            self.send_header("request-id", f"req_cap{_N:06d}{int(time.time() * 1000) % 10**8:08d}")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # models lists and health probes
            _record(args.out, self.path, dict(self.headers), b"")
            self._send(200, json.dumps({"object": "list", "data": [
                {"id": "cache-probe", "object": "model", "owned_by": "capture"}]}).encode(),
                "application/json")

        def do_HEAD(self):
            self._send(200, b"", "text/plain")

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            n = _record(args.out, self.path, dict(self.headers), raw)
            body = json.loads(raw) if raw else {}
            path = self.path.split("?")[0]
            if path.endswith("/messages/count_tokens"):
                self._send(200, b'{"input_tokens": 4242}', "application/json")
                return
            if path.endswith("/messages"):
                model = body.get("model", "cache-probe")
                done = _a_results(body)
                if body.get("tools") and done < len(a_steps):
                    name, targs = a_steps[done]
                    payload = _a_tool(model, n, done + 1, name, targs)
                else:
                    payload = _a_text(model, n, "Done." if body.get("tools") else "Cache probe")
                self._send(200, payload, "text/event-stream")
                return
            if path.endswith("/responses"):
                rid = f"resp_cap_{n}"
                done = _r_results(body)
                if body.get("tools") and done < len(r_steps):
                    name, targs = _r_shell(body, r_steps[done])
                    payload = _r_tool(rid, done + 1, name, targs)
                else:
                    payload = _r_text(rid, "Done.")
                self._send(200, payload, "text/event-stream")
                return
            self._send(404, b'{"error": "not captured"}', "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"capturing on http://127.0.0.1:{args.port} -> {args.out}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
