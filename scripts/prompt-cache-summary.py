#!/usr/bin/env python3
"""Tables from `prompt-cache-measurement.py` results: what was read, what was reused.

    python prompt-cache-summary.py results.jsonl [more.jsonl ...]

`processed` is the engine's own counter (tokens it computed). The prompt's
size is `processed` plus what the response says came from the cache; a row
whose response carried no usage counts as fully processed.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def cached_of(usage: dict | None) -> int:
    if not isinstance(usage, dict):
        return 0
    if "cache_read_input_tokens" in usage:
        return int(usage.get("cache_read_input_tokens") or 0)
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    return int(details.get("cached_tokens") or 0)


def main() -> None:
    rows = []
    for name in sys.argv[1:]:
        rows += [json.loads(x) for x in Path(name).read_text(encoding="utf-8").splitlines() if x.strip()]
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["experiment"] + (f" [{r['model']}]" if r.get("model") and not r["experiment"].startswith("family") else ""),
                r["client"], r["target"])].append(r)
    print(f"{'experiment':<22} {'client':<7} {'target':<8} {'reqs':>4} {'prompt':>9} {'read':>9} "
          f"{'reused':>7} {'seconds':>8} {'first turns read':>17} {'errors':>6}")
    for (exp, client, target), rs in groups.items():
        ok = [r for r in rs if r["status"] == 200]
        read = sum(r["processed"] for r in ok)
        prompt = sum(r["processed"] + cached_of(r["usage"]) for r in ok)
        seconds = sum(r["seconds"] for r in ok)
        firsts = [int(r["processed"]) for r in ok if r["turn"] == 1]
        print(f"{exp:<22} {client:<7} {target:<8} {len(rs):>4} {prompt:>9.0f} {read:>9.0f} "
              f"{100 * (1 - read / prompt) if prompt else 0:>6.1f}% {seconds:>8.1f} "
              f"{str(firsts):>17} {len(rs) - len(ok):>6}")
    by_engine = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r["experiment"].startswith("interleaved2") and r.get("served_by"):
            by_engine[(r["experiment"], r["client"])][(r["session"], r["served_by"])] += 1
    for key, spread in by_engine.items():
        sessions = defaultdict(set)
        for (session, engine), _ in spread.items():
            sessions[session].add(engine)
        split = sum(1 for engines in sessions.values() if len(engines) > 1)
        print(f"{key[0]} {key[1]}: {split} of {len(sessions)} sessions were served by both replicas")


if __name__ == "__main__":
    main()
