"""A patch release cut end to end, offline, against bare file:// repositories.

    python scripts/release-patch-acceptance.py              # build, run, check, clean up
    python scripts/release-patch-acceptance.py --keep DIR   # keep the fixture in DIR

It builds bare repositories for specs, the nine components and the website.
Each component is tagged at its v1.2.0 pin, and its `main` is three commits
past it (a fix, a feature, and a change that needs the feature; gateway's
feature adds a dependency). ui and Workbench have `dist` branches, specs has
`edge`, and v1.2.0's specs carries older release tooling than `main` does.
Then, as a person would:

1. a rehearsal: `release-line.py open v1.2 --rehearsal`, `release.py
   v1.2.1-rehearsal.1 --rehearsal` (preflight to qualify only), and
   `release-line.py close v1.2 --rehearsal --delete-branches`;
2. `release-line.py open v1.2`, then `pick`: three fixes from main, one of
   them twice, a commit that is not on main, and one that conflicts;
3. `release.py v1.2.2` (refused), then `release.py v1.2.1` through every phase,
   writing the release notes when it stops for them, then `release-line.py
   close v1.2`;
4. a security fix on the older line: `open v1.1` (refused), `open v1.1
   --security`, `release.py v1.1.1` (refused), `release.py v1.1.1 --security`:
   published with --latest=false, the website untouched, the record saying so;
5. `release.py v1.2.2` stops for its notes, v1.3.0 becomes Latest meanwhile,
   and the resumed run publishes v1.2.2 without taking Latest back.

release.py runs in its own process, from the line's specs worktree, with the
tooling that `open` brought onto the line. A recording stand-in answers its
GitHub calls (`release.run_gh`); stubs stand in for the registry, the evidence
runs on this machine, the front-end builds and the live website. A real `gh`
cannot run: the environment has no GitHub token and an empty gh configuration.

Checks: every main, dist and edge ref is unchanged, except one
documentation-only commit on specs main; every push is to the line's own refs;
tag v1.2.1 names the line's record commit; the installers pin v1.2.0's commits
except the picked repositories, which are at their line heads with the `-x`
trailer; the stand-in saw one `release create`. Exit 0 when every check
passes, 1 otherwise. The fixture classes are also the tests' (test_release.py,
test_release_line.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
ORG = "eugene-plexus"
TAGGED = "v1.2.0"
# Built in this order: the agent pins Workbench and the site host.
COMPONENTS = (
    "site-host",
    "workbench",
    "ui",
    "control",
    "gateway",
    "library",
    "store",
    "inference-driver",
    "tool-driver",
    "agent",
)
MANIFEST_REPOS = (
    "agent",
    "control",
    "gateway",
    "library",
    "store",
    "inference-driver",
    "tool-driver",
)
# What `open` brings onto a line from main; v1.2.0 has older copies.
TOOLING = (
    "scripts/release.py",
    "scripts/ship.py",
    "scripts/release-line.py",
    ".github/workflows/release-qualification.yml",
    ".github/workflows/container.yml",
)
SUPPORT = (
    "scripts/release-inputs.py",
    "scripts/release-artifacts.py",
    "scripts/ci_plan.py",
)
UI_STATIC = "python/eugene_plexus_ui/static"
WB_STATIC = "src/eugene_plexus_workbench/static"
CATALOGUE = "src/eugene_plexus_agent/apps_catalogue.yaml"
SITE_HOST_PY = "src/eugene_plexus_agent/site_host.py"
DEPENDENCIES = ["httpx>=0.27"]
AGENT_SERVICE = "pywin32>=306; sys_platform == 'win32'"
LOCK = (
    "hatchling==1.27.0 \\\n    --hash=sha256:" + "1" * 64 + "\n"
    "httpx==0.28.1 \\\n    --hash=sha256:" + "2" * 64 + "\n"
)
INSTALL_SH = """#!/bin/sh
# The fixture's installer: pins and the generated dependency block only.
PY_VERSION=3.12
UV_MINIMUM=0.12.18
PIN_AGENT={zero}
PIN_CONTROL={zero}
PIN_GATEWAY={zero}
PIN_LIBRARY={zero}
PIN_STORE={zero}
PIN_DRIVER={zero}
PIN_TOOL_DRIVER={zero}
PIN_UI={zero}
PIN_SITE_HOST={site_host}
# BEGIN GENERATED DEPENDENCIES
# END GENERATED DEPENDENCIES
"""
INSTALL_PS1 = """# The fixture's installer: pins and the generated dependency block only.
$PyVersion = "3.12"
$UvMinimum = [version]"0.12.18"
$Pins = @{{
    "agent" = "{zero}"
    "control" = "{zero}"
    "gateway" = "{zero}"
    "library" = "{zero}"
    "store" = "{zero}"
    "inference-driver" = "{zero}"
    "tool-driver" = "{zero}"
    "ui" = "{zero}"
}}
# BEGIN GENERATED DEPENDENCIES
# END GENERATED DEPENDENCIES
"""
GITCONFIG = """[user]
\tname = Patch Fixture
\temail = fixture@example.invalid
[init]
\tdefaultBranch = main
[commit]
\tgpgsign = false
[tag]
\tgpgsign = false
[core]
\tautocrlf = false
[advice]
\tdetachedHead = false
"""


def _writable(function: Any, path: str, _: Any) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove_tree(path: Path) -> None:
    """Delete a fixture; git's object files are read-only on Windows."""
    if path.exists():
        shutil.rmtree(path, onexc=_writable)


