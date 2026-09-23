#!/usr/bin/env python3
"""Images on the Anthropic door, through a real gateway, driver and vision engine.

2026-09-23. A real `llama-server` serving a vision model with its projector
(Gemma 4 E4B, CPU) behind the real `eugene-plexus-inference-driver` behind the
real `eugene-plexus-gateway`. The agent is `r4-stubs.py agent`, as in the
reasoning run: the gateway reads only its component list here.

The question the unit fixtures cannot answer: does a picture sent in
Anthropic's shape -- above all Claude Code's own, a `Read` of an image that
comes back as a `tool_result` holding a lone `image` block -- reach the ENGINE
as a picture, so the model answers from what it sees?

Every check that could pass for the wrong reason has a pair or reads the
subject directly. A colour is asked of two images that differ only in colour,
so a model guessing, or reading a filename, cannot pass both; and the prompt
grows by a picture's worth of tokens when it is there, which a dropped image
cannot fake. Claude Code gets the same pair: one file name, two colours.

Safe beside a live install: ports 9182-9185 (the live agent holds 8079), every
ambient EUGENE_PLEXUS_* variable dropped, teardown by pid.

Usage:
    python scripts/anthropic-images-acceptance.py
    EP_CLAUDE=1 python scripts/anthropic-images-acceptance.py   # + a real Claude Code

Needs a vision model already served at EP_LLAMA_URL (default
http://127.0.0.1:9181, alias gemma-4-e4b), e.g.

    llama-server -m gemma-4-E4B-it-Q4_K_M.gguf --mmproj mmproj-gemma-4-E4B-it-BF16.gguf \
        --no-mmproj-offload -ngl 0 -c 32768 -np 1 --alias gemma-4-e4b --port 9181
"""

from __future__ import annotations

import base64
import io
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
QUESTION = "What single colour fills this image? Answer with one word."

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {len(RESULTS):>2}. {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def http(method: str, url: str, body: Any = None, timeout: float = 900) -> tuple[int, Any, dict]:
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


def picture(colour: tuple[int, int, int], fmt: str = "PNG") -> str:
    """A solid colour, made by the gateway's own Pillow so this script needs none."""
    code = (
        "import base64, io, sys; from PIL import Image; b = io.BytesIO(); "
        f"Image.new('RGB', (224, 224), {colour!r}).save(b, format={fmt!r}"
        + (", lossless=True" if fmt == "WEBP" else "")
        + "); sys.stdout.write(base64.b64encode(b.getvalue()).decode())"
    )
    return subprocess.run(
        [str(GATEWAY_PY), "-c", code], capture_output=True, text=True, check=True
    ).stdout


def image_block(data: str, media_type: str = "image/png") -> dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def ask(content: list[dict[str, Any]], *, stream: bool = False, **extra: Any) -> dict[str, Any]:
    return {
        "model": MODEL,
        "max_tokens": 400,
        "temperature": 0,
        "stream": stream,
        "messages": [{"role": "user", "content": content}],
        **extra,
    }


def answer_text(body: Any) -> str:
    if isinstance(body, str):  # an event stream
        text = []
        for line in body.splitlines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text.append(delta["text"])
        return "".join(text)
    return "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")


def input_tokens(body: Any) -> int:
    usage = body.get("usage") or {}
    return (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)


def clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    status, props, _ = http("GET", f"{LLAMA}/props", timeout=10)
    if status != 200 or not (props.get("modalities") or {}).get("vision"):
        print(f"no vision engine at {LLAMA} ({status}); start llama-server with --mmproj first")
        return 2
    for port in (AGENT_PORT, DRIVER_PORT, GATEWAY_PORT):
        if not port_free(port):
            print(f"port {port} is taken; refusing to start")
            return 2

    work = Path(tempfile.mkdtemp(prefix="anthropic-images-acceptance-"))
    (work / "driver.yaml").write_text(
        "provider: openai_compat_custom\n"
        f"baseUrl: {LLAMA}\n"
        f"modelId: {MODEL}\n"
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
        model_row: dict[str, Any] = {}
        while time.perf_counter() < deadline:
            try:
                s, models, _ = http("GET", f"{GATEWAY}/v1/models", timeout=5)
                model_row = next((m for m in models.get("data", []) if m.get("id") == MODEL), {})
                if s == 200 and (model_row.get("x_eugene_plexus") or {}).get("image_input"):
                    break
            except OSError:
                pass
            time.sleep(1)
        s, info, _ = http("GET", f"http://127.0.0.1:{DRIVER_PORT}/v1/info", timeout=10)
        check(
            "the real driver fronts the engine and confirms image input from its /props",
            s == 200 and (info.get("capabilities") or {}).get("imageInput") is True,
            f"imageInput={(info.get('capabilities') or {}).get('imageInput')}",
        )
        if not check(
            "the gateway routes the model as image-capable",
            (model_row.get("x_eugene_plexus") or {}).get("image_input") is True,
            f"x_eugene_plexus={model_row.get('x_eugene_plexus')}",
        ):
            return 1

        run_door_checks()
        if os.environ.get("EP_CLAUDE") == "1":
            run_claude_code_checks(work)
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


def run_door_checks() -> None:
    red, blue = picture((220, 20, 20)), picture((20, 40, 220))

    # 1. A person's own image, the documented shape -- as a PAIR, so a model
    #    that guesses or never saw the picture cannot pass both.
    answers = {}
    for name, data in (("red", red), ("blue", blue)):
        s, body, _ = http("POST", f"{GATEWAY}/v1/messages",
                          ask([image_block(data), {"type": "text", "text": QUESTION}]))
        answers[name] = (s, answer_text(body) if s == 200 else str(body)[:200], body)
    check(
        "a user image block reaches the engine: red is answered red and blue blue",
        all(s == 200 and name in text.lower() for name, (s, text, _) in answers.items()),
        "; ".join(f"{n}: {s} {t.strip()[:30]!r}" for n, (s, t, _) in answers.items()),
    )

    # 2. The picture's tokens are in the prompt: the same question with no
    #    image is shorter by a picture's worth, which a dropped image cannot
    #    fake. Gemma 4 E4B spends 83 tokens on a 224x224 image (measured on
    #    the first execution, which asked for "more than 100" and failed on
    #    that guess); 32 is well clear of any text-only difference here.
    s, plain, _ = http("POST", f"{GATEWAY}/v1/messages", ask([{"type": "text", "text": QUESTION}]))
    with_image = input_tokens(answers["red"][2]) if answers["red"][0] == 200 else 0
    check(
        "the image's tokens reach the engine's prompt",
        s == 200 and with_image - input_tokens(plain) > 32,
        f"input_tokens with image {with_image}, without {input_tokens(plain) if s == 200 else s}",
    )

    # 3. Streaming, Anthropic's event stream, same picture.
    s, raw, _ = http("POST", f"{GATEWAY}/v1/messages",
                     ask([image_block(blue), {"type": "text", "text": QUESTION}], stream=True))
    check(
        "streamed: the image is seen and the stream ends at message_stop",
        s == 200 and "blue" in answer_text(raw).lower() and "message_stop" in raw,
        f"{s} {answer_text(raw).strip()[:30]!r}",
    )

    # 4. Claude Code's own shape: a Read whose tool_result holds a lone image.
    def tool_read(data: str, media_type: str = "image/png") -> dict[str, Any]:
        return {
            "model": MODEL,
            "max_tokens": 400,
            "temperature": 0,
            "thinking": {"type": "adaptive", "display": "omitted"},
            "output_config": {"effort": "high"},
            "tools": [{
                "name": "Read",
                "description": "Read a file from the local filesystem.",
                "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}},
                                 "required": ["file_path"]},
            }],
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": "Read sample.png and tell me, in one word, "
                                             "what single colour fills it."}]},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "toolu_live_0001", "name": "Read",
                     "input": {"file_path": "sample.png"}}]},
                {"role": "user", "content": [
                    {"tool_use_id": "toolu_live_0001", "type": "tool_result",
                     "content": [image_block(data, media_type)],
                     "cache_control": {"type": "ephemeral"}}]},
            ],
        }

    seen = {}
    for name, data in (("red", red), ("blue", blue)):
        s, body, _ = http("POST", f"{GATEWAY}/v1/messages", tool_read(data))
        seen[name] = (s, answer_text(body) if s == 200 else str(body)[:200])
    check(
        "Claude Code's shape -- a tool_result holding a lone image -- is seen by the model",
        all(s == 200 and name in text.lower() for name, (s, text) in seen.items()),
        "; ".join(f"{n}: {s} {t.strip()[:30]!r}" for n, (s, t) in seen.items()),
    )

    # 5. WebP, which Claude Code sends as itself: re-encoded, still the picture.
    green = picture((20, 170, 40), "WEBP")
    s, body, _ = http("POST", f"{GATEWAY}/v1/messages", tool_read(green, "image/webp"))
    text = answer_text(body) if s == 200 else str(body)[:200]
    check("a WebP image is re-encoded and still seen: green", s == 200 and "green" in text.lower(),
          f"{s} {text.strip()[:30]!r}")

    # 6. A URL is refused and never fetched.
    s, body, _ = http("POST", f"{GATEWAY}/v1/messages", ask([
        {"type": "image", "source": {"type": "url", "url": "http://127.0.0.1:9/never.png"}},
        {"type": "text", "text": QUESTION}]))
    message = (body.get("error") or {}).get("message", "") if isinstance(body, dict) else ""
    check("an image URL is a 400 naming the block, never fetched",
          s == 400 and "messages.0.content.0.source" in message and "not fetched" in message,
          f"{s} {message[:90]!r}")


