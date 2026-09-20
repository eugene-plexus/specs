"""R3.8 contract and duration-clock regression; no services or configs are read.

Run with a Python that has PyYAML installed. --polyrepo additionally checks
the five active Python consumers. --sabotage mutates in-memory copies only.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import yaml

REPOS = ("agent", "control", "gateway", "inference-driver", "library")


def check(documents: dict[str, str], sources: dict[str, str]) -> list[str]:
    failures = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    schemas = {
        name: yaml.safe_load(body)["components"]["schemas"]
        for name, body in documents.items()
    }
    mode = schemas["common"]["SecurityMode"]
    require("passphrase_file" in mode["enum"], "SecurityMode omits passphrase_file")
    for name in ("agent", "common"):
        require(
            "bcrypt" not in documents[name].lower(), f"{name} still promises bcrypt"
        )
    name_description = schemas["agent"]["RuntimeSpec"]["properties"]["name"][
        "description"
    ]
    require(
        "unique per node" in name_description, "runtime names must be scoped per node"
    )
    local_fit = yaml.safe_load(documents["library"])["paths"]["/v1/models/{id}/fit"][
        "get"
    ]
    require(
        "so `basis` is `metadata` rather than `estimate`"
        not in local_fit["description"],
        "local fit still guarantees metadata for an incomplete shape",
    )
    basis = schemas["library"]["Fit"]["properties"]["basis"]["description"]
    require(
        "per-layer" in basis and "scalar" in basis, "fit basis omits scalar fallback"
    )
    overview = yaml.safe_load(documents["gateway"])["info"]["description"]
    require(
        "diagnosing it is its own piece" not in overview,
        "overhead cause is still unknown",
    )
    backend = schemas["gateway"]["MetricAttempt"]["properties"]["backendMs"][
        "description"
    ]
    require("perf_counter" in backend, "backend metric omits the duration clock")
    tiers = schemas["gateway"]["ModelRoutingInfo"]["properties"]["tiers"]["description"]
    require("An empty tier is kept" in tiers, "tier contract loses empty positions")
    require("virtual alias" in tiers, "tier contract omits the alias exception")

    for filename, source in sources.items():
        tree = ast.parse(source, filename=filename)
        time_names = {"time"}
        clock_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                time_names.update(
                    n.asname or n.name for n in node.names if n.name == "time"
                )
            elif isinstance(node, ast.ImportFrom) and node.module == "time":
                clock_names.update(
                    n.asname or n.name
                    for n in node.names
                    if n.name in {"monotonic", "monotonic_ns"}
                )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            wrong = isinstance(func, ast.Name) and func.id in clock_names
            wrong |= (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in time_names
                and func.attr in {"monotonic", "monotonic_ns"}
            )
            require(
                not wrong, f"{filename}:{node.lineno}: use perf_counter for durations"
            )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--specs", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--polyrepo", type=Path)
    parser.add_argument("--sabotage", action="store_true")
    args = parser.parse_args()
    documents = {
        name: (args.specs / "openapi" / filename).read_text(encoding="utf-8")
        for name, filename in (
            ("agent", "agent.yaml"),
            ("common", "components/common.yaml"),
            ("gateway", "gateway.yaml"),
            ("library", "library.yaml"),
        )
    }
    sources = {}
    if args.polyrepo:
        for repo in REPOS:
            files = list((args.polyrepo / repo / "src").rglob("*.py"))
            assert files, f"missing consumer source tree: {repo}"
            sources.update(
                (str(path), path.read_text(encoding="utf-8"))
                for path in files
                if "_generated" not in path.parts
            )
    failures = check(documents, sources)
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        raise SystemExit(1)
    print(f"PASS contract sweep; {len(sources)} consumer source files checked")
    if not args.sabotage:
        return
    mutations = [
        ("common", "        - passphrase_file\n", ""),
        ("common", "Argon2id", "bcrypt"),
        ("agent", "Argon2id", "bcrypt"),
        ("agent", "unique per node", "unique per install"),
        ("library", "scalar", "uniform"),
        ("gateway", "perf_counter", "monotonic"),
        ("gateway", "An empty tier is kept", "Empty tiers are omitted"),
        ("gateway", "virtual alias", "alias"),
    ]
    for name, old, new in mutations:
        assert old in documents[name], (name, old)
        mutated = dict(documents)
        mutated[name] = mutated[name].replace(old, new)
        assert check(mutated, sources), f"escaped: {name} {old}"
        print(f"CAUGHT {name}: {old.strip()}")
    for spelling in (
        "import time; time.monotonic()",
        "import time as t; t.monotonic_ns()",
        "from time import monotonic as clock; clock()",
    ):
        mutated_sources = dict(sources, clock_regression=spelling)
        assert check(documents, mutated_sources), f"escaped: {spelling}"
        print(f"CAUGHT {spelling}")
    assert not check(documents, sources)
    print("11/11 caught; unchanged baseline passes")


if __name__ == "__main__":
    main()
