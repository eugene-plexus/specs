"""Sabotage for specs#11: a recovery checkpoint left out an app's data kept
by systemd outside the prefix on a Linux system install.

Each sabotage edits scripts/recovery.py, runs scripts/a7-recovery-checks.py,
and restores the file from a byte copy taken first. A baseline run that
must pass opens it. A timeout counts as caught.

    python scripts/specs11-sabotage.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / "recovery.py"
CHECKS = HERE / "a7-recovery-checks.py"

SABOTAGES: list[tuple[str, str, str]] = [
    (
        "the checkpoint leaves app data out, as before",
        "    entries = [(f, f.relative_to(root).as_posix()) for f in files] + app_state(root)",
        "    entries = [(f, f.relative_to(root).as_posix()) for f in files]",
    ),
    (
        "unreadable app data is skipped silently",
        "        except PermissionError as exc:\n            raise ValueError(",
        "        except PermissionError as exc:\n            present = False\n            continue\n            raise ValueError(",
    ),
    (
        "activation overwrites data already there",
        "        if target.exists() and any(target.iterdir()):",
        "        if False:",
    ),
    (
        "activation never puts app data back",
        "    for app_id in place_app_state(destination / \"state\"):",
        "    for app_id in []:",
    ),
    (
        "apps.yaml is not read",
        "    for item in raw.get(\"installed\") or []:\n        app_id",
        "    for item in []:\n        app_id",
    ),
]


def run() -> bool:
    try:
        done = subprocess.run(
            [sys.executable, str(CHECKS)],
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
    if not run():
        print("BASELINE FAILED: the checks do not pass unsabotaged")
        return 2
    print("baseline passes")
    caught = 0
    original = TARGET.read_bytes()
    text = original.decode("utf-8")
    for name, old, new in SABOTAGES:
        if "\r\n" in text:
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} matches): {name}")
            return 2
        try:
            TARGET.write_bytes(text.replace(old, new).encode("utf-8"))
            passed = run()
        finally:
            TARGET.write_bytes(original)
        caught += not passed
        print(f"{'CAUGHT ' if not passed else 'ESCAPED'} {name}")
    print(f"{caught}/{len(SABOTAGES)} caught")
    return 0 if caught == len(SABOTAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
