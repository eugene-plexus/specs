"""Check that every consumer's codegen names the documents it should generate.

Each consumer repository (`gateway`, `ui`, ...) regenerates its models from the
specs commit in its `SPECS_REF`, from the documents its codegen config names
(`scripts/codegen.py`, or `scripts/codegen.mjs` for `ui`). A document that
reaches a consumer's pin and that its config does not name is a contract the
consumer never sees: nothing fails, the types are simply missing.

The table below is the one place that says which consumer generates which
document. It is not under `openapi/`, where CI validates every YAML file as an
OpenAPI document.

Rule A: every `openapi/*.yaml` and `openapi/components/*.yaml` has a row, and
every row names a file that exists.

Rule B: for each consumer, read its `SPECS_REF` and its codegen config.
  * Fail when the table gives the consumer a document that is present at that
    `SPECS_REF`, and the config does not name it.
  * Fail when the config names a document the table does not give the consumer.
A consumer that has not been re-pinned yet is not checked against a document
its pin predates, so Rule B never blocks the specs-first order of a contract
change.

Where the files come from:
  * `--root DIR`: the sibling checkouts `DIR/<repo>/...`.
  * Without it: each file at the consumer's release pin, from
    raw.githubusercontent.com. The pins are the `PIN_*` lines of
    `scripts/install.sh`, and the agent's own pins of the site host and
    Workbench, read from the agent at its pin.
A file this script cannot read fails the check, naming the URL and the HTTP
status. It never passes silently.

Run it from a checkout with full history (`git fetch --unshallow`): it asks git
whether a document exists at a consumer's `SPECS_REF`.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SPECS = Path(__file__).resolve().parent.parent

SHA = re.compile(r"[0-9a-f]{40}")
RAW_URL = "https://raw.githubusercontent.com/eugene-plexus/{repo}/{ref}/{path}"


@dataclass(frozen=True)
class Document:
    """One contract document and who reads it.

    `consumers` generate it directly. `reached_through` names the documents
    that `$ref` it: a fragment reaches a consumer through them. A document
    nobody generates says why in `why_not`.
    """

    consumers: tuple[str, ...] = ()
    reached_through: tuple[str, ...] = ()
    why_not: str = ""


#: Consumer repository -> its codegen config, relative to the repository.
CONSUMERS: dict[str, str] = {
    "agent": "scripts/codegen.py",
    "control": "scripts/codegen.py",
    "gateway": "scripts/codegen.py",
    "inference-driver": "scripts/codegen.py",
    "library": "scripts/codegen.py",
    "site-host": "scripts/codegen.py",
    "store": "scripts/codegen.py",
    "tool-driver": "scripts/codegen.py",
    "ui": "scripts/codegen.mjs",
    "workbench": "scripts/codegen.py",
}

#: The release pin of each consumer that `scripts/install.sh` carries. The
#: site host and Workbench are pinned by the agent instead (`agent_pins`).
INSTALLER_PINS: dict[str, str] = {
    "agent": "PIN_AGENT",
    "control": "PIN_CONTROL",
    "gateway": "PIN_GATEWAY",
    "inference-driver": "PIN_DRIVER",
    "library": "PIN_LIBRARY",
    "store": "PIN_STORE",
    "tool-driver": "PIN_TOOL_DRIVER",
    "ui": "PIN_UI",
}

#: Every document, and which consumers generate it.
TABLE: dict[str, Document] = {
    "openapi/agent.yaml": Document(consumers=("agent", "control", "ui")),
    "openapi/control.yaml": Document(consumers=("control", "ui")),
    "openapi/gateway.yaml": Document(consumers=("gateway", "ui")),
    "openapi/inference-driver.yaml": Document(consumers=("gateway", "inference-driver", "ui")),
    "openapi/library.yaml": Document(consumers=("gateway", "library", "ui")),
    "openapi/site-host.yaml": Document(consumers=("agent", "site-host")),
    "openapi/store.yaml": Document(consumers=("gateway", "store", "ui")),
    "openapi/tool-driver.yaml": Document(consumers=("gateway", "tool-driver", "ui")),
    "openapi/workbench-ag-ui.yaml": Document(
        why_not=(
            "a prose contract: Workbench writes its AG-UI adapters by hand against it, "
            "and no consumer generates models from it"
        )
    ),
    "openapi/workbench-interactions.yaml": Document(
        why_not=(
            "Workbench implements its request models by hand "
            "(interactions_api.py); no consumer generates models from it"
        )
    ),
    "openapi/components/common.yaml": Document(
        consumers=("agent", "workbench"),
        reached_through=(
            "openapi/agent.yaml",
            "openapi/control.yaml",
            "openapi/gateway.yaml",
            "openapi/inference-driver.yaml",
            "openapi/library.yaml",
            "openapi/store.yaml",
            "openapi/tool-driver.yaml",
        ),
    ),
    "openapi/components/client-keys.yaml": Document(
        consumers=("gateway",),
        reached_through=("openapi/agent.yaml", "openapi/control.yaml"),
    ),
    "openapi/components/job-sites.yaml": Document(reached_through=("openapi/control.yaml",)),
    "openapi/components/sign-in.yaml": Document(reached_through=("openapi/control.yaml",)),
    "openapi/components/sites.yaml": Document(
        reached_through=(
            "openapi/control.yaml",
            "openapi/components/job-sites.yaml",
            "openapi/site-host.yaml",
        )
    ),
}


class Unreadable(Exception):
    """A file the check needs and could not read; the message names where."""


class Source(Protocol):
    def read(self, repo: str, path: str) -> str: ...


# --------------------------------------------------------------------------- #
# Where the consumers' files come from
# --------------------------------------------------------------------------- #


class Checkouts:
    """Sibling checkouts: `root/<repo>/<path>`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def read(self, repo: str, path: str) -> str:
        file = self.root / repo / path
        try:
            return file.read_text(encoding="utf-8")
        except OSError as e:
            raise Unreadable(f"cannot read {file}: {e.strerror or e}") from e


