"""Deterministically vendor a versioned platform snapshot into sibling repositories.

Usage: python scripts/vendor-platform.py [--check] [--repo agent] [--root ..]
No dependency on a shared runtime package; every consumer remains standalone.
"""

import argparse
import hashlib
import json
from pathlib import Path

SPECS = Path(__file__).resolve().parent.parent
LOCK = "VENDORED.json"


def planned(specs: Path = SPECS) -> dict[str, dict[str, tuple[str, bytes]]]:
    """Every file vendoring writes, per consumer: relative path -> (source, bytes).

    The source names where the bytes come from in this repository; the lock
    (`VENDORED.json`) is generated from the other files and names itself."""
    manifest = json.loads((specs / "platform/manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    consumers: dict[str, dict[str, tuple[str, bytes]]] = {}
    for source, destinations in manifest["modules"].items():
        label = f"platform/{version}/{source}"
        data = (specs / label).read_text(encoding="utf-8").encode()
        for name, relative in destinations.items():
            consumers.setdefault(name, {})[relative] = (label, data)
    for source, destinations in manifest.get("contracts", {}).items():
        data = (specs / source).read_text(encoding="utf-8").encode()
        for name, relative in destinations.items():
            consumers.setdefault(name, {})[relative] = (source, data)
    checker = (specs / "scripts/check-vendored.py").read_bytes().replace(b"\r\n", b"\n")
    for files in consumers.values():
        files["scripts/check-vendored.py"] = ("scripts/check-vendored.py", checker)
        lock = {
            "format": 1,
            "source": "eugene-plexus/specs/platform",
            "version": version,
            "files": {
                p: {"sha256": hashlib.sha256(data).hexdigest()}
                for p, (_, data) in sorted(files.items())
            },
        }
        files[LOCK] = (LOCK, (json.dumps(lock, indent=2) + "\n").encode())
    return consumers


def vendor(root: Path, *, check: bool, repo: str | None = None) -> None:
    version = json.loads((SPECS / "platform/manifest.json").read_text(encoding="utf-8"))["version"]
    for name, files in planned().items():
        if repo is not None and name != repo:
            continue
        for relative, (_, data) in files.items():
            path = (root / name / relative).resolve()
            if not path.is_relative_to((root / name).resolve()):
                raise ValueError("invalid destination")
            if check:
                if not path.exists() or path.read_bytes().replace(b"\r\n", b"\n") != data:
                    raise ValueError(f"{path}: regenerate from platform/{version}")
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
