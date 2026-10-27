"""Sabotage row 5's new checks (rows/row-05.md); each case names the test that catches it.

The sign-in key's schedule and the passphrase change: the re-seal, its two
nets, the compaction, the standby gate, where the new passphrase is sent
and how an agent takes it. Files are restored from exact bytes kept in
memory and on disk beside the run, never from Git. Every named check passes
first, and again after. A syntax or import error does not count as caught.

    python scripts/row5-sabotage.py [--home DIR] [label ...]

`--home` is the folder holding the control, agent and ui checkouts; by
default the one this specs checkout sits in (a row's worktrees included).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

NPX = "npx.cmd" if os.name == "nt" else "npx"
ENV = {
    k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")
} | {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}

C_APPLIED = "src/eugene_plexus_control/applied.py"
C_CHANGE = "src/eugene_plexus_control/passphrase_change.py"
C_SM = "src/eugene_plexus_control/state_machine.py"
C_REPL = "src/eugene_plexus_control/replication.py"
C_AUTHSTATE = "src/eugene_plexus_control/auth_state.py"
C_OIDC = "src/eugene_plexus_control/oidc.py"
C_OIDC_ROUTES = "src/eugene_plexus_control/routes/oidc.py"
C_AUTH = "src/eugene_plexus_control/routes/auth.py"
C_CTRL = "src/eugene_plexus_control/routes/control.py"
C_KEYS = "src/eugene_plexus_control/oidc_keys.py"
C_CONF = "src/eugene_plexus_control/config.py"
A_AUTH = "src/eugene_plexus_agent/routes/auth.py"
A_STATE = "src/eugene_plexus_agent/state.py"
U_CHANGE = "src/components/PassphraseChange.tsx"
U_LOGIN = "src/app/login/page.tsx"

CP = "tests/test_passphrase_change.py::"
CK = "tests/test_oidc_key_change.py::"
AP = "tests/test_passphrase_change.py::"

# (label, repo, file, before, after, kind, check)
CASES: list[tuple[str, str, str, str, str, str, str]] = [
    ("apply takes a change that misses a sealed value", "control", C_APPLIED,
     "    if shape(sealed) != shape(held):\n", "    if False:\n", "pytest",
     CP + "test_apply_refuses_a_change_that_misses_a_sealed_value"),
    ("the walk finds nothing", "control", C_CHANGE,
     "    return [path for path, value in _places(to_canonical(state)) if _opens(value, old_key)]",
     "    return []", "pytest",
     CP + "test_a_sealed_value_the_reseal_does_not_know_stops_the_change"),
    ("a value that does not open is kept as it is", "control", C_CHANGE,
     "            raise CannotOpen(what) from exc\n", "            return sealed\n", "pytest",
     CP + "test_a_value_that_does_not_open_stops_the_change_and_names_it"),
    ("no compaction after a change", "control", C_SM,
     "COMPACT_AFTER = frozenset({OP_CHANGE_PASSPHRASE})", "COMPACT_AFTER = frozenset()", "pytest",
     CP + "test_change_reseals_every_sealed_value"),
    ("the current passphrase is not checked", "control", C_AUTH,
     "    if verifier is None or not await asyncio.to_thread(\n        security.verify_passphrase, current, verifier\n    ):",
     "    if False:", "pytest",
     CP + "test_the_change_needs_the_current_passphrase_a_session_and_a_long_new_one"),
    ("a wrong current passphrase is not counted", "control", C_AUTH,
     (
         "        auth.record_login_failure(\n            remote,\n"
         "            window_seconds=_RATE_LIMIT_WINDOW_SECONDS,\n"
         "            max_in_window=_RATE_LIMIT_MAX_FAILURES,\n        )\n"
         "        log.warning(\"a passphrase change from %s gave the wrong current passphrase\", remote)"
     ),
     "        log.warning(\"a passphrase change from %s gave the wrong current passphrase\", remote)",
     "pytest", CP + "test_the_change_needs_the_current_passphrase_a_session_and_a_long_new_one"),
    ("no standby gate", "control", C_CTRL,
     "    return holder if _log_version(str(report.get(\"logVersion\") or 0)) < needed else None",
     "    return None", "pytest",
     CP + "test_the_change_waits_for_a_standby_that_cannot_apply_it"),
    ("sent over plain HTTP", "control", C_CHANGE,
     "        if name != own and not _on_this_machine(url) and machine_route(url) is None:",
     "        if False:", "pytest",
     CP + "test_the_new_passphrase_goes_only_where_it_is_kept_and_never_in_plain"),
    ("sent to a machine with no passphrase of its own", "control", C_CHANGE,
     "        if probe.own_passphrase is False:\n            continue\n", "", "pytest",
     CP + "test_the_new_passphrase_goes_only_where_it_is_kept_and_never_in_plain"),
    ("the old keyring entry is kept", "control", C_CHANGE,
     "    if old_id and old_id != new_id:\n        keyring_store.delete_master_key(old_id)\n", "",
     "pytest", CP + "test_the_keyring_moves_to_the_new_install_id"),
    ("a snapshot is matched on its salt again", "control", C_SM,
     "            names = (\"controlPublicKey\",) if held.controlPublicKey is not None else (\"salt\",)",
     "            names = (\"controlPublicKey\", \"salt\")", "pytest",
     CP + "test_a_standby_follows_the_change_by_entry_or_by_snapshot"),
    ("a routine change does not wait", "control", C_KEYS,
     "        if now() - changed < ROUTINE_MIN_AGE:\n", "        if False:\n", "pytest",
     CK + "test_change_signs_with_new_key_and_old_refresh_still_works"),
    ("End every app sign-in now retires nothing", "control", C_KEYS,
     "        machine.append(OP_RETIRE_OIDC_KEYS, {\"keep\": [jwk[\"kid\"]]})\n", "        pass\n",
     "pytest", CK + "test_end_sign_ins_refuses_old_refresh"),
    ("the timer changes a key that is not due", "control", C_KEYS,
     "    if due is None or now() < due:\n", "    if due is None:\n", "pytest",
     CK + "test_the_root_changes_the_key_when_it_is_due"),
    ("signInKeyDays takes 1 to 30", "control", C_CONF,
     "            and 0 < value < SIGN_IN_KEY_MIN_DAYS\n", "            and False\n", "pytest",
     CK + "test_sign_in_key_days_is_zero_or_at_least_31"),
    ("an agent derives a new key instead of wrapping its own", "agent", A_AUTH,
     "    kek_salt, wrapped = security.wrap_master_key(master_key, new)",
     "    kek_salt, wrapped = security.wrap_master_key(security.derive_master_key(new, b\"0123456789abcdef\"), new)",
     "pytest", AP + "test_wrapped_key_keeps_share_password_open"),
    ("the wrapped key is not read", "agent", A_STATE,
     "        if wrapped is not None:\n            return security.unwrap_master_key(",
     "        if False:\n            return security.unwrap_master_key(", "pytest",
     AP + "test_wrapped_key_keeps_share_password_open"),
    ("the root's change is taken in plain HTTP", "agent", A_AUTH,
     "    if request.url.scheme != \"https\" and not _from_this_machine(request):",
     "    if False:", "pytest", AP + "test_the_root_sends_the_new_passphrase_over_tls_only"),
    ("the root's change takes any token", "agent", A_AUTH,
     "    require_control(request, await _bearer_scheme(request))\n    if request.url.scheme",
     "    await _bearer_scheme(request)\n    if request.url.scheme", "pytest",
     AP + "test_the_root_sends_the_new_passphrase_over_tls_only"),
    ("a replayed change is taken", "agent", A_AUTH,
     "    if not await asyncio.to_thread(security.verify_passphrase, current, stored):",
     "    if False:", "pytest", AP + "test_the_root_sends_the_new_passphrase_over_tls_only"),
    ("a catch-up believes a session that does not verify", "agent", A_AUTH,
     "        claims = auth.trust.verify(signed_in.sessionToken, classes=(tokens.TYP_SESSION,))",
     "        claims = auth.trust.verify(auth.trust.mint_local_session()[0], classes=(tokens.TYP_SESSION,))",
     "pytest", AP + "test_a_session_that_does_not_verify_changes_nothing"),
    ("a locked machine is not asked for the old passphrase", "agent", A_AUTH,
     "            \"old-passphrase-needed\",", "            \"something-else\",", "pytest",
     AP + "test_a_locked_machine_asks_once_for_the_old_passphrase"),
    # The review (Codex, 2026-10-24).
    ("a value sealed under the old key is stored", "control", C_SM,
     "                if sealed_under != self._state.identity.salt:\n                    raise SealedUnderOldKey()\n",
     "", "pytest", CP + "test_a_secret_sealed_before_a_change_is_refused_not_stored"),
    ("a sealed write need not name its generation", "control", C_SM,
     "                if sealed_under is _UNSET:\n", "                if False:\n", "pytest",
     CP + "test_every_sealed_op_names_the_salt_it_sealed_under"),
    ("compaction runs inside the append again", "control", C_SM,
     "            self._pending_change = self._state.index\n            return\n",
     (
         "            self._store.write_snapshot(\n"
         "                to_canonical(self._state), compact_through=self._state.index - 1\n"
         "            )\n            return\n"
     ),
     "pytest", CP + "test_a_compaction_that_fails_leaves_the_new_key_in_effect"),
    ("a start does not finish a change's compaction", "control", C_SM,
     "                self._pending_change = changes[-1]\n", "                pass\n", "pytest",
     CP + "test_a_restart_finishes_a_compaction_a_crash_left"),
    ("a standby takes a change without noting its keyring entry", "control", C_REPL,
     "        if salt is not None and self._before_passphrase_change is not None:\n",
     "        if False:\n", "pytest",
     CP + "test_a_standby_follows_the_change_by_entry_or_by_snapshot"),
    ("the stale keyring note is not written", "control", C_CHANGE,
     "    if old_salt:\n        _private_write(\n", "    if False:\n        _private_write(\n",
     "pytest", CP + "test_a_standby_killed_before_its_cleanup_finishes_it_at_start"),
    ("two key changes at once both change it", "control", C_KEYS,
     "    with _CHANGE_LOCK:\n        machine = app.state.machine\n",
     "    with threading.Lock():\n        machine = app.state.machine\n", "pytest",
     CK + "test_two_routine_changes_at_once_change_the_key_once"),
    ("the root ignores a machine's unsaved file", "control", C_CHANGE,
     "            if isinstance(body, dict) and body.get(\"passphraseFile\") == \"old\":\n",
     "            if False:\n", "pytest",
     CP + "test_a_machine_that_could_not_save_its_file_says_so"),
    ("an agent hides a file it could not save", "agent", A_AUTH,
     "    return NodePassphraseResult.model_validate({\"passphraseFile\": file_state, \"detail\": why})",
     "    return NodePassphraseResult.model_validate({\"passphraseFile\": \"matches\"})", "pytest",
     AP + "test_the_root_hears_when_this_machine_could_not_save_its_file"),
    ("a changed machine's warning is not shown", "ui", U_CHANGE,
     "      ? `${machine.node}: changed, but ${machine.detail}`",
     "      ? `${machine.node}: changed`", "vitest",
     "src/app/people/page.test.tsx::changes Eugene's passphrase from the owner's row"),
    # The re-review (Codex, 2026-10-24).
    ("an unlock labels its key with the salt now, not its own", "control", C_AUTH,
     "    unseal_with_master_key(auth, machine, master_key, salt=identity.salt)",
     "    unseal_with_master_key(auth, machine, master_key, salt=machine.state.identity.salt)",
     "pytest", CP + "test_a_sign_in_the_change_overtook_publishes_no_key"),
    ("a key is published whatever the salt now", "control", C_AUTHSTATE,
     (
         "            if salt is None or current() != salt:\n                return False\n"
         "            self.set_master_key(key, salt=salt)"
     ),
     "            self.set_master_key(key, salt=current())", "pytest",
     CP + "test_a_change_between_the_check_and_the_publish_publishes_nothing"),
    ("a sign-in does not wait for the key in effect", "control", C_OIDC,
     "        if generation is not None and generation == machine.state.identity.salt:",
     "        if True:", "pytest", CP + "test_a_first_sign_in_during_the_handoff_is_asked_to_retry"),
    ("no Retry-After while the key changes", "control", C_OIDC_ROUTES,
     "        response.headers[\"Retry-After\"] = str(oidc.RETRY_AFTER_SECONDS)",
     "        pass", "pytest", CP + "test_a_first_sign_in_during_the_handoff_is_asked_to_retry"),
    ("plain is shown as changed", "ui", U_CHANGE,
     "  if (machine.state === \"plain\") return `${machine.node}: not sent: reached in plain HTTP`;",
     "  if (machine.state === \"plain\") return `${machine.node}: changed`;", "vitest",
     "src/app/people/page.test.tsx::changes Eugene's passphrase from the owner's row"),
    ("the old passphrase is not sent", "ui", U_LOGIN,
     "        previousNeeded && previous ? { passphrase, previousPassphrase: previous } : { passphrase },",
     "        { passphrase },", "vitest",
     "src/app/login/page.test.tsx::asks once for the old passphrase"),
]


def python_in(root: Path) -> Path:
    venv = root / ".venv"
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def run(home: Path, repo: str, kind: str, check: str) -> tuple[bool, str]:
    root = home / repo
    if kind == "vitest":
        file, _, name = check.partition("::")
        result = subprocess.run(
            [NPX, "vitest", "run", file, *(["-t", name] if name else [])],
            cwd=root, env=ENV, capture_output=True, text=True, encoding="utf-8", check=False,
        )  # fmt: skip
        output = result.stdout + result.stderr
        if not re.search(r"Tests\s+(\d+ failed \| )?[1-9]\d* (passed|failed)", output):
            raise SystemExit(f"{check} matched no test; update the instrument.\n{output}")
        return result.returncode == 0, output
    result = subprocess.run(
        [str(python_in(root)), "-m", "pytest", "-q", "-p", "no:cacheprovider", check],
        cwd=root, env=ENV, capture_output=True, text=True, encoding="utf-8", timeout=600, check=False,
    )  # fmt: skip
    output = result.stdout + result.stderr
    if " passed" not in output and " failed" not in output:
        raise SystemExit(f"{check} ran no test; update the instrument.\n{output[-2000:]}")
    return result.returncode == 0, output


def broken(output: str) -> bool:
    return any(
        m in output
        for m in ("SyntaxError", "IndentationError", "ERROR collecting", "ImportError",
                  "Transform failed", "error TS")
    )  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--home", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("only", nargs="*")
    args = parser.parse_args()
    home: Path = args.home
    cases = [c for c in CASES if not args.only or any(o in c[0] for o in args.only)]
    checks = sorted({(repo, kind, check) for _, repo, _, _, _, kind, check in cases})
    for repo, kind, check in checks:
        passed, output = run(home, repo, kind, check)
        if not passed:
            print(output[-3000:])
            raise SystemExit(f"Baseline failed ({repo} {check}); nothing changed.")
    print(f"Baseline: {len(checks)} checks pass.", flush=True)
    backup = Path(tempfile.mkdtemp(prefix="row5-sabotage-"))
    print(f"Exact backups: {backup}", flush=True)
    caught = 0
    for index, (label, repo, name, before, after, kind, check) in enumerate(cases):
        path = home / repo / name
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(before) != 1:
            raise SystemExit(f"{repo}/{name}: the anchor for '{label}' is not unique or gone.")
        (backup / f"{index}-{path.name}").write_bytes(original)
        try:
            path.write_bytes(text.replace(before, after).encode("utf-8"))
            passed, output = run(home, repo, kind, check)
            ok = not passed and not broken(output)
            print(f"{'CAUGHT' if ok else 'ESCAPED'}: {label}", flush=True)
            if not ok:
                print(output[-2500:])
            caught += ok
        finally:
            path.write_bytes(original)
            assert path.read_bytes() == original
    for repo, kind, check in checks:
        passed, output = run(home, repo, kind, check)
        if not passed:
            print(output[-3000:])
            raise SystemExit(f"Restored baseline failed ({repo} {check}).")
    print(f"{caught}/{len(cases)} caught; restored baseline passes.")
    return 0 if caught == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
