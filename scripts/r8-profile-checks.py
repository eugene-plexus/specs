"""Prove R8's regression checks fail against deliberately broken copies.

Only disposable copies are mutated; never restore a working checkout with git.
Requires gateway/library dev dependencies in this Python environment.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> None:
    repos = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="ep-r8-mutations-") as directory:
        root = Path(directory).resolve()
        for name in ("gateway", "library"):
            dest = root / name
            dest.mkdir()
            for sub in ("src", "tests"):
                shutil.copytree(repos / name / sub, dest / sub,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copyfile(repos / name / "pyproject.toml", dest / "pyproject.toml")
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(str(root / name / "src") for name in ("gateway", "library"))
        def run(repo: str, test: str, label: str, expected: int) -> None:
            env["PYTHONPYCACHEPREFIX"] = str(root / "pycache" / label)
            result = subprocess.run([sys.executable, "-m", "pytest", test, "-q", "--disable-warnings", "--tb=no"],
                cwd=root / repo, env=env, text=True, capture_output=True, timeout=90)
            if result.returncode != expected:
                raise AssertionError(f"{label}: expected {expected}, got {result.returncode}\n{result.stdout}\n{result.stderr}")
            print(("PASS baseline " if expected == 0 else "CAUGHT ") + label, flush=True)
        run("gateway", "tests/test_profile_defaults.py", "gateway", 0)
        run("library", "tests/test_profile_generation.py", "library", 0)
        module = "src/eugene_plexus_gateway/"
        cases = [
            ("wire-profile-resolver", "gateway", module + "routes/inference.py",
             "client.prepare_request = prepare_candidate", "client.prepare_request = None",
             "tests/test_profile_defaults.py::test_both_doors_preserve_caller_values_and_apply_profile"),
            ("caller-zero", "gateway", module + "routes/inference.py",
             'body.temperature if body.temperature is not None else defaults.get("temperature")',
             'body.temperature or defaults.get("temperature")',
             "tests/test_profile_defaults.py::test_both_doors_preserve_caller_values_and_apply_profile"),
            ("default-selection", "gateway", module + "profiles.py",
             "if profile.default]", "if not profile.default]",
             "tests/test_profile_defaults.py::test_both_doors_preserve_caller_values_and_apply_profile"),
            ("library-path", "gateway", module + "routes/inference.py",
             'backend.runtime.spec.get("modelPath")', 'backend.runtime.spec.get("localPath")',
             "tests/test_profile_defaults.py::test_both_doors_preserve_caller_values_and_apply_profile"),
            ("fresh-cache", "gateway", module + "profiles.py",
             'and now - previous.fetched_at < self._seconds("profileCacheSeconds", 30)',
             'and False', "tests/test_profile_defaults.py::test_cache_outage_expiry_deletion_and_recovery"),
            ("stale-bound", "gateway", module + "profiles.py",
             "if age < fresh + stale else {}", "if True else {}",
             "tests/test_profile_defaults.py::test_cache_outage_expiry_deletion_and_recovery"),
            ("retry-backoff", "gateway", module + "profiles.py",
             "_RETRY_SECONDS = 5.0", "_RETRY_SECONDS = 0.0",
             "tests/test_profile_defaults.py::test_cache_outage_expiry_deletion_and_recovery"),
            ("clear-deleted", "gateway", module + "profiles.py",
             "entry = _Entry(values, self._clock())", "entry = _Entry(values or (previous.values if previous else {}), self._clock())",
             "tests/test_profile_defaults.py::test_cache_outage_expiry_deletion_and_recovery"),
            ("cache-bound", "gateway", module + "profiles.py",
             "_MAX_ENTRIES = 256", "_MAX_ENTRIES = 10000",
             "tests/test_profile_defaults.py::test_cache_is_bounded_and_cloud_does_no_lookup"),
            ("persist-create", "library", "src/eugene_plexus_library/store.py",
             "maxTokens=spec.maxTokens,", "maxTokens=None,",
             "tests/test_profile_generation.py::test_generation_defaults_survive_save_replace_and_restart"),
        ]
        for label, repo, relative, old, new, test in cases:
            path = root / repo / relative
            saved = path.read_bytes()
            text = saved.decode("utf-8")
            assert old in text, f"{label}: mutation no longer matches"
            try:
                path.write_text(text.replace(old, new, 1), encoding="utf-8")
                run(repo, test, label, 1)
            finally:
                path.write_bytes(saved)
        run("gateway", "tests/test_profile_defaults.py", "restored-gateway", 0)
        run("library", "tests/test_profile_generation.py", "restored-library", 0)
        print(f"PASS {len(cases)} deliberate regressions caught; restored baselines pass", flush=True)


if __name__ == "__main__":
    main()
