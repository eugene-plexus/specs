"""Select checks conservatively; missing history and unknown inputs mean full coverage.

A push to a branch other than main (`--branch`) is planned against its
merge-base with origin/main, so a branch that only changes documentation or
pins gets the reduced plan. Its component candidates are the same-named
branches of the component repositories, when they exist; a candidate counts
as a pin change of that component (P1, docs/design/development-plan.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Callable
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
# CI's `<input>_ref` inputs and the repository each names. ui and workbench
# keep their own candidate jobs (inputs.ui_ref, inputs.workbench_ref).
REF_INPUTS = {
    "agent": "agent",
    "control": "control",
    "gateway": "gateway",
    "inference_driver": "inference-driver",
    "library": "library",
    "tool_driver": "tool-driver",
    "site_host": "site-host",
}
OUTPUTS = (*CHECKS, "base", *(f"{name}_ref" for name in REF_INPUTS))
ORGANIZATION = "https://github.com/eugene-plexus"


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


def plan(
    root: Path,
    base: str,
    head: str,
    *,
    full: bool = False,
    candidates: frozenset[str] = frozenset(),
) -> dict[str, bool]:
    """Select checks for base..head; `candidates` are repositories whose candidate
    commits replace their pins in this run, so each counts as a pin change.

    A site-host candidate selects everything: shipping a site host moves the
    installer's PIN_SITE_HOST, which already selects full coverage."""
    selected = dict.fromkeys(CHECKS, False)
    if (
        full
        or "site-host" in candidates
        or not re.fullmatch(r"[a-f0-9]{40}", base)
        or base == "0" * 40
    ):
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
        tested = pins | (candidates & COMPONENTS)
        if tested:
            selected.update(runtime=True, instruments=True, container=True)
            if tested & {"agent", "inference-driver"}:
                selected["launch"] = True
            if "agent" in tested:
                selected["installers"] = True
            if tested & {"agent", "library", "gateway", "inference-driver"}:
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
                # An installer's pin lines are judged against the manifest's
                # own pin changes, never against a candidate from elsewhere.
                if installer_body(previous) != installer_body(current) or not pins:
                    return dict.fromkeys(CHECKS, True)
                selected["instruments"] = True
                continue
            return dict.fromkeys(CHECKS, True)
    except (subprocess.CalledProcessError, KeyError, TypeError, ValueError):
        return dict.fromkeys(CHECKS, True)
    return selected


def branch_base(root: Path, head: str, main: str = "origin/main") -> str:
    """The commit a branch left main at; empty (so full coverage) when unknown."""
    try:
        return git(root, "merge-base", main, head).strip()
    except subprocess.CalledProcessError:
        return ""


def remote_branch(repository: str, branch: str) -> str | None:
    """The head of `branch` in an eugene-plexus repository, or None if it has none.

    A failed lookup raises: a run must not quietly test the pins instead."""
    ref = f"refs/heads/{branch}"
    try:
        listing = subprocess.run(
            ["git", "ls-remote", f"{ORGANIZATION}/{repository}", ref],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=120,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"could not look up branch {branch!r} in {repository}: "
            f"git ls-remote exited {error.returncode}: {(error.stderr or '').strip()}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"could not look up branch {branch!r} in {repository}: no answer in 120 s"
        ) from error
    for line in listing.splitlines():
        commit, _, name = line.partition("\t")
        if name == ref and re.fullmatch(r"[a-f0-9]{40}", commit):
            return commit
    return None


def resolve_refs(
    branch: str,
    given: dict[str, str],
    lookup: Callable[[str, str], str | None] = remote_branch,
) -> dict[str, str]:
    """Each `<input>_ref` for this run: a given input wins; on a branch push, a
    component repository's same-named branch; otherwise none (the pin)."""
    refs = {}
    for name, repository in REF_INPUTS.items():
        if given.get(name):
            refs[name] = given[name]
        elif branch:
            commit = lookup(repository, branch)
            if commit:
                refs[name] = commit
    return refs


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--full", action="store_true")
    parser.add_argument(
        "--branch",
        default="",
        help="a pushed branch other than main: plan from its merge-base with origin/main "
        "and test the component repositories' branches of the same name",
    )
    parser.add_argument(
        "--ref",
        action="append",
        default=[],
        metavar="INPUT=COMMIT",
        help=f"a candidate given for an <input>_ref input; inputs: {', '.join(REF_INPUTS)}",
    )
    return parser


def main() -> None:
    options = parser()
    arguments = options.parse_args()
    root = Path(__file__).resolve().parent.parent
    given = {}
    for item in arguments.ref:
        name, _, commit = item.partition("=")
        if name not in REF_INPUTS:
            options.error(f"unknown ref input {name!r}")
        if commit and not re.fullmatch(r"[A-Za-z0-9._/-]+", commit):
            options.error(f"{name}_ref is not a commit or branch name: {commit!r}")
        given[name] = commit
    base = arguments.base
    if arguments.branch:
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "fetch",
                "--quiet",
                "--no-tags",
                "origin",
                "+refs/heads/main:refs/remotes/origin/main",
            ],
            check=True,
        )
        base = branch_base(root, arguments.head)
    refs = resolve_refs(arguments.branch, given)
    selected = plan(
        root,
        base,
        arguments.head,
        full=arguments.full,
        candidates=frozenset(REF_INPUTS[name] for name in refs),
    )
    print(json.dumps(selected, indent=2))
    print(json.dumps({"base": base, "candidates": refs}, indent=2))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8", newline="\n") as stream:
            for name, enabled in selected.items():
                stream.write(f"{name}={str(enabled).lower()}\n")
            stream.write(f"base={base}\n")
            for name in REF_INPUTS:
                stream.write(f"{name}_ref={refs.get(name, '')}\n")


if __name__ == "__main__":
    main()
