"""Sabotage pass: Strata through the gateway, and saying why when it cannot be reached
(2026-10-10, found on Troy's live install). Only the code that changed.

Every Strata runtime's companion driver came up degraded (`strata_local` gave
its engine no `default_base_url`), the NAS's gateway could not reach a new
driver port the node's firewall rule did not name, and the console said
neither. Restores from a COPY, never `git checkout --`, and opens with a
baseline per gate. Gates:

- `driver`: the provider registry and the driver's `degraded` reason;
- `gateway`: an unreachable driver's reason, a degraded one's, and the
  driver list that always answers;
- `agent`: the firewall rule following the listeners;
- `ui`: the companion joined to its runtime, the reasons on the row, the
  stale selection (vitest, started from `D:`);
- `acceptance`: `ls5-preparation-acceptance.py`'s chat through the gateway.

Usage: python specs/scripts/strata-gateway-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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

DRIVER = "inference-driver/src/eugene_plexus_inference_driver/"
PROVIDERS = DRIVER + "providers.py"
INFO = DRIVER + "routes/info.py"
GW = "gateway/src/eugene_plexus_gateway/"
ROUTING = GW + "routing.py"
ADMIN = GW + "routes/admin.py"
FOLLOW = "agent/src/eugene_plexus_agent/firewall_follow.py"
ROWS = "ui/src/lib/inferenceRows.ts"
PAGE = "ui/src/app/inference/page.tsx"
ACCEPTANCE = "specs/scripts/ls5-preparation-acceptance.py"


def _py(repo: str, *tests: str) -> tuple[str, list[str]]:
    return repo, [
        str(ROOT / repo / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *tests,
    ]


GATES: dict[str, tuple[str, list[str]]] = {
    "driver": _py("inference-driver", "tests/test_provider_registry.py", "tests/test_info.py"),
    "gateway": _py("gateway", "tests/test_routing.py", "tests/test_admin_and_config.py"),
    "agent": _py("agent", "tests/test_firewall_follow.py"),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/lib/inferenceRows.test.ts",
        "src/app/inference/page.test.tsx",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"), ACCEPTANCE.removeprefix("specs/"),
    ]),
}

STRATA_BASE_URL = (
    "            # the gateway (2026-10-10, Troy's live install).\n"
    '            "default_base_url": None,\n'
)

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the driver ----------------------------------------------------------------------
    ("THE BUG: Strata's provider gives its engine no default_base_url", "driver", PROVIDERS,
     STRATA_BASE_URL, "            # the gateway (2026-10-10, Troy's live install).\n"),
    ("a degraded driver does not say why", "driver", INFO,
     '        degraded=getattr(request.app.state, "adapter_error", None) or "its engine was not built",\n',
     ""),
    # --- the gateway ---------------------------------------------------------------------
    ("an unreachable driver's reason is the exception's own (empty) text", "gateway", ROUTING,
     "            reason = unreachable_reason(e, url=url, timeout=self._request_timeout)",
     "            reason = str(e)"),
    ("a connect timeout names the request timeout", "gateway", ROUTING,
     'f"no answer within {CONNECT_TIMEOUT_SECONDS:g} s connecting to {where}: the machine "',
     'f"no answer within {timeout:g} s connecting to {where}: the machine "'),
    ("a degraded driver is reported with no error", "gateway", ROUTING,
     '                        f"answers, but serves nothing: {b.info.degraded}"\n'
     "                        if b.info.degraded\n",
     "                        None\n                        if True\n"),
    ("an all-unreachable topology is a 503 again", "gateway", ADMIN,
     "    healths = table.as_driver_health()\n    return DriversInfo(drivers=healths)",
     "    healths = table.as_driver_health()\n"
     "    if not any(h.reachable for h in healths):\n"
     '        raise HTTPException(status_code=503, detail="No driver in the topology is reachable.")\n'
     "    return DriversInfo(drivers=healths)"),
    # --- the agent's firewall rule -----------------------------------------------------
    ("a rule the person never allowed is made", "agent", FOLLOW,
     "    if have is None:\n        return None", "    if have is None:\n        have = ()"),
    ("an unelevated agent tries anyway", "agent", FOLLOW,
     "    if not firewall.elevated():\n        return None", "    if False:\n        return None"),
    ("loopback listeners are opened too", "agent", FOLLOW,
     '                if listener.bind_host and listener.bind_host.strip("[]") not in _LOOPBACK',
     "                if True"),
    # --- the console -------------------------------------------------------------------
    ("a placed companion is an external backend of its own", "ui", ROWS,
     "    const runtimeName = companionOf(c.name, c.node);",
     "    const runtimeName = null as string | null;"),
    ("an unreachable driver's reason stays in a tooltip", "ui", PAGE,
     "        {row.reachable === false && (", "        {false && ("),
    ("the page keeps showing the backend it removed", "ui", PAGE,
     "      if (scope?.driver && scope.driver === row.driver) {", "      if (false) {"),
    ("a selection that is not listed reads as shown", "ui", PAGE,
     "              {scope.driver && sources !== null && !rows.some((r) => r.driver === scope.driver)",
     "              {false"),
    # --- only real processes show ------------------------------------------------------
    ("ACCEPTANCE: Strata's provider gives its engine no default_base_url", "acceptance", PROVIDERS,
     STRATA_BASE_URL, "            # the gateway (2026-10-10, Troy's live install).\n"),
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
    backup = Path(tempfile.mkdtemp(prefix="strata-gateway-sabotage-"))
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
