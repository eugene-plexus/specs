"""A3c sabotage pass: break each starter-set MoE rule in the library; a test must fail.

Restores from a copy taken first and opens with a baseline that must pass.

    python a3c-sabotage.py [--library DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = "src/eugene_plexus_library/"
STARTER = SRC + "starter.py"
REVIEW = SRC + "starter_review.py"
TESTS = [
    "tests/test_starter.py",
    "tests/test_starter_moe.py",
    "tests/test_starter_review.py",
    "tests/test_starter_routes.py",
]

SABOTAGES = [
    (
        "no entry is ever read as MoE",
        STARTER,
        "return bool(model.fit and model.fit.expertBytes)",
        "return False",
    ),
    (
        "a MoE entry is a candidate whatever moves",
        STARTER,
        "return is_moe(model) and model.fit.offload is FitOffload.experts",
        "return is_moe(model) and model.fit.verdict is not FitVerdict.no",
    ),
    (
        "a MoE entry wins within its own class",
        STARTER,
        "size_rank(moe.parameters) > size_rank(dense.parameters)",
        "size_rank(moe.parameters) >= size_rank(dense.parameters)",
    ),
    (
        "a MoE entry never wins",
        STARTER,
        "        pick = moe\n",
        "        pick = dense\n",
    ),
    (
        "a machine with no graphics card loses the smallest-first rule",
        STARTER,
        "if has_no_accelerator(budget) and fitting:",
        "if False and fitting:",
    ),
    (
        "expert bytes not read from the file",
        STARTER,
        'expert_bytes=_as_int(rec.get("expertBytes")),',
        "expert_bytes=None,",
    ),
    (
        "the entry's fit is scored without its expert bytes",
        STARTER,
        "        kv_cache_type=kv,\n        expert_bytes=entry.expert_bytes,\n    )\n",
        "        kv_cache_type=kv,\n    )\n",
    ),
    (
        "the experts-in-RAM context never offered",
        STARTER,
        "maxContextExpertsInRam=fit_mod.max_context_experts_in_ram(",
        "maxContextExpertsInRam=None and fit_mod.max_context_experts_in_ram(",
    ),
    (
        "a split MoE pick described as fitting entirely",
        STARTER,
        "if best.fit.verdict is not FitVerdict.fits:",
        "if False:",
    ),
    (
        "the displaced dense pick not named",
        STARTER,
        "    if dense is not None:\n        reason +=",
        "    if False:\n        reason +=",
    ),
    (
        "an unknown parameter count ranks above every class",
        STARTER,
        "    if parameters is None:\n        return -1",
        "    if parameters is None:\n        return 99",
    ),
    (
        "the review ignores a MoE architecture id",
        REVIEW,
        'return "moe" in arch or bool(',
        "return bool(",
    ),
    (
        "the review ignores an active-parameter suffix",
        REVIEW,
        ' or bool(ACTIVE_SUFFIX.search(self.name.lower()))',
        "",
    ),
    (
        "a MoE candidate ranked in a dense class",
        REVIEW,
        "MOE_CLASSES if self.looks_moe else SIZE_CLASSES",
        "SIZE_CLASSES",
    ),
    (
        "a MoE entry kept with no tensor table read",
        REVIEW,
        "        if moe_class:\n            # A MoE entry is proved by its tensor table, and there is none.\n"
        "            return None\n",
        "",
    ),
    (
        "expert bytes not recorded in the proposed entry",
        REVIEW,
        "    if meta.expert_bytes is not None:\n        entry[",
        "    if False:\n        entry[",
    ),
    (
        "a MoE class accepts a file with zero expert bytes",
        REVIEW,
        "if moe_class and not meta.expert_bytes:",
        "if moe_class and meta.expert_bytes is None:",
    ),
    (
        "the review never reviews the MoE class",
        REVIEW,
        "            for name, _, _ in ALL_CLASSES\n        ]",
        "            for name, _, _ in SIZE_CLASSES\n        ]",
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
    with tempfile.TemporaryDirectory(prefix="a3c-sabotage-") as tmp:
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
                text = (backup / f).read_bytes().decode("utf-8")
                if text.count(original) != 1:
                    print(f"NOT APPLIED ({text.count(original)} matches): {name}")
                    escaped += 1
                    continue
                (library / f).write_bytes(text.replace(original, sabotaged).encode("utf-8"))
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
