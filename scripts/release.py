"""Run a release end to end, from Edge's pins to the published GitHub release.

    python scripts/release.py v0.3.1              # every phase not yet done
    python scripts/release.py v0.3.1 --dry-run    # check, and say what would run
    python scripts/release.py v0.3.1 --from qualify   # redo from a phase after a fix

Asking for a release is the approval to publish it (Troy, 2026-10-19), so
nothing here stops for approval: it stops on a failure, naming the cause, or
when it needs the release notes written. A session runs it in the background
and is woken by its exit. Design: docs/design/release-script.md.

Exit codes: 0 released; 1 a phase failed; 2 a precondition is not met;
3 it needs the release notes at docs/releases/<version>.md.

Phases, in order, each recorded in docs/private/release-<version>/state.json
so a rerun resumes after the last one that passed:

  preflight  Edge's pins are every repo's main, and their own CI is green.
  candidate  The console rebuilt with this version's installer links; pinned.
  artifacts  The packaged installers (release-artifacts.py).
  evidence   This machine's runs: fresh installs on Windows and WSL, the
             Windows upgrade from the last release, the Linux system update,
             recovery. Sequential: they share browsers and port ranges.
  record     docs/acceptance/<version>-release-run.md from those results.
  qualify    Release qualification on that commit, before any tag exists.
  tag        The annotated tag at the qualified commit.
  image      The qualified container image, retagged as the version.
  publish    The GitHub release as Latest, its assets checked after upload.
  website    The site's release data, checked, built, deployed, then checked live.
  close      The record's publication section; a read-only update check.

The NAS root's container upgrade stays Troy's, root first.

A patch release (docs/design/release-script.md, "Patch releases") runs from a
release line's specs worktree, which `scripts/release-line.py open vX.Y` makes:

    python scripts/release-line.py open v0.3
    python scripts/release-line.py pick v0.3 agent:<commit on main>
    cd ../eugene-plexus-release/v0.3/specs && python scripts/release.py v0.3.1

On a `release/vX.Y` branch the run is in patch mode: the version is the next
patch of the line's newest release; the candidate is that release's pins plus
the line's commits; every push goes to the line's own refs, and only the notes
and the record reach specs `main`, as one documentation-only commit. Only the
newest line is patched, except with `--security`. `--rehearsal`, on a
`rehearsal/vX.Y` line, runs preflight to qualify for `vX.Y.Z-rehearsal.N`.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ship  # noqa: E402
from ship import ROOT, SPECS, Stop, git, main_parent  # noqa: E402

PHASES = (
    "preflight",
    "candidate",
    "artifacts",
    "evidence",
    "record",
    "qualify",
    "tag",
    "image",
    "publish",
    "website",
    "close",
)
#: What a rehearsal runs: no tag, image, release or website.
REHEARSAL_PHASES = ("preflight", "candidate", "artifacts", "record", "qualify")
VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
REHEARSAL_VERSION = re.compile(r"(v\d+\.\d+\.\d+)-rehearsal\.\d+")
LINE_BRANCH = re.compile(r"(release|rehearsal)/v(\d+)\.(\d+)")
ORG = "eugene-plexus"
IMAGE = "ghcr.io/eugene-plexus/control-plane"
MODEL = Path(r"D:\eugene-demo\models\gemma-4-E4B-it-Q4_K_M.gguf")
WSL_PYTHON = "/mnt/d/py/eugene-plexus/agent/.venv-wsl/bin/python"
TEMP = Path(tempfile.gettempdir())
UI_STATIC = "python/eugene_plexus_ui/static"
WB_STATIC = "src/eugene_plexus_workbench/static"
SITE = ROOT / "website"
#: The components a release line branches, besides specs.
LINE_REPOS = (
    "agent",
    "control",
    "gateway",
    "library",
    "inference-driver",
    "tool-driver",
    "site-host",
    "workbench",
    "ui",
)
#: The repositories whose dependencies release-inputs.py locks.
LOCK_REPOS = (
    "agent",
    "control",
    "gateway",
    "inference-driver",
    "library",
    "tool-driver",
    "ui",
    "workbench",
)
#: Patch mode (a release line), set by main(): its branch, version and the
#: directory of the person's own checkouts. None on main.
LINE: dict[str, Any] | None = None


class Failed(Exception):
    """A phase ran and something did not pass."""


class NeedsNotes(Exception):
    """The release notes are the session's to write."""


class Refused(Stop):
    """A push a release must never make."""


# --- small helpers -----------------------------------------------------------


def say(text: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {text}", flush=True)


def run_gh(*args: str) -> str:
    """The one way to GitHub's CLI (the patch acceptance answers it offline)."""
    return ship.run(SPECS, "gh", *args, quiet=True)


def gh(*args: str, repo: str = "specs") -> str:
    return run_gh(*args, "-R", f"{ORG}/{repo}")


def gh_api(path: str) -> Any:
    return json.loads(run_gh("api", path) or "null")


def fetch_url(url: str, timeout: float = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as reply:
        return reply.read()


def ref_or_none(repo: Path, ref: str) -> str | None:
    """The object `ref` names, or None when there is none."""
    done = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return (done.stdout.strip() or None) if done.returncode == 0 else None


def same_path(one: Path, other: Path) -> bool:
    return one.resolve() == other.resolve()


def push(
    repo: Path,
    src: str,
    ref: str,
    *,
    force: bool = False,
    delete: bool = False,
    docs_to_main: bool = False,
) -> None:
    """Every push a release makes. Never `edge`; a deletion only of a scratch
    branch. In patch mode only the line's own refs move: its branch, its dist
    branch, its release-candidate branch and its tag. Never main or dist, except
    the documentation-only commit on specs main at the close (`docs_to_main`)
    and the website's own main."""
    full = ref if ref.startswith("refs/") else f"refs/heads/{ref}"
    if full == "refs/heads/edge":
        raise Refused(
            f"{repo.name}: a release never pushes edge; Publish Edge moves it"
        )
    if delete and not full.startswith(
        ("refs/heads/release-candidate/", "refs/heads/rehearsal/")
    ):
        raise Refused(
            f"{repo.name}: a release deletes only scratch branches, not {full}"
        )
    if LINE is not None and same_path(repo, SITE):
        if full != "refs/heads/main" or force or delete:
            raise Refused(f"website: a patch release moves only its main, not {full}")
    elif LINE is not None:
        branch, version = LINE["branch"], LINE.get("version")
        allowed = {f"refs/heads/{branch}", f"refs/heads/{branch}-dist"}
        if version:
            allowed |= {
                f"refs/heads/release-candidate/{version}",
                f"refs/tags/{version}",
            }
        own_candidate = full.startswith(
            f"refs/heads/release-candidate/{branch.split('/')[-1]}."
        )
        if delete and own_candidate:
            pass  # a scratch branch of one of the line's own versions
        elif (
            docs_to_main
            and full == "refs/heads/main"
            and same_path(repo, SPECS)
            and not (force or delete)
        ):
            base = git(repo, "rev-parse", "origin/main")
            if git(repo, "rev-list", "--parents", "-1", src).split()[1:] != [base]:
                raise Refused(f"specs: {src[:7]} is not one commit on origin/main")
            docs_only(repo, base, src)
        elif full not in allowed:
            raise Refused(
                f"{repo.name}: a patch release never pushes {full}; "
                f"it moves only {', '.join(sorted(allowed))}"
            )
    args = ["--delete", full] if delete else [f"{src}:{full}"]
    git(repo, "push", "-q", *(["-f"] if force else []), "origin", *args)


def docs_only(repo: Path, old: str, new: str) -> list[str]:
    """The paths `new` changes against `old`: each must be a regular file added
    or modified under docs/. A deletion, rename, mode change, symlink or
    submodule is refused, as is any other path."""
    raw = git(repo, "diff", "--raw", "--no-renames", "--no-abbrev", old, new)
    paths, bad = [], []
    for line in raw.splitlines():
        meta, _, path = line.partition("\t")
        old_mode, new_mode, _, _, status = meta.lstrip(":").split()
        paths.append(path)
        if (
            not path.startswith("docs/")
            or status not in ("A", "M")
            or new_mode != "100644"
            or old_mode not in ("000000", "100644")
        ):
            bad.append(f"{path} ({status}, mode {old_mode} to {new_mode})")
    if bad or not paths:
        raise Refused(
            "specs: refused to push to main: not a documentation-only change: "
            + (", ".join(bad) or "no change")
        )
    return paths


def wsl_path(path: Path) -> str:
    drive, rest = path.resolve().drive, path.resolve().as_posix()[2:]
    return f"/mnt/{drive[0].lower()}{rest}"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fresh_dir(name: str) -> Path:
    """A directory under %TEMP% that does not exist yet (the harnesses refuse old ones)."""
    for n in range(1, 100):
        path = TEMP / f"{name}-{n}"
        if not path.exists():
            return path
    raise Stop(f"{TEMP}: no free {name}-N directory")


def logged(
    log: Path, command: list[str], *, timeout: float, env: dict[str, str] | None = None
) -> tuple[int, str]:
    """Run a long command with its output in `log`; return the exit code and the output."""
    log.parent.mkdir(parents=True, exist_ok=True)
    say(f"running {' '.join(command)[:200]}")
    started = time.perf_counter()
    with log.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"$ {' '.join(command)}\n")
        stream.flush()
        child = subprocess.Popen(
            command,
            cwd=SPECS,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env={**os.environ, **(env or {})},
        )
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # The harnesses start agents, engines and a browser; kill the whole
            # tree, or the next attempt meets their ports still held.
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(child.pid)], capture_output=True
            )
            child.wait()
            code = -1
            stream.write(f"\nTIMED OUT after {timeout:.0f} s; process tree killed\n")
        stream.write(f"\nEXIT={code} ELAPSED={time.perf_counter() - started:.0f}s\n")
    return code, log.read_text(encoding="utf-8", errors="replace")


