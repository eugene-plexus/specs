"""Publish Edge from a verified immutable container image; CI does not gate it."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ci_plan import git

REPOSITORY = "eugene-plexus/specs"
IMAGE = "ghcr.io/eugene-plexus/control-plane"
SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
Receipt = dict[str, Any]
RunLookup = Callable[[str, str], Receipt | None]


def fingerprint(root: Path, ref: str, *, image: bool = False) -> str:
    digest = hashlib.sha256()
    tree = subprocess.check_output(["git", "-C", str(root), "ls-tree", "-r", "-z", ref])
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        name = raw_name.decode("utf-8")
        path = Path(name)
        if (
            path.suffix == ".md" and (name.startswith("docs/") or len(path.parts) == 1)
        ) or name == "LICENSE":
            continue
        if image and not (
            name.startswith(("docker/", "unraid/", "release/", "platform/", "scripts/"))
            or name == ".github/workflows/container.yml"
            or name in {".dockerignore", ".gitattributes"}
        ):
            continue
        content = metadata
        if name == "release/manifest.json":
            content = json.dumps(
                json.loads(git(root, "show", f"{ref}:{name}")),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        digest.update(raw_name + b"\0" + content + b"\0")
    return digest.hexdigest()


def ancestor(root: Path, older: str, newer: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer], check=False
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("could not verify Edge ancestry")
    return result.returncode == 0


def choose(
    root: Path,
    head: str,
    marker: str | None,
    run: RunLookup,
    *,
    limit: int = 100,
) -> Receipt | None:
    """The newest descendant of the marker whose container image was built and
    verified (`container.yml`'s build-verify-publish, for the same image inputs).

    **Nothing else gates Edge** (Troy, 2026-10-19, restated 2026-11-06): CI's
    result does not hold it. Edge is for rapid development and drives the
    maintainer's own testbed; a red CI is reported by the session-start warning
    and fixed before a release, whose qualification keeps every gate. The image
    receipt stays because Edge publishes those bytes: an image that did not
    build, or did not start in its own checks, has nothing to publish.
    """
    if not SHA.fullmatch(head) or (marker is not None and not SHA.fullmatch(marker)):
        raise ValueError("Edge candidates must be full commit IDs")
    if marker is not None and not ancestor(root, marker, head):
        raise ValueError("the existing Edge marker is not an ancestor of main; refusing to move it")
    history = git(root, "rev-list", "--first-parent", f"--max-count={limit}", head).splitlines()
    image_hashes: dict[str, str] = {}
    receipts: dict[str, Receipt | None] = {}

    def hashed(commit: str) -> str:
        if commit not in image_hashes:
            image_hashes[commit] = fingerprint(root, commit, image=True)
        return image_hashes[commit]

    def built(commit: str) -> Receipt | None:
        if commit not in receipts:
            receipts[commit] = run("container.yml", commit)
        return receipts[commit]

    for position, candidate in enumerate(history):
        if candidate == marker:
            break
        # First-parent history passes through merged branches and then older main
        # commits the marker has already passed; only a descendant moves Edge forward.
        if marker is not None and not ancestor(root, marker, candidate):
            continue
        image_hash = hashed(candidate)
        for previous in history[position:]:
            if hashed(previous) != image_hash:
                continue
            receipt = built(previous)
            if receipt is not None:
                return {
                    "specsCommit": candidate,
                    "previousMarker": marker,
                    "imageCommit": previous,
                    "imageRun": receipt["id"],
                    "imageFingerprint": image_hash,
                }
    return None


def api(path: str, *, method: str = "GET", body: Receipt | None = None) -> Any:
    command = ["gh", "api", "--method", method, f"repos/{REPOSITORY}/{path}"]
    if body is not None:
        command.extend(["--input", "-"])
    return json.loads(
        subprocess.check_output(
            command, input=json.dumps(body) if body is not None else None, text=True
        )
    )


def successful_run(workflow: str, commit: str) -> Receipt | None:
    query = urlencode({"head_sha": commit, "event": "push", "branch": "main", "per_page": 100})
    body = api(f"actions/workflows/{workflow}/runs?{query}")
    runs = body.get("workflow_runs") if isinstance(body, dict) else None
    if not isinstance(runs, list):
        raise ValueError("GitHub did not return workflow receipts")
    matching = [
        entry
        for entry in runs
        if entry.get("head_sha") == commit
        and entry.get("event") == "push"
        and entry.get("head_branch") == "main"
    ]
    newest = max(matching, key=lambda entry: entry["id"], default=None)
    if newest is not None:
        newest = api(f"actions/runs/{newest['id']}")
        if (
            not isinstance(newest, dict)
            or newest.get("head_sha") != commit
            or newest.get("event") != "push"
            or newest.get("head_branch") != "main"
        ):
            raise ValueError("GitHub's exact workflow receipt does not match the candidate")
    if (
        newest is not None
        and newest.get("status") == "completed"
        and newest.get("conclusion") == "success"
    ):
        if workflow == "container.yml" and "build-verify-publish" not in passed_jobs(newest):
            return None
        return newest
    return None


def latest_jobs(receipt: Receipt) -> list[Receipt]:
    body = api(f"actions/runs/{receipt['id']}/jobs?per_page=100&filter=latest")
    jobs = body.get("jobs") if isinstance(body, dict) else None
    if not isinstance(jobs, list) or body.get("total_count", 0) > 100:
        raise ValueError("GitHub did not return complete Edge gate jobs")
    return jobs


def passed_jobs(receipt: Receipt) -> set[str]:
    return {job["name"] for job in latest_jobs(receipt) if job.get("conclusion") == "success"}


def current_marker() -> str | None:
    refs = api("git/matching-refs/heads/edge")
    if not isinstance(refs, list):
        raise ValueError("GitHub did not return branch references")
    exact = [ref for ref in refs if ref.get("ref") == "refs/heads/edge"]
    if not exact:
        return None
    commit = exact[0].get("object", {}).get("sha")
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise ValueError("the existing Edge marker is malformed")
    return commit


def image_digest(reference: str) -> str:
    digest = subprocess.check_output(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            reference,
            "--format",
            "{{.Manifest.Digest}}",
        ],
        text=True,
    ).strip()
    if not DIGEST.fullmatch(digest):
        raise ValueError("the verified image has no valid registry digest")
    return digest


def image_receipt(root: Path, receipt: Receipt) -> str:
    body = api(f"actions/runs/{receipt['imageRun']}/artifacts?per_page=100")
    artifacts = body.get("artifacts") if isinstance(body, dict) else None
    if not isinstance(artifacts, list) or body.get("total_count", 0) > 100:
        raise ValueError("could not read complete image build artifacts")
    matching = [
        artifact
        for artifact in artifacts
        if artifact.get("name") == "verified-container" and not artifact.get("expired")
    ]
    if len(matching) != 1:
        raise ValueError("the successful image build has no unique retained digest receipt")
    archive = subprocess.check_output(
        ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{matching[0]['id']}/zip"]
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        built = json.loads(bundle.read("image-receipt.json"))
    if (
        built.get("specsCommit") != receipt["imageCommit"]
        or built.get("imageFingerprint") != receipt["imageFingerprint"]
        or fingerprint(root, receipt["imageCommit"], image=True) != receipt["imageFingerprint"]
        or not isinstance(built.get("digest"), str)
        or not DIGEST.fullmatch(built["digest"])
    ):
        raise ValueError("the image digest receipt does not match the verified build inputs")
    return built["digest"]


def publish(root: Path, receipt: Receipt) -> None:
    previous = current_marker()
    if previous != receipt["previousMarker"]:
        raise ValueError("the Edge marker changed during evaluation; refusing a stale publication")
    candidate = receipt["specsCommit"]
    if previous is not None and not ancestor(root, previous, candidate):
        raise ValueError("refusing to move Edge backwards")
    digest = image_receipt(root, receipt)
    if image_digest(f"{IMAGE}@{digest}") != digest:
        raise ValueError("the retained tested image digest is unavailable")
    subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "create",
            "--prefer-index=false",
            "--tag",
            f"{IMAGE}:edge",
            f"{IMAGE}@{digest}",
        ],
        check=True,
    )
    if image_digest(f"{IMAGE}:edge") != digest:
        raise ValueError("the Edge image digest differs from the tested image; marker not moved")
    receipt["imageDigest"] = digest
    if previous is None:
        api("git/refs", method="POST", body={"ref": "refs/heads/edge", "sha": candidate})
    else:
        api("git/refs/heads/edge", method="PATCH", body={"sha": candidate, "force": False})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    if os.environ.get("EDGE_PUBLICATION_PAUSED", "").lower() == "true":
        raise RuntimeError("Edge publication is paused by the repository safety hold")
    root = Path(__file__).resolve().parent.parent
    head = git(root, "rev-parse", "HEAD").strip()
    receipt = choose(root, head, current_marker(), successful_run)
    if receipt is None:
        print(
            "No newer candidate has a verified image receipt; Edge is unchanged."
        )
        return
    if not arguments.dry_run:
        publish(root, receipt)
        Path("edge-receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
