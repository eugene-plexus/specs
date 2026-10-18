"""Select checks conservatively; missing history and unknown inputs mean full coverage."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

CHECKS = (
    "full",
    "runtime",
    "launch",
    "installers",
    "dev",
    "uninstall",
    "contracts",
    "instruments",
    "macos",
    "container",
)
COMPONENTS = {"agent", "control", "gateway", "library", "inference-driver", "tool-driver", "ui"}


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, encoding="utf-8"
    )


def installer_body(text: str) -> str:
    text = re.sub(
        r"(?m)^(PIN_(?:AGENT|CONTROL|GATEWAY|LIBRARY|DRIVER|TOOL_DRIVER|UI)=)[a-f0-9]{40}",
        r"\1<PIN>",
        text,
    )
    return re.sub(
        r'(?m)^(\s*"(?:agent|control|gateway|library|inference-driver|tool-driver|ui)"\s*=\s*")[a-f0-9]{40}',
        r"\1<PIN>",
        text,
    )


def plan(root: Path, base: str, head: str, *, full: bool = False) -> dict[str, bool]:
    selected = dict.fromkeys(CHECKS, False)
    if full or not re.fullmatch(r"[a-f0-9]{40}", base) or base == "0" * 40:
        return dict.fromkeys(CHECKS, True)
    try:
        changed = git(root, "diff", "--name-only", "--no-renames", base, head).splitlines()
        before = json.loads(git(root, "show", f"{base}:release/manifest.json"))
        after = json.loads(git(root, "show", f"{head}:release/manifest.json"))
        if set(before["components"]) != COMPONENTS or set(after["components"]) != COMPONENTS:
            return dict.fromkeys(CHECKS, True)
        old_settings = {key: value for key, value in before.items() if key != "components"}
        new_settings = {key: value for key, value in after.items() if key != "components"}
        if old_settings != new_settings:
            return dict.fromkeys(CHECKS, True)
        pins = {
            name for name in COMPONENTS if before["components"][name] != after["components"][name]
        }
        if pins:
            selected.update(runtime=True, instruments=True, container=True)
            if pins & {"agent", "inference-driver"}:
                selected["launch"] = True
            if "agent" in pins:
                selected["installers"] = True
            if pins & {"agent", "library", "gateway", "inference-driver"}:
                selected["macos"] = True
        for name in changed:
            path = Path(name)
            if (
                path.suffix == ".md" and (name.startswith("docs/") or len(path.parts) == 1)
            ) or name == "LICENSE":
                continue
            if name == "release/manifest.json":
                selected["instruments"] = True
                continue
            if name in {"scripts/install.sh", "scripts/install.ps1"}:
                previous = git(root, "show", f"{base}:{name}")
                current = git(root, "show", f"{head}:{name}")
                if installer_body(previous) != installer_body(current) or not pins:
                    return dict.fromkeys(CHECKS, True)
                selected["instruments"] = True
                continue
            return dict.fromkeys(CHECKS, True)
    except (subprocess.CalledProcessError, KeyError, TypeError, ValueError):
        return dict.fromkeys(CHECKS, True)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--full", action="store_true")
    arguments = parser.parse_args()
    selected = plan(
        Path(__file__).resolve().parent.parent, arguments.base, arguments.head, full=arguments.full
    )
    print(json.dumps(selected, indent=2))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8", newline="\n") as stream:
            for name, enabled in selected.items():
                stream.write(f"{name}={str(enabled).lower()}\n")


if __name__ == "__main__":
    main()
