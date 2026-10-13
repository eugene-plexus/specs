"""Sabotage for agent#6's console half: the builder writes "on", and the console
carries a profile's Flash attention as the Library holds it.

A profile saved as a checkbox is converted once, by the Library, in the profile
and in the record of its build (and the agent converts its own settings), so the
console reads no old checkbox: `legacyFlags.ts` is gone. What is checked now is
that the editor saves what it was given, and that a build is called edited only
when a flag differs from what was recorded, exactly.

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

BUILD = "src/lib/profileBuild.ts"
EDITOR = "src/components/ProfileEditor.tsx"
TESTS = [
    "src/lib/profileBuild.test.ts",
    "src/components/ProfileEditor.test.tsx",
]

# What the console used to do to an old checkbox, written out, so that putting it
# back is caught: true was On, false was dropped.
READS_A_CHECKBOX = (
    "    ...Object.fromEntries(\n"
    "      Object.entries(existing?.flags ?? {}).flatMap(([k, v]) =>\n"
    '        k === "flashAttention" && v === true\n'
    '          ? [[k, "on"]]\n'
    '          : k === "flashAttention" && v === false\n'
    "            ? []\n"
    "            : [[k, v]],\n"
    "      ),\n"
    "    ),"
)

SABOTAGES: list[tuple[str, str, str, str]] = [
    ("the builder writes true", BUILD, 'flags.flashAttention = "on";', "flags.flashAttention = true;"),
    (
        "the editor reads an old checkbox again",
        EDITOR,
        "    ...(existing?.flags ?? {}),",
        READS_A_CHECKBOX,
    ),
    (
        "the editor drops Flash attention",
        EDITOR,
        "    ...(existing?.flags ?? {}),",
        "    ...Object.fromEntries(\n"
        '      Object.entries(existing?.flags ?? {}).filter(([k]) => k !== "flashAttention"),\n'
        "    ),",
    ),
    (
        "the editor adds Flash attention to a profile that has none",
        EDITOR,
        "    ...(existing?.flags ?? {}),",
        '    flashAttention: "on",\n    ...(existing?.flags ?? {}),',
    ),
    (
        "the build comparison reads an old checkbox again",
        BUILD,
        '    states[key] = same(profile.flags?.[key], value) ? "built" : "edited";',
        '    states[key] = same(profile.flags?.[key] === true ? "on" : profile.flags?.[key], value)\n'
        '      ? "built"\n'
        '      : "edited";',
    ),
    (
        "every flag of a build is called as built",
        BUILD,
        '    states[key] = same(profile.flags?.[key], value) ? "built" : "edited";',
        '    states[key] = "built";',
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
