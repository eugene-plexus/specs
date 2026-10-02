"""Sabotage for agent#6's console half: a profile saved as a checkbox keeps
what it did (true is on, false is llama.cpp's own choice), and the builder
writes "on".

Each file is restored from a byte copy taken first; a baseline run that must
pass opens it. A timeout counts as caught.

    python scripts/agent6-ui-sabotage.py [--ui ../ui]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

LEGACY = "src/lib/legacyFlags.ts"
BUILD = "src/lib/profileBuild.ts"
EDITOR = "src/components/ProfileEditor.tsx"
TESTS = [
    "src/lib/legacyFlags.test.ts",
    "src/lib/profileBuild.test.ts",
    "src/components/ProfileEditor.test.tsx",
]

SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "an old false reads as off (the over-correction)",
        LEGACY,
        "  else if (out.flashAttention === false) delete out.flashAttention;",
        '  else if (out.flashAttention === false) out.flashAttention = "off";',
    ),
    (
        "an old true stays a boolean",
        LEGACY,
        '  if (out.flashAttention === true) out.flashAttention = "on";',
        "  if (out.flashAttention === true) out.flashAttention = true;",
    ),
    (
        "the editor opens old flags as they are",
        EDITOR,
        "    ...currentFlags(existing?.flags ?? {}),",
        "    ...(existing?.flags ?? {}),",
    ),
    ("the builder writes true", BUILD, 'flags.flashAttention = "on";', "flags.flashAttention = true;"),
    (
        "an old build reads as edited",
        BUILD,
        "same(currentFlag(key, profile.flags?.[key]), currentFlag(key, value))",
        "same(profile.flags?.[key], value)",
    ),
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