def hermetic_env(root: Path) -> dict[str, str]:
    """No GitHub token, no gh login, no user or system git configuration, no
    Eugene Plexus variables: a stray real `gh` or a global hook cannot act."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("EUGENE_PLEXUS_", "GH_", "GITHUB_", "GIT_"))
    }
    config = root / "gitconfig"
    config.write_text(GITCONFIG, encoding="utf-8", newline="\n")
    (root / "gh-config").mkdir(exist_ok=True)
    env.update(
        GIT_CONFIG_GLOBAL=str(config),
        GIT_CONFIG_NOSYSTEM="1",
        GH_CONFIG_DIR=str(root / "gh-config"),
        GH_HOST="gh-stand-in.invalid",
        GH_PROMPT_DISABLED="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
    )
    return env


def pyproject(name: str, dependencies: list[str]) -> str:
    listed = ", ".join(json.dumps(d) for d in dependencies)
    text = f'[project]\nname = "eugene-plexus-{name}"\nversion = "0.0.0"\ndependencies = [{listed}]\n'
    if name == "agent":
        text += f"\n[project.optional-dependencies]\nservice = [{json.dumps(AGENT_SERVICE)}]\n"
    return (
        text
        + '\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )


def catalogue(pin: str) -> str:
    return (
        "- id: workbench\n"
        "  name: Workbench\n"
        f"  source: https://github.com/{ORG}/workbench/archive/{pin}.tar.gz\n"
        f"  version: {pin}\n"
        "  package: eugene-plexus-workbench\n"
    )


def package(name: str) -> str:
    return "eugene_plexus_" + name.replace("-", "_")


class Fixture:
    """Bare repositories (`bare/`), the person's checkouts of them (`main/`, the
    siblings release-line.py finds) and the release lines (`lines/`)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.bare = self.root / "bare"
        self.main = self.root / "main"
        self.lines = self.root / "lines"
        for folder in (self.bare, self.main, self.lines):
            folder.mkdir(parents=True, exist_ok=True)
        self.env = hermetic_env(self.root)
        self.pins: dict[
            str, str
        ] = {}  # what v1.2.0 pins (dist commits for ui, Workbench)
        self.source: dict[str, str] = {}  # the source commit of each pin
        self.fix: dict[str, str] = {}  # on main past the pin: picked
        self.feature: dict[str, str] = {}  # after it; gateway's adds a dependency
        self.later: dict[str, str] = {}  # main's head; conflicts without the feature
        self.side: dict[str, str] = {}  # on another branch, never on main
        self.moved_dist: dict[str, str] = {}  # dist built from main's head

    # --- running things -------------------------------------------------

    def git(
        self,
        cwd: Path,
        *args: str,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> str:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env or self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and done.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} in {cwd}: {done.stdout}{done.stderr}"
            )
        return done.stdout.strip()

    def python(self, script: Path, *args: str, cwd: Path) -> tuple[int, str]:
        done = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=cwd,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        return done.returncode, done.stdout + done.stderr

    def line(self, *args: str) -> tuple[int, str]:
        """release-line.py, run from the person's specs checkout."""
        specs = self.main / "specs"
        return self.python(
            specs / "scripts" / "release-line.py",
            *args,
            "--lines",
            str(self.lines),
            cwd=specs,
        )

    def release(
        self, specs: Path, *args: str, stop_after: str | None = None
    ) -> tuple[int, str]:
        """release.py from a line's specs worktree, with GitHub and this machine stood in."""
        extra = ["--stop-after", stop_after] if stop_after else []
        return self.python(
            Path(__file__).resolve(),
            "--inner",
            str(self.root),
            str(specs),
            *extra,
            "--",
            *args,
            cwd=specs,
        )

    # --- reading the repositories -----------------------------------------

    def refs(self) -> dict[str, dict[str, str]]:
        found = {}
        for bare in sorted(self.bare.glob("*.git")):
            listing = self.git(
                bare, "for-each-ref", "--format=%(refname) %(objectname)"
            )
            found[bare.stem] = dict(line.split(" ", 1) for line in listing.splitlines())
        return found

    def pushes(self) -> list[tuple[str, str, str, str]]:
        """(repository, ref, old, new) for every push received since the build."""
        out = []
        for bare in sorted(self.bare.glob("*.git")):
            log = bare / "pushes.log"
            if log.exists():
                for line in log.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        old, new, ref = line.split()
                        out.append((bare.stem, ref, old, new))
        return out

    def reset_pushes(self) -> None:
        for log in self.bare.glob("*.git/pushes.log"):
            log.unlink()

    def rev(self, repo: str, ref: str) -> str:
        return self.git(
            self.bare / f"{repo}.git", "rev-parse", "--verify", f"{ref}^{{commit}}"
        )

    def show(self, repo: str, ref: str) -> str:
        return self.git(self.bare / f"{repo}.git", "show", ref)

    def is_ancestor(self, repo: str, older: str, newer: str) -> bool:
        done = subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=self.bare / f"{repo}.git",
            env=self.env,
            capture_output=True,
        )
        return done.returncode == 0

    def gh_calls(self) -> list[list[str]]:
        log = self.root / "gh-calls.jsonl"
        if not log.exists():
            return []
        return [
            json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x
        ]

    def set_latest(self, tag: str) -> None:
        """GitHub's Latest release, as the stand-in answers it: another line shipped."""
        path = self.root / "gh-state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["latest"] = tag
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def write_notes(self, specs: Path, version: str) -> None:
        notes = specs / "docs" / "releases" / f"{version}.md"
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text(
            f"# Eugene Plexus {version}\n\nA patch.\n\n## Fixed crashes on start\n\nx\n",
            encoding="utf-8",
            newline="\n",
        )

    # --- building ---------------------------------------------------------

    def repo(self, name: str) -> Path:
        bare = self.bare / f"{name}.git"
        self.git(self.root, "init", "-q", "--bare", str(bare))
        hooks = bare / "hooks"
        hooks.mkdir(exist_ok=True)
        hook = hooks / "pre-receive"
        hook.write_text(
            "#!/bin/sh\ncat >> pushes.log\n", encoding="utf-8", newline="\n"
        )
        os.chmod(hook, 0o755)
        self.git(bare, "config", "core.hooksPath", hooks.as_posix())
        work = self.main / name
        self.git(self.root, "clone", "-q", bare.as_uri(), str(work))
        return work

    def commit(self, work: Path, files: dict[str, str | bytes], message: str) -> str:
        for name, content in files.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8", newline="\n")
        self.git(work, "add", "-A")
        self.git(work, "commit", "-q", "-m", message)
        return self.git(work, "rev-parse", "HEAD")

    def build_dist(self, work: Path, name: str, source: str, parent: str | None) -> str:
        """A dist commit as ship.py makes one: the source's tree plus the build."""
        static = UI_STATIC if name == "ui" else WB_STATIC
        folder = work / static
        remove_tree(folder)
        folder.mkdir(parents=True)
        (folder / "index.html").write_text(
            f"<p>{name} built from {source}</p>\n", encoding="utf-8", newline="\n"
        )
        index = self.root / f"{name}.index"
        env = {**self.env, "GIT_INDEX_FILE": str(index)}
        self.git(work, "read-tree", source, env=env)
        self.git(work, "add", "-f", "--", static, env=env)
        tree = self.git(work, "write-tree", env=env)
        index.unlink()
        title = "Publish UI distribution" if name == "ui" else "Publish Workbench dist"
        parents = (["-p", parent] if parent else []) + ["-p", source]
        return self.git(
            work,
            "commit-tree",
            tree,
            *parents,
            "-m",
            f"{title} from {source[:7]}\n\nbuilt-from: eugene-plexus/{name}@{source}",
        )

    def component(self, name: str) -> None:
        work = self.repo(name)
        code = f"src/{package(name)}"
        files: dict[str, str | bytes] = {
            "pyproject.toml": pyproject(name, DEPENDENCIES),
            f"{code}/core.py": "VALUE = 1\n",
        }
        if name == "ui":
            files[".gitignore"] = f"out/\n{UI_STATIC}/\nnode_modules/\n"
        if name == "workbench":
            files[".gitignore"] = f"{WB_STATIC}/\nweb/node_modules/\n"
        if name == "agent":
            files[CATALOGUE] = catalogue(self.pins["workbench"])
            files[SITE_HOST_PY] = f'SITE_HOST_COMMIT = "{self.pins["site-host"]}"\n'
        pin = self.commit(work, files, f"{name} as {TAGGED} ships it")
        self.git(work, "push", "-q", "origin", "main")
        self.source[name] = pin
        self.pins[name] = pin
        if name in ("ui", "workbench"):
            self.pins[name] = self.build_dist(work, name, pin, None)
            self.git(work, "push", "-q", "origin", f"{self.pins[name]}:refs/heads/dist")
        self.git(work, "checkout", "-q", "-b", "side")
        self.side[name] = self.commit(
            work,
            {f"{code}/side.py": "SIDE = True\n"},
            "An experiment that never reached main",
        )
        self.git(work, "push", "-q", "origin", "side")
        self.git(work, "checkout", "-q", "main")
        self.fix[name] = self.commit(
            work, {f"{code}/fix.py": "FIXED = True\n"}, f"Fix {name}'s crash on start"
        )
        feature: dict[str, str | bytes] = {f"{code}/core.py": "VALUE = 2\n"}
        if name == "gateway":
            feature["pyproject.toml"] = pyproject(name, [*DEPENDENCIES, "rich>=13"])
        self.feature[name] = self.commit(work, feature, f"{name}: a new feature")
        self.later[name] = self.commit(
            work, {f"{code}/core.py": "VALUE = 3\n"}, f"{name}: build on the feature"
        )
        self.git(work, "push", "-q", "origin", "main")
        if name in ("ui", "workbench"):
            self.moved_dist[name] = self.build_dist(
                work, name, self.later[name], self.pins[name]
            )
            self.git(
                work, "push", "-q", "origin", f"{self.moved_dist[name]}:refs/heads/dist"
            )

    def manifest(self, pins: dict[str, str]) -> str:
        components = {name: pins[name] for name in (*MANIFEST_REPOS, "ui")}
        return (
            json.dumps(
                {
                    "format": 1,
                    "python": "3.12",
                    "uvMinimum": "0.12.18",
                    "components": components,
                    "dependenciesSha256": "0" * 64,
                },
                indent=2,
            )
            + "\n"
        )

    def specs(self) -> None:
        work = self.repo("specs")
        zero = "0" * 40
        files: dict[str, str | bytes] = {".gitignore": "docs/private/\n__pycache__/\n"}
        for name in SUPPORT:
            files[name] = (SCRIPTS.parent / name).read_bytes()
        for name in TOOLING:
            files[name] = f"# {name} as {TAGGED} has it: older release tooling\n"
        files["release/manifest.json"] = self.manifest(self.pins)
        files["release/requirements.in"] = (
            "\n".join(sorted({*DEPENDENCIES, "hatchling", AGENT_SERVICE})) + "\n"
        )
        files["release/requirements.lock"] = LOCK
        files["release/constraints.txt"] = ""
        files["scripts/install.sh"] = INSTALL_SH.format(
            zero=zero, site_host=self.pins["site-host"]
        )
        files["scripts/install.ps1"] = INSTALL_PS1.format(zero=zero)
        files["docs/releases/v1.1.0.md"] = "# Eugene Plexus v1.1.0\n\nThe older line.\n"
        self.commit(work, files, "v1.1.0: the older line")
        self.inputs(work)
        self.git(work, "tag", "-a", "v1.1.0", "-m", "Eugene Plexus v1.1.0")
        self.commit(
            work,
            {
                "docs/acceptance/v1.2.0-release-run.md": (
                    "# v1.2.0 release run\n\n## Untested paths and limits\n\n"
                    "- The fixture has no hardware.\n"
                ),
                "docs/releases/v1.2.0.md": "# Eugene Plexus v1.2.0\n\nThe newest line.\n",
            },
            "v1.2.0: run record and release notes",
        )
        self.git(work, "tag", "-a", TAGGED, "-m", f"Eugene Plexus {TAGGED}")
        self.git(work, "push", "-q", "origin", "main", "--tags")
        # main moves on: today's release tooling, then a ship of every main.
        self.commit(
            work,
            {name: (SCRIPTS.parent / name).read_bytes() for name in TOOLING},
            "Release tooling as main has it",
        )
        shipped = {**self.later, "ui": self.moved_dist["ui"]}
        text = (work / "scripts" / "install.sh").read_text(encoding="utf-8")
        files = {
            "release/manifest.json": self.manifest(shipped),
            "scripts/install.sh": re.sub(
                r"(?m)^PIN_SITE_HOST=[a-f0-9]{40}",
                f"PIN_SITE_HOST={self.later['site-host']}",
                text,
            ),
        }
        self.commit(work, files, "Ship to Edge: every component's main")
        self.inputs(work)
        self.git(work, "push", "-q", "origin", "main")
        self.git(work, "push", "-q", "origin", "main:refs/heads/edge")

    def inputs(self, work: Path) -> None:
        """release-inputs.py fills the installers; amend them into the commit."""
        code, output = self.python(work / "scripts" / "release-inputs.py", cwd=work)
        if code != 0:
            raise RuntimeError(f"release-inputs.py: {output}")
        self.git(work, "add", "-A")
        self.git(work, "commit", "-q", "--amend", "--no-edit")

    def website(self) -> None:
        work = self.repo("website")
        current = {
            "version": TAGGED,
            "specsCommit": self.rev("specs", TAGGED),
            "files": {"install.sh": {"sha256": "0" * 64}},
            "offlineRemoval": True,
        }
        files: dict[str, str | bytes] = {
            ".gitignore": "dist/\nnode_modules/\n",
            "src/data/alpha-release.json": json.dumps(current, indent=2) + "\n",
            "src/data/archived-releases.json": json.dumps(
                [{"version": "v1.1.0"}], indent=2
            )
            + "\n",
            "src/data/docs-revision.json": json.dumps({"commit": "0" * 40}, indent=2)
            + "\n",
            "src/content/recovery.md": (
                f"Download [scripts/recovery.py](https://github.com/{ORG}/specs/blob/"
                + "0" * 40
                + "/scripts/recovery.py).\n"
            ),
        }
        self.commit(work, files, "The site as v1.2.0 left it")
        self.git(work, "push", "-q", "origin", "main")

    def build(self) -> Fixture:
        for name in COMPONENTS:
            self.component(name)
        self.specs()
        self.website()
        self.reset_pushes()  # the build's own pushes
        return self


