#!/usr/bin/env python3
"""Start and finish a row's worktrees across the Eugene Plexus repos.

    python scripts/worktree.py add <branch> <repo> [<repo> ...] [--base origin/main]
                               [--no-venv] [--npm] [--python PY] [--no-uv] [--jobs N]
    python scripts/worktree.py remove <branch> [--delete-branch] [--force]
    python scripts/worktree.py list

`add` puts a worktree of every named repo at <root>/<branch>/<repo> on a branch
called <branch>, and for every Python repo (one with a pyproject.toml) gives it
its own `.venv` on Python 3.12, with the editable install and the extras that
the repo's own ci.yml installs. It then proves that importing the package from
that venv resolves into the worktree and not into the main checkout. A worktree
that quietly tests the main checkout's code through that checkout's editable
install is the failure this script exists to prevent.

`<branch> <repo> ...` without a subcommand means `add`.

Standard library only. Repos are the sibling checkouts of the specs checkout
this script belongs to; from a specs worktree the siblings are found through
the main checkout (`git rev-parse --git-common-dir`).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

DEFAULT_ROOT = Path("D:/py/ep-wt") if os.name == "nt" else Path.home() / "ep-wt"
DEFAULT_BASE = "origin/main"
WANTED_PYTHON = (3, 12)
SUBCOMMANDS = ("add", "remove", "list")
# A worktree must not see the caller's venv, import path or git plumbing.
STRIPPED_ENV = (
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "PYTHONHOME",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
)
# Resolve the module without running it; -I keeps PYTHONPATH and the current
# directory out of the answer, so the path printed is the venv's own.
PROBE = (
    "import importlib.util, sys\n"
    "print('%d.%d.%d' % sys.version_info[:3])\n"
    "spec = importlib.util.find_spec(sys.argv[1])\n"
    "where = ''\n"
    "if spec is not None:\n"
    "    where = spec.origin if spec.origin not in (None, 'namespace') else ''\n"
    "    if not where and spec.submodule_search_locations:\n"
    "        where = list(spec.submodule_search_locations)[0]\n"
    "print(where)\n"
)
EDITABLE_EXTRAS = re.compile(r"""-e\s+["']?\.\[([^\]\n]*)\]""")


class WorktreeError(Exception):
    """A step failed in a way the person can act on; the message says which."""


# --- running things ---------------------------------------------------------


def clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in STRIPPED_ENV}


