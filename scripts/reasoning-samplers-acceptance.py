#!/usr/bin/env python3
"""Reasoning and the local samplers, through a real gateway and a real driver.

2026-09-23. A real `llama-server` serving a reasoning model (Qwen3-0.6B,
CPU) behind the real `eugene-plexus-inference-driver` behind the real
`eugene-plexus-gateway`. The agent is `r4-stubs.py agent`, because the
gateway reads only its component list here and a real agent would add a
supervisor, an engine store and an install to a run that asks none of
their questions.

The question is the one the unit fixtures cannot answer: does a thinking
model's reasoning, which llama.cpp reports apart from the answer by
default, now reach a caller on both doors in that door's own vocabulary
-- and do the samplers that were refused with a 400 until today reach
the ENGINE, not just the driver's request object?

Every check that could pass for the wrong reason has a pair or reads the
subject directly: the samplers are read out of the driver's own DEBUG
log of the upstream payload, and their effect is shown by greedy
determinism at temperature 2 against a non-greedy control; a reasoning
replay is proved by the prompt growing, not by a 200.

Safe beside a live install: ports 9182-9185 (the live agent holds 8079),
every ambient EUGENE_PLEXUS_* variable dropped, teardown by pid.

Usage:
    python scripts/reasoning-samplers-acceptance.py
    EP_CLAUDE=1 python scripts/reasoning-samplers-acceptance.py   # + Claude Code

Needs a reasoning model already served at EP_LLAMA_URL (default
http://127.0.0.1:9181, alias qwen3-0.6b). For EP_CLAUDE=1 its context must
hold Claude Code's system prompt: `-c 40960` for Qwen3-0.6B.
"""

from __future__ import annotations

