"""Fail direct acceptance/lock conflicts before CI starts its integration matrix."""

from __future__ import annotations

from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def requirements(text: str) -> list[Requirement]:
    return [
        Requirement(line.split("#", 1)[0].strip())
        for line in text.splitlines()
        if line.split("#", 1)[0].strip()
    ]


def conflicts(acceptance: str, constraints: str) -> list[str]:
    locked = requirements(constraints)
    errors = set()
    for requirement in requirements(acceptance):
        matching = [
            r
            for r in locked
            if canonicalize_name(r.name) == canonicalize_name(requirement.name)
        ]
        for constraint in matching:
            for platform, system in (
                ("linux", "Linux"),
                ("win32", "Windows"),
                ("darwin", "Darwin"),
            ):
                env = {
                    **default_environment(),
                    "python_version": "3.12",
                    "python_full_version": "3.12.0",
                    "sys_platform": platform,
                    "platform_system": system,
                    "os_name": "nt" if platform == "win32" else "posix",
                }
                if requirement.marker and not requirement.marker.evaluate(env):
                    continue
                if constraint.marker and not constraint.marker.evaluate(env):
                    continue
                pins = [
                    s.version
                    for s in constraint.specifier
                    if s.operator == "==" and "*" not in s.version
                ]
                if len(pins) != 1:
                    raise ValueError(
                        f"Release constraint must have one exact version: {constraint}"
                    )
                if not requirement.specifier.contains(pins[0], prereleases=True):
                    errors.add(
                        f"{requirement} conflicts with release constraint {constraint} ({platform}, Python 3.12)"
                    )
    return sorted(errors)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors = conflicts(
        (root / "scripts/requirements-acceptance.txt").read_text(encoding="utf-8"),
        (root / "release/constraints.txt").read_text(encoding="utf-8"),
    )
    for error in errors:
        print(error)
    if errors:
        print(
            "Use the release constraint for a shared runtime dependency, or update its requirement and release lock together."
        )
    else:
        print(
            "Acceptance requirements agree with the release constraints on Linux, Windows and macOS."
        )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
