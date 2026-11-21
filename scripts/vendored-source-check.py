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

Every branch name (`main` included) is turned into its commit with `git
ls-remote` first, and every file is fetched by commit: raw.githubusercontent.com
caches a branch name for up to five minutes, and a ship pushes the component
mains seconds before specs `main`.

Usage: python scripts/vendored-source-check.py [--at pins|main] [--branch NAME]
       [--ref REPO=REF ...] [--root DIR]
Exit 1 names each repository, file, source and both digests that differ, or
the address that could not be read and why.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

COMMIT = re.compile(r"[0-9a-f]{40}")
#: Tries per file on a 429, a 5xx or a timeout, and the waits between them.
ATTEMPTS = 4
BACKOFF_SECONDS = (2.0, 5.0, 10.0)

Fetch = Callable[[str, str, str], bytes | None]
#: (repository, branch) -> the branch's head commit, or None when it has none.
Lookup = Callable[[str, str], str | None]


class FetchError(RuntimeError):
    """A file that could not be read: its address and what was observed."""


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


def fetch_raw(
    repository: str,
    commit: str,
    path: str,
    *,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes | None:
    """One file of a public repository at a commit; None when it is absent (404).

    A 429, a 5xx or a timeout is tried again, `ATTEMPTS` times in all; after
    that, `FetchError` names the address and the last thing observed."""
    if not COMMIT.fullmatch(commit):
        raise ValueError(f"{repository}: {commit!r} is not a commit; resolve it first")
    quoted = f"{urllib.parse.quote(repository)}/{commit}/{urllib.parse.quote(path)}"
    url = f"https://raw.githubusercontent.com/{ORGANIZATION}/{quoted}"
    observed = ""
    for attempt in range(ATTEMPTS):
        if attempt:
            sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
        try:
            with urlopen(url, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            observed = f"HTTP {error.code}"
            if error.code != 429 and error.code < 500:
                break
        except TimeoutError as error:  # socket.timeout is this name since 3.10
            observed = f"no answer in 60 s ({error})"
        except (ConnectionError, http.client.IncompleteRead) as error:
            observed = f"the connection broke ({type(error).__name__}: {error})"
        except urllib.error.URLError as error:
            if not isinstance(error.reason, TimeoutError):
                observed = f"could not connect ({error.reason})"
                break
            observed = f"no answer in 60 s ({error.reason})"
    raise FetchError(f"{url}: {observed} after {attempt + 1} attempt(s)")


def remote_head(repository: str, branch: str) -> str | None:
    """The commit `branch` names on GitHub now (`ci_plan.remote_branch`, which
    raises when the lookup itself fails)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ci_plan import remote_branch

    return remote_branch(repository, branch)


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
    lookup: Lookup = lambda repository, branch: None,
    branch: str = "",
    at: str = "pins",
    said: dict[str, str] | None = None,
) -> dict[str, str]:
    """The commit to read in each repository: a given ref, else the
    same-named branch when it exists, else the commit that ships (`at="pins"`)
    or the repository's `main` (`at="main"`). Branch names become commits
    here (`lookup`); `said` gets where each commit came from."""
    unknown = sorted(set(refs) - repositories)
    if unknown:
        raise ValueError(
            f"--ref names no consumer in platform/manifest.json: {', '.join(unknown)} "
            f"(consumers: {', '.join(sorted(repositories))})"
        )
    chosen: dict[str, str] = {}
    origin: dict[str, str] = {} if said is None else said
    pins = installer_pins(installer)

    def commit(repository: str, name: str, why: str) -> str:
        if COMMIT.fullmatch(name):
            return name
        head = lookup(repository, name)
        if head is None:
            raise ValueError(
                f"{repository}: GitHub has no branch {name!r} ({why}); "
                "give a branch or a full 40-character commit"
            )
        return head

    def pick(repository: str, pinned: Callable[[], str]) -> str:
        if refs.get(repository):
            origin[repository] = f"--ref {refs[repository]}"
            return commit(repository, refs[repository], "--ref")
        if branch:
            head = lookup(repository, branch)
            if head is not None:
                origin[repository] = f"branch {branch}"
                return head
        if at == "main":
            origin[repository] = "main"
            return commit(repository, "main", "its main")
        origin[repository] = "the pin that ships"
        return pinned()

    def no_pin(repository: str) -> str:
        raise ValueError(
            f"{repository}: this check knows no pin for it. Add where it is pinned "
            "(INSTALLER_PINS, or a pin the agent holds) to scripts/vendored-source-check.py, "
            "or run with --at main"
        )

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
            chosen[repository] = pick(repository, lambda r=repository: no_pin(r))
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
    # Every name is kept, an empty value too (CI passes one per input), so a
    # misspelt name fails instead of being dropped.
    refs = {}
    for item in args.ref:
        repository, _, ref = item.partition("=")
        refs[repository] = ref
    expected = _load("vendor-platform").planned(SPECS)
    said: dict[str, str] = {}
    try:
        unknown = sorted(set(refs) - set(expected))
        if unknown:
            raise ValueError(
                f"--ref names no consumer in platform/manifest.json: {', '.join(unknown)}"
            )
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
                lookup=remote_head,
                branch=args.branch,
                at=args.at,
                said=said,
            )
        for repository, ref in chosen.items():
            how = f" ({said[repository]})" if repository in said else ""
            print(f"{repository}: {ref}{how}")
        problems = compare(expected, chosen, fetch)
    except (ValueError, RuntimeError) as error:
        # FetchError and a failed `git ls-remote` are RuntimeErrors: fail closed.
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
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