import base64
import json
import os
import re
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
LLAMA = os.environ.get("EP_LLAMA_URL", "http://127.0.0.1:9181")
MODEL = os.environ.get("EP_MODEL_ID", "qwen3-0.6b")
AGENT_PORT = int(os.environ.get("EP_AGENT_PORT", "9182"))
DRIVER_PORT = int(os.environ.get("EP_DRIVER_PORT", "9183"))
GATEWAY_PORT = int(os.environ.get("EP_GATEWAY_PORT", "9184"))
CAPTURE_PORT = int(os.environ.get("EP_CAPTURE_PORT", "9185"))
GATEWAY = f"http://127.0.0.1:{GATEWAY_PORT}"
SIGNATURE_PREFIX = "eugene-plexus-reasoning-v1:"
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]
ANTHROPIC_TOOLS = [
    {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }
]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {len(RESULTS):>2}. {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def http(method: str, url: str, body: Any = None, timeout: float = 300) -> tuple[int, Any, dict[str, str]]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("content-type", "application/json")
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


def openai_frames(raw: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in raw.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def anthropic_events(raw: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


def chat(**body: Any) -> dict[str, Any]:
    body.setdefault("model", MODEL)
    body.setdefault("temperature", 0)
    return body


def messages_body(**body: Any) -> dict[str, Any]:
    body.setdefault("model", MODEL)
    body.setdefault("max_tokens", 400)
    body.setdefault("temperature", 0)
    return body


def clean_env() -> dict[str, str]:
    # A loop, not a list: install.ps1 sets the agent's config file at USER
    # scope, and a throwaway process that inherits it becomes the live node.
    return {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    status, info, _ = http("GET", f"{LLAMA}/v1/models", timeout=10)
    if status != 200:
        print(f"no engine at {LLAMA} ({status}); start llama-server with a reasoning model first")
        return 2
    for port in (AGENT_PORT, DRIVER_PORT, GATEWAY_PORT, CAPTURE_PORT):
        if not port_free(port):
            print(f"port {port} is taken; refusing to start")
            return 2

    work = Path(tempfile.mkdtemp(prefix="reasoning-acceptance-"))
    driver_log = work / "driver.log"
    (work / "driver.yaml").write_text(
        "provider: openai_compat_custom\n"
        f"baseUrl: {LLAMA}\n"
        f"modelId: {MODEL}\n"
        "logLevel: DEBUG\n"
        "requestTimeoutSeconds: 600\n",
        encoding="utf-8",
    )
    (work / "gateway.yaml").write_text("", encoding="utf-8")
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

    try:
        spawn(
            [sys.executable, str(ROOT / "specs/scripts/r4-stubs.py"), "agent",
             "--port", str(AGENT_PORT), "--driver-port", str(DRIVER_PORT)],
            work / "agent.log",
            {},
        )
        spawn(
            [str(ROOT / "inference-driver/.venv/Scripts/python.exe"), "-m",
             "eugene_plexus_inference_driver"],
            driver_log,
            {
                "EUGENE_PLEXUS_DRIVER_CONFIG_FILE": str(work / "driver.yaml"),
                "EUGENE_PLEXUS_DRIVER_BIND_PORT": str(DRIVER_PORT),
                "EUGENE_PLEXUS_DRIVER_AGENT_URL": f"http://127.0.0.1:{AGENT_PORT}",
            },
        )
        spawn(
            [str(ROOT / "gateway/.venv/Scripts/python.exe"), "-m", "eugene_plexus_gateway"],
            work / "gateway.log",
            {
                "EUGENE_PLEXUS_GATEWAY_CONFIG_FILE": str(work / "gateway.yaml"),
                "EUGENE_PLEXUS_GATEWAY_METRICS_FILE": str(work / "metrics.sqlite3"),
                "EUGENE_PLEXUS_GATEWAY_BIND_PORT": str(GATEWAY_PORT),
                "EUGENE_PLEXUS_GATEWAY_AGENT_URL": f"http://127.0.0.1:{AGENT_PORT}",
            },
        )

        # The processes came up where they were told, and it is OUR driver
        # answering -- an ignored env var is silent by construction.
        deadline = time.perf_counter() + 90
        routable = False
        while time.perf_counter() < deadline:
            try:
                s, models, _ = http("GET", f"{GATEWAY}/v1/models", timeout=5)
                if s == 200 and any(m.get("id") == MODEL for m in models.get("data", [])):
                    routable = True
                    break
            except OSError:
                pass
            time.sleep(1)
        s, info, _ = http("GET", f"http://127.0.0.1:{DRIVER_PORT}/v1/info", timeout=10)
        check(
            "the real driver is on its port, fronting the engine, advertising the samplers",
            s == 200
            and info.get("modelId") == MODEL
            and {"topK", "minP", "frequencyPenalty", "presencePenalty", "parallelToolCalls"}
            <= set((info.get("capabilities") or {}).get("supportedSettings") or []),
            f"supportedSettings={(info.get('capabilities') or {}).get('supportedSettings')}",
        )
        if not check("the gateway routes the model", routable):
            return 1

        run_openai_checks(driver_log)
        run_anthropic_checks()
        if os.environ.get("EP_CLAUDE") == "1":
            run_claude_code_check(work)
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


def run_openai_checks(driver_log: Path) -> None:
    # 1. THE FINDING: a model that thinks until max_tokens.
    s, r, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                   chat(max_tokens=24, messages=[{"role": "user", "content": "What is 2+2?"}]))
    msg = (r.get("choices") or [{}])[0].get("message", {}) if s == 200 else {}
    check(
        "OpenAI: a model that thought until max_tokens returns its reasoning, not an empty answer",
        s == 200
        and r["choices"][0]["finish_reason"] == "length"
        and len(msg.get("reasoning_content") or "") > 20,
        f"content={msg.get('content')!r} reasoning={len(msg.get('reasoning_content') or '')} chars",
    )

    # 2. Streamed, the thinking arrives first and on its own field.
    t0 = time.perf_counter()
    s, raw, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                     chat(max_tokens=600, stream=True,
                          messages=[{"role": "user", "content": "Reply with the single word ok"}]))
    frames = openai_frames(raw) if s == 200 else []
    deltas = [f["choices"][0]["delta"] for f in frames if f.get("choices")]
    r_at = [i for i, d in enumerate(deltas) if d.get("reasoning_content")]
    c_at = [i for i, d in enumerate(deltas) if d.get("content")]
    check(
        "OpenAI stream: reasoning_content deltas, all of them before the first content delta",
        len(r_at) > 5 and bool(c_at) and max(r_at) < min(c_at),
        f"{len(r_at)} reasoning frames, {len(c_at)} content frames, {time.perf_counter() - t0:.1f}s",
    )

    # 3. Cached prompt tokens, from llama.cpp's own prompt cache.
    body = chat(max_tokens=8, messages=[{"role": "user", "content": "What is 3+3?"}])
    http("POST", f"{GATEWAY}/v1/chat/completions", body)
    s, r, _ = http("POST", f"{GATEWAY}/v1/chat/completions", body)
    usage = r.get("usage", {}) if s == 200 else {}
    check(
        "OpenAI: usage carries llama.cpp's cached prompt tokens; no invented reasoning count",
        (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) > 0
        and "completion_tokens_details" not in usage,
        f"usage={usage}",
    )

    # 4. The samplers reach the ENGINE: read the driver's own log of the
    # upstream payload rather than trusting its request object.
    mark = driver_log.stat().st_size
    s, r, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                   chat(max_tokens=16, top_k=7, min_p=0.03, frequency_penalty=0.11,
                        presence_penalty=0.12, parallel_tool_calls=False, tools=TOOLS,
                        messages=[{"role": "user", "content": "Say hi."}]))
    time.sleep(0.5)
    tail = driver_log.read_bytes()[mark:].decode("utf-8", "replace")
    wanted = ['"top_k": 7', '"min_p": 0.03', '"frequency_penalty": 0.11',
              '"presence_penalty": 0.12', '"parallel_tool_calls": false']
    missing = [w for w in wanted if w not in tail]
    check(
        "OpenAI: all five samplers are in the payload the driver sent llama.cpp",
        s == 200 and not missing,
        f"status={s} missing={missing}",
    )

    # 5. ...and they take effect: top_k=1 at temperature 2 is greedy.
    def sample(**extra: Any) -> str:
        _, out, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                         chat(max_tokens=48, temperature=2.0,
                              messages=[{"role": "user", "content": "Name a colour."}], **extra))
        m = out["choices"][0]["message"]
        return (m.get("reasoning_content") or "") + "|" + (m.get("content") or "")

    greedy = {sample(top_k=1) for _ in range(3)}
    free = {sample() for _ in range(3)}
    check(
        "OpenAI: top_k=1 at temperature 2 is deterministic, and without it the same request is not",
        len(greedy) == 1 and len(free) > 1,
        f"{len(greedy)} distinct greedy, {len(free)} distinct unconstrained",
    )

    # 6. The developer role is accepted and answered.
    s, r, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                   chat(max_tokens=400, messages=[
                       {"role": "developer", "content": "Answer in one word."},
                       {"role": "user", "content": "Capital of France?"}]))
    check(
        "OpenAI: a developer message is served",
        s == 200 and bool(r["choices"][0]["message"].get("content")),
        f"status={s}",
    )

    # 7. A tool loop hands the reasoning back, and the ENGINE reads it.
    s, first, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                       chat(max_tokens=400, tools=TOOLS,
                            messages=[{"role": "user", "content": "What's the weather in Oslo?"}]))
    assistant = first["choices"][0]["message"] if s == 200 else {}
    has_call = bool(assistant.get("tool_calls")) and bool(assistant.get("reasoning_content"))
    grew = None
    if has_call:
        call_id = assistant["tool_calls"][0]["id"]
        tool = {"role": "tool", "tool_call_id": call_id, "content": "snowing, -3C"}
        user = {"role": "user", "content": "What's the weather in Oslo?"}
        verbatim = {k: v for k, v in assistant.items() if v is not None}
        stripped = {k: v for k, v in verbatim.items() if k != "reasoning_content"}
        _, with_r, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                            chat(max_tokens=1, tools=TOOLS, messages=[user, verbatim, tool]))
        _, without, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                             chat(max_tokens=1, tools=TOOLS, messages=[user, stripped, tool]))
        grew = with_r["usage"]["prompt_tokens"] - without["usage"]["prompt_tokens"]
    check(
        "OpenAI: an assistant turn sent back verbatim puts its reasoning into the engine's prompt",
        has_call and grew is not None and grew > 5,
        f"tool call + reasoning={has_call}, prompt grew by {grew} tokens",
    )

    # 8. ...and only an assistant turn may carry it.
    s, r, _ = http("POST", f"{GATEWAY}/v1/chat/completions",
                   chat(messages=[{"role": "user", "content": "hi", "reasoning_content": "x"}]))
    check(
        "OpenAI: reasoning_content on a user message is a 400 naming the field",
        s == 400 and r["error"]["param"] == "messages[0].reasoning_content",
        f"status={s}",
    )


