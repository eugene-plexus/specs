"""Reuse branch CI only when its recorded immutable inputs match exactly."""

from __future__ import annotations

import io
import json
import re
import subprocess
import zipfile
from collections.abc import Callable
from typing import Any

REPOSITORY = "eugene-plexus/specs"


class PendingPlan(RuntimeError):
    """A running workflow has not yet published its immutable inputs."""


def make_receipt(
    specs_commit: str,
    base: str,
    checks: dict[str, bool],
    candidates: dict[str, str],
    main_refs: dict[str, str],
) -> dict[str, Any]:
    for value in (specs_commit, base, *candidates.values(), *main_refs.values()):
        if not re.fullmatch(r"[a-f0-9]{40}", value):
            raise ValueError(f"CI inputs must be immutable commit IDs: {value!r}")
    return {
        "format": 1,
        "specs_commit": specs_commit,
        "base": base,
        "checks": checks,
        "candidates": candidates,
        "main_refs": main_refs,
    }


def equivalent_run(
    expected: dict[str, Any],
    branch: str,
    runs: list[dict[str, Any]],
    read: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> str | None:
    pending = []
    failed = []
    for run in runs:
        if (
            run.get("head_sha") != expected["specs_commit"]
            or run.get("head_branch") != branch
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or run.get("event") not in {"push", "workflow_dispatch"}
            or (branch == "main" and run.get("event") != "workflow_dispatch")
            or run.get("conclusion") == "cancelled"
        ):
            continue
        receipt = read(run)
        active = run.get("status") in {
            "queued",
            "in_progress",
            "waiting",
            "pending",
            "requested",
        }
        if receipt is None and active:
            pending.append(run["html_url"])
        elif receipt == expected:
            if active or run.get("conclusion") == "success":
                return run["html_url"]
            failed.append(run["html_url"])
    if failed:
        raise RuntimeError(
            f"The same inputs already failed: {failed[0]}. Inspect and fix the cause; no run dispatched."
        )
    if pending:
        raise PendingPlan(
            f"A run is still recording its inputs: {pending[0]}. Check again after its plan finishes; no run dispatched."
        )
    return None


def api(path: str) -> bytes:
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/{path}"], capture_output=True
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def read_receipt(run: dict[str, Any]) -> dict[str, Any] | None:
    name = f"ci-inputs-{run.get('run_attempt', 1)}"
    # This workflow has fewer than 100 artifacts; follow pages rather than
    # silently treating a later receipt as absent if that changes.
    found = []
    page = 1
    while True:
        body = json.loads(
            api(f"actions/runs/{run['id']}/artifacts?per_page=100&page={page}")
        )
        artifacts = body["artifacts"]
        found.extend(a for a in artifacts if a["name"] == name and not a["expired"])
        if len(artifacts) < 100:
            break
        page += 1
    if not found:
        return None
    if len(found) != 1:
        raise RuntimeError(
            f"Run {run['id']} has more than one current CI input receipt"
        )
    with zipfile.ZipFile(
        io.BytesIO(api(f"actions/artifacts/{found[0]['id']}/zip"))
    ) as bundle:
        info = bundle.getinfo("ci-inputs.json")
        if info.file_size > 64_000:
            raise RuntimeError(f"Run {run['id']}'s CI input receipt is too large")
        return json.loads(bundle.read(info))


def find_equivalent(expected: dict[str, Any], branch: str) -> str | None:
    body = json.loads(
        api(
            f"actions/workflows/ci.yml/runs?head_sha={expected['specs_commit']}&per_page=100"
        )
    )
    return equivalent_run(expected, branch, body["workflow_runs"], read_receipt)