def fetch(url: str, *, attempts: int = 3, pause: float = 2.0) -> str:
    """One file from the network. A server error or a refused burst is tried
    again, said on stderr; a 4xx is the answer."""
    problem = ""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            problem = f"HTTP {e.code}"
            if e.code != 429 and e.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as e:
            problem = str(getattr(e, "reason", None) or e)
        if attempt < attempts:
            print(f"  {url}: {problem}; trying again", file=sys.stderr)
            time.sleep(pause * attempt)
    raise Unreadable(f"cannot read {url}: {problem}")


class Pins:
    """Each consumer at its release pin, from raw.githubusercontent.com."""

    def __init__(self, pins: dict[str, str], fetcher=fetch) -> None:  # type: ignore[no-untyped-def]
        self.pins = pins
        self.fetcher = fetcher

    def read(self, repo: str, path: str) -> str:
        return self.fetcher(RAW_URL.format(repo=repo, ref=self.pins[repo], path=path))


def installer_pins(installer: str) -> dict[str, str]:
    """The `PIN_*` lines of `scripts/install.sh`, by consumer."""
    found: dict[str, str] = {}
    for repo, variable in INSTALLER_PINS.items():
        match = re.search(rf"(?m)^{variable}=([0-9a-f]{{40}})\b", installer)
        if match is None:
            raise Unreadable(f"scripts/install.sh has no {variable}=<40 hex digits> line")
        found[repo] = match[1]
    return found


#: The same patterns `scripts/ship.py` uses to read these pins from the agent.
_WORKBENCH_PIN = re.compile(r"workbench/archive/([0-9a-f]{40})\.tar\.gz")
_SITE_HOST_PIN = re.compile(r'(?m)^SITE_HOST_COMMIT = "([0-9a-f]{40})"')
AGENT_CATALOGUE = "src/eugene_plexus_agent/apps_catalogue.yaml"
AGENT_SITE_HOST = "src/eugene_plexus_agent/site_host.py"


def agent_pins(read) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """The Workbench and site-host pins the agent carries, read through
    `read(path)` from the agent at its own pin."""
    workbench = _WORKBENCH_PIN.search(read(AGENT_CATALOGUE))
    if workbench is None:
        raise Unreadable(f"the agent's {AGENT_CATALOGUE} names no Workbench pin")
    site_host = _SITE_HOST_PIN.search(read(AGENT_SITE_HOST))
    if site_host is None:
        raise Unreadable(f"the agent's {AGENT_SITE_HOST} names no SITE_HOST_COMMIT")
    return {"workbench": workbench[1], "site-host": site_host[1]}


def release_pins(specs: Path, fetcher=fetch) -> dict[str, str]:  # type: ignore[no-untyped-def]
    pins = installer_pins((specs / "scripts" / "install.sh").read_text(encoding="utf-8"))
    agent = Pins({"agent": pins["agent"]}, fetcher)
    pins.update(agent_pins(lambda path: agent.read("agent", path)))
    return pins


# --------------------------------------------------------------------------- #
# What a codegen config names
# --------------------------------------------------------------------------- #


