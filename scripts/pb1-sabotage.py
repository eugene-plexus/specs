"""PB1 sabotage pass: break each promise the profile builder makes; a test must fail.

Restores every file from a copy taken before the first sabotage (never
`git checkout`, which reverts uncommitted work), and opens with a baseline
run that must pass, or the escapes below would prove nothing.

    python pb1-sabotage.py [--agent DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = "src/eugene_plexus_agent/"
TESTS = [
    "tests/test_profile_builds.py",
    "tests/test_benchmark_routes.py",
    "tests/test_benchmarks.py",
    "tests/test_engines.py",
    "tests/test_engine_places.py",
]

# (name, file, original, sabotaged)
SABOTAGES = [
    (
        "placement reaches llama-bench through -fitc (design M3's trap)",
        SRC + "profile_builds.py",
        "*bench_placement(candidate.placement),",
        '"--fit-ctx", str(candidate.contextSize),',
    ),
    (
        "llama-bench's warm-up turned off",
        SRC + "profile_builds.py",
        '"--repetitions",\n                str(REPETITIONS),',
        '"--repetitions",\n                str(REPETITIONS),\n                "--no-warmup",',
    ),
    (
        "the quality boundary rule dropped (no minus one standard error)",
        SRC + "profile_builds.py",
        "passes=percent - error >= threshold,",
        "passes=percent >= threshold,",
    ),
    (
        "candidates measured at half their own context again",
        SRC + "profile_builds.py",
        "return min(context // 2, COMMON_DEPTH)",
        "return min(context // 2, 8192)",
    ),
    (
        "no speed tolerance: noise picks among equals",
        SRC + "profile_builds.py",
        "tolerance = SPEED_TOLERANCE * _speed(c)",
        "tolerance = 0.0",
    ),
    (
        "a less precise cache kept on the frontier at an equal speed",
        SRC + "profile_builds.py",
        "                or _precision(o) > _precision(c)\n",
        "",
    ),
    (
        "a smaller cache kept although it places identically",
        SRC + "profile_builds.py",
        "if not any(placements[k] == placements[cache] for k in kept):",
        "if True:",
    ),
    (
        "a cache allowed although it failed the level",
        SRC + "profile_builds.py",
        "            if quality.passes:\n                allowed.append(cache)",
        "            if True:\n                allowed.append(cache)",
    ),
    (
        "Max runs the quality step",
        SRC + "profile_builds.py",
        "                if body.accuracy is not ProfileBuildAccuracy.max:\n"
        "                    job.phase = ProfileBuildPhase.quality",
        "                if True:\n                    job.phase = ProfileBuildPhase.quality",
    ),
    (
        "a shutdown restarts models on the way out",
        SRC + "profile_builds.py",
        "        if self.shutting_down:\n            for restart in job.restarts:",
        "        if False:\n            for restart in job.restarts:",
    ),
    (
        "a build never restarts what it stopped",
        SRC + "profile_builds.py",
        "                job.restarts = await after()",
        "                job.restarts = job.restarts",
    ),
    (
        "the quality baseline assumes its folder exists (the defect PB1's tests found)",
        SRC + "profile_builds.py",
        "        plan.work.mkdir(parents=True, exist_ok=True)\n        base = plan.work",
        "        base = plan.work",
    ),
    (
        "a short text's token count is not recorded",
        SRC + "profile_builds.py",
        "            job.evaluation.tokens = have",
        "            pass",
    ),
    (
        "a candidate llama-server could not load is still recommended",
        SRC + "profile_builds.py",
        "            candidate.confirmed = ok",
        "            candidate.confirmed = True",
    ),
    (
        "a running model nobody agreed to is stopped anyway",
        SRC + "measurement_node.py",
        "return [name for name in running if name not in allowed]",
        "return []",
    ),
    (
        "an agreed stop recorded as an operator stop",
        SRC + "measurement_node.py",
        "await supervisor.stop_one(name, reason=StopReason.measurement)",
        "await supervisor.stop_one(name, reason=StopReason.operator)",
    ),
    (
        "a refused benchmark leaves the models it stopped stopped",
        SRC + "routes/benchmarks.py",
        "await restart_stopped(request, stopped, enabled=True, hold_lock=False)",
        "stopped = stopped",
    ),
    (
        "a running build does not hold other launches",
        SRC + "node_work.py",
        "if kind := active_measurement(request.app):",
        "if kind := None:",
    ),
    (
        "a tool lacking an option a build needs is accepted",
        SRC + "routes/profile_builds.py",
        "if missing := sorted(opt for opt in required if opt not in listed):",
        "if missing := []:",
    ),
    (
        "a quantised cache served without flash attention",
        SRC + "engines/llama_cpp.py",
        'if cache not in (None, "f16") and not flags.get("flashAttention"):',
        "if False:",
    ),
    (
        "the GGUF reader does not skip a numeric array",
        SRC + "gguf_context.py",
        "stream.seek(_FIXED[inner] * count, 1)",
        "stream.seek(0, 1)",
    ),
    # moe-aware-fit call A and the thresholds Troy set, 2026-09-30.
    (
        "an unset gpuLayers is full offload whatever the build can do",
        SRC + "admission.py",
        "return not (engine_places and not fit_disabled(spec))",
        "return True",
    ),
    (
        "a profile's own --fit off is ignored",
        SRC + "admission.py",
        "return not (engine_places and not fit_disabled(spec))",
        "return not engine_places",
    ),
    (
        "any llama-server is taken to place models, help unread",
        SRC + "engines/llama_cpp.py",
        'return flags is not None and "--fit" in flags',
        "return True",
    ),
    (
        "admission never learns whether the engine places the model",
        SRC + "routes/runtimes.py",
        "engine_places=await asyncio.to_thread(engine_places, spec, state.get_config),",
        "",
    ),
    (
        "High back at 96.5%",
        SRC + "profile_builds.py",
        "ProfileBuildAccuracy.high: 96.0,",
        "ProfileBuildAccuracy.high: 96.5,",
    ),
    (
        "Low no looser than Medium",
        SRC + "profile_builds.py",
        "ProfileBuildAccuracy.low: 88.0,",
        "ProfileBuildAccuracy.low: 92.0,",
    ),
]


def run_tests(agent: Path) -> bool:
    result = subprocess.run(
        [str(agent / ".venv" / "Scripts" / "python.exe"), "-m", "pytest", "-q", "-x",
         "-p", "no:warnings", *TESTS],
        cwd=agent,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=Path(__file__).resolve().parents[2] / "agent")
    agent = parser.parse_args().agent.resolve()
    files = sorted({f for _, f, _, _ in SABOTAGES})
    with tempfile.TemporaryDirectory(prefix="pb1-sabotage-") as tmp:
        backup = Path(tmp)
        for f in files:
            (backup / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(agent / f, backup / f)

        def restore() -> None:
            for f in files:
                shutil.copy2(backup / f, agent / f)

        try:
            if not run_tests(agent):
                print("BASELINE FAILED: the tests do not pass unsabotaged; nothing below means anything")
                return 2
            print("baseline passes")
            caught = escaped = 0
            for name, f, original, sabotaged in SABOTAGES:
                text = (backup / f).read_text(encoding="utf-8")
                if text.count(original) != 1:
                    print(f"NOT APPLIED ({text.count(original)} matches): {name}")
                    escaped += 1
                    continue
                (agent / f).write_text(text.replace(original, sabotaged), encoding="utf-8")
                try:
                    if run_tests(agent):
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
