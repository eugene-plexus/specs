"""Resolve nested release pins and bind publication to full qualification evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from ci_plan import COMPONENTS, git
from edge_marker import DIGEST, REPOSITORY, SHA, api, fingerprint

VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z]+\.[0-9]+)?")


def resolve(root: Path, agent: Path) -> dict[str, str]:
    import yaml

    pins = json.loads((root / "release/manifest.json").read_text(encoding="utf-8"))["components"]
    if set(pins) != COMPONENTS:
        raise ValueError("the release must name exactly seven component pins")
    catalogue = yaml.safe_load(
        (agent / "src/eugene_plexus_agent/apps_catalogue.yaml").read_text(encoding="utf-8")
    )
    entries = [entry for entry in catalogue if entry["id"] == "workbench"]
    if len(entries) != 1:
        raise ValueError("the pinned agent must declare one Workbench archive")
    workbench = entries[0]["version"]
    if (
        entries[0]["source"]
        != f"https://github.com/eugene-plexus/workbench/archive/{workbench}.tar.gz"
    ):
        raise ValueError("Workbench's archive and version pin disagree")
    pins["workbench"] = workbench
    tree = ast.parse((agent / "src/eugene_plexus_agent/site_host.py").read_text(encoding="utf-8"))
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SITE_HOST_COMMIT"
            for target in statement.targets
        ):
            pins["site-host"] = ast.literal_eval(statement.value)
            break
    if set(pins) != COMPONENTS | {"workbench", "site-host"} or any(
        not isinstance(value, str) or not SHA.fullmatch(value) for value in pins.values()
    ):
        raise ValueError("every shipped component and nested app must have a full commit pin")
    shell = (root / "scripts/install.sh").read_text(encoding="utf-8")
    site = re.search(r"^PIN_SITE_HOST=([a-f0-9]{40})\b", shell, re.MULTILINE)
    if site is not None and site.group(1) != pins["site-host"]:
        raise ValueError("the installer and pinned agent disagree about site-host")
    return pins


def acceptance_digest(root: Path, commit: str, record: str) -> str:
    path = Path(record)
    if (
        not record.startswith("docs/acceptance/")
        or path.suffix != ".md"
        or ".." in path.parts
        or "\\" in record
    ):
        raise ValueError("reviewed acceptance must be a committed docs/acceptance Markdown record")
    content = git(root, "show", f"{commit}:{record}")
    if not content.strip():
        raise ValueError("the reviewed acceptance record is empty")
    return hashlib.sha256(content.encode()).hexdigest()


def validate(root: Path, report: dict[str, Any], run: dict[str, Any], tag: str) -> str:
    if (
        run.get("path", "").split("@")[0] != ".github/workflows/release-qualification.yml"
        or run.get("event") != "workflow_dispatch"
        or run.get("conclusion") != "success"
        or run.get("status") != "completed"
    ):
        raise ValueError(
            "publication requires a completed successful Release qualification workflow"
        )
    if (run.get("head_repository") or {}).get("full_name") != REPOSITORY:
        raise ValueError("the qualification must belong to the Eugene specs repository")
    source = report.get("specsCommit", "")
    if not SHA.fullmatch(source) or source != run.get("head_sha"):
        raise ValueError("the qualification report does not match its workflow commit")
    if not VERSION.fullmatch(tag) or report.get("releaseTag") != tag:
        raise ValueError("the qualified image was not built for this release tag")
    if (
        git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}").strip()
        != git(root, "rev-parse", "HEAD").strip()
    ):
        raise ValueError("the checkout is not the requested release tag")
    expected = fingerprint(root, "HEAD")
    if report.get("runtimeFingerprint") != expected or fingerprint(root, source) != expected:
        raise ValueError("release inputs changed after qualification")
    record = report.get("acceptanceRecord", "")
    if report.get("acceptanceSha256") != acceptance_digest(root, source, record):
        raise ValueError("the reviewed acceptance record does not match qualification")
    digest = report.get("imageDigest", "")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ValueError("qualification did not retain a valid tested image digest")
    return digest


def qualified_digest(root: Path, run_id: str, tag: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("a successful qualification run ID is required before publishing")
    run = api(f"actions/runs/{run_id}")
    body = api(f"actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = body.get("artifacts") if isinstance(body, dict) else None
    if not isinstance(artifacts, list) or body.get("total_count", 0) > 100:
        raise ValueError("could not read complete qualification artifacts")
    matching = [
        artifact
        for artifact in artifacts
        if artifact.get("name") == "release-qualification" and not artifact.get("expired")
    ]
    if len(matching) != 1:
        raise ValueError("the run has no unique retained Release qualification receipt")
    archive = subprocess.check_output(
        ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{matching[0]['id']}/zip"]
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        report = json.loads(bundle.read("qualification.json"))
    return validate(root, report, run, tag)


def output(values: dict[str, str]) -> None:
    if target := os.environ.get("GITHUB_OUTPUT"):
        with open(target, "a", encoding="utf-8", newline="\n") as stream:
            for name, value in values.items():
                stream.write(f"{name}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    resolver = commands.add_parser("resolve")
    resolver.add_argument("--agent", type=Path, required=True)
    resolver.add_argument("--output", type=Path, required=True)
    recorder = commands.add_parser("record")
    recorder.add_argument("--pins", type=Path, required=True)
    recorder.add_argument("--release-tag", required=True)
    recorder.add_argument("--acceptance-record", required=True)
    recorder.add_argument("--digest", required=True)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if arguments.command == "resolve":
        pins = resolve(root, arguments.agent)
        arguments.output.write_text(
            json.dumps(pins, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        matrix = {
            "include": [
                {"repository": name, "commit": commit, "os": platform}
                for name, commit in sorted(pins.items())
                for platform in (
                    ["ubuntu-latest"] if name == "ui" else ["ubuntu-latest", "windows-latest"]
                )
            ]
        }
        output({"matrix": json.dumps(matrix, separators=(",", ":"))})
    elif arguments.command == "record":
        commit = git(root, "rev-parse", "HEAD").strip()
        if not VERSION.fullmatch(arguments.release_tag) or not DIGEST.fullmatch(arguments.digest):
            raise ValueError("qualification must retain a release tag and tested digest")
        report = {
            "specsCommit": commit,
            "releaseTag": arguments.release_tag,
            "runtimeFingerprint": fingerprint(root, commit),
            "imageDigest": arguments.digest,
            "components": json.loads(arguments.pins.read_text(encoding="utf-8")),
            "acceptanceRecord": arguments.acceptance_record,
            "acceptanceSha256": acceptance_digest(root, commit, arguments.acceptance_record),
        }
        Path("qualification.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(json.dumps(report, indent=2))
    else:
        digest = qualified_digest(
            root, os.environ.get("QUALIFICATION_RUN", ""), os.environ.get("RELEASE_TAG", "")
        )
        output({"digest": digest})
        print(f"Qualified image: {digest}")


if __name__ == "__main__":
    main()