def documents_named(path: str, text: str) -> set[str] | None:
    """The `openapi/...` documents a codegen config generates, or None when the
    config has no list this script knows how to read.

    Python: the strings in the `SPECS_TO_GENERATE` assignment. JavaScript: each
    `input:` of the `SPECS` list. Comments that mention other documents (a
    rename, a history) are not part of either.
    """
    if path.endswith(".mjs"):
        found = set(re.findall(r"""\binput:\s*["'](openapi/[^"']+)["']""", text))
        return found or None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "SPECS_TO_GENERATE" for t in targets):
            return {
                n.value
                for n in ast.walk(value)
                if isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and n.value.startswith("openapi/")
            }
    return None


# --------------------------------------------------------------------------- #
# The rules
# --------------------------------------------------------------------------- #


def documents_in(specs: Path) -> set[str]:
    """Every contract document in the checkout, as `openapi/...` paths."""
    found = {p.relative_to(specs).as_posix() for p in (specs / "openapi").glob("*.yaml")}
    found |= {
        p.relative_to(specs).as_posix() for p in (specs / "openapi" / "components").glob("*.yaml")
    }
    return found


def rule_a(
    specs: Path,
    table: dict[str, Document] = TABLE,
    consumers: dict[str, str] = CONSUMERS,
) -> list[str]:
    """Every document has a row, and every row is true."""
    problems: list[str] = []
    present = documents_in(specs)
    for name in sorted(present - set(table)):
        problems.append(
            f"{name} has no row in the table in scripts/codegen-inputs.py. Name the consumers "
            "that generate it, the document that reaches it, or why nobody does."
        )
    for name in sorted(set(table) - present):
        problems.append(
            f"The table in scripts/codegen-inputs.py has a row for {name}, which does not exist."
        )
    for name, row in sorted(table.items()):
        if not (row.consumers or row.reached_through or row.why_not):
            problems.append(
                f"{name}: its row names no consumer, no document that reaches it, and no reason."
            )
        for repo in row.consumers:
            if repo not in consumers:
                problems.append(f"{name}: its row names {repo}, which is not a consumer.")
        for reaching in row.reached_through:
            if reaching not in present:
                problems.append(f"{name}: reached through {reaching}, which does not exist.")
                continue
            text = (specs / reaching).read_text(encoding="utf-8")
            base = re.escape(Path(name).name)
            if re.search(rf"""\$ref:\s*['"]?[^'"\s#]*{base}""", text) is None:
                problems.append(f"{name}: {reaching} does not $ref it.")
    return problems


def _git(specs: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(specs), *args], capture_output=True, text=True, encoding="utf-8"
    )


def rule_b(
    specs: Path,
    source: Source,
    table: dict[str, Document] = TABLE,
    consumers: dict[str, str] = CONSUMERS,
) -> list[str]:
    """Each consumer's config against the documents its `SPECS_REF` holds."""
    problems: list[str] = []
    for repo, config in consumers.items():
        try:
            ref = source.read(repo, "SPECS_REF").strip()
            text = source.read(repo, config)
        except Unreadable as e:
            problems.append(str(e))
            continue
        if not SHA.fullmatch(ref):
            problems.append(f"{repo}/SPECS_REF holds {ref[:60]!r}, not a 40-digit commit.")
            continue
        if _git(specs, "cat-file", "-e", f"{ref}^{{commit}}").returncode != 0:
            problems.append(
                f"{repo} pins specs {ref[:7]}, which this checkout does not have. "
                "Fetch the full history (git fetch --unshallow) and run again."
            )
            continue
        named = documents_named(config, text)
        if named is None:
            problems.append(f"{repo}/{config} has no list of documents this script can read.")
            continue
        for name, row in table.items():
            if repo not in row.consumers or name in named:
                continue
            if _git(specs, "cat-file", "-e", f"{ref}:{name}").returncode == 0:
                problems.append(
                    f"{repo} pins specs {ref[:7]}, which has {name}; "
                    f"{repo}/{config} does not generate it."
                )
        for name in sorted(named):
            row = table.get(name)
            if row is None or repo not in row.consumers:
                problems.append(
                    f"{repo}/{config} generates {name}, which the table in "
                    f"scripts/codegen-inputs.py does not give {repo}. Add {repo} to its row, "
                    "or take the document out of the config."
                )
    return problems


def check(specs: Path, source: Source) -> list[str]:
    return [*rule_a(specs), *rule_b(specs, source)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--root",
        type=Path,
        help="read the sibling checkouts DIR/<repo>/... instead of each repo at its release pin",
    )
    arguments = parser.parse_args(argv)
    try:
        source: Source
        if arguments.root is not None:
            source = Checkouts(arguments.root)
            where = f"the checkouts under {arguments.root}"
        else:
            source = Pins(release_pins(SPECS))
            where = "each repository at its release pin"
        problems = check(SPECS, source)
    except Unreadable as e:
        problems = [str(e)]
        where = "the pins"
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"ok: {len(TABLE)} documents, {len(CONSUMERS)} consumers, read from {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
