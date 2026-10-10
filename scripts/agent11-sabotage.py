"""Sabotage pass: a person's Stop outlives the agent (agent#11, 2026-10-10).
Only the code that changed.

A model Troy had stopped came back at every update and reboot: the stop
reason lived in memory and boot started every runtime with `autoStart`.
Restores from a COPY, never `git checkout --`, and opens with a baseline
per gate. Gates:

- `agent`: the stop kept in `agent.yaml`, the boot that honours it, the
  start that forgets it, and `PUT .../auto-start`;
- `ui`: the stop reason in words and the "Start when Eugene starts" box
  (vitest, started from `D:`);
- `acceptance`: `ls5-preparation-acceptance.py`'s S1-S3, across a real
  agent restart.

Usage: python specs/scripts/agent11-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
TIMEOUT = 900

AGENT = "agent/src/eugene_plexus_agent/"
APP = AGENT + "app.py"
RUNTIMES = AGENT + "runtimes.py"
STATE = AGENT + "state.py"
ROUTES = AGENT + "routes/runtimes.py"
PAGE = "ui/src/app/inference/page.tsx"
WORDS = "ui/src/lib/runningModel.ts"


def _py(repo: str, *tests: str) -> tuple[str, list[str]]:
    return repo, [
        str(ROOT / repo / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *tests,
    ]


GATES: dict[str, tuple[str, list[str]]] = {
    "agent": _py("agent", "tests/test_remembered_stop.py", "tests/test_lifecycle_routes.py"),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/app/inference/page.test.tsx",
        "src/lib/runningModel.test.ts",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"),
        "scripts/ls5-preparation-acceptance.py",
    ]),
}

BOOT = "            runtime_supervisor.start_at_boot(spec)"
ROUTE_BODY = (
    "    updated = state.set_runtime_auto_start(name, body.autoStart)\n"
    "    if updated is None:\n"
    "        raise _not_found(name)\n"
    "    return _compose(updated, _supervisor(request))\n"
)

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the agent -----------------------------------------------------------------------
    ("THE BUG: boot starts every runtime, stopped or not", "agent", APP,
     BOOT, "            runtime_supervisor.add_and_start(spec)"),
    ("boot does not read what was remembered", "agent", RUNTIMES,
     "        if self._stop_memory is not None and spec.name in self._stop_memory.remembered_stops():",
     "        if False:"),
    ("a person's stop is not remembered", "agent", RUNTIMES,
     "        if self._stop_memory is not None and reason is StopReason.operator:",
     "        if False:"),
    ("an idle unload is remembered too", "agent", RUNTIMES,
     "        if self._stop_memory is not None and reason is StopReason.operator:",
     "        if self._stop_memory is not None:"),
    ("a start does not forget the stop", "agent", RUNTIMES,
     "        self._stop_reasons.pop(spec.name, None)\n        self._forget_stop(spec.name)\n        sp.start()",
     "        self._stop_reasons.pop(spec.name, None)\n        sp.start()"),
    ("the stop is never written to agent.yaml", "agent", STATE,
     '            out["stoppedRuntimes"] = sorted(self._stopped)',
     "            pass"),
    ("agent.yaml's stop is not read back", "agent", STATE,
     '                    for name in raw.get("stoppedRuntimes") or []',
     "                    for name in []"),
    ("removing a runtime keeps its stop", "agent", STATE,
     "            del self._runtimes[name]\n            self._stopped.discard(name)\n            self._write_locked()\n            return True",
     "            del self._runtimes[name]\n            self._write_locked()\n            return True"),
    ("renaming a runtime keeps the old name's stop", "agent", STATE,
     "                del self._runtimes[name]\n                self._stopped.discard(name)\n",
     "                del self._runtimes[name]\n"),
    ("auto-start restarts the engine", "agent", ROUTES,
     ROUTE_BODY,
     "    updated = state.set_runtime_auto_start(name, body.autoStart)\n"
     "    if updated is None:\n"
     "        raise _not_found(name)\n"
     "    supervisor = _supervisor(request)\n"
     "    if supervisor is not None:\n"
     "        await supervisor.remove_and_stop(name)\n"
     "        supervisor.add_and_start(updated)\n"
     "    return _compose(updated, supervisor)\n"),
    ("auto-start changes more than autoStart", "agent", STATE,
     '            updated = spec.model_copy(update={"autoStart": auto_start})',
     '            updated = spec.model_copy(update={"autoStart": auto_start, "port": None})'),
    ("auto-start is open to the gateway's token", "agent", ROUTES,
     "    dependencies=_write_auth,\n)\nasync def set_runtime_auto_start(",
     "    dependencies=_lifecycle_auth,\n)\nasync def set_runtime_auto_start("),
    # --- the console ---------------------------------------------------------------------
    ("the row shows the raw stop token", "ui", PAGE,
     'status === "stopped" ? stopReasonWords(row.stopReason ?? own?.stopReason ?? null) : null;',
     'status === "stopped" ? (row.stopReason ?? own?.stopReason ?? null) : null;'),
    ("the words do not say the stop stays", "ui", WORDS,
     '  operator: "someone stopped it, and it stays stopped until it is started",',
     '  operator: "someone stopped it",'),
    ("the box shows the old value after saving", "ui", PAGE,
     "                  setSavedAutoStart({ value, over: autoStartNow });",
     "                  void autoStartNow;"),
    ("a refused save shows as saved", "ui", PAGE,
     '      failed("change whether Eugene starts", runtime, node, err);\n      return false;',
     '      failed("change whether Eugene starts", runtime, node, err);\n      return true;'),
    # --- only real processes show ------------------------------------------------------
    ("ACCEPTANCE: boot starts every runtime, stopped or not", "acceptance", APP,
     BOOT, "            runtime_supervisor.add_and_start(spec)"),
    ("ACCEPTANCE: auto-start restarts the engine", "acceptance", ROUTES,
     ROUTE_BODY,
     "    updated = state.set_runtime_auto_start(name, body.autoStart)\n"
     "    if updated is None:\n"
     "        raise _not_found(name)\n"
     "    supervisor = _supervisor(request)\n"
     "    if supervisor is not None:\n"
     "        await supervisor.remove_and_stop(name)\n"
     "        supervisor.add_and_start(updated)\n"
     "    return _compose(updated, supervisor)\n"),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, command = GATES[name]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    try:
        done = subprocess.run(command, cwd=str(ROOT / repo), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:] + (done.stderr or "")[-500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="append", choices=sorted(GATES))
    parser.add_argument("--label", action="append", help="run only entries whose label has this")
    parser.add_argument("--anchors", action="store_true", help="check every anchor, run nothing")
    args = parser.parse_args()
    chosen = [
        s
        for s in SABOTAGES
        if (not args.gate or s[1] in args.gate)
        and (not args.label or any(part in s[0] for part in args.label))
    ]
    gates = sorted({s[1] for s in chosen})
    missing = [
        (label, io.open(ROOT / relative, encoding="utf-8").read().count(old))
        for label, _gate, relative, old, _new in chosen
        if io.open(ROOT / relative, encoding="utf-8").read().count(old) != 1
    ]
    if missing:
        for label, count in missing:
            print(f"[ANCHOR ] {label}: matched {count} times")
        return 1
    if args.anchors:
        print(f"{len(chosen)} anchors, each matched once")
        return 0
    backup = Path(tempfile.mkdtemp(prefix="agent11-sabotage-"))
    for _label, _gate, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
    print(f"copy in {backup}\n")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, gate, relative, old, new in chosen:
        path = ROOT / relative
        source = io.open(path, encoding="utf-8").read()
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, _out = run_gate(gate)
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] ({gate}) {label}", flush=True)
            caught += 1
        else:
            print(f"[ESCAPED] ({gate}) {label}", flush=True)
            escaped += 1
    print(f"\n{caught} caught, {escaped} escaped, {len(chosen)} sabotages")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
