"""R3.5 mutation gate, run with the library's dev interpreter.

Copies source and tests to a temporary directory. Establishes a green
baseline, restores every mutation from copied bytes, and requires assertion
failures rather than accepting syntax errors, collection errors, or hangs.
The original checkout is never mutated. Run on Linux AND Windows to cover
symlinks and junctions respectively.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

SCANNER = "scanner.py"
MUTATIONS = [
    (
        "app ignores the saved switch",
        "app.py",
        'follow_symlinks=lambda: bool(config_store.get("followSymlinks")),',
        "follow_symlinks=lambda: False,",
    ),
    (
        "manager never forwards the switch",
        "scan_manager.py",
        "follow_symlinks=self._resolve_follow_symlinks(),",
        "follow_symlinks=False,",
    ),
    (
        "manager freezes the switch at startup",
        "scan_manager.py",
        "self._resolve_follow_symlinks = follow_symlinks or (lambda: False)",
        "initial = follow_symlinks() if follow_symlinks else False\n"
        "        self._resolve_follow_symlinks = lambda: initial",
    ),
    (
        "scanner always follows directory links",
        SCANNER,
        "self._follow_symlinks = follow_symlinks",
        "self._follow_symlinks = True",
    ),
    (
        "scanner never follows directory links",
        SCANNER,
        "self._follow_symlinks = follow_symlinks",
        "self._follow_symlinks = False",
    ),
    ("cycle guard removed", SCANNER, "if identity in ancestors:", "if False:"),
    (
        "current directory never enters ancestry",
        SCANNER,
        "ancestors = ancestors | {identity}",
        "ancestors = ancestors",
    ),
    (
        "child walk loses ancestry",
        SCANNER,
        "stack.append((Path(entry.path), ancestors))",
        "stack.append((Path(entry.path), frozenset()))",
    ),
    (
        "cycle diagnostic disappears",
        SCANNER,
        'detail="directory link cycle: target is an ancestor",',
        'detail="not scanned",',
    ),
    ("alias replaced with target path", SCANNER, "yield current", "yield current.resolve()"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library", type=Path, default=Path(__file__).resolve().parents[2] / "library"
    )
    args = parser.parse_args()
    mutations = list(MUTATIONS)
    if os.name == "nt":
        mutations.append(
            (
                "junction bypasses the off switch",
                SCANNER,
                "entry.is_symlink() or Path(entry.path).is_junction()",
                "entry.is_symlink()",
            )
        )
    else:
        mutations.extend(
            [
                (
                    "file links disappear again",
                    SCANNER,
                    "if entry.is_file():",
                    "if entry.is_file(follow_symlinks=False):",
                ),
                (
                    "one bad link discards sibling files",
                    SCANNER,
                    "except OSError as exc:\n                        result.skipped.append(",
                    "except OSError as exc:\n                        raise\n"
                    "                        result.skipped.append(",
                ),
            ]
        )

    with tempfile.TemporaryDirectory(prefix="ep-r35-sabotage-") as temporary:
        root = Path(temporary)
        for folder in ("src", "tests"):
            shutil.copytree(
                args.library / folder,
                root / folder,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        shutil.copy2(args.library / "pyproject.toml", root / "pyproject.toml")
        package = root / "src" / "eugene_plexus_library"
        originals = {
            name: (package / name).read_bytes() for name in {mutation[1] for mutation in mutations}
        }
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("EUGENE_PLEXUS_")
        }
        env["PYTHONPATH"] = str(root / "src")

        def gate(number: int) -> tuple[subprocess.CompletedProcess[str], int, int]:
            report = root / f"result-{number}.xml"
            env["PYTHONPYCACHEPREFIX"] = str(root / "pycache" / str(number))
            done = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                    f"--junitxml={report}",
                    "tests/test_scanner.py",
                    "tests/test_routes.py",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
            report_root = ET.parse(report).getroot()
            failures = len(report_root.findall(".//failure"))
            errors = len(report_root.findall(".//error"))
            return done, failures, errors

        baseline, failures, errors = gate(0)
        assert baseline.returncode == 0 and failures == errors == 0, (
            baseline.stdout + baseline.stderr
        )
        print("PASS: unsabotaged copied checkout", flush=True)
        escaped = []
        for number, (label, name, old, new) in enumerate(mutations, 1):
            path = package / name
            source = originals[name].decode("utf-8")
            assert source.count(old) == 1, f"mutation anchor drifted: {label}"
            try:
                path.write_bytes(source.replace(old, new).encode("utf-8"))
                done, failures, errors = gate(number)
                assert errors == 0 and done.returncode in (0, 1), done.stdout + done.stderr
                caught = failures > 0
                print(
                    f"{'CAUGHT' if caught else 'ESCAPED'}: {label} ({failures} failing checks)",
                    flush=True,
                )
                if not caught:
                    escaped.append(label)
            finally:
                path.write_bytes(originals[name])
        assert not escaped, f"escaped mutations: {escaped}"
        final, failures, errors = gate(len(mutations) + 1)
        assert final.returncode == 0 and failures == errors == 0, final.stdout + final.stderr
        print(
            f"{len(mutations)}/{len(mutations)} caught; restored baseline passes; "
            "original checkout untouched"
        )


if __name__ == "__main__":
    main()