def run(command: Sequence[object], *, cwd: Path | None = None, what: str | None = None) -> str:
    arguments = [str(part) for part in command]
    try:
        done = subprocess.run(
            arguments,
            cwd=cwd,
            env=clean_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as error:
        raise WorktreeError(f"{arguments[0]} was not found on this machine") from error
    if done.returncode:
        detail = (done.stderr.strip() or done.stdout.strip())[-1500:]
        label = what or " ".join(arguments)
        raise WorktreeError(f"{label} failed (exit {done.returncode}): {detail}")
    return done.stdout


def succeeds(command: Sequence[object]) -> bool:
    try:
        done = subprocess.run(
            [str(part) for part in command],
            env=clean_env(),
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return done.returncode == 0


def git(repo: Path, *arguments: str) -> str:
    return run(["git", "-C", repo, *arguments], what="git " + " ".join(arguments))


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --- paths and repos --------------------------------------------------------


def normal(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def is_within(path: Path | str, parent: Path | str) -> bool:
    child, base = normal(path), normal(parent)
    return child == base or child.startswith(base + os.sep)


def under(path: Path | str, root: Path | str) -> bool:
    """Strictly below `root`; the root itself does not count."""
    return normal(path) != normal(root) and is_within(path, root)


def default_repos_root(script: Path | None = None) -> Path:
    """The folder holding the repo checkouts, found from any specs checkout.

    A specs worktree lives under the worktree root, not beside the other
    repos, so its siblings are found through the main checkout's git dir.
    """
    checkout = Path(script or __file__).resolve().parents[1]
    try:
        common = git(checkout, "rev-parse", "--git-common-dir").strip()
    except WorktreeError:
        return checkout.parent
    common_dir = (checkout / common).resolve()
    if common_dir.name == ".git":
        return common_dir.parent.parent
    return checkout.parent


def known_repos(repos_root: Path) -> list[Path]:
    """Main checkouts only: a `.git` directory, not a worktree's `.git` file."""
    return sorted(path for path in repos_root.iterdir() if (path / ".git").is_dir())


def main_checkout(repos_root: Path, repo: str) -> Path:
    path = repos_root / repo
    if not (path / ".git").is_dir():
        known = ", ".join(p.name for p in known_repos(repos_root)) or "none"
        raise WorktreeError(f"{path} is not a git checkout (repos here: {known})")
    return path


@dataclasses.dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None  # None when detached
    head: str


def worktrees(repo: Path) -> list[Worktree]:
    found = []
    for block in git(repo, "worktree", "list", "--porcelain").split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.strip().splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value
        if "worktree" not in fields:
            continue
        ref = fields.get("branch", "")
        branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else None
        found.append(Worktree(Path(fields["worktree"]), branch, fields.get("HEAD", "")))
    return found


def check_branch(branch: str) -> None:
    if branch.startswith("-") or not succeeds(["git", "check-ref-format", "--branch", branch]):
        raise WorktreeError(f"{branch!r} is not a usable branch name")


def ref_exists(repo: Path, ref: str) -> bool:
    return succeeds(["git", "-C", repo, "rev-parse", "--verify", "--quiet", ref])


def create_worktree(repo: Path, path: Path, branch: str, base: str) -> str:
    """Make the worktree and say how it came about."""
    for tree in worktrees(repo):
        if normal(tree.path) == normal(path):
            if tree.branch != branch:
                raise WorktreeError(
                    f"{path} is already a worktree, on {tree.branch or 'no branch'}"
                )
            return "exists"
    if path.exists() and any(path.iterdir()):
        raise WorktreeError(f"{path} exists and is not a worktree of {repo.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if ref_exists(repo, f"refs/heads/{branch}"):
        git(repo, "worktree", "add", str(path), branch)
        return "existing local branch"
    if ref_exists(repo, f"refs/remotes/origin/{branch}"):
        git(repo, "worktree", "add", "--track", "-b", branch, str(path), f"origin/{branch}")
        return f"tracking origin/{branch}"
    if not ref_exists(repo, f"{base}^{{commit}}"):
        raise WorktreeError(f"base {base} does not exist in {repo.name}")
    # --no-track: the branch must not silently track origin/main, or a plain
    # `git pull` merges main. `git push -u origin <branch>` sets the upstream.
    git(repo, "worktree", "add", "--no-track", "-b", branch, str(path), base)
    return f"new from {base}"


# --- the Python side --------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Package:
    name: str
    module: str
    location: PurePosixPath  # the package directory, relative to the worktree
    extras: tuple[str, ...]  # optional-dependencies the pyproject defines


def read_package(worktree: Path) -> Package:
    data = tomllib.loads((worktree / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    name = project.get("name")
    if not name:
        raise WorktreeError(f"{worktree / 'pyproject.toml'} has no [project] name")
    wheel = (
        data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    )
    packages = wheel.get("packages") or []
    if packages:
        location = PurePosixPath(packages[0])
    else:
        location = PurePosixPath("src") / name.replace("-", "_").lower()
    extras = tuple(project.get("optional-dependencies", {}))
    return Package(name, location.name, location, extras)


def ci_extras(workflow: str, available: Sequence[str], *, windows: bool) -> list[str]:
    """The extras the repo's CI installs, as the CI of this OS installs them.

    ci.yml says `pip install -e ".[dev]"`; the agent's says `.[dev,service,tray]`
    on Windows only. Where several lines disagree, Windows takes the largest set
    and the rest the smallest one that has `dev`.
    """
    sets: list[tuple[str, ...]] = []
    for found in EDITABLE_EXTRAS.findall(workflow):
        names = [part.strip() for part in found.split(",") if part.strip()]
        sets.append(tuple(name for name in names if name in available))
    if not sets:
        return ["dev"] if "dev" in available else []
    if windows:
        return list(sorted(sets, key=len)[-1])
    with_dev = [one for one in sets if "dev" in one] or sets
    return list(sorted(with_dev, key=len)[0])


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def interpreter(python: str | None) -> list[str]:
    if python:
        return [python] if Path(python).exists() else shlex.split(python)
    if os.name == "nt":
        return ["py", f"-{WANTED_PYTHON[0]}.{WANTED_PYTHON[1]}"]
    return [f"python{WANTED_PYTHON[0]}.{WANTED_PYTHON[1]}"]


def create_venv(venv: Path, python: str | None, uv: str | None) -> None:
    if uv:
        spec = python or f"{WANTED_PYTHON[0]}.{WANTED_PYTHON[1]}"
        run([uv, "venv", "--python", spec, venv], what="uv venv")
    else:
        try:
            run([*interpreter(python), "-m", "venv", venv], what="python -m venv")
        except WorktreeError as error:
            raise WorktreeError(
                f"{error} (Python 3.12 is needed: install it, or pass --python PATH)"
            ) from error


def keep_out_of_git(venv: Path) -> None:
    """Python 3.12's venv, unlike 3.13's, does not keep itself out of git.

    A `.venv` that shows as untracked makes the worktree look dirty and gets
    swept into `git add -A`, and ui's .gitignore does not list it.
    """
    ignore = venv / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8", newline="\n")


def install_editable(worktree: Path, venv: Path, extras: Sequence[str], uv: str | None) -> None:
    target = f".[{','.join(extras)}]" if extras else "."
    python = venv_python(venv)
    if uv:
        run(
            [uv, "pip", "install", "--python", python, "-e", target],
            cwd=worktree,
            what="uv pip install",
        )
    else:
        run(
            [python, "-m", "pip", "install", "--disable-pip-version-check", "-e", target],
            cwd=worktree,
            what=f"pip install -e {target}",
        )


def probe(python: Path, module: str) -> tuple[str, Path | None]:
    lines = run([python, "-I", "-X", "utf8", "-c", PROBE, module], what="import probe").splitlines()
    where = lines[1].strip() if len(lines) > 1 else ""
    return lines[0].strip(), Path(where) if where else None


def check_version(version: str, *, pinned: bool) -> None:
    """A venv on the wrong Python cannot be repaired by installing again."""
    if pinned and tuple(int(part) for part in version.split(".")[:2]) != WANTED_PYTHON:
        raise WorktreeError(
            f"the venv runs Python {version}, CI uses {WANTED_PYTHON[0]}.{WANTED_PYTHON[1]}; "
            "delete .venv and run again, or pass --python"
        )


def check_location(worktree: Path, package: Package, where: Path | None) -> Path:
    """Raise unless importing the package resolves into this worktree."""
    if where is None:
        raise WorktreeError(f"import {package.module} finds nothing in the venv (not installed)")
    expected = worktree / package.location
    if not is_within(where, expected):
        raise WorktreeError(
            f"import {package.module} resolves to {where}, not into {expected}: "
            "this venv would test another checkout's code"
        )
    return where


@dataclasses.dataclass
class Result:
    repo: str
    path: Path
    how: str = ""
    venv: str = ""
    import_line: str = ""
    npm: str = ""
    error: str = ""


def prepare_python(worktree: Path, args: argparse.Namespace, uv: str | None) -> tuple[str, str]:
    """Create or reuse the venv, install, verify. Returns (venv text, import text)."""
    package = read_package(worktree)
    pinned = not args.python
    venv = worktree / ".venv"
    python = venv_python(venv)
    installer = "uv" if uv else "pip"
    if not python.exists():
        log(f"{worktree.name}: creating venv")
        create_venv(venv, args.python, uv)
        keep_out_of_git(venv)
    else:
        # Reuse a venv only when it already passes; a missing or foreign
        # install is repaired by installing again.
        keep_out_of_git(venv)
        version, where = probe(python, package.module)
        check_version(version, pinned=pinned)
        try:
            found = check_location(worktree, package, where)
        except WorktreeError:
            pass
        else:
            return describe(worktree, package, python, version, installer, found, "reused")
    workflow = worktree / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8") if workflow.is_file() else ""
    extras = ci_extras(text, package.extras, windows=os.name == "nt")
    log(f"{worktree.name}: installing {', '.join(extras) or 'no extras'} with {installer}")
    install_editable(worktree, venv, extras, uv)
    version, where = probe(python, package.module)
    check_version(version, pinned=pinned)
    found = check_location(worktree, package, where)
    return describe(worktree, package, python, version, installer, found, "")


def describe(
    worktree: Path,
    package: Package,
    python: Path,
    version: str,
    installer: str,
    found: Path,
    note: str,
) -> tuple[str, str]:
    venv_text = f"{python.as_posix()} ({version}, {installer}{', ' + note if note else ''})"
    try:
        shown = Path(os.path.relpath(found, worktree)).as_posix()
    except ValueError:
        shown = found.as_posix()
    return venv_text, f"ok: {package.module} -> {shown}"


def npm_directories(worktree: Path) -> list[Path]:
    return [
        folder
        for folder in (worktree, worktree / "web")
        if (folder / "package-lock.json").is_file()
    ]


def prepare_npm(worktree: Path, requested: bool) -> str:
    folders = npm_directories(worktree)
    if not folders:
        return ""
    if not requested:
        return "not run (--npm runs npm ci)"
    npm = shutil.which("npm")
    if not npm:
        raise WorktreeError("npm was not found on this machine")
    for folder in folders:
        log(f"{worktree.name}: npm ci in {folder.name}")
        run([npm, "ci"], cwd=folder, what=f"npm ci in {folder}")
    return "ci ok in " + ", ".join(
        folder.relative_to(worktree).as_posix() or "." for folder in folders
    )


# --- add --------------------------------------------------------------------


def add_one(
    args: argparse.Namespace, repos_root: Path, root: Path, repo: str, uv: str | None
) -> Result:
    path = root / args.branch / repo
    result = Result(repo, path)
    try:
        checkout = main_checkout(repos_root, repo)
        git(checkout, "fetch", "origin")
        result.how = create_worktree(checkout, path, args.branch, args.base)
        if (path / "pyproject.toml").is_file():
            if args.no_venv:
                result.venv, result.import_line = "skipped (--no-venv)", "not checked"
            else:
                result.venv, result.import_line = prepare_python(path, args, uv)
        else:
            result.venv, result.import_line = "-", "-"
        result.npm = prepare_npm(path, args.npm)
    except (WorktreeError, OSError) as error:
        result.error = str(error)
    return result


def render(result: Result) -> str:
    where = result.path.as_posix()
    if result.error:
        return f"{result.repo}: FAILED {where}: {result.error}"
    line = (
        f"{result.repo}  {where}  [{result.how}]  venv {result.venv}  import {result.import_line}"
    )
    return f"{line}  npm {result.npm}" if result.npm else line


def command_add(args: argparse.Namespace) -> int:
    check_branch(args.branch)
    repos_root = args.repos_root or default_repos_root()
    repos = list(dict.fromkeys(args.repos))
    uv = None if args.no_uv else shutil.which("uv")
    jobs = max(1, min(args.jobs, len(repos)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(add_one, args, repos_root, args.root, repo, uv) for repo in repos]
        results = [future.result() for future in futures]
    for result in results:
        print(render(result))
    return 1 if any(result.error for result in results) else 0


# --- remove and list --------------------------------------------------------


def branch_worktrees(repos_root: Path, root: Path, branch: str) -> list[tuple[Path, Worktree]]:
    found = []
    for repo in known_repos(repos_root):
        for tree in worktrees(repo):
            if tree.branch == branch and under(tree.path, root):
                found.append((repo, tree))
    return found


def changes(path: Path) -> list[str]:
    return git(path, "status", "--porcelain").splitlines()


def prune_empty(path: Path, root: Path) -> None:
    """Remove the now-empty <root>/<branch> folders left by the removal."""
    parent = path.parent
    while under(parent, root):
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def command_remove(args: argparse.Namespace) -> int:
    check_branch(args.branch)
    repos_root = args.repos_root or default_repos_root()
    found = branch_worktrees(repos_root, args.root, args.branch)
    if not found:
        print(f"no worktrees of {args.branch} under {args.root.as_posix()}")
        return 0
    if not args.force:
        dirty = [(repo, tree) for repo, tree in found if tree.path.exists() and changes(tree.path)]
        if dirty:
            for repo, tree in dirty:
                print(f"{repo.name}: uncommitted changes in {tree.path.as_posix()}")
            print("nothing removed; commit or discard them, or pass --force")
            return 1
    failed = False
    for repo, tree in found:
        try:
            if tree.path.exists():
                flags = ["--force"] if args.force else []
                git(repo, "worktree", "remove", *flags, str(tree.path))
            else:
                git(repo, "worktree", "prune")
            prune_empty(tree.path, args.root)
            print(f"{repo.name}: removed {tree.path.as_posix()}")
        except WorktreeError as error:
            failed = True
            print(f"{repo.name}: FAILED {error}")
            continue
        if args.delete_branch:
            try:
                git(repo, "branch", "-D" if args.force else "-d", args.branch)
                print(f"{repo.name}: deleted local branch {args.branch}")
            except WorktreeError as error:
                failed = True
                print(
                    f"{repo.name}: kept branch {args.branch}: {error}; "
                    f"`git -C {repo.as_posix()} branch -D {args.branch}` deletes it anyway"
                )
    return 1 if failed else 0


def standing(tree: Worktree) -> tuple[str, str]:
    state = "dirty" if changes(tree.path) else "clean"
    if not tree.branch or not ref_exists(tree.path, f"refs/remotes/origin/{tree.branch}"):
        return state, "not on origin"
    counts = git(tree.path, "rev-list", "--left-right", "--count", f"HEAD...origin/{tree.branch}")
    ahead, behind = counts.split()
    return state, f"ahead {ahead} behind {behind}"


def command_list(args: argparse.Namespace) -> int:
    repos_root = args.repos_root or default_repos_root()
    rows = []
    for repo in known_repos(repos_root):
        try:
            trees = worktrees(repo)
        except WorktreeError as error:
            log(f"{repo.name}: {error}")
            continue
        for tree in trees:
            if under(tree.path, args.root) and tree.path.exists():
                rows.append((tree.branch or f"(detached) {tree.head[:8]}", repo.name, tree))
    if not rows:
        print(f"no worktrees under {args.root.as_posix()}")
        return 0
    print(f"worktrees under {args.root.as_posix()} (ahead/behind as of the last fetch)")
    current = None
    for branch, name, tree in sorted(rows, key=lambda row: (row[0], row[1])):
        if branch != current:
            print(branch)
            current = branch
        state, sync = standing(tree)
        print(f"  {name:<18} {state:<6} {sync:<18} {tree.path.as_posix()}")
    return 0


# --- command line -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"worktree root (default {DEFAULT_ROOT.as_posix()})",
    )
    common.add_argument(
        "--repos-root",
        type=Path,
        help="folder holding the repo checkouts (default: the siblings of the main specs checkout)",
    )
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], prog="worktree.py")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", parents=[common], help="make worktrees for a branch")
    add.add_argument("branch")
    add.add_argument("repos", nargs="+", metavar="repo")
    add.add_argument(
        "--base", default=DEFAULT_BASE, help="where a new branch starts (default origin/main)"
    )
    add.add_argument("--no-venv", action="store_true", help="make the worktrees only")
    add.add_argument(
        "--npm", action="store_true", help="run npm ci where a package-lock.json exists"
    )
    add.add_argument("--python", help="interpreter for the venvs (default: Python 3.12)")
    add.add_argument(
        "--no-uv", action="store_true", help="use venv and pip even when uv is installed"
    )
    add.add_argument("--jobs", type=int, default=4, help="repos prepared at once (default 4)")
    add.set_defaults(run=command_add)

    remove = sub.add_parser("remove", parents=[common], help="remove a branch's worktrees")
    remove.add_argument("branch")
    remove.add_argument("--delete-branch", action="store_true", help="also delete the local branch")
    remove.add_argument(
        "--force", action="store_true", help="remove dirty worktrees, delete unmerged branches"
    )
    remove.set_defaults(run=command_remove)

    listing = sub.add_parser("list", parents=[common], help="show every worktree under the root")
    listing.set_defaults(run=command_list)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] not in (*SUBCOMMANDS, "-h", "--help"):
        arguments.insert(0, "add")  # `worktree.py <branch> <repos...>`
    args = build_parser().parse_args(arguments)
    try:
        return int(args.run(args))
    except WorktreeError as error:
        print(f"worktree.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
