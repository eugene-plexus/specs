"""Compare every vendored copy that ships with its source in this repository (specs#135).

Each component checks its own copies offline against the digests in its own
`VENDORED.json` (`check-vendored.py`). That check cannot see a copy that is
old everywhere: a repository that was never re-vendored records the old
digest too. This check compares the other way, with the source: for every
consumer in `platform/manifest.json`, every file `vendor-platform.py` would
write there (the modules, the contracts, `check-vendored.py` and the lock)
must equal what the consumer holds at the commit that ships.

The commit that ships is the installer's `PIN_*` (`scripts/install.sh`), and
for site-host and Workbench the agent's own pins at the agent commit in use;
Release qualification reads these. CI's merge gate reads each repository's
`main` instead (`--at main`): consumers merge first, then specs, and a ship
moves the pins only after that, so the pins lag every merge that changes a
source. A candidate replaces either: `--ref <repo>=<commit or branch>`, or
`--branch <name>` for each repository that has a branch of that name (a specs
branch push tests the same-named component branches).

Usage: python scripts/vendored-source-check.py [--at pins|main] [--branch NAME]
       [--ref REPO=REF ...] [--root DIR]
Exit 1 names each repository, file, source and both digests that differ.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

SPECS = Path(__file__).resolve().parent.parent
ORGANIZATION = "eugene-plexus"
# The installer's pin variable for each repository it pins.
INSTALLER_PINS = {
    "agent": "AGENT",
    "control": "CONTROL",
    "gateway": "GATEWAY",
    "inference-driver": "DRIVER",
    "library": "LIBRARY",
    "store": "STORE",
    "tool-driver": "TOOL_DRIVER",
    "ui": "UI",
}
# The agent pins these two; read at the agent commit in use (as ship.py does).
CATALOGUE = "src/eugene_plexus_agent/apps_catalogue.yaml"
SITE_HOST_PY = "src/eugene_plexus_agent/site_host.py"
WB_PIN = re.compile(r"workbench/archive/([a-f0-9]{40})\.tar\.gz\n  version: ([a-f0-9]{40})")
SH_PIN = re.compile(r'(?m)^SITE_HOST_COMMIT = "([a-f0-9]{40})"')

Fetch = Callable[[str, str, str], bytes | None]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), Path(__file__).with_name(name + ".py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data: bytes) -> str:
    """The digest `check-vendored.py` uses: text read as UTF-8 with universal newlines."""
    return hashlib.sha256(data.decode("utf-8").replace("\r\n", "\n").encode()).hexdigest()


def fetch_raw(repository: str, ref: str, path: str) -> bytes | None:
    """One file of a public repository at a commit or branch; None when absent."""
    url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
        ORGANIZATION,
        urllib.parse.quote(repository),
        urllib.parse.quote(ref, safe=""),
        urllib.parse.quote(path),
    )
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def branch_exists(repository: str, branch: str) -> bool:
    url = f"https://github.com/{ORGANIZATION}/{repository}"
    output = subprocess.run(
        ["git", "ls-remote", "--heads", url, f"refs/heads/{branch}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    return bool(output.strip())


def installer_pins(installer: str) -> dict[str, str]:
    pins = {}
    for repository, name in INSTALLER_PINS.items():
        found = re.search(rf"(?m)^PIN_{name}=([0-9a-f]{{40}})\b", installer)
        if not found:
            raise ValueError(f"scripts/install.sh: no PIN_{name}")
        pins[repository] = found.group(1)
    return pins


def resolve(
    repositories: set[str],
    refs: dict[str, str],
    *,
    installer: str,
    fetch: Fetch,
    has_branch: Callable[[str], bool] = lambda repository: False,
    branch: str = "",
    at: str = "pins",
) -> dict[str, str]:
    """The commit or branch to read in each repository: a given ref, else the
    same-named branch when it exists, else the commit that ships (`at="pins"`)
    or the repository's `main` (`at="main"`)."""
    chosen: dict[str, str] = {}
    pins = installer_pins(installer)

    def pick(repository: str, pinned: Callable[[], str]) -> str:
        if refs.get(repository):
            return refs[repository]
        if branch and has_branch(repository):
            return branch
        return "main" if at == "main" else pinned()

    chosen["agent"] = pick("agent", lambda: pins["agent"])

    def agent_pin(path: str, pattern: re.Pattern[str], what: str) -> str:
        text = fetch("agent", chosen["agent"], path)
        found = pattern.search(text.decode("utf-8")) if text is not None else None
        if not found or (pattern is WB_PIN and found.group(1) != found.group(2)):
            raise ValueError(f"agent at {chosen['agent']}: could not read the {what} pin")
        return found.group(1)

    for repository in sorted(repositories - {"agent"}):
        if repository == "workbench":
            chosen[repository] = pick(repository, lambda: agent_pin(CATALOGUE, WB_PIN, "Workbench"))
        elif repository == "site-host":
            chosen[repository] = pick(
                repository, lambda: agent_pin(SITE_HOST_PY, SH_PIN, "site-host")
            )
        elif repository in pins:
            chosen[repository] = pick(repository, lambda r=repository: pins[r])
        else:
            raise ValueError(f"{repository}: no pin to read it at; name it with --ref")
    return {r: chosen[r] for r in sorted(repositories)}


