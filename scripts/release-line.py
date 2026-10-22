"""Open a release line, pick fixes from main onto it, and close it: the first
half of a patch release (docs/design/release-script.md, "Patch releases").

    python scripts/release-line.py open v0.3 [--security] [--rehearsal]
    python scripts/release-line.py pick v0.3 agent:<commit> [gateway:<commit> ...]
    python scripts/release-line.py close v0.3 [--rehearsal] [--delete-branches] [--force]

`open` makes the branch release/vX.Y in specs and in every component, at the
commits the line's newest release pins (ui and Workbench at the source their
dist commit was built from). It pushes each branch that is missing and adds a
worktree of each repository under <lines>/vX.Y/ (by default the folder
eugene-plexus-release beside the checkouts). On the specs line it commits
main's release tooling (release.py, release-line.py, ship.py, and the
qualification and image workflows) where the release's own differs, so a
patch is cut with today's gates. Only the newest line opens; an older line
opens with --security, for a security fix.

`pick` cherry-picks commits that are on main onto the line, with `-x`, and
pushes the line. A commit that is not on main is refused (fix it on main
first); one the line holds already is skipped; a conflict is aborted, and its
files are named.

`close` copies the line's docs/private/release-* (state and logs) into the
specs checkout, removes the worktrees and keeps the branches. On a rehearsal
line, --delete-branches deletes its branches too.

Then, from <lines>/vX.Y/specs: python scripts/release.py vX.Y.(Z+1).

Exit codes: 0 done; 2 a precondition is not met, or a pick conflicts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release  # noqa: E402
import ship  # noqa: E402
from ship import Stop, git  # noqa: E402

LINE_NAME = re.compile(r"v(\d+)\.(\d+)")
#: Main's release tooling: a line is cut with today's gates.
TOOLING = (
    "scripts/release.py",
    "scripts/release-line.py",
    "scripts/ship.py",
    ".github/workflows/release-qualification.yml",
    ".github/workflows/container.yml",
)
say = release.say


def checkouts() -> Path:
    """The folder of the person's checkouts: the parent of the specs checkout,
    also when this runs from a worktree of it."""
    common = git(
        Path(__file__).resolve().parent,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    return Path(common).resolve().parent.parent


class Line:
    def __init__(self, name: str, *, lines: Path | None, rehearsal: bool) -> None:
        match = LINE_NAME.fullmatch(name)
        if not match:
            raise Stop(f"{name}: a release line is named vX.Y")
        self.name = name
        self.key = (int(match[1]), int(match[2]))
        self.rehearsal = rehearsal
        self.branch = f"{'rehearsal' if rehearsal else 'release'}/{name}"
        self.root = checkouts()
        lines = (lines or self.root.parent / "eugene-plexus-release").resolve()
        self.dir = lines / (f"{name}-rehearsal" if rehearsal else name)
        # The push guard: this script moves only the line's own branches.
        release.LINE = {"branch": self.branch, "root": str(self.root)}

    def repo(self, name: str) -> Path:
        return self.root / name

    def worktree(self, name: str) -> Path:
        return self.dir / name


def open_line(line: Line, *, security: bool, co_author: str | None) -> None:
    specs = line.repo("specs")
    git(specs, "fetch", "-q", "--tags", "origin")
    tags = [
        t
        for t in git(specs, "tag", "-l", "v*").splitlines()
        if release.VERSION.fullmatch(t)
    ]
    on_line = sorted(
        (release.version_key(t), t)
        for t in tags
        if release.version_key(t)[:2] == line.key
    )
    if not on_line:
        raise Stop(f"line {line.name} has no release to patch")
    previous = on_line[-1][1]
    newest = max(tags, key=release.version_key)
    if line.key < release.version_key(newest)[:2] and not security:
        raise Stop(
            f"line {line.name} is older than the newest release, {newest}. Only a "
            "security fix patches an older line: rerun with --security"
        )
    for name in release.LINE_REPOS:
        git(line.repo(name), "fetch", "-q", "origin")
    pins = release.tag_pins(specs, line.repo("agent"), previous)
    starts = {"specs": git(specs, "rev-parse", f"{previous}^{{commit}}")}
    starts.update(release.line_sources(line.root, pins))
    line.dir.mkdir(parents=True, exist_ok=True)
    for name, start in starts.items():
        repo = line.repo(name)
        remote = release.ref_or_none(repo, f"refs/remotes/origin/{line.branch}")
        if remote is None:
            release.push(repo, start, f"refs/heads/{line.branch}")
            git(repo, "fetch", "-q", "origin", line.branch)
            say(f"{name}: {line.branch} at {start[:7]}")
        elif not ship.is_ancestor(repo, start, remote):
            raise Stop(
                f"{name}: origin's {line.branch} does not hold {previous}'s commit {start[:7]}"
            )
        add_worktree(repo, line.worktree(name), line.branch)
    bring_tooling(line, co_author)
    (line.dir / "line.json").write_text(
        json.dumps(
            {
                "line": line.name,
                "branch": line.branch,
                "root": str(line.root),
                "opened": previous,
                "rehearsal": line.rehearsal,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Line {line.name} is open at {previous}'s pins: {line.dir}")
    print(
        f"Pick fixes from main: python scripts/release-line.py pick {line.name} <repo>:<commit>"
    )
    print(f"Then, from {line.worktree('specs')}: python scripts/release.py <version>")


def add_worktree(repo: Path, path: Path, branch: str) -> None:
    if path.exists():
        here = git(path, "rev-parse", "--abbrev-ref", "HEAD")
        if here != branch:
            raise Stop(f"{path} is on {here}, not {branch}")
        return
    remote = git(repo, "rev-parse", f"refs/remotes/origin/{branch}")
    local = release.ref_or_none(repo, f"refs/heads/{branch}")
    if local is None:
        git(
            repo,
            "worktree",
            "add",
            "-q",
            "--track",
            "-b",
            branch,
            str(path),
            f"origin/{branch}",
        )
        return
    if not ship.is_ancestor(repo, local, remote):
        raise Stop(
            f"{repo.name}: the local branch {branch} has commits origin lacks; "
            "push or delete it first"
        )
    git(repo, "worktree", "add", "-q", str(path), branch)
    if local != remote:
        git(path, "merge", "-q", "--ff-only", f"origin/{branch}")


def bring_tooling(line: Line, co_author: str | None) -> None:
    """Main's release tooling onto the specs line, as one commit, where it differs."""
    specs = line.worktree("specs")
    if git(specs, "status", "--porcelain", "--untracked-files=no"):
        raise Stop(f"specs: uncommitted changes to tracked files in {specs}")
    git(specs, "fetch", "-q", "origin", "main")
    changed = []
    for name in TOOLING:
        want = release.ref_or_none(specs, f"origin/main:{name}")
        if want is None or want == release.ref_or_none(specs, f"HEAD:{name}"):
            continue
        data = subprocess.run(
            ["git", "cat-file", "blob", want],
            cwd=specs,
            capture_output=True,
            check=True,
        ).stdout
        (specs / name).parent.mkdir(parents=True, exist_ok=True)
        (specs / name).write_bytes(data)
        changed.append(name)
    if not changed:
        return
    main = git(specs, "rev-parse", "origin/main")
    ship.commit_files(
        specs,
        changed,
        f"Release tooling from main {main[:7]}\n\n"
        f"The line is cut with today's release gates: {', '.join(changed)}.",
        co_author,
    )
    release.push(specs, "HEAD", f"refs/heads/{line.branch}")
    say(f"specs: main's release tooling on {line.branch} ({len(changed)} files)")


