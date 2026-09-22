"""Sabotage pass for b1-mlx-identity-acceptance.py.

Each sabotage reintroduces one half of the identity-split defect into a
component's working tree (the acceptance run uses the editable venvs, so
a source edit is what runs), runs the full acceptance, and requires it
to FAIL. Restores are from byte copies taken before the first edit —
never `git checkout --`, which reverts uncommitted work and turned an
earlier sabotage run into one that tested nothing
(feedback: sabotage-runs-restore-from-a-copy).

Opens with a baseline assertion that the gate passes unsabotaged.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1]
ROOT = SPECS.parent
DRIVER = ROOT / "inference-driver" / "src" / "eugene_plexus_inference_driver"
GATEWAY = ROOT / "gateway" / "src" / "eugene_plexus_gateway"
AGENT_PY = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"
ACCEPTANCE = SPECS / "scripts" / "b1-mlx-identity-acceptance.py"

SABOTAGES: list[tuple[str, Path, str, str]] = [
    (
        "the wire carries the public alias instead of the upstream id",
        DRIVER / "engines" / "openai_compat_http.py",
        '            "model": self._upstream_model_id,',
        '            "model": self._model_id,',
    ),
    (
        "a translating driver echoes the backend's name on responses",
        DRIVER / "engines" / "openai_compat_http.py",
        "        if self._upstream_model_id != self._model_id:\n            return self._model_id\n        return str(reported or self._model_id)",
        "        return str(reported or self._model_id)",
    ),
    (
        "the stream's terminal frame takes the backend's name raw",
        DRIVER / "engines" / "openai_compat_http.py",
        '                    served_model = self._public_model_id(event.get("model") or served_model)',
        '                    served_model = str(event.get("model") or served_model)',
    ),
    (
        "the gateway routes on the upstream id when one is advertised",
        GATEWAY / "routing.py",
        "        model_id = backend.info.modelId",
        "        model_id = getattr(backend.info, 'upstreamModelId', None) or backend.info.modelId",
    ),
]


def run_acceptance() -> int:
    result = subprocess.run(
        [str(AGENT_PY), str(ACCEPTANCE)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = "\n".join((result.stdout + result.stderr).splitlines()[-4:])
    print(f"    exit={result.returncode}  {tail.splitlines()[-1] if tail else ''}")
    return result.returncode


def main() -> None:
    files = {path for _, path, _, _ in SABOTAGES}
    copies = {path: path.read_bytes() for path in files}
    backups = {}
    for path in files:
        backup = path.with_suffix(path.suffix + ".b1-sabotage-backup")
        backup.write_bytes(copies[path])
        backups[path] = backup

    caught = 0
    escaped: list[str] = []
    try:
        print("baseline: the gate must pass unsabotaged")
        if run_acceptance() != 0:
            raise SystemExit("BASELINE FAILED — the gate does not pass unsabotaged; fix that first")
        print("baseline PASS\n")

        for label, path, old, new in SABOTAGES:
            # The working trees are CRLF on this box; normalize so a
            # multi-line anchor can match. The write goes back LF-only,
            # and the byte copy restores the original either way.
            source = copies[path].decode("utf-8").replace("\r\n", "\n")
            if source.count(old) != 1:
                raise SystemExit(f"sabotage anchor not found exactly once: {label}")
            print(f"sabotage: {label}")
            path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            try:
                code = run_acceptance()
            finally:
                path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT\n")
            else:
                escaped.append(label)
                print("    ESCAPED\n")

        print(f"{caught} of {len(SABOTAGES)} caught")
        if escaped:
            for label in escaped:
                print(f"ESCAPED: {label}")
            sys.exit(1)
    finally:
        for path, backup in backups.items():
            path.write_bytes(copies[path])
            backup.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
