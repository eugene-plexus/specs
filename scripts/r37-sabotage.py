"""R3.7 command-routing sabotage gate. Run with Python on Linux/WSL.

Copies both setup scripts and their standalone shell regression to a
temporary directory. Restores copied bytes after each mutation. A shell
syntax error is never a caught behavior failure. No working tree is edited.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

MUTATIONS = [
    (
        "install ignores the architecture-qualified request",
        "install.sh",
        '"$UV" venv --python "$PY_REQUEST"',
        '"$UV" venv --python "$PY_VERSION"',
    ),
    (
        "bootstrap tooling ignores the qualified request",
        "bootstrap.sh",
        '"$UV" venv --python "$PY_REQUEST" "$BOOT/venv"',
        '"$UV" venv --python "$PY_VERSION" "$BOOT/venv"',
    ),
    (
        "bootstrap components ignore the qualified request",
        "bootstrap.sh",
        '"$UV" venv --python "$PY_REQUEST" "$venv"',
        '"$UV" venv --python "$PY_VERSION" "$venv"',
    ),
    (
        "install trusts Rosetta uname without checking hardware",
        "install.sh",
        '*) [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" != 1 ] || NATIVE_APPLE=1 ;;',
        "*) : ;;",
    ),
    (
        "bootstrap trusts Rosetta uname without checking hardware",
        "bootstrap.sh",
        '*) [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" != 1 ] || NATIVE_APPLE=1 ;;',
        "*) : ;;",
    ),
    (
        "install stops recognizing native ARM uname",
        "install.sh",
        "arm64|aarch64) NATIVE_APPLE=1 ;;",
        "arm64|aarch64) : ;;",
    ),
    (
        "bootstrap stops recognizing native ARM uname",
        "bootstrap.sh",
        "arm64|aarch64) NATIVE_APPLE=1 ;;",
        "arm64|aarch64) : ;;",
    ),
    (
        "install skips inspecting the chosen interpreter",
        "install.sh",
        'if [ "$NATIVE_APPLE" = 1 ]; then\n    PY_ARCH=',
        "if false; then\n    PY_ARCH=",
    ),
    (
        "bootstrap does not inspect an existing component venv",
        "bootstrap.sh",
        '    require_native_python "$venv"\n',
        "",
    ),
    (
        "bootstrap does not inspect an existing tooling venv",
        "bootstrap.sh",
        'else\n    require_native_python "$BOOT/venv"\nfi',
        "fi",
    ),
    (
        "bootstrap does not inspect new tooling before installing into it",
        "bootstrap.sh",
        '    require_native_python "$BOOT/venv"\n    "$UV" pip',
        '    "$UV" pip',
    ),
    (
        "bootstrap overwrites an explicit interpreter choice",
        "bootstrap.sh",
        "*[!0-9.]*|'') NATIVE_APPLE=0 ;;",
        "'') NATIVE_APPLE=0 ;;",
    ),
    (
        "bootstrap applies Apple detection on Linux",
        "bootstrap.sh",
        'if [ "$(uname -s)" = Darwin ]; then',
        "if true; then",
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before-ref", help="reproduce the defect against this specs revision"
    )
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="ep-r37-sabotage-") as temporary:
        root = Path(temporary)
        for name in ("install.sh", "bootstrap.sh", "r37-install-sh-checks.sh"):
            shutil.copy2(scripts / name, root / name)
        originals = {
            name: (root / name).read_bytes() for name in ("install.sh", "bootstrap.sh")
        }

        def gate() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", str(root / "r37-install-sh-checks.sh")],
                capture_output=True,
                text=True,
                timeout=60,
            )

        if args.before_ref:
            for name in originals:
                source = subprocess.check_output(
                    ["git", "show", f"{args.before_ref}:scripts/{name}"], cwd=scripts
                )
                (root / name).write_bytes(source)
            before = gate()
            assert before.returncode == 1 and "FAIL " in before.stdout, (
                before.stdout + before.stderr
            )
            print(before.stdout, end="")
            print("Pre-fix revision fails the behavior checks as expected")
            return

        baseline = gate()
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        print(baseline.stdout.splitlines()[-1], flush=True)
        escaped = []
        for label, name, old, new in MUTATIONS:
            path = root / name
            source = originals[name].decode("utf-8").replace("\r\n", "\n")
            assert source.count(old) == 1, f"mutation anchor drifted: {label}"
            try:
                path.write_bytes(source.replace(old, new).encode("utf-8"))
                subprocess.run(["sh", "-n", str(path)], check=True, capture_output=True)
                result = gate()
                caught = result.returncode == 1 and "FAIL " in result.stdout
                assert result.returncode in (0, 1), result.stdout + result.stderr
                print(f"{'CAUGHT' if caught else 'ESCAPED'}: {label}", flush=True)
                if not caught:
                    escaped.append(label)
            finally:
                path.write_bytes(originals[name])
        restored = gate()
        assert restored.returncode == 0, restored.stdout + restored.stderr
        assert not escaped, f"escaped: {escaped}"
        print(f"{len(MUTATIONS)}/{len(MUTATIONS)} caught; restored baseline passes")


if __name__ == "__main__":
    main()
