"""A5, step one: how often a local model's tool call fails, and whose failure it is.

The audience roadmap's A5 (tool-call repair) starts with a measurement,
because each kind of failure has a different answer:

* **the engine's parsing** - the model wrote a good call in its own format
  and the engine did not turn it into `tool_calls` (it arrives as text, or
  as an engine error). A repair would be a second parser, ours;
* **the model's JSON** - the arguments do not parse, or were cut off by the
  token budget. Cut-off JSON must be reported, never repaired: a truncated
  call can still be valid JSON with a 200 (the failover thread's warning);
* **the wrong tool or arguments** - valid JSON that names a tool nobody
  offered, breaks the schema, or does something other than what was asked.
  No parser fixes that; it is the model.

This drives `llama-server` directly (the engine Eugene supervises), one
model at a time, over twelve scenarios with each model's recommended
sampling, and classifies every answer. Where the answer is text that looks
like a call, it also tries a lenient parse, so the table says how much a
repair could recover. Nothing here goes through Eugene: what is measured is
the engine and the model, which is what decides what, if anything, Eugene
builds.

    python scripts/a5-tool-call-measurement.py --server DIR/llama-server.exe \
        --model FILE.gguf [--samples 3] [--out docs/acceptance/a5-data]

Its own port, its own process, killed at the end; safe beside the live
install. CPU by default (`--gpu-layers 0`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #


def fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


STRING = {"type": "string"}
T = {
    "get_weather": fn(
        "get_weather",
        "Get the current weather for a city.",
        {"city": STRING, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}},
        ["city"],
    ),
    "read_file": fn("read_file", "Read a text file and return its contents.", {"path": STRING}, ["path"]),
    "write_file": fn(
        "write_file",
        "Write text to a file, replacing it if it exists.",
        {"path": STRING, "content": STRING},
        ["path", "content"],
    ),
    "search_files": fn(
        "search_files",
        "Search file contents for a pattern and return matching lines as path:line: text.",
        {"pattern": STRING, "directory": STRING},
        ["pattern"],
    ),
    "run_shell": fn(
        "run_shell",
        "Run a shell command.",
        {"command": STRING, "timeout_seconds": {"type": "integer"}},
        ["command"],
    ),
    "send_email": fn(
        "send_email",
        "Send an email.",
        {"to": {"type": "array", "items": STRING}, "subject": STRING, "body": STRING},
        ["to", "subject", "body"],
    ),
    "create_event": fn(
        "create_event",
        "Create a calendar event.",
        {
            "title": STRING,
            "start": {
                "type": "object",
                "properties": {"date": STRING, "time": STRING},
                "required": ["date", "time"],
                "additionalProperties": False,
            },
            "attendees": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": STRING, "email": STRING},
                    "required": ["name", "email"],
                    "additionalProperties": False,
                },
            },
        },
        ["title", "start"],
    ),
    "set_timer": fn(
        "set_timer",
        "Start a countdown timer.",
        {"minutes": {"type": "integer"}, "label": STRING},
        ["minutes"],
    ),
    "get_time": fn("get_time", "Get the current local time.", {}, []),
}
DECOYS = {
    name: fn(name, description, {"value": STRING}, ["value"])
    for name, description in [
        ("list_directory", "List the files in a directory (value: the directory)."),
        ("delete_file", "Delete a file (value: the path)."),
        ("move_file", "Move a file (value: 'from -> to')."),
        ("git_status", "Show the git working tree status (value: the repository path)."),
        ("http_get", "Fetch a URL (value: the URL)."),
        ("calculator", "Evaluate an arithmetic expression (value: the expression)."),
        ("translate_text", "Translate text to English (value: the text)."),
        ("create_ticket", "Open an issue in the tracker (value: the title)."),
        ("query_database", "Run a read-only SQL query (value: the SQL)."),
        ("resize_image", "Resize an image (value: 'path WIDTHxHEIGHT')."),
    ]
}
GIT_COMMIT = fn(
    "git_commit",
    "Commit the staged changes in the current repository.",
    {"message": STRING, "amend": {"type": "boolean"}},
    ["message"],
)

ESCAPED_PROGRAM = (
    'print("Hello, \\"world\\"!")\n'
    'path = "C:\\\\Users\\\\me\\\\notes.txt"\n'
    'print(f"Saving to {path}")\n'
)


def tools(*names: str) -> list[dict]:
    return [T[n] for n in names]


def user(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


# --------------------------------------------------------------------------- #
# scenarios
# --------------------------------------------------------------------------- #

# Each: id, tools, messages, what is expected, and optional request extras.
# `expect` is a list of (tool, check) pairs; check(args) says whether the
# arguments mean what was asked. `None` means no call should be made.
SCENARIOS: list[dict] = [
    {
        "id": "single",
        "tools": tools("get_weather"),
        "messages": user("What's the weather in Oslo right now? Use celsius."),
        "expect": [("get_weather", lambda a: "oslo" in str(a.get("city", "")).lower()
                    and a.get("unit") in (None, "celsius"))],
    },
    {
        "id": "choose",
        "tools": list(T.values()),
        "messages": user("Show me what's in the file src/main.py."),
        "expect": [("read_file", lambda a: str(a.get("path", "")).endswith("src/main.py"))],
    },
    {
        "id": "escaping",
        "tools": tools("write_file", "read_file"),
        "messages": user(
            "Create a file named hello.py containing exactly this Python program, "
            "character for character:\n\n" + ESCAPED_PROGRAM
        ),
        "expect": [("write_file", lambda a: str(a.get("path", "")).endswith("hello.py")
                    and 'print("Hello, \\"world\\"!")' in str(a.get("content", ""))
                    and "C:\\\\Users\\\\me" in str(a.get("content", "")))],
    },
    {
        "id": "nested",
        "tools": tools("create_event"),
        "messages": user(
            "Book a meeting called Design review on 2026-10-05 at 14:00 with "
            "Ana (ana@example.com) and Ben (ben@example.com)."
        ),
        "expect": [("create_event", lambda a: isinstance(a.get("start"), dict)
                    and "2026-10-05" in str(a["start"].get("date", ""))
                    and "14:00" in str(a["start"].get("time", ""))
                    and isinstance(a.get("attendees"), list) and len(a["attendees"]) == 2)],
    },
    {
        "id": "parallel",
        "tools": tools("get_weather"),
        "messages": user("What's the weather in Oslo and in Paris? Check both cities."),
        "expect": [
            ("get_weather", lambda a: "oslo" in str(a.get("city", "")).lower()),
            ("get_weather", lambda a: "paris" in str(a.get("city", "")).lower()),
        ],
        "extra": {"parallel_tool_calls": True},
    },
    {
        "id": "chain",
        "tools": tools("search_files", "read_file"),
        "messages": [
            {"role": "user", "content": "Find the file that defines the function main, then show me that file."},
            {
                "role": "assistant",
                "content": None,
                # An id shaped like a real client's. The first run used
                # `call_1`, and Mistral Small 3.2's template refuses an id
                # under 9 characters (llama-server answers 400 before
                # generating); OpenAI's, Claude Code's and llama-server's
                # own ids are all longer, and all pass.
                "tool_calls": [{
                    "id": "call_k2Hq9XwZp4RtYv8LmN3sB6dF",
                    "type": "function",
                    "function": {"name": "search_files", "arguments": json.dumps({"pattern": "def main"})},
                }],
            },
            {"role": "tool", "tool_call_id": "call_k2Hq9XwZp4RtYv8LmN3sB6dF",
             "content": "src/app/entry.py:12: def main():"},
        ],
        "expect": [("read_file", lambda a: str(a.get("path", "")).endswith("src/app/entry.py"))],
    },
    {
        "id": "types",
        "tools": tools("set_timer", "get_time"),
        "messages": user("Set a 15 minute timer called tea."),
        "expect": [("set_timer", lambda a: a.get("minutes") == 15)],
    },
    {
        "id": "no_params",
        "tools": tools("get_time", "get_weather"),
        "messages": user("What time is it?"),
        "expect": [("get_time", lambda a: a == {})],
    },
    {
        "id": "no_call_needed",
        "tools": tools("get_weather", "read_file"),
        "messages": user("What is 17 times 3? Answer directly."),
        "expect": None,
    },
    {
        "id": "many_tools",
        "tools": list(T.values()) + list(DECOYS.values()) + [GIT_COMMIT],
        "messages": user("Commit the staged changes with the message 'fix typo in README'."),
        "expect": [("git_commit", lambda a: "fix typo in readme" in str(a.get("message", "")).lower())],
    },
    {
        "id": "forced",
        "tools": tools("get_weather", "get_time"),
        "messages": user("Tell me about Oslo."),
        "expect": [("get_weather", lambda a: "oslo" in str(a.get("city", "")).lower())],
        "extra": {"tool_choice": {"type": "function", "function": {"name": "get_weather"}}},
    },
    {
        # What Eugene could send instead of a named choice llama-server
        # ignores: only that tool, and `required`. Measured apart (A5 §2).
        "id": "forced_as_required",
        "tools": tools("get_weather"),
        "messages": user("Tell me about Oslo."),
        "expect": [("get_weather", lambda a: "oslo" in str(a.get("city", "")).lower())],
        "extra": {"tool_choice": "required"},
        "apart": True,
    },
    {
        # The budget runs out: whatever comes back must say so. A call that
        # arrives here with valid JSON is the failover thread's hazard.
        "id": "truncated",
        "tools": tools("write_file"),
        "messages": user("Write a file notes.md containing a 300-word essay about the history of tea."),
        "expect": [("write_file", lambda a: str(a.get("path", "")).endswith("notes.md"))],
        "extra": {"max_tokens": 120},
        "budget": True,
    },
]

# --------------------------------------------------------------------------- #
# per-model sampling: each model card's own recommendation
# --------------------------------------------------------------------------- #

PRESETS: list[tuple[str, dict]] = [
    ("qwen3-coder", {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "repeat_penalty": 1.05}),
    ("qwen3-30b-a3b-instruct", {"temperature": 0.7, "top_p": 0.8, "top_k": 20}),
    ("qwen3", {"temperature": 0.6, "top_p": 0.95, "top_k": 20}),
    ("gemma", {"temperature": 1.0, "top_p": 0.95, "top_k": 64}),
    ("gpt-oss", {"temperature": 1.0, "top_p": 1.0}),
    ("llama-3", {"temperature": 0.6, "top_p": 0.9}),
    ("mistral-small", {"temperature": 0.15}),
]


def preset_for(model: Path) -> dict:
    name = model.name.lower()
    for key, preset in PRESETS:
        if key in name:
            return dict(preset)
    return {"temperature": 0.7}


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #

KINDS = {
    "ok": "ok",
    "unparsed_call": "engine",
    "engine_error": "engine",
    "broken_json": "model_json",
    "cut_off": "model_json",
    "truncated_valid": "model_json",
    "wrong_tool": "wrong",
    "bad_args": "wrong",
    "wrong_args": "wrong",
    "partial": "wrong",
    "unneeded_call": "wrong",
    "no_call": "no_call",
}

CALL_MARKERS = re.compile(
    r"<tool_call>|</tool_call>|<function=|\[TOOL_CALLS\]|<\|python_tag\|>|<\|tool_call"
    r"|to=functions\.|<\|channel\|>commentary|\"(?:name|function)\"\s*:\s*\"[a-z_]+\"|```json\s*\{\s*\"name\"",
)


def schema_errors(value, schema: dict, where: str = "$") -> list[str]:
    """The subset of JSON Schema these tools use."""
    kind = schema.get("type")
    checks = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
    }
    if kind in checks and not checks[kind](value):
        return [f"{where}: expected {kind}, got {type(value).__name__}"]
    errors: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} not in {schema['enum']}")
    if kind == "object":
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}.{key}: missing")
        for key, item in value.items():
            if key in props:
                errors += schema_errors(item, props[key], f"{where}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{where}.{key}: not in the schema")
    if kind == "array" and "items" in schema:
        for i, item in enumerate(value):
            errors += schema_errors(item, schema["items"], f"{where}[{i}]")
    return errors


def lenient_calls(text: str) -> list[tuple[str, object]]:
    """What a forgiving second parser could pull out of text: `(name, args)`."""
    found: list[tuple[str, object]] = []
    for block in re.findall(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", text, re.S):
        try:
            obj = json.loads(block)
            found.append((obj.get("name"), obj.get("arguments", obj.get("parameters"))))
        except ValueError:
            pass
    for name, body in re.findall(r"<function=([\w.-]+)>(.*?)(?:</function>|$)", text, re.S):
        params = dict(re.findall(r"<parameter=([\w.-]+)>\s*(.*?)\s*</parameter>", body, re.S))
        found.append((name, params))
    for name, args in re.findall(r"\[TOOL_CALLS\]\s*([\w.-]+)\s*\[ARGS\]\s*(\{.*\})", text, re.S):
        try:
            found.append((name, json.loads(args)))
        except ValueError:
            pass
    if not found:
        for match in re.finditer(r"\{", text):
            try:
                obj, _ = json.JSONDecoder().raw_decode(text[match.start():])
            except ValueError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("name"), str):
                found.append((obj["name"], obj.get("arguments", obj.get("parameters", {}))))
    return found


def classify(scenario: dict, status: int | None, body) -> dict:
    offered = {t["function"]["name"]: t["function"]["parameters"] for t in scenario["tools"]}
    if status != 200 or not isinstance(body, dict):
        return {"class": "engine_error", "detail": str(body)[:300]}
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    finish = choice.get("finish_reason")
    calls = message.get("tool_calls") or []
    content = message.get("content") or ""
    out: dict = {"finish": finish, "calls": len(calls)}
    if scenario["expect"] is None:
        out["class"] = "unneeded_call" if calls else "ok"
        return out
    if not calls:
        if CALL_MARKERS.search(content):
            recovered = []
            for name, args in lenient_calls(content):
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        continue
                if name in offered and isinstance(args, dict) and not schema_errors(args, offered[name]):
                    recovered.append(name)
            out.update({"class": "unparsed_call", "repairable": bool(recovered), "text": content[:400]})
        elif finish == "length":
            out["class"] = "cut_off"
        else:
            out.update({"class": "no_call", "text": content[:200]})
        return out
    parsed: list[tuple[str, dict]] = []
    for call in calls:
        function = call.get("function") or {}
        name, raw = function.get("name"), function.get("arguments")
        if name not in offered:
            out.update({"class": "wrong_tool", "detail": f"called {name!r}"})
            return out
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            out.update({"class": "cut_off" if finish == "length" else "broken_json", "detail": str(raw)[:300]})
            return out
        if not isinstance(args, dict):
            out.update({"class": "broken_json", "detail": str(raw)[:300]})
            return out
        errors = schema_errors(args, offered[name])
        if errors:
            out.update({"class": "bad_args", "detail": "; ".join(errors)[:300]})
            return out
        parsed.append((name, args))
    if finish == "length":
        out.update({"class": "truncated_valid", "detail": json.dumps(parsed)[:300]})
        return out
    unmet = list(scenario["expect"])
    for name, args in parsed:
        for i, (want, test) in enumerate(unmet):
            if name == want and test(args):
                unmet.pop(i)
                break
    if not unmet:
        out["class"] = "ok"
    elif len(unmet) < len(scenario["expect"]):
        out.update({"class": "partial", "detail": json.dumps(parsed)[:300]})
    elif any(name != scenario["expect"][0][0] for name, _ in parsed):
        out.update({"class": "wrong_tool", "detail": json.dumps(parsed)[:300]})
    else:
        out.update({"class": "wrong_args", "detail": json.dumps(parsed)[:300]})
    return out


# --------------------------------------------------------------------------- #
# the engine
# --------------------------------------------------------------------------- #


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(url: str, body: dict, timeout: float):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    request.add_header("content-type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, str(e)


def post_streamed(url: str, body: dict, timeout: float):
    """The same request streamed, assembled the way a client assembles it.

    Harnesses stream, and llama-server parses a streamed call on a separate,
    partial-parsing path. Tool-call deltas are joined by `index`; an error
    event in the stream is an engine error. Returns what a non-streamed
    answer would have looked like, so one classifier reads both.
    """
    request = urllib.request.Request(url, data=json.dumps({**body, "stream": True}).encode(), method="POST")
    request.add_header("content-type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    content: list[str] = []
    calls: dict[int, dict] = {}
    finish = None
    try:
        with opener.open(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except ValueError:
                    continue
                if "error" in event:
                    return 500, event
                choice = (event.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    content.append(delta["content"])
                for part in delta.get("tool_calls") or []:
                    slot = calls.setdefault(part.get("index", 0), {"id": None, "function": {"name": "", "arguments": ""}})
                    slot["id"] = slot["id"] or part.get("id")
                    function = part.get("function") or {}
                    slot["function"]["name"] += function.get("name") or ""
                    slot["function"]["arguments"] += function.get("arguments") or ""
                finish = choice.get("finish_reason") or finish
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, str(e)
    message = {"role": "assistant", "content": "".join(content) or None,
               "tool_calls": [{"type": "function", **calls[i]} for i in sorted(calls)] or None}
    return 200, {"choices": [{"message": message, "finish_reason": finish}]}


def serve(server: Path, model: Path, port: int, log: Path, args: argparse.Namespace) -> subprocess.Popen:
    argv = [
        str(server), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
        "-c", str(args.context), "-np", "1", "-ngl", str(args.gpu_layers), "--jinja",
    ]
    if args.threads:
        argv += ["-t", str(args.threads)]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log.open("w"), stderr=subprocess.STDOUT, env=env)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.perf_counter() + 900
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"llama-server exited {process.returncode}; see {log}")
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return process
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    process.kill()
    raise SystemExit("llama-server did not become healthy")


def serve_driver(python: str, llama_port: int, name: str, workdir: Path) -> tuple[subprocess.Popen, int]:
    """A real inference-driver in front of llama-server, as Eugene runs one.

    No trust bundle, so it verifies nothing (its dev path), on a port of its
    own; its config is what the agent writes for a companion driver.
    """
    port = free_port()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "driver.yaml").write_text(json.dumps({
        "provider": "openai_compat_custom",
        "baseUrl": f"http://127.0.0.1:{llama_port}",
        "modelId": name,
        "backendLocality": "local",
    }), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update({
        "EUGENE_PLEXUS_DRIVER_CONFIG_FILE": str(workdir / "driver.yaml"),
        "EUGENE_PLEXUS_DRIVER_BIND_PORT": str(port),
        "EUGENE_PLEXUS_DRIVER_BIND_HOST": "127.0.0.1",
    })
    log = (workdir / "driver.log").open("w")
    process = subprocess.Popen([python, "-m", "eugene_plexus_inference_driver"], env=env,
                               stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                if r.status == 200:
                    return process, port
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    process.kill()
    raise SystemExit(f"the driver did not start; see {workdir / 'driver.log'}")


def via_driver(url: str, body: dict, timeout: float):
    """One request in the driver's own contract, the answer back in OpenAI's.

    Messages here are plain user turns or carry OpenAI's tool fields, which
    the driver spells `toolCalls` and `toolCallId`.
    """
    messages = []
    for m in body["messages"]:
        out = {"role": m["role"], "content": m.get("content")}
        if m.get("tool_calls"):
            out["toolCalls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            out["toolCallId"] = m["tool_call_id"]
        messages.append(out)
    request = {"messages": messages, "tools": body.get("tools"), "maxTokens": body.get("max_tokens"),
               "seed": body.get("seed")}
    for theirs, ours in (("temperature", "temperature"), ("top_p", "topP"), ("top_k", "topK"),
                         ("tool_choice", "toolChoice"), ("parallel_tool_calls", "parallelToolCalls")):
        if theirs in body:
            request[ours] = body[theirs]
    status, answer = post(url, {k: v for k, v in request.items() if v is not None}, timeout)
    if status != 200 or not isinstance(answer, dict):
        return status, answer
    return 200, {"choices": [{"message": {"content": answer.get("content"),
                                          "tool_calls": answer.get("toolCalls")},
                              "finish_reason": answer.get("finishReason")}],
                 "usage": {"completion_tokens": (answer.get("usage") or {}).get("completionTokens")}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--name", help="how the table names the model (default: the file's stem)")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--gpu-layers", type=int, default=0)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--only", help="comma-separated scenario ids")
    parser.add_argument("--stream", action="store_true", help="stream every request, as harnesses do")
    parser.add_argument("--via-driver", metavar="PYTHON",
                        help="send every request through a real inference-driver, run by this interpreter")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "docs/acceptance/a5-data")
    args = parser.parse_args()

    name = args.name or args.model.stem
    sampling = preset_for(args.model)
    scenarios = [s for s in SCENARIOS if not args.only or s["id"] in args.only.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    log = Path(tempfile.gettempdir()) / f"a5-{name}.server.log"
    version = subprocess.run([str(args.server), "--version"], capture_output=True, text=True).stderr.strip()
    print(f"{name}: {version.splitlines()[0] if version else '?'}; sampling {sampling}", flush=True)
    process = serve(args.server, args.model, port, log, args)
    driver = None
    if args.via_driver:
        if args.stream:
            raise SystemExit("--via-driver measures the non-streamed path; the driver's stream is unit-tested")
        driver, driver_port = serve_driver(args.via_driver, port, name,
                                           Path(tempfile.gettempdir()) / f"a5-driver-{name}")
    records: list[dict] = []
    try:
        for scenario in scenarios:
            for seed in range(1, args.samples + 1):
                body = {
                    "model": name,
                    "messages": scenario["messages"],
                    "tools": scenario["tools"],
                    "max_tokens": args.max_tokens,
                    "seed": seed,
                    **sampling,
                    **scenario.get("extra", {}),
                }
                started = time.perf_counter()
                if driver is not None:
                    status, answer = via_driver(f"http://127.0.0.1:{driver_port}/v1/generate", body, 1800)
                else:
                    send = post_streamed if args.stream else post
                    status, answer = send(f"http://127.0.0.1:{port}/v1/chat/completions", body, timeout=1800)
                seconds = round(time.perf_counter() - started, 1)
                verdict = classify(scenario, status, answer)
                usage = answer.get("usage", {}) if isinstance(answer, dict) else {}
                record = {
                    "model": name, "scenario": scenario["id"], "seed": seed, "status": status,
                    "seconds": seconds, "completion_tokens": usage.get("completion_tokens"), **verdict,
                }
                if verdict["class"] != "ok":
                    message = ((answer.get("choices") or [{}])[0].get("message") if isinstance(answer, dict) else None)
                    record["message"] = message if message is not None else str(answer)[:1000]
                records.append(record)
                print(f"  {scenario['id']:>15} #{seed}  {verdict['class']:<15} {seconds:>6}s  "
                      f"{verdict.get('detail', '')[:90]}", flush=True)
    finally:
        for running in (driver, process):
            if running is not None:
                running.kill()
                running.wait()
    result = {"model": name, "file": args.model.name, "streamed": args.stream,
              "via_driver": bool(args.via_driver),
              "engine": version.splitlines()[0] if version else None,
              "sampling": sampling, "samples": args.samples, "records": records}
    (args.out / f"{name}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in records:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    print(f"{name}: {counts}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
