"""R7 step 1: run regressions, then sabotage disposable source copies.

Requires each consumer's dev dependencies. Never edits a checkout, reads an
installed config, starts a server, or uses a real inference backend.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


# repo, source file, replacement, expected regression test(s).
MUTATIONS = [
    (
        "agent",
        "child_env.py",
        "if reserved_override({key: value}, component_prefix=component_prefix) is None",
        "if True",
        "component_receives_only or real_engine_child",
    ),
    (
        "agent",
        "supervisor.py",
        'kind_value in {"library", "inference-driver"}',
        'kind_value in {"gateway", "library", "inference-driver"}',
        "component_receives_only",
    ),
    (
        "agent",
        "supervisor.py",
        "if reserved is not None:",
        "if False:",
        "component_override",
    ),
    (
        "agent",
        "runtimes.py",
        "if reserved is not None:",
        "if False:",
        "runtime_env_cannot",
    ),
    ("agent", "runtimes.py", "if spec.extraArgs:", "if False:", "raw_arguments"),
    ("agent", "runtimes.py", "if not spec.binary:", "if True:", "unapproved_binary"),
    (
        "agent",
        "runtimes.py",
        "binary.is_relative_to(root.resolve())",
        "str(binary).startswith(str(root.resolve()))",
        "binary_root_prefix",
    ),
    (
        "agent",
        "runtimes.py",
        "reason = _launch_policy(self.spec, self._adapter, self._get_config)",
        "reason = None",
        "policy_is_rechecked",
    ),
    (
        "agent",
        "routes/runtimes.py",
        "validate_spec(body, state.get_config)",
        "None",
        "routes_refuse",
    ),
    (
        "agent",
        "engines/llama_cpp.py",
        "env=child_environment(),",
        "env=None,",
        "probes",
    ),
    ("agent", "engines/vllm.py", "env=child_environment(),", "env=None,", "probes"),
    ("agent", "engines/host.py", "env=child_environment(),", "env=None,", "probes"),
    ("agent", "engines/devices.py", "env=child_environment(),", "env=None,", "probes"),
    (
        "inference-driver",
        "engines/_subprocess.py",
        'if not key.upper().startswith("EUGENE_PLEXUS_")',
        "if True",
        "cli",
    ),
    (
        "inference-driver",
        "engines/_subprocess.py",
        "env=_utf8_subprocess_env(),",
        "env=None,",
        "real_cli_child",
    ),
]


def run(
    python: Path, directory: Path, test: str, selection: str = ""
) -> subprocess.CompletedProcess:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("EUGENE_PLEXUS_")
    }
    env["PYTHONPATH"] = str(directory / "src")
    # Do not let Python reuse timestamp+size pycs between mutations.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        str(python),
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--disable-warnings",
        test,
    ]
    if selection:
        command.extend(["-k", selection])
    return subprocess.run(
        command, cwd=directory, env=env, text=True, capture_output=True, timeout=90
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--polyrepo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--agent-python", type=Path)
    parser.add_argument("--driver-python", type=Path)
    parser.add_argument(
        "--current-python",
        action="store_true",
        help="use this interpreter with both consumers' dev dependencies installed",
    )
    args = parser.parse_args()
    repos = ("agent", "inference-driver")
    pythons = {}
    tests = {
        "agent": "tests/test_launch_boundary.py",
        "inference-driver": "tests/test_cli_credentials.py",
    }
    for repo, override in zip(
        repos, (args.agent_python, args.driver_python), strict=True
    ):
        if args.current_python:
            override = Path(sys.executable)
        pythons[repo] = (
            override
            or args.polyrepo
            / repo
            / ".venv"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        ).absolute()
        if not pythons[repo].is_file():
            parser.error(
                f"missing Python with {repo} dev dependencies: {pythons[repo]}"
            )
    with tempfile.TemporaryDirectory(prefix="ep-r7-boundary-") as temp:
        copies = {}
        for repo in repos:
            source = args.polyrepo / repo
            target = Path(temp) / repo
            target.mkdir()
            for tree in ("src", "tests"):
                shutil.copytree(
                    source / tree,
                    target / tree,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
            shutil.copy2(source / "pyproject.toml", target / "pyproject.toml")
            copies[repo] = target
            result = run(pythons[repo], target, tests[repo])
            if result.returncode:
                raise SystemExit(
                    f"{repo} baseline failed:\n{result.stdout}\n{result.stderr}"
                )
            print(f"PASS {repo} baseline (includes real child processes)", flush=True)
        for repo, filename, old, new, selection in MUTATIONS:
            module = "eugene_plexus_" + (
                "inference_driver" if repo == "inference-driver" else repo
            )
            path = copies[repo] / "src" / module / filename
            original = path.read_bytes()
            text = original.decode("utf-8")
            if old not in text:
                raise SystemExit(f"mutation anchor missing: {repo}/{filename}: {old}")
            try:
                path.write_text(text.replace(old, new), encoding="utf-8")
                result = run(pythons[repo], copies[repo], tests[repo], selection)
                if (
                    result.returncode != 1
                    or "FAILURES" not in result.stdout
                    or "ERROR" in result.stdout
                ):
                    raise SystemExit(
                        f"mutation escaped or check broke: {repo}/{filename}: {old}\n"
                        f"{result.stdout}\n{result.stderr}"
                    )
                print(f"CAUGHT {repo}/{filename}: {selection}", flush=True)
            finally:
                path.write_bytes(original)
        for repo in repos:
            result = run(pythons[repo], copies[repo], tests[repo])
            if result.returncode:
                raise SystemExit(
                    f"restored {repo} baseline failed:\n{result.stdout}\n{result.stderr}"
                )
        print(
            f"{len(MUTATIONS)}/{len(MUTATIONS)} mutations caught; restored baselines pass"
        )


if __name__ == "__main__":
    main()
