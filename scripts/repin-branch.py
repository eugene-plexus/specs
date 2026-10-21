#!/usr/bin/env python3
"""Re-pin a row's consumer branches after its specs branch is rebased (W0.14).

    python scripts/repin-branch.py <branch>             # rebase, re-pin, commit; push nothing
    python scripts/repin-branch.py <branch> --push      # and push specs and the consumers
    python scripts/repin-branch.py <branch> --dry-run   # say what would happen; change nothing

A row that changes a contract has commits on a specs branch, and the same-named
branch of each consumer repo pins one of them in `SPECS_REF`. When specs `main`
moves, the specs branch is rebased onto it and its commits get new SHAs. This
script does the whole hop, for the worktrees of <branch> under the worktree
root (`scripts/worktree.py`):

1. It stops, changing nothing, if any of those worktrees has an uncommitted
   change to a tracked file.
2. In specs it fetches and rebases <branch> onto `origin/main`. On a conflict
   it aborts the rebase and names the files. If the rebase dropped or changed
   a commit, it puts the branch back where it was and says so. It never leaves
   a rebase half done.
3. Each consumer whose `SPECS_REF` names a commit of the old branch gets the
   rebased commit's SHA in `SPECS_REF` and in the generated code that records
   the pin (`src/*/_generated/__init__.py`, or `src/generated/index.ts` in ui).
   Only the SHA changes. The commit is `Re-pin specs <sha> after rebasing
   <branch>`; the repo's pre-commit hooks run, including its SPECS_REF check.
4. With `--push`, specs is pushed first (`--force-with-lease`), then each
   re-pinned consumer.

It only re-pins. A consumer that uses a contract that changed on `main` needs
its code regenerated; the script lists the contract files that changed between
the branch's old base and `origin/main`.

Standard library only; the helpers are `scripts/worktree.py`'s.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

import worktree
from worktree import WorktreeError, git

FULL_SHA = re.compile(r"[0-9a-f]{40}")
STAMP = re.compile(rb'SPECS_REF\s*=\s*"([^"]*)"')
STAMP_GLOBS = ("src/*/_generated/__init__.py", "src/generated/index.ts")
# The folders of specs that the consumers' codegen reads.
CONTRACT_PATHS = ("openapi", "protocols")


class RepinError(WorktreeError):
    """A step failed in a way the person can act on; the message says which."""


def short(sha: str) -> str:
    return sha[:7]


def say(message: str) -> None:
    print(message, flush=True)


# --- git ---------------------------------------------------------------------


def commit_list(repo: Path, revisions: str) -> list[tuple[str, str]]:
    """(sha, subject) of each commit in the range, oldest first."""
    out = git(repo, "log", "--reverse", "--topo-order", "--format=%H%x09%s", revisions)
    commits = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\t")
        commits.append((sha, subject))
    return commits


def tracked_changes(path: Path) -> list[str]:
    return git(path, "status", "--porcelain", "--untracked-files=no").splitlines()


def rebase_in_progress(path: Path) -> bool:
    for name in ("rebase-merge", "rebase-apply"):
        folder = git(path, "rev-parse", "--git-path", name).strip()
        if (path / folder).exists():
            return True
    return False


def rebase(path: Path, onto: str) -> list[str]:
    """Rebase what is checked out at `path` onto `onto`.

    Returns [] when it applied. On a conflict it aborts, so the worktree is as
    it was, and returns the conflicting files. Any other failure raises.
    """
    done = subprocess.run(
        ["git", "-C", str(path), "rebase", onto],
        env=worktree.clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if done.returncode == 0:
        return []
    detail = (done.stderr.strip() or done.stdout.strip())[-1500:]
    conflicts = git(path, "diff", "--name-only", "--diff-filter=U").split()
    if rebase_in_progress(path):
        try:
            git(path, "rebase", "--abort")
        except WorktreeError as error:
            raise RepinError(
                f"the rebase stopped and `git rebase --abort` failed in {path.as_posix()}: "
                f"{error}; run it by hand before anything else"
            ) from error
    if not conflicts:
        raise RepinError(f"git rebase {onto} failed in {path.as_posix()}: {detail}")
    return conflicts


@contextlib.contextmanager
def trial_worktree(specs: Path, head: str) -> Iterator[Path]:
    """A throwaway detached worktree of specs, for a rebase that changes nothing real."""
    folder = Path(tempfile.mkdtemp(prefix="ep-repin-"))
    path = folder / "specs"
    try:
        git(specs, "worktree", "add", "--detach", str(path), head)
        yield path
    finally:
        try:
            git(specs, "worktree", "remove", "--force", str(path))
        except WorktreeError:
            pass
        shutil.rmtree(folder, ignore_errors=True)
        try:
            git(specs, "worktree", "prune")
        except WorktreeError:
            pass


# --- the plan ----------------------------------------------------------------


@dataclasses.dataclass
class Consumer:
    repo: str
    path: Path
    pin: str
    stamps: list[Path]
    index: int | None = None  # which commit of the branch the pin names
    note: str = ""  # why the pin is left alone, or how it was found
    new: str = ""
    commit: str = ""
    pushed: bool = False
    error: str = ""


def find_stamps(path: Path) -> list[Path]:
    return [match for pattern in STAMP_GLOBS for match in sorted(path.glob(pattern))]


def locate(
    specs: Path, pin: str, old: list[tuple[str, str]], main: str, branch: str
) -> tuple[int | None, str]:
    """Which commit of the old branch `pin` names: its index, or why it names none."""
    if not FULL_SHA.fullmatch(pin):
        return None, f"SPECS_REF {pin!r} is not a full commit SHA"
    shas = [sha for sha, _ in old]
    if pin in shas:
        return shas.index(pin), ""
    if not worktree.ref_exists(specs, f"{pin}^{{commit}}"):
        return None, f"pin {short(pin)} is not a commit this specs checkout has"
    if worktree.succeeds(["git", "-C", specs, "merge-base", "--is-ancestor", pin, main]):
        return None, f"pin {short(pin)} is a commit of main, not of {branch}"
    # Not a commit of the branch as it is now: an earlier rebase of it, if one
    # commit of the branch has the same subject.
    subject = git(specs, "log", "-1", "--format=%s", pin).strip()
    matches = [i for i, (_, found) in enumerate(old) if found == subject]
    if len(matches) == 1:
        return matches[0], f"pin {short(pin)} was an earlier version of the branch"
    which = "no commit" if not matches else "several commits"
    return None, f"pin {short(pin)} is not on {branch} ({which} of it has its subject)"


@dataclasses.dataclass
class Plan:
    branch: str
    specs: Path
    old_head: str
    old_base: str
    main: str
    old: list[tuple[str, str]]
    consumers: list[Consumer]

    @property
    def rebase_needed(self) -> bool:
        return self.old_base != self.main

    def will_change(self, consumer: Consumer) -> bool:
        if consumer.index is None:
            return False
        return self.rebase_needed or consumer.pin != self.old[consumer.index][0]


def make_plan(args: argparse.Namespace) -> Plan:
    worktree.check_branch(args.branch)
    repos_root = args.repos_root or worktree.default_repos_root()
    found = worktree.branch_worktrees(repos_root, args.root, args.branch)
    specs = None
    pinned: list[tuple[str, Path]] = []
    for repo, tree in found:
        if not tree.path.exists():
            worktree.log(f"{repo.name}: {tree.path.as_posix()} is gone (run `git worktree prune`)")
            continue
        if repo.name == "specs":
            specs = tree.path
        elif (tree.path / "SPECS_REF").is_file():
            pinned.append((repo.name, tree.path))
    if specs is None:
        raise RepinError(
            f"no specs worktree of {args.branch} under {args.root.as_posix()}; "
            f"`python scripts/worktree.py add {args.branch} specs` makes one"
        )
    dirty = [
        f"{name}: {path.as_posix()}"
        for name, path in [("specs", specs), *pinned]
        if tracked_changes(path)
    ]
    if dirty:
        raise RepinError(
            "uncommitted changes to tracked files; commit or discard them first:\n  "
            + "\n  ".join(dirty)
        )
    git(specs, "fetch", "--quiet", "origin")
    if not worktree.ref_exists(specs, "refs/remotes/origin/main"):
        raise RepinError("specs has no origin/main")
    main = git(specs, "rev-parse", "origin/main").strip()
    old_head = git(specs, "rev-parse", "HEAD").strip()
    old_base = git(specs, "merge-base", old_head, main).strip()
    if int(git(specs, "rev-list", "--merges", "--count", f"{old_base}..{old_head}")):
        raise RepinError(
            f"{args.branch} has merge commits in specs; a rebase would flatten them. "
            "Rebase it by hand."
        )
    old = commit_list(specs, f"{old_base}..{old_head}")
    plan = Plan(args.branch, specs, old_head, old_base, main, old, [])
    for name, path in pinned:
        pin = (path / "SPECS_REF").read_text(encoding="utf-8-sig").strip()
        consumer = Consumer(name, path, pin, find_stamps(path))
        consumer.index, consumer.note = locate(specs, pin, old, main, args.branch)
        if plan.will_change(consumer):
            check_stamps(consumer)
        plan.consumers.append(consumer)
    if args.push:
        unseen = remote_only_commits(plan)
        if unseen:
            raise RepinError(
                f"origin/{args.branch} in specs has commits this worktree lacks "
                f"({'; '.join(unseen)}); a force-push would delete them. "
                "Pull or rebase them in first."
            )
    return plan


def check_stamps(consumer: Consumer) -> None:
    """The generated stamps must record the pin now, or the re-pin cannot be exact."""
    for stamp in consumer.stamps:
        recorded = STAMP.search(stamp.read_bytes())
        found = recorded.group(1).decode("utf-8", "replace") if recorded else "(none)"
        if found != consumer.pin:
            where = stamp.relative_to(consumer.path).as_posix()
            raise RepinError(
                f"{consumer.repo}: {where} records {found} but SPECS_REF is {consumer.pin}; "
                "run the repo's codegen first"
            )


def remote_only_commits(plan: Plan) -> list[str]:
    remote = f"refs/remotes/origin/{plan.branch}"
    if not worktree.ref_exists(plan.specs, remote):
        return []
    have = {subject for _, subject in plan.old}
    return [
        subject
        for _, subject in commit_list(plan.specs, f"{plan.main}..{remote}")
        if subject not in have
    ]


# --- the rebase --------------------------------------------------------------


def check_rebased(plan: Plan, path: Path) -> list[tuple[str, str]]:
    """The branch's commits after the rebase, once they match the old ones one for one."""
    new = commit_list(path, f"{plan.main}..HEAD")
    if [subject for _, subject in new] == [subject for _, subject in plan.old]:
        return new
    kept = {subject for _, subject in new}
    dropped = [subject for _, subject in plan.old if subject not in kept]
    detail = f"; dropped: {', '.join(dropped)}" if dropped else ""
    raise RepinError(
        f"the rebase changed the branch's commits: {len(plan.old)} before, {len(new)} after"
        f"{detail}. A commit already on main is the usual cause."
    )


