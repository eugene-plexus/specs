#!/usr/bin/env python3
"""The Responses door, through a real gateway, driver and engine -- and Codex.

2026-09-23, slice 4. Real `llama-server` engines behind the real
`eugene-plexus-inference-driver` behind the real `eugene-plexus-gateway`,
with `r4-stubs.py agent` as the agent (the gateway reads only its component
list). Two engines: a small reasoning model for text, tools and reasoning,
and a vision model for images and the timing check.

The questions the unit fixtures cannot answer: does a real Codex CLI finish a
turn, run a shell tool loop, see a picture both ways it sends one, and
survive a prefill longer than its own idle timeout -- through this door?

Every check that could pass for the wrong reason has a pair or reads its
subject directly. The shell loop reads a file whose contents are not in the
prompt. Colours are asked of two pictures with one name, from three words.
The output cap is shown absent on this door by the chat door hitting it with
the same prompt. The keepalive is shown by a Codex whose idle timeout is
shorter than the prefill it sat through -- measured from the engine's own
log, with its prompt cache cleared first, because a cache hit from an
earlier run makes the prefill instant and the check meaningless.

Safe beside a live install: ports 9182-9185 (the live agent holds 8079),
every ambient EUGENE_PLEXUS_* variable dropped, teardown by pid.

Usage:
    python scripts/responses-acceptance.py              # the door, over HTTP
    EP_CODEX=1 python scripts/responses-acceptance.py   # + a real Codex CLI

Needs two engines already serving, each started with --slot-save-path so its
prompt cache can be cleared:
    llama-server -m Qwen3-0.6B-Q4_K_M.gguf -ngl 0 -c 49152 -np 1 \
        --alias qwen3-0.6b --port 9181 --slot-save-path <dir>
    llama-server -m gemma-4-E4B-it-Q4_K_M.gguf --mmproj mmproj-gemma-4-E4B-it-BF16.gguf \
        --no-mmproj-offload -ngl 0 -c 49152 -np 1 --alias gemma-4-e4b --port 9186 \
        --slot-save-path <dir>
EP_ENGINE_LOG_VISION names the vision engine's log, for the prefill time.
EP_ONLY=shell,slow (any of door, hello, shell, attach, view_image, slow) runs
only those parts.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TEXT = os.environ.get("EP_LLAMA_URL", "http://127.0.0.1:9181")
TEXT_MODEL = os.environ.get("EP_MODEL_ID", "qwen3-0.6b")
VISION = os.environ.get("EP_VISION_URL", "http://127.0.0.1:9186")
VISION_MODEL = os.environ.get("EP_VISION_MODEL_ID", "gemma-4-e4b")
VISION_LOG = os.environ.get("EP_ENGINE_LOG_VISION")
AGENT_PORT = int(os.environ.get("EP_AGENT_PORT", "9182"))
DRIVER_PORT = int(os.environ.get("EP_DRIVER_PORT", "9183"))
GATEWAY_PORT = int(os.environ.get("EP_GATEWAY_PORT", "9184"))
VISION_DRIVER_PORT = int(os.environ.get("EP_VISION_DRIVER_PORT", "9185"))
GATEWAY = f"http://127.0.0.1:{GATEWAY_PORT}"
GATEWAY_PY = ROOT / "gateway/.venv/Scripts/python.exe"
PREFIX = "eugene-plexus-reasoning-v1:"
#: The install default this run sets, so low that any answer on the chat
#: door hits it -- which is the half of the pair that proves it is live.
INSTALL_CAP = 16

RESULTS: list[tuple[str, bool, str]] = []
ONLY = {part for part in os.environ.get("EP_ONLY", "").split(",") if part}


def wanted(part: str) -> bool:
    return not ONLY or part in ONLY


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(
        f"{'PASS' if ok else 'FAIL'}  {len(RESULTS):>2}. {name}" + (f"  -- {detail}" if detail else ""),
        flush=True,
    )
    return ok


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def http(method: str, url: str, body: Any = None, timeout: float = 900) -> tuple[int, Any, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("content-type", "application/json")
    req.add_header("authorization", "Bearer local-no-auth")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            headers = {k.lower(): v for k, v in r.headers.items()}
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        headers = {k.lower(): v for k, v in e.headers.items()}
        status = e.code
    if "text/event-stream" in headers.get("content-type", ""):
        return status, raw, headers
    try:
        return status, json.loads(raw), headers
    except ValueError:
        return status, raw, headers


def frames(raw: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    name = None
    for line in raw.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            out.append((str(name), json.loads(line[6:])))
            name = None
    return out


def timed_frames(url: str, body: dict[str, Any]) -> list[tuple[float, str, dict[str, Any]]]:
    """A stream read line by line, each frame stamped with its arrival."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("authorization", "Bearer local-no-auth")
    started = time.perf_counter()
    out: list[tuple[float, str, dict[str, Any]]] = []
    name = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                out.append((time.perf_counter() - started, str(name), json.loads(line[6:])))
    return out


