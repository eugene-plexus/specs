"""Score repetition detectors on the labelled evaluation set (specs row 19).

Run it from the gateway's own environment, because the detector under test is
the gateway's (`eugene_plexus_gateway.repetition`)::

    cd gateway && .venv/Scripts/python ../specs/scripts/evaluate-repetition-set.py \
        --output report.json

The data is `docs/acceptance/repetition-set/` (see its README). `cases.jsonl`
holds the cases, labels and provenance. Optional --tokens supplies token IDs
under a documented model tokenizer for a numerical vLLM comparison.

Two rules are scored on the same cases:

* the gateway's detector, driven through its real `Guard` (so the rules for
  which channel may stop an answer apply exactly as they do when serving), and
* vLLM's `repetition_detection` rule, re-implemented here from vLLM's source
  (`vllm/v1/core/sched/utils.py`, `check_sequence_repetition`, v0.18.1;
  Apache-2.0). vLLM is not installed or run. Without --tokens this comparison
  is source-only; characters or words are never passed off as model tokens.

A case is a *stop* when the rule would end the answer part-way. `label` is
`loop` (a degenerate repeat that would run on), `legitimate` (a person wants
that answer) or `ambiguous` (a poor answer that ended by itself; listed but not
scored). The report holds counts and positions, never the text.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from eugene_plexus_gateway.driver_client import StreamEvent
from eugene_plexus_gateway.repetition import MAX_PERIOD, SCAN_EVERY, Guard, Policy

DATA = Path(__file__).resolve().parent.parent / "docs" / "acceptance" / "repetition-set"
LABELS = ("loop", "legitimate", "ambiguous")
CHUNK = 8  # Detection checkpoints are independent of transport chunk boundaries.

# What the sweep covers. The gateway's current setting is 100 characters x 4.
EUGENE_MIN_CHARS = (64, 80, 100, 128, 160, 200, 256, 384, 512, 1024, 1600, 2048)
EUGENE_REPEATS = (3, 4, 5, 6, 8)
# vLLM defaults to disabled: `repetition_detection` needs max size and count;
# minimum size defaults to one. These cover small units (1) up to ~25
# tokens) and long units (512 tokens).
VLLM_MIN_PATTERN = (1, 4, 25)
VLLM_MAX_PATTERN = (32, 128, 512)
VLLM_MIN_COUNT = (3, 4, 5, 8, 16)


# ---------------------------------------------------------------- the data


def materialize(case: dict[str, Any]) -> str:
    """The text of a case: literal, or built from its `construct` recipe.

    A recipe is a list of `{"text": ..., "copies": n}` parts. `<n>` in a part's
    text becomes the copy's number (starting at `start`, default 1), so a
    counting loop can be written without a thousand lines of data.
    """
    if "text" in case:
        return str(case["text"])
    out: list[str] = []
    for part in case["construct"]:
        start = int(part.get("start", 1))
        for i in range(int(part.get("copies", 1))):
            out.append(str(part["text"]).replace("<n>", str(start + i)))
    return "".join(out)


def load_cases(path: Path, tokens_path: Path | None = None) -> list[dict[str, Any]]:
    cases = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    tokens = None
    if tokens_path is not None:
        with gzip.open(tokens_path, "rt", encoding="utf-8") as handle:
            tokens = json.load(handle)
    seen: set[str] = set()
    for case in cases:
        name = case.get("id")
        if not isinstance(name, str) or name in seen:
            raise SystemExit(f"case id missing or repeated: {name!r}")
        seen.add(name)
        if case.get("label") not in LABELS:
            raise SystemExit(f"{name}: label must be one of {LABELS}")
        if ("text" in case) == ("construct" in case):
            raise SystemExit(f"{name}: needs exactly one of text and construct")
        case["_text"] = materialize(case)
        digest = hashlib.sha256(case["_text"].encode()).hexdigest()
        if case.get("sha256") != digest:
            raise SystemExit(f"{name}: text does not match its recorded sha256")
        if tokens is not None:
            record = tokens.get(name, {})
            ids = record.get("ids")
            if (
                not isinstance(ids, list)
                or not ids
                or any(type(token) is not int for token in ids)
                or record.get("sha256") != digest
            ):
                raise SystemExit(f"{name}: missing or stale token ids in {tokens_path}")
            case["_ids"] = ids
    return cases


def eligible(case: dict[str, Any]) -> bool:
    """Whether the gateway may stop this answer at all (visible streamed text)."""
    return case.get("channel", "text") == "text" and not case.get("structured", False)


# ---------------------------------------------------------- the gateway rule


def eugene_run(case: dict[str, Any], policy: Policy) -> dict[str, Any]:
    guard = Guard(policy)
    guard.structured = bool(case.get("structured", False))
    channel = case.get("channel", "text")
    text = case["_text"]
    stopped_at = None
    for offset in range(0, len(text), CHUNK):
        piece = text[offset : offset + CHUNK]
        if channel == "reasoning":
            event = StreamEvent(reasoning=piece)
        elif channel == "tool":
            event = StreamEvent(tool_calls=[{"index": 0, "function": {"arguments": piece}}])
        else:
            event = StreamEvent(text=piece)
        if guard.take(event):
            stopped_at = min(len(text), offset + len(piece))
            break
    else:
        guard.take(StreamEvent(done=True))
    detected = any(d.detection is not None for d in guard.channels.values())
    return {
        "stop": stopped_at is not None,
        "detected": detected,
        "at": stopped_at,
        "of": len(text),
    }


# ------------------------------------------------------------- vLLM's rule


def vllm_has_repeating_pattern(ids: list[int], pattern_len: int, min_count: int) -> bool:
    """vLLM `_has_repeating_pattern`, unchanged."""
    for n in range(1, pattern_len + 1):
        target = ids[-n]
        for m in range(1, min_count):
            if ids[-(pattern_len * m + n)] != target:
                return False
    return True


def vllm_check(ids: list[int], min_pattern: int, max_pattern: int, min_count: int) -> bool:
    """vLLM `check_sequence_repetition`, unchanged (reference version)."""
    if min_pattern <= 0:
        min_pattern = 1
    if max_pattern <= 0 or min_count < 2 or min_pattern > max_pattern:
        return False
    for pattern_len in range(min_pattern, max_pattern + 1):
        if pattern_len * min_count > len(ids):
            return False
        if vllm_has_repeating_pattern(ids, pattern_len, min_count):
            return True
    return False


def vllm_first_stop(
    ids: list[int], min_pattern: int, max_pattern: int, min_count: int
) -> int | None:
    """The first token count at which vLLM's per-token check would stop.

    vLLM runs the check after every generated token. This gives the same answer
    as calling `vllm_check` on every prefix, but only tries pattern lengths whose
    previous occurrence of the last token lines up (the first comparison the
    reference makes), so a sweep stays fast. `--verify` compares the two.
    """
    min_pattern = max(1, min_pattern)
    if max_pattern <= 0 or min_count < 2 or min_pattern > max_pattern:
        return None
    last_seen: dict[int, list[int]] = defaultdict(list)
    for n in range(1, len(ids) + 1):
        token = ids[n - 1]
        previous = last_seen[token]
        previous.append(n - 1)
        if n < min_pattern * min_count:
            continue
        for position in reversed(previous[:-1]):
            pattern_len = (n - 1) - position
            if pattern_len > max_pattern:
                break
            if pattern_len < min_pattern or pattern_len * min_count > n:
                continue
            if vllm_has_repeating_pattern(ids[:n], pattern_len, min_count):
                return n
    return None


def vllm_run(case: dict[str, Any], rule: tuple[int, int, int]) -> dict[str, Any]:
    ids = case["_ids"]
    at = vllm_first_stop(ids, *rule)
    return {"stop": at is not None, "at": at, "of": len(ids)}


def verify_vllm_fast_path(cases: list[dict[str, Any]]) -> int:
    """Check the fast first-stop search against the reference on real prefixes."""
    checked = 0
    for case in cases[:: max(1, len(cases) // 25)]:
        ids = case["_ids"][:400]
        for rule in ((1, 32, 3), (4, 128, 4), (25, 512, 4)):
            fast = vllm_first_stop(ids, *rule)
            slow = next(
                (n for n in range(1, len(ids) + 1) if vllm_check(ids[:n], *rule)),
                None,
            )
            if fast != slow:
                raise SystemExit(f"fast path differs on {case['id']} {rule}: {fast} != {slow}")
            checked += 1
    return checked


# ------------------------------------------------------------------ scoring


def group_of(case: dict[str, Any]) -> str:
    if case["label"] == "ambiguous":
        return "ambiguous"
    if case["label"] == "loop":
        if not eligible(case):
            return "loop/other-channel"
        return "loop/real" if case["origin"].startswith("real") else "loop/constructed"
    return "legitimate/requested" if case.get("class") == "requested" else "legitimate/natural"


def score(
    rows: list[tuple[dict[str, Any], dict[str, Any]]], *, only_eligible: bool
) -> dict[str, Any]:
    """Counts and rates over the scored cases (never the ambiguous ones)."""
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"cases": 0, "stops": 0, "saved": []})
    for case, result in rows:
        group = group_of(case)
        if group == "ambiguous" or (only_eligible and not eligible(case)):
            continue
        entry = groups[group]
        entry["cases"] += 1
        if result["stop"]:
            entry["stops"] += 1
            if group.startswith("loop") and result["at"] is not None:
                entry["saved"].append(1 - result["at"] / max(1, result["of"]))
    tp = sum(g["stops"] for name, g in groups.items() if name.startswith("loop"))
    loops = sum(g["cases"] for name, g in groups.items() if name.startswith("loop"))
    fp_natural = groups["legitimate/natural"]["stops"]
    fp_requested = groups["legitimate/requested"]["stops"]
    fp = fp_natural + fp_requested
    saved = [s for g in groups.values() for s in g["saved"]]
    return {
        "loops": loops,
        "caught": tp,
        "recall": round(tp / loops, 3) if loops else None,
        "false_stops_natural": fp_natural,
        "natural_cases": groups["legitimate/natural"]["cases"],
        "false_stops_requested": fp_requested,
        "requested_cases": groups["legitimate/requested"]["cases"],
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "precision_natural_only": round(tp / (tp + fp_natural), 3) if tp + fp_natural else None,
        "mean_share_of_answer_saved": round(sum(saved) / len(saved), 3) if saved else None,
        "by_group": {
            name: {"cases": g["cases"], "stops": g["stops"]} for name, g in sorted(groups.items())
        },
    }


def evaluate(cases: list[dict[str, Any]], *, sweep: bool) -> dict[str, Any]:
    eugene_settings = (
        [(m, r) for m in EUGENE_MIN_CHARS for r in EUGENE_REPEATS] if sweep else [(100, 4)]
    )
    eugene = []
    for min_chars, repeats in eugene_settings:
        policy = Policy(mode="stop", min_chars=min_chars, repeats=repeats)
        rows = [(case, eugene_run(case, policy)) for case in cases]
        eugene.append(
            {
                "min_chars": min_chars,
                "repeats": repeats,
                "serving": score(rows, only_eligible=True),
                "cases": [
                    {
                        "id": c["id"],
                        "group": group_of(c),
                        "stop": r["stop"],
                        "detected": r["detected"],
                        "at_chars": r["at"],
                        "of_chars": r["of"],
                    }
                    for c, r in rows
                ],
            }
        )
    vllm_rules = (
        [(a, b, c) for a in VLLM_MIN_PATTERN for b in VLLM_MAX_PATTERN for c in VLLM_MIN_COUNT]
        if sweep
        else [(1, 128, 4), (25, 512, 4)]
    )
    if not all("_ids" in case for case in cases):
        vllm_rules = []
    vllm = []
    for rule in vllm_rules:
        rows = [(case, vllm_run(case, rule)) for case in cases]
        vllm.append(
            {
                "min_pattern_size": rule[0],
                "max_pattern_size": rule[1],
                "min_count": rule[2],
                # Same cases the gateway may stop, for a like-for-like comparison.
                "serving": score(rows, only_eligible=True),
                # vLLM cannot tell reasoning, tool arguments or JSON from the answer.
                "every_channel": score(rows, only_eligible=False),
                "cases": [
                    {
                        "id": c["id"],
                        "group": group_of(c),
                        "stop": r["stop"],
                        "at_tokens": r["at"],
                        "of_tokens": r["of"],
                    }
                    for c, r in rows
                ],
            }
        )
    return {
        "default_serving": score(
            [(case, eugene_run(case, Policy())) for case in cases], only_eligible=True
        ),
        "eugene": eugene,
        "vllm": vllm,
    }


def decision(settings: list[dict[str, Any]]) -> dict[str, Any]:
    """The brief's gate: no legitimate stops, and a majority of loops caught."""
    zero_false_stops = [
        row
        for row in settings
        if row["serving"]["false_stops_natural"] == 0
        and row["serving"]["false_stops_requested"] == 0
    ]
    best = max(zero_false_stops, key=lambda row: row["serving"]["caught"], default=None)
    enable = best is not None and best["serving"]["caught"] * 2 > best["serving"]["loops"]
    return {
        "recommended_mode": "stop" if enable else "observe",
        "gate": "zero legitimate false stops AND more than half the loops caught",
        "settings_tested": len(settings),
        "best_zero_false_stop": (
            {key: best[key] for key in ("min_chars", "repeats", "serving")} if best else None
        ),
    }


