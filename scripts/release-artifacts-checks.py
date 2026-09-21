"""The published bytes must be Git blobs, and divergent OS pins must fail."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location("release", Path(__file__).with_name("release-artifacts.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix="ep-release-check-") as work:
    root = Path(work).resolve()
    assert root.parent == Path(tempfile.gettempdir()).resolve()
    output = root / "artifacts"
    manifest = module.package("v0.1.0-alpha.1", "HEAD", output)
    for line in (output / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    for name in ("install.sh", "install.ps1"):
        blob = subprocess.check_output(["git", "-C", str(module.ROOT), "show", f"{manifest['specsCommit']}:scripts/{name}"])
        assert (output / name).read_bytes() == blob
    shell, windows = (output / "install.sh").read_bytes(), (output / "install.ps1").read_bytes()
    changed = windows.replace(manifest["components"]["agent"].encode(), b"0" * 40)
    try:
        module.pins(shell, changed)
    except ValueError:
        print("CAUGHT: Windows and POSIX release pins diverge")
    else:
        raise AssertionError("accepted mismatched release pins")
    try:
        module.package("v0.1.0-alpha.1", "HEAD", output)
    except FileExistsError:
        pass
    else:
        raise AssertionError("overwrote existing release artifacts")
print("PASS: exact committed bytes, checksums, six matching pins, no output overwrite")