def last_json(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {}


def version_key(tag: str) -> tuple[int, int, int]:
    match = VERSION.fullmatch(tag)
    if not match:
        raise Stop(
            f"{tag}: a release version is three numbers, vX.Y.Z (updaters reject other forms)"
        )
    return int(match[1]), int(match[2]), int(match[3])


# --- release lines (patch mode) ----------------------------------------------


def release_version(version: str, *, rehearsal: bool) -> tuple[int, int, int]:
    """The three numbers of a version; a rehearsal's is vX.Y.Z-rehearsal.N."""
    if rehearsal:
        match = REHEARSAL_VERSION.fullmatch(version)
        if not match:
            raise Stop(f"{version}: a rehearsal's version is vX.Y.Z-rehearsal.N")
        return version_key(match[1])
    return version_key(version)


def patch_previous(
    version: str,
    line: tuple[int, int],
    tags: list[str],
    latest: str,
    *,
    security: bool,
    rehearsal: bool,
) -> str:
    """The release a patch follows: the newest on its line. The version must be
    that release's next patch, and the line the latest release's, unless the
    patch is a security fix (--security)."""
    key = release_version(version, rehearsal=rehearsal)
    name = f"v{line[0]}.{line[1]}"
    if key[:2] != line:
        raise Stop(f"{version} is not on line {name}, the line of this checkout")
    on_line = sorted(
        (version_key(t), t)
        for t in tags
        if VERSION.fullmatch(t) and version_key(t)[:2] == line
    )
    if not on_line:
        raise Stop(f"line {name} has no release to patch")
    (major, minor, patch), previous = on_line[-1]
    if key != (major, minor, patch + 1):
        raise Stop(
            f"{version} must follow {previous}, the newest release on line {name}: "
            f"the next patch is v{major}.{minor}.{patch + 1}"
        )
    newest = version_key(latest)[:2]
    if line > newest:
        raise Stop(f"line {name} is newer than the latest release, {latest}")
    if line < newest and not security:
        raise Stop(
            f"{version}: line {name} is older than the latest release, {latest}. "
            "Only a security fix patches an older line: rerun with --security "
            "(the record says so)"
        )
    return previous


def tag_pins(specs: Path, agent: Path, ref: str) -> dict[str, str]:
    """Every pin a release names: the manifest's seven, and the Workbench and
    site-host pins in its agent."""
    pins = dict(
        json.loads(git(specs, "show", f"{ref}:release/manifest.json"))["components"]
    )
    catalogue = git(agent, "show", f"{pins['agent']}:{ship.CATALOGUE.as_posix()}")
    site_host = git(agent, "show", f"{pins['agent']}:{ship.SITE_HOST_PY.as_posix()}")
    wb, sh = ship.WB_PIN.search(catalogue), ship.SH_PIN.search(site_host)
    if not wb or wb[2] != wb[4] or not sh:
        raise Stop(f"{ref}: could not read its agent's Workbench or site-host pin")
    pins["workbench"], pins["site-host"] = wb[2], sh[2]
    return pins


def built_from(repo: Path, name: str, dist: str) -> str:
    """The source commit a dist commit was built from: its `built-from:` line,
    which must name one of its parents; or, without one, its parent on main."""
    message = git(repo, "log", "-1", "--format=%B", dist)
    found = re.search(
        rf"(?m)^built-from: eugene-plexus/{re.escape(name)}@([a-f0-9]{{40}})$", message
    )
    if not found:
        return main_parent(repo, dist)
    if found[1] not in git(repo, "rev-list", "--parents", "-1", dist).split()[1:]:
        raise Stop(
            f"{name}: dist {dist[:7]} names {found[1][:7]}, not one of its parents"
        )
    return found[1]


def line_sources(root: Path, pins: dict[str, str]) -> dict[str, str]:
    """Where each repository's line starts: its pin, or for ui and Workbench the
    source their dist commit was built from."""
    return {
        name: built_from(root / name, name, pins[name])
        if name in ("ui", "workbench")
        else pins[name]
        for name in LINE_REPOS
    }


def dist_parent(repo: Path, pin: str, dist_branch: str) -> str:
    """The first parent of a line's dist commit: the last release's dist, or an
    earlier candidate of this release built on it. Never main's `dist`."""
    remote = ref_or_none(repo, f"refs/remotes/origin/{dist_branch}")
    if remote is None or ship.is_ancestor(repo, remote, pin):
        return pin
    if ship.is_ancestor(repo, pin, remote):
        return remote
    raise Stop(
        f"{repo.name}: {dist_branch} is at {remote[:7]}, which does not hold the "
        f"last release's dist {pin[:7]}"
    )


def check_lock(sources: dict[str, str], heads: dict[str, str]) -> None:
    """A line commit that changes a dependency needs the lock re-resolved on the line."""
    changed = [
        name
        for name in LOCK_REPOS
        if heads[name] != sources[name]
        and ship.dependencies(ROOT / name, sources[name])
        != ship.dependencies(ROOT / name, heads[name])
    ]
    if not changed:
        return
    wanted = set().union(*(ship.dependencies(ROOT / n, heads[n]) for n in LOCK_REPOS))
    listed = SPECS / "release" / "requirements.in"
    have = {
        x.strip() for x in listed.read_text(encoding="utf-8").splitlines() if x.strip()
    }
    if wanted != have:
        branch = LINE["branch"] if LINE else "main"
        raise Stop(
            f"{', '.join(changed)}: its dependencies changed on {branch}. Re-resolve the "
            f"lock on the line first: python scripts/release-inputs.py --resolve --uv <uv> "
            f"(in {SPECS}), commit release/ and both installers on {branch}, push, rerun"
        )


# --- state -------------------------------------------------------------------


class Release:
    def __init__(
        self,
        version: str,
        co_author: str | None,
        *,
        security: bool = False,
        rehearsal: bool = False,
    ) -> None:
        self.version = version
        self.co_author = co_author
        self.security = security
        self.rehearsal = rehearsal
        self.dir = SPECS / "docs" / "private" / f"release-{version}"
        self.state_file = self.dir / "state.json"
        self.state: dict[str, Any] = (
            json.loads(self.state_file.read_text(encoding="utf-8"))
            if self.state_file.exists()
            else {}
        )
        self.state.setdefault("version", version)
        self.state.setdefault("done", [])

    persist = True  # a dry run keeps its state in memory

    def save(self) -> None:
        if self.persist:
            write(self.state_file, json.dumps(self.state, indent=2) + "\n")

    def __getitem__(self, key: str) -> Any:
        if key not in self.state:
            raise Stop(f"state has no {key!r}; run the phase that records it (--from)")
        return self.state[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.state[key] = value
        self.save()

    def done(self, phase: str) -> bool:
        return phase in self.state["done"]

    def mark(self, phase: str) -> None:
        self.state["done"].append(phase)
        self.save()

    def reopen(self, phase: str) -> None:
        later = PHASES[PHASES.index(phase) :]
        self.state["done"] = [p for p in self.state["done"] if p not in later]
        if "evidence" in later and phase != "evidence":
            # A new candidate or package: no earlier run describes it.
            self.state.pop("evidence", None)
        self.save()

    @property
    def record(self) -> str:
        return f"docs/acceptance/{self.version}-release-run.md"

    @property
    def notes(self) -> Path:
        return SPECS / "docs" / "releases" / f"{self.version}.md"

    def commit(self, repo: Path, files: list[str], message: str) -> str:
        """Commit `files` if they changed; either way, return HEAD (a rerun after a failed push)."""
        if not git(repo, "status", "--porcelain", "--", *files):
            return git(repo, "rev-parse", "HEAD")
        return ship.commit_files(repo, files, message, self.co_author)


# --- GitHub runs -------------------------------------------------------------


def patient_gh(*args: str, repo: str = "specs") -> str:
    """`gh` for a poll: a passing network error must not end a 150-minute wait."""
    for attempt in range(6):
        try:
            return gh(*args, repo=repo)
        except Stop:
            if attempt == 5:
                raise
            time.sleep(30)
    raise AssertionError("unreachable")


def find_run(
    workflow: str,
    sha: str,
    since: float,
    *,
    repo: str = "specs",
    event: str = "workflow_dispatch",
) -> int:
    deadline = time.perf_counter() + 300
    while time.perf_counter() < deadline:
        runs = json.loads(
            patient_gh(
                "run",
                "list",
                "--workflow",
                workflow,
                "--event",
                event,
                "-L",
                "20",
                "--json",
                "databaseId,headSha,createdAt",
                repo=repo,
            )
            or "[]"
        )
        for entry in runs:
            created = datetime.fromisoformat(
                entry["createdAt"].replace("Z", "+00:00")
            ).timestamp()
            if entry["headSha"] == sha and created >= since - 30:
                return int(entry["databaseId"])
        time.sleep(10)
    raise Failed(f"{repo}: no {workflow} run for {sha[:7]} appeared within 5 minutes")


def wait_run(run_id: int, minutes: float, *, repo: str = "specs") -> None:
    url = f"https://github.com/{ORG}/{repo}/actions/runs/{run_id}"
    say(f"waiting on {url}")
    deadline = time.perf_counter() + minutes * 60
    while time.perf_counter() < deadline:
        view = json.loads(
            patient_gh(
                "run",
                "view",
                str(run_id),
                "--json",
                "status,conclusion,jobs",
                repo=repo,
            )
        )
        if view["status"] == "completed":
            if view["conclusion"] == "success":
                say(f"run {run_id} passed")
                return
            failed = [
                j["name"]
                for j in view.get("jobs", [])
                if j.get("conclusion") in ("failure", "timed_out", "cancelled")
            ]
            try:
                log = gh("run", "view", str(run_id), "--log-failed", repo=repo)
            except Stop as exc:
                log = str(exc)
            raise Failed(
                f"{url} ended {view['conclusion']}: {', '.join(failed) or 'no job named'}\n"
                + "\n".join(log.splitlines()[-60:])
            )
        time.sleep(60)
    raise Failed(f"{url} did not finish within {minutes:.0f} minutes")


def rollup(repo: str, sha: str) -> str | None:
    query = (
        f'{{ repository(owner: "{ORG}", name: "{repo}") {{ object(oid: "{sha}") '
        "{ ... on Commit { statusCheckRollup { state } } } } }"
    )
    data = json.loads(run_gh("api", "graphql", "-f", f"query={query}"))
    commit = ((data.get("data") or {}).get("repository") or {}).get("object") or {}
    return (commit.get("statusCheckRollup") or {}).get("state")


def registry_digest(tag: str) -> str:
    with urllib.request.urlopen(
        f"https://ghcr.io/token?scope=repository:{ORG}/control-plane:pull", timeout=30
    ) as reply:
        token = json.load(reply)["token"]
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{ORG}/control-plane/manifests/{tag}",
        method="HEAD",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ", ".join(
                (
                    "application/vnd.oci.image.index.v1+json",
                    "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                )
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as reply:
        return reply.headers["docker-content-digest"]


# --- phases ------------------------------------------------------------------


def preflight(r: Release, *, dry_run: bool) -> None:
    version_key(r.version)
    latest = gh_api(f"repos/{ORG}/specs/releases/latest")["tag_name"]
    if version_key(r.version) <= version_key(latest):
        raise Stop(f"{r.version} is not above the latest release, {latest}")
    if not r.done("tag") and git(SPECS, "tag", "-l", r.version):
        raise Stop(f"{r.version} is already tagged; a release version is never reused")
    r["previous"] = latest
    if git(SPECS, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise Stop("specs: not on main")
    if git(SPECS, "status", "--porcelain", "--untracked-files=no"):
        raise Stop("specs: uncommitted changes to tracked files")
    git(SPECS, "fetch", "-q", "--tags", "origin", "main")
    if git(SPECS, "rev-parse", "HEAD") != git(SPECS, "rev-parse", "origin/main"):
        raise Stop("specs: main differs from origin/main; pull or push first")
    pins = ship.current_pins()
    if not r.done("candidate"):
        unshipped = [
            name
            for name in ship.ORDER
            if ship.prepare(name, pins[name], explicit=False)
        ]
        if unshipped:
            raise Stop(
                f"not on Edge yet: {', '.join(unshipped)}. Ship them first (scripts/ship.py --wait)"
            )
    red = []
    for name, pin in pins.items():
        sha = main_parent(ROOT / name, pin) if name in ("ui", "workbench") else pin
        state = rollup(name, sha)
        if state != "SUCCESS":
            red.append(f"{name} {sha[:7]} ({state or 'no CI result'})")
    if red:
        raise Stop("component CI is not green on the pins: " + "; ".join(red))
    local_tools()
    rehearsals = gh_api(
        f"repos/{ORG}/specs/actions/workflows/release-qualification.yml/runs?event=schedule&per_page=1"
    )
    newest = (rehearsals or {}).get("workflow_runs") or []
    if newest and newest[0].get("conclusion") not in (None, "success"):
        say(
            f"warning: the newest weekly rehearsal ended {newest[0]['conclusion']}: {newest[0]['html_url']}"
        )
    if not r.notes.exists():
        say(
            f"note: {r.notes.relative_to(SPECS).as_posix()} is not written yet; the record phase needs it"
        )
    say(
        f"preflight passed: {r.version} after {latest}; Edge pins green"
        + (" (dry run)" if dry_run else "")
    )


def local_tools() -> None:
    """What the evidence runs need on this machine."""
    for need, check in (
        ("the seeded model", MODEL.is_file()),
        ("npm on PATH", shutil.which("npm") is not None),
        ("httpx and PyYAML in this interpreter", _imports(sys.executable)),
    ):
        if not check:
            raise Stop(f"missing: {need}")
    probe = subprocess.run(
        ["wsl.exe", "-e", WSL_PYTHON, "-c", "import httpx, yaml"], capture_output=True
    )
    if probe.returncode != 0:
        raise Stop(f"WSL: {WSL_PYTHON} cannot import httpx and yaml")


def _imports(python: str) -> bool:
    return (
        subprocess.run(
            [python, "-c", "import httpx, yaml"], capture_output=True
        ).returncode
        == 0
    )


def preflight_patch(r: Release, *, dry_run: bool) -> None:
    """The version is the line's next patch; every worktree is at its line head,
    and holds the last release; every moved head's own CI passed. Edge's pins
    are not compared: main is not what ships."""
    assert LINE is not None
    branch = LINE["branch"]
    git(SPECS, "fetch", "-q", "--tags", "origin", "main", branch)
    latest = gh_api(f"repos/{ORG}/specs/releases/latest")["tag_name"]
    previous = patch_previous(
        r.version,
        LINE["key"],
        git(SPECS, "tag", "-l", "v*").splitlines(),
        latest,
        security=r.security,
        rehearsal=r.rehearsal,
    )
    if not r.done("tag") and git(SPECS, "tag", "-l", r.version):
        raise Stop(f"{r.version} is already tagged; a release version is never reused")
    r["previous"], r["latest"] = previous, latest
    r["olderLine"] = LINE["key"] < version_key(latest)[:2]
    r["security"], r["rehearsal"], r["line"] = r.security, r.rehearsal, branch
    for name in ("specs", *LINE_REPOS):
        repo = SPECS if name == "specs" else ROOT / name
        if not (repo / ".git").exists():
            raise Stop(
                f"{name}: no worktree at {repo}; run release-line.py open {LINE['name']}"
            )
        here = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if here != branch:
            raise Stop(f"{name}: {repo} is on {here}, not {branch}")
        if name != "specs":
            git(repo, "fetch", "-q", "origin", "main", branch)
        if git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise Stop(f"{name}: uncommitted changes to tracked files in {repo}")
        if git(repo, "rev-parse", "HEAD") != git(repo, "rev-parse", f"origin/{branch}"):
            raise Stop(
                f"{name}: {repo} differs from origin/{branch}; push or pull first"
            )
    if not ship.is_ancestor(SPECS, previous, "HEAD"):
        raise Stop(f"specs: {branch} does not hold {previous}")
    sources = line_sources(ROOT, tag_pins(SPECS, ROOT / "agent", previous))
    moved = []
    for name in LINE_REPOS:
        head = git(ROOT / name, "rev-parse", "HEAD")
        if not ship.is_ancestor(ROOT / name, sources[name], head):
            raise Stop(
                f"{name}: {branch} does not hold {previous}'s commit {sources[name][:7]}"
            )
        if head != sources[name]:
            moved.append(name)
            line_ci(name, head, branch, dry_run=dry_run)
    if not r.rehearsal:
        local_tools()
    if not r.rehearsal and not r.notes.exists():
        say(
            f"note: {r.notes.relative_to(SPECS).as_posix()} is not written yet; the record phase needs it"
        )
    say(
        f"preflight passed: {r.version} after {previous} on {branch}"
        + (f"; moved: {', '.join(moved)}" if moved else "; no repository moved")
        + (" (security fix)" if r.security else "")
        + (" (dry run)" if dry_run else "")
    )


def line_ci(name: str, sha: str, branch: str, *, dry_run: bool) -> None:
    """A moved line head's own CI passed. With no result yet, wait for its run,
    or start one on the line and wait."""
    state = rollup(name, sha)
    if state == "SUCCESS":
        return
    runs = json.loads(
        gh(
            "run",
            "list",
            "--workflow",
            "ci.yml",
            "--commit",
            sha,
            "--json",
            "databaseId,url,status,conclusion",
            repo=name,
        )
        or "[]"
    )
    newest = max(runs, key=lambda entry: entry["databaseId"], default=None)
    if state in ("FAILURE", "ERROR"):
        where = (
            newest["url"] if newest else f"https://github.com/{ORG}/{name}/commit/{sha}"
        )
        raise Stop(f"{name}: CI failed on {branch} at {sha[:7]}: {where}")
    if dry_run:
        say(
            f"{name}: {sha[:7]} has no passed CI yet ({state or 'no result'}); a run waits for it"
        )
        return
    if newest is None:
        since = time.time()
        gh("workflow", "run", "ci.yml", "--ref", branch, repo=name)
        run_id = find_run("ci.yml", sha, since, repo=name)
    else:
        run_id = int(newest["databaseId"])
    try:
        wait_run(run_id, 90, repo=name)
    except Failed as failed:
        raise Stop(
            f"{name}: CI did not pass on {branch} at {sha[:7]}: {failed}"
        ) from None


def candidate(r: Release) -> None:
    ui = ROOT / "ui"
    pins = ship.current_pins()
    source = main_parent(ui, pins["ui"])
    if git(ui, "rev-parse", "HEAD") != source or git(
        ui, "status", "--porcelain", "--untracked-files=no"
    ):
        raise Stop(
            f"ui: the checkout must be clean at {source[:7]}, the Edge console's source"
        )
    git(ui, "fetch", "-q", "origin", "dist")
    dist, count = build_console(r, source, "origin/dist")
    push(ui, dist, "refs/heads/dist")
    say(f"ui: dist {dist[:7]} ({count} files)")
    manifest = json.loads(ship.MANIFEST.read_text(encoding="utf-8"))
    manifest["components"]["ui"] = dist
    write(ship.MANIFEST, json.dumps(manifest, indent=2) + "\n")
    ship.run(SPECS, sys.executable, "scripts/release-inputs.py", quiet=True)
    ship.run(SPECS, sys.executable, "scripts/release-inputs.py", "--check", quiet=True)
    pins = ship.current_pins()
    shell = (SPECS / "scripts" / "install.sh").read_text(encoding="utf-8")
    site = re.search(r"(?m)^PIN_SITE_HOST=([a-f0-9]{40})", shell)
    if not site or site[1] != pins["site-host"]:
        raise Failed("the installers and the pinned agent disagree about site-host")
    commit = r.commit(
        SPECS,
        ["release/manifest.json", "scripts/install.sh", "scripts/install.ps1"],
        f"{r.version} candidate: console with release-pinned machine setup",
    )
    push(SPECS, "HEAD", "refs/heads/main")
    r["candidate"] = commit
    r["pins"] = pins
    r["consoleSource"] = source
    r["consoleFiles"] = count
    r["workbenchSource"] = main_parent(ROOT / "workbench", pins["workbench"])
    say(f"candidate specs {commit[:7]} pushed")


def build_console(r: Release, source: str, parent: str) -> tuple[str, int]:
    """Build the console from `source` with this version's installer links;
    return its dist commit (parents: `parent` and the source) and file count."""
    ui = ROOT / "ui"
    ref = f"specs/{r.version}/scripts"
    os.environ["NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF"] = r.version
    try:
        say(f"building the console from {source[:7]} for {r.version}")
        ship.npm(ui, "run", "build:python")
    finally:
        del os.environ["NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF"]
    static, export = ui / UI_STATIC, ui / "out"
    files = sorted(p.relative_to(export) for p in export.rglob("*") if p.is_file())
    staged = sorted(p.relative_to(static) for p in static.rglob("*") if p.is_file())
    if files != staged or any(
        not filecmp.cmp(export / f, static / f, shallow=False) for f in files
    ):
        raise Failed("ui: the staged static files differ from the export")
    texts = [(static / f).read_bytes() for f in staged]
    if not any(ref.encode() in t for t in texts) or any(
        b"specs/main/scripts" in t for t in texts
    ):
        raise Failed(f"ui: the export must name {ref} and never specs/main/scripts")
    dist = assemble_dist(
        ui,
        "ui",
        source,
        parent,
        UI_STATIC,
        f"Build {r.version} console with release-pinned machine setup",
        r.co_author,
        extra=f"NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF={r.version}\n",
    )
    count = len(
        [
            n
            for n in git(ui, "ls-tree", "-r", "--name-only", dist).splitlines()
            if n.startswith(UI_STATIC + "/")
        ]
    )
    if count != len(staged):
        raise Failed(
            f"ui: the dist commit holds {count} static files, the build {len(staged)}"
        )
    return dist, count


def assemble_dist(
    repo: Path,
    name: str,
    source: str,
    parent: str,
    static: str,
    title: str,
    co_author: str | None,
    *,
    extra: str = "",
) -> str:
    """A dist commit as ship.py makes one, without a checkout: the source's tree
    plus the built files, with `parent` and the source as its parents."""
    with tempfile.TemporaryDirectory() as scratch:
        env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(repo, "read-tree", source, env=env)
        git(repo, "add", "-f", "--", static, env=env)
        if name == "workbench":
            info = Path(scratch) / "BUILD_INFO"
            write(info, f"built-from: eugene-plexus/workbench@{source}\n")
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
        write(
            message,
            f"{title}\n\nbuilt-from: eugene-plexus/{name}@{source}\n{extra}\n"
            + ship.trailers(co_author, repo)
            + "\n",
        )
        return git(
            repo, "commit-tree", tree, "-p", parent, "-p", source, "-F", str(message)
        )


def candidate_patch(r: Release) -> None:
    """The last release's pins plus the line's commits. The console is rebuilt
    from ui's line head on the last release's dist; Workbench, when it moved,
    likewise, and pinned on the agent's line. Everything goes to the line."""
    assert LINE is not None
    branch = LINE["branch"]
    dist_branch = f"{branch}-dist"
    base = tag_pins(SPECS, ROOT / "agent", r["previous"])
    sources = line_sources(ROOT, base)
    heads = {name: git(ROOT / name, "rev-parse", "HEAD") for name in LINE_REPOS}
    check_lock(sources, heads)
    ui = ROOT / "ui"
    if git(ui, "status", "--porcelain", "--untracked-files=no"):
        raise Stop(f"ui: uncommitted changes to tracked files in {ui}")
    git(ui, "fetch", "-q", "origin")
    dist, count = build_console(
        r, heads["ui"], dist_parent(ui, base["ui"], dist_branch)
    )
    push(ui, dist, f"refs/heads/{dist_branch}")
    say(f"ui: {dist_branch} {dist[:7]} ({count} files)")
    workbench = base["workbench"]
    if heads["workbench"] != sources["workbench"]:
        workbench = workbench_dist(
            r, heads["workbench"], base["workbench"], dist_branch
        )
    pin_on_line(r, workbench, heads["site-host"])
    manifest = json.loads(ship.MANIFEST.read_text(encoding="utf-8"))
    for name in ship.MANIFEST_REPOS:
        manifest["components"][name] = git(ROOT / name, "rev-parse", "HEAD")
    manifest["components"]["ui"] = dist
    write(ship.MANIFEST, json.dumps(manifest, indent=2) + "\n")
    shell_file = SPECS / "scripts" / "install.sh"
    write(
        shell_file,
        re.sub(
            r"(?m)^PIN_SITE_HOST=[a-f0-9]{40}",
            f"PIN_SITE_HOST={heads['site-host']}",
            shell_file.read_text(encoding="utf-8"),
        ),
    )
    ship.run(SPECS, sys.executable, "scripts/release-inputs.py", quiet=True)
    ship.run(SPECS, sys.executable, "scripts/release-inputs.py", "--check", quiet=True)
    pins = ship.current_pins()
    site = re.search(
        r"(?m)^PIN_SITE_HOST=([a-f0-9]{40})", shell_file.read_text(encoding="utf-8")
    )
    if not site or site[1] != pins["site-host"]:
        raise Failed("the installers and the pinned agent disagree about site-host")
    if pins["workbench"] != workbench:
        raise Failed(
            f"agent: pins Workbench {pins['workbench'][:7]}, not {workbench[:7]}"
        )
    commit = r.commit(
        SPECS,
        ["release/manifest.json", "scripts/install.sh", "scripts/install.ps1"],
        f"{r.version} candidate: {r['previous']} and the commits on {branch}",
    )
    push(SPECS, "HEAD", f"refs/heads/{branch}")
    r["candidate"] = commit
    r["pins"] = pins
    r["consoleSource"] = heads["ui"]
    r["consoleFiles"] = count
    r["workbenchSource"] = built_from(
        ROOT / "workbench", "workbench", pins["workbench"]
    )
    r["lineCommits"] = line_commits(r, sources)
    say(f"candidate specs {commit[:7]} pushed to {branch}")


def workbench_dist(r: Release, source: str, pin: str, dist_branch: str) -> str:
    """Workbench's dist built from its line head on the last release's dist; an
    earlier candidate's build of the same source is used again."""
    wb = ROOT / "workbench"
    git(wb, "fetch", "-q", "origin")
    remote = ref_or_none(wb, f"refs/remotes/origin/{dist_branch}")
    if (
        remote
        and remote != pin
        and ship.is_ancestor(wb, pin, remote)
        and built_from(wb, "workbench", remote) == source
    ):
        say(f"workbench: {dist_branch} {remote[:7]} is built from {source[:7]} already")
        return remote
    if git(wb, "status", "--porcelain", "--untracked-files=no"):
        raise Stop(f"workbench: uncommitted changes to tracked files in {wb}")
    ship.npm(wb / "web", "run", "build")
    static = wb / WB_STATIC
    if not static.is_dir() or not any(static.iterdir()):
        raise Failed(f"workbench: the build left {WB_STATIC} empty")
    if git(wb, "status", "--porcelain", "--untracked-files=no"):
        raise Failed("workbench: the build changed tracked files")
    commit = assemble_dist(
        wb,
        "workbench",
        source,
        dist_parent(wb, pin, dist_branch),
        WB_STATIC,
        f"Build {r.version} Workbench from {source[:7]}",
        r.co_author,
    )
    push(wb, commit, f"refs/heads/{dist_branch}")
    say(f"workbench: {dist_branch} {commit[:7]}")
    return commit


def pin_on_line(r: Release, workbench: str, site_host: str) -> None:
    """The agent's line pins this Workbench dist and site host (a commit on its
    line when either differs)."""
    assert LINE is not None
    agent = ROOT / "agent"
    pins = ship.current_pins()
    if pins["workbench"] == workbench and pins["site-host"] == site_host:
        return
    if git(agent, "status", "--porcelain", "--untracked-files=no"):
        raise Stop(f"agent: uncommitted changes to tracked files in {agent}")
    words, files = [], []
    if pins["workbench"] != workbench:
        path = agent / ship.CATALOGUE
        write(
            path,
            ship.WB_PIN.sub(
                rf"\g<1>{workbench}\g<3>{workbench}", path.read_text(encoding="utf-8")
            ),
        )
        words.append(f"Workbench dist {workbench[:7]}")
        files.append(ship.CATALOGUE.as_posix())
    if pins["site-host"] != site_host:
        path = agent / ship.SITE_HOST_PY
        write(
            path,
            ship.SH_PIN.sub(
                rf"\g<1>{site_host}\g<3>", path.read_text(encoding="utf-8")
            ),
        )
        words.append(f"site host {site_host[:7]}")
        files.append(ship.SITE_HOST_PY.as_posix())
    ship.commit_files(
        agent, files, f"Pin {' and '.join(words)} for {r.version}", r.co_author
    )
    push(agent, "HEAD", f"refs/heads/{LINE['branch']}")


def line_commits(r: Release, sources: dict[str, str]) -> list[dict[str, Any]]:
    """The commits on the line past the last release, for the record: every
    component commit, and specs' picks and tooling commit."""
    found = []
    previous = git(SPECS, "rev-parse", f"{r['previous']}^{{commit}}")
    for name in ("specs", *LINE_REPOS):
        repo = SPECS if name == "specs" else ROOT / name
        start = previous if name == "specs" else sources[name]
        log = git(
            repo, "log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"{start}..HEAD"
        )
        for entry in filter(None, (e.strip() for e in log.split("\x1e"))):
            sha, subject, body = (entry.split("\x1f") + ["", ""])[:3]
            picked = re.search(r"\(cherry picked from commit ([a-f0-9]{40})\)", body)
            if (
                name == "specs"
                and not picked
                and not subject.startswith("Release tooling")
            ):
                continue
            found.append(
                {
                    "repo": name,
                    "commit": sha,
                    "from": picked[1] if picked else None,
                    "subject": subject,
                }
            )
    return found


def artifacts(r: Release, ref: str, name: str) -> Path:
    out = r.dir / name
    shutil.rmtree(out, ignore_errors=True)
    ship.run(
        SPECS,
        sys.executable,
        "scripts/release-artifacts.py",
        "--version",
        r.version,
        "--ref",
        ref,
        "--output",
        str(out),
        quiet=True,
    )
    return out


def installed_commits(python: Path, names: list[str]) -> dict[str, str]:
    code = (
        "import importlib, json; print(json.dumps({n: importlib.import_module("
        "'eugene_plexus_' + n.replace('-', '_') + '._build').commit() for n in %r}))"
        % names
    )
    return json.loads(
        subprocess.check_output([str(python), "-I", "-c", code], text=True)
    )


def check_windows_install(r: Release, prefix: Path) -> dict[str, Any]:
    """The installed packages, console files and Workbench pin are the candidate's."""
    pins = r["pins"]
    manifest = {k: v for k, v in pins.items() if k not in ("workbench", "site-host")}
    python = prefix / "venv" / "Scripts" / "python.exe"
    commits = installed_commits(python, list(manifest))
    static = prefix / "venv" / "Lib" / "site-packages" / "eugene_plexus_ui" / "static"
    installed = {
        p.relative_to(static).as_posix(): blob_id(p.read_bytes())
        for p in static.rglob("*")
        if p.is_file()
    }
    tree = git(ROOT / "ui", "ls-tree", "-r", pins["ui"], "--", UI_STATIC)
    shipped = {
        line.split("\t")[1][len(UI_STATIC) + 1 :]: line.split()[2]
        for line in tree.splitlines()
    }
    catalogue_file = (
        prefix
        / "venv"
        / "Lib"
        / "site-packages"
        / "eugene_plexus_agent"
        / "apps_catalogue.yaml"
    )
    if not catalogue_file.is_file():
        raise Failed(f"windows: the install has no agent catalogue at {catalogue_file}")
    catalogue = catalogue_file.read_text(encoding="utf-8")
    return {
        "commitsMatch": commits == manifest,
        # Two empty sets are not a match: the count must be the dist's.
        "consoleIdentical": installed == shipped
        and len(installed) == r["consoleFiles"],
        "consoleFiles": len(installed),
        "workbenchPinned": pins["workbench"] in catalogue,
    }


def evidence(r: Release) -> None:
    cand = r.dir / "candidate"
    if not (cand / "install.ps1").exists():
        raise Stop("no packaged candidate; run --from artifacts")
    logs = r.dir / "logs"
    results: dict[str, Any] = r.state.get("evidence", {})

    def current(name: str) -> bool:
        """Passed, and against this candidate (a rerun after a new one redoes it)."""
        entry = results.get(name, {})
        return bool(entry.get("passed")) and entry.get("candidate") == r["candidate"]

    def keep(name: str, result: dict[str, Any]) -> None:
        result["candidate"] = r["candidate"]
        results[name] = result
        r["evidence"] = results
        if not result.get("passed"):
            raise Failed(f"{name} did not pass; log {result.get('log')}")
        say(f"{name} passed")

    if not current("windows"):
        out = fresh_dir(f"ep-{r.version}-win")
        code, output = logged(
            logs / "windows.log",
            [
                sys.executable,
                "scripts/s10-acceptance.py",
                "--output",
                str(out),
                "--model",
                str(MODEL),
                "--installer",
                str(cand / "install.ps1"),
            ],
            timeout=2400,
        )
        summary = last_json(output)
        result = {
            "log": str(logs / "windows.log"),
            "output": str(out),
            "prefix": str(out / "install"),
            "installSeconds": summary.get("installSeconds"),
            "liveInstallUnchanged": summary.get("liveInstallUnchanged"),
        }
        if code == 0 and summary.get("passed"):
            detail = json.loads((out / "result.json").read_text(encoding="utf-8"))
            result["firstToken"] = (
                (detail.get("browser") or {}).get("firstReply") or {}
            ).get("installToFirstTokenSeconds")
            result.update(check_windows_install(r, out / "install"))
            result["passed"] = all(
                result[k]
                for k in ("commitsMatch", "consoleIdentical", "workbenchPinned")
            )
        keep("windows", result)

    if not current("wsl"):
        n = len(list(logs.glob("wsl*.log"))) + 1
        wsl_out, staged = (
            f"/tmp/ep-{r.version}-wsl-{n}",
            f"/tmp/ep-{r.version}-candidate-{n}",
        )
        names = [k for k in r["pins"] if k not in ("workbench", "site-host")]
        check = (
            "import importlib, json, sys; print('COMMITS ' + json.dumps({n: importlib.import_module("
            "'eugene_plexus_' + n.replace('-', '_') + '._build').commit() for n in %r}))"
            % names
        )
        script = "\n".join(
            [
                "set -e",
                "for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*'); do unset \"$v\"; done",
                f"mkdir -p {staged} && cp '{wsl_path(cand / 'install.sh')}' {staged}/install.sh",
                f"cd '{wsl_path(SPECS)}'",
                f"{WSL_PYTHON} scripts/s10-acceptance.py --output {wsl_out} --model '{wsl_path(MODEL)}' --installer {staged}/install.sh",
                f'cat {wsl_out}/result.json | {WSL_PYTHON} -c "import json,sys; d=json.load(sys.stdin); '
                "print('FIRSTTOKEN', ((d.get('browser') or {}).get('firstReply') or {}).get('installToFirstTokenSeconds'))\"",
                f'{wsl_out}/install/venv/bin/python -I -c "{check}"',
                "",
            ]
        )
        script_file = r.dir / f"wsl-{n}.sh"
        write(script_file, script)
        code, output = logged(
            logs / f"wsl-{n}.log",
            ["wsl.exe", "-e", "bash", wsl_path(script_file)],
            timeout=2400,
        )
        summary = last_json(
            "\n".join(x for x in output.splitlines() if '"target"' in x)
        )
        commits = re.search(r"^COMMITS (\{.*\})$", output, re.MULTILINE)
        first = re.search(r"^FIRSTTOKEN (\S+)$", output, re.MULTILINE)
        manifest = {k: v for k, v in r["pins"].items() if k in names}
        result = {
            "log": str(logs / f"wsl-{n}.log"),
            "output": wsl_out,
            "installSeconds": summary.get("installSeconds"),
            "firstToken": float(first[1]) if first and first[1] != "None" else None,
            "commitsMatch": commits is not None and json.loads(commits[1]) == manifest,
        }
        result["passed"] = (
            code == 0 and bool(summary.get("passed")) and result["commitsMatch"]
        )
        keep("wsl", result)

    if not current("upgrade"):
        previous = r["previous"]
        old = r.dir / f"{previous}-install.ps1"
        old.write_bytes(
            subprocess.check_output(
                ["git", "show", f"{previous}:scripts/install.ps1"], cwd=SPECS
            )
        )
        out = fresh_dir(f"ep-{r.version}-upgrade")
        out.mkdir()
        code, output = logged(
            logs / "upgrade.log",
            [
                sys.executable,
                "scripts/release-upgrade-acceptance.py",
                "--from-installer",
                str(old),
                "--to-installer",
                str(cand / "install.ps1"),
                "--model",
                str(MODEL),
                "--output",
                str(out),
            ],
            timeout=3600,
        )
        line = re.search(r"RESULT (PASS|FAIL): (\d+)/(\d+) checks", output)
        result = {
            "log": str(logs / "upgrade.log"),
            "output": str(out),
            "from": previous,
            "checks": f"{line[2]}/{line[3]}" if line else None,
        }
        detail = out / "result.json"
        result["passed"] = (
            code == 0
            and detail.exists()
            and bool(json.loads(detail.read_text(encoding="utf-8")).get("passed"))
        )
        keep("upgrade", result)

    if not current("systemUpdate"):
        person = subprocess.check_output(["wsl.exe", "-e", "whoami"], text=True).strip()
        code, output = logged(
            logs / "system-update.log",
            [
                "wsl.exe",
                "-u",
                "root",
                "-e",
                "env",
                f"EP_PERSON={person}",
                f"EP_FROM={r['previous']}",
                f"EP_TARGET={r['candidate']}",
                "bash",
                wsl_path(SPECS / "scripts" / "updates-system-install-acceptance.sh"),
            ],
            timeout=1800,
        )
        # The script exits 0 with failed checks; only its last word says.
        keep(
            "systemUpdate",
            {
                "log": str(logs / "system-update.log"),
                "from": r["previous"],
                "passed": code == 0 and "ALL PASS" in output,
            },
        )

    if not current("recovery"):
        prefix = Path(results["windows"]["prefix"])
        engine = next(prefix.glob("engines/**/llama-server.exe"), None)
        if engine is None:
            raise Failed(f"recovery: no llama-server.exe under {prefix / 'engines'}")
        out = fresh_dir(f"ep-{r.version}-recovery")
        code, output = logged(
            logs / "recovery.log",
            [
                str(prefix / "venv" / "Scripts" / "python.exe"),
                "scripts/a7-recovery-acceptance.py",
                "--directory",
                str(out),
                "--disposable-venv",
                str(prefix / "venv"),
                "--uv",
                str(prefix / "bin" / "uv.exe"),
                "--model",
                str(MODEL),
                "--engine",
                str(engine),
            ],
            timeout=1800,
        )
        detail = out / "result.json"
        data = json.loads(detail.read_text(encoding="utf-8")) if detail.exists() else {}
        keep(
            "recovery",
            {
                "log": str(logs / "recovery.log"),
                "output": str(out),
                "timings": data.get("timings"),
                "passed": code == 0 and bool(data.get("passed")),
            },
        )


def _section(text: str, heading: str) -> str:
    match = re.search(rf"(?ms)^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text)
    return match[1].strip() if match else ""


def record_text(r: Release) -> str:
    pins, ev, previous = r["pins"], r["evidence"], r["previous"]
    files = json.loads(
        (r.dir / "candidate" / "manifest.json").read_text(encoding="utf-8")
    )["files"]
    added = git(
        SPECS,
        "diff",
        "--name-only",
        "--diff-filter=A",
        f"{previous}..HEAD",
        "--",
        "docs/acceptance",
    ).splitlines()
    added = [
        a for a in added if a.endswith(".md") and not a.endswith("-release-run.md")
    ]
    old = SPECS / "docs" / "acceptance" / f"{previous}-release-run.md"
    limits = (
        _section(old.read_text(encoding="utf-8"), "Untested paths and limits")
        if old.exists()
        else ""
    )
    rows = "\n".join(
        f"| {name} | `{pins[name]}` |"
        for name in (
            "agent",
            "control",
            "gateway",
            "library",
            "inference-driver",
            "tool-driver",
        )
    )
    win, wsl, up, rec = ev["windows"], ev["wsl"], ev["upgrade"], ev["recovery"]

    def secs(value: Any) -> str:
        return f"{value:.1f} s" if isinstance(value, (int, float)) else "not recorded"

    timings = ", ".join(
        f"{k} {v:.1f} s"
        for k, v in (rec.get("timings") or {}).items()
        if isinstance(v, (int, float))
    )
    text = (
        f"""# {r.version} release run

Run by `scripts/release.py`. Every check below ran against candidate specs
`{r["candidate"]}`, packaged by `release-artifacts.py`; the evidence logs are in
`docs/private/release-{r.version}/logs/`.

{patch_section(r)}## Candidate and scope

"""
        + candidate_table(r, rows, files)
        + f"""

Feature-level acceptance since {previous}, each run against its own Edge pins:

"""
        + (
            "\n".join(f"- [{Path(a).stem}]({Path(a).name})" for a in added)
            or "- None added."
        )
        + f"""

## Packaged installations

Both candidate installers passed `scripts/s10-acceptance.py`: a fresh prefix, all
seven packages, the shipped browser UI, setup and sign-in, engine acquisition, a
model launch, a visible browser reply and a separate keyed reply, with the seeded
Gemma 4 E4B Q4_K_M on the processor (real CPU inference, not GPU compatibility).
In both, every installed package commit equals the manifest.

| Target | Installer elapsed | Install to first token | Result |
| --- | ---: | ---: | --- |
| Windows 11 | {secs(win.get("installSeconds"))} | {secs(win.get("firstToken"))} | Passed; {win.get("consoleFiles")} console files identical to the dist; live install unchanged: {win.get("liveInstallUnchanged")} |
| Ubuntu under WSL2 | {secs(wsl.get("installSeconds"))} | {secs(wsl.get("firstToken"))} | Passed |

## Upgrade from {previous}

**Windows 11, in place, with a person's data** (`scripts/release-upgrade-acceptance.py`):
{up.get("checks") or "all"} checks passed. {previous}'s own installer (from its tag), a root, a
second person, Workbench with a chat, a pinned note and a document; then the
candidate installer over the same prefix, and everything back.

**Ubuntu under WSL2, Linux system install, the in-app update path**
(`scripts/updates-system-install-acceptance.sh`, `EP_FROM={previous}`): all checks passed.

## Recovery

`scripts/a7-recovery-acceptance.py` against the Windows candidate install: passed.
{timings}.

## Untested paths and limits

{limits or "- Not carried: the previous record has no such section."}
"""
    )
    return text


def candidate_table(r: Release, rows: str, files: dict[str, Any]) -> str:
    """The candidate's pins, how the console was built, and the package hashes."""
    pins = r["pins"]
    if LINE is None:
        where, ci = "the Edge console's source", "Every pin's own CI was green."
    else:
        where = f"ui's head on `{LINE['branch']}`"
        ci = f"Every repository that moved on the line passed its own CI there; the rest are {r['previous']}'s pins."
    return f"""| Component | Commit |
| --- | --- |
{rows}
| UI dist | `{pins["ui"]}` |
| Workbench dist (agent catalogue) | `{pins["workbench"]}` |
| site-host | `{pins["site-host"]}` |

The console was rebuilt from `{r["consoleSource"]}` ({where})
with `NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF={r.version}`; its {r["consoleFiles"]} static
files matched the export, which names `specs/{r.version}/scripts` and no `specs/main`
installer reference. The Workbench dist was built from `{r["workbenchSource"]}`. The
agent's site-host pin equals the installers' `PIN_SITE_HOST`;
`release-inputs.py --check` passed. {ci}

| File | SHA-256 |
| --- | --- |
""" + "\n".join(
        f"| {name} | `{info['sha256']}` |" for name, info in sorted(files.items())
    )


def patch_section(r: Release) -> str:
    """For a patch: the line, the security flag, and every commit on the line."""
    if LINE is None:
        return ""
    previous, branch = r["previous"], LINE["branch"]
    lines = [
        f"## Patch of {previous}",
        "",
        f"{r.version} patches {previous} from `{branch}` while `main` moved on. Each "
        f"repository is at {previous}'s pin, except for these commits on the line:",
        "",
    ]
    if r.security and r.state.get("olderLine"):
        lines[2] = (
            f"**Security fix.** Line `{branch}` is older than the latest release, "
            f"{r['latest']}; only a security fix patches an older line (`--security`). "
            + lines[2]
        )
    elif r.security:
        lines[2] = "**Security fix** (`--security`). " + lines[2]
    commits = r.state.get("lineCommits") or []
    if commits:
        lines += [
            "| Repository | Line commit | Picked from main | Subject |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {c['repo']} | `{c['commit']}` | "
            + (f"`{c['from']}`" if c["from"] else "on the line only")
            + f" | {c['subject'].replace('|', '/')} |"
            for c in commits
        ]
    else:
        lines.append("- None: the candidate is a rebuild of the same commits.")
    return "\n".join(lines) + "\n\n"


def rehearsal_record_text(r: Release) -> str:
    rows = "\n".join(
        f"| {name} | `{r['pins'][name]}` |" for name in ship.MANIFEST_REPOS
    )
    files = json.loads(
        (r.dir / "candidate" / "manifest.json").read_text(encoding="utf-8")
    )["files"]
    return (
        f"""# {r.version} release run (rehearsal)

rehearsal: no evidence run. `scripts/release.py --rehearsal` built this candidate,
specs `{r["candidate"]}`, on `{LINE["branch"] if LINE else "?"}` and stops after Release
qualification: no tag, image, GitHub release or website.

{patch_section(r)}## Candidate and scope

"""
        + candidate_table(r, rows, files)
        + "\n"
    )


def record(r: Release) -> None:
    # The evidence is the candidate's: anything but documentation since then (an Edge
    # ship from another session) means it no longer describes what would be tagged.
    moved = [
        p
        for p in git(SPECS, "diff", "--name-only", r["candidate"], "HEAD").splitlines()
        if not p.startswith("docs/")
    ]
    if moved:
        raise Stop(
            f"specs moved past the candidate ({', '.join(moved[:5])}); start again: --from candidate"
        )
    if r.rehearsal:
        write(SPECS / r.record, rehearsal_record_text(r))
        files = [r.record]
    else:
        if not r.notes.exists():
            raise NeedsNotes(
                f"write {r.notes.relative_to(SPECS).as_posix()} (shape: the previous release's notes), "
                f"then rerun; the record is written at {r.record}"
            )
        write(SPECS / r.record, record_text(r))
        files = [r.record, r.notes.relative_to(SPECS).as_posix()]
    words = "run record" if r.rehearsal else "run record and release notes"
    commit = r.commit(SPECS, files, f"{r.version}: {words}")
    push(SPECS, "HEAD", f"refs/heads/{LINE['branch']}" if LINE else "refs/heads/main")
    r["qualified"] = commit
    say(f"record committed: specs {commit[:7]}")


def qualify(r: Release) -> None:
    commit = r["qualified"]
    branch = f"release-candidate/{r.version}"
    push(SPECS, commit, f"refs/heads/{branch}", force=True)
    since = time.time()
    gh(
        "workflow",
        "run",
        "release-qualification.yml",
        "--ref",
        branch,
        "-f",
        f"release_tag={r.version}",
        "-f",
        f"acceptance_record={r.record}",
    )
    run_id = find_run("release-qualification.yml", commit, since)
    r["qualificationRun"] = run_id
    wait_run(run_id, 150)
    receipt = r.dir / "receipt"
    shutil.rmtree(receipt, ignore_errors=True)
    gh(
        "run",
        "download",
        str(run_id),
        "-n",
        "release-qualification",
        "-D",
        str(receipt),
    )
    report = json.loads((receipt / "qualification.json").read_text(encoding="utf-8"))
    if report["specsCommit"] != commit or report["releaseTag"] != r.version:
        raise Failed("the qualification receipt names another commit or version")
    r["qualifiedDigest"] = report["imageDigest"]


def tag(r: Release) -> None:
    commit = r["qualified"]
    if not git(SPECS, "tag", "-l", r.version):
        git(SPECS, "tag", "-a", r.version, "-m", f"Eugene Plexus {r.version}", commit)
    if git(SPECS, "rev-parse", f"{r.version}^{{commit}}") != commit:
        raise Failed(f"{r.version} names another commit")
    push(SPECS, f"refs/tags/{r.version}", f"refs/tags/{r.version}")
    try:
        push(SPECS, "", f"refs/heads/release-candidate/{r.version}", delete=True)
    except Refused:
        raise
    except Stop:
        pass  # the scratch branch is gone already (a rerun after this point)
    say(f"tagged {r.version} at {commit[:7]}")


def image(r: Release) -> None:
    since = time.time()
    gh(
        "workflow",
        "run",
        "container.yml",
        "--ref",
        r.version,
        "-f",
        f"release_tag={r.version}",
        "-f",
        f"qualification_run={r['qualificationRun']}",
        "-f",
        "publish=true",
    )
    run_id = find_run("container.yml", r["qualified"], since)
    wait_run(run_id, 30)
    digest = registry_digest(r.version)
    if digest != r["qualifiedDigest"]:
        raise Failed(
            f"{IMAGE}:{r.version} is {digest}, not the qualified {r['qualifiedDigest']}"
        )
    r["imageRun"] = run_id
    say(f"{IMAGE}:{r.version} is {digest}")


def release_body(r: Release) -> str:
    notes = r.notes.read_text(encoding="utf-8")
    intro = next(
        (
            p.strip()
            for p in notes.split("\n\n")[1:]
            if p.strip() and not p.startswith("#")
        ),
        "",
    )
    heads = [
        h
        for h in re.findall(r"(?m)^## (.+)$", notes)
        if h not in ("Other changes", "Updating")
    ]
    base = f"https://github.com/{ORG}/specs/blob/{r.version}"
    return "\n".join(
        [
            intro,
            "",
            *[f"- {h}" for h in heads],
            "",
            f"[Release notes]({base}/docs/releases/{r.version}.md) · [Install](https://eugeneplexus.com/install/) · "
            f"[Release checks]({base}/{r.record})",
            "",
            "Assets: `install.sh` and `install.ps1` (installers pinned to this release), `manifest.json` "
            "(component pins and hashes), `requirements.lock`, `SHA256SUMS`.",
            "",
            f"Verified container digest: `{r['qualifiedDigest']}`",
            "",
        ]
    )


def publish(r: Release) -> None:
    if git(SPECS, "rev-parse", f"{r.version}^{{commit}}") != r["qualified"]:
        raise Failed(
            f"{r.version} does not name the qualified commit {r['qualified'][:7]}"
        )
    final = artifacts(r, r.version, "final")
    # What is published must be what the evidence ran: the same pins and the same
    # installer and lock bytes as the candidate package (only manifest.json names
    # the tagged commit).
    tested = json.loads(
        (r.dir / "candidate" / "manifest.json").read_text(encoding="utf-8")
    )
    packaged = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
    pins = {k: v for k, v in r["pins"].items() if k not in ("workbench", "site-host")}
    if packaged["components"] != tested["components"] or packaged["components"] != pins:
        raise Failed("the tag's package pins differ from the tested candidate's")
    if packaged.get("siteHost") != tested.get("siteHost"):
        raise Failed(
            "the tag's package names another site-host than the tested candidate"
        )
    for name in ("install.sh", "install.ps1", "requirements.lock"):
        if sha256(final / name) != sha256(r.dir / "candidate" / name):
            raise Failed(f"the tag's {name} differs from the tested candidate's")
    body = r.dir / "release-body.md"
    write(body, release_body(r))
    assets = [
        str(final / n)
        for n in (
            "install.ps1",
            "install.sh",
            "manifest.json",
            "requirements.lock",
            "SHA256SUMS",
        )
    ]
    # Only the newest line's release is Latest: an older line's security patch
    # must not take the updaters and the website off the newest line.
    older = older_line_now(r)
    try:
        gh("release", "view", r.version)
        exists = True
    except Stop:
        exists = False
    if not exists:
        gh(
            "release",
            "create",
            r.version,
            "--verify-tag",
            "--latest=false" if older else "--latest",
            "--title",
            f"Eugene Plexus {r.version}",
            "--notes-file",
            str(body),
            *assets,
        )
    view = json.loads(
        gh("release", "view", r.version, "--json", "isDraft,isPrerelease,url,assets")
    )
    if view["isDraft"] or view["isPrerelease"]:
        raise Failed(f"{view['url']} is a draft or prerelease")
    names = {asset["name"] for asset in view["assets"]}
    if names != {Path(a).name for a in assets}:
        raise Failed(
            f"{view['url']} carries {sorted(names)}, not the five release assets"
        )
    sums: dict[str, str] = {}
    for line in (final / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.strip().lstrip("*")] = digest
    got = r.dir / "downloaded"
    shutil.rmtree(got, ignore_errors=True)
    got.mkdir()
    gh("release", "download", r.version, "-D", str(got))
    for asset in view["assets"]:
        name = asset["name"]
        local = sha256(got / name)
        if name != "SHA256SUMS" and (
            sums.get(name) != local or asset.get("digest") != f"sha256:{local}"
        ):
            raise Failed(
                f"{name}: downloaded {local}, listed {sums.get(name)}, GitHub {asset.get('digest')}"
            )
    if (got / "SHA256SUMS").read_bytes() != (final / "SHA256SUMS").read_bytes():
        raise Failed("the published SHA256SUMS differs from the packaged one")
    latest = gh_api(f"repos/{ORG}/specs/releases/latest")["tag_name"]
    expected = r["latest"] if older else r.version
    if latest != expected:
        raise Failed(f"GitHub's latest release is {latest}, not {expected}")
    r["releaseUrl"] = view["url"]
    say(f"published {view['url']}")


def older_line_now(r: Release) -> bool:
    """Whether a newer release than this patch is GitHub's Latest now. Preflight's
    answer can be stale: a newer line can ship while a run waits for its notes,
    and the patch must then not take Latest, or the website, back from it."""
    if LINE is None:
        return False
    latest = gh_api(f"repos/{ORG}/specs/releases/latest")["tag_name"]
    older = latest != r.version and version_key(latest) > version_key(r.version)
    if older and not r.state.get("olderLine"):
        say(
            f"{latest} became Latest while this ran: {r.version} is published "
            f"without Latest, and the website keeps {latest}"
        )
    if older:
        r["latest"] = latest
    r["olderLine"] = older
    return older


def website(r: Release) -> None:
    if older_line_now(r):
        say(
            "website: unchanged; it offers the newest line, and this patches an older one"
        )
        return
    data = SITE / "src" / "data"
    if git(SITE, "rev-parse", "--abbrev-ref", "HEAD") != "main" or git(
        SITE, "status", "--porcelain", "--untracked-files=no"
    ):
        raise Stop("website: the checkout must be clean on main")
    git(SITE, "pull", "-q", "--ff-only")
    commit = r["qualified"]
    new = json.loads((r.dir / "final" / "manifest.json").read_text(encoding="utf-8"))
    current = json.loads((data / "alpha-release.json").read_text(encoding="utf-8"))
    if current["version"] != r.version:
        archive = json.loads(
            (data / "archived-releases.json").read_text(encoding="utf-8")
        )
        if all(entry["version"] != current["version"] for entry in archive):
            archive = [current, *archive]
        write(data / "archived-releases.json", json.dumps(archive, indent=2) + "\n")
        new["offlineRemoval"] = current.get("offlineRemoval", True)
        write(data / "alpha-release.json", json.dumps(new, indent=2) + "\n")
        revision = json.loads((data / "docs-revision.json").read_text(encoding="utf-8"))
        revision["commit"] = commit
        write(data / "docs-revision.json", json.dumps(revision, indent=2) + "\n")
        recovery = SITE / "src" / "content" / "recovery.md"
        write(
            recovery,
            re.sub(
                r"specs/blob/[a-f0-9]{40}/scripts/recovery\.py",
                f"specs/blob/{commit}/scripts/recovery.py",
                recovery.read_text(encoding="utf-8"),
            ),
        )
    npm = shutil.which("npm") or "npm"
    for args in (("run", "check"), ("test",)):
        code, _ = _site(npm, args, r)
        if code != 0:
            raise Failed(
                f"website: npm {' '.join(args)} failed; log {r.dir / 'logs' / ('website-' + args[-1] + '.log')}"
            )
    for name, info in new["files"].items():
        built = SITE / "dist" / "releases" / r.version / name
        if not built.exists() or sha256(built) != info["sha256"]:
            raise Failed(
                f"website: the built releases/{r.version}/{name} does not match the release"
            )
    files = [
        "src/data/alpha-release.json",
        "src/data/archived-releases.json",
        "src/data/docs-revision.json",
        "src/content/recovery.md",
    ]
    other = [
        name
        for name in git(SITE, "diff", "--name-only", "HEAD").splitlines()
        if name not in files
    ]
    if other:
        raise Failed(
            f"website: the check or build changed tracked files: {', '.join(other)}"
        )
    r.commit(SITE, files, f"Release {r.version}")
    git(SITE, "fetch", "-q", "origin", "main")
    if not ship.is_ancestor(SITE, "HEAD", "origin/main"):
        push(SITE, "HEAD", "refs/heads/main")
    head = git(SITE, "rev-parse", "HEAD")
    since = time.time()
    gh("workflow", "run", "pages.yml", "--ref", "main", repo="website")
    run_id = find_run("pages.yml", head, since, repo="website")
    wait_run(run_id, 30, repo="website")
    for name, info in new["files"].items():
        url = f"https://eugeneplexus.com/releases/{r.version}/{name}"
        if hashlib.sha256(fetch_url(url)).hexdigest() != info["sha256"]:
            raise Failed(f"{url} does not match the release")
    if f"releases/{r.version}/install.ps1".encode() not in fetch_url(
        "https://eugeneplexus.com/install/"
    ):
        raise Failed("the live install page does not name this release's installer")
    say("website deployed and its installers match")


def _site(npm: str, args: tuple[str, ...], r: Release) -> tuple[int, str]:
    log = r.dir / "logs" / f"website-{args[-1]}.log"
    say(f"website: npm {' '.join(args)}")
    with log.open("w", encoding="utf-8", newline="\n") as stream:
        done = subprocess.run(
            [npm, *args],
            cwd=SITE,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=3600,
        )
    return done.returncode, log.read_text(encoding="utf-8", errors="replace")


def close(r: Release) -> None:
    older = bool(r.state.get("olderLine"))
    home = Path(LINE["root"]) / "specs" if LINE else SPECS  # the person's own checkout
    previous_state = next(
        (
            path
            for path in (
                spec / "docs" / "private" / f"release-{r['previous']}" / "state.json"
                for spec in (SPECS, home)
            )
            if path.exists()
        ),
        SPECS / "docs" / "private" / f"release-{r['previous']}" / "state.json",
    )
    prefix = None
    if previous_state.exists():
        prefix = (
            (
                json.loads(previous_state.read_text(encoding="utf-8")).get("evidence")
                or {}
            )
            .get("windows", {})
            .get("prefix")
        )
    prefix = r.state.get("previousInstall") or prefix
    if not prefix:  # a release run before release.py: its Windows install under %TEMP%
        compact = r["previous"].replace(".", "")
        found = sorted(
            {*TEMP.glob(f"ep-{r['previous']}-win-*"), *TEMP.glob(f"ep-{compact}-win-*")}
        )
        prefix = str(found[-1] / "install") if found else None
    check = "No installed previous-version agent was available, so its update check was not run."
    if older:
        check = (
            "This patches an older line and is not Latest, so an installed agent's "
            "update check does not offer it; none was run."
        )
    elif prefix and (Path(prefix) / "venv" / "Scripts" / "python.exe").exists():
        answer = subprocess.run(
            [
                str(Path(prefix) / "venv" / "Scripts" / "python.exe"),
                "-I",
                "-c",
                "from eugene_plexus_agent import updates; print(updates.newest_release().ref)",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        ref = answer.stdout.strip().splitlines()[-1] if answer.stdout.strip() else ""
        if ref != r.version:
            raise Failed(
                f"the installed {r['previous']} agent's update check found {ref or answer.stderr[-500:]}"
            )
        check = (
            f"The installed {r['previous']} agent's own update check (`updates.newest_release()`, "
            f"read-only) found {r.version}; it installed nothing."
        )
    digest = r["qualifiedDigest"]
    if older:
        latest = f"is published, not as Latest ({r['latest']} stays Latest), neither draft nor"
        site = (
            "The website was not changed: it offers the newest line. This release is on "
            "GitHub only."
        )
    else:
        latest = "is published as Latest, neither draft nor"
        site = (
            "The website's release data passed its check, build and browser tests and was\n"
            "deployed; the live installers match the release's hashes."
        )
    section = f"""
## Publication

The annotated `{r.version}` tag names `{r["qualified"]}`, the qualified commit.
[Release qualification {r["qualificationRun"]}](https://github.com/{ORG}/specs/actions/runs/{r["qualificationRun"]})
passed on it before the tag existed; [Container image {r["imageRun"]}](https://github.com/{ORG}/specs/actions/runs/{r["imageRun"]})
retagged its qualified image without rebuilding. An anonymous registry request for
`{IMAGE}:{r.version}` returned `{digest}`.

[The release]({r["releaseUrl"]}) {latest}
prerelease, at Troy's request for this release. Every asset was downloaded after
publication and matched both GitHub's digests and the local package. {check}

{site}
"""
    text = (SPECS / r.record).read_text(encoding="utf-8")
    if "## Publication" not in text:
        marker = "## Untested paths and limits"
        write(
            SPECS / r.record, text.replace(marker, section.strip() + "\n\n" + marker, 1)
        )
        r.commit(SPECS, [r.record], f"{r.version} run record: publication")
    if LINE is None:
        git(SPECS, "fetch", "-q", "origin", "main")
        if not ship.is_ancestor(
            SPECS, "HEAD", "origin/main"
        ):  # also a rerun after a failed push
            git(SPECS, "pull", "-q", "--rebase", "origin", "main")
            push(SPECS, "HEAD", "refs/heads/main")
    else:
        branch = LINE["branch"]
        git(SPECS, "fetch", "-q", "origin", branch)
        if not ship.is_ancestor(SPECS, "HEAD", f"origin/{branch}"):
            push(SPECS, "HEAD", f"refs/heads/{branch}")
        push_docs_to_main(r)
    say(f"{r.version} released: {r['releaseUrl']}")


def push_docs_to_main(r: Release) -> None:
    """The notes and the record (with its publication section) onto specs main
    as one documentation-only commit, built from the line without a checkout of
    main; the push guard checks it again. Main moving meanwhile is retried."""
    assert LINE is not None
    files = [r.record, r.notes.relative_to(SPECS).as_posix()]
    for _ in range(3):
        git(SPECS, "fetch", "-q", "origin", "main")
        base = git(SPECS, "rev-parse", "origin/main")
        with tempfile.TemporaryDirectory() as scratch:
            env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
            git(SPECS, "read-tree", base, env=env)
            for name in files:
                blob = git(SPECS, "rev-parse", f"HEAD:{name}")
                git(
                    SPECS,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{name}",
                    env=env,
                )
            tree = git(SPECS, "write-tree", env=env)
            if tree == git(SPECS, "rev-parse", f"{base}^{{tree}}"):
                say("specs main holds the notes and the record already")
                return
            message = Path(scratch) / "message"
            write(
                message,
                f"{r.version}: release notes and run record, from {LINE['branch']}\n\n"
                + ship.trailers(r.co_author, SPECS)
                + "\n",
            )
            commit = git(SPECS, "commit-tree", tree, "-p", base, "-F", str(message))
        try:
            push(SPECS, commit, "refs/heads/main", docs_to_main=True)
        except Refused:
            raise
        except Stop as stop:
            # Retry only a race: main moved after the fetch. Anything else (a
            # permission error, a refusing hook, the network) is the cause.
            git(SPECS, "fetch", "-q", "origin", "main")
            if git(SPECS, "rev-parse", "origin/main") == base:
                raise Failed(
                    "specs: the notes and the record did not reach main, and main "
                    f"did not move: {stop}"
                ) from None
            say("specs main moved meanwhile; building on its new head")
            continue
        say(f"specs main {commit[:7]}: the notes and the record")
        return
    raise Failed(
        "specs main moved three times while the notes were pushed; rerun --from close"
    )


# --- driver ------------------------------------------------------------------


def open_line(
    version: str, *, rehearsal: bool, security: bool
) -> dict[str, Any] | None:
    """Patch mode when the specs checkout is on a release line (a worktree made
    by release-line.py open): its line.json, branch and version. None on main."""
    branch = git(SPECS, "rev-parse", "--abbrev-ref", "HEAD")
    match = LINE_BRANCH.fullmatch(branch)
    if not match:
        if rehearsal or security:
            raise Stop(
                "--security and --rehearsal are for a release line: run from its specs "
                "worktree (scripts/release-line.py open vX.Y)"
            )
        return None
    name = f"v{match[2]}.{match[3]}"
    if (match[1] == "rehearsal") != rehearsal:
        raise Stop(
            f"{branch} is a rehearsal line: run with --rehearsal"
            if rehearsal is False
            else f"--rehearsal runs on a rehearsal line: release-line.py open {name} --rehearsal"
        )
    file = SPECS.parent / "line.json"
    if not file.is_file():
        raise Stop(f"{file} is missing: open the line with release-line.py open {name}")
    line = json.loads(file.read_text(encoding="utf-8"))
    if line.get("branch") != branch:
        raise Stop(f"{file} is for {line.get('branch')}, not {branch}")
    return {
        **line,
        "name": name,
        "key": (int(match[2]), int(match[3])),
        "version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("version", help="vX.Y.Z")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the preflight checks and list the phases",
    )
    parser.add_argument(
        "--from", dest="start", choices=PHASES, help="redo from this phase"
    )
    parser.add_argument(
        "--previous-install",
        type=Path,
        help="an installed previous-release prefix for the read-only update check",
    )
    parser.add_argument("--co-author", default=os.environ.get("EP_SHIP_CO_AUTHOR"))
    parser.add_argument(
        "--security",
        action="store_true",
        help="a security fix: on a release line, the only patch an older line takes; "
        "the record names it",
    )
    parser.add_argument(
        "--rehearsal",
        action="store_true",
        help="on a rehearsal/vX.Y line: vX.Y.Z-rehearsal.N, preflight to qualify only; "
        "no tag, image, GitHub release or website",
    )
    args = parser.parse_args()
    for name in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[
            name
        ]  # an ambient config file would point a harness at the live install
    global LINE, SITE
    phase = "preflight"
    try:
        LINE = open_line(args.version, rehearsal=args.rehearsal, security=args.security)
        if LINE is not None:
            SITE = Path(LINE["root"]) / "website"
        r = Release(
            args.version,
            args.co_author,
            security=args.security,
            rehearsal=args.rehearsal,
        )
        for flag in ("security", "rehearsal"):
            if flag in r.state and r.state[flag] != getattr(args, flag):
                raise Stop(
                    f"this release ran {'with' if r.state[flag] else 'without'} --{flag}; "
                    "rerun it the same way"
                )
        r.persist = not args.dry_run
        if args.previous_install:
            r["previousInstall"] = str(args.previous_install)
        if args.start:
            r.reopen(args.start)
        phases = [p for p in PHASES if not r.rehearsal or p in REHEARSAL_PHASES]
        check = preflight_patch if LINE is not None else preflight
        if args.dry_run:
            check(r, dry_run=True)
            for phase in phases:
                print(f"  {phase:10s} {'done' if r.done(phase) else 'to run'}")
            return 0
        for phase in phases:
            if r.done(phase):
                continue
            say(f"== {phase}")
            if phase == "preflight":
                check(r, dry_run=False)
            elif phase == "candidate" and LINE is not None:
                candidate_patch(r)
            elif phase == "artifacts":
                artifacts(r, r["candidate"], "candidate")
            else:
                globals()[phase](r)
            r.mark(phase)
        if r.rehearsal:
            say(f"rehearsal {r.version} qualified; no tag, image, release or website")
    except NeedsNotes as need:
        print(f"NEEDS NOTES: {need}", file=sys.stderr)
        return 3
    except Stop as stop:
        print(f"NOT READY: {stop}", file=sys.stderr)
        return 2
    except (
        Failed,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        StopIteration,
        OSError,
        KeyError,
        ValueError,
    ) as failure:
        print(f"FAILED in {phase}: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
