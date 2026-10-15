"""Backend prerequisites for interactive UI, through the real gateway and drivers.

No AG-UI, A2UI or MCP Apps support is claimed by this check. It proves that an
application can carry UI JSON and tools through Eugene's existing inference API.
Provider responses are deterministic fixtures, not evidence of model quality.

Run with the shared acceptance Python (locally agent/.venv). Uses the isolated
process/trust harness in tools-assumed-acceptance.py: loopback, disposable ports
and state, no installed services, provider credentials or model downloads.

    python scripts/genui-inference-acceptance.py [--report PATH]
    python scripts/genui-inference-acceptance.py --only schema --families local
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import logging
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


def load_harness() -> Any:
    path = Path(__file__).with_name("tools-assumed-acceptance.py")
    spec = importlib.util.spec_from_file_location("genui_inference_harness", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# The harness clears ambient Eugene configuration before importing components.
h = load_harness()
import httpx  # noqa: E402

TITLE = 'München 🌦 — "quoted" and \\ escaped\nnext line'
VALUE = {"title": TITLE, "values": [0, -1.25, 3], "active": False, "note": None}
JSON_TEXT = json.dumps(VALUE, ensure_ascii=False, separators=(",", ":"))
UI_MESSAGES = [
    {
        "version": "v0.9.1",
        "createSurface": {
            "surfaceId": "weather",
            "catalogId": "urn:eugene:acceptance:catalog",
        },
    },
    {
        "version": "v0.9.1",
        "updateComponents": {
            "surfaceId": "weather",
            "components": [
                {"id": "root", "component": "Text", "text": TITLE},
            ],
        },
    },
    {
        "version": "v0.9.1",
        "updateDataModel": {
            "surfaceId": "weather",
            "path": "/",
            "value": VALUE,
        },
    },
]
JSONL = "\n".join(json.dumps(v, ensure_ascii=False) for v in UI_MESSAGES) + "\n"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "$defs": {"numberList": {"type": "array", "items": {"type": "number"}}},
    "properties": {
        "title": {"type": "string"},
        "values": {"$ref": "#/$defs/numberList"},
        "active": {"type": "boolean"},
        "note": {"type": ["string", "null"]},
    },
    "required": ["title", "values", "active", "note"],
}
FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "ui_data",
        "strict": True,
        "schema": SCHEMA,
    },
}
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": "Return UI data.",
            "parameters": SCHEMA,
            "strict": True,
        },
    }
    for name in ("weather", "summary")
]
CALLS: list[dict[str, Any]] = [
    {
        "id": f"call_ui_{i}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": JSON_TEXT,
        },
    }
    for i, name in enumerate(("weather", "summary"))
]


class JoinedDriver(h.Driver):  # type: ignore[name-defined]
    def stop(self) -> None:
        # A Windows venv Python is a launcher. Closing stdin lets the driver's
        # parent watcher exit Python before the launcher exits and logs are removed.
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            super().stop()
        finally:
            self.log.close()


class UIWire(h.OpenAIWire):  # type: ignore[name-defined]  # Loaded from the sibling harness.
    """Provider-shaped fixture; deliberately fragment at arbitrary string offsets."""

    def read_json(self) -> Any:
        self.body = super().read_json()
        return self.body

    def chat_done(self, model: str, stream: bool) -> None:
        messages = self.body.get("messages", [])
        marker = next(
            (
                m.get("content", "")
                for m in messages
                if m.get("role") == "user"
                and str(m.get("content", "")).startswith("UI-READINESS/")
            ),
            "",
        )
        if not marker:
            return super().chat_done(model, stream)
        mode = marker.split("/", 1)[1]
        if self.tag == "strata stand-in" and mode in {"refuse", "uncertain"}:
            self.send_json(
                429 if mode == "refuse" else 503,
                {"error": {"message": "fixture refusal"}},
            )
            return
        if mode == "resume":
            text = json.dumps(messages[-1].get("content"), ensure_ascii=False)
        else:
            text = JSONL if mode == "jsonl" else JSON_TEXT
        tool = mode in {"tools", "partial-tool"}
        finish = "tool_calls" if tool else "stop"
        usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        if not stream:
            message: dict[str, Any] = {
                "role": "assistant",
                "content": None if tool else text,
            }
            if tool:
                message["tool_calls"] = copy.deepcopy(CALLS)
            self.send_json(
                200,
                {
                    "id": "ui-fixture",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {"index": 0, "message": message, "finish_reason": finish}
                    ],
                    "usage": usage,
                },
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(delta: dict[str, Any], reason: str | None = None) -> None:
            frame: dict[str, Any] = {
                "id": "ui-fixture",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
            }
            if reason:
                frame["usage"] = usage
            raw = ("data: " + json.dumps(frame, ensure_ascii=False) + "\n\n").encode()
            # Split UTF-8 and SSE framing as a real HTTP connection may do.
            for offset in range(0, len(raw), 17):
                self.wfile.write(raw[offset : offset + 17])
                self.wfile.flush()

        try:
            if mode == "cancel":
                until = time.perf_counter() + 12
                while time.perf_counter() < until:
                    emit({"content": "still-running "})
                    time.sleep(0.02)
                return
            if tool:
                for i, call in enumerate(CALLS):
                    emit(
                        {
                            "tool_calls": [
                                {
                                    "index": i,
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": call["function"]["name"],
                                        "arguments": "{",
                                    },
                                }
                            ]
                        }
                    )
                if mode == "partial-tool":
                    return
                for offset in range(1, len(JSON_TEXT), 7):
                    for i in (1, 0):
                        emit(
                            {
                                "tool_calls": [
                                    {
                                        "index": i,
                                        "function": {
                                            "arguments": JSON_TEXT[offset : offset + 7],
                                        },
                                    }
                                ]
                            }
                        )
            else:
                for offset in range(0, len(text), 9):
                    emit({"content": text[offset : offset + 9]})
                    if mode == "partial-text":
                        return
            emit({}, finish)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            if mode == "cancel":
                self.cancelled.set()


def frames(raw: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in raw.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def decode(response: httpx.Response, stream: bool) -> dict[str, Any]:
    assert response.status_code == 200, (
        f"HTTP {response.status_code}: {response.text[:500]}"
    )
    if not stream:
        return response.json()["choices"][0]
    assert "data: [DONE]" in response.text, "missing stream terminator"
    calls: dict[int, dict[str, Any]] = {}
    content = ""
    finish = None
    for frame in frames(response.text):
        assert "error" not in frame, f"stream error: {frame}"
        for choice in frame.get("choices", []):
            delta = choice.get("delta", {})
            content += delta.get("content") or ""
            finish = choice.get("finish_reason") or finish
            for part in delta.get("tool_calls") or []:
                call = calls.setdefault(
                    part["index"],
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if part.get("id"):
                    call["id"] += part["id"]
                for key in ("name", "arguments"):
                    call["function"][key] += part.get("function", {}).get(key) or ""
    return {
        "finish_reason": finish,
        "message": {
            "content": content,
            "tool_calls": [calls[k] for k in sorted(calls)],
        },
    }


def request(
    model: str, mode: str, stream: bool = False, **extra: Any
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "UI-READINESS/" + mode}],
        "stream": stream,
        **extra,
    }


def post(gateway: Any, body: dict[str, Any]) -> httpx.Response:
    return gateway.http.post("/v1/chat/completions", json=body, headers=gateway.keyed)


def upstream(handler: Any) -> dict[str, Any]:
    return next(
        body
        for path, body in reversed(handler.recorded)
        if path == "/v1/chat/completions" and "UI-READINESS/" in json.dumps(body)
    )


def check_schema(stack: Any, fam: Any) -> None:
    handler = stack.stand_in(fam)
    for stream in (False, True):
        for fmt in ({"type": "json_object"}, FORMAT):
            result = decode(
                post(
                    stack.gw, request(fam.route, "schema", stream, response_format=fmt)
                ),
                stream,
            )
            assert result["message"]["content"] == JSON_TEXT, (
                "structured answer changed"
            )
            assert result["finish_reason"] == "stop"
            assert upstream(handler).get("response_format") == fmt, (
                "response_format changed upstream"
            )


def check_jsonl(stack: Any, fam: Any) -> None:
    for stream in (False, True):
        result = decode(post(stack.gw, request(fam.route, "jsonl", stream)), stream)
        assert result["message"]["content"] == JSONL, "UI JSONL/Unicode changed"
        assert result["finish_reason"] == "stop"


def check_tools(stack: Any, fam: Any) -> None:
    for stream in (False, True):
        body = request(fam.route, "tools", stream, tools=TOOLS)
        result = decode(post(stack.gw, body), stream)
        assert result["message"]["tool_calls"] == CALLS, (
            "tool ids/names/arguments changed"
        )
        assert result["finish_reason"] == "tool_calls", "tool completion lost"
        assert upstream(stack.stand_in(fam)).get("tools") == TOOLS, (
            "tool schema or strict lost"
        )
        body["messages"] = [
            {"role": "user", "content": "UI-READINESS/resume"},
            {"role": "assistant", "content": None, "tool_calls": copy.deepcopy(CALLS)},
            *[
                {"role": "tool", "tool_call_id": call["id"], "content": JSONL}
                for call in CALLS
            ],
        ]
        resumed = decode(post(stack.gw, body), stream)
        assert json.loads(resumed["message"]["content"]) == JSONL, (
            "tool result not returned"
        )
        assert upstream(stack.stand_in(fam))["messages"] == body["messages"], (
            "tool history changed"
        )


def check_metadata(stack: Any, fam: Any) -> None:
    handler = stack.stand_in(fam)
    bad = [request(fam.route, "schema", ui={"resourceUri": "ui://fixture"})]
    tool = copy.deepcopy(TOOLS[0])
    tool["_meta"] = {"ui": {"resourceUri": "ui://fixture"}}
    bad.append(request(fam.route, "tools", tools=[tool]))
    for body in bad:
        before = len(handler.recorded)
        response = post(stack.gw, body)
        assert response.status_code == 400, "UI metadata admitted to inference contract"
        assert len(handler.recorded) == before, "rejected metadata reached provider"


def check_translations(stack: Any, fam: Any) -> None:
    """The other public APIs carry the same JSON without becoming UI transports."""
    for door in ("responses", "messages"):
        for stream in (False, True):
            if door == "responses":
                body = {
                    "model": fam.route,
                    "input": "UI-READINESS/schema",
                    "stream": stream,
                    "text": {
                        "format": {"type": "json_schema", **FORMAT["json_schema"]}
                    },
                }
            else:
                body = request(
                    fam.route,
                    "schema",
                    stream,
                    max_tokens=1024,
                    output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
                )
            response = stack.gw.http.post(
                "/v1/" + door, json=body, headers=stack.gw.keyed
            )
            assert response.status_code == 200, (
                f"{door}: {response.status_code} {response.text[:400]}"
            )
            sent = upstream(stack.stand_in(fam)).get("response_format", {})
            assert sent.get("type") == "json_schema", f"{door}: format missing"
            assert sent.get("json_schema", {}).get("schema") == SCHEMA, (
                f"{door}: schema changed"
            )
            if door == "responses":
                assert sent == FORMAT, "Responses name/strict/schema changed"
                if stream:
                    events = frames(response.text)
                    assert events[-1]["type"] == "response.completed", (
                        "Responses not completed"
                    )
                    text = "".join(
                        f["delta"]
                        for f in events
                        if f["type"] == "response.output_text.delta"
                    )
                else:
                    answer = response.json()
                    assert answer["status"] == "completed"
                    text = "".join(
                        c["text"]
                        for i in answer["output"]
                        for c in i.get("content", [])
                        if c["type"] == "output_text"
                    )
            elif stream:
                events = frames(response.text)
                assert events[-1]["type"] == "message_stop", "Messages not completed"
                assert any(
                    f.get("delta", {}).get("stop_reason") == "end_turn" for f in events
                )
                text = "".join(
                    f["delta"]["text"]
                    for f in events
                    if f.get("delta", {}).get("type") == "text_delta"
                )
            else:
                answer = response.json()
                assert answer["stop_reason"] == "end_turn"
                text = "".join(
                    c["text"] for c in answer["content"] if c["type"] == "text"
                )
            assert text == JSON_TEXT, f"{door}: structured text changed"


def check_cancel(stack: Any, fam: Any) -> None:
    handler = stack.stand_in(fam)
    handler.cancelled = threading.Event()
    before = len(stack.agent_h.admissions)
    with stack.gw.http.stream(
        "POST",
        "/v1/chat/completions",
        headers=stack.gw.keyed,
        json=request(fam.route, "cancel", True),
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: ") and "still-running" in line:
                break
        else:
            raise AssertionError("no content arrived before disconnect")
    assert handler.cancelled.wait(8), (
        "disconnect did not close provider stream within 8 s"
    )
    deadline = time.perf_counter() + 5
    while (
        "release" not in stack.agent_h.admissions[before:]
        and time.perf_counter() < deadline
    ):
        time.sleep(0.02)
    assert "release" in stack.agent_h.admissions[before:], (
        "client admission not released"
    )
    assert "acquire" in stack.agent_h.admissions[before:], (
        "cancellation had no admission to release"
    )


def check_failover(stack: Any) -> None:
    primary = stack.stand_in(h.FAM["strata"])
    backup = stack.stand_in(h.FAM["local"])
    for mode in ("refuse", "uncertain", "partial-tool", "partial-text"):
        gateway = stack.new_gateway(stack.slots, "ui-" + mode)
        primary.recorded.clear()
        backup.recorded.clear()
        try:
            body = request("slot-strata", mode, True)
            if mode == "partial-tool":
                body["tools"] = TOOLS
            response = post(gateway, body)
            seen_primary = [
                b
                for p, b in primary.recorded
                if p.endswith("/chat/completions") and "UI-READINESS/" in json.dumps(b)
            ]
            seen_backup = [
                b
                for p, b in backup.recorded
                if p.endswith("/chat/completions") and "UI-READINESS/" in json.dumps(b)
            ]
            assert len(seen_primary) == 1, (
                f"{mode}: primary attempts {len(seen_primary)}"
            )
            if mode == "refuse":
                assert len(seen_backup) == 1, (
                    "known refusal did not fail over exactly once"
                )
                assert decode(response, True)["message"]["content"] == JSON_TEXT
            else:
                assert not seen_backup, f"{mode}: uncertain/partial work was replayed"
                assert response.status_code >= 400 or any(
                    "error" in f for f in frames(response.text)
                ), f"{mode}: incomplete answer reported success"
                if mode == "partial-tool":
                    assert any(
                        c.get("delta", {}).get("tool_calls")
                        for f in frames(response.text)
                        for c in f.get("choices", [])
                    ), "no tool fragment exercised"
                if mode == "partial-text":
                    assert any(
                        c.get("delta", {}).get("content")
                        for f in frames(response.text)
                        for c in f.get("choices", [])
                    ), "no text fragment exercised"
        finally:
            stack.retire(gateway)


CHECKS = {
    "schema": check_schema,
    "jsonl": check_jsonl,
    "tools": check_tools,
    "metadata": check_metadata,
    "translations": check_translations,
    "cancel": check_cancel,
}


def revisions() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    result = {}
    for name in ("specs", "gateway", "inference-driver"):
        path = root / name

        def git(*args: str) -> str:
            return subprocess.check_output(
                ["git", "-C", str(path), *args], text=True
            ).strip()

        result[name] = {
            "commit": git("rev-parse", "HEAD"),
            "workingTree": git("status", "--short"),
        }
    return result


def runtime_sources(stack: Any) -> dict[str, Any]:
    """Fail if the environment imports a different checkout than the one reported."""
    root = Path(__file__).resolve().parents[2]
    gateway = Path(stack.mods.file).resolve()
    expected_gateway = Path(h.GATEWAY_SRC or root / "gateway/src").resolve()
    assert expected_gateway in gateway.parents, f"unexpected gateway source: {gateway}"
    drivers = sorted({d.code().strip() for d in stack.drivers})
    expected_driver = Path(h.DRIVER_SRC or root / "inference-driver/src").resolve()
    assert all(expected_driver in Path(p).resolve().parents for p in drivers), drivers
    return {"gateway": str(gateway), "drivers": drivers}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=[*CHECKS, "failover"])
    parser.add_argument("--families", default="local,strata,oai-gpt55")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    names = args.families.split(",")
    if set(names) - {"local", "strata", "oai-gpt55"}:
        parser.error("families must be local,strata,oai-gpt55")
    if args.only in (None, "failover"):
        names = list(dict.fromkeys([*names, "local", "strata"]))
    h.refuse_the_internet()
    h.OpenAIWire = UIWire
    h.Driver = JoinedDriver
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="genui-inference-") as directory:
        tmp = Path(directory)
        logging.basicConfig(level=logging.ERROR)
        stack = h.Stack(tmp, [h.FAM[n] for n in names], h.load_gateway())
        try:
            sources = runtime_sources(stack)
            for name in names:
                for label, check in CHECKS.items():
                    if args.only and args.only != label:
                        continue
                    row = {"family": name, "check": label, "passed": True}
                    try:
                        check(stack, h.FAM[name])
                    except Exception as exc:
                        row.update(passed=False, error=f"{type(exc).__name__}: {exc}")
                    rows.append(row)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
            if args.only in (None, "failover"):
                row = {"family": "strata-to-local", "check": "failover", "passed": True}
                try:
                    check_failover(stack)
                except Exception as exc:
                    row.update(passed=False, error=f"{type(exc).__name__}: {exc}")
                rows.append(row)
                print(json.dumps(row), flush=True)
        finally:
            stack.stop()
            for server in stack.servers:
                server.server_close()
    report = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "source": revisions(),
        "runtimeSources": sources,
        "seconds": round(time.perf_counter() - started, 2),
        "checks": rows,
        "scope": "Real gateway/drivers; fixture providers; no UI protocol conformance claim.",
    }
    if args.report:
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    failed = sum(not row["passed"] for row in rows)
    print(f"{len(rows) - failed}/{len(rows)} passed in {report['seconds']} s")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
