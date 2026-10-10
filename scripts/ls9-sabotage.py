"""LS9 sabotage pass: the best route for this machine (library-sources-and-engines.md
§6.12, Troy's B54 change). Only the code that changed. Restores from a COPY,
never `git checkout --`, and opens with a baseline per gate.

Usage: python specs/scripts/ls9-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
TIMEOUT = 900

RULE = "ui/src/lib/eligibility.ts"
ROUTE = "ui/src/components/BestRoute.tsx"
DOT = "ui/src/components/EligibilityDot.tsx"
PAGE = "ui/src/app/library/page.tsx"

GATES: dict[str, tuple[str, list[str]]] = {
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/lib/eligibility.test.ts",
        "src/components/EligibilityDot.test.tsx", "src/app/library/page.test.tsx",
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    ("THE RULE: preparing is recommended even when llama.cpp fits on the card", "ui", RULE,
     '  if (asIs.fit.verdict !== "split" && asIs.fit.verdict !== "no") return null;', ""),
    ("an unestimated fit counts", "ui", RULE,
     "  if (!asIs?.fit?.estimated) return null;", "  if (!asIs?.fit) return null;"),
    ("a preparing engine that only fits tightly is recommended", "ui", RULE,
     '      (v.fit.verdict === "fits" || v.fit.verdict === "split"),',
     '      v.fit.verdict !== "no",'),
    ("a preparing engine not installed here is recommended", "ui", RULE,
     "    (v) =>\n      v.available &&\n      v.verdict === \"after_preparation\" &&",
     "    (v) =>\n      v.verdict === \"after_preparation\" &&"),
    ("the why says the wrong thing when llama.cpp cannot fit it", "ui", RULE,
     '    route.asIs.fit?.verdict === "no"', "    false"),
    ("THE RULE: Run's question opens on running now", "ui", ROUTE,
     '  const [choice, setChoice] = useState<"prepare" | "now">("prepare");',
     '  const [choice, setChoice] = useState<"prepare" | "now">("now");'),
    ("the dot says nothing beside itself", "ui", DOT,
     "  const route = betterAfterPreparing(answer.engines);", "  const route = null;"),
    ("the model page never asks", "ui", PAGE,
     "      ? betterAfterPreparing(verdicts)", "      ? null"),
    ("the recommended engine's Prepare shows twice", "ui", PAGE,
     'v.verdict === "after_preparation" && v.engine !== route?.prepare.engine',
     'v.verdict === "after_preparation"'),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, command = GATES[name]
    where = str(ROOT / repo)
    try:
        done = subprocess.run(command, cwd=where, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:] + (done.stderr or "")[-500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="append", choices=sorted(GATES))
    parser.add_argument("--label", action="append", help="run only entries whose label has this")
    parser.add_argument("--anchors", action="store_true", help="check every anchor, run nothing")
    args = parser.parse_args()
    chosen = [
        s
        for s in SABOTAGES
        if (not args.gate or s[1] in args.gate)
        and (not args.label or any(part in s[0] for part in args.label))
    ]
    gates = sorted({s[1] for s in chosen})
    missing = [
        (label, io.open(ROOT / relative, encoding="utf-8").read().count(old))
        for label, _gate, relative, old, _new in chosen
        if io.open(ROOT / relative, encoding="utf-8").read().count(old) != 1
    ]
    if missing:
        for label, count in missing:
            print(f"[ANCHOR ] {label}: matched {count} times")
        return 1
    if args.anchors:
        print(f"{len(chosen)} anchors, each matched once")
        return 0
    backup = Path(tempfile.mkdtemp(prefix="ls9-sabotage-"))
    for _label, _gate, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
    print(f"copy in {backup}\n")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, gate, relative, old, new in chosen:
        path = ROOT / relative
        source = io.open(path, encoding="utf-8").read()
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, _out = run_gate(gate)
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] ({gate}) {label}")
            caught += 1
        else:
            print(f"[ESCAPED] ({gate}) {label}")
            escaped += 1
    print(f"\n{caught} caught, {escaped} escaped, {len(chosen)} sabotages")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