def run_claude_code_checks(work: Path) -> None:
    """A real Claude Code reads a picture through the real gateway -- twice.

    The file is always `sample.png`, so its name says nothing; it is red in
    one task directory and green in the other, and the answer is asked from
    three words. A model that never saw the picture cannot answer both.

    **Two instruments were wrong on the first execution and are recorded
    in the run's record.** The answer was asked in free words and the model
    said *Emerald* -- a green, and a fail. And a check read the engine's log
    for an image encode that llama.cpp b10948 does not log at its default
    level, while the driver deliberately never logs an image payload; so
    the pair is the direct evidence, not a log line.
    """
    claude = shutil.which("claude")
    if claude is None:
        check("Claude Code is installed", False)
        return
    config = work / "claude-config"
    config.mkdir()
    task = work / "claude-task"
    task.mkdir()

    def run(
        args: list[str], stdin: str | None = None, cwd: Path = task
    ) -> subprocess.CompletedProcess[str]:
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
        return subprocess.run(
            [claude, "-p", *args, "--model", MODEL],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
            cwd=str(cwd), timeout=1800, input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
        )

    outcomes = {}
    for name, colour in (("red", (220, 20, 20)), ("green", (20, 170, 40))):
        here = work / f"claude-task-{name}"
        here.mkdir()
        (here / "sample.png").write_bytes(base64.b64decode(picture(colour)))
        started = time.perf_counter()
        done = run(["Use the Read tool to open sample.png. Which single colour fills it? "
                    "Answer with exactly one word: red, green or blue.",
                    "--tools", "Read", "--allowedTools", "Read",
                    "--output-format", "stream-json", "--verbose"], cwd=here)
        (work / f"claude-{name}.jsonl").write_text(done.stdout, encoding="utf-8")
        lines = [json.loads(x) for x in done.stdout.splitlines() if x.strip().startswith("{")]
        result = next((x for x in lines if x.get("type") == "result"), {})
        read_ok = any(
            b.get("type") == "tool_use" and b.get("name") == "Read"
            for x in lines if x.get("type") == "assistant"
            for b in (x.get("message") or {}).get("content") or []
        )
        answer = str(result.get("result") or "").strip().lower()
        others = {"red", "green", "blue"} - {name}
        outcomes[name] = (
            done.returncode == 0 and read_ok and result.get("subtype") == "success"
            and name in answer and not any(o in answer for o in others),
            f"{name}: exit={done.returncode} read={read_ok} {answer[:24]!r} "
            f"{time.perf_counter() - started:.0f}s",
        )
    check(
        "a real Claude Code Reads a picture through the gateway and answers from it "
        "(sample.png red, then sample.png green)",
        all(ok for ok, _ in outcomes.values()),
        "; ".join(detail for _, detail in outcomes.values()),
    )

    # What /context does against a gateway with no /v1/messages/count_tokens.
    # It calls that endpoint 13 times (captured). On the first execution the
    # gateway's log showed every 404 followed at once by a real POST
    # /v1/messages on the same connection: Claude Code falls back to
    # INFERENCE to count, and the engine evaluated prompts of up to 9,050
    # tokens for one output token each. Counted here, from the log, so the
    # record states the cost rather than an impression of it.
    gateway_log = work / "gateway.log"
    mark = gateway_log.stat().st_size
    done = run(["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"],
               stdin=json.dumps({"type": "user",
                                 "message": {"role": "user", "content": "/context"}}) + "\n")
    lines = [json.loads(x) for x in done.stdout.splitlines() if x.strip().startswith("{")]
    result = next((x for x in lines if x.get("type") == "result"), {})
    text = str(result.get("result") or "")
    tokens_line = next((x for x in text.splitlines() if "Tokens:" in x), text[:80])
    time.sleep(0.5)
    tail = gateway_log.read_bytes()[mark:].decode("utf-8", "replace")
    counts = tail.count('"POST /v1/messages/count_tokens?beta=true HTTP/1.1" 404')
    fallbacks = tail.count('"POST /v1/messages?beta=true HTTP/1.1" 200')
    check(
        "Claude Code's /context answers without count_tokens -- by falling back to inference",
        done.returncode == 0 and result.get("subtype") == "success" and "Context Usage" in text
        and counts > 0 and fallbacks >= counts,
        f"exit={done.returncode} {tokens_line.strip()!r} count_tokens 404s={counts} "
        f"messages requests={fallbacks}",
    )
    (work / "claude-context.txt").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