def run_anthropic_checks() -> None:
    ask = [{"role": "user", "content": "Reply with the single word ok"}]

    # 9. Thinking enabled, no display: the text is shown.
    s, r, _ = http("POST", f"{GATEWAY}/v1/messages",
                   messages_body(messages=ask, thinking={"type": "adaptive"}))
    content = r.get("content", []) if s == 200 else []
    check(
        "Anthropic: thinking enabled returns a thinking block with text, then the answer",
        len(content) >= 2
        and content[0]["type"] == "thinking"
        and len(content[0]["thinking"]) > 20
        and content[0]["signature"] == ""
        and content[-1]["type"] == "text",
        f"blocks={[b['type'] for b in content]}",
    )

    # 10. display omitted: empty text, the reasoning in our signature.
    s, r, _ = http("POST", f"{GATEWAY}/v1/messages",
                   messages_body(messages=ask, thinking={"type": "adaptive", "display": "omitted"}))
    block = (r.get("content") or [{}])[0] if s == 200 else {}
    decoded = ""
    if str(block.get("signature", "")).startswith(SIGNATURE_PREFIX):
        decoded = base64.b64decode(block["signature"][len(SIGNATURE_PREFIX):]).decode()
    check(
        "Anthropic: display omitted empties the text and carries the reasoning in the signature",
        block.get("type") == "thinking" and block.get("thinking") == "" and len(decoded) > 20,
        f"decoded {len(decoded)} chars",
    )

    # 11. Streamed: a thinking block, closed before the text block opens.
    s, raw, _ = http("POST", f"{GATEWAY}/v1/messages",
                     messages_body(messages=ask, stream=True, thinking={"type": "adaptive"}))
    events = anthropic_events(raw) if s == 200 else []
    starts = [(i, e) for i, e in enumerate(events) if e["type"] == "content_block_start"]
    kinds = [e["content_block"]["type"] for _, e in starts]
    thinking_deltas = [e for e in events
                       if e["type"] == "content_block_delta" and e["delta"]["type"] == "thinking_delta"]
    stop0 = next((i for i, e in enumerate(events) if e == {"type": "content_block_stop", "index": 0}), None)
    check(
        "Anthropic stream: thinking_delta events in block 0, closed before the text block opens",
        kinds[:2] == ["thinking", "text"]
        and len(thinking_deltas) > 5
        and stop0 is not None
        and stop0 < starts[1][0],
        f"blocks={kinds} thinking_deltas={len(thinking_deltas)}",
    )

    # 12. Not asked for: no thinking block at all.
    s, r, _ = http("POST", f"{GATEWAY}/v1/messages", messages_body(messages=ask))
    check(
        "Anthropic: a client that did not enable thinking gets content[0].text",
        s == 200 and [b["type"] for b in r["content"]] == ["text"],
        f"blocks={[b['type'] for b in r.get('content', [])]}",
    )

    # 13. The omitted signature carries a tool loop's reasoning back.
    user = {"role": "user", "content": "What's the weather in Oslo?"}
    s, first, _ = http("POST", f"{GATEWAY}/v1/messages",
                       messages_body(messages=[user], tools=ANTHROPIC_TOOLS,
                                     thinking={"type": "adaptive", "display": "omitted"}))
    blocks = first.get("content", []) if s == 200 else []
    tool_use = next((b for b in blocks if b["type"] == "tool_use"), None)
    grew = None
    if tool_use and blocks and blocks[0]["type"] == "thinking":
        result = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use["id"], "content": "snowing, -3C"}]}

        def prompt(assistant_blocks: list[dict[str, Any]]) -> int:
            _, out, _ = http("POST", f"{GATEWAY}/v1/messages", messages_body(
                max_tokens=1, tools=ANTHROPIC_TOOLS,
                messages=[user, {"role": "assistant", "content": assistant_blocks}, result]))
            u = out["usage"]
            return u["input_tokens"] + u["cache_read_input_tokens"]

        grew = prompt(blocks) - prompt([b for b in blocks if b["type"] != "thinking"])
    check(
        "Anthropic: an omitted thinking block echoed back puts the reasoning into the engine's prompt",
        grew is not None and grew > 5,
        f"blocks={[b['type'] for b in blocks]} prompt grew by {grew} tokens",
    )

    # 14. Cached input is split out, Anthropic's way.
    body = messages_body(max_tokens=8, messages=[{"role": "user", "content": "What is 5+5?"}])
    http("POST", f"{GATEWAY}/v1/messages", body)
    s, r, _ = http("POST", f"{GATEWAY}/v1/messages", body)
    u = r.get("usage", {}) if s == 200 else {}
    check(
        "Anthropic: cache_read_input_tokens carries the engine's cache, input_tokens the rest",
        u.get("cache_read_input_tokens", 0) > 0 and u.get("input_tokens", -1) >= 0,
        f"usage={u}",
    )

    # 15. top_k, refused with a 400 until today.
    s, r, _ = http("POST", f"{GATEWAY}/v1/messages", messages_body(messages=ask, top_k=1))
    check("Anthropic: top_k is served, not refused", s == 200, f"status={s}")