def text_of(response: dict[str, Any]) -> str:
    return "".join(
        part.get("text", "")
        for item in response.get("output") or []
        if item.get("type") == "message"
        for part in item.get("content") or []
    )


def ask(prompt: str, *, model: str = TEXT_MODEL, **extra: Any) -> dict[str, Any]:
    """A Codex-shaped request: instructions, a developer message, two user
    messages in a row, the tools with a web_search among them."""
    body: dict[str, Any] = {
        "model": model,
        "instructions": "You are a helpful assistant. Answer briefly.",
        "input": [
            {"type": "message", "role": "developer",
             "content": [{"type": "input_text", "text": "Sandbox: read-only."}]},
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "<environment_context>cwd</environment_context>"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]},
        ],
        "tools": [
            {"type": "function", "name": "shell", "description": "Run a command.", "strict": False,
             "parameters": {"type": "object",
                            "properties": {"command": {"type": "array", "items": {"type": "string"}}},
                            "required": ["command"]}},
            {"type": "web_search", "external_web_access": False},
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "reasoning": None,
        "store": False,
        "stream": False,
        "include": [],
        "prompt_cache_key": secrets.token_hex(8),
        "client_metadata": {"x-codex-installation-id": "acceptance"},
    }
    body.update(extra)
    return body


def erase_cache(engine: str) -> bool:
    status, _, _ = http("POST", f"{engine}/slots/0?action=erase", {}, timeout=30)
    return status == 200


def clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    for engine in (TEXT, VISION):
        status, _, _ = http("GET", f"{engine}/health", timeout=10)
        if status != 200:
            print(f"no engine at {engine} ({status}); start llama-server first")
            return 2
    for port in (AGENT_PORT, DRIVER_PORT, GATEWAY_PORT, VISION_DRIVER_PORT):
        if not port_free(port):
            print(f"port {port} is taken; refusing to start")
            return 2

    work = Path(tempfile.mkdtemp(prefix="responses-acceptance-"))
    for name, engine, model in (("driver", TEXT, TEXT_MODEL), ("vision", VISION, VISION_MODEL)):
        (work / f"{name}.yaml").write_text(
            f"provider: openai_compat_custom\nbaseUrl: {engine}\nmodelId: {model}\n"
            "requestTimeoutSeconds: 900\n",
            encoding="utf-8",
        )
    (work / "gateway.yaml").write_text(
        f"requestTimeoutSeconds: 900\ndefaultMaxTokens: {INSTALL_CAP}\n", encoding="utf-8"
    )
    env = clean_env()
    procs: list[subprocess.Popen[bytes]] = []

    def spawn(args: list[str], log: Path, extra: dict[str, str]) -> None:
        procs.append(
            subprocess.Popen(
                args,
                stdout=open(log, "wb"),  # noqa: SIM115 - closed with the process
                stderr=subprocess.STDOUT,
                env={**env, **extra},
            )
        )

    driver_py = str(ROOT / "inference-driver/.venv/Scripts/python.exe")
    try:
        spawn(
            [sys.executable, str(ROOT / "specs/scripts/r4-stubs.py"), "agent", "--port",
             str(AGENT_PORT), "--driver-port", str(DRIVER_PORT), str(VISION_DRIVER_PORT)],
            work / "agent.log",
            {},
        )
        for name, port in (("driver", DRIVER_PORT), ("vision", VISION_DRIVER_PORT)):
            spawn(
                [driver_py, "-m", "eugene_plexus_inference_driver"],
                work / f"{name}.log",
                {
                    "EUGENE_PLEXUS_DRIVER_CONFIG_FILE": str(work / f"{name}.yaml"),
                    "EUGENE_PLEXUS_DRIVER_BIND_PORT": str(port),
                    "EUGENE_PLEXUS_DRIVER_AGENT_URL": f"http://127.0.0.1:{AGENT_PORT}",
                },
            )
        spawn(
            [str(GATEWAY_PY), "-m", "eugene_plexus_gateway"],
            work / "gateway.log",
            {
                "EUGENE_PLEXUS_GATEWAY_CONFIG_FILE": str(work / "gateway.yaml"),
                "EUGENE_PLEXUS_GATEWAY_METRICS_FILE": str(work / "metrics.sqlite3"),
                "EUGENE_PLEXUS_GATEWAY_BIND_PORT": str(GATEWAY_PORT),
                "EUGENE_PLEXUS_GATEWAY_AGENT_URL": f"http://127.0.0.1:{AGENT_PORT}",
            },
        )

        deadline = time.perf_counter() + 90
        ids: set[str] = set()
        while time.perf_counter() < deadline:
            try:
                s, models, _ = http("GET", f"{GATEWAY}/v1/models", timeout=5)
                ids = {m.get("id") for m in models.get("data", [])} if s == 200 else set()
                if {TEXT_MODEL, VISION_MODEL} <= ids:
                    break
            except OSError:
                pass
            time.sleep(1)
        if not check("the gateway routes both engines", {TEXT_MODEL, VISION_MODEL} <= ids,
                     f"models={sorted(i for i in ids if i)}"):
            return 1

        if wanted("door"):
            run_door_checks(work)
        if os.environ.get("EP_CODEX") == "1":
            run_codex_checks(work)
    finally:
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