def pick(line: Line, picks: list[str]) -> None:
    if not (line.dir / "line.json").is_file():
        raise Stop(
            f"line {line.name} is not open here: release-line.py open {line.name}"
        )
    for spec in picks:
        name, _, sha = spec.partition(":")
        if name not in ("specs", *release.LINE_REPOS) or not re.fullmatch(
            r"[0-9a-f]{4,40}", sha
        ):
            raise Stop(
                f"{spec}: name a pick <repo>:<commit>, the repo one of specs, "
                + ", ".join(release.LINE_REPOS)
            )
        worktree = line.worktree(name)
        if not worktree.is_dir():
            raise Stop(
                f"{name}: no worktree at {worktree}; run release-line.py open {line.name}"
            )
        git(worktree, "fetch", "-q", "origin", "main", line.branch)
        full = release.ref_or_none(worktree, f"{sha}^{{commit}}")
        if full is None:
            raise Stop(
                f"{name}: no commit {sha} here or on main. Fix it on main first, then pick it"
            )
        if not ship.is_ancestor(worktree, full, "origin/main"):
            raise Stop(
                f"{name}: {full[:7]} is not on main. Fix it on main first, then pick it"
            )
        if len(git(worktree, "rev-list", "--parents", "-1", full).split()) != 2:
            raise Stop(f"{name}: {full[:7]} is a merge; pick the commits it merged")
        if git(worktree, "status", "--porcelain", "--untracked-files=no"):
            raise Stop(f"{name}: uncommitted changes to tracked files in {worktree}")
        remote = git(worktree, "rev-parse", f"origin/{line.branch}")
        if not ship.is_ancestor(worktree, remote, "HEAD"):
            raise Stop(f"{name}: {worktree} is behind origin/{line.branch}; pull first")
        if ship.is_ancestor(worktree, full, "HEAD"):
            say(f"{name}: {full[:7]} is in the line already: the release has it")
        elif git(
            worktree,
            "log",
            "--format=%H",
            "-F",
            f"--grep=(cherry picked from commit {full})",
            "origin/main..HEAD",
        ):
            say(f"{name}: {full[:7]} is picked already")
        else:
            cherry_pick(worktree, name, full, line.branch)
        if git(worktree, "rev-parse", "HEAD") != remote:
            release.push(worktree, "HEAD", f"refs/heads/{line.branch}")