# --- the stand-ins release.py runs with ----------------------------------------

VALUED = {
    "--ref",
    "-f",
    "--workflow",
    "--event",
    "-L",
    "--json",
    "--commit",
    "-n",
    "-D",
    "--title",
    "--notes-file",
}


def options(tokens: list[str]) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    opts: dict[str, Any] = {}
    fields: dict[str, str] = {}
    positional: list[str] = []
    stream = iter(tokens)
    for token in stream:
        if token in VALUED:
            value = next(stream)
            if token == "-f":
                key, _, field = value.partition("=")
                fields[key] = field
            else:
                opts[token] = value
        elif token.startswith("-"):
            opts[token] = True
        else:
            positional.append(token)
    return opts, fields, positional


class FakeGitHub:
    """Answers the `gh` calls release.py makes, from the bare repositories, and
    records every call. Anything it does not know fails the run."""

    def __init__(self, root: Path, stop: type[Exception]) -> None:
        self.root = root
        self.stop = stop
        self.file = root / "gh-state.json"
        self.state: dict[str, Any] = (
            json.loads(self.file.read_text(encoding="utf-8"))
            if self.file.exists()
            else {"latest": TAGGED, "runs": [], "releases": {}, "next": 1000}
        )

    def git(self, repo: str, *args: str) -> str:
        done = subprocess.run(
            ["git", *args],
            cwd=self.root / "bare" / f"{repo}.git",
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            raise self.stop(
                f"gh stand-in: git {' '.join(args)} in {repo}: {done.stderr}"
            )
        return done.stdout.strip()

    def digest(self, tag: str) -> str:
        return "sha256:" + hashlib.sha256(tag.encode()).hexdigest()

    def __call__(self, *args: str) -> str:
        with (self.root / "gh-calls.jsonl").open(
            "a", encoding="utf-8", newline="\n"
        ) as log:
            log.write(json.dumps(list(args)) + "\n")
        tokens, repo = list(args), "specs"
        if "-R" in tokens:
            at = tokens.index("-R")
            repo = tokens[at + 1].split("/", 1)[1]
            del tokens[at : at + 2]
        try:
            return self.answer(repo, tokens)
        finally:
            self.file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def run_by_id(self, run_id: str) -> dict[str, Any]:
        for run in self.state["runs"]:
            if str(run["databaseId"]) == run_id:
                return run
        raise self.stop(f"gh stand-in: no run {run_id}")

    def answer(self, repo: str, args: list[str]) -> str:
        runs, releases = self.state["runs"], self.state["releases"]
        if args[0] == "api":
            path = args[1]
            if path == "graphql":
                query = args[args.index("-f") + 1]
                name = re.search(r'name: "([^"]+)"', query)[1]  # type: ignore[index]
                oid = re.search(r'oid: "([a-f0-9]+)"', query)[1]  # type: ignore[index]
                # gateway's moved heads have no CI result until a run exists.
                ran = any(r["repo"] == name and r["headSha"] == oid for r in runs)
                rollup = None if name == "gateway" and not ran else {"state": "SUCCESS"}
                return json.dumps(
                    {"data": {"repository": {"object": {"statusCheckRollup": rollup}}}}
                )
            if path == f"repos/{ORG}/specs/releases/latest":
                return json.dumps({"tag_name": self.state["latest"]})
            if path.startswith(f"repos/{ORG}/specs/actions/workflows/"):
                return json.dumps({"workflow_runs": []})
        if args[:2] == ["workflow", "run"]:
            opts, fields, _ = options(args[3:])
            run_id = self.state["next"]
            self.state["next"] += 1
            runs.append(
                {
                    "databaseId": run_id,
                    "workflow": args[2],
                    "repo": repo,
                    "ref": opts["--ref"],
                    "headSha": self.git(
                        repo, "rev-parse", f"{opts['--ref']}^{{commit}}"
                    ),
                    "inputs": fields,
                    "event": "workflow_dispatch",
                    "createdAt": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "status": "completed",
                    "conclusion": "success",
                    "url": f"https://github.com/{ORG}/{repo}/actions/runs/{run_id}",
                }
            )
            return ""
        if args[:2] == ["run", "list"]:
            opts, _, _ = options(args[2:])
            fields = opts["--json"].split(",")
            found = [
                {key: run[key] for key in fields}
                for run in reversed(runs)
                if run["repo"] == repo
                and run["workflow"] == opts["--workflow"]
                and opts.get("--event") in (None, run["event"])
                and opts.get("--commit") in (None, run["headSha"])
            ]
            return json.dumps(found)
        if args[:2] == ["run", "view"]:
            run = self.run_by_id(args[2])
            if "--log-failed" in args:
                return ""
            return json.dumps(
                {"status": run["status"], "conclusion": run["conclusion"], "jobs": []}
            )
        if args[:2] == ["run", "download"]:
            run = self.run_by_id(args[2])
            opts, _, _ = options(args[3:])
            folder = Path(opts["-D"])
            folder.mkdir(parents=True, exist_ok=True)
            tag = run["inputs"]["release_tag"]
            (folder / "qualification.json").write_text(
                json.dumps(
                    {
                        "specsCommit": run["headSha"],
                        "releaseTag": tag,
                        "imageDigest": self.digest(tag),
                        "acceptanceRecord": run["inputs"]["acceptance_record"],
                    }
                ),
                encoding="utf-8",
            )
            return ""
        if args[:2] == ["release", "view"]:
            entry = releases.get(args[2])
            if entry is None:
                raise self.stop("gh stand-in: release not found")
            if "--json" not in args:
                return f"title:\tEugene Plexus {args[2]}"
            return json.dumps(
                {
                    "isDraft": False,
                    "isPrerelease": False,
                    "url": entry["url"],
                    "assets": [
                        {"name": name, "digest": f"sha256:{digest}"}
                        for name, digest in entry["assets"].items()
                    ],
                }
            )
        if args[:2] == ["release", "create"]:
            version = args[2]
            opts, _, assets = options(args[3:])
            if version in releases:
                raise self.stop(f"gh stand-in: {version} already exists")
            if opts.get("--verify-tag"):
                self.git("specs", "rev-parse", "--verify", f"refs/tags/{version}")
            store = self.root / "gh-releases" / version
            store.mkdir(parents=True)
            digests = {}
            for asset in assets:
                data = Path(asset).read_bytes()
                (store / Path(asset).name).write_bytes(data)
                digests[Path(asset).name] = hashlib.sha256(data).hexdigest()
            releases[version] = {
                "url": f"https://github.com/{ORG}/specs/releases/tag/{version}",
                "assets": digests,
                "latest": bool(opts.get("--latest")),
            }
            if opts.get("--latest"):
                self.state["latest"] = version
            return releases[version]["url"]
        if args[:2] == ["release", "download"]:
            opts, _, _ = options(args[3:])
            for asset in (self.root / "gh-releases" / args[2]).iterdir():
                shutil.copyfile(asset, Path(opts["-D"]) / asset.name)
            return ""
        raise self.stop(
            f"gh stand-in: unexpected call: gh {' '.join(args)} -R {ORG}/{repo}"
        )


def inner(argv: list[str]) -> int:
    """Run the line's own release.py with GitHub and this machine stood in."""
    root, specs, rest = Path(argv[0]), Path(argv[1]).resolve(), argv[2:]
    stop_after = None
    if rest[:1] == ["--stop-after"]:
        stop_after, rest = rest[1], rest[2:]
    if rest[:1] == ["--"]:
        rest = rest[1:]
    scripts = specs / "scripts"
    sys.path.insert(0, str(scripts))
    import release  # the line's release.py
    import ship

    if Path(release.__file__).resolve().parent != scripts or ship.SPECS != specs:
        print(f"release.py did not load from {scripts}", file=sys.stderr)
        return 1
    hub = FakeGitHub(root, ship.Stop)

    def npm(cwd: Path, *args: str) -> None:
        head = ship.git(cwd if cwd.name != "web" else cwd.parent, "rev-parse", "HEAD")
        if args == ("run", "build:python"):
            ref = os.environ["NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF"]
            page = (
                f'<a href="https://raw.githubusercontent.com/{ORG}/specs/{ref}/scripts/'
                f'install.sh">Install</a> built from {head}\n'
            )
            for folder in (cwd / "out", cwd / UI_STATIC):
                remove_tree(folder)
                folder.mkdir(parents=True)
                (folder / "index.html").write_text(page, encoding="utf-8", newline="\n")
                (folder / "app.js").write_text(
                    "// console\n", encoding="utf-8", newline="\n"
                )
        elif args == ("run", "build") and cwd.name == "web":
            folder = cwd.parent / WB_STATIC
            remove_tree(folder)
            folder.mkdir(parents=True)
            (folder / "index.html").write_text(
                f"<p>Workbench built from {head}</p>\n", encoding="utf-8", newline="\n"
            )
        else:
            raise ship.Stop(f"npm stand-in: unexpected npm {' '.join(args)} in {cwd}")

    def evidence(r: Any) -> None:
        r["evidence"] = {
            "windows": {
                "passed": True,
                "candidate": r["candidate"],
                "installSeconds": 20.0,
                "firstToken": 60.0,
                "consoleFiles": r["consoleFiles"],
                "liveInstallUnchanged": True,
                "prefix": str(root / "no-previous-install"),
            },
            "wsl": {
                "passed": True,
                "candidate": r["candidate"],
                "installSeconds": 15.0,
            },
            "upgrade": {"passed": True, "candidate": r["candidate"], "checks": "31/31"},
            "systemUpdate": {"passed": True, "candidate": r["candidate"]},
            "recovery": {
                "passed": True,
                "candidate": r["candidate"],
                "timings": {"rootBackupSeconds": 1.0},
            },
        }

    def site_build(npm_path: str, args: tuple[str, ...], r: Any) -> tuple[int, str]:
        if args == ("run", "check"):
            data = json.loads(
                (release.SITE / "src" / "data" / "alpha-release.json").read_text(
                    encoding="utf-8"
                )
            )
            out = release.SITE / "dist" / "releases" / data["version"]
            out.mkdir(parents=True, exist_ok=True)
            for name in data["files"]:
                shutil.copyfile(r.dir / "final" / name, out / name)
        return 0, ""

    def fetch(url: str, timeout: float = 60) -> bytes:
        site = "https://eugeneplexus.com/"
        if url.startswith(site + "releases/"):
            return (release.SITE / "dist" / url[len(site) :]).read_bytes()
        if url == site + "install/":
            data = json.loads(
                (release.SITE / "src" / "data" / "alpha-release.json").read_text(
                    encoding="utf-8"
                )
            )
            return f'<a href="/releases/{data["version"]}/install.ps1">'.encode()
        raise ship.Stop(f"web stand-in: unexpected {url}")

    release.run_gh = hub
    release.registry_digest = hub.digest
    release.fetch_url = fetch
    release.local_tools = lambda: None
    release.evidence = evidence
    release._site = site_build
    ship.npm = npm
    if stop_after:
        release.PHASES = release.PHASES[: release.PHASES.index(stop_after) + 1]
    sys.argv = ["release.py", *rest]
    return release.main()


# --- the scenario -------------------------------------------------------------


class Checks:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def __call__(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, bool(ok), detail))
        print(
            f"{'PASS' if ok else 'FAIL'}  {name}"
            + ("" if ok else f"\n      {detail[-1500:]}")
        )
        return bool(ok)

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.results)


