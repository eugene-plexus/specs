"""Sabotage for agent#6: Flash attention is on, off, or the engine's own
choice, and a runtime saved as a checkbox keeps doing what it did. The
checkbox is converted once, when `agent.yaml` is loaded (`conversions.py`,
2026-10-13), and nothing else reads one; `conversions-b-sabotage.py` holds
the rest of that converter's sabotages.

Each sabotage edits the agent's source, runs the engine, benchmark, builder
and conversion tests, and restores the file from a byte copy taken first. A
baseline run that must pass opens it. A timeout counts as caught.

    python scripts/agent6-sabotage.py [--agent ../agent]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

LLAMA = "src/eugene_plexus_agent/engines/llama_cpp.py"
BENCH = "src/eugene_plexus_agent/benchmarks.py"
BUILDS = "src/eugene_plexus_agent/profile_builds.py"
CONVERSIONS = "src/eugene_plexus_agent/conversions.py"
TESTS = [
    "tests/test_engines.py",
    "tests/test_benchmarks.py",
    "tests/test_profile_builds.py",
    "tests/test_conversions.py",
]

SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "a converted False becomes off (the over-correction)",
        CONVERSIONS,
        '        del flags["flashAttention"]\n        return True',
        '        flags["flashAttention"] = "off"\n        return True',
    ),
    (
        "a converted True is no longer on",
        CONVERSIONS,
        '        flags["flashAttention"] = "on"\n        return True',
        "        return True",
    ),
    (
        "a checkbox that reaches a launch is read as a setting",
        LLAMA,
        "    if choice is not None and choice not in FLASH_ATTENTION_CHOICES:",
        "    if False:",
    ),
    (
        "off is never sent",
        LLAMA,
        '    return ["--flash-attn", choice] if choice else []',
        '    return ["--flash-attn", choice] if choice == "on" else []',
    ),
    (
        "a quantised cache no longer forces it on",
        LLAMA,
        "    if quantised:\n        if choice == \"off\":",
        "    if False:\n        if choice == \"off\":",
    ),
    (
        "an overridden off is ignored silently",
        LLAMA,
        '            log.warning(\n                "flash attention is set off',
        '            log.debug(\n                "flash attention is set off',
    ),
    (
        "the setting is a checkbox again",
        LLAMA,
        "        valueType=ConfigValueType.enum,\n        enumValues=[\"on\", \"off\"],",
        "        valueType=ConfigValueType.enum,\n        default=False,\n        enumValues=[\"on\", \"off\"],",
    ),
    (
        "the benchmark reads the setting as a boolean",
        BENCH,
        "    flash = flash_attention_argv(flags)",
        "    flash = [\"--flash-attn\", \"on\"] if flags.get(\"flashAttention\") else []",
    ),
    (
        "a build's f16 trial ignores the profile",
        BUILDS,
        "    return args + flash_attention_argv(",
        "    return args + ([\"--flash-attn\", \"on\"] if flash_attention else []) or flash_attention_argv(",
    ),
]


def run(agent: Path) -> bool:
    python = agent / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = agent / ".venv" / "bin" / "python"
    try:
        done = subprocess.run(
            [str(python), "-m", "pytest", "-q", "-x", *TESTS],
            cwd=agent,
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
    parser.add_argument("--agent", type=Path, default=Path(__file__).resolve().parents[2] / "agent")
    agent = parser.parse_args().agent.resolve()
    if not run(agent):
        print("BASELINE FAILED: the tests do not pass unsabotaged")
        return 2
    print("baseline passes")
    caught = 0
    for name, rel, old, new in SABOTAGES:
        path = agent / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if "\r\n" in text:  # a Windows checkout
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} matches): {name}")
            return 2
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            passed = run(agent)
        finally:
            path.write_bytes(original)
        caught += not passed
        print(f"{'CAUGHT ' if not passed else 'ESCAPED'} {name}")
    print(f"{caught}/{len(SABOTAGES)} caught")
    return 0 if caught == len(SABOTAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