def cherry_pick(worktree: Path, name: str, full: str, branch: str) -> None:
    done = subprocess.run(
        ["git", "cherry-pick", "-x", full],
        cwd=worktree,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if done.returncode == 0:
        say(f"{name}: picked {full[:7]}")
        return
    conflicts = git(worktree, "diff", "--name-only", "--diff-filter=U").splitlines()
    subprocess.run(["git", "cherry-pick", "--abort"], cwd=worktree, capture_output=True)
    if not conflicts and "empty" in done.stdout + done.stderr:
        say(f"{name}: {full[:7]} changes nothing on the line; skipped")
        return
    raise Stop(
        f"{name}: cherry-pick of {full[:7]} conflicts in "
        f"{', '.join(conflicts) or (done.stdout + done.stderr).strip()[-300:]}; resolve it on "
        f"{branch} in {worktree} (git cherry-pick -x {full[:7]}, fix, git cherry-pick "
        "--continue), then rerun"
    )


def close(line: Line, *, force: bool, delete_branches: bool) -> None:
    if delete_branches and not line.rehearsal:
        raise Stop(
            "--delete-branches is for a rehearsal line; a release line keeps its branches"
        )
    private = line.worktree("specs") / "docs" / "private"
    keep = line.repo("specs") / "docs" / "private"
    for folder in sorted(private.glob("release-*")) if private.is_dir() else []:
        if not (keep / folder.name).exists():
            shutil.copytree(folder, keep / folder.name)
            say(f"kept {keep / folder.name}")
    names = ("specs", *release.LINE_REPOS)
    for name in names:
        worktree = line.worktree(name)
        if worktree.exists() and git(worktree, "status", "--porcelain") and not force:
            raise Stop(
                f"{name}: {worktree} has changes or new files; commit and push them, "
                "or close --force to drop them"
            )
    for name in names:
        worktree = line.worktree(name)
        if worktree.exists():
            git(
                line.repo(name),
                "worktree",
                "remove",
                *(["--force"] if force else []),
                str(worktree),
            )
    if delete_branches:
        scratch = re.compile(
            rf"release-candidate/v{line.key[0]}\.{line.key[1]}\.\d+-rehearsal\.\d+"
        )
        for name in names:
            repo = line.repo(name)
            git(repo, "fetch", "-q", "--prune", "origin")
            refs = [line.branch]
            if name in ("ui", "workbench"):
                refs.append(f"{line.branch}-dist")
            if name == "specs":
                listing = git(
                    repo,
                    "for-each-ref",
                    "--format=%(refname:strip=3)",
                    "refs/remotes/origin/release-candidate/",
                )
                refs += [ref for ref in listing.splitlines() if scratch.fullmatch(ref)]
            for ref in refs:
                if release.ref_or_none(repo, f"refs/remotes/origin/{ref}"):
                    release.push(repo, "", f"refs/heads/{ref}", delete=True)
            if release.ref_or_none(repo, f"refs/heads/{line.branch}"):
                git(repo, "branch", "-q", "-D", line.branch)
        say(f"deleted the {line.branch} branches")
    (line.dir / "line.json").unlink(missing_ok=True)
    if line.dir.is_dir() and not any(line.dir.iterdir()):
        line.dir.rmdir()
    print(
        f"Line {line.name} is closed; its branches {'are deleted' if delete_branches else 'stay'}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("line", help="vX.Y")
    common.add_argument(
        "--lines",
        type=Path,
        help="where line worktrees go (default: eugene-plexus-release beside the checkouts)",
    )
    common.add_argument(
        "--rehearsal", action="store_true", help="the rehearsal/vX.Y line"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    opener = commands.add_parser("open", parents=[common], help="open a release line")
    opener.add_argument(
        "--security", action="store_true", help="open an older line, for a security fix"
    )
    opener.add_argument("--co-author", default=os.environ.get("EP_SHIP_CO_AUTHOR"))
    picker = commands.add_parser(
        "pick", parents=[common], help="pick commits from main"
    )
    picker.add_argument("commits", nargs="+", metavar="REPO:COMMIT")
    closer = commands.add_parser("close", parents=[common], help="remove the worktrees")
    closer.add_argument(
        "--delete-branches", action="store_true", help="a rehearsal line's branches too"
    )
    closer.add_argument(
        "--force", action="store_true", help="drop uncommitted changes in the worktrees"
    )
    args = parser.parse_args()
    for name in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    try:
        line = Line(args.line, lines=args.lines, rehearsal=args.rehearsal)
        if args.command == "open":
            open_line(line, security=args.security, co_author=args.co_author)
        elif args.command == "pick":
            pick(line, args.commits)
        else:
            close(line, force=args.force, delete_branches=args.delete_branches)
    except Stop as stop:
        print(f"NOT DONE: {stop}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