def picked_from(fx: Fixture, repo: str, start: str, head: str) -> list[str]:
    """The main commits named by the `-x` trailers on start..head."""
    log = fx.git(fx.bare / f"{repo}.git", "log", "--format=%B", f"{start}..{head}")
    return re.findall(r"\(cherry picked from commit ([a-f0-9]{40})\)", log)


def scenario(fx: Fixture, check: Checks) -> None:
    before = fx.refs()

    # 1. A rehearsal: preflight to qualify on rehearsal/v1.2, then gone.
    code, out = fx.line("open", "v1.2", "--rehearsal")
    check("open v1.2 --rehearsal", code == 0, out)
    code, out = fx.release(
        fx.lines / "v1.2-rehearsal" / "specs", "v1.2.1-rehearsal.1", "--rehearsal"
    )
    check("a rehearsal runs preflight to qualify and stops", code == 0, out)
    calls = fx.gh_calls()
    dispatched = [
        c for c in calls if c[:3] == ["workflow", "run", "release-qualification.yml"]
    ]
    check(
        "the rehearsal qualified v1.2.1-rehearsal.1 on its own candidate branch",
        len(dispatched) == 1
        and "release-candidate/v1.2.1-rehearsal.1" in dispatched[0]
        and "release_tag=v1.2.1-rehearsal.1" in dispatched[0],
        json.dumps(dispatched),
    )
    check(
        "the rehearsal made no tag, image or GitHub release",
        not fx.git(fx.bare / "specs.git", "tag", "-l", "v1.2.1*")
        and not any(c[:2] == ["release", "create"] for c in calls)
        and not any("container.yml" in c for c in calls),
        json.dumps(calls),
    )
    code, out = fx.line("close", "v1.2", "--rehearsal", "--delete-branches")
    check("close v1.2 --rehearsal --delete-branches", code == 0, out)
    left = {
        repo: [r for r in refs if "rehearsal" in r] for repo, refs in fx.refs().items()
    }
    check(
        "no rehearsal branch is left",
        not any(left.values()),
        json.dumps(left),
    )

    # 2. The line, and picks from main.
    code, out = fx.line("open", "v1.2")
    check("open v1.2", code == 0, out)
    line = fx.lines / "v1.2"
    fixes = [f"{name}:{fx.fix[name]}" for name in ("agent", "gateway", "workbench")]
    code, out = fx.line("pick", "v1.2", *fixes)
    check("pick three fixes from main", code == 0, out)
    code, out = fx.line("pick", "v1.2", f"gateway:{fx.fix['gateway'][:12]}")
    gateway_head = fx.rev("gateway", "release/v1.2")
    check(
        "a second pick of the same fix applies nothing",
        code == 0
        and picked_from(fx, "gateway", fx.pins["gateway"], gateway_head)
        == [fx.fix["gateway"]],
        out,
    )
    code, out = fx.line("pick", "v1.2", f"control:{fx.side['control']}")
    check(
        "a commit that is not on main is refused",
        code == 2 and "not on main" in out,
        out,
    )
    code, out = fx.line("pick", "v1.2", f"library:{fx.later['library']}")
    check(
        "a conflicting pick is aborted and names its files",
        code == 2
        and "core.py" in out
        and not fx.git(
            line / "library", "status", "--porcelain", "--untracked-files=no"
        )
        and fx.git(line / "library", "rev-parse", "HEAD") == fx.pins["library"],
        out,
    )

    # 3. The release.
    code, out = fx.release(line / "specs", "v1.2.2")
    check(
        "v1.2.2 is refused: it must follow v1.2.0",
        code == 2 and "must follow v1.2.0" in out,
        out,
    )
    code, out = fx.release(line / "specs", "v1.2.1")
    check("release.py stops for the release notes (exit 3)", code == 3, out)
    notes = line / "specs" / "docs" / "releases" / "v1.2.1.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(
        "# Eugene Plexus v1.2.1\n\nA patch of v1.2.0.\n\n## Fixed crashes on start\n\nx\n",
        encoding="utf-8",
        newline="\n",
    )
    code, out = fx.release(line / "specs", "v1.2.1")
    check("release.py v1.2.1 runs every phase", code == 0, out)
    state_file = line / "specs" / "docs" / "private" / "release-v1.2.1" / "state.json"
    state = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else {}
    )
    code, out = fx.line("close", "v1.2")
    check("close v1.2", code == 0 and not (line / "agent").exists(), out)
    after = fx.refs()

    # Edge's refs, and every push.
    moved = {
        f"{repo}:{ref}": (before[repo].get(ref), after[repo].get(ref))
        for repo in before
        if repo != "website"
        for ref in ("refs/heads/main", "refs/heads/dist", "refs/heads/edge")
        if before[repo].get(ref) != after[repo].get(ref)
    }
    check(
        "no main, dist or edge ref moved except specs main",
        set(moved) == {"specs:refs/heads/main"},
        json.dumps(moved),
    )
    old_main, new_main = moved.get("specs:refs/heads/main", ("", ""))
    specs_bare = fx.bare / "specs.git"
    if new_main:
        parents = fx.git(specs_bare, "rev-list", "--parents", "-1", new_main).split()[
            1:
        ]
        changed = fx.git(
            specs_bare, "diff", "--raw", "--no-renames", old_main, new_main
        )
        check(
            "specs main gained one documentation-only commit: the notes and the record",
            parents == [old_main]
            and sorted(line.split("\t")[1] for line in changed.splitlines())
            == ["docs/acceptance/v1.2.1-release-run.md", "docs/releases/v1.2.1.md"]
            and all(line.split()[1] == "100644" for line in changed.splitlines()),
            changed,
        )
    allowed = {
        "refs/heads/release/v1.2",
        "refs/heads/rehearsal/v1.2",
        "refs/heads/release/v1.2-dist",
        "refs/heads/rehearsal/v1.2-dist",
        "refs/heads/release-candidate/v1.2.1",
        "refs/heads/release-candidate/v1.2.1-rehearsal.1",
        "refs/tags/v1.2.1",
    }
    strays = [
        p
        for p in fx.pushes()
        if p[1] not in allowed
        and not (p[0] in ("specs", "website") and p[1] == "refs/heads/main")
    ]
    check("every push is to the line's own refs", not strays, json.dumps(strays))
    main_pushes = [
        p for p in fx.pushes() if p[0] == "specs" and p[1] == "refs/heads/main"
    ]
    check("specs main was pushed once", len(main_pushes) == 1, json.dumps(main_pushes))

    # The tag, and what it pins.
    tagged = (
        fx.rev("specs", "v1.2.1") if fx.git(specs_bare, "tag", "-l", "v1.2.1") else ""
    )
    check(
        "tag v1.2.1 names the line's record commit",
        bool(tagged)
        and tagged == state.get("qualified")
        and fx.is_ancestor("specs", tagged, "release/v1.2")
        and "v1.2.1-release-run.md"
        in fx.git(specs_bare, "ls-tree", "--name-only", f"{tagged}:docs/acceptance"),
        f"tag {tagged} state {state.get('qualified')}",
    )
    shell = fx.show("specs", "v1.2.1:scripts/install.sh") if tagged else ""
    pins = {
        {"DRIVER": "inference-driver"}.get(key, key.lower().replace("_", "-")): sha
        for key, sha in re.findall(r"(?m)^PIN_([A-Z_]+)=([a-f0-9]{40})", shell)
    }
    unpicked = ("control", "library", "inference-driver", "tool-driver", "site-host")
    check(
        "the repositories with no pick are at v1.2.0's commits",
        all(pins.get(name) == fx.pins[name] for name in unpicked),
        json.dumps({n: (pins.get(n), fx.pins[n]) for n in unpicked}),
    )
    for name in ("agent", "gateway"):
        head = fx.rev(name, "release/v1.2")
        check(
            f"{name} is at its line head, which holds the fix with its -x trailer",
            pins.get(name) == head
            and picked_from(fx, name, fx.pins[name], head) == [fx.fix[name]],
            f"pin {pins.get(name)} head {head}",
        )
    ui_dist = fx.rev("ui", "release/v1.2-dist")
    ui_parents = fx.git(
        fx.bare / "ui.git", "rev-list", "--parents", "-1", ui_dist
    ).split()[1:]
    check(
        "the console is rebuilt on v1.2.0's dist, not main's",
        pins.get("ui") == ui_dist and ui_parents == [fx.pins["ui"], fx.source["ui"]],
        f"pin {pins.get('ui')} dist {ui_dist} parents {ui_parents}",
    )
    agent_pin = pins.get("agent", "")
    pinned = (
        re.search(
            r"workbench/archive/([a-f0-9]{40})",
            fx.show("agent", f"{agent_pin}:{CATALOGUE}"),
        )
        if agent_pin
        else None
    )
    wb_dist = fx.rev("workbench", "release/v1.2-dist")
    wb_parents = fx.git(
        fx.bare / "workbench.git", "rev-list", "--parents", "-1", wb_dist
    ).split()[1:]
    wb_head = fx.rev("workbench", "release/v1.2")
    check(
        "the agent pins a Workbench dist built from the line, on v1.2.0's dist",
        pinned is not None
        and pinned[1] == wb_dist
        and wb_parents == [fx.pins["workbench"], wb_head]
        and picked_from(fx, "workbench", fx.source["workbench"], wb_head)
        == [fx.fix["workbench"]],
        f"pinned {pinned and pinned[1]} dist {wb_dist} parents {wb_parents}",
    )
    check(
        "the line's specs carries main's release tooling",
        bool(tagged)
        and all(
            fx.git(specs_bare, "rev-parse", f"v1.2.1:{name}")
            == fx.git(specs_bare, "rev-parse", f"{old_main}:{name}")
            for name in TOOLING
        ),
    )

    # GitHub, the website, the record.
    calls = fx.gh_calls()
    creates = [c for c in calls if c[:2] == ["release", "create"]]
    check(
        "the stand-in saw one release create, as Latest",
        len(creates) == 1
        and creates[0][2] == "v1.2.1"
        and "--latest" in creates[0]
        and "--latest=false" not in creates[0],
        json.dumps(creates),
    )
    site = json.loads(fx.show("website", "main:src/data/alpha-release.json"))
    archive = json.loads(fx.show("website", "main:src/data/archived-releases.json"))
    check(
        "the website offers v1.2.1 and archives v1.2.0",
        site.get("version") == "v1.2.1" and archive[0].get("version") == TAGGED,
        json.dumps([site.get("version"), [a.get("version") for a in archive]]),
    )
    record = (
        fx.show("specs", "main:docs/acceptance/v1.2.1-release-run.md")
        if new_main
        else ""
    )
    check(
        "the record on main names the line, the picks and the publication",
        "## Patch of v1.2.0" in record
        and fx.fix["agent"] in record
        and "## Publication" in record,
        record[:1500],
    )
    check(
        "close kept the line's branches and the run's private files",
        all("refs/heads/release/v1.2" in after[name] for name in ("specs", *COMPONENTS))
        and (
            fx.main / "specs" / "docs" / "private" / "release-v1.2.1" / "state.json"
        ).exists(),
    )


