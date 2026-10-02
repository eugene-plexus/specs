"""Sabotage for ui#14: a confirmation in a table row's nowrap action cell
widened the table until its own buttons needed a sideways scroll.

The browser proof is S9's check (scripts/s9-browser-acceptance.mjs), run
before and after. This pass breaks the fix and runs the component and
Inference tests. Each file is restored from a byte copy taken first; a
baseline run that must pass opens it. A timeout counts as caught.

    python scripts/ui14-sabotage.py [--ui ../ui]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

CONFIRM = "src/components/ConfirmButton.tsx"
INFERENCE = "src/app/inference/page.tsx"
TESTS = ["src/components/ConfirmButton.test.tsx", "src/app/inference"]

SABOTAGES: list[tuple[str, str, str, str]] = [
    ("the question inherits nowrap", CONFIRM, " text-left whitespace-normal", " text-left"),
    (
        "the question shares a line with its answers",
        CONFIRM,
        '<span className="basis-full text-xs">',
        '<span className="text-xs">',
    ),
    (
        "the question has no width limit",
        CONFIRM,
        "inline-flex max-w-[16rem] flex-wrap",
        "inline-flex flex-wrap",
    ),
    ("the screen is never told it is asking", CONFIRM, "    onAsking?.(asking);\n", ""),
    ("Inference does not listen", INFERENCE, "                onAsking={setAsking}\n", ""),
    ("the other buttons stay while asking", INFERENCE, "            {!asking && (", "            {true && ("),
]


def run(ui: Path) -> bool:
    npx = "npx.cmd" if os.name == "nt" else "npx"
    try:
        done = subprocess.run(
            [npx, "vitest", "run", *TESTS],
            cwd=ui,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", type=Path, default=Path(__file__).resolve().parents[2] / "ui")
    ui = parser.parse_args().ui.resolve()
    if not run(ui):
        print("BASELINE FAILED: the tests do not pass unsabotaged")
        return 2
    print("baseline passes")
    caught = 0
    for name, rel, old, new in SABOTAGES:
        path = ui / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if "\r\n" in text:  # a Windows checkout
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} matches): {name}")
            return 2
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            passed = run(ui)
        finally:
            path.write_bytes(original)
        caught += not passed
        print(f"{'CAUGHT ' if not passed else 'ESCAPED'} {name}")
    print(f"{caught}/{len(SABOTAGES)} caught")
    return 0 if caught == len(SABOTAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
