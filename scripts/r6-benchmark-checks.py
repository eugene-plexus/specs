"""Prove benchmark checks catch broken cleanup, output validation and launch guards.

Mutates disposable source copies only. Uses the current interpreter's agent dev deps.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> None:
    source = Path(__file__).resolve().parents[2] / "agent"
    with tempfile.TemporaryDirectory(prefix="ep-r6-mutations-") as directory:
        root = Path(directory)
        for folder in ("src", "tests"):
            shutil.copytree(source / folder, root / folder,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(source / "pyproject.toml", root / "pyproject.toml")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        def run(label: str, tests: list[str], expected: int) -> None:
            env["PYTHONPYCACHEPREFIX"] = str(root / "bytecode" / label)
            result = subprocess.run([sys.executable, "-m", "pytest", *tests,
                "-q", "--disable-warnings", "--tb=no"], cwd=root, env=env,
                capture_output=True, text=True, timeout=90)
            assert result.returncode == expected, f"{label}: {result.stdout}\n{result.stderr}"
            print(("PASS " if expected == 0 else "CAUGHT ") + label, flush=True)
        baseline = ["tests/test_benchmarks.py", "tests/test_benchmark_jobs.py", "tests/test_benchmark_routes.py"]
        run("baseline", baseline, 0)
        module = "src/eugene_plexus_agent/"
        cases = [
            ("missing-depths", "benchmarks.py", "if {p.depth for p in job.points} != set(depths):",
             "if False:", "tests/test_benchmark_jobs.py::test_bad_child_output_never_becomes_success"),
            ("duplicate-depths", "benchmarks.py", "if any(p.depth == point.depth for p in job.points):",
             "if False:", "tests/test_benchmark_jobs.py::test_bad_child_output_never_becomes_success"),
            ("credential-leak", "benchmarks.py", "env = child_environment()", "env = __import__('os').environ.copy()",
             "tests/test_benchmark_jobs.py::test_real_child_results_persist_and_snapshot_is_independent"),
            ("launch-exclusion", "node_work.py", "if manager is not None and manager.active:",
             "if False:", "tests/test_benchmark_routes.py::test_active_benchmark_excludes_launch_mutations"),
            ("busy-node", "routes/benchmarks.py", "if busy:", "if False:",
             "tests/test_benchmark_routes.py::test_busy_runtime_refuses_without_stopping"),
            ("context-tail", "benchmarks.py", "context - tokens", "context",
             "tests/test_benchmarks.py::test_depth_sweep_preserves_profile_and_leaves_generation_room"),
        ]
        for label, relative, old, new, test in cases:
            path = root / module / relative
            saved = path.read_bytes()
            text = saved.decode("utf-8")
            assert old in text, f"{label}: mutation no longer matches"
            try:
                path.write_text(text.replace(old, new, 1), encoding="utf-8")
                run(label, [test], 1)
            finally:
                path.write_bytes(saved)
        run("restored", baseline, 0)
        print(f"PASS all {len(cases)} deliberate regressions detected", flush=True)


if __name__ == "__main__":
    main()
