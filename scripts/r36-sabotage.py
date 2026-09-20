"""R3.6 copied-checkout mutation gate; run with the agent dev interpreter.

Only the temporary copy is edited. Every mutation is restored from copied
bytes, a fresh bytecode cache is used per run, and both baselines must pass.
The deterministic runtime tests drive controlled exits and readiness probes;
neighboring tests keep component safe mode and graceful restart in the gate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

MUTATIONS = [
    (
        "runtime never opts into startup protection",
        "runtimes.py",
        "stop_on_startup_crash=True",
        "stop_on_startup_crash=False",
    ),
    (
        "all nonzero engine exits become terminal",
        "supervisor.py",
        "and not self._was_ready",
        "and True",
    ),
    (
        "readiness never reaches the recovery policy",
        "runtimes.py",
        "sp.observe_readiness(isinstance(outcome, Ready))",
        "pass",
    ),
    (
        "loading counts as useful uptime",
        "runtimes.py",
        "sp.observe_readiness(isinstance(outcome, Ready))",
        "sp.observe_readiness(isinstance(outcome, (Ready, Loading)))",
    ),
    (
        "manual restart leaves an ended task ended",
        "supervisor.py",
        "elif self._task is None or self._task.done():\n            self.start()",
        "elif self._task is None or self._task.done():\n            pass",
    ),
    (
        "crash history never clears after stable service",
        "supervisor.py",
        "exited_at - self._ready_since >= _STABLE_READY_SECONDS",
        "exited_at - self._ready_since >= float('inf')",
    ),
    (
        "brief readiness clears crash history",
        "supervisor.py",
        "exited_at - self._ready_since >= _STABLE_READY_SECONDS",
        "exited_at - self._ready_since >= 0",
    ),
    (
        "sixty seconds no longer meets the stability boundary",
        "supervisor.py",
        "exited_at - self._ready_since >= _STABLE_READY_SECONDS",
        "exited_at - self._ready_since > _STABLE_READY_SECONDS",
    ),
    (
        "every probe restarts the stability clock",
        "supervisor.py",
        "if self._ready_since is None:",
        "if True:",
    ),
    (
        "lost readiness leaves the stability clock running",
        "supervisor.py",
        "else:\n            self._ready_since = None",
        "else:\n            pass",
    ),
    (
        "replacement inherits the old process readiness",
        "supervisor.py",
        '"""One spawn / wait / mark-state iteration."""\n        self._was_ready = False',
        '"""One spawn / wait / mark-state iteration."""',
    ),
    (
        "replacement inherits the old stability clock",
        "supervisor.py",
        '"""One spawn / wait / mark-state iteration."""\n'
        "        self._was_ready = False\n        self._ready_since = None",
        '"""One spawn / wait / mark-state iteration."""\n        self._was_ready = False',
    ),
    (
        "late probe is applied to a replacement",
        "runtimes.py",
        "            or sp.last_restart != started_at\n",
        "",
    ),
    (
        "short-lived crashes lose their backoff",
        "supervisor.py",
        "await asyncio.sleep(min(2.0 * self._consecutive_crashes, 10.0))",
        "await asyncio.sleep(0)",
    ),
    (
        "diagnosis loses the operator remedy",
        "supervisor.py",
        '"the runtime to retry."',
        '"the runtime."',
    ),
]


def main() -> None:
    agent = Path(__file__).resolve().parents[2] / "agent"
    with tempfile.TemporaryDirectory(prefix="ep-r36-sabotage-") as temporary:
        root = Path(temporary)
        for folder in ("src", "tests"):
            shutil.copytree(
                agent / folder,
                root / folder,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        shutil.copy2(agent / "pyproject.toml", root / "pyproject.toml")
        package = root / "src" / "eugene_plexus_agent"
        originals = {name: (package / name).read_bytes() for name in {row[1] for row in MUTATIONS}}
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("EUGENE_PLEXUS_")
        }
        env["PYTHONPATH"] = str(root / "src")

        def gate(number: int) -> tuple[int, int, int, str]:
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
                    "-W",
                    "ignore::DeprecationWarning",
                    f"--junitxml={report}",
                    "tests/test_runtime_end_to_end.py",
                    "tests/test_supervisor.py::test_auto_safe_mode_after_crash_threshold",
                    "tests/test_windows_supervision.py::test_a_requested_restart_is_not_a_crash",
                    "tests/test_windows_supervision.py::test_a_child_that_ignores_the_request_is_killed",
                    "-k",
                    "not runtime_goes_starting_then_loading_then_ready "
                    "and not stop_releases_the_process",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
            result = ET.parse(report).getroot()
            return (
                done.returncode,
                len(result.findall(".//failure")),
                len(result.findall(".//error")),
                done.stdout + done.stderr,
            )

        code, failures, errors, output = gate(0)
        assert code == failures == errors == 0, output
        print("PASS: unsabotaged copied checkout", flush=True)
        escaped = []
        for number, (label, name, old, new) in enumerate(MUTATIONS, 1):
            path = package / name
            source = originals[name].decode("utf-8").replace("\r\n", "\n")
            assert source.count(old) == 1, f"mutation anchor drifted: {label}"
            try:
                path.write_bytes(source.replace(old, new).encode("utf-8"))
                code, failures, errors, output = gate(number)
                assert errors == 0 and code in (0, 1), output
                caught = failures > 0
                print(
                    f"{'CAUGHT' if caught else 'ESCAPED'}: {label} ({failures} failures)",
                    flush=True,
                )
                if not caught:
                    escaped.append(label)
            finally:
                path.write_bytes(originals[name])
        assert not escaped, f"escaped: {escaped}"
        code, failures, errors, output = gate(len(MUTATIONS) + 1)
        assert code == failures == errors == 0, output
        print(f"{len(MUTATIONS)}/{len(MUTATIONS)} caught; restored baseline passes")


if __name__ == "__main__":
    main()
