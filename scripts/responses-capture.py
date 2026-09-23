#!/usr/bin/env python3
"""Capture what an OpenAI-wire client (Codex CLI) sends, 2026-09-23.

An instrument, not a test: records every request -- headers (credential
truncated) and body, long text and tool schemas elided -- and answers just
enough of the Responses stream for the client to finish a turn. With
`toolloop` the first turn is a `function_call` to `shell`, so the follow-up
shows how the client hands a call back.

    python responses-capture.py 9187 capture.txt [toolloop]

    # an isolated CODEX_HOME whose config.toml names a custom provider:
    #   model_provider = "ep"
    #   [model_providers.ep]
    #   base_url = "http://127.0.0.1:9187/v1"
    #   env_key = "EP_TEST_KEY"
    #   wire_api = "responses"
    CODEX_HOME=<dir> EP_TEST_KEY=x codex exec --skip-git-repo-check "say ok"

Behind docs/design/responses-and-completions.md.
"""


import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = sys.argv[2]
PORT = int(sys.argv[1])
TOOLLOOP = len(sys.argv) > 3 and sys.argv[3] == "toolloop"
TURN = 0


def log(text: str) -> None:
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(text)


def sse(events):
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _record(self, body: bytes):
        log(f"\n######## {self.command} {self.path}\n")
        for k, v in self.headers.items():
            if k.lower() == "authorization":
                v = v[:14] + "..."
            log(f"  {k}: {v}\n")
        try:
            parsed = json.loads(body)
            for m in parsed.get("input", []) if isinstance(parsed.get("input"), list) else []:
                for c in m.get("content", []) if isinstance(m, dict) and isinstance(m.get("content"), list) else []:
                    if isinstance(c, dict) and isinstance(c.get("text"), str) and len(c["text"]) > 300:
                        c["text"] = c["text"][:300] + f"...<{len(c['text'])} chars>"
            if isinstance(parsed.get("instructions"), str) and len(parsed["instructions"]) > 300:
                parsed["instructions"] = parsed["instructions"][:300] + f"...<{len(parsed['instructions'])} chars>"
            tools = parsed.get("tools")
            if isinstance(tools, list):
                parsed["tools"] = [
                    {k: (v if k in ("type", "name") else "...") for k, v in t.items()} for t in tools
                ]
            log(json.dumps(parsed, indent=2)[:12000] + "\n")
        except Exception:
            log(body[:2000].decode("utf-8", "replace") + "\n")

    def do_GET(self):
        self._record(b"")
        if self.path.rstrip("/").endswith("/models"):
            payload = json.dumps({"object": "list", "data": [{"id": "qwen3-0.6b", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        self._record(body)
        global TURN
        if self.path.split("?")[0].endswith("/responses") and TURN == 0 and TOOLLOOP:
            TURN += 1
            call = {"id": "fc_1", "type": "function_call", "status": "completed", "call_id": "call_1",
                    "name": "shell", "arguments": json.dumps({"command": ["cmd", "/c", "echo hi"]})}
            rid = "resp_tool"
            payload = sse([
                ("response.created", {"type": "response.created", "response": {"id": rid, "object": "response", "status": "in_progress", "output": []}}),
                ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": {**call, "status": "in_progress", "arguments": ""}}),
                ("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": "fc_1", "output_index": 0, "delta": call["arguments"]}),
                ("response.function_call_arguments.done", {"type": "response.function_call_arguments.done", "item_id": "fc_1", "output_index": 0, "arguments": call["arguments"]}),
                ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": call}),
                ("response.completed", {"type": "response.completed", "response": {"id": rid, "object": "response", "status": "completed", "output": [call], "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}}),
            ])
            ctype = "text/event-stream"
        elif self.path.split("?")[0].endswith("/responses"):
            rid = f"resp_{int(time.time()*1000)}"
            item = {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "ok", "annotations": []}]}
            payload = sse([
                ("response.created", {"type": "response.created", "response": {"id": rid, "object": "response", "status": "in_progress", "output": []}}),
                ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}}),
                ("response.content_part.added", {"type": "response.content_part.added", "item_id": "msg_1", "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": ""}}),
                ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0, "content_index": 0, "delta": "ok"}),
                ("response.output_text.done", {"type": "response.output_text.done", "item_id": "msg_1", "output_index": 0, "content_index": 0, "text": "ok"}),
                ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
                ("response.completed", {"type": "response.completed", "response": {"id": rid, "object": "response", "status": "completed", "output": [item], "usage": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11}}}),
            ])
            ctype = "text/event-stream"
        elif self.path.split("?")[0].endswith("/chat/completions"):
            chunk = {"id": "c1", "object": "chat.completion.chunk", "model": "qwen3-0.6b",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": None}]}
            end = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            payload = f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(end)}\n\ndata: [DONE]\n\n".encode()
            ctype = "text/event-stream"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


open(OUT, "w").close()
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
