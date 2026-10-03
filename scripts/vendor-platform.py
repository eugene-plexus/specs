"""Deterministically vendor a versioned platform snapshot into sibling repositories.

Usage: python scripts/vendor-platform.py [--check] [--repo agent] [--root ..]
No dependency on a shared runtime package; every consumer remains standalone.
"""

import argparse
import hashlib
import json
from pathlib import Path

SPECS = Path(__file__).resolve().parent.parent


def vendor(root: Path, *, check: bool, repo: str | None = None) -> None:
    manifest = json.loads((SPECS / "platform/manifest.json").read_text(encoding="utf-8"))
    snapshot = SPECS / "platform" / manifest["version"]
    consumers: dict[str, dict[str, bytes]] = {}
    for source, destinations in manifest["modules"].items():
        data = (snapshot / source).read_text(encoding="utf-8").encode()
        for name, relative in destinations.items():
            consumers.setdefault(name, {})[relative] = data
    for source, destinations in manifest.get("contracts", {}).items():
        data = (SPECS / source).read_text(encoding="utf-8").encode()
        for name, relative in destinations.items():
            consumers.setdefault(name, {})[relative] = data
    checker = (SPECS / "scripts/check-vendored.py").read_bytes().replace(b"\r\n", b"\n")
    for name, files in consumers.items():
        if repo is not None and name != repo:
            continue
        files["scripts/check-vendored.py"] = checker
        lock = {
            "format": 1,
            "source": "eugene-plexus/specs/platform",
            "version": manifest["version"],
            "files": {
                p: {"sha256": hashlib.sha256(data).hexdigest()} for p, data in sorted(files.items())
            },
        }
        files["VENDORED.json"] = (json.dumps(lock, indent=2) + "\n").encode()
        for relative, data in files.items():
            path = (root / name / relative).resolve()
            if not path.is_relative_to((root / name).resolve()):
                raise ValueError("invalid destination")
            if check:
                if not path.exists() or path.read_bytes().replace(b"\r\n", b"\n") != data:
                    raise ValueError(f"{path}: regenerate from platform/{manifest['version']}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--repo")
    parser.add_argument("--root", type=Path, default=SPECS.parent)
    args = parser.parse_args()
    vendor(args.root, check=args.check, repo=args.repo)
