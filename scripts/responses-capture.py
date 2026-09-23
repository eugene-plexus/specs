#!/usr/bin/env python3
"""Capture what an OpenAI-wire client (Codex CLI) sends, 2026-09-23.

An instrument, not a test: records every request -- headers (credential
truncated) and body, long text and tool schemas elided -- and answers just
enough of the Responses stream for the client to finish a turn. The full,
unelided bodies go to `<capture>.jsonl`, one per line, for fixtures.

    python responses-capture.py 9187 capture.txt [MODE]

MODE:
  capture    (default) every turn answers "ok"
  toolloop   turn 1 is a `function_call` to `shell` (the command in
             $CAP_COMMAND, a JSON array), so the follow-up shows
             how the client hands a call back
  reasoning  as toolloop, with a `reasoning` item (summary + encrypted
             content) ahead of the call, so the follow-up shows whether and
             how the client echoes reasoning back
  rawreasoning  as reasoning, but the text rides in `content` as
             `reasoning_text` (how open-weight models report it) with no
             summary, streamed as `response.reasoning_text.delta`
  incomplete the answer ends in `response.incomplete` (max_output_tokens)
  viewimage  turn 1 calls `view_image` on the path in $CAP_IMAGE_PATH,
             so the follow-up shows how the client hands an
             image back
  failed     the stream opens, then ends in `response.failed` (`failed=CODE`
             sets its error code)
  errorevent the stream opens, then ends in a bare `error` event
  <status>   every request is answered with that HTTP status and an
             OpenAI error envelope, to count what the client does next
  slow:N     send nothing for N seconds, then answer "ok" -- does the
             client's stream idle timeout run before the first event?
  comment:N  as slow:N, with an SSE comment line every 2 s -- does a
             comment keep the stream alive?
  early:N    `response.created` at once, then N silent seconds, then "ok"
  inprogress:N  as early:N, with `response.in_progress` every 2 s

    # an isolated CODEX_HOME whose config.toml names a custom provider:
    #   model_provider = "ep"
    #   [model_providers.ep]
    #   base_url = "http://127.0.0.1:9187/v1"
    #   env_key = "EP_TEST_KEY"
    #   wire_api = "responses"
    CODEX_HOME=<dir> EP_TEST_KEY=x codex exec --skip-git-repo-check "say ok"

Behind docs/design/responses-and-completions.md.
"""

import copy
import os
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = sys.argv[2]
RAW = OUT.rsplit(".", 1)[0] + ".jsonl"
PORT = int(sys.argv[1])
MODE = sys.argv[3] if len(sys.argv) > 3 else "capture"
TURN = 0
CMD = json.dumps(["cmd", "/c", "echo hi"])
STARTED = time.perf_counter()


def log(text: str) -> None:
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(text)


def sse(events):
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


def created(rid):
    return (
        "response.created",
        {
            "type": "response.created",
            "response": {"id": rid, "object": "response", "status": "in_progress", "output": []},
        },
    )


def completed(rid, output, out_tokens):
    return (
        "response.completed",
        {
            "type": "response.completed",
            "response": {
                "id": rid,
                "object": "response",
                "status": "completed",
                "output": output,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": out_tokens,
                    "total_tokens": 10 + out_tokens,
                },
            },
        },
    )


def text_turn(rid, text="ok"):
    item = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    return [
        created(rid),
        (
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**item, "status": "in_progress", "content": []},
            },
        ),
        (
            "response.content_part.added",
            {
                "type": "response.content_part.added",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": ""},
            },
        ),
        (
            "response.output_text.delta",
            {
                "type": "response.output_text.delta",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "delta": text,
            },
        ),
        (
            "response.output_text.done",
            {
                "type": "response.output_text.done",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "text": text,
            },
        ),
        (
            "response.output_item.done",
            {"type": "response.output_item.done", "output_index": 0, "item": item},
        ),
        completed(rid, [item], 1),
    ]


