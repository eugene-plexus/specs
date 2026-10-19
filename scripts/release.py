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
VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
ORG = "eugene-plexus"
IMAGE = "ghcr.io/eugene-plexus/control-plane"
MODEL = Path(r"D:\eugene-demo\models\gemma-4-E4B-it-Q4_K_M.gguf")
WSL_PYTHON = "/mnt/d/py/eugene-plexus/agent/.venv-wsl/bin/python"
TEMP = Path(tempfile.gettempdir())
UI_STATIC = "python/eugene_plexus_ui/static"
SITE = ROOT / "website"


class Failed(Exception):
    """A phase ran and something did not pass."""


class NeedsNotes(Exception):
    """The release notes are the session's to write."""


# --- small helpers -----------------------------------------------------------


def say(text: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {text}", flush=True)


def gh(*args: str, repo: str = "specs") -> str:
    return ship.run(SPECS, "gh", *args, "-R", f"{ORG}/{repo}", quiet=True)


def gh_api(path: str) -> Any:
    return json.loads(ship.run(SPECS, "gh", "api", path, quiet=True) or "null")


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


# --- state -------------------------------------------------------------------


class Release:
    def __init__(self, version: str, co_author: str | None) -> None:
        self.version = version
        self.co_author = co_author
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
                log = ship.run(
                    SPECS,
                    "gh",
                    "run",
                    "view",
                    str(run_id),
                    "--log-failed",
                    "-R",
                    f"{ORG}/{repo}",
                    quiet=True,
                )
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
    data = json.loads(
        ship.run(SPECS, "gh", "api", "graphql", "-f", f"query={query}", quiet=True)
    )
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


def _imports(python: str) -> bool:
    return (
        subprocess.run(
            [python, "-c", "import httpx, yaml"], capture_output=True
        ).returncode
        == 0
    )


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
    git(ui, "fetch", "-q", "origin", "dist")
    with tempfile.TemporaryDirectory() as scratch:
        env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(ui, "read-tree", source, env=env)
        git(ui, "add", "-f", "--", UI_STATIC, env=env)
        tree = git(ui, "write-tree", env=env)
        message = Path(scratch) / "message"
        write(
            message,
            f"Build {r.version} console with release-pinned machine setup\n\n"
            f"built-from: eugene-plexus/ui@{source}\nNEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF={r.version}\n\n"
            + ship.trailers(r.co_author, ui)
            + "\n",
        )
        dist = git(
            ui,
            "commit-tree",
            tree,
            "-p",
            "origin/dist",
            "-p",
            source,
            "-F",
            str(message),
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
    git(ui, "push", "-q", "origin", f"{dist}:refs/heads/dist")
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
    git(SPECS, "push", "-q", "origin", "HEAD:main")
    r["candidate"] = commit
    r["pins"] = pins
    r["consoleSource"] = source
    r["consoleFiles"] = count
    r["workbenchSource"] = main_parent(ROOT / "workbench", pins["workbench"])
    say(f"candidate specs {commit[:7]} pushed")


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

## Candidate and scope

| Component | Commit |
| --- | --- |
{rows}
| UI dist | `{pins["ui"]}` |
| Workbench dist (agent catalogue) | `{pins["workbench"]}` |
| site-host | `{pins["site-host"]}` |

The console was rebuilt from `{r["consoleSource"]}` (the Edge console's source)
with `NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF={r.version}`; its {r["consoleFiles"]} static
files matched the export, which names `specs/{r.version}/scripts` and no `specs/main`
installer reference. The Workbench dist was built from `{r["workbenchSource"]}`. The
agent's site-host pin equals the installers' `PIN_SITE_HOST`;
`release-inputs.py --check` passed. Every pin's own CI was green.

| File | SHA-256 |
| --- | --- |
"""
        + "\n".join(
            f"| {name} | `{info['sha256']}` |" for name, info in sorted(files.items())
        )
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
    if not r.notes.exists():
        raise NeedsNotes(
            f"write {r.notes.relative_to(SPECS).as_posix()} (shape: the previous release's notes), "
            f"then rerun; the record is written at {r.record}"
        )
    write(SPECS / r.record, record_text(r))
    files = [r.record, r.notes.relative_to(SPECS).as_posix()]
    commit = r.commit(SPECS, files, f"{r.version}: run record and release notes")
    git(SPECS, "push", "-q", "origin", "HEAD:main")
    r["qualified"] = commit
    say(f"record committed: specs {commit[:7]}")


def qualify(r: Release) -> None:
    commit = r["qualified"]
    branch = f"release-candidate/{r.version}"
    git(SPECS, "push", "-q", "-f", "origin", f"{commit}:refs/heads/{branch}")
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
    git(SPECS, "push", "-q", "origin", f"refs/tags/{r.version}")
    # The scratch branch may be gone already (a rerun after this point).
    subprocess.run(
        ["git", "push", "-q", "origin", "--delete", f"release-candidate/{r.version}"],
        cwd=SPECS,
        capture_output=True,
    )
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
    existing = subprocess.run(
        ["gh", "release", "view", r.version, "-R", f"{ORG}/specs"], capture_output=True
    )
    if existing.returncode != 0:
        gh(
            "release",
            "create",
            r.version,
            "--verify-tag",
            "--latest",
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
    if latest != r.version:
        raise Failed(f"GitHub's latest release is {latest}")
    r["releaseUrl"] = view["url"]
    say(f"published {view['url']}")


def website(r: Release) -> None:
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
        git(SITE, "push", "-q", "origin", "HEAD:main")
    head = git(SITE, "rev-parse", "HEAD")
    since = time.time()
    gh("workflow", "run", "pages.yml", "--ref", "main", repo="website")
    run_id = find_run("pages.yml", head, since, repo="website")
    wait_run(run_id, 30, repo="website")
    for name, info in new["files"].items():
        with urllib.request.urlopen(
            f"https://eugeneplexus.com/releases/{r.version}/{name}", timeout=60
        ) as reply:
            if hashlib.sha256(reply.read()).hexdigest() != info["sha256"]:
                raise Failed(
                    f"https://eugeneplexus.com/releases/{r.version}/{name} does not match the release"
                )
    with urllib.request.urlopen(
        "https://eugeneplexus.com/install/", timeout=60
    ) as reply:
        if f"releases/{r.version}/install.ps1".encode() not in reply.read():
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
    previous_state = (
        SPECS / "docs" / "private" / f"release-{r['previous']}" / "state.json"
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
    if prefix and (Path(prefix) / "venv" / "Scripts" / "python.exe").exists():
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
    section = f"""
## Publication

The annotated `{r.version}` tag names `{r["qualified"]}`, the qualified commit.
[Release qualification {r["qualificationRun"]}](https://github.com/{ORG}/specs/actions/runs/{r["qualificationRun"]})
passed on it before the tag existed; [Container image {r["imageRun"]}](https://github.com/{ORG}/specs/actions/runs/{r["imageRun"]})
retagged its qualified image without rebuilding. An anonymous registry request for
`{IMAGE}:{r.version}` returned `{digest}`.

[The release]({r["releaseUrl"]}) is published as Latest, neither draft nor
prerelease, at Troy's request for this release. Every asset was downloaded after
publication and matched both GitHub's digests and the local package. {check}

The website's release data passed its check, build and browser tests and was
deployed; the live installers match the release's hashes.
"""
    text = (SPECS / r.record).read_text(encoding="utf-8")
    if "## Publication" not in text:
        marker = "## Untested paths and limits"
        write(
            SPECS / r.record, text.replace(marker, section.strip() + "\n\n" + marker, 1)
        )
        r.commit(SPECS, [r.record], f"{r.version} run record: publication")
    git(SPECS, "fetch", "-q", "origin", "main")
    if not ship.is_ancestor(
        SPECS, "HEAD", "origin/main"
    ):  # also a rerun after a failed push
        git(SPECS, "pull", "-q", "--rebase", "origin", "main")
        git(SPECS, "push", "-q", "origin", "HEAD:main")
    say(f"{r.version} released: {r['releaseUrl']}")


# --- driver ------------------------------------------------------------------


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
    args = parser.parse_args()
    for name in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[
            name
        ]  # an ambient config file would point a harness at the live install
    r = Release(args.version, args.co_author)
    r.persist = not args.dry_run
    if args.previous_install:
        r["previousInstall"] = str(args.previous_install)
    if args.start:
        r.reopen(args.start)
    phase = "preflight"
    try:
        if args.dry_run:
            preflight(r, dry_run=True)
            for phase in PHASES:
                print(f"  {phase:10s} {'done' if r.done(phase) else 'to run'}")
            return 0
        for phase in PHASES:
            if r.done(phase):
                continue
            say(f"== {phase}")
            if phase == "preflight":
                preflight(r, dry_run=False)
            elif phase == "artifacts":
                artifacts(r, r["candidate"], "candidate")
            else:
                globals()[phase](r)
            r.mark(phase)
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