def composition(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for case in cases:
        counts[f"{group_of(case)} ({case['origin']})"] += 1
    return dict(sorted(counts.items()))


def table(report: dict[str, Any]) -> str:
    def line(name: str, s: dict[str, Any]) -> str:
        return (
            f"{name:<34} loops {s['caught']:>3}/{s['loops']:<3} recall {s['recall']}  "
            f"false stops natural {s['false_stops_natural']}/{s['natural_cases']} "
            f"requested {s['false_stops_requested']}/{s['requested_cases']}  "
            f"precision {s['precision']}"
        )

    lines = ["Gateway detector (serving rules: visible streamed text only)"]
    for item in report["eugene"]:
        lines.append(line(f"  {item['min_chars']} chars x {item['repeats']}", item["serving"]))
    lines.append("vLLM repetition_detection, same cases the gateway may stop")
    if not report["vllm"]:
        lines.append("  Source comparison only: no model tokenizer/token IDs available.")
    for item in report["vllm"]:
        name = (
            f"  pattern {item['min_pattern_size']}-{item['max_pattern_size']} x {item['min_count']}"
        )
        lines.append(line(name, item["serving"]))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cases", type=Path, default=DATA / "cases.jsonl")
    parser.add_argument("--tokens", type=Path, help="optional gzipped, text-hashed model token IDs")
    parser.add_argument("--output", type=Path, help="write the full JSON report here")
    parser.add_argument("--sweep", action="store_true", help="try the threshold grids")
    parser.add_argument("--verify", action="store_true", help="check vLLM fast path first")
    parser.add_argument(
        "--fail-on-false-stop",
        action="store_true",
        help="exit 1 if the candidate stop policy stops ANY legitimate case",
    )
    args = parser.parse_args()

    cases = load_cases(args.cases, args.tokens)
    started = time.perf_counter()
    if args.verify and args.tokens:
        print(f"vLLM fast path matches the reference on {verify_vllm_fast_path(cases)} runs")
    result = evaluate(cases, sweep=args.sweep)
    report = {
        "kind": "labelled evaluation set; recorded outputs, no live backend",
        "python": platform.python_version(),
        "system": platform.system(),
        "gateway_default_policy": {
            "mode": Policy().mode,
            "min_chars": Policy().min_chars,
            "repeats": Policy().repeats,
        },
        "max_period_chars": MAX_PERIOD,
        "scan_interval_chars": SCAN_EVERY,
        "stream_chunk_chars": CHUNK,
        "composition": composition(cases),
        "decision": decision(result["eugene"]),
        "corpus_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "vllm_source": {
            "url": "https://github.com/vllm-project/vllm/blob/v0.18.1/vllm/v1/core/sched/utils.py",
            "blob_sha": "c7cb6b94367e7ed331947c7ad27196165054c8ff",
            "comparison": "token replay" if args.tokens else "source only; no model token IDs",
        },
        "seconds": round(time.perf_counter() - started, 1),
        **result,
    }
    if args.output:
        args.output.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["composition"], indent=1))
    print(table(report))
    if args.fail_on_false_stop:
        current = next(e for e in report["eugene"] if (e["min_chars"], e["repeats"]) == (100, 4))[
            "serving"
        ]
        if current["false_stops_natural"] + current["false_stops_requested"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
