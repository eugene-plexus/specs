"""Ship committed component work to Edge in one command.

    python scripts/ship.py                    # every repo whose main moved past its pin
    python scripts/ship.py workbench gateway  # just these
    python scripts/ship.py --dry-run          # say what would ship; change nothing
    python scripts/ship.py --wait             # then wait until Edge carries it
    python scripts/ship.py --one-push         # merged specs commits ride with the pins

It does every hop a pin needs, in the order CLAUDE.md gives: each repo's
`main` is pushed if it is ahead; `ui` and `workbench` get a `dist` commit
built from that `main` (no worktree: the commit is assembled with a private
index, so no stale `dist` checkout can be picked up); `workbench` and
`site-host` are pinned in the agent, which is committed and pushed; then the
specs manifest, both installers and their generated block are updated,
committed and pushed. Specs CI and the image build then publish Edge by
themselves (`edge.yml`); `--wait` watches for that or names the failure.

The pin commit is pushed alone (P11): merged specs commits that `main` holds
beyond `origin/main` are pushed first, on their own, so their run plans their
change and the pin push's run plans the pins only (the reduced profile). CI
passes the pin push's run only once the merged work's run has passed
(`scripts/previous_push.py`). When a merged specs script needs the new
component code, it must go out with the pins: pass `--one-push`.

What it checks before anything is pushed: each repo is on `main` with no
uncommitted tracked changes and not behind `origin/main`, and `ruff check` /
`ruff format --check` pass in each Python repo's own `.venv`. It does not run
test suites: CI does, after the push (docs/maintenance/testing-and-release.md).
A dependency change stops it, because the lock must be re-resolved first
(`python scripts/release-inputs.py --resolve --uv <uv>`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

SPECS = Path(__file__).resolve().parent.parent
ROOT = SPECS.parent
MANIFEST = SPECS / "release" / "manifest.json"
CATALOGUE = Path("src/eugene_plexus_agent/apps_catalogue.yaml")
SITE_HOST_PY = Path("src/eugene_plexus_agent/site_host.py")
MANIFEST_REPOS = (
    "agent",
    "control",
    "gateway",
    "library",
    "inference-driver",
    "tool-driver",
)
ORDER = (*MANIFEST_REPOS[1:], "site-host", "workbench", "agent", "ui")
SHA = re.compile(r"[a-f0-9]{40}")
WB_PIN = re.compile(
    r"(workbench/archive/)([a-f0-9]{40})(\.tar\.gz\n  version: )([a-f0-9]{40})"
)
SH_PIN = re.compile(r'(?m)^(SITE_HOST_COMMIT = ")([a-f0-9]{40})(")')


class Stop(Exception):
    """A reason not to ship, worded for the person reading the terminal."""


def run(
    cwd: Path, *args: str, env: dict[str, str] | None = None, quiet: bool = False
) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        env={**os.environ, **env} if env else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise Stop(f"{cwd.name}: `{' '.join(args)}` failed:\n{detail[-3000:]}")
    if not quiet and result.stdout.strip() and args[0] != "git":
        print(result.stdout.strip()[-1500:])
    return result.stdout.strip()


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return run(repo, "git", *args, env=env)


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=repo,
            capture_output=True,
        ).returncode
        == 0
    )


def main_parent(repo: Path, dist_commit: str) -> str:
    """The `main` commit a `dist` commit was built from: its parent on main."""
    for parent in git(repo, "rev-list", "--parents", "-1", dist_commit).split()[1:]:
        if is_ancestor(repo, parent, "origin/main"):
            return parent
    raise Stop(f"{repo.name}: dist {dist_commit[:7]} has no parent on main")


def dependencies(repo: Path, ref: str) -> list[str]:
    project = tomllib.loads(git(repo, "show", f"{ref}:pyproject.toml"))
    deps = list(project["project"].get("dependencies", []))
    deps += project["build-system"]["requires"]
    if repo.name == "agent":
        deps += project["project"].get("optional-dependencies", {}).get("service", [])
    return sorted(deps)


def venv_python(repo: Path) -> Path:
    for candidate in (
        repo / ".venv" / "Scripts" / "python.exe",
        repo / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return candidate
    raise Stop(f"{repo.name}: no .venv; static checks run from the repo's own venv")


def trailers(co_author: str | None, repo: Path) -> str:
    name = git(repo, "config", "user.name")
    email = git(repo, "config", "user.email")
    lines = [f"Co-Authored-By: {co_author}"] if co_author else []
    return "\n".join([*lines, f"Signed-off-by: {name} <{email}>"])


@dataclass
class Plan:
    name: str
    repo: Path
    pinned: str  # the commit the release names now (a dist commit for ui/workbench)
    source: str  # the main commit that pin was built from
    head: str  # the main commit to ship
    push_main: bool
    new_pin: str = ""


def current_pins() -> dict[str, str]:
    pins = dict(json.loads(MANIFEST.read_text(encoding="utf-8"))["components"])
    agent = ROOT / "agent"
    catalogue = git(agent, "show", f"HEAD:{CATALOGUE.as_posix()}")
    site_host = git(agent, "show", f"HEAD:{SITE_HOST_PY.as_posix()}")
    wb, sh = WB_PIN.search(catalogue), SH_PIN.search(site_host)
    if not wb or wb[2] != wb[4] or not sh:
        raise Stop("agent: could not read the Workbench or site-host pin")
    pins["workbench"] = wb[2]
    pins["site-host"] = sh[2]
    return pins


def prepare(name: str, pinned: str, *, explicit: bool) -> Plan | None:
    repo = ROOT / name
    git(
        repo,
        "fetch",
        "-q",
        "origin",
        "main",
        *(["dist"] if name in ("ui", "workbench") else []),
    )
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    head = git(repo, "rev-parse", "HEAD")
    remote = git(repo, "rev-parse", "origin/main")
    source = main_parent(repo, pinned) if name in ("ui", "workbench") else pinned
    if branch != "main":
        if explicit:
            raise Stop(f"{name}: on branch {branch}, not main")
        head = remote  # not shipping from here; only report whether origin moved
    if head == source:
        return None
    if branch == "main":
        if git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise Stop(
                f"{name}: uncommitted changes to tracked files; commit or stash them"
            )
        if not is_ancestor(repo, remote, head):
            raise Stop(
                f"{name}: main is behind or diverged from origin/main; pull first"
            )
    if not is_ancestor(repo, source, head):
        raise Stop(
            f"{name}: the pinned {source[:7]} is not an ancestor of main {head[:7]}"
        )
    if not explicit and branch != "main":
        print(f"  {name}: origin/main moved but the checkout is on {branch}; skipped")
        return None
    return Plan(name, repo, pinned, source, head, push_main=head != remote)


def static_checks(plan: Plan) -> None:
    if not (plan.repo / "pyproject.toml").exists() or plan.name == "ui":
        return
    python = venv_python(plan.repo)
    run(plan.repo, str(python), "-m", "ruff", "check", "--quiet", ".", quiet=True)
    run(
        plan.repo,
        str(python),
        "-m",
        "ruff",
        "format",
        "--check",
        "--quiet",
        ".",
        quiet=True,
    )


def npm(cwd: Path, *args: str) -> None:
    executable = shutil.which("npm")
    if executable is None:
        raise Stop("npm is not on PATH; it builds the ui and workbench front ends")
    lock, installed = (
        cwd / "package-lock.json",
        cwd / "node_modules" / ".package-lock.json",
    )
    if not installed.exists() or lock.stat().st_mtime > installed.stat().st_mtime:
        run(cwd, executable, "ci", "--no-audit", "--no-fund", quiet=True)
    run(cwd, executable, *args, quiet=True)


def publish_dist(plan: Plan, co_author: str | None, dry_run: bool) -> str:
    """Build the front end from `main` and commit main's tree plus the build onto `dist`.

    The commit's parents are the previous `dist` and the `main` commit, so
    `dist` only ever fast-forwards and records what it was built from."""
    repo = plan.repo
    if plan.name == "ui":
        built = ["python/eugene_plexus_ui/static"]
        npm(repo, "run", "build:python")
        title = f"Publish UI distribution from {plan.head[:7]}"
    else:
        built = ["src/eugene_plexus_workbench/static"]
        npm(repo / "web", "run", "build")
        title = f"Publish Workbench dist from {plan.head[:7]}"
    for path in built:
        if not any((repo / path).iterdir()):
            raise Stop(f"{plan.name}: the build left {path} empty")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise Stop(f"{plan.name}: the build changed tracked files; commit them first")
    with tempfile.TemporaryDirectory() as scratch:
        env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(repo, "read-tree", plan.head, env=env)
        git(repo, "add", "-f", "--", *built, env=env)
        if plan.name == "workbench":
            info = Path(scratch) / "BUILD_INFO"
            info.write_text(
                f"built-from: eugene-plexus/workbench@{plan.head}\n",
                encoding="utf-8",
                newline="\n",
            )
            blob = git(repo, "hash-object", "-w", str(info))
            git(
                repo,
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{blob},BUILD_INFO",
                env=env,
            )
        tree = git(repo, "write-tree", env=env)
        message = Path(scratch) / "message"
        message.write_text(
            f"{title}\n\nbuilt-from: eugene-plexus/{plan.name}@{plan.head}\n\n"
            + trailers(co_author, repo)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        commit = git(
            repo,
            "commit-tree",
            tree,
            "-p",
            "origin/dist",
            "-p",
            plan.head,
            "-F",
            str(message),
        )
    if not dry_run:
        git(repo, "push", "-q", "origin", f"{commit}:refs/heads/dist")
    return commit


def commit_files(
    repo: Path, files: list[str], message: str, co_author: str | None
) -> str:
    git(repo, "add", "--", *files)
    with tempfile.NamedTemporaryFile(
        "w", delete=False, encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(message + "\n\n" + trailers(co_author, repo) + "\n")
    try:
        git(repo, "commit", "-q", "-F", handle.name, "--", *files)
    finally:
        os.unlink(handle.name)
    return git(repo, "rev-parse", "HEAD")


def pin_in_agent(
    plans: dict[str, Plan], co_author: str | None, dry_run: bool
) -> Plan | None:
    """Pin a new Workbench dist and/or site-host in the agent; return the agent's plan."""
    moved = [name for name in ("workbench", "site-host") if name in plans]
    if not moved:
        return plans.get("agent")
    repo = ROOT / "agent"
    agent = plans.get("agent")
    if agent is None:  # agent itself unchanged: it ships because of the pin commit
        if git(repo, "rev-parse", "--abbrev-ref", "HEAD") != "main":
            raise Stop(
                "agent: on another branch; the Workbench/site-host pin is committed on main"
            )
        if git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise Stop(
                "agent: uncommitted changes to tracked files; commit or stash them"
            )
        head = git(repo, "rev-parse", "HEAD")
        if head != git(repo, "rev-parse", "origin/main"):
            raise Stop(
                "agent: main differs from origin/main; name agent to ship it too, or pull"
            )
        agent = Plan("agent", repo, head, head, head, push_main=False)
    if dry_run:
        print(f"  agent: would pin {', '.join(moved)} and commit")
        return agent
    words = []
    if "workbench" in plans:
        path = repo / CATALOGUE
        text = path.read_text(encoding="utf-8")
        new = plans["workbench"].new_pin
        path.write_text(
            WB_PIN.sub(rf"\g<1>{new}\g<3>{new}", text), encoding="utf-8", newline="\n"
        )
        words.append(f"Workbench dist {new[:7]}")
    if "site-host" in plans:
        path = repo / SITE_HOST_PY
        text = path.read_text(encoding="utf-8")
        new = plans["site-host"].head
        path.write_text(
            SH_PIN.sub(rf"\g<1>{new}\g<3>", text), encoding="utf-8", newline="\n"
        )
        words.append(f"site host {new[:7]}")
    files = [
        p.as_posix()
        for p, n in ((CATALOGUE, "workbench"), (SITE_HOST_PY, "site-host"))
        if n in plans
    ]
    agent.head = commit_files(repo, files, f"Pin {' and '.join(words)}", co_author)
    agent.push_main = True
    return agent