def conflict_error(plan: Plan, conflicts: list[str]) -> RepinError:
    return RepinError(
        f"rebasing {plan.branch} onto origin/main {short(plan.main)} conflicts in:\n  "
        + "\n  ".join(conflicts)
        + "\nThe rebase was aborted; nothing changed. Rebase by hand, resolve, then run this again."
    )


def rebase_specs(plan: Plan) -> list[tuple[str, str]]:
    """Rebase the specs worktree; on a bad result put the branch back."""
    conflicts = rebase(plan.specs, plan.main)
    if conflicts:
        raise conflict_error(plan, conflicts)
    try:
        return check_rebased(plan, plan.specs)
    except RepinError as error:
        git(plan.specs, "reset", "--hard", plan.old_head)
        raise RepinError(f"{error} The branch is back at {short(plan.old_head)}.") from error


def trial_rebase(plan: Plan) -> None:
    """Dry run: the same rebase in a throwaway worktree, to find a conflict or a dropped commit."""
    with trial_worktree(plan.specs, plan.old_head) as path:
        conflicts = rebase(path, plan.main)
        if conflicts:
            raise conflict_error(plan, conflicts)
        check_rebased(plan, path)


# --- the re-pin --------------------------------------------------------------


def write_pin(consumer: Consumer, new: str) -> list[str]:
    """Write the new SHA to SPECS_REF and into the stamps; return the files written."""
    written = ["SPECS_REF"]
    (consumer.path / "SPECS_REF").write_bytes((new + "\n").encode("ascii"))
    for stamp in consumer.stamps:
        data = stamp.read_bytes()
        stamp.write_bytes(data.replace(consumer.pin.encode("ascii"), new.encode("ascii")))
        written.append(stamp.relative_to(consumer.path).as_posix())
    return written


