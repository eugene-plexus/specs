"""Generate self-contained installers from release/manifest.json and its dependency lock.

After changing dependencies: --resolve --uv <uv executable>. After changing
component pins: run without flags. CI uses --check. Resolution is explicit;
ordinary regeneration never contacts a package index.
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
REPOS = (
    "agent",
    "control",
    "gateway",
    "inference-driver",
    "library",
    "tool-driver",
    "ui",
    "workbench",
)


def generate(*, check=False, resolve=False, uv="uv"):
    release = ROOT / "release"
    manifest = json.loads((release / "manifest.json").read_text())
    if resolve:
        deps = set()
        for repo in REPOS:
            project = tomllib.loads((ROOT.parent / repo / "pyproject.toml").read_text())
            deps.update(project["project"].get("dependencies", []))
            deps.update(project["build-system"]["requires"])
            if repo == "agent":
                deps.update(project["project"]["optional-dependencies"]["service"])
        (release / "requirements.in").write_text("\n".join(sorted(deps)) + "\n", encoding="utf-8")
        subprocess.run(
            [
                uv,
                "pip",
                "compile",
                str(release / "requirements.in"),
                "--universal",
                "--python-version",
                manifest["python"],
                "--generate-hashes",
                "--no-annotate",
                "--no-header",
                "--output-file",
                str(release / "requirements.lock"),
                "--quiet",
            ],
            check=True,
        )
    lock = (release / "requirements.lock").read_text(encoding="utf-8")
    constraints = (
        "\n".join(
            line.rstrip(" \\") for line in lock.splitlines() if line and not line[0].isspace()
        )
        + "\n"
    )
    if check:
        if (release / "constraints.txt").read_text(encoding="utf-8") != constraints:
            raise ValueError("release constraints are stale")
    else:
        (release / "constraints.txt").write_text(constraints, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(lock.encode()).hexdigest()
    if check and manifest["dependenciesSha256"] != digest:
        raise ValueError("release manifest dependency digest is stale")
    manifest["dependenciesSha256"] = digest
    components = manifest["components"]
    if not re.fullmatch(r"3\.\d+(?:\.\d+)?", manifest["python"]) or not re.fullmatch(
        r"\d+\.\d+\.\d+", manifest["uvMinimum"]
    ):
        raise ValueError("invalid release tool versions")
    if set(components) != set(REPOS) - {"workbench"} or any(
        not re.fullmatch("[a-f0-9]{40}", v) for v in components.values()
    ):
        raise ValueError("release components must be seven full commit IDs")
    for name in ("install.sh", "install.ps1"):
        path = ROOT / "scripts" / name
        before = path.read_text(encoding="utf-8")
        if "# BEGIN GENERATED DEPENDENCIES\n" not in before:
            raise ValueError(f"{name}: missing dependency generation block")
        body = before
        if name.endswith(".sh"):
            body = re.sub(r"(?m)^PY_VERSION=[0-9.]+$", "PY_VERSION=" + manifest["python"], body)
            body = re.sub(r"(?m)^UV_MINIMUM=[0-9.]+$", "UV_MINIMUM=" + manifest["uvMinimum"], body)
        else:
            body = re.sub(
                r'(?m)^\$PyVersion = "[0-9.]+"$',
                lambda m: '$PyVersion = "' + manifest["python"] + '"',
                body,
            )
            body = re.sub(
                r'(?m)^\$UvMinimum = \[version\]"[0-9.]+"$',
                lambda m: '$UvMinimum = [version]"' + manifest["uvMinimum"] + '"',
                body,
            )
        for repo, sha in components.items():
            if name.endswith(".sh"):
                key = "DRIVER" if repo == "inference-driver" else repo.upper().replace("-", "_")
                body = re.sub(rf"(?m)^PIN_{key}=[a-f0-9]{{40}}", f"PIN_{key}={sha}", body)
            else:
                body = re.sub(rf'("{repo}"\s*=\s*")[a-f0-9]{{40}}', lambda m: m[1] + sha, body)
        if name.endswith(".sh"):
            block = (
                'in_prefix "$PYBIN" -c \'import pathlib,sys; '
                'pathlib.Path(sys.argv[1]).write_text(sys.stdin.read(), '
                'encoding="utf-8", newline="\\n")\' "$PREFIX/release-requirements.lock" '
                "<<'EUGENE_REQUIREMENTS'\n"
                + lock
                + "EUGENE_REQUIREMENTS\n"
            )
        else:
            block = (
                "$ReleaseRequirements = @'\n" + lock + "'@\n"
                '[System.IO.File]::WriteAllText((Join-Path $Prefix "release-requirements.lock"), '
                '($ReleaseRequirements.Replace("`r`n", "`n") + "`n"), '
                '[System.Text.UTF8Encoding]::new($false))\n'
            )
        body = re.sub(
            r"(?ms)^# BEGIN GENERATED DEPENDENCIES\n.*?^# END GENERATED DEPENDENCIES",
            lambda m: "# BEGIN GENERATED DEPENDENCIES\n" + block + "# END GENERATED DEPENDENCIES",
            body,
        )
        if check:
            if body != before:
                raise ValueError(f"{name} is stale; run scripts/release-inputs.py")
        else:
            path.write_text(body, encoding="utf-8", newline="\n")
    if not check:
        (release / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--resolve", action="store_true")
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args()
    if args.check and args.resolve:
        parser.error("--check and --resolve are exclusive")
    generate(**vars(args))