def tool_turn(rid, with_reasoning, raw=False):
    call = {
        "id": "fc_1",
        "type": "function_call",
        "status": "completed",
        "call_id": "call_1",
        "name": "shell",
        "arguments": json.dumps({"command": json.loads(os.environ.get("CAP_COMMAND") or CMD)}),
    }
    events = [created(rid)]
    output = []
    index = 0
    if with_reasoning:
        reasoning = {
            "id": "rs_1",
            "type": "reasoning",
            "summary": [] if raw else [{"type": "summary_text", "text": "I should run echo."}],
            "encrypted_content": "CAPTURE-OPAQUE-REASONING-1",
        }
        if raw:
            reasoning["content"] = [{"type": "reasoning_text", "text": "RAW: I should run echo."}]
        delta = (
            (
                "response.reasoning_text.delta",
                {
                    "type": "response.reasoning_text.delta",
                    "item_id": "rs_1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "RAW: I should run echo.",
                },
            )
            if raw
            else (
                "response.reasoning_summary_text.delta",
                {
                    "type": "response.reasoning_summary_text.delta",
                    "item_id": "rs_1",
                    "output_index": 0,
                    "summary_index": 0,
                    "delta": "I should run echo.",
                },
            )
        )
        events += [
            (
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {"id": "rs_1", "type": "reasoning", "summary": []},
                },
            ),
            delta,
            (
                "response.output_item.done",
                {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
            ),
        ]
        output.append(reasoning)
        index = 1
    events += [
        (
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": index,
                "item": {**call, "status": "in_progress", "arguments": ""},
            },
        ),
        (
            "response.function_call_arguments.delta",
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": index,
                "delta": call["arguments"],
            },
        ),
        (
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_1",
                "output_index": index,
                "arguments": call["arguments"],
            },
        ),
        (
            "response.output_item.done",
            {"type": "response.output_item.done", "output_index": index, "item": call},
        ),
    ]
    output.append(call)
    events.append(completed(rid, output, 5))
    return events


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _record(self, body: bytes):
        global TURN
        log(f"\n######## t+{time.perf_counter() - STARTED:.2f}s {self.command} {self.path}\n")
        for k, v in self.headers.items():
            if k.lower() == "authorization":
                v = v[:14] + "..."
            log(f"  {k}: {v}\n")
        try:
            parsed = json.loads(body)
        except Exception:
            log(body[:2000].decode("utf-8", "replace") + "\n")
            return
        with open(RAW, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"path": self.path, "body": parsed}) + "\n")
        shown = copy.deepcopy(parsed)
        for m in shown.get("input", []) if isinstance(shown.get("input"), list) else []:
            if not isinstance(m, dict):
                continue
            for c in m.get("content", []) if isinstance(m.get("content"), list) else []:
                if isinstance(c, dict) and isinstance(c.get("text"), str) and len(c["text"]) > 300:
                    c["text"] = c["text"][:300] + f"...<{len(c['text'])} chars>"
                if isinstance(c, dict) and isinstance(c.get("image_url"), str):
                    c["image_url"] = c["image_url"][:40] + f"...<{len(c['image_url'])} chars>"
        if isinstance(shown.get("instructions"), str) and len(shown["instructions"]) > 300:
            shown["instructions"] = (
                shown["instructions"][:300] + f"...<{len(shown['instructions'])} chars>"
            )
        tools = shown.get("tools")
        if isinstance(tools, list):
            shown["tools"] = [
                {k: (v if k in ("type", "name", "strict") else "...") for k, v in t.items()}
                for t in tools
            ]
        log(json.dumps(shown, indent=2)[:12000] + "\n")

    def _send(self, status, payload: bytes, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._record(b"")
        if self.path.split("?")[0].rstrip("/").endswith("/models"):
            payload = json.dumps(
                {"object": "list", "data": [{"id": "qwen3-0.6b", "object": "model"}]}
            ).encode()
            self._send(200, payload, "application/json")
            return
        self._send(404, b"", "text/plain")

    def do_POST(self):
        global TURN
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        self._record(body)
        path = self.path.split("?")[0]
        if not path.endswith("/responses"):
            self._send(404, b"", "text/plain")
            return
        if MODE.isdigit():
            status = int(MODE)
            payload = json.dumps(
                {
                    "error": {
                        "message": f"CAPTURE-{status}: the capture listener refused this.",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": None,
                    }
                }
            ).encode()
            log(f"  -> answered {status}\n")
            self._send(status, payload, "application/json")
            return
        TURN += 1
        rid = f"resp_{int(time.time() * 1000)}"
        if ":" in MODE:
            kind, seconds = MODE.split(":")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                if kind in ("early", "inprogress"):
                    self.wfile.write(sse([created(rid)]))
                    self.wfile.flush()
                deadline = time.perf_counter() + float(seconds)
                while time.perf_counter() < deadline:
                    time.sleep(min(2.0, deadline - time.perf_counter()))
                    if kind == "comment":
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    if kind == "inprogress":
                        name, data = created(rid)
                        data = {**data, "type": "response.in_progress"}
                        self.wfile.write(sse([("response.in_progress", data)]))
                        self.wfile.flush()
                events = text_turn(rid)
                if kind in ("early", "inprogress"):
                    events = events[1:]
                self.wfile.write(sse(events))
                self.wfile.flush()
                log(f"  -> answered after {seconds}s ({kind})\n")
            except OSError as e:
                log(f"  -> client left: {e!r}\n")
            self.close_connection = True
            return
        if MODE in ("toolloop", "reasoning", "rawreasoning") and TURN == 1:
            events = tool_turn(
                rid, with_reasoning=MODE != "toolloop", raw=MODE == "rawreasoning"
            )
        elif MODE == "incomplete":
            events = text_turn(rid, "ok, but cut")
            name, data = events[-1]
            response = {
                **data["response"],
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            }
            events[-1] = (
                "response.incomplete",
                {"type": "response.incomplete", "response": response},
            )
        elif MODE == "viewimage" and TURN == 1:
            events = tool_turn(rid, with_reasoning=False)
            path = os.environ["CAP_IMAGE_PATH"]
            for _, data in events:
                item = data.get("item") or {}
                if item.get("type") == "function_call":
                    item["name"] = "view_image"
                    item["arguments"] = json.dumps({"path": path})
                if data.get("type") == "response.function_call_arguments.delta":
                    data["delta"] = json.dumps({"path": path})
                if data.get("type") == "response.function_call_arguments.done":
                    data["arguments"] = json.dumps({"path": path})
                for out in (data.get("response") or {}).get("output") or []:
                    if out.get("type") == "function_call":
                        out["name"] = "view_image"
                        out["arguments"] = json.dumps({"path": path})
        elif MODE == "failed" or MODE.startswith("failed="):
            code = MODE.partition("=")[2] or "server_error"
            events = [
                created(rid),
                (
                    "response.failed",
                    {
                        "type": "response.failed",
                        "response": {
                            "id": rid,
                            "object": "response",
                            "status": "failed",
                            "output": [],
                            "error": {
                                "code": code,
                                "message": "CAPTURE-FAILED: the backend stopped.",
                            },
                        },
                    },
                ),
            ]
        elif MODE == "errorevent":
            events = [
                created(rid),
                (
                    "error",
                    {
                        "type": "error",
                        "code": "server_error",
                        "message": "CAPTURE-ERROR-EVENT: the backend stopped.",
                        "param": None,
                    },
                ),
            ]
        else:
            events = text_turn(rid)
        self._send(200, sse(events), "text/event-stream")


open(OUT, "w").close()
open(RAW, "w").close()
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