def ship(
    names: list[str], *, dry_run: bool, co_author: str | None, one_push: bool = False
) -> str | None:
    if git(SPECS, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise Stop("specs: not on main")
    if git(SPECS, "status", "--porcelain", "--untracked-files=no"):
        raise Stop(
            "specs: uncommitted changes to tracked files; commit or stash them first"
        )
    git(SPECS, "fetch", "-q", "origin", "main")
    if not is_ancestor(SPECS, "origin/main", "HEAD"):
        raise Stop("specs: main is behind origin/main; pull first")
    merged = int(git(SPECS, "rev-list", "--count", "origin/main..HEAD"))
    merged_head = git(SPECS, "rev-parse", "HEAD")
    pins = current_pins()
    explicit = bool(names)
    unknown = set(names) - set(ORDER)
    if unknown:
        raise Stop(
            f"unknown repo(s): {', '.join(sorted(unknown))}; known: {', '.join(ORDER)}"
        )
    plans: dict[str, Plan] = {}
    for name in ORDER:
        if names and name not in names:
            continue
        plan = prepare(name, pins[name], explicit=explicit)
        if plan is not None:
            plans[name] = plan
    if not plans:
        print("Nothing to ship: every pin is at its repo's main.")
        return None
    for plan in plans.values():
        print(
            f"  {plan.name}: {plan.source[:7]} -> {plan.head[:7]}"
            + (" (push main)" if plan.push_main else "")
        )
    for plan in plans.values():
        if plan.name in (*MANIFEST_REPOS, "workbench"):
            if dependencies(plan.repo, plan.source) != dependencies(
                plan.repo, plan.head
            ):
                raise Stop(
                    f"{plan.name}: its dependencies changed. Re-resolve the lock first:\n"
                    "  python scripts/release-inputs.py --resolve --uv <uv>"
                )
        static_checks(plan)
    for plan in plans.values():
        if plan.push_main and not dry_run:
            git(plan.repo, "push", "-q", "origin", "HEAD:main")
    if merged and not one_push:
        # Their own push, before the pin commit exists: its run plans their
        # change, and the pin push's run plans the pins alone (P11).
        if dry_run:
            print(f"  specs: would push {merged} merged commit(s) first, on their own")
        else:
            git(SPECS, "push", "-q", "origin", f"{merged_head}:refs/heads/main")
            print(
                f"  specs: pushed {merged} merged commit(s) to {merged_head[:7]} on their own"
            )
    for name in ("ui", "workbench"):
        if name in plans:
            plans[name].new_pin = publish_dist(plans[name], co_author, dry_run)
            print(
                f"  {name}: dist {plans[name].new_pin[:7]}"
                + (" (not pushed)" if dry_run else "")
            )
    agent = pin_in_agent(plans, co_author, dry_run)
    if agent is not None:
        plans["agent"] = agent
        if agent.push_main and not dry_run:
            git(agent.repo, "push", "-q", "origin", "HEAD:main")
    for name in MANIFEST_REPOS:
        if name in plans:
            plans[name].new_pin = plans[name].head
    if dry_run:
        if merged and one_push:
            print(f"  specs: the pin commit would carry {merged} merged commit(s) in one push")
        else:
            print("  specs: the pin commit would be pushed alone")
        print("Dry run: nothing pushed, specs unchanged.")
        return None
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name in (*MANIFEST_REPOS, "ui"):
        if name in plans:
            manifest["components"][name] = plans[name].new_pin
    MANIFEST.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    run(SPECS, sys.executable, "scripts/release-inputs.py", quiet=True)
    if "site-host" in plans:
        path = SPECS / "scripts" / "install.sh"
        text = path.read_text(encoding="utf-8")
        new = plans["site-host"].head
        text = re.sub(r"(?m)^PIN_SITE_HOST=[a-f0-9]{40}", f"PIN_SITE_HOST={new}", text)
        path.write_text(text, encoding="utf-8", newline="\n")
    run(SPECS, sys.executable, "scripts/release-inputs.py", "--check", quiet=True)
    shipped = ", ".join(
        f"{n} {plans[n].new_pin[:7] or plans[n].head[:7]}" for n in plans
    )
    commit = commit_files(
        SPECS,
        ["release/manifest.json", "scripts/install.sh", "scripts/install.ps1"],
        f"Ship to Edge: {shipped}",
        co_author,
    )
    git(SPECS, "push", "-q", "origin", "HEAD:main")
    alone = "" if one_push and merged else " alone"
    print(
        f"Pushed specs {commit[:7]}{alone}. Edge publishes once its CI and image pass."
    )
    return commit


def gh_json(*args: str) -> object:
    return json.loads(run(SPECS, "gh", *args, quiet=True) or "null")


def wait_for_edge(commit: str, minutes: float) -> int:
    """Return 0 once `edge` contains `commit`; 1 with the failing jobs if CI fails."""
    deadline = time.perf_counter() + minutes * 60
    started = time.perf_counter()
    while time.perf_counter() < deadline:
        git(SPECS, "fetch", "-q", "origin", "edge")
        edge = git(SPECS, "rev-parse", "origin/edge")
        if is_ancestor(SPECS, commit, edge):
            took = (time.perf_counter() - started) / 60
            print(
                f"Edge is at {edge[:7]}, which includes {commit[:7]} ({took:.0f} min)."
            )
            print("On an install: Machines -> the machine's update card -> Check now, then Update.")
            return 0
        for workflow in ("ci.yml", "container.yml"):
            runs = gh_json(
                "run",
                "list",
                "--workflow",
                workflow,
                "--commit",
                commit,
                "--event",
                "push",
                "--json",
                "databaseId,status,conclusion",
            )
            for entry in runs if isinstance(runs, list) else []:
                # A cancelled run is not a failure here. A failed run of the
                # merged work pushed first fails this commit's run as well
                # (its "previous push" job), and is named through it.
                if entry["status"] == "completed" and entry["conclusion"] in (
                    "failure",
                    "timed_out",
                ):
                    jobs = gh_json(
                        "run", "view", str(entry["databaseId"]), "--json", "jobs"
                    )
                    failed = [
                        j["name"]
                        for j in (jobs or {}).get("jobs", [])
                        if j.get("conclusion") == "failure"
                    ]
                    print(
                        f"{workflow} failed for {commit[:7]}: {', '.join(failed) or entry['conclusion']}"
                    )
                    print(f"  gh run view {entry['databaseId']} --log-failed")
                    return 1
        time.sleep(30)
    print(
        f"Edge did not include {commit[:7]} within {minutes:.0f} minutes; see `gh run list`."
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repos", nargs="*", help=f"some of: {', '.join(ORDER)}")
    parser.add_argument(
        "--dry-run", action="store_true", help="build and report; push nothing"
    )
    parser.add_argument(
        "--wait", action="store_true", help="wait until Edge carries the result"
    )
    parser.add_argument(
        "--wait-for", metavar="SPECS_COMMIT", help="only wait, for this commit"
    )
    parser.add_argument(
        "--one-push",
        action="store_true",
        help="push merged specs commits with the pin commit (one push, their plan); "
        "for a merged script that needs the new component code",
    )
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument(
        "--co-author",
        default=os.environ.get("EP_SHIP_CO_AUTHOR"),
        help='e.g. "Claude Opus 5.5 <noreply@anthropic.com>" (or set EP_SHIP_CO_AUTHOR)',
    )
    args = parser.parse_args()
    try:
        if args.wait_for:
            return wait_for_edge(git(SPECS, "rev-parse", args.wait_for), args.minutes)
        commit = ship(
            args.repos,
            dry_run=args.dry_run,
            co_author=args.co_author,
            one_push=args.one_push,
        )
        if commit and args.wait:
            return wait_for_edge(commit, args.minutes)
    except Stop as stop:
        print(f"Not shipped: {stop}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