def not_latest(
    fx: Fixture, check: Checks, version: str, latest: str, site_before: str
) -> str:
    """Checks for a patch published while another line is Latest; returns its record."""
    creates = [c for c in fx.gh_calls() if c[:3] == ["release", "create", version]]
    check(
        f"{version} is published once, with --latest=false",
        len(creates) == 1
        and "--latest=false" in creates[0]
        and "--latest" not in creates[0],
        json.dumps(creates),
    )
    state = json.loads((fx.root / "gh-state.json").read_text(encoding="utf-8"))
    check(f"{latest} stays GitHub's Latest", state["latest"] == latest, state["latest"])
    site_pushes = [p for p in fx.pushes() if p[0] == "website"]
    check(
        "the website is not pushed and still offers the newest line",
        not site_pushes and fx.rev("website", "main") == site_before,
        json.dumps(site_pushes),
    )
    record = fx.show("specs", f"main:docs/acceptance/{version}-release-run.md")
    check(
        f"the record on main says {version} is not Latest and the website is unchanged",
        f"not as Latest ({latest} stays Latest)" in record
        and "The website was not changed" in record
        and "is not Latest, so an installed agent's" in record,
        record[-2500:],
    )
    return record


def older_line(fx: Fixture, check: Checks) -> None:
    """4. A security fix on the older line v1.1, while v1.2.1 is Latest."""
    fx.reset_pushes()
    site_before = fx.rev("website", "main")
    code, out = fx.line("open", "v1.1")
    check(
        "open v1.1 is refused without --security",
        code == 2 and "--security" in out,
        out,
    )
    code, out = fx.line("open", "v1.1", "--security")
    check("open v1.1 --security", code == 0, out)
    code, out = fx.line("pick", "v1.1", f"gateway:{fx.fix['gateway']}")
    check("pick the fix onto v1.1", code == 0, out)
    specs = fx.lines / "v1.1" / "specs"
    code, out = fx.release(specs, "v1.1.1")
    check(
        "release.py v1.1.1 is refused without --security",
        code == 2 and "older than the latest release, v1.2.1" in out,
        out,
    )
    fx.write_notes(specs, "v1.1.1")
    code, out = fx.release(specs, "v1.1.1", "--security")
    check("release.py v1.1.1 --security runs every phase", code == 0, out)
    record = not_latest(fx, check, "v1.1.1", "v1.2.1", site_before)
    check(
        "the record names the security fix on the older line",
        "**Security fix.** Line `release/v1.1` is older than the latest release, v1.2.1"
        in record,
        record[:1500],
    )
    code, out = fx.line("close", "v1.1")
    check("close v1.1", code == 0, out)


