"""Sabotage for C4's console half: a person's email on the People page, and
an app's licence on the Apps catalogue card.

Each sabotage edits the UI's source, runs the page tests that should catch
it, and restores the file from a byte copy taken first. A baseline run that
must pass opens it. A timeout counts as caught.

    python scripts/c4-ui-sabotage.py [--ui ../ui]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PEOPLE = "src/app/people/page.tsx"
LIB = "src/lib/people.ts"
APPS = "src/app/apps/page.tsx"
TESTS = ["src/app/people", "src/app/apps"]

SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "a new person's email is not sent",
        PEOPLE,
        '        ...(email.trim() ? { email: email.trim() } : {}),\n',
        "",
    ),
    (
        "anything passes as an address",
        LIB,
        '  return /^[^@\\s]+@[^@\\s]+$/.test(trimmed) ? null : "That does not look like an email address.";',
        "  return null;",
    ),
    (
        "removing an email sends an empty string, not null",
        PEOPLE,
        "              onClick={() => void onSave(null).then(() => setEmail(\"\"))}",
        "              onClick={() => void onSave(\"\" as unknown as null).then(() => setEmail(\"\"))}",
    ),
    (
        "a person's email is not shown",
        PEOPLE,
        "            {person.email}\n",
        "\n",
    ),
    (
        "the licence link can reach back to the console",
        APPS,
        '              rel="noopener noreferrer"\n              className="text-[color:var(--accent-left)] underline"\n              data-testid={`apps-license-${manifest.id}`}',
        '              className="text-[color:var(--accent-left)] underline"\n              data-testid={`apps-license-${manifest.id}`}',
    ),
    (
        "the links line shows for an app with neither",
        APPS,
        "      {(manifest.homepage || manifest.licenseUrl) && (",
        "      {true && (",
    ),
    (
        "the licence is not linked",
        APPS,
        "              href={manifest.licenseUrl}",
        "              href={manifest.homepage}",
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