def run_claude_code_check(work: Path) -> None:
    """A real Claude Code 2.1.207, three ways.

    **It chooses `display` by output mode** -- measured 2026-09-23 with
    `r4-capture.py`: its default text mode sends `{"type": "adaptive",
    "display": "omitted"}`, and `--output-format stream-json --verbose`
    sends `{"type": "adaptive"}` with no display, so an SDK consumer can
    see the thinking. So:

    * stream-json: it must receive the reasoning as text, in its strict SDK;
    * text mode: it must parse a block with empty text and a closing
      `signature_delta` and still print its answer;
    * `--continue` of that text-mode session, pointed at the capture
      listener: it must send our block back with the signature intact,
      which is the half that carries a tool loop's reasoning.
    """
    claude = shutil.which("claude")
    if claude is None:
        check("Claude Code is installed", False)
        return
    config = work / "claude-config"
    config.mkdir()
    session = work / "claude-session"
    session.mkdir()

    def run(args: list[str], base_url: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("EUGENE_PLEXUS_", "ANTHROPIC_"))
        }
        env.update(
            ANTHROPIC_BASE_URL=base_url,
            ANTHROPIC_AUTH_TOKEN="local-no-auth",
            ANTHROPIC_MODEL=MODEL,
            CLAUDE_CONFIG_DIR=str(config),
            DISABLE_TELEMETRY="1",
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        )
        return subprocess.run(
            [claude, "-p", *args, "--model", MODEL, "--tools", ""],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, cwd=str(cwd), timeout=600, stdin=subprocess.DEVNULL,
        )

    # 1. stream-json: no display, so the text comes back.
    started = time.perf_counter()
    done = run(["Reply with the single word ok", "--output-format", "stream-json", "--verbose"],
               GATEWAY, work)
    (work / "claude.jsonl").write_text(done.stdout, encoding="utf-8")
    lines = [json.loads(line) for line in done.stdout.splitlines() if line.strip().startswith("{")]
    blocks = [
        b
        for line in lines
        if line.get("type") == "assistant"
        for b in (line.get("message") or {}).get("content") or []
    ]
    result = next((line for line in lines if line.get("type") == "result"), {})
    thinking = [b for b in blocks if b.get("type") == "thinking"]
    check(
        "Claude Code (stream-json, no display) receives the reasoning as a thinking block with text",
        done.returncode == 0
        and bool(thinking)
        and len(thinking[0].get("thinking") or "") > 20
        and result.get("subtype") == "success",
        f"exit={done.returncode} blocks={[b.get('type') for b in blocks]} "
        f"result={str(result.get('result'))[:40]!r} {time.perf_counter() - started:.0f}s",
    )

    # 2. text mode: display omitted -- empty text, then a signature_delta.
    done = run(["Reply with the single word ok"], GATEWAY, session)
    check(
        "Claude Code (text mode, display omitted) parses the omitted block and prints its answer",
        done.returncode == 0 and bool(done.stdout.strip()),
        f"exit={done.returncode} stdout={done.stdout.strip()[:60]!r} "
        f"stderr={done.stderr.strip()[-120:]!r}",
    )

    # 3. Continue that session against the capture listener: what comes back?
    capture = work / "claude-continue-capture.txt"
    listener = subprocess.Popen(
        [sys.executable, str(ROOT / "specs/scripts/r4-capture.py"), "--port", str(CAPTURE_PORT),
         "--out", str(capture), "--mode", "capture"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.5)
        done = run(["--continue", "Reply with the single word yes"],
                   f"http://127.0.0.1:{CAPTURE_PORT}", session)
    finally:
        listener.terminate()
        listener.wait(timeout=10)
    text = capture.read_text(encoding="utf-8") if capture.exists() else ""
    ours = [
        m.group(1)
        for m in re.finditer(r'"signature": "(' + SIGNATURE_PREFIX + r'[^"]*)"', text)
    ]
    decoded = base64.b64decode(ours[0][len(SIGNATURE_PREFIX):]).decode() if ours else ""
    check(
        "Claude Code sends our omitted block back on the next turn with the signature intact",
        bool(ours) and len(decoded) > 20 and '"thinking": ""' in text,
        f"exit={done.returncode} signatures={len(ours)} decoded {len(decoded)} chars",
    )


if __name__ == "__main__":
    sys.exit(main())