def run_door_checks(work: Path) -> None:
    url = f"{GATEWAY}/v1/responses"

    # 1. A Codex-shaped request is answered, and what was not honoured is named.
    s, body, headers = http("POST", url, ask("Reply with the single word: ok. /no_think"))
    ignored = headers.get("x-eugene-plexus-ignored-settings", "")
    check(
        "a Codex-shaped request is answered, web_search and the cache key named not refused",
        s == 200 and body.get("status") == "completed" and text_of(body).strip() != ""
        and "tools.web_search" in ignored and "prompt_cache_key" in ignored,
        f"{s} {text_of(body).strip()[:30]!r} ignored={ignored!r}" if isinstance(body, dict)
        else f"{s} {str(body)[:120]}",
    )

    # 2. The event stream: order, numbering, both channels, no [DONE].
    s, raw, _ = http("POST", url, ask("Reply with the single word: ok. /no_think", stream=True))
    got = frames(raw) if isinstance(raw, str) else []
    names = [n for n, _ in got]
    check(
        "streamed: created and in_progress first, completed last, numbered, no [DONE]",
        s == 200 and names[:2] == ["response.created", "response.in_progress"]
        and names[-1:] == ["response.completed"]
        and [d.get("sequence_number") for _, d in got] == list(range(len(got)))
        and all(n == d.get("type") for n, d in got) and "[DONE]" not in (raw or ""),
        f"{s} {len(got)} frames, first {names[:2]}, last {names[-1:]}",
    )

    # 3. The output cap: none from the install default here, while the chat
    #    door -- same prompt, same engine -- stops at it. The pair is the proof.
    prompt = "Count from 1 to 40, separated by spaces. /no_think"
    s1, chat, _ = http("POST", f"{GATEWAY}/v1/chat/completions", {
        "model": TEXT_MODEL, "messages": [{"role": "user", "content": prompt}]})
    s2, resp, _ = http("POST", url, ask(prompt))
    chat_ok = s1 == 200 and chat["choices"][0]["finish_reason"] == "length" and (
        chat["usage"]["completion_tokens"] == INSTALL_CAP)
    resp_tokens = ((resp.get("usage") or {}).get("output_tokens") or 0) if s2 == 200 else 0
    check(
        f"the install cap ({INSTALL_CAP}) stops the chat door and not this one",
        chat_ok and resp.get("status") == "completed" and resp_tokens > INSTALL_CAP,
        f"chat {s1} {chat['choices'][0]['finish_reason'] if s1 == 200 else chat} "
        f"{chat['usage']['completion_tokens'] if s1 == 200 else ''} tokens; "
        f"responses {s2} {resp.get('status') if s2 == 200 else resp} {resp_tokens} tokens",
    )

    # 4. A caller's own cap is honoured, and the cut says so.
    s, body, _ = http("POST", url, ask(prompt, max_output_tokens=6))
    check(
        "max_output_tokens is carried and a cut answer is incomplete",
        s == 200 and body.get("status") == "incomplete"
        and body.get("incomplete_details") == {"reason": "max_output_tokens"},
        f"{s} {body.get('status')} {body.get('incomplete_details')}" if s == 200 else f"{s} {body}",
    )

    # 5. A real tool call, forced, both paths. `required` and not a named
    #    function: llama.cpp b10948 IGNORES a named tool_choice and answers
    #    in text (measured on the first execution, straight at the engine) --
    #    a silent drop one layer down, recorded in the run's record.
    forced = "required"
    s, body, _ = http("POST", url, ask("List the files here. /no_think", tool_choice=forced))
    calls = [i for i in (body.get("output") or []) if i.get("type") == "function_call"] if s == 200 else []
    try:
        arguments = json.loads(calls[0]["arguments"]) if calls else None
    except ValueError:
        arguments = None
    check(
        "a required tool call comes back as a function_call item with JSON arguments",
        bool(calls) and calls[0]["name"] == "shell" and calls[0]["call_id"]
        and isinstance(arguments, dict),
        f"{s} {calls[0]['name'] if calls else None} {str(arguments)[:60]}",
    )
    s, raw, _ = http("POST", url, ask("List the files here. /no_think", tool_choice=forced, stream=True))
    got = frames(raw) if isinstance(raw, str) else []
    deltas = "".join(d["delta"] for n, d in got if n == "response.function_call_arguments.delta")
    done = next((d for n, d in got if n == "response.function_call_arguments.done"), {})
    check(
        "streamed: the call's argument deltas add up to its arguments",
        s == 200 and bool(deltas) and deltas == done.get("arguments"),
        f"{s} {len(deltas)} chars in deltas, done={str(done.get('arguments'))[:50]!r}",
    )

    # 6. Reasoning: a reasoning_text item first, and the carrier decodes to it.
    s, body, _ = http("POST", url, ask("What is 17 + 25?", include=["reasoning.encrypted_content"]))
    items = body.get("output") or [] if s == 200 else []
    first = items[0] if items else {}
    text = "".join(p.get("text", "") for p in first.get("content") or [])
    carried = first.get("encrypted_content") or ""
    decoded = (
        base64.b64decode(carried[len(PREFIX):]).decode()
        if carried.startswith(PREFIX) else None
    )
    check(
        "a reasoning model's thinking is a reasoning_text item, and encrypted_content carries it",
        first.get("type") == "reasoning" and bool(text.strip()) and decoded == text,
        f"{s} first={first.get('type')} {len(text)} chars, carrier decodes={decoded == text}",
    )

    # 7. Reasoning sent back reaches the model: the same tool-loop turn with a
    #    canary in its reasoning item is longer by roughly the canary.
    canary = "The quartz lantern hums in the seventh violet corridor tonight."

    def turn_two(reasoning: str | None) -> dict[str, Any]:
        body = ask("Run ls. /no_think")
        if reasoning is not None:
            body["input"].append({"type": "reasoning", "summary": [], "encrypted_content": None,
                                  "content": [{"type": "reasoning_text", "text": reasoning}]})
        body["input"] += [
            {"type": "function_call", "name": "shell", "arguments": '{"command": ["ls"]}',
             "call_id": "call_live_1"},
            {"type": "function_call_output", "call_id": "call_live_1", "output": "a.txt\nb.txt"},
        ]
        return {**body, "max_output_tokens": 4}

    s1, without, _ = http("POST", url, turn_two(None))
    s2, with_it, _ = http("POST", url, turn_two(canary))
    a = (without.get("usage") or {}).get("input_tokens", 0) if s1 == 200 else 0
    b = (with_it.get("usage") or {}).get("input_tokens", 0) if s2 == 200 else 0
    check(
        "a reasoning item sent back is rendered into the prompt",
        s1 == 200 and s2 == 200 and b - a >= 8,
        f"input_tokens without {a}, with the canary {b}",
    )

    # 8. An over-long prompt: context_length_exceeded, both paths.
    huge = ask("word " * 60000)
    s, body, _ = http("POST", url, huge)
    code = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
    s2, raw, _ = http("POST", url, {**huge, "stream": True})
    last = frames(raw)[-1] if isinstance(raw, str) and frames(raw) else ("", {})
    stream_code = ((last[1].get("response") or {}).get("error") or {}).get("code")
    check(
        "an over-long prompt is context_length_exceeded, as a 400 and as response.failed",
        s == 400 and code == "context_length_exceeded" and last[0] == "response.failed"
        and stream_code == "context_length_exceeded",
        f"batch {s} {code}; stream {s2} {last[0]} {stream_code}",
    )

    # 9. A model nothing serves is a 400 here and a 404 on the chat door.
    s1, body, _ = http("POST", url, ask("hi", model="no-such-model"))
    s2, _, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                    {"model": "no-such-model", "messages": [{"role": "user", "content": "hi"}]})
    check(
        "a model nothing serves is 400 model_not_found here, 404 on the chat door",
        s1 == 400 and (body.get("error") or {}).get("code") == "model_not_found" and s2 == 404,
        f"responses {s1} {(body.get('error') or {}).get('code')}; chat {s2}",
    )

    # 10. The keepalive, over HTTP: a prefill longer than ten seconds is
    #     covered by response.in_progress. The vision engine's cache is
    #     cleared and the prompt opens with a nonce, so nothing is reused.
    erase_cache(VISION)
    long_prompt = f"{secrets.token_hex(8)}\n" + (
        "The committee reviewed the quarterly figures and noted a steady rise in costs. " * 2600
    ) + "\nIn one word, what did the committee review?"
    stamped = timed_frames(url, ask(long_prompt, model=VISION_MODEL, stream=True,
                                    max_output_tokens=24))
    first_output = next((t for t, n, _ in stamped if n == "response.output_item.added"), None)
    beats = [t for t, n, _ in stamped if n == "response.in_progress"]
    before = [t for t in beats if first_output is not None and t < first_output]
    gaps = [b - a for a, b in zip([0.0, *before], [*before, first_output or 0.0], strict=False)]
    check(
        "a long prefill is covered by response.in_progress at most ten seconds apart",
        first_output is not None and first_output > 20 and len(before) >= 3
        and max(gaps) < 12,
        f"first output at {first_output or 0:.1f}s, {len(before)} in_progress before it, "
        f"largest gap {max(gaps) if gaps else 0:.1f}s",
    )