def compare(
    expected: dict[str, dict[str, tuple[str, bytes]]],
    refs: dict[str, str],
    fetch: Fetch,
) -> list[str]:
    """One line per vendored file that differs from its source in this repository."""
    problems = []
    for repository, files in sorted(expected.items()):
        ref = refs[repository]
        for relative, (source, data) in sorted(files.items()):
            want = digest(data)
            held = fetch(repository, ref, relative)
            if held is None:
                problems.append(
                    f"{repository} {relative}: missing at {ref}; source {source} sha256 {want}"
                )
                continue
            have = digest(held)
            if have != want:
                problems.append(
                    f"{repository} {relative}: sha256 {have} at {ref} differs from "
                    f"source {source} sha256 {want}"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--branch", default="", help="read each repository's branch of this name")
    parser.add_argument("--ref", action="append", default=[], metavar="REPO=REF")
    parser.add_argument(
        "--at",
        choices=("pins", "main"),
        default="pins",
        help="what a repository with no ref or branch is read at: the commit that ships "
        "(default) or its main (CI's merge gate: a ship moves the pins after the merge)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="read the working trees in ROOT/<repo> instead of GitHub (no pins, no network)",
    )
    args = parser.parse_args(argv)
    refs = {}
    for item in args.ref:
        repository, _, ref = item.partition("=")
        if ref:
            refs[repository] = ref
    expected = _load("vendor-platform").planned(SPECS)
    if args.root is not None:
        root: Path = args.root

        def fetch(repository: str, ref: str, path: str) -> bytes | None:
            file = root / repository / path
            return file.read_bytes() if file.is_file() else None

        chosen = {repository: "the working tree" for repository in sorted(expected)}
    else:
        fetch = fetch_raw
        installer = (SPECS / "scripts/install.sh").read_text(encoding="utf-8")
        chosen = resolve(
            set(expected),
            refs,
            installer=installer,
            fetch=fetch_raw,
            has_branch=lambda repository: branch_exists(repository, args.branch),
            branch=args.branch,
            at=args.at,
        )
    for repository, ref in chosen.items():
        print(f"{repository}: {ref}")
    problems = compare(expected, chosen, fetch)
    for line in problems:
        print(f"DIFFERS {line}", file=sys.stderr)
    if problems:
        print(
            f"FAIL: {len(problems)} vendored file(s) differ from their source; "
            "run scripts/vendor-platform.py --repo <repo> in that repository's branch",
            file=sys.stderr,
        )
        return 1
    count = sum(len(files) for files in expected.values())
    print(f"PASS: {count} vendored files in {len(expected)} repositories equal their source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
