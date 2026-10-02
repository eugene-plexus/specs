"""Sabotage for gateway#4: a search's progress says when it finished, and a
failed search's reason ends with one full stop.

Each sabotage edits the gateway's source, runs the tests that should catch
it, and restores the file from a byte copy taken first. A baseline run that
must pass opens it. A timeout counts as caught.

    python scripts/gw4-sabotage.py [--gateway ../gateway]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROUTE = "src/eugene_plexus_gateway/routes/inference.py"
TOOLS = "src/eugene_plexus_gateway/server_tools.py"
TESTS = ["tests/test_server_tools.py"]

SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "only the start is reported, as before",
        ROUTE,
        "                    if generate.reportProgress:\n                        yield frame(",
        '                    if event.search.phase == "started" and generate.reportProgress:\n                        yield frame(',
    ),
    (
        "progress goes to a caller that did not ask",
        ROUTE,
        "                    if generate.reportProgress:\n                        yield frame(",
        "                    if True:\n                        yield frame(",
    ),
    (
        "the finish is reported as a start",
        ROUTE,
        "                                            else StreamPhase.finished",
        "                                            else StreamPhase.started",
    ),
    (
        "the phase is left off",
        ROUTE,
        "                                        phase=(\n",
        "                                        phase=None and (\n",
    ),
    (
        "the reason keeps its own full stop",
        TOOLS,
        '        reason = (execution.error or "no reason was given").rstrip().rstrip(".")',
        '        reason = execution.error or "no reason was given"',
    ),
    (
        "the paragraph break between turns is dropped",
        ROUTE,
        '                    text, paragraph = "\\n\\n" + text, False',
        "                    paragraph = False",
    ),
]


def run(gateway: Path) -> bool:
    python = gateway / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = gateway / ".venv" / "bin" / "python"
    try:
        done = subprocess.run(
            [str(python), "-m", "pytest", "-q", "-x", *TESTS],
            cwd=gateway,
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
    parser.add_argument("--gateway", type=Path, default=Path(__file__).resolve().parents[2] / "gateway")
    gateway = parser.parse_args().gateway.resolve()
    if not run(gateway):
        print("BASELINE FAILED: the tests do not pass unsabotaged")
        return 2
    print("baseline passes")
    caught = 0
    for name, rel, old, new in SABOTAGES:
        path = gateway / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if "\r\n" in text:  # a Windows checkout
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} matches): {name}")
            return 2
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            passed = run(gateway)
        finally:
            path.write_bytes(original)
        caught += not passed
        print(f"{'CAUGHT ' if not passed else 'ESCAPED'} {name}")
    print(f"{caught}/{len(SABOTAGES)} caught")
    return 0 if caught == len(SABOTAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
