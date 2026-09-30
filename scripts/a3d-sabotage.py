"""A3d sabotage pass: break each rule of Low's smaller-file offer; a test must fail.

moe-aware-fit.md §6: offered only after a build at Low, only when the file
on disk does not fit entirely at the chosen context, from the repository the
model's own download names, the largest smaller file that fits entirely, and
never a rebuild on the person's behalf.

Restores from a copy taken first and opens with a baseline that must pass.

    python a3d-sabotage.py [--ui DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORDS = "src/lib/smallerFile.ts"
OFFER = "src/components/SmallerFileOffer.tsx"
BUILDER = "src/components/ProfileBuilder.tsx"
GATE = ["src/lib/smallerFile.test.ts", "src/components/ProfileBuilder.test.tsx"]

SABOTAGES = [
    (
        "an unfinished download names the model's repository",
        WORDS,
        '.filter((d) => d.state === "done" && d.modelId === modelId && d.repo)',
        ".filter((d) => d.modelId === modelId && d.repo)",
    ),
    (
        "any download names the model's repository",
        WORDS,
        '.filter((d) => d.state === "done" && d.modelId === modelId && d.repo)',
        '.filter((d) => d.state === "done" && d.repo)',
    ),
    (
        "the branch asked for wins over the commit resolved",
        WORDS,
        "revision: found.resolvedCommit ?? found.revision ?? null",
        "revision: found.revision ?? null",
    ),
    (
        "a file no smaller than the one on disk is offered",
        WORDS,
        ".filter((c) => c.sizeBytes < currentBytes && c.sizeBytes <= room)",
        ".filter((c) => c.sizeBytes <= room)",
    ),
    (
        "a file too big for the room beside the cache is offered",
        WORDS,
        ".filter((c) => c.sizeBytes < currentBytes && c.sizeBytes <= room)",
        ".filter((c) => c.sizeBytes < currentBytes && c.sizeBytes <= room * 1.5)",
    ),
    (
        "the catalogue's size-only verdict is trusted",
        WORDS,
        ".filter((c) => c.sizeBytes < currentBytes && c.sizeBytes <= room)",
        '.filter((c) => c.sizeBytes < currentBytes && c.fit?.verdict === "fits")',
    ),
    # Not here: removing the "missing cache or overhead" guard. Measured
    # 2026-09-30, it escapes this gate because `free - undefined` is NaN and
    # no size compares below NaN, so nothing is offered either way; and it
    # is a type error, which `npm run typecheck` (in CI) refuses. Two
    # mechanisms, neither of them a vitest case.
    (
        "the smallest file is offered, not the largest that fits",
        WORDS,
        ".sort((a, b) => b.sizeBytes - a.sizeBytes)[0] ?? null",
        ".sort((a, b) => a.sizeBytes - b.sizeBytes)[0] ?? null",
    ),
    (
        "a file that already fits is offered a smaller one",
        OFFER,
        'if (fit.fit.verdict === "fits") return setCheck({ kind: "fits" });',
        "",
    ),
    (
        "the repository is guessed for a file copied in by hand",
        OFFER,
        'if (!origin) return setCheck({ kind: "unknown-origin" });',
        'if (!origin) return setCheck({ kind: "none" });',
    ),
    (
        "the file's fit is taken at the default context, not the chosen one",
        OFFER,
        "            contextLength: String(contextLength),\n",
        "",
    ),
    (
        "the file's fit ignores the chosen cache type",
        OFFER,
        "            kvCacheType: cacheType,\n",
        "",
    ),
    (
        "a smaller file already on disk is downloaded again",
        OFFER,
        "  const owned = candidate.alreadyOwned;",
        "  const owned = null as CatalogueCandidate[\"alreadyOwned\"];",
    ),
    (
        "the caveat about answers is dropped",
        OFFER,
        '<p className="text-[color:var(--muted)]">{SMALLER_CAVEAT}</p>',
        "",
    ),
    (
        "every accuracy level offers a smaller file",
        BUILDER,
        '{build.accuracy === "low" && !failed && stop && (',
        "{!failed && stop && (",
    ),
]


def run_gate(ui: Path) -> int:
    try:
        return subprocess.run(
            ["npx", "vitest", "run", *GATE],
            cwd=ui,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            shell=True,
        ).returncode
    except subprocess.TimeoutExpired:
        return 124


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", type=Path, default=Path(__file__).resolve().parents[2] / "ui")
    ui = parser.parse_args().ui.resolve()
    files = sorted({f for _, f, _, _ in SABOTAGES})
    with tempfile.TemporaryDirectory(prefix="a3d-sabotage-") as tmp:
        backup = Path(tmp)
        for f in files:
            (backup / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ui / f, backup / f)

        def restore() -> None:
            for f in files:
                shutil.copy2(backup / f, ui / f)

        try:
            if run_gate(ui) != 0:
                print("BASELINE FAILED: the gate does not pass unsabotaged")
                return 2
            print("baseline passes", flush=True)
            caught = escaped = 0
            for name, f, original, sabotaged in SABOTAGES:
                text = (backup / f).read_bytes().decode("utf-8")
                if text.count(original) != 1:
                    print(f"NOT APPLIED ({text.count(original)} matches): {name}", flush=True)
                    escaped += 1
                    continue
                (ui / f).write_bytes(text.replace(original, sabotaged).encode("utf-8"))
                try:
                    if run_gate(ui) == 0:
                        print(f"ESCAPED: {name}", flush=True)
                        escaped += 1
                    else:
                        print(f"caught: {name}", flush=True)
                        caught += 1
                finally:
                    restore()
            print(f"{caught} of {len(SABOTAGES)} caught, {escaped} escaped or not applied")
            return 0 if escaped == 0 else 1
        finally:
            restore()


if __name__ == "__main__":
    sys.exit(main())
