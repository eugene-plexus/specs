"""A3b sabotage pass: break each MoE-aware fit promise in the library; a test must fail.

Restores from a copy taken first and opens with a baseline that must pass.

    python a3b-sabotage.py [--library DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = "src/eugene_plexus_library/"
TESTS = ["tests/test_moe_fit.py", "tests/test_one_fit_path.py", "tests/test_guidance.py"]

SABOTAGES = [
    (
        "chunked expert tensors not counted",
        SRC + "formats/gguf.py",
        'r"_(?:ch)?exps(?:\\.|$)"',
        'r"_exps(?:\\.|$)"',
    ),
    (
        "a shared expert counted as an expert",
        SRC + "formats/gguf.py",
        'r"_(?:ch)?exps(?:\\.|$)"',
        'r"_(?:ch|sh)?exps?(?:\\.|$)"',
    ),
    (
        "a type the reader does not know is sized anyway",
        SRC + "formats/gguf.py",
        "        if size is None or elements % size[0]:\n            known = False\n            continue",
        "        if size is None or elements % size[0]:\n            continue",
    ),
    (
        "the tensor table read by default, growing every remote preflight",
        SRC + "formats/gguf.py",
        "def read_metadata(path: Path, *, tensors: bool = False)",
        "def read_metadata(path: Path, *, tensors: bool = True)",
    ),
    (
        "experts always said to move, however small the card",
        SRC + "fit.py",
        "return FitOffload.experts if on_card <= (budget.vramFreeBytes or 0) else FitOffload.layers",
        "return FitOffload.experts",
    ),
    (
        "a dense model described as moving experts",
        SRC + "fit.py",
        "    if expert_bytes <= 0:\n        return FitOffload.layers",
        "    if expert_bytes <= 0:\n        return FitOffload.experts",
    ),
    (
        "an unknown expert share described anyway",
        SRC + "fit.py",
        "    if expert_bytes is None:\n        return None\n    if expert_bytes <= 0:",
        "    if expert_bytes is None:\n        return FitOffload.layers\n    if expert_bytes <= 0:",
    ),
    (
        "the experts-in-RAM context ignores what RAM holds",
        SRC + "fit.py",
        "context = int(min(on_card, overall) // per_token)",
        "context = int(on_card // per_token)",
    ),
    (
        "an entry cached before expert bytes is served as it is",
        SRC + "scanner.py",
        "if cached is not None and not _lacks_expert_bytes(cached):",
        "if cached is not None:",
    ),
    (
        "a sharded model's other parts not summed",
        SRC + "scanner.py",
        "        total += part\n    return total",
        "    return total",
    ),
    (
        "the fit route never passes expert bytes",
        SRC + "routes/guidance.py",
        "        expert_bytes=expert_bytes,\n    )\n    if projector_bytes:",
        "    )\n    if projector_bytes:",
    ),
    (
        "the fit route never offers the experts-in-RAM context",
        SRC + "routes/guidance.py",
        "        maxContextExpertsInRam=fit_mod.max_context_experts_in_ram(",
        "        maxContextExpertsInRam=None and fit_mod.max_context_experts_in_ram(",
    ),
]


def run_tests(library: Path) -> bool:
    python = library / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = library / ".venv" / "bin" / "python"
    result = subprocess.run(
        [str(python), "-m", "pytest", "-q", "-x", "-p", "no:warnings", *TESTS],
        cwd=library,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--library", type=Path, default=Path(__file__).resolve().parents[2] / "library"
    )
    library = parser.parse_args().library.resolve()
    files = sorted({f for _, f, _, _ in SABOTAGES})
    with tempfile.TemporaryDirectory(prefix="a3b-sabotage-") as tmp:
        backup = Path(tmp)
        for f in files:
            (backup / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(library / f, backup / f)

        def restore() -> None:
            for f in files:
                shutil.copy2(backup / f, library / f)

        try:
            if not run_tests(library):
                print("BASELINE FAILED: the tests do not pass unsabotaged")
                return 2
            print("baseline passes")
            caught = escaped = 0
            for name, f, original, sabotaged in SABOTAGES:
                text = (backup / f).read_text(encoding="utf-8")
                if text.count(original) != 1:
                    print(f"NOT APPLIED ({text.count(original)} matches): {name}")
                    escaped += 1
                    continue
                (library / f).write_text(text.replace(original, sabotaged), encoding="utf-8")
                try:
                    if run_tests(library):
                        print(f"ESCAPED: {name}")
                        escaped += 1
                    else:
                        print(f"caught: {name}")
                        caught += 1
                finally:
                    restore()
            print(f"{caught} of {len(SABOTAGES)} caught, {escaped} escaped or not applied")
            return 0 if escaped == 0 else 1
        finally:
            restore()


if __name__ == "__main__":
    sys.exit(main())
