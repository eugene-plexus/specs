"""Prove the UI inference gate detects a dropped schema; never edit a checkout.

Run after genui-inference-acceptance.py passes, with the same Python. A temporary
copy of the real driver loses response_format forwarding. The schema gate must
fail with that specific observation, not a startup or unrelated failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    specs = Path(__file__).resolve().parents[1]
    package = specs.parent / "inference-driver/src/eugene_plexus_inference_driver"
    relative = Path("engines/openai_compat_http.py")
    original = (package / relative).read_bytes()
    anchor = (
        'if request.responseFormat is not None:\n            payload["response_format"]'
    )
    digest = hashlib.sha256(original).hexdigest()
    with tempfile.TemporaryDirectory(prefix="genui-sabotage-") as directory:
        tmp = Path(directory)
        copied = tmp / package.name
        shutil.copytree(
            package, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        target = copied / relative
        text = target.read_text(encoding="utf-8")
        assert text.count(anchor) == 1, "driver schema forwarding anchor changed"
        target.write_text(
            text.replace(anchor, anchor.replace("is not None", "is None")),
            encoding="utf-8",
            newline="\n",
        )
        report = tmp / "result.json"
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith("EUGENE_PLEXUS")
        }
        env.update(EP_DRIVER_SRC=str(tmp), PYTHONUTF8="1")
        result = subprocess.run(
            [
                sys.executable,
                str(specs / "scripts/genui-inference-acceptance.py"),
                "--families",
                "local",
                "--only",
                "schema",
                "--report",
                str(report),
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
        if result.returncode != 1 or not report.exists():
            raise AssertionError(
                f"sabotage did not reach the gate: {result.stdout}\n{result.stderr}"
            )
        checks = json.loads(report.read_text(encoding="utf-8"))["checks"]
        assert len(checks) == 1 and not checks[0]["passed"], checks
        assert (
            checks[0].get("error") == "AssertionError: response_format changed upstream"
        ), checks
    assert hashlib.sha256((package / relative).read_bytes()).hexdigest() == digest
    print("PASS: dropped schema rejected by the wire gate; original driver unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