def picture(colour: tuple[int, int, int]) -> bytes:
    code = (
        "import io, sys; from PIL import Image; b = io.BytesIO(); "
        f"Image.new('RGB', (224, 224), {colour!r}).save(b, format='PNG'); "
        "sys.stdout.buffer.write(b.getvalue())"
    )
    return subprocess.run([str(GATEWAY_PY), "-c", code], capture_output=True, check=True).stdout


def run_codex_checks(work: Path) -> None:
    """A real Codex CLI against the real gateway.

    An isolated CODEX_HOME with one custom provider on `wire_api =
    "responses"`, `codex exec --skip-git-repo-check --ephemeral`, and the
    sandbox at `workspace-write` -- measured to let `cat` and
    `powershell.exe -Command` run where `read-only` and `cmd /c` are
    refused as "blocked by policy".
    """
    codex = shutil.which("codex")
    if codex is None:
        check("Codex CLI is installed", False)
        return
    home = work / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text(
        'model_provider = "ep"\n\n[model_providers.ep]\nname = "Eugene Plexus"\n'
        f'base_url = "{GATEWAY}/v1"\nenv_key = "EP_TEST_KEY"\nwire_api = "responses"\n',
        encoding="utf-8",
    )
    gateway_log = work / "gateway.log"

    def posts_since(mark: int) -> int:
        time.sleep(0.5)
        return gateway_log.read_bytes()[mark:].decode("utf-8", "replace").count(
            '"POST /v1/responses HTTP/1.1" 200'
        )

    def run(
        cwd: Path, model: str, args: list[str], *, timeout: float = 1800
    ) -> tuple[subprocess.CompletedProcess[str], int]:
        mark = gateway_log.stat().st_size
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("EUGENE_PLEXUS_", "OPENAI_", "CODEX_"))}
        env.update(CODEX_HOME=str(home), EP_TEST_KEY="local-no-auth")
        done = subprocess.run(
            [codex, "exec", "--skip-git-repo-check", "--ephemeral", "-m", model, *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
            cwd=str(cwd), timeout=timeout, stdin=subprocess.DEVNULL,
        )
        return done, posts_since(mark)

    def last_message(done: subprocess.CompletedProcess[str]) -> str:
        return done.stdout.strip().splitlines()[-1].strip() if done.stdout.strip() else ""

    if wanted("hello"):
        codex_hello(work, run, last_message)
    if wanted("shell"):
        codex_shell(work, run, last_message)
    for how in ("attach", "view_image"):
        if wanted(how):
            codex_picture(work, run, last_message, how)
    if wanted("slow"):
        codex_slow(work, run)


def codex_hello(work: Path, run: Any, last_message: Any) -> None:
    # C1. A turn: the answer comes back and the process exits clean.
    task = work / "codex-hello"
    task.mkdir()
    done, posts = run(task, TEXT_MODEL, ["Reply with the single word: ready. /no_think"])
    (work / "codex-hello.txt").write_text(done.stdout + done.stderr, encoding="utf-8")
    check(
        "Codex CLI completes a turn through the door",
        done.returncode == 0 and posts >= 1 and last_message(done) != "",
        f"exit={done.returncode} posts={posts} last={last_message(done)[:40]!r}",
    )



def codex_shell(work: Path, run: Any, last_message: Any) -> None:
    # C2. The shell tool loop: the file's contents are not in the prompt, so
    #     the only way to the nonce is a tool call run and its output returned.
    nonce = f"NONCE-{secrets.token_hex(4).upper()}"
    task = work / "codex-shell"
    task.mkdir()
    (task / "secret.txt").write_text(nonce + "\n", encoding="utf-8")
    loop_model = os.environ.get("EP_CODEX_TOOL_MODEL", VISION_MODEL)
    # The argv is spelled out: on the first execution the model sent
    # `["cat secret.txt"]`, ONE string, which Codex's policy blocks as it
    # blocks `cmd /c` -- the loop worked and the command did not.
    done, posts = run(task, loop_model, [
        "-s", "workspace-write",
        'Call the shell tool with exactly this command array: ["cat", "secret.txt"]. '
        "Then reply with only the text it printed.",
    ])
    (work / "codex-shell.txt").write_text(done.stdout + done.stderr, encoding="utf-8")
    check(
        f"Codex runs a shell tool loop through the door ({loop_model}): it reads a nonce "
        "only the tool could have given it",
        done.returncode == 0 and posts >= 2 and nonce in done.stdout,
        f"exit={done.returncode} posts={posts} nonce_seen={nonce in done.stdout} "
        f"last={last_message(done)[:40]!r}",
    )



def codex_picture(work: Path, run: Any, last_message: Any, how: str) -> None:
    # C3 + C4. Pictures, both ways Codex sends one, each as a PAIR: one file
    #     name, two colours, three allowed words.
    question = "Which single colour fills the image? Answer with exactly one word: red, green or blue."
    if True:
        outcomes = []
        for name, colour in (("red", (220, 20, 20)), ("green", (20, 170, 40))):
            here = work / f"codex-{how}-{name}"
            here.mkdir()
            (here / "sample.png").write_bytes(picture(colour))
            if how == "attach":
                args = [question, "-i", str(here / "sample.png")]
            else:
                args = [f"Use the view_image tool on the file {here / 'sample.png'} . {question}"]
            done, posts = run(here, VISION_MODEL, args)
            (work / f"codex-{how}-{name}.txt").write_text(done.stdout + done.stderr, encoding="utf-8")
            answer = last_message(done).lower()
            others = {"red", "green", "blue"} - {name}
            outcomes.append((
                done.returncode == 0 and name in answer and not any(o in answer for o in others)
                and (posts >= 2 if how == "view_image" else posts >= 1),
                f"{name}: exit={done.returncode} posts={posts} {answer[:24]!r}",
            ))
        check(
            f"Codex's picture reaches the model ({how}): sample.png red, then green",
            all(ok for ok, _ in outcomes),
            "; ".join(detail for _, detail in outcomes),
        )



def codex_slow(work: Path, run: Any) -> None:
    # C5. The keepalive, in the client it exists for: an idle timeout of 15 s
    #     and a first prompt whose prefill takes longer. The cache is cleared
    #     so the prefill is real, and the engine's own log says how long.
    #     Codex's own prompt prefills in about ten seconds on this CPU (the
    #     first execution measured it), so an AGENTS.md -- which Codex puts
    #     in the prompt -- makes the prefill long enough to matter.
    erase_cache(VISION)
    task = work / "codex-slow"
    task.mkdir()
    (task / "AGENTS.md").write_text(
        "# Project notes\n\n"
        + "The build uses the standard toolchain and the tests run on every change. " * 1600,
        encoding="utf-8",
    )
    log_mark = Path(VISION_LOG).stat().st_size if VISION_LOG else 0
    started = time.perf_counter()
    done, posts = run(task, VISION_MODEL, [
        "-c", "model_providers.ep.stream_idle_timeout_ms=15000",
        "-c", "project_doc_max_bytes=400000",
        "Reply with the single word: ready.",
    ])
    elapsed = time.perf_counter() - started
    (work / "codex-slow.txt").write_text(done.stdout + done.stderr, encoding="utf-8")
    prefill_ms = 0.0
    if VISION_LOG:
        tail = Path(VISION_LOG).read_bytes()[log_mark:].decode("utf-8", "replace")
        times = [float(m) for m in re.findall(r"prompt eval time =\s+([\d.]+) ms", tail)]
        prefill_ms = max(times) if times else 0.0
    check(
        "Codex with a 15 s idle timeout sits through a longer prefill in ONE request",
        done.returncode == 0 and posts == 1 and prefill_ms > 15000,
        f"exit={done.returncode} posts={posts} prefill={prefill_ms / 1000:.1f}s "
        f"elapsed={elapsed:.0f}s",
    )


if __name__ == "__main__":
    sys.exit(main())