def latest_moved(fx: Fixture, check: Checks) -> None:
    """5. v1.2.2 waits for its notes; meanwhile v1.3.0 ships and is Latest. The
    resumed run must not take Latest back to the older line v1.2."""
    fx.reset_pushes()
    site_before = fx.rev("website", "main")
    code, out = fx.line("open", "v1.2")
    check("open v1.2 again, at v1.2.1's pins", code == 0, out)
    code, out = fx.line("pick", "v1.2", f"control:{fx.fix['control']}")
    check("pick a fix for v1.2.2", code == 0, out)
    specs = fx.lines / "v1.2" / "specs"
    code, out = fx.release(specs, "v1.2.2")
    check("release.py v1.2.2 stops for its notes (exit 3)", code == 3, out)
    fx.set_latest("v1.3.0")
    fx.write_notes(specs, "v1.2.2")
    code, out = fx.release(specs, "v1.2.2")
    check("the resumed v1.2.2 runs every phase", code == 0, out)
    not_latest(fx, check, "v1.2.2", "v1.3.0", site_before)
    code, out = fx.line("close", "v1.2")
    check("close v1.2", code == 0, out)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--inner":
        return inner(sys.argv[2:])
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--keep", type=Path, help="build the fixture here and keep it")
    args = parser.parse_args()
    root = args.keep or Path(tempfile.mkdtemp(prefix="ep-patch-"))
    root.mkdir(parents=True, exist_ok=True)
    check = Checks()
    try:
        fx = Fixture(root).build()
        scenario(fx, check)
        older_line(fx, check)
        latest_moved(fx, check)
    finally:
        if not args.keep:
            remove_tree(root)
    failed = [name for name, ok, _ in check.results if not ok]
    print(
        f"RESULT {'PASS' if not failed else 'FAIL'}: "
        f"{len(check.results) - len(failed)}/{len(check.results)} checks"
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
