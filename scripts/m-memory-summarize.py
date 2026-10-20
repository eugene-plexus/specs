"""MR8 and MV3: the per-model table from the measurement's data, and the file Workbench ships.

    workbench/.venv/Scripts/python scripts/m-memory-summarize.py [DATA_DIR] [--ship FILE]

Prints markdown: one row per model and path with what the code kept and, beside it, what the
model wrote (raw); the verdict per model against Suggest's bar and Keep automatically's; the
rules that turned proposals away; and every kept false memory, leak, injection and wrong
supersession, so a reader can check each verdict.

`--ship FILE` writes the measurements Workbench ships (`memory_measured.json`): for each model
named in `PATTERNS`, its pass (the run without `+tool`, `+tags` or `+thinking`), its tool path
and its tag-list run, with the verdict. The numbers and verdicts come from Workbench's own
`memory_measure`, so the file says what the screen will.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()

#: The models Workbench ships a measurement of: run name, display name, and the pattern a model
#: id must match (case ignored, anywhere; an "abliterated" fine-tune never matches).
_SEP = r"[-_ .]?"
PATTERNS = {
    "gemma-4-e4b": ("Gemma 4 E4B", rf"gemma{_SEP}4{_SEP}e4b"),
    "gemma-4-12b": ("Gemma 4 12B", rf"gemma{_SEP}4{_SEP}12b"),
    "qwen3.6-35b-a3b": ("Qwen3.6-35B-A3B", rf"qwen3\.6{_SEP}35b{_SEP}a3b"),
    "qwen3.8-27b": ("Qwen3.8-27B", rf"qwen3\.8{_SEP}27b"),
    "qwen3.5-4b": ("Qwen3.5-4B", rf"qwen3\.5{_SEP}4b"),
}


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("data", nargs="?", type=Path, default=HERE.parents[1] / "docs/acceptance/m-memory-data/mv3")
    parser.add_argument("--ship", type=Path, help="write Workbench's memory_measured.json here")
    parser.add_argument("--workbench", type=Path, default=HERE.parents[2] / "workbench" / "src")
    args = parser.parse_args()
    sys.path.insert(0, str(args.workbench))
    from eugene_plexus_workbench import memory_measure as mm  # type: ignore[import-not-found]

    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.data.glob("*.json"))]
    print("| Run | Answers | Unreadable | Kept | False memories | Recall | Noise | Leaks kept (raw) | "
          "Injections kept (raw) | Sensitive kept (raw) | Event dates | Supersession named | Wrong supersessions | Median s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    by_name: dict[str, dict[str, dict]] = {}
    reasons: dict[str, Counter] = {}
    for run in runs:
        records = run["records"]
        kept, raw = mm.summarize(records), mm.summarize(records, "raw_score")
        path = "tags" if run.get("tags") else run.get("path", "pass")
        if run.get("thinking") == "on":
            path = "thinking"
        name = run.get("name") or run["model"].split("+")[0]
        by_name.setdefault(name, {})[path] = {"metrics": kept, "run": run}
        print(
            f"| {run['model']} | {kept['answers']} | {kept['unreadable']} | {kept['kept']} | "
            f"{kept['false']} ({pct(kept['false'], kept['kept'])}) | "
            f"{kept['facts']}/{kept['expected']} ({pct(kept['facts'], kept['expected'])}) | "
            f"{kept['noise']}/{kept['noiseSets']} | {kept['leaks']} ({raw['leaks']}) | "
            f"{kept['injections']} ({raw['injections']}) | {kept['sensitive']} ({raw['sensitive']}) | "
            f"{kept['datesRight']}/{kept['datesAsked']} | {kept['replacesRight']}/{kept['changed']} | "
            f"{kept['replacesWrong']} | {kept['medianSeconds']} |"
        )
        reasons[run["model"]] = Counter(x["reason"] for r in records for x in r.get("rejected", []))
    print("\n## Verdicts\n")
    print("| Model | Suggest | Keep automatically | Tag list in the request |")
    print("|---|---|---|---|")
    shipped = []
    for name, paths in sorted(by_name.items()):
        if "pass" not in paths:
            continue
        p = paths["pass"]["metrics"]
        t = paths.get("tool", {}).get("metrics")
        g = paths.get("tags", {}).get("metrics")
        p8 = mm.summarize(paths["pass"]["run"]["records"], only=mm.MR8_IDS)
        g8 = mm.summarize(paths["tags"]["run"]["records"], only=mm.MR8_IDS) if "tags" in paths else None
        v = mm.verdict(p, t, g, suggest=p8, tags_suggest=g8)
        print(f"| {name} | {'yes' if v['suggest'] else 'no: ' + v['why']['suggest']} | "
              f"{'yes' if v['keep'] else 'no: ' + str(v['why']['keep'])} | {'yes' if v['tags'] else 'no'} |")
        if name in PATTERNS:
            run = paths["pass"]["run"]
            display, pattern = PATTERNS[name]
            shipped.append({
                "name": display, "pattern": pattern, "measuredOn": run.get("measuredOn") or "",
                "engine": run.get("engine"), "file": run.get("file"), "samples": run.get("samples"),
                "sets": len(run.get("sets") or {}), "pass": p, "passMr8": p8, "tool": t, "tags": g,
                "tagsMr8": g8, "verdict": v,
            })
    print("\n## What the code turned away, by rule\n")
    names = sorted({k for c in reasons.values() for k in c})
    print("| Run | " + " | ".join(names) + " |")
    print("|---|" + "---|" * len(names))
    for model, c in reasons.items():
        print(f"| {model} | " + " | ".join(str(c.get(n, 0)) for n in names) + " |")
    print("\n## Kept false memories, leaks, injections and wrong supersessions\n")
    for run in runs:
        for r in run["records"]:
            sc = r["score"]
            for text in sc["false"]:
                print(f"- {run['model']} `{r['set']}` #{r['seed']} false: {text}")
            if sc["leaks"] or sc["injections"] or sc["sensitive"] or sc.get("replaces_wrong"):
                print(f"- {run['model']} `{r['set']}` #{r['seed']} leaks {sc['leaks']} injections "
                      f"{sc['injections']} sensitive {sc['sensitive']} wrong supersessions "
                      f"{sc.get('replaces_wrong', 0)}: {[a['text'] for a in r.get('kept', r.get('accepted', []))]}")
    if args.ship:
        document = {
            "generatedBy": "specs/scripts/m-memory-summarize.py --ship",
            "bars": {"suggest": mm.SUGGEST_BAR, "keep": mm.KEEP_BAR},
            "models": shipped,
        }
        with args.ship.open("w", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        print(f"\nwrote {args.ship} ({len(shipped)} models)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
