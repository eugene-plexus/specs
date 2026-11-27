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
from pathlib import Path

from ci_plan import REF_INPUTS, branch_base, git, plan, remote_branch, resolve_main_refs
from ci_receipt import PendingPlan, find_equivalent, make_receipt

SPECS = Path(__file__).resolve().parent.parent
REPOSITORY = "eugene-plexus/specs"
# Every CI input that names a candidate, and the repository it comes from.
INPUTS = REF_INPUTS


def dispatch(branch: str, *, full: bool) -> tuple[str, dict[str, str], dict]:
    """Resolve the workflow ref, explicit inputs, and expected coverage receipt."""
    main = "+refs/heads/main:refs/remotes/origin/main"
    git(SPECS, "fetch", "--quiet", "--no-tags", "origin", main)
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
    inputs = {"profile": "full" if full else "edge", "base": base}
    inputs.update({f"{name}_ref": commit for name, commit in refs.items()})
    head = specs or git(SPECS, "rev-parse", "origin/main").strip()
    selected = plan(
        SPECS,
        base,
        head,
        full=full,
        candidates=frozenset(REF_INPUTS[name] for name in refs),
    )
    receipt = make_receipt(head, base or head, selected, refs, resolve_main_refs())
    return ref, inputs, receipt


def submit(ref: str, inputs: dict[str, str]) -> str:
    """Return the dispatched run's own URL, without guessing from concurrent runs."""
    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            "-H",
            "X-GitHub-Api-Version: 2026-03-10",
            f"repos/{REPOSITORY}/actions/workflows/ci.yml/dispatches",
            "--input",
            "-",
        ],
        input=json.dumps({"ref": ref, "inputs": inputs}),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(
            f"Dispatch did not confirm a run: {result.stderr.strip()}. Inspect Actions before retrying."
        )
    response = json.loads(result.stdout or "{}")
    if not response.get("workflow_run_id") or not response.get("html_url"):
        raise RuntimeError(
            "GitHub accepted the dispatch without run details. Inspect Actions before retrying."
        )
    return response["html_url"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("branch")
    parser.add_argument("--full", action="store_true", help="run every check")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the dispatch; run nothing"
    )
    arguments = parser.parse_args()
    if arguments.branch in {"main", "edge"}:
        parser.error("name a work branch; main runs CI on every push")
    ref, inputs, receipt = dispatch(arguments.branch, full=arguments.full)
    if arguments.dry_run:
        print("Would dispatch: " + json.dumps({"ref": ref, "inputs": inputs}, indent=2))
        return 0
    try:
        for attempt in range(13):
            try:
                existing = find_equivalent(receipt, ref)
                break
            except PendingPlan:
                if attempt == 12:
                    raise
                if attempt == 0:
                    print(
                        "Waiting up to 60 seconds for the existing run to record its inputs."
                    )
                time.sleep(5)
        if existing:
            print(
                f"These immutable inputs already have a running or successful CI run: {existing}"
            )
            return 0
        print(submit(ref, inputs))
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
