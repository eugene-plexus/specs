#!/usr/bin/env python3
"""Does an Apple-silicon engine reuse a growing conversation? (prompt-cache measurement)

Run on GitHub's macOS runners by `.github/workflows/prompt-cache-mac.yml`.
Stdlib only. It builds agent-shaped sessions from this repository's own text
(a long system prompt, then a file's contents per turn, the way a coding
agent's tool results arrive), then replays them, with one output token per
request, at an engine already listening:

    python prompt-cache-mac.py --url http://127.0.0.1:19601 --label mlx --report out.json

Three sessions one after another, then three taking turns. The reading is
time per request and the usage the engine reports. A llama-server also has
`llamacpp:prompt_tokens_total`, which says exactly what it read; mlx_lm.server
has no counter, so its time against a cold request of the same size is the
evidence there.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sessions(n: int, turns: int) -> list[list[list[dict]]]:
    """n sessions, each a list of `turns` message lists (each the full request)."""
    system = (ROOT / "docs/design/local-inference-control-plane.md").read_text(encoding="utf-8")[:24000]
    files = sorted((ROOT / "scripts").glob("*.py"), key=lambda p: p.name)[: turns * n + 4]
    out = []
    for s in range(n):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": f"Session {s + 1}: review each file I paste."}]
        requests = []
        for t in range(turns):
            body = files[(s * turns + t) % len(files)].read_text(encoding="utf-8")[:8000]
            if t:
                messages = messages + [{"role": "assistant", "content": f"Noted file {t}."},
                                       {"role": "user", "content": f"File {t + 1}:\n{body}"}]
            requests.append(list(messages))
        out.append(requests)
    return out


def post(url: str, payload: dict) -> tuple[float, dict]:
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=900) as r:
        data = json.loads(r.read())
    return time.perf_counter() - t, data


def counter(url: str) -> float | None:
    try:
        with urllib.request.urlopen(url + "/metrics", timeout=10) as r:
            text = r.read().decode()
    except Exception:  # noqa: BLE001 -- an engine without /metrics simply has no counter
        return None
    m = re.search(r"^llamacpp:prompt_tokens_total (\S+)", text, re.M)
    return float(m.group(1)) if m else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default="probe")
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    rows = []
    sets = sessions(3, 5)

    def ask(phase: str, s: int, t: int, messages: list[dict]) -> None:
        before = counter(args.url)
        took, data = post(args.url, {"model": args.model, "messages": messages, "max_tokens": 1,
                                     "temperature": 0, "stream": False})
        after = counter(args.url)
        usage = data.get("usage") or {}
        row = {"engine": args.label, "phase": phase, "session": s, "turn": t, "seconds": round(took, 3),
               "prompt_tokens": usage.get("prompt_tokens"),
               "cached": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
               "processed": None if before is None or after is None else after - before}
        rows.append(row)
        print(json.dumps(row), flush=True)

    # A cold reference: the same size as a first turn, a prefix nobody has sent.
    cold = [dict(m) for m in sets[0][0]]
    cold[0] = {"role": "system", "content": "Cold reference. " + cold[0]["content"][::-1]}
    ask("cold", 0, 0, cold)
    for s, requests in enumerate(sets, 1):
        for t, messages in enumerate(requests, 1):
            ask("sequential", s, t, messages)
    # Taking turns: a fresh conversation set, so nothing is warm from above.
    fresh = [[[dict(m, content=f"[i] {m['content']}") if m["role"] == "user" and i == 1 else m
               for i, m in enumerate(msgs)] for msgs in requests] for requests in sets]
    for t in range(5):
        for s, requests in enumerate(fresh, 1):
            ask("interleaved", s, t + 1, requests[t])
    args.report.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
