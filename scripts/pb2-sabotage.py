"""PB2 sabotage pass: break each rule of the settings builder's page and the library's record.

The page (ui): the frontier the slider rests on, the words for a stop, what
Save writes, the never-lie reading of a built profile, the shared
ask-before-stopping step (builder and Benchmark), and the tray. The record
(library): builtBy stored, and kept by a replace that omits it.

Restores from a copy taken first and opens with a baseline that must pass.

    python pb2-sabotage.py [--ui DIR] [--library DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORDS = "src/lib/profileBuild.ts"
BUILDER = "src/components/ProfileBuilder.tsx"
ASK = "src/components/AskBeforeStopping.tsx"
BENCH = "src/components/ProfileBenchmark.tsx"
EDITOR = "src/components/ProfileEditor.tsx"
TASKS = "src/lib/tasks.ts"
USE_TASKS = "src/lib/useTasks.ts"
STORE = "src/eugene_plexus_library/store.py"

UI_GATE = [
    "src/lib/profileBuild.test.ts",
    "src/components/ProfileBuilder.test.tsx",
    "src/components/ProfileBenchmark.test.tsx",
    "src/components/ProfileEditor.test.tsx",
]
LIBRARY_GATE = ["tests/test_routes.py", "tests/test_profile_generation.py"]

# (name, repo, file, original, sabotaged)
SABOTAGES = [
    # --- the slider ---------------------------------------------------------
    (
        "the slider rests off the frontier",
        "ui",
        WORDS,
        "candidate.onFrontier && comparedSpeed(candidate) !== null && candidate.confirmed !== false,",
        "comparedSpeed(candidate) !== null && candidate.confirmed !== false,",
    ),
    (
        "the slider rests on a candidate that failed to load",
        "ui",
        WORDS,
        "candidate.onFrontier && comparedSpeed(candidate) !== null && candidate.confirmed !== false,",
        "candidate.onFrontier && comparedSpeed(candidate) !== null,",
    ),
    (
        "two stops at one context are ordered by chance",
        "ui",
        WORDS,
        "PRECISION.indexOf(a.candidate.cacheType) - PRECISION.indexOf(b.candidate.cacheType),",
        "0,",
    ),
    (
        "the slider ignores the build's suggestion",
        "ui",
        WORDS,
        "return at >= 0 ? at : stops.length - 1;",
        "return 0;",
    ),
    (
        "stops are compared by the empty context, not the common depth",
        "ui",
        WORDS,
        "return candidate.deepDecodeTokensPerSecond ?? candidate.decodeTokensPerSecond ?? null;",
        "return candidate.decodeTokensPerSecond ?? null;",
    ),
    (
        "a quality rate is rounded up",
        "ui",
        WORDS,
        "Math.floor(measured.sameTopTokenPercent)",
        "Math.round(measured.sameTopTokenPercent)",
    ),
    # --- what Save writes ---------------------------------------------------
    (
        "a quantised cache is saved without flash attention",
        "ui",
        WORDS,
        '  if (candidate.cacheType !== "f16") flags.flashAttention = true;',
        "",
    ),
    (
        "flash attention is forced on a full-precision cache",
        "ui",
        WORDS,
        '  if (candidate.cacheType !== "f16") flags.flashAttention = true;',
        "  flags.flashAttention = true;",
    ),
    (
        "a built profile keeps the base's gpuLayers",
        "ui",
        WORDS,
        "  delete kept.gpuLayers;\n",
        "",
    ),
    (
        "replacing the base loses its default",
        "ui",
        WORDS,
        "default: replacing ? (base?.default ?? false) : false,",
        "default: false,",
    ),
    (
        "Save writes no record",
        "ui",
        WORDS,
        "    builtBy: builtByRecord(build, candidate, chosen),\n",
        "",
    ),
    # --- a built profile read back ------------------------------------------
    (
        "an edited builder field still reads as built",
        "ui",
        WORDS,
        'states[key] = same(profile.flags?.[key], value) ? "built" : "edited";',
        'states[key] = "built";',
    ),
    (
        "gpuLayers set by hand does not count as an edit",
        "ui",
        WORDS,
        "  if (profile.flags?.gpuLayers != null) return true;\n",
        "",
    ),
    (
        "the measured numbers are not labelled once edited",
        "ui",
        WORDS,
        "  return editedSinceBuilt(profile)\n",
        "  return false\n",
    ),
    (
        "the edit form does not say which fields the builder set",
        "ui",
        EDITOR,
        "{existing?.builtBy && field.key in (existing.builtBy.flags ?? {}) && (",
        "{false && existing?.builtBy && field.key in (existing.builtBy.flags ?? {}) && (",
    ),
    (
        "an edit clears the builder's record",
        "ui",
        EDITOR,
        "      notes: notes.trim() || undefined,\n",
        "      notes: notes.trim() || undefined,\n      builtBy: null,\n",
    ),
    # --- asking before stopping ----------------------------------------------
    (
        "one stopped model is spoken of as many",
        "ui",
        WORDS,
        'const again = names.length === 1 ? "It starts" : "They start";',
        'const again = "They start";',
    ),
    (
        "Start stops nothing it asked about",
        "ui",
        ASK,
        "onClick={() => onStart(running)}",
        "onClick={() => onStart([])}",
    ),
    (
        "Start is offered while the node would refuse",
        "ui",
        ASK,
        "disabled={busy || asking || problems.length > 0}",
        "disabled={busy || asking}",
    ),
    (
        "the build does not restart what it stopped",
        "ui",
        BUILDER,
        "        stopRuntimes,\n        restartAfter: true,\n      });\n      await onStarted();",
        "        stopRuntimes,\n        restartAfter: false,\n      });\n      await onStarted();",
    ),
    (
        "the build does not ask again after a 409",
        "ui",
        BUILDER,
        "        setAsked((n) => n + 1);\n",
        "",
    ),
    (
        "the build's question is not re-asked when the options change",
        "ui",
        BUILDER,
        "  }, [node.target, request, marginValid, asked]);",
        "  }, [node.target, marginValid, asked]); // eslint-disable-line react-hooks/exhaustive-deps",
    ),
    (
        "the build's question is re-asked on every new model object",
        "ui",
        BUILDER,
        "  }, [modelId, modelName, modelPath, base, accuracy, marginMiB, marginValid, text]);",
        "  }, [model, modelId, modelName, modelPath, base, accuracy, marginMiB, marginValid, text]); // eslint-disable-line react-hooks/exhaustive-deps",
    ),
    (
        "the builder reads this machine instead of the node the page looks at",
        "ui",
        BUILDER,
        'const list = await api.get<ProfileBuildList>(target, "/v1/profile-builds");',
        'const list = await api.get<ProfileBuildList>("agent", "/v1/profile-builds");',
    ),
    (
        "replacing the base profile is not asked first",
        "ui",
        BUILDER,
        "                <ConfirmButton\n"
        "                  label={`Replace ${base.name}`}\n"
        "                  prompt={`${base.name}'s context and memory settings are replaced with these.`}\n"
        "                  onConfirm={() => void save(true)}\n",
        "                <button\n"
        '                  type="button"\n'
        "                  onClick={() => void save(true)}\n"
        "                  children={`Replace ${base.name}`}\n",
    ),
    (
        "the Benchmark does not restart what it stopped",
        "ui",
        BENCH,
        "        stopRuntimes,\n        restartAfter: true,\n      });\n      setJobs",
        "        stopRuntimes,\n        restartAfter: false,\n      });\n      setJobs",
    ),
    (
        "the Benchmark does not ask again after a 409",
        "ui",
        BENCH,
        "      if (e instanceof ApiError && e.status === 409) setAsked((n) => n + 1);\n",
        "",
    ),
    # --- the tray ------------------------------------------------------------
    (
        "a finished build stays in the tray",
        "ui",
        TASKS,
        '      .filter((b) => b.state === "running")',
        "      .filter(() => true)",
    ),
    (
        "the tray reads builds on this machine only",
        "ui",
        USE_TASKS,
        '      api.get<ProfileBuildList>(`node:${n.name}`, "/v1/profile-builds").catch(() => null),',
        "      Promise.resolve(null),",
    ),
    # --- the library's record ------------------------------------------------
    (
        "a replace that omits builtBy drops it",
        "library",
        STORE,
        'built_by = spec.builtBy if "builtBy" in spec.model_fields_set else current.builtBy',
        "built_by = spec.builtBy",
    ),
    (
        "an explicit null does not clear builtBy",
        "library",
        STORE,
        'built_by = spec.builtBy if "builtBy" in spec.model_fields_set else current.builtBy',
        "built_by = spec.builtBy or current.builtBy",
    ),
    (
        "a new profile does not store builtBy",
        "library",
        STORE,
        "                builtBy=spec.builtBy,\n                createdAt=now,",
        "                createdAt=now,",
    ),
]


def run_ui(ui: Path) -> int:
    try:
        return subprocess.run(
            ["npx", "vitest", "run", *UI_GATE],
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


def run_library(library: Path) -> int:
    python = library / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = library / ".venv" / "bin" / "python"
    return subprocess.run(
        [str(python), "-m", "pytest", "-q", "-x", "-p", "no:warnings", *LIBRARY_GATE],
        cwd=library,
        capture_output=True,
        text=True,
        timeout=600,
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--ui", type=Path, default=root / "ui")
    parser.add_argument("--library", type=Path, default=root / "library")
    args = parser.parse_args()
    repos = {"ui": args.ui.resolve(), "library": args.library.resolve()}
    gates = {"ui": run_ui, "library": run_library}
    files = sorted({(repo, f) for _, repo, f, _, _ in SABOTAGES})
    with tempfile.TemporaryDirectory(prefix="pb2-sabotage-") as tmp:
        backup = Path(tmp)
        for repo, f in files:
            (backup / repo / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repos[repo] / f, backup / repo / f)

        def restore() -> None:
            for repo, f in files:
                shutil.copy2(backup / repo / f, repos[repo] / f)

        try:
            for repo, gate in gates.items():
                if gate(repos[repo]) != 0:
                    print(f"BASELINE FAILED: the {repo} gate does not pass unsabotaged")
                    return 2
            print("baseline passes", flush=True)
            caught = escaped = 0
            for name, repo, f, original, sabotaged in SABOTAGES:
                text = (backup / repo / f).read_bytes().decode("utf-8")
                if text.count(original) != 1:
                    print(f"NOT APPLIED ({text.count(original)} matches): {name}", flush=True)
                    escaped += 1
                    continue
                (repos[repo] / f).write_bytes(text.replace(original, sabotaged).encode("utf-8"))
                try:
                    if gates[repo](repos[repo]) == 0:
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
