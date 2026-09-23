#!/usr/bin/env python3
"""Anthropic's count_tokens, through a real gateway, driver and llama.cpp.

2026-09-23. A real `llama-server` behind the real
`eugene-plexus-inference-driver` behind the real `eugene-plexus-gateway`,
with `r4-stubs.py agent` in front of the component list, as in the
reasoning and images runs.

The question the unit fixtures cannot answer: is the number EXACT? Each
count is compared with the `input_tokens` a real one-token
`POST /v1/messages` of the same body reports through the same stack --
the number Claude Code's fallback would have obtained by generating. And
the half that is the point of the change: nothing is generated, nothing
is recorded, and a real Claude Code's `/context` stops falling back.

Safe beside a live install: ports 9182-9184 (the live agent holds 8079),
every ambient EUGENE_PLEXUS_* variable dropped, teardown by pid.

Usage:
    python scripts/count-tokens-acceptance.py
    EP_LLAMA_URL=http://127.0.0.1:9186 EP_MODEL_ID=qwen3-0.6b python scripts/count-tokens-acceptance.py
    EP_CLAUDE=1 python scripts/count-tokens-acceptance.py   # + a real Claude Code /context
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LLAMA = os.environ.get("EP_LLAMA_URL", "http://127.0.0.1:9181")
MODEL = os.environ.get("EP_MODEL_ID", "gemma-4-e4b")
AGENT_PORT = int(os.environ.get("EP_AGENT_PORT", "9182"))
DRIVER_PORT = int(os.environ.get("EP_DRIVER_PORT", "9183"))
GATEWAY_PORT = int(os.environ.get("EP_GATEWAY_PORT", "9184"))
GATEWAY = f"http://127.0.0.1:{GATEWAY_PORT}"
GATEWAY_PY = ROOT / "gateway/.venv/Scripts/python.exe"
COUNT = f"{GATEWAY}/v1/messages/count_tokens?beta=true"
READ_TOOL = {
    "name": "Read",
    "description": "Read a file from the local filesystem.",
    "input_schema": {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    },
}

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {len(RESULTS):>2}. {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def http(method: str, url: str, body: Any = None, timeout: float = 900) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status = r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode("utf-8", "replace"), e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}


def recorded() -> int:
    _, page = http("GET", f"{GATEWAY}/v1/metrics/requests?limit=500", timeout=10)
    return len(page.get("requests", [])) if isinstance(page, dict) else -1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    status, _ = http("GET", f"{LLAMA}/props", timeout=10)
    if status != 200:
        print(f"no llama.cpp engine at {LLAMA} ({status})")
        return 2
    for port in (AGENT_PORT, DRIVER_PORT, GATEWAY_PORT):
        if not port_free(port):
            print(f"port {port} is taken; refusing to start")
            return 2

    work = Path(tempfile.mkdtemp(prefix="count-tokens-acceptance-"))
    (work / "driver.yaml").write_text(
        f"provider: openai_compat_custom\nbaseUrl: {LLAMA}\nmodelId: {MODEL}\n"
        "requestTimeoutSeconds: 900\n",
        encoding="utf-8",
    )
    (work / "gateway.yaml").write_text("requestTimeoutSeconds: 900\n", encoding="utf-8")
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
            work / "driver.log",
            {
                "EUGENE_PLEXUS_DRIVER_CONFIG_FILE": str(work / "driver.yaml"),
                "EUGENE_PLEXUS_DRIVER_BIND_PORT": str(DRIVER_PORT),
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
        routable = False
        while time.perf_counter() < deadline:
            try:
                s, models = http("GET", f"{GATEWAY}/v1/models", timeout=5)
                if s == 200 and any(m.get("id") == MODEL for m in models.get("data", [])):
                    routable = True
                    break
            except OSError:
                pass
            time.sleep(1)
        if not check("the gateway routes the model", routable, f"{MODEL} via {LLAMA}"):
            return 1
        run_checks(work)
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


def run_checks(work: Path) -> None:
    # A Claude Code-sized system prompt, unique to this run. The second
    # execution compared a count with a generation llama.cpp answered from
    # its prompt cache (the first execution had prefilled the same text:
    # 10.7 s then, 5 tokens evaluated now), which is no prefill at all.
    long_system = f"Run {uuid.uuid4()}. " + "You are a careful assistant. " * 900
    cases = {
        "plain": {"messages": [{"role": "user", "content": "What is 2+2?"}]},
        "system + tools (a /context category)": {
            "system": [{"type": "text", "text": "You are a Claude agent."}],
            "tools": [READ_TOOL],
            "messages": [{"role": "user", "content": "x"}],
        },
        "a tool loop, with a thinking block handed back": {
            "tools": [READ_TOOL],
            "messages": [
                {"role": "user", "content": "Read a.py"},
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "I should read the file first.",
                     "signature": ""},
                    {"type": "tool_use", "id": "toolu_1", "name": "Read",
                     "input": {"file_path": "a.py"}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1",
                     "content": "print('hello')"},
                    {"type": "text", "text": "What does it print?"},
                ]},
            ],
        },
        "a long system prompt": {
            "system": long_system,
            "messages": [{"role": "user", "content": "ok?"}],
        },
    }

    # 1. Exact: the count equals what a one-token generation of the same
    #    body reports through the same stack. The pair is the evidence.
    before = recorded()
    timings: dict[str, tuple[float, float]] = {}
    exact: list[str] = []
    for name, case in cases.items():
        started = time.perf_counter()
        s, counted = http("POST", COUNT, {"model": MODEL, **case})
        count_s = time.perf_counter() - started
        after_count = recorded()
        started = time.perf_counter()
        g, generated = http("POST", f"{GATEWAY}/v1/messages",
                            {"model": MODEL, "max_tokens": 1, "temperature": 0, **case})
        gen_s = time.perf_counter() - started
        usage = generated.get("usage", {}) if isinstance(generated, dict) else {}
        truth = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        got = counted.get("input_tokens") if isinstance(counted, dict) else None
        timings[name] = (count_s, gen_s)
        ok = s == 200 and g == 200 and got == truth and after_count == before
        exact.append(f"{name}: {got} vs {truth}" + ("" if ok else f" [{s} {g} {str(counted)[:80]}]"))
        before = recorded()
    check(
        "every count equals the input tokens a one-token generation of the same body reports",
        all(" [" not in e for e in exact),
        "; ".join(exact),
    )

    # 2. Nothing generated, nothing recorded: counts leave no metrics rows
    #    (checked per count above) and cost nothing like a prefill.
    long_count, long_gen = timings["a long system prompt"]
    check(
        "a count of a long prompt costs a fraction of the prefill it replaces",
        long_count * 5 < long_gen,
        f"count {long_count * 1000:.0f} ms vs one-token generation {long_gen * 1000:.0f} ms",
    )

    # 3. An image is refused with the 400 Claude Code falls back on.
    png = subprocess.run(
        [str(GATEWAY_PY), "-c",
         "import base64, io, sys; from PIL import Image; b = io.BytesIO(); "
         "Image.new('RGB', (32, 32), 'red').save(b, format='PNG'); "
         "sys.stdout.write(base64.b64encode(b.getvalue()).decode())"],
        capture_output=True, text=True, check=True,
    ).stdout
    s, body = http("POST", COUNT, {"model": MODEL, "messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}},
        {"type": "text", "text": "what colour?"}]}]})
    message = (body.get("error") or {}).get("message", "") if isinstance(body, dict) else ""
    check("an image is a 400 naming why, not a guess", s == 400 and "projector" in message,
          f"{s} {message[:80]!r}")

    # 4. A model nothing serves is a 400 naming it, as on /v1/messages.
    s, body = http("POST", COUNT, {"model": "nothing-serves-this", "messages": [
        {"role": "user", "content": "x"}]})
    message = (body.get("error") or {}).get("message", "") if isinstance(body, dict) else ""
    check("a model nothing serves is a 400 naming it", s == 400 and "nothing-serves-this" in message,
          f"{s} {message[:80]!r}")


def run_claude_code_check(work: Path) -> None:
    """A real Claude Code's /context through the gateway: counted, not generated.

    Against the previous gateway every one of its 13-14 counts was a 404
    followed by a real one-token request. Counted from the gateway's own
    access log, so the record states the traffic rather than an impression.
    """
    claude = shutil.which("claude")
    if claude is None:
        check("Claude Code is installed", False)
        return
    config = work / "claude-config"
    config.mkdir()
    task = work / "claude-task"
    task.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("EUGENE_PLEXUS_", "ANTHROPIC_", "CLAUDE_"))}
    env.update(
        ANTHROPIC_BASE_URL=GATEWAY,
        ANTHROPIC_AUTH_TOKEN="local-no-auth",
        ANTHROPIC_MODEL=MODEL,
        CLAUDE_CONFIG_DIR=str(config),
        DISABLE_TELEMETRY="1",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
    )
    gateway_log = work / "gateway.log"
    mark = gateway_log.stat().st_size
    before = recorded()
    started = time.perf_counter()
    done = subprocess.run(
        [claude, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
         "--verbose", "--model", MODEL],
        input=json.dumps({"type": "user", "message": {"role": "user", "content": "/context"}})
        + "\n",
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        cwd=str(task), timeout=1800,
    )
    elapsed = time.perf_counter() - started
    time.sleep(0.5)
    lines = [json.loads(x) for x in done.stdout.splitlines() if x.strip().startswith("{")]
    result = next((x for x in lines if x.get("type") == "result"), {})
    text = str(result.get("result") or "")
    (work / "claude-context.txt").write_text(text, encoding="utf-8")
    tail = gateway_log.read_bytes()[mark:].decode("utf-8", "replace")
    counted = tail.count('"POST /v1/messages/count_tokens?beta=true HTTP/1.1" 200')
    refused = tail.count('"POST /v1/messages/count_tokens?beta=true HTTP/1.1" 4')
    generated = tail.count('"POST /v1/messages?beta=true HTTP/1.1"')
    tokens_line = next((x for x in text.splitlines() if "Tokens:" in x), text[:60]).strip()
    check(
        "a real Claude Code's /context is answered by counting, with no inference fallback",
        done.returncode == 0 and "Context Usage" in text and counted >= 10 and refused == 0
        and generated == 0 and recorded() == before,
        f"count_tokens 200s={counted} refused={refused} /v1/messages={generated} "
        f"{elapsed:.1f}s {tokens_line!r}",
    )


if __name__ == "__main__":
    sys.exit(main())
