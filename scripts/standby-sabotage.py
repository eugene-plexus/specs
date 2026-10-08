"""Sabotage the warm standby's changed code (warm-standby.md); each case names its check.

Files are restored from exact bytes kept in memory and on disk beside the
run, never from Git. A baseline of every named check passes first, and again
after. Syntax and import errors do not count as a caught defect.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(r"D:\py\eugene-plexus")
NPX = "npx.cmd" if os.name == "nt" else "npx"
ENV = {
    k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")
} | {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}

C_TOK = "src/eugene_plexus_control/tokens.py"
C_DEP = "src/eugene_plexus_control/dependencies.py"
C_APP = "src/eugene_plexus_control/applied.py"
C_NODES = "src/eugene_plexus_control/routes/nodes.py"
C_CTRL = "src/eugene_plexus_control/routes/control.py"
C_REPL = "src/eugene_plexus_control/replication.py"
C_MAIN = "src/eugene_plexus_control/app.py"
C_PROBE = "src/eugene_plexus_control/nodes_client.py"
C_CONF = "src/eugene_plexus_control/config.py"
A_TRUST = "src/eugene_plexus_agent/trust.py"
A_SUP = "src/eugene_plexus_agent/supervisor.py"
A_SB = "src/eugene_plexus_agent/standby.py"
A_NODE = "src/eugene_plexus_agent/routes/node.py"
U_PANEL = "src/components/StandbyPanel.tsx"
U_WORDS = "src/lib/standby.ts"

CT = "tests/test_tokens.py::test_a_standby_token_reaches_control_only_and_only_from_the_granted_node"
CS = "tests/test_standby.py::"
CC = "tests/test_config.py::"
AS = "tests/test_standby.py::"
UP = "src/components/StandbyPanel.test.tsx::"

# (label, repo, file, before, after, kind, check)
CASES: list[tuple[str, str, str, str, str, str, str]] = [
    ("no standby rule in the verifier", "control", C_TOK,
     "    if sub == SUB_STANDBY and GRANT_STANDBY in key.grants:\n",
     "    if False:\n", "pytest", CT),
    ("a standby token reaches any machine", "control", C_TOK,
     "        if all(a == RECIPIENT_CONTROL for a in aud):\n            return\n        raise TokenError(f\"{key.issuer} is the standby",
     "        if True:\n            return\n        raise TokenError(f\"{key.issuer} is the standby", "pytest", CT),
    ("replication session-only again (the bug as filed)", "control", C_DEP,
     "    if not claims.is_service:\n        return verify_bearer(",
     "    if True:\n        return verify_bearer(", "pytest",
     CS + "test_only_the_granted_node_reads_replication_with_its_standby_token"),
    ("any service token opens replication", "control", C_DEP,
     "    if claims.sub == tokens.SUB_STANDBY and holder is not None and claims.issuer_node == holder:\n",
     "    if claims.is_service:\n", "pytest",
     CS + "test_only_the_granted_node_reads_replication_with_its_standby_token"),
    ("the grant is trusted from the bundle alone", "control", C_DEP,
     "    if claims.sub == tokens.SUB_STANDBY and holder is not None and claims.issuer_node == holder:\n",
     "    if claims.sub == tokens.SUB_STANDBY:\n", "pytest",
     CS + "test_the_grant_is_checked_against_applied_state_on_every_pull"),
    ("two standbys in applied state", "control", C_APP,
     "        if holder not in (None, name):\n            raise ApplyError(",
     "        if False:\n            raise ApplyError(", "pytest",
     CS + "test_set_standby_refuses_what_the_route_refuses"),
    ("a promoted node keeps its standby grant", "control", C_APP,
     "            grants=tuple(g for g in promoted.grants if g != GRANT_STANDBY),\n",
     "            grants=promoted.grants,\n", "pytest",
     CS + "test_set_standby_refuses_what_the_route_refuses"),
    ("the root's own machine may be the standby", "control", C_NODES,
     "        if name == request.app.state.node_name or (probe is not None and probe.hosts_control):\n",
     "        if False:\n", "pytest", CS + "test_one_standby_at_a_time_never_the_roots_own_machine"),
    ("the route lets a second machine in", "control", C_NODES,
     "        if holder not in (None, name):\n            raise problem(",
     "        if False:\n            raise problem(", "pytest",
     CS + "test_one_standby_at_a_time_never_the_roots_own_machine"),
    ("the standby's position is the root's own", "control", C_CTRL,
     '            "appliedIndex": applied,\n',
     '            "appliedIndex": request.app.state.machine.state.index,\n', "pytest",
     CS + "test_status_reports_the_standby_from_its_own_pulls"),
    ("the follower is given no token", "control", C_MAIN,
     "                if settings.agent_url and settings.service_token\n",
     "                if False\n", "pytest",
     CS + "test_a_standby_started_by_its_agent_follows_with_the_token_it_was_given"),
    ("a refused pull is not said in the root's words", "control", C_REPL,
     '        _refused(response, "log read")\n', "", "pytest",
     CS + "test_the_standby_follows_with_the_token_its_agent_trades_it"),
    ("the probe ignores hostsControl", "control", C_PROBE,
     '            hosts_control=body.get("hostsControl") is True,\n',
     "            hosts_control=False,\n", "pytest",
     CS + "test_the_probe_reads_whether_a_node_hosts_the_root"),
    ("the retired list is just an unknown field", "control", C_CONF,
     '            message = RETIRED.get(key, "unknown field")\n',
     '            message = "unknown field"\n', "pytest",
     CC + "test_the_retired_standby_list_is_refused_and_says_what_replaced_it"),
    ("the retired list is still shown", "control", C_CONF,
     "        **{k: v for k, v in values.items() if k != MODE_CHANGED_AT and k not in RETIRED},\n",
     "        **{k: v for k, v in values.items() if k != MODE_CHANGED_AT},\n", "pytest",
     CC + "test_an_old_logs_standby_list_replays_and_is_not_shown"),
    ("the agent mints a standby token for any machine", "agent", A_TRUST,
     "                    and audience == tokens.RECIPIENT_CONTROL\n", "", "pytest",
     AS + "test_a_standby_token_leaves_this_machine_for_control_only_with_the_grant"),
    ("the agent mints a standby token with no grant", "agent", A_TRUST,
     "                    and tokens.GRANT_STANDBY in grants\n", "", "pytest",
     AS + "test_a_standby_token_leaves_this_machine_for_control_only_with_the_grant"),
    ("the install's root is given the standby's wiring", "agent", A_SUP,
     "        if standby.is_standby(self.entry):\n",
     "        if self.entry.kind == ComponentKind.control:\n", "pytest",
     AS + "test_the_standby_is_the_one_control_process_given_a_credential"),
    ("a promoted copy is still given a standby token", "agent", A_SUP,
     '            if wiring.get("ROLE") == "standby":\n', "            if True:\n", "pytest",
     AS + "test_the_standby_is_the_one_control_process_given_a_credential"),
    ("a promoted copy is stopped and deleted", "agent", A_SB,
     "        if role == ROLE_ACTIVE:\n", "        if False:\n", "pytest",
     AS + "test_a_promoted_standby_is_never_stopped_or_deleted"),
    ("the standby is stopped without asking it", "agent", A_SB,
     "        if role != ROLE_STANDBY:\n", "        if False:\n", "pytest",
     AS + "test_the_grant_starts_the_standby_and_its_removal_deletes_the_copy"),
    ("a standby beside the active root", "agent", A_SB,
     "    if want and hosts_active_control(state):\n", "    if False:\n", "pytest",
     AS + "test_no_standby_on_the_machine_that_runs_the_active_root"),
    ("the standby counts as the root", "agent", A_SB,
     "        e.kind == ComponentKind.control and not is_standby(e) for e in",
     "        e.kind == ComponentKind.control for e in", "pytest",
     AS + "test_the_node_report_says_whether_this_machine_hosts_the_root"),
    ("hostsControl is never reported", "agent", A_NODE,
     "        hostsControl=standby.hosts_active_control(state),\n",
     "        hostsControl=False,\n", "pytest",
     AS + "test_the_node_report_says_whether_this_machine_hosts_the_root"),
    ("the copy outlives the grant", "agent", A_SB,
     "            shutil.rmtree(copy)\n", "            copy.stat()\n", "pytest",
     AS + "test_the_grant_starts_the_standby_and_its_removal_deletes_the_copy"),
    ("Make acts without asking", "ui", U_PANEL,
     'onClick={() => setAsking("make")}', "onClick={() => void act(true)}", "vitest",
     UP + "asks first, saying what the copy holds"),
    ("Stop removes nothing at the root", "ui", U_PANEL,
     '      else await api.delete("control", path);\n',
     '      else await api.put("control", path, undefined);\n', "vitest",
     UP + "names the standby with what the root last heard"),
    ("the question leaves out the trade", "ui", U_WORDS,
     '    "Someone who takes that machine could try to guess your passphrase offline."\n',
     '    ""\n', "vitest", UP + "asks first, saying what the copy holds"),
    ("behind reads as up to date", "ui", U_WORDS,
     "  if (lag === 0) return", "  if (lag >= 0) return", "vitest",
     UP + "says each state the root reports"),
]


def run(repo: str, kind: str, check: str) -> tuple[bool, str]:
    root = HOME / repo
    if kind == "vitest":
        file, _, name = check.partition("::")
        result = subprocess.run(
            [NPX, "vitest", "run", file, *(["-t", name] if name else [])],
            cwd=Path(str(root).replace("d:", "D:")),
            env=ENV,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        output = result.stdout + result.stderr
        if not re.search(r"Tests\s+(\d+ failed \| )?[1-9]\d* (passed|failed)", output):
            raise SystemExit(f"{check} matched no test; update the instrument.\n{output}")
        return result.returncode == 0, output
    result = subprocess.run(
        [str(root / ".venv" / "Scripts" / "python.exe"), "-m", "pytest", "-q", "-p", "no:cacheprovider", check],
        cwd=root,
        env=ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )
    output = result.stdout + result.stderr
    if " passed" not in output and " failed" not in output:
        raise SystemExit(f"{check} ran no test; update the instrument.\n{output[-2000:]}")
    return result.returncode == 0, output


def broken(output: str) -> bool:
    return any(
        m in output
        for m in ("SyntaxError", "IndentationError", "ERROR collecting", "ImportError", "Transform failed", "error TS")
    )


def main() -> int:
    only = sys.argv[1:]
    cases = [c for c in CASES if not only or any(o in c[0] for o in only)]
    checks = sorted({(repo, kind, check) for _, repo, _, _, _, kind, check in cases})
    for repo, kind, check in checks:
        passed, output = run(repo, kind, check)
        if not passed:
            print(output[-3000:])
            raise SystemExit(f"Baseline failed ({repo} {check}); nothing changed.")
    print(f"Baseline: {len(checks)} checks pass.", flush=True)
    backup = Path(tempfile.mkdtemp(prefix="standby-sabotage-"))
    print(f"Exact backups: {backup}", flush=True)
    caught = 0
    for index, (label, repo, name, before, after, kind, check) in enumerate(cases):
        path = HOME / repo / name
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(before) != 1:
            raise SystemExit(f"{repo}/{name}: the anchor for '{label}' is not unique or gone.")
        (backup / f"{index}-{path.name}").write_bytes(original)
        try:
            path.write_bytes(text.replace(before, after).encode("utf-8"))
            passed, output = run(repo, kind, check)
            ok = not passed and not broken(output)
            print(f"{'CAUGHT' if ok else 'ESCAPED'}: {label}", flush=True)
            if not ok:
                print(output[-2500:])
            caught += ok
        finally:
            path.write_bytes(original)
            assert path.read_bytes() == original
    for repo, kind, check in checks:
        passed, output = run(repo, kind, check)
        if not passed:
            print(output[-3000:])
            raise SystemExit(f"Restored baseline failed ({repo} {check}).")
    print(f"{caught}/{len(cases)} caught; restored baseline passes.")
    return 0 if caught == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
