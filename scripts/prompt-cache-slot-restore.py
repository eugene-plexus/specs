#!/usr/bin/env python3
"""Is a saved slot faster to bring back than the prompt is to read again?

An instrument for the prompt-cache measurement (2026-10-02). An engine that
is stopped -- idle unload, a restart, a crash -- loses its whole prompt
cache, so the next request reads its prompt from the first token. llama-server
can save a slot's cache to a file (`--slot-save-path`, `POST
/slots/{id}?action=save`) and restore it into a fresh process. This measures,
for one captured request:

  1. reading the prompt cold (the time a stop costs today);
  2. saving the slot: seconds and bytes on disk;
  3. a fresh process restoring it, and the same request's next turn:
     restore seconds plus what was still read.

    python prompt-cache-slot-restore.py --llama-dir <dir> --model <gguf>
        --session <claude-1.jsonl> [--engine-arg=--device --engine-arg=none]

The port is chosen by the OS and is never in 8079-8290.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

LIVE = range(8079, 8291)


def port() -> int:
    while True:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        if p not in LIVE:
            return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llama-dir", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--session", type=Path, required=True)
    ap.add_argument("--ctx", type=int, default=40960)
    ap.add_argument("--engine-arg", dest="engine_args", action="append", default=[])
    args = ap.parse_args()
    rows = [json.loads(x) for x in args.session.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if r.get("body") and r["body"].get("tools") and "count_tokens" not in r["path"]]
    first, second = rows[0]["body"], rows[1]["body"]
    anthropic = "system" in first or rows[0]["path"].startswith("/v1/messages")
    path = "/v1/messages" if anthropic else "/v1/responses"

    def shape(body: dict) -> dict:
        body = dict(body, model="probe", stream=False)
        if anthropic:
            body["max_tokens"] = 1
            body.pop("thinking", None)
        else:
            body["max_output_tokens"] = 16
        return body

    binary = args.llama_dir / ("llama-server.exe" if os.name == "nt" else "llama-server")
    http = httpx.Client(timeout=1800, trust_env=False)
    with tempfile.TemporaryDirectory(prefix="ep-slot-") as tmp:
        saves = Path(tmp) / "slots"
        saves.mkdir()
        p = port()
        base = f"http://127.0.0.1:{p}"
        log = open(Path(tmp) / "llama.log", "ab")

        def start():
            proc = subprocess.Popen(
                [str(binary), "-m", str(args.model), "--alias", "probe", "--host", "127.0.0.1",
                 "--port", str(p), "--metrics", "--jinja", "-c", str(args.ctx), "-np", "1",
                 "--slot-save-path", str(saves), *args.engine_args],
                stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.time() + 300
            while time.time() < deadline:
                try:
                    if http.get(base + "/health").status_code == 200:
                        return proc
                except httpx.HTTPError:
                    pass
                time.sleep(0.3)
            raise SystemExit("llama-server did not come up")

        def processed() -> float:
            m = re.search(r"^llamacpp:prompt_tokens_total (\S+)", http.get(base + "/metrics").text, re.M)
            return float(m.group(1)) if m else 0.0

        def ask(body: dict) -> tuple[float, float]:
            before = processed()
            t = time.perf_counter()
            r = http.post(base + path, json=shape(body))
            r.raise_for_status()
            return time.perf_counter() - t, processed() - before

        proc = start()
        cold_s, cold_n = ask(first)
        print(f"cold read: {cold_n:.0f} tokens in {cold_s:.2f}s")
        warm_s, warm_n = ask(second)
        print(f"next turn, same process: {warm_n:.0f} tokens in {warm_s:.2f}s")
        t = time.perf_counter()
        r = http.post(base + "/slots/0?action=save", json={"filename": "s.bin"})
        save_s = time.perf_counter() - t
        size = (saves / "s.bin").stat().st_size if (saves / "s.bin").exists() else 0
        print(f"save: HTTP {r.status_code} in {save_s:.2f}s, {size / 2**20:.0f} MiB  {r.text[:160]}")
        proc.terminate()
        proc.wait(timeout=30)

        proc = start()
        t = time.perf_counter()
        r = http.post(base + "/slots/0?action=restore", json={"filename": "s.bin"})
        restore_s = time.perf_counter() - t
        print(f"restore into a fresh process: HTTP {r.status_code} in {restore_s:.2f}s  {r.text[:160]}")
        after_s, after_n = ask(second)
        print(f"next turn after restore: {after_n:.0f} tokens in {after_s:.2f}s")
        proc.terminate()
        proc.wait(timeout=30)

        proc = start()
        cold2_s, cold2_n = ask(second)
        print(f"next turn in a fresh process, no restore: {cold2_n:.0f} tokens in {cold2_s:.2f}s")
        proc.terminate()
        proc.wait(timeout=30)
        log.close()
        tail = (Path(tmp) / "llama.log").read_text(encoding="utf-8", errors="replace")
        for line in tail.splitlines():
            if re.search(r"restor|checkpoint|re-process|slot_save|slot_restore", line, re.I):
                print("  log:", line.strip()[:200])
        print(json.dumps({"model": args.model.name, "cold_tokens": cold_n, "cold_s": round(cold_s, 2),
                          "save_s": round(save_s, 2), "save_mib": round(size / 2**20),
                          "restore_s": round(restore_s, 2), "after_restore_tokens": after_n,
                          "after_restore_s": round(after_s, 2), "fresh_tokens": cold2_n,
                          "fresh_s": round(cold2_s, 2)}))


if __name__ == "__main__":
    main()
