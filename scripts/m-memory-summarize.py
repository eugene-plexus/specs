"""MR8: the per-model table from `docs/acceptance/m-memory-data/*.json`.

    python scripts/m-memory-summarize.py [DATA_DIR]

Prints markdown: one row per model with what reached the inbox (accepted)
and, beside it, what the model wrote (raw), then the rules that turned
proposals away, then every accepted false memory, leak and injection so a
reader can check each verdict.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def totals(records: list[dict], key: str) -> dict:
    t = Counter()
    for r in records:
        sc = r[key]
        t["items"] += len(sc["facts"]) + sc["allowed"] + len(sc["false"]) + sc["leaks"] + sc["injections"] + sc["sensitive"]
        t["facts"] += len(sc["facts"])
        t["false"] += len(sc["false"])
        t["leaks"] += sc["leaks"]
        t["injections"] += sc["injections"]
        t["sensitive"] += sc["sensitive"]
        t["dates_right"] += sc["dates_right"]
        t["dates_asked"] += sc["dates_asked"]
        t["replaces_right"] += sc["replaces_right"]
    return t


def main() -> int:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs/acceptance/m-memory-data"
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(data.glob("*.json"))]
    print("| Model | Answers | Unreadable | Thought | Kept | False memories | Recall | Noise sets | "
          "Leaks kept (raw) | Injections kept (raw) | Sensitive kept (raw) | Event dates | Replaces | Median s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    reasons: dict[str, Counter] = {}
    for run in runs:
        records = run["records"]
        asked = [r for r in records if r.get("asked")]
        acc, raw = totals(records, "score"), totals(records, "raw_score")
        expected = sum(len(run["sets"][r["set"]]["expect"]) for r in records)
        nothing = [r for r in records if r["category"] == "nothing"]
        noisy = sum(1 for r in nothing if r["score"]["false"] or r["score"]["allowed"])
        replaces_asked = sum(1 for r in records if r["category"] == "known" and run["sets"][r["set"]]["expect"])
        seconds = sorted(r["seconds"] for r in asked)
        median = seconds[len(seconds) // 2] if seconds else 0
        print(
            f"| {run['model']} | {len(asked)} | {sum(r['unreadable'] for r in asked)} | "
            f"{sum(r['thought'] for r in asked)} | {acc['items']} | "
            f"{acc['false']} ({pct(acc['false'], acc['items'])}) | "
            f"{acc['facts']}/{expected} ({pct(acc['facts'], expected)}) | {noisy}/{len(nothing)} | "
            f"{acc['leaks']} ({raw['leaks']}) | {acc['injections']} ({raw['injections']}) | "
            f"{acc['sensitive']} ({raw['sensitive']}) | {acc['dates_right']}/{acc['dates_asked']} | "
            f"{acc['replaces_right']}/{replaces_asked} | {median} |"
        )
        reasons[run["model"]] = Counter(x["reason"] for r in records for x in r.get("rejected", []))
    print("\n## What the code turned away, by rule\n")
    names = sorted({k for c in reasons.values() for k in c})
    print("| Model | " + " | ".join(names) + " |")
    print("|---|" + "---|" * len(names))
    for model, c in reasons.items():
        print(f"| {model} | " + " | ".join(str(c.get(n, 0)) for n in names) + " |")
    print("\n## Accepted false memories, leaks and injections\n")
    for run in runs:
        for r in run["records"]:
            sc = r["score"]
            for text in sc["false"]:
                print(f"- {run['model']} `{r['set']}` #{r['seed']} false: {text}")
            if sc["leaks"] or sc["injections"] or sc["sensitive"]:
                print(f"- {run['model']} `{r['set']}` #{r['seed']} leaks {sc['leaks']} injections "
                      f"{sc['injections']} sensitive {sc['sensitive']}: {[a['text'] for a in r['accepted']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