def commit_pin(consumer: Consumer, branch: str, co_author: str | None) -> str:
    new = consumer.new
    written = write_pin(consumer, new)
    message = f"Re-pin specs {short(new)} after rebasing {branch}\n\n"
    if co_author:
        message += f"Co-Authored-By: {co_author}\n"
    with tempfile.NamedTemporaryFile(
        "w", delete=False, encoding="utf-8", newline="\n", suffix=".txt"
    ) as handle:
        handle.write(message)
    try:
        git(consumer.path, "add", "--", *written)
        git(consumer.path, "commit", "-s", "-q", "-F", handle.name, "--", *written)
    except WorktreeError:
        # The tree was clean before; put back what this run wrote.
        git(consumer.path, "restore", "--source=HEAD", "--staged", "--worktree", "--", *written)
        raise
    finally:
        os.unlink(handle.name)
    return git(consumer.path, "rev-parse", "HEAD").strip()


def push_specs(plan: Plan) -> str:
    remote = f"refs/remotes/origin/{plan.branch}"
    target = f"HEAD:refs/heads/{plan.branch}"
    if worktree.ref_exists(plan.specs, remote):
        expected = git(plan.specs, "rev-parse", remote).strip()
        if expected == git(plan.specs, "rev-parse", "HEAD").strip():
            return "already on origin"
        git(
            plan.specs,
            "push",
            "--quiet",
            f"--force-with-lease={plan.branch}:{expected}",
            "origin",
            target,
        )
    else:
        git(plan.specs, "push", "--quiet", "origin", target)
    return "pushed"


