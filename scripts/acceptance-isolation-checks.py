"""Every agent a script starts from its own config never checks GitHub for updates (specs#19).

An agent runs Eugene's update check 60 s after it boots: up to about 16
unauthenticated calls to api.github.com, out of the 60 an hour a machine
gets. Acceptance runs on a developer's machine used that up on 2026-10-08,
and the machine's own install could not update. So every `agent.yaml` a
script writes (a dict literal with `firstRunComplete`) must carry
`"updateChecks": False`.

Run from anywhere; reads `scripts/*.py` beside this file. `--sabotage` drops
the key from one script in memory and expects the check to fail.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

#: Scripts whose subject is the update check or its setting, or that are
#: tools for a real install rather than tests.
EXEMPT = frozenset(
    {
        "recovery.py",
        "settings-sabotage.py",
        "updates-sabotage.py",
        "uninstall_inventory.py",
        "test_uninstall.py",
        "windows-service-smoke.py",
        Path(__file__).name,
    }
)


def agent_configs(name: str, source: str) -> list[tuple[int, bool]]:
    """(line, update checks off) for each agent config dict in `source`."""
    found = []
    for node in ast.walk(ast.parse(source, filename=name)):
        if not isinstance(node, ast.Dict):
            continue
        keys = {
            k.value: v
            for k, v in zip(node.keys, node.values, strict=True)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        if "firstRunComplete" in keys:
            value = keys.get("updateChecks")
            found.append(
                (node.lineno, isinstance(value, ast.Constant) and value.value is False)
            )
    return found


def check(sources: dict[str, str]) -> tuple[int, list[str]]:
    """How many agent configs there are, and each one that checks GitHub."""
    total, found = 0, []
    for name, source in sorted(sources.items()):
        if name in EXEMPT:
            continue
        for line, off in agent_configs(name, source):
            total += 1
            if not off:
                found.append(
                    f'{name}:{line}: an agent config without "updateChecks": False'
                )
    return total, found


def main() -> int:
    sources = {p.name: p.read_text(encoding="utf-8") for p in SCRIPTS.glob("*.py")}
    configs, found = check(sources)
    if found:
        print("\n".join(found))
        print(
            f"FAIL: {len(found)} agent config(s) would check GitHub for updates (specs#19)"
        )
        return 1
    if not configs:
        print("FAIL: no agent config found at all, so this check checks nothing")
        return 1
    if "--sabotage" in sys.argv:
        target = "standby-acceptance.py"
        broken = dict(sources)
        broken[target] = broken[target].replace('"updateChecks": False,', "", 1)
        assert broken[target] != sources[target], (
            f"{target} carries no updateChecks to drop"
        )
        if not check(broken)[1]:
            print(f"FAIL: dropping updateChecks from {target} went unnoticed")
            return 1
        print("PASS: a config without updateChecks is caught")
    print(
        f"PASS: {configs} agent configs in {len(sources)} scripts never check GitHub for updates"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
