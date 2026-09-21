"""Package committed installers and their exact component pins for a release.

Reads Git blobs, not checkout bytes (Windows CRLF must not change checksums).
This fixes Eugene source versions; uv, Python patch versions, transitive Python
dependencies, model catalogue entries and downloaded engines remain upstream.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = {"agent", "control", "gateway", "inference-driver", "library", "ui"}


def pins(shell: bytes, powershell: bytes) -> dict[str, str]:
    posix = {name.lower().replace("_", "-"): sha for name, sha in
             re.findall(r"^PIN_([A-Z_]+)=([0-9a-f]{40})\b", shell.decode(), re.M)}
    if "driver" in posix:
        posix["inference-driver"] = posix.pop("driver")
    windows = dict(re.findall(r'^\s*"([a-z-]+)"\s*=\s*"([0-9a-f]{40})"', powershell.decode(), re.M))
    if set(posix) != COMPONENTS or windows != posix:
        raise ValueError("installers must pin the same six components to full commit IDs")
    return posix


def package(version: str, ref: str, output: Path) -> dict:
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[a-z]+\.\d+)?", version):
        raise ValueError("expected a version such as v0.1.0-alpha.1")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args])
    commit = git("rev-parse", "--verify", ref + "^{commit}").decode().strip()
    files = {name: git("show", f"{commit}:scripts/{name}") for name in ("install.sh", "install.ps1")}
    components = pins(files["install.sh"], files["install.ps1"])
    manifest = {"version": version, "specsCommit": commit, "components": components,
                "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                                 "source": f"https://raw.githubusercontent.com/eugene-plexus/specs/{commit}/scripts/{name}"}
                          for name, data in files.items()},
                "container": f"ghcr.io/eugene-plexus/control-plane:{version}",
                "scope": "Eugene source pins; upstream tools, Python dependencies, engines and models are not locked"}
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()), encoding="ascii", newline="\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.version, args.ref, args.output), indent=2))
