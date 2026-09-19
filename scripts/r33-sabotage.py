"""R3.3 sabotage pass: the self tier, and which shape it belongs to.

Roadmap §4 item 3, review §6.2 #20. Restores from a COPY, never
`git checkout --`, and opens with a baseline.

**The first entry puts the finding itself back** — the unconditional
carve-out that drops the slot's own tier whenever nothing is advertising
that model this instant, which is what made a cloud fallback report
`tier: 1` for an install whose primary was simply down.

**The second puts back the over-correction**, and it is the one that
matters most here, because this defect has already been fixed once in
the wrong direction: keeping every empty self tier renumbers a virtual
alias's own targets, which is how the 2026-09-10 attempt broke five
tests. A fix that only ever answers "keep" is not a fix, it is the same
bug facing the other way, and a check set that cannot tell the two apart
would pass it.

The rest take the discriminator apart: the alias half, the name half,
reading the wrong map (`by_model` is the instant and is empty by
construction in the case under test), and the install-wide iteration.

The gate is `test_slots.py` plus `test_routing.py` and
`test_multi_agent.py`: the first holds the tier rules, and the other two
are what notice if a change to `resolve` is really a change to the
snapshot every node feeds it.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
GATEWAY = "gateway"
ROUTING = "src/eugene_plexus_gateway/routing.py"
FILES = (ROUTING,)

UNIT_TIMEOUT = 600


def run_gate() -> tuple[int, str]:
    try:
        py = ROOT / GATEWAY / ".venv" / "Scripts" / "python.exe"
        done = subprocess.run(
            [
                str(py),
                "-m",
                "pytest",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                "tests/test_slots.py",
                "tests/test_routing.py",
                "tests/test_multi_agent.py",
            ],
            cwd=ROOT / GATEWAY,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=UNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


# (label, file, old, new)
SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "THE FINDING: the self tier is dropped whenever nothing serves it right now",
        ROUTING,
        "            if index == 0 and not backends and not declared:",
        "            if index == 0 and not backends:",
    ),
    (
        "THE OVER-CORRECTION: every empty self tier is kept, renumbering a virtual alias",
        ROUTING,
        "            if index == 0 and not backends and not declared:\n                continue",
        "            if False:\n                continue",
    ),
    (
        "the discriminator always says yes, which is the over-correction by another route",
        ROUTING,
        "        return any(\n            facts.alias == model or facts.name == model",
        "        return any(\n            True or facts.alias == model or facts.name == model",
    ),
    (
        "the discriminator always says no, which is the finding by another route",
        ROUTING,
        "        return any(\n            facts.alias == model or facts.name == model",
        "        return any(\n            False and (facts.alias == model or facts.name == model)",
    ),
    (
        "the alias half goes: every runtime whose operator DID name it loses its self tier",
        ROUTING,
        "            facts.alias == model or facts.name == model",
        "            facts.name == model",
    ),
    (
        "the name half goes: a runtime declared without a modelAlias loses its self tier",
        ROUTING,
        "            facts.alias == model or facts.name == model",
        "            facts.alias == model",
    ),
    (
        "it asks what is advertised NOW instead of what the install declares",
        ROUTING,
        "        return any(\n            facts.alias == model or facts.name == model\n"
        "            for facts in self._snapshot.runtimes.values()\n        )",
        "        return model in self._snapshot.by_model",
    ),
    (
        "it asks only this node, so a primary on another machine reads as a virtual alias",
        ROUTING,
        "            for facts in self._snapshot.runtimes.values()",
        "            for key, facts in self._snapshot.runtimes.items()\n            if key[0] is None",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    backup = Path(tempfile.mkdtemp(prefix="r33-sabotage-"))
    for relative in FILES:
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / GATEWAY / relative, destination)
    print(f"copy in {backup}\n")

    code, out = run_gate()
    print(f"[baseline] {GATEWAY}: {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    print()

    caught = escaped = 0
    for label, relative, old, new in SABOTAGES:
        path = ROOT / GATEWAY / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate()
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")
    code, out = run_gate()
    print(f"[restored] {GATEWAY}: {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
