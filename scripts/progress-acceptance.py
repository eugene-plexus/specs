"""What the backend is doing reaches the caller, before it has anything to say. Live.

2026-09-27. A tester sent a prompt to a model on the processor, saw
nothing for minutes, concluded it had failed and left; the answer was
waiting when he came back. Measured on llama.cpp b11215 before any of
this: 21 s of prompt reading on the processor and not one frame.

The unit checks drive each hop in process. What only a live run can show
is the whole path -- a real `llama-server` reading a real prompt on the
processor, a real inference-driver, a real gateway, and a client reading
the gateway's stream as it arrives:

  0. isolated from any install on this machine, and from its ports
  1. a real llama-server (CPU, a real 0.6B), a real driver over it, a real
     driver over a stub HOSTED API, and a real gateway over both
  2. asked: the prompt's reading arrives as progress, batch by batch,
     rising to the whole prompt, all of it before the first word -- and
     seconds before it
  3. unasked: nothing of the kind, and the same silence the tester saw
  4. the gateway's time-to-first-token is the first word, not the first
     progress frame
  4b. while it writes (2026-10-10): llama.cpp's own running count reaches
      the caller between the words, rising and never past the usage; the
      final frame names the cap sent and where it came from, the request's
      own and then the install's
  5. a hosted API that has no /props is never sent llama.cpp's flags, never
     says it is writing, still says it has the request, and keeps saying
     so at its keepalives
  6. unasked, the hosted API sends nothing extra either
  7. (EP_CLAUDE=1) the real Claude Code CLI: a tool it runs, and its
     thinking, reach the caller before its answer. Spends a Haiku call.
  8. teardown by pid; no owned port still listening

**Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable is
dropped, ports are +300, teardown is by pid. Never `pkill -f
eugene_plexus_`: this box is a worker node.

Run with the gateway's interpreter (it has httpx):
  gateway/.venv/Scripts/python.exe specs/scripts/progress-acceptance.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("EP_ROOT", "D:/py/eugene-plexus"))
GW_PY = ROOT / "gateway" / ".venv" / "Scripts" / "python.exe"
DRV_PY = ROOT / "inference-driver" / ".venv" / "Scripts" / "python.exe"
TEMP = Path(os.environ.get("TEMP", tempfile.gettempdir()))
LLAMA = Path(
    os.environ.get(
        "EP_LLAMA_SERVER", str(TEMP / "ep-second-vendor/engines/llama_cpp/b11215/llama-server.exe")
    )
)
MODEL_FILE = Path(
    os.environ.get(
        "EP_MODEL_FILE",
        str(TEMP / "ep-download-and-run/models/unsloth/Qwen3-0.6B-GGUF/Qwen3-0.6B-Q4_K_M.gguf"),
    )
)
CLAUDE = os.environ.get("EP_CLAUDE") == "1"

GW_PORT, AGENT_PORT, DRV_A, ENGINE, DRV_B, HOSTED, DRV_C = range(8390, 8397)
OWNED = [GW_PORT, AGENT_PORT, DRV_A, ENGINE, DRV_B, HOSTED, DRV_C]
GW = f"http://127.0.0.1:{GW_PORT}"
LOCAL, HOSTED_MODEL, CLAUDE_MODEL = "progress-local", "progress-hosted", "progress-claude"

FAILURES = 0


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


def ok(text: str) -> None:
    print(f"  PASS  {text}", flush=True)


def bad(text: str) -> None:
    global FAILURES
    FAILURES += 1
    print(f"  FAIL  {text}", flush=True)


def note(text: str) -> None:
    print(f"  NOTE  {text}", flush=True)


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


# --------------------------------------------------------------------------- #
# The stub agent (topology only) and the stub hosted API
# --------------------------------------------------------------------------- #

HOSTED_BODIES: list[dict[str, Any]] = []
LOCK = threading.Lock()


class Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        pass

    def _json(self, body: Any, status: int = 200) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        port = self.server.server_address[1]
        path = self.path.split("?")[0]
        if port == AGENT_PORT:
            if path == "/v1/components":
                drivers = [("progress-a", DRV_A), ("progress-b", DRV_B)]
                if CLAUDE:
                    drivers.append(("progress-c", DRV_C))
                return self._json(
                    {
                        "components": [
                            {
                                "name": name,
                                "kind": "inference-driver",
                                "url": f"http://127.0.0.1:{p}/",
                                "status": "running",
                            }
                            for name, p in drivers
                        ]
                    }
                )
            if path == "/v1/runtimes":
                return self._json({"runtimes": []})
            if path == "/v1/node":
                return self._json({"name": "progress-node", "enrolled": False})
            return self._json({"status": "ok"})
        # The hosted API: no /props, no /api/ps -- a hosted provider has
        # neither -- and one model.
        if path == "/v1/models":
            return self._json({"data": [{"id": HOSTED_MODEL, "object": "model"}]})
        return self._json({"error": {"message": "not found"}}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        with LOCK:
            HOSTED_BODIES.append(body)
        if not body.get("stream"):
            return self._json(
                {
                    "choices": [
                        {"index": 0, "message": {"content": "1"}, "finish_reason": "stop"}
                    ]
                }
            )
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        # What OpenRouter does while a model is queued or thinking.
        for _ in range(5):
            self.wfile.write(b": OPENROUTER PROCESSING\n\n")
            self.wfile.flush()
            time.sleep(0.7)
        for piece in ({"content": "Hosted "}, {"content": "answer"}):
            frame = {"choices": [{"index": 0, "delta": piece, "finish_reason": None}]}
            self.wfile.write(b"data: " + json.dumps(frame).encode() + b"\n\n")
        done = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        self.wfile.write(b"data: " + json.dumps(done).encode() + b"\n\ndata: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


class Quiet(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A driver probe that hangs up early is not news.
        pass


def serve(port: int) -> None:
    Quiet(("127.0.0.1", port), Stub).serve_forever()


# --------------------------------------------------------------------------- #
# The probe: the gateway's stream, read as it arrives
# --------------------------------------------------------------------------- #


def stream(
    model: str,
    content: str,
    *,
    progress: bool,
    timeout: float = 600,
    max_tokens: int | None = 48,
    usage: bool = False,
) -> list[dict]:
    """Every data frame, stamped with seconds since the request was sent.

    httpx's `iter_lines` over a streamed response, not urllib: a buffering
    instrument reported a first token at 94% of a request once (M10).
    """
    import httpx

    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": True,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if progress:
        body["stream_options"] = {"include_progress": True}
    if usage:
        body.setdefault("stream_options", {})["include_usage"] = True
    frames: list[dict] = []
    started = time.perf_counter()
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        with client.stream("POST", f"{GW}/v1/chat/completions", json=body) as response:
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.read()[:300]!r}")
            for line in response.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                parsed = json.loads(line[6:])
                frames.append({"t": time.perf_counter() - started, "frame": parsed})
    return frames


def split(frames: list[dict]) -> tuple[list[dict], list[dict]]:
    """(progress chunks, output chunks) -- output meaning a role, a thought
    or a word; the final frame is neither and is left out."""
    progress, output = [], []
    for f in frames:
        chunk = f["frame"]
        if not chunk.get("choices") and (chunk.get("x_eugene_plexus") or {}).get("progress"):
            progress.append({"t": f["t"], **chunk["x_eugene_plexus"]["progress"]})
            continue
        delta = ((chunk.get("choices") or [{}])[0] or {}).get("delta") or {}
        if delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls"):
            output.append({"t": f["t"], **delta})
    return progress, output


def long_prompt() -> str:
    # A nonce first, so no two runs, and no two requests in one run,
    # share a cached prefix: the reading has to actually happen.
    nonce = uuid.uuid4().hex
    lines = " ".join(f"Line {i}: the river {i} runs to the east." for i in range(320))
    return f"[{nonce}] {lines} Which way do the rivers run? One word."


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    procs: list[subprocess.Popen] = []
    work = Path(tempfile.mkdtemp(prefix="ep-progress-"))

    def start(argv: list[str], log: str, env: dict[str, str], cwd: Path | None = None) -> None:
        handle = open(work / log, "w", encoding="utf-8")
        procs.append(
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        )

    def wait_for(port: int, seconds: float = 90) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if listening(port):
                return True
            time.sleep(0.5)
        return False

    try:
        say("0. isolate this run")
        base = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            base.pop(proxy, None)
            base.pop(proxy.lower(), None)
        ok("no ambient EUGENE_PLEXUS_* variable reaches a child")
        taken = [p for p in OWNED if listening(p)]
        if taken:
            bad(f"ports already in use: {taken}")
            return 1
        for path in (GW_PY, DRV_PY, LLAMA, MODEL_FILE):
            if not path.exists():
                bad(f"missing: {path}")
                return 1
        ok(f"ports {OWNED[0]}-{OWNED[-1]} free; llama-server {LLAMA.parent.name}; {MODEL_FILE.name}")

        say("1. a real engine, two real drivers, a real gateway")
        for port in (AGENT_PORT, HOSTED):
            threading.Thread(target=serve, args=(port,), daemon=True).start()
        start(
            [
                str(LLAMA), "-m", str(MODEL_FILE), "--host", "127.0.0.1", "--port", str(ENGINE),
                "-ngl", "0", "-t", "2", "-c", "8192", "-b", "256", "-ub", "256",
            ],
            "llama.log",
            {**base, "CUDA_VISIBLE_DEVICES": "-1", "GGML_VK_VISIBLE_DEVICES": ""},
        )

        def driver(name: str, port: int, config: str, cwd: Path | None = None) -> None:
            (work / f"{name}.yaml").write_text(config, encoding="utf-8")
            start(
                [str(DRV_PY), "-m", "eugene_plexus_inference_driver"],
                f"{name}.log",
                {
                    **base,
                    "EUGENE_PLEXUS_DRIVER_CONFIG_FILE": str(work / f"{name}.yaml"),
                    "EUGENE_PLEXUS_DRIVER_BIND_HOST": "127.0.0.1",
                    "EUGENE_PLEXUS_DRIVER_BIND_PORT": str(port),
                },
                cwd=cwd,
            )

        driver(
            "driver-a",
            DRV_A,
            f"provider: openai_compat_custom\nbaseUrl: http://127.0.0.1:{ENGINE}\n"
            f"modelId: {LOCAL}\nrequestTimeoutSeconds: 600\n",
        )
        driver(
            "driver-b",
            DRV_B,
            f"provider: openai_compat_custom\nbaseUrl: http://127.0.0.1:{HOSTED}\n"
            f"modelId: {HOSTED_MODEL}\nrequestTimeoutSeconds: 120\n",
        )
        if CLAUDE:
            cwd = work / "claude-cwd"
            cwd.mkdir()
            (cwd / "a.txt").write_text("hello\n", encoding="utf-8")
            driver(
                "driver-c",
                DRV_C,
                f"provider: claude_subscription\nmodelId: {CLAUDE_MODEL}\n"
                "upstreamModelId: claude-haiku-4-5-20251001\nrequestTimeoutSeconds: 240\n",
                cwd=cwd,
            )
        (work / "gateway.yaml").write_text("routingRefreshSeconds: 3\n", encoding="utf-8")
        start(
            [str(GW_PY), "-m", "eugene_plexus_gateway"],
            "gateway.log",
            {
                **base,
                "EUGENE_PLEXUS_GATEWAY_CONFIG_FILE": str(work / "gateway.yaml"),
                "EUGENE_PLEXUS_GATEWAY_METRICS_FILE": str(work / "metrics.sqlite3"),
                "EUGENE_PLEXUS_GATEWAY_BIND_HOST": "127.0.0.1",
                "EUGENE_PLEXUS_GATEWAY_BIND_PORT": str(GW_PORT),
                "EUGENE_PLEXUS_GATEWAY_AGENT_URL": f"http://127.0.0.1:{AGENT_PORT}",
            },
        )
        for port in (ENGINE, DRV_A, DRV_B, GW_PORT) + ((DRV_C,) if CLAUDE else ()):
            if not wait_for(port, 120):
                bad(f"nothing came up on {port}; logs in {work}")
                return 1
        import httpx

        wanted = {LOCAL, HOSTED_MODEL} | ({CLAUDE_MODEL} if CLAUDE else set())
        ids: set[str] = set()
        end = time.time() + 90
        while time.time() < end and not wanted <= ids:
            try:
                listed = httpx.get(f"{GW}/v1/models", timeout=5, trust_env=False).json()
                ids = {m["id"] for m in listed.get("data") or []}
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(1)
        if wanted <= ids:
            ok(f"the gateway routes {sorted(wanted)}")
        else:
            bad(f"expected {sorted(wanted)}, routable: {sorted(ids)}")
            return 1

        say("2. asked: the prompt's reading arrives, before the first word")
        asked = stream(LOCAL, long_prompt(), progress=True)
        reads, output = split(asked)
        prompt_reads = [r for r in reads if r.get("stage") == "prompt"]
        if len(prompt_reads) >= 5:
            ok(f"{len(prompt_reads)} progress chunks for the prompt's reading")
        else:
            bad(f"expected a chunk per batch, got {len(prompt_reads)}: {reads[:3]}")
        processed = [r.get("processed_tokens", -1) for r in prompt_reads]
        total = prompt_reads[-1].get("prompt_tokens") if prompt_reads else None
        if processed == sorted(processed) and total and processed[-1] == total:
            ok(f"processed rises to the whole prompt: {processed[0]} ... {processed[-1]} of {total}")
        else:
            bad(f"processed does not rise to the total: {processed} of {total}")
        if output and prompt_reads and max(r["t"] for r in prompt_reads) <= output[0]["t"]:
            ok("every progress chunk came before the first word")
        else:
            bad("a progress chunk came after output began, or there was no output")
        if output and prompt_reads:
            first_read, first_word = prompt_reads[0]["t"], output[0]["t"]
            print(
                f"  timeline: first progress at {first_read:.2f} s, last at "
                f"{prompt_reads[-1]['t']:.2f} s, first word at {first_word:.2f} s"
            )
            if first_word - first_read >= 1.5:
                ok(f"the caller heard {first_word - first_read:.1f} s before the model said anything")
            else:
                bad(f"progress arrived only {first_word - first_read:.2f} s ahead of the answer")
        text = "".join((o.get("content") or "") + (o.get("reasoning_content") or "") for o in output)
        ok(f"and then the model answered: {text[:60]!r}") if text else bad("no answer at all")

        say("3. unasked: nothing extra, and the silence the tester saw")
        plain = stream(LOCAL, long_prompt(), progress=False)
        plain_reads, plain_output = split(plain)
        if not plain_reads:
            ok("no progress chunk in a stream that did not ask")
        else:
            bad(f"{len(plain_reads)} progress chunks reached a caller who did not ask")
        if plain and plain[0]["t"] >= 1.5:
            ok(f"the first frame of any kind arrived at {plain[0]['t']:.1f} s: nothing before it")
        else:
            note("the first frame arrived early; the prompt read faster than the run expects")

        say("4. the gateway's time-to-first-token is the first word")
        page = httpx.get(
            f"{GW}/v1/metrics/requests", params={"model": LOCAL}, timeout=10, trust_env=False
        ).json()
        rows = page.get("requests") or []
        firsts = [
            a.get("firstMs")
            for row in rows
            for a in (row.get("tries") or [])
            if a.get("served") and a.get("firstMs") is not None
        ]
        if len(firsts) >= 2 and output and prompt_reads:
            # Newest first: [plain, asked]. The asked request's first
            # token must sit near its first word, not near its first
            # progress chunk.
            asked_first = firsts[1] / 1000
            if asked_first >= prompt_reads[-1]["t"] * 0.8:
                ok(f"its first token was timed at {asked_first:.2f} s, after the prompt was read")
            else:
                bad(f"first token timed at {asked_first:.2f} s, before the prompt was read")
        else:
            bad(f"no retained first-token times to compare: {firsts}")

        say("4b. while it writes: the backend's own count, and the cap it was sent")

        def final_routing(frames: list[dict]) -> dict:
            for f in reversed(frames):
                chunk = f["frame"]
                if any((c or {}).get("finish_reason") for c in chunk.get("choices") or []):
                    return chunk.get("x_eugene_plexus") or {}
            return {}

        def final_usage(frames: list[dict]) -> dict:
            for f in reversed(frames):
                if f["frame"].get("usage"):
                    return f["frame"]["usage"]
            return {}

        writing_frames = stream(
            LOCAL,
            "Count from one to forty in words, one per line.",
            progress=True,
            max_tokens=200,
            usage=True,
        )
        writes, written_out = split(writing_frames)
        counts = [w for w in writes if w.get("stage") == "generating"]
        numbers = [w.get("generated_tokens") or 0 for w in counts]
        completion = final_usage(writing_frames).get("completion_tokens")
        if len(counts) >= 2 and numbers == sorted(set(numbers)) and numbers[0] > 0:
            ok(f"{len(counts)} counts while it wrote, rising: {numbers[0]} ... {numbers[-1]}")
        else:
            bad(f"expected rising counts while it wrote, got {numbers}")
        # The first count can come a moment before the first word: llama.cpp
        # counts the token that opens its thinking on a frame with no text.
        if len(counts) >= 2 and any(counts[0]["t"] < o["t"] < counts[-1]["t"] for o in written_out):
            ok("the counts came between the words, as it wrote")
        else:
            bad("the counts did not come between the words")
        if numbers and completion and numbers[-1] <= completion:
            ok(f"the last count, {numbers[-1]}, is within the usage's {completion}")
        else:
            bad(f"last count {numbers[-1] if numbers else None} against usage {completion}")
        speeds = [w.get("tokens_per_second") for w in counts if w.get("tokens_per_second")]
        ok(f"and the backend's own speed: {speeds[-1]} tok/s") if speeds else bad("no speed said")
        cap = final_routing(writing_frames).get("output_cap")
        if cap == {"tokens": 200, "source": "request"}:
            ok("the final frame says the cap was the request's own 200")
        else:
            bad(f"the final frame's output_cap: {cap}")
        patched = httpx.patch(
            f"{GW}/v1/config", json={"defaultMaxTokens": 24}, timeout=10, trust_env=False
        )
        try:
            capped = stream(LOCAL, "Name ten rivers.", progress=False, max_tokens=None)
        finally:
            httpx.patch(f"{GW}/v1/config", json={"defaultMaxTokens": None}, timeout=10, trust_env=False)
        ended = next(
            (
                c.get("finish_reason")
                for f in reversed(capped)
                for c in f["frame"].get("choices") or []
                if c.get("finish_reason")
            ),
            None,
        )
        cap = final_routing(capped).get("output_cap")
        if patched.status_code == 200 and ended == "length" and cap == {"tokens": 24, "source": "install"}:
            ok("a reply stopped by the install's cap says it was the install's 24 (Troy's case)")
        else:
            bad(f"install cap: PATCH {patched.status_code}, finish {ended}, output_cap {cap}")

        say("5. a hosted API: never sent llama.cpp's flag, and still heard from")
        HOSTED_BODIES.clear()
        hosted = stream(HOSTED_MODEL, "hello", progress=True)
        h_reads, h_output = split(hosted)
        streamed = [b for b in HOSTED_BODIES if b.get("stream")]
        if streamed and not {"return_progress", "timings_per_token"} & streamed[-1].keys():
            ok("the hosted API was not sent return_progress or timings_per_token, which it would refuse")
        else:
            bad(f"the hosted API's body: {streamed[-1] if streamed else None}")
        stages = [r.get("stage") for r in h_reads]
        if stages and set(stages) == {"working"} and 2 <= len(stages) <= 3:  # never `generating`
            ok(f"'working' when it opened and at its keepalives, throttled: {len(stages)} for 5")
        else:
            bad(f"expected 2-3 working chunks, got {stages}")
        if h_reads and h_output and h_reads[0]["t"] < 1.0 < h_output[0]["t"]:
            ok(f"heard at {h_reads[0]['t']:.2f} s; the first word came at {h_output[0]['t']:.2f} s")
        else:
            bad("the hosted API's progress did not come ahead of its answer")
        answer = "".join(o.get("content") or "" for o in h_output)
        ok("the answer is intact") if answer == "Hosted answer" else bad(f"answer: {answer!r}")

        say("6. unasked, the hosted API sends nothing extra")
        HOSTED_BODIES.clear()
        quiet = stream(HOSTED_MODEL, "hello", progress=False)
        q_reads, _ = split(quiet)
        streamed = [b for b in HOSTED_BODIES if b.get("stream")]
        if not q_reads and streamed and "return_progress" not in streamed[-1]:
            ok("no progress chunk, and no flag sent")
        else:
            bad(f"{len(q_reads)} progress chunks; body {streamed[-1] if streamed else None}")

        if CLAUDE:
            say("7. the real Claude Code CLI: its tool and its thinking reach the caller")
            prompt = "Read the file a.txt with your Read tool, then tell me what it says."
            # No max_tokens: Claude Code cannot carry it, and refuses a
            # setting it would otherwise silently drop.
            try:
                claude = stream(CLAUDE_MODEL, prompt, progress=True, timeout=300, max_tokens=None)
            except RuntimeError as exc:
                bad(f"Claude Code did not answer: {exc}")
                claude = []
            c_reads, c_output = split(claude)
            tools = [r for r in c_reads if r.get("stage") == "tool"]
            words = [o for o in c_output if o.get("content")]
            thoughts = [o for o in c_output if o.get("reasoning_content")]
            if tools and tools[0].get("tool") == "Read":
                ok(f"the Read tool was reported at {tools[0]['t']:.1f} s")
            else:
                bad(f"no Read tool reported: {c_reads}")
            if tools and words and tools[0]["t"] < words[0]["t"]:
                ok(f"before its first word at {words[0]['t']:.1f} s")
            else:
                bad("the tool was not reported ahead of the answer")
            if thoughts:
                ok(f"{len(thoughts)} fragments of its thinking reached the caller")
            else:
                note("Claude did not think on this turn; its thinking is unit-tested")
            said = "".join(o.get("content") or "" for o in words).lower()
            ok("and it answered from the file") if "hello" in said else bad(f"answer: {said!r}")
        else:
            note("7 skipped: set EP_CLAUDE=1 to run the real Claude Code CLI (one Haiku call)")
    finally:
        say("8. teardown")
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        time.sleep(1)
        still = [p for p in OWNED if p not in (AGENT_PORT, HOSTED) and listening(p)]
        ok("no owned port still listening") if not still else bad(f"still listening: {still}")
        print(f"  logs: {work}")

    print(f"\n{'ALL PASS' if FAILURES == 0 else f'{FAILURES} FAILED'}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
