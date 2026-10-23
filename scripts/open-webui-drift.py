#!/usr/bin/env python3
"""Inspect an Open WebUI wheel without importing or starting its code."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import yaml


#: Names the entry sets for a library Open WebUI installs, so its own source never reads them:
#: huggingface_hub's cache directory, chromadb's telemetry switch and scarf's two opt-outs.
#: A name here is not checked for drift. Remove one when its library leaves the app.
READ_BY_DEPENDENCIES = frozenset(
    {"HF_HOME", "ANONYMIZED_TELEMETRY", "DO_NOT_TRACK", "SCARF_NO_ANALYTICS"}
)


def inspect_sources(sources: dict[str, str], environment: dict[str, str]) -> list[str]:
    reads: set[str] = set()
    findings: list[str] = []
    plugin_default = None
    for file, source in sources.items():
        tree = ast.parse(source, filename=file)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = ast.unparse(node.func)
            if function not in {"os.getenv", "os.environ.get", "getenv"}:
                continue
            name = node.args[0]
            if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
                continue
            name = name.value
            reads.add(name)
            default = (
                node.args[1]
                if len(node.args) > 1
                else next(
                    (k.value for k in node.keywords if k.arg == "default"),
                    ast.Constant(None),
                )
            )
            if name == "ENABLE_PLUGINS":
                plugin_default = (
                    default.value
                    if isinstance(default, ast.Constant)
                    else ast.unparse(default)
                )
            if name.endswith("_BASE_URL") and name not in environment:
                if any(
                    (isinstance(n, ast.Name) and n.id == "OPENAI_API_BASE_URL")
                    or (
                        isinstance(n, ast.Constant)
                        and isinstance(n.value, str)
                        and "api.openai.com" in n.value
                    )
                    for n in ast.walk(default)
                ):
                    findings.append(
                        f"{file}:{node.lineno}: {name} falls back to OpenAI but is not set"
                    )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Subscript)
                and ast.unparse(node.value) == "os.environ"
            ):
                if isinstance(node.slice, ast.Constant) and isinstance(
                    node.slice.value, str
                ):
                    reads.add(node.slice.value)
    reads |= READ_BY_DEPENDENCIES
    for name in sorted(environment.keys() - reads):
        findings.append(
            f"{name}: this version no longer reads this environment variable"
        )
    if plugin_default is None:
        findings.append("ENABLE_PLUGINS: no environment reader found")
    else:
        findings.append(f"INFO ENABLE_PLUGINS default: {plugin_default}")
        if "ENABLE_PLUGINS" not in environment:
            findings.append(
                "ENABLE_PLUGINS: the catalogue must choose its behavior explicitly"
            )
    return findings


def failures(findings: list[str]) -> list[str]:
    return [f for f in findings if not f.startswith("INFO ")]


def download(version: str, destination: Path) -> None:
    with urllib.request.urlopen(
        f"https://pypi.org/pypi/open-webui/{version}/json", timeout=30
    ) as response:
        release = json.load(response)
    wheel = next(f for f in release["urls"] if f["packagetype"] == "bdist_wheel")
    digest = hashlib.sha256()
    with (
        urllib.request.urlopen(wheel["url"], timeout=60) as response,
        destination.open("wb") as output,
    ):
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != wheel["digests"]["sha256"]:
        raise ValueError("The downloaded wheel does not match PyPI's SHA-256")


def inspect_wheel(path: Path, environment: dict[str, str]) -> list[str]:
    with zipfile.ZipFile(path) as wheel:
        sources = {
            n: wheel.read(n).decode("utf-8")
            for n in wheel.namelist()
            if n.startswith("open_webui/") and n.endswith(".py")
        }
    if not {"open_webui/config.py", "open_webui/env.py"} <= sources.keys():
        raise ValueError("The wheel has no Open WebUI config.py and env.py")
    return inspect_sources(sources, environment)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument(
        "--wheel", type=Path, help="Inspect an already downloaded wheel"
    )
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "agent/src/eugene_plexus_agent/apps_catalogue.yaml",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+(?:[a-z0-9.]*)", args.version):
        parser.error("version must be one exact release")
    entry = next(
        e
        for e in yaml.safe_load(args.catalogue.read_text(encoding="utf-8"))
        if e["id"] == "open-webui"
    )
    try:
        if args.wheel:
            findings = inspect_wheel(args.wheel, entry["environment"])
        else:
            with tempfile.TemporaryDirectory(prefix="open-webui-drift-") as temp:
                path = Path(temp) / "open-webui.whl"
                download(args.version, path)
                findings = inspect_wheel(path, entry["environment"])
    except (OSError, ValueError, StopIteration, zipfile.BadZipFile) as exc:
        print(f"Could not inspect Open WebUI {args.version}: {exc}")
        return 1
    for finding in findings:
        print(finding)
    return 1 if failures(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
