"""Run specs CI for a branch, at that branch in every repository that has it (W0.2).

    python scripts/branch-ci.py r12-row-name            # dispatch; print the run's URL
    python scripts/branch-ci.py r12-row-name --full     # every check, whatever changed
    python scripts/branch-ci.py r12-row-name --dry-run  # say what it would dispatch

Each component repository with a branch of that name is tested at the
branch's head through CI's `<repo>_ref` inputs (ui and workbench through their
candidate jobs). The planner's base is the specs branch's merge-base with
main, or main's head when specs has no such branch, so a row whose specs
change is documentation or nothing runs the reduced plan plus its
components' pin checks. A push to a specs branch starts the same run by
itself; dispatch this after the component branches move, or when specs has
no branch for the row.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ci_plan import REF_INPUTS, branch_base, git, remote_branch

SPECS = Path(__file__).resolve().parent.parent
REPOSITORY = "eugene-plexus/specs"
# Every CI input that names a candidate, and the repository it comes from.
INPUTS = {**REF_INPUTS, "ui": "ui", "workbench": "workbench"}


def dispatch(branch: str, *, full: bool) -> tuple[str, list[str]]:
    """The ref CI runs at and the `gh workflow run` command for this branch."""
    git(SPECS, "fetch", "--quiet", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
    specs = remote_branch("specs", branch)
    if specs:
        git(
            SPECS,
            "fetch",
            "--quiet",
            "--no-tags",
            "origin",
            f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
        )
        ref, base = branch, branch_base(SPECS, specs)
    else:
        ref, base = "main", git(SPECS, "rev-parse", "origin/main").strip()
    refs = {}
    for name, repository in INPUTS.items():
        commit = remote_branch(repository, branch)
        if commit:
            refs[name] = commit
            print(f"  {repository}: {branch} at {commit[:7]}")
    if not specs and not refs:
        raise SystemExit(f"No eugene-plexus repository has a branch named {branch!r}.")
    print(
        f"  specs: {'its ' + branch if specs else 'main (no ' + branch + ' branch)'}"
        f", planned from {base[:7] or 'nothing (full)'}"
    )
    command = ["gh", "workflow", "run", "ci.yml", "--repo", REPOSITORY, "--ref", ref]
    command += ["-f", f"profile={'full' if full else 'edge'}", "-f", f"base={base}"]
    for name, commit in refs.items():
        command += ["-f", f"{name}_ref={commit}"]
    return ref, command


def started_run(ref: str, since: datetime) -> str | None:
    """The URL of the CI dispatch on `ref` created after `since`, once GitHub lists it."""
    for _ in range(12):
        listing = subprocess.check_output(
            [
                "gh",
                "run",
                "list",
                "--repo",
                REPOSITORY,
                "--workflow",
                "ci.yml",
                "--branch",
                ref,
                "--event",
                "workflow_dispatch",
                "--limit",
                "10",
                "--json",
                "url,createdAt",
            ],
            text=True,
            encoding="utf-8",
        )
        runs = [
            run
            for run in json.loads(listing or "[]")
            if datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00")) >= since
        ]
        if runs:
            return min(runs, key=lambda run: run["createdAt"])["url"]
        time.sleep(5)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("branch")
    parser.add_argument("--full", action="store_true", help="run every check")
    parser.add_argument("--dry-run", action="store_true", help="print the dispatch; run nothing")
    arguments = parser.parse_args()
    if arguments.branch in {"main", "edge"}:
        parser.error("name a work branch; main runs CI on every push")
    ref, command = dispatch(arguments.branch, full=arguments.full)
    if arguments.dry_run:
        print("Would run: " + " ".join(command))
        return 0
    since = datetime.now(UTC) - timedelta(seconds=10)
    subprocess.run(command, check=True)
    url = started_run(ref, since)
    if url is None:
        print(f"Dispatched; see `gh run list --repo {REPOSITORY} --workflow ci.yml --branch {ref}`.")
        return 0
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
