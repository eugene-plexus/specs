"""Sabotage pass for p1-accounts-acceptance.py.

Each sabotage puts back one way P1 could be wrong -- in the driver, the
gateway or the agent -- runs the fixture half of the acceptance, and
requires it to FAIL. The acceptance runs the editable installs, so a source
edit is what runs.

Restores are from byte copies taken before the first edit, never `git
checkout --`, which reverts uncommitted work and once turned a sabotage
run into one that tested nothing. Opens with a baseline assertion that the
gate passes unsabotaged.

    python scripts/p1-sabotage.py <python with all five components>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1]
ROOT = SPECS.parent
DRIVER = ROOT / "inference-driver" / "src" / "eugene_plexus_inference_driver"
GATEWAY = ROOT / "gateway" / "src" / "eugene_plexus_gateway"
AGENT = ROOT / "agent" / "src" / "eugene_plexus_agent"
ACCEPTANCE = SPECS / "scripts" / "p1-accounts-acceptance.py"
CATALOGUE = DRIVER / "engines" / "_catalogue.py"
ENGINE = DRIVER / "engines" / "openai_compat_http.py"

SABOTAGES: list[tuple[str, Path, str, str]] = [
    (
        "the driver serves its first model whatever the request named",
        ENGINE,
        "        entry = self.catalogue.find(requested)\n",
        "        entry = (self.catalogue.exposed() or [None])[0]\n",
    ),
    (
        "a model the account does not list is served instead of refused",
        ENGINE,
        "        if entry is None:\n            raise ModelNotServed(requested, served=len(self.catalogue.exposed()))\n",
        "        if entry is None:\n            entry = self.catalogue.exposed()[0]\n",
    ),
    (
        "the include/exclude patterns are read once rather than live",
        CATALOGUE,
        '        include = self._get("catalogueInclude")\n        exclude = self._get("catalogueExclude")\n',
        "        include = None\n        exclude = None\n",
    ),
    (
        "a failed read empties the list",
        CATALOGUE,
        "            except CatalogueError as e:\n                self._error = str(e)\n",
        "            except CatalogueError as e:\n                self._error = str(e)\n                self._set([], None)\n",
    ),
    (
        "the last good list is not kept on disk",
        CATALOGUE,
        "    def _save(self) -> None:\n        if self._path is None:\n            return\n",
        "    def _save(self) -> None:\n        return\n",
    ),
    (
        "the gateway publishes an account's models without its name",
        GATEWAY / "routing.py",
        '            public = f"{driver.name}/{entry.id}" if account else entry.id\n',
        "            public = entry.id\n",
    ),
    (
        "a candidate does not name its model on the request",
        GATEWAY / "driver_client.py",
        '        return request.model_copy(update={"model": self.model})\n',
        "        return request\n",
    ),
    (
        "an answer is published under the driver's own id",
        GATEWAY / "driver_client.py",
        "        if reported is None or reported == self.model:\n            return self.public_model\n        return reported\n",
        "        return reported\n",
    ),
    (
        "the gateway's key matcher knows no wildcard",
        GATEWAY / "model_patterns.py",
        '    if "*" not in pattern:\n        return pattern == value\n',
        "    if True:\n        return pattern == value\n",
    ),
    # The AGENT's copy of the matcher is not here: this run's agent is
    # enrolled, and an enrolled agent forwards admission to the control
    # root, so the agent's copy decides only on a standalone install. Its
    # own unit tests are the check for it (measured 2026-09-27: that
    # sabotage escapes this run and fails two of
    # `agent/tests/test_client_admission.py`).
    (
        "the control root's key matcher knows no wildcard",
        ROOT / "control" / "src" / "eugene_plexus_control" / "client_admission.py",
        '        if "*" not in pattern:\n            if pattern == model:\n',
        "        if True:\n            if pattern == model:\n",
    ),
    (
        "a driver from before P1 is dropped without being named",
        GATEWAY / "routing.py",
        "                snapshot.outdated.append(\n",
        "                (lambda _unused: None)(\n",
    ),
    (
        "an attempt's model is not recorded",
        GATEWAY / "routing.py",
        "                driver=driver,\n                model=model,\n",
        "                driver=driver,\n                model=None,\n",
    ),
    (
        "the per-model entry is ignored and a driver's first model routes every id",
        GATEWAY / "routing.py",
        "            backend = replace(driver, client=bound, model=entry, public_id=public)\n",
        "            backend = replace(driver, client=bound, model=served[0], public_id=public)\n",
    ),
]


def run_acceptance(python: str) -> int:
    result = subprocess.run(
        [python, str(ACCEPTANCE)],
        capture_output=True,
        text=True,
        timeout=600,
        stdin=subprocess.DEVNULL,
    )
    lines = (result.stdout + result.stderr).strip().splitlines()
    print(f"    exit={result.returncode}  {lines[-1] if lines else ''}", flush=True)
    return result.returncode


def main() -> None:
    python = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    # Optional: only the sabotages whose label contains this text.
    only = sys.argv[2] if len(sys.argv) > 2 else None
    chosen = [s for s in SABOTAGES if only is None or only in s[0]]
    files = {path for _, path, _, _ in chosen}
    copies = {path: path.read_bytes() for path in files}
    caught = 0
    escaped: list[str] = []
    try:
        print("baseline: the gate must pass unsabotaged", flush=True)
        if run_acceptance(python) != 0:
            raise SystemExit("BASELINE FAILED: the gate does not pass unsabotaged; fix that first")
        print("baseline PASS\n", flush=True)
        for label, path, old, new in chosen:
            source = copies[path].decode("utf-8").replace("\r\n", "\n")
            if source.count(old) != 1:
                raise SystemExit(f"sabotage anchor not found exactly once: {label}")
            print(f"sabotage: {label}", flush=True)
            path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            try:
                code = run_acceptance(python)
            finally:
                path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT\n", flush=True)
            else:
                escaped.append(label)
                print("    ESCAPED\n", flush=True)
        print(f"{caught} of {len(chosen)} caught", flush=True)
        for label in escaped:
            print(f"ESCAPED: {label}", flush=True)
        if escaped:
            sys.exit(1)
    finally:
        for path, data in copies.items():
            path.write_bytes(data)


if __name__ == "__main__":
    main()
