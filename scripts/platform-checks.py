"""Verify deterministic vendoring and detect changes to a generated consumer."""

import importlib.util
import tempfile
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vendor = load("vendor-platform")
checker = load("check-vendored")
with tempfile.TemporaryDirectory(prefix="ep-platform-check-") as directory:
    root = Path(directory)
    vendor.vendor(root, check=False)
    vendor.vendor(root, check=True)
    for repo in root.iterdir():
        checker.check(repo)
    target = root / "agent/src/eugene_plexus_agent/tokens.py"
    before = target.read_bytes()
    target.write_bytes(before + b"\n# accidental drift\n")
    try:
        checker.check(root / "agent")
    except ValueError:
        pass
    else:
        raise AssertionError("consumer accepted edited canonical code")
    vendor.vendor(root, check=False)
    assert target.read_bytes() == before
    vendor.vendor(root, check=True)
print("PASS: deterministic vendoring, per-consumer integrity and regeneration after drift")