# --- reporting ---------------------------------------------------------------


def contract_note(plan: Plan) -> list[str]:
    stat = git(
        plan.specs, "diff", "--stat=200", plan.old_base, plan.main, "--", *CONTRACT_PATHS
    ).strip()
    span = f"{short(plan.old_base)}..{short(plan.main)}"
    if not stat:
        return [
            f"No {'/'.join(CONTRACT_PATHS)} change on main since the branch's old base ({span}): "
            "no regeneration is needed."
        ]
    return [
        f"Contracts that changed on main since the branch's old base ({span}):",
        *[f"  {line}" for line in stat.splitlines()],
        "This script only re-pins. A consumer that uses one of these contracts needs a",
        "regeneration (python scripts/codegen.py from its own .venv), then a commit.",
    ]


def render(name: str, old: str, new: str, state: str) -> str:
    return f"{name:<18} {short(old)} -> {new:<10} {state}"


def run(args: argparse.Namespace) -> int:
    plan = make_plan(args)
    count = len(plan.old)
    say(
        f"specs {plan.branch}: {count} commit(s), based on {short(plan.old_base)}; "
        f"origin/main is {short(plan.main)}"
    )
    for line in contract_note(plan):
        say(line)

    if args.dry_run:
        trial_rebase(plan)
        say("Dry run: nothing changed. A trial rebase in a throwaway worktree applied cleanly.")
        if plan.rebase_needed:
            lines = [render("specs", plan.old_head, "(rebased)", "would force-push with --push")]
        else:
            lines = [
                f"{'specs':<18} {short(plan.old_head)}  unchanged: already based on origin/main"
            ]
        for one in plan.consumers:
            if one.index is None:
                lines.append(f"{one.repo:<18} {short(one.pin)}  unchanged: {one.note}")
                continue
            there = f"commit {one.index + 1} of {count}"
            what = "would re-pin" if plan.will_change(one) else "pin is current"
            lines.append(render(one.repo, one.pin, f"({there})", f"{what}; would push with --push"))
        for line in lines:
            say(line)
        return 0

    worktree.log(f"rebasing {plan.branch} onto origin/main {short(plan.main)}")
    new = rebase_specs(plan)
    new_head = git(plan.specs, "rev-parse", "HEAD").strip()
    for one in plan.consumers:
        if one.index is not None:
            one.new = new[one.index][0]

    failed = False
    for one in plan.consumers:
        if plan.will_change(one):
            try:
                one.commit = commit_pin(one, plan.branch, args.co_author)
            except WorktreeError as error:
                one.error = str(error)
                failed = True

    published = False
    specs_state = (
        "unchanged" if new_head == plan.old_head else "not pushed (--push force-pushes it)"
    )
    if args.push:
        try:
            specs_state = push_specs(plan)
            published = True
        except WorktreeError as error:
            specs_state = f"NOT PUSHED: {error}"
            failed = True
    for one in plan.consumers:
        if one.commit and published:
            try:
                git(one.path, "push", "--quiet", "origin", f"refs/heads/{plan.branch}")
                one.pushed = True
            except WorktreeError as error:
                one.error = f"committed {short(one.commit)}, NOT PUSHED: {error}"
                failed = True

    say(render("specs", plan.old_head, short(new_head), specs_state))
    for one in plan.consumers:
        if one.error:
            say(f"{one.repo:<18} {short(one.pin)} -> {short(one.new)}  FAILED: {one.error}")
        elif one.commit:
            if one.pushed:
                state = f"committed {short(one.commit)}, pushed"
            elif args.push:
                state = f"committed {short(one.commit)}, not pushed (specs was not pushed)"
            else:
                state = f"committed {short(one.commit)}, not pushed (--push pushes it)"
            say(render(one.repo, one.pin, short(one.new), state))
        elif one.index is None:
            say(f"{one.repo:<18} {short(one.pin)}  unchanged: {one.note}")
        else:
            say(f"{one.repo:<18} {short(one.pin)}  unchanged: pin is current")
    return 1 if failed else 0


# --- command line ------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        prog="repin-branch.py",
    )
    parser.add_argument("branch", help="the row's branch, the same name in specs and each consumer")
    parser.add_argument(
        "--push",
        action="store_true",
        help="push specs (force-with-lease) and then each re-pinned consumer",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan; change nothing (it does fetch)"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=worktree.DEFAULT_ROOT,
        help=f"worktree root (default {worktree.DEFAULT_ROOT.as_posix()})",
    )
    parser.add_argument(
        "--repos-root",
        type=Path,
        help="folder holding the repo checkouts (default: the siblings of the main specs checkout)",
    )
    parser.add_argument(
        "--co-author",
        default=os.environ.get("EP_SHIP_CO_AUTHOR"),
        help='e.g. "Claude Opus 5.5 <noreply@anthropic.com>" (or set EP_SHIP_CO_AUTHOR)',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except WorktreeError as error:
        print(f"repin-branch.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
