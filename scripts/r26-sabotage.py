#!/usr/bin/env python
"""R2.6 sabotage: put each defect back and confirm something catches it.

A check that passes proves nothing until it has been shown to fail. Six
of the adversarial review's findings were sitting under a green test
that asserted the wrong subject, and this project has produced a check
that could not fail in almost every slice it has shipped.

**Restore is from a COPY, never `git checkout --`.** The first sabotage
run this project ever did used `git checkout --`, which reverts
UNCOMMITTED work -- so it deleted the change under test and every result
after the first read *caught* for the real reason. The baseline below is
the other half of that lesson: the gate is asserted GREEN before
anything is sabotaged, so "it failed" cannot mean "it was already
failing".

Usage:
    python scripts/r26-sabotage.py            # every sabotage
    python scripts/r26-sabotage.py --list
    python scripts/r26-sabotage.py --only console-alloc
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

EP_ROOT = Path(__file__).resolve().parents[2]
AGENT = EP_ROOT / "agent"
UI = EP_ROOT / "ui"
SPECS = EP_ROOT / "specs"
AGENT_PY = AGENT / ".venv" / "Scripts" / "python.exe"


@dataclass
class Sabotage:
    """One defect put back, and the gate that should notice."""

    name: str
    why: str
    path: Path
    old: str
    new: str
    gate: list[str]
    cwd: Path
    #: Set when a sabotage is expected to escape, with the reason. An
    #: escape recorded is worth more than an escape patched over with a
    #: test that only looks like it could catch it.
    expected_escape: str | None = None
    extra: dict = field(default_factory=dict)


PYTEST = [str(AGENT_PY), "-m", "pytest", "-q", "-p", "no:randomly"]
VITEST = ["npx", "vitest", "run"]

SABOTAGES: list[Sabotage] = [
    # --- the console ---------------------------------------------------
    Sabotage(
        name="console-alloc",
        why=(
            "ensure_console stops allocating. This is install-paths §7's "
            "accepted hard kill put back: every engine gets TerminateProcess "
            "instead of its shutdown hooks."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "process_signals.py",
        old="        kernel32.AllocConsole()",
        new="        pass  # SABOTAGE",
        gate=[*PYTEST, "tests/test_windows_supervision.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="console-ordering",
        why=(
            "the service allocates its console AFTER build_server rather than "
            "before. A child inherits the console the parent held AT SPAWN "
            "TIME, so the event would fail for exactly the children already "
            "running -- worse than failing for all of them."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "winservice.py",
        old="            process_signals.ensure_console()",
        new="            pass  # SABOTAGE: moved after the first spawn",
        gate=[*PYTEST, "tests/test_winservice.py"],
        cwd=AGENT,
        expected_escape=(
            "ORDERING IS NOT OBSERVABLE FROM A UNIT TEST. SvcDoRun needs a "
            "real SCM to run at all, so nothing here can watch the sequence; "
            "the only instrument that could is the elevated session-0 check "
            "in `install.ps1 -Verify`. Recorded rather than covered by a test "
            "that would assert the source text and call it behaviour."
        ),
    ),
    # --- reach -----------------------------------------------------------
    Sabotage(
        name="restart-timeout",
        why=(
            "the restart helper goes back to `timeout /t 3`, measured to exit "
            "rc 125 in 0.18 s under stdin=DEVNULL -- so the start is issued "
            "before the stop finishes and the helper reports success anyway."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "reach.py",
        old='    attempts = [start]\n    attempts += [f"(ping -n {n} 127.0.0.1 >nul & {start})" for n in _RESTART_PACES]\n    return f"{stop} & " + " || ".join(attempts)',
        new='    return f"{stop} & timeout /t 3 /nobreak >nul & {start}"  # SABOTAGE',
        gate=[*PYTEST, "tests/test_reach.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="restart-single-attempt",
        why=(
            "the pacer stays but the start is tried once. A service that takes "
            "longer than one ping never comes back, and nothing reports it."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "reach.py",
        old='    attempts = [start]\n    attempts += [f"(ping -n {n} 127.0.0.1 >nul & {start})" for n in _RESTART_PACES]',
        new='    attempts = [f"(ping -n 3 127.0.0.1 >nul & {start})"]  # SABOTAGE',
        gate=[*PYTEST, "tests/test_reach.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="service-session-only",
        why=(
            "session 0 alone decides again -- the unscoped check. A "
            "SYSTEM-principal task, PsExec -s, or ANOTHER INSTALL'S service "
            "all answer `service` and get handed an `sc stop` aimed at "
            "somebody else's agent. This is the S5 note on the other branch."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "reach.py",
        old="    if not _running_as_windows_service():\n        return False\n    image = _service_image_path(WINDOWS_SERVICE_NAME)",
        new="    return _running_as_windows_service()  # SABOTAGE\n    image = _service_image_path(WINDOWS_SERVICE_NAME)",
        gate=[*PYTEST, "tests/test_reach.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="service-unreadable-fails-open",
        why=(
            "an unreadable service entry falls back to 'well, session 0'. The "
            "tempting version of the fix, and it fails open onto the same "
            "`sc stop`."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "reach.py",
        old="    if image is None:",
        new="    if False:  # SABOTAGE",
        gate=[*PYTEST, "tests/test_reach.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="service-no-detail",
        why=(
            "the service branch loses its `detail` again -- the field R2.6 "
            "exists to put on a screen, and the one that distinguishes "
            "'comes back at boot' from 'comes back when you log in'."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "reach.py",
        old='            detail="This agent starts at boot, before anyone signs in.",',
        new="            # SABOTAGE: no detail",
        gate=[*PYTEST, "tests/test_reach.py"],
        cwd=AGENT,
    ),
    # --- share credentials ------------------------------------------------
    Sabotage(
        name="password-not-merged",
        why=(
            "THE ONE THAT COSTS AN INSTALL ITS MODELS. A UI writes back the "
            "row it was shown, whose password is null, and the merge is gone "
            "-- so the secret is lost and nothing says so until the next "
            "reboot."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "share_credentials.py",
        old='            previous = by_host.get(host.casefold())\n            if previous is not None and has_password(previous):\n                kept["password"] = previous["password"]\n            else:\n                kept["password"] = None',
        new='            kept["password"] = None  # SABOTAGE',
        gate=[*PYTEST, "tests/test_share_credentials.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="password-not-sealed",
        why="the password is written to agent.yaml in the clear.",
        path=AGENT / "src" / "eugene_plexus_agent" / "share_credentials.py",
        old='            kept["password"] = security.seal(str(entry["password"]), master_key).to_dict()',
        new='            kept["password"] = str(entry["password"])  # SABOTAGE',
        gate=[*PYTEST, "tests/test_share_credentials.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="password-not-redacted",
        why=(
            "GET /v1/config hands the password back. A UI that never holds a "
            "secret cannot leak one; this is what makes that true."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "routes" / "config.py",
        old="    stored = getattr(document, SHARE_CREDENTIALS_KEY, None)\n    if stored:",
        new="    stored = None  # SABOTAGE\n    if stored:",
        gate=[*PYTEST, "tests/test_share_credentials.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="empty-password-keeps",
        why=(
            "clearing a password stops working -- absent and empty collapse "
            "into one meaning, and the field becomes a one-way door."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "share_credentials.py",
        old='        elif entry.get("password") == "":\n            kept["password"] = None',
        new='        elif entry.get("password") == "" and False:  # SABOTAGE\n            kept["password"] = None',
        gate=[*PYTEST, "tests/test_share_credentials.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="duplicate-server-accepted",
        why=(
            "two rows for one server save happily. Windows allows one login "
            "per server (1219), so the second could never take effect -- the "
            "operator sees it saved and the share still refused."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "share_credentials.py",
        old="        if key in seen:\n            return (\n                f\"{where}: {cleaned} is already listed.",
        new="        if key in seen and False:\n            return (\n                f\"{where}: {cleaned} is already listed.",
        gate=[*PYTEST, "tests/test_share_credentials.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="unc-host-accepted",
        why=(
            "a whole UNC path is accepted as a host, so the row is saved and "
            "silently dials a server called `\\\\nas\\downloads`."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "share_credentials.py",
        old='        if cleaned.startswith("\\\\\\\\") or cleaned.startswith("//"):',
        new="        if False:  # SABOTAGE",
        gate=[*PYTEST, "tests/test_share_credentials.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="envelope-rejected-by-validator",
        why=(
            "the validator refuses a sealed envelope, so the agent writes a "
            "config it cannot load -- the worst of the three failures "
            "available, because it only appears on the NEXT start."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "share_credentials.py",
        old="        if isinstance(password, dict) and _looks_like_envelope(password):\n            continue",
        new="        pass  # SABOTAGE",
        gate=[*PYTEST, "tests/test_share_credentials.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="1272-unexplained",
        why=(
            "the one error code a guest-open share produces loses its "
            "sentence, and an operator goes looking at the NAS for a password "
            "the share does not have."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "share_credentials.py",
        old='    1272: (\n        "Windows refused an unauthenticated connection to that server, so the "\n        "share needs a user name even if it does not need a password"\n    ),',
        new='    1272: "refused",  # SABOTAGE',
        gate=[*PYTEST, "tests/test_share_credentials.py"],
        cwd=AGENT,
    ),
    # --- the tray ---------------------------------------------------------
    Sabotage(
        name="tray-unknown-rounds-to-stopped",
        why=(
            "an unreadable service offers Start. One click that does nothing "
            "and looks broken, in front of somebody whose service is running."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "tray.py",
        old="    stopped = state == ServiceState.stopped",
        new="    stopped = state != ServiceState.running  # SABOTAGE",
        gate=[*PYTEST, "tests/test_tray.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="tray-access-denied-unexplained",
        why=(
            "the one failure whose fix is in the installer stops naming it, "
            "so a person concludes the button is broken."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "tray.py",
        old='    if "5:" in text or "Access is denied" in text:',
        new="    if False:  # SABOTAGE",
        gate=[*PYTEST, "tests/test_tray.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="tray-console-flash",
        why=(
            "every click flashes a black window on a machine somebody is "
            "about to play a game on, which reads as *something went wrong*."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "tray.py",
        old='            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),',
        new="            # SABOTAGE: no creationflags",
        gate=[*PYTEST, "tests/test_tray.py"],
        cwd=AGENT,
    ),
    # --- the way back in (2026-09-19) -------------------------------------
    Sabotage(
        name="tray-second-icon",
        why=(
            "the single-instance guard goes, so the Start menu entry -- whose "
            "whole job is to bring the icon back -- puts a SECOND icon beside "
            "an existing one every time it is clicked."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "tray.py",
        old="        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS",
        new="        return True  # SABOTAGE",
        gate=[*PYTEST, "tests/test_tray.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="tray-open-skipped-when-showing",
        why=(
            "the open action is skipped when an icon is already there -- which "
            "is exactly when somebody clicks the Start menu entry, because "
            "Eugene is stopped and the icon is still sitting in the tray."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "tray.py",
        old="    if wants_open:\n        opened, why = open_and_wait(port)",
        new="    if wants_open and claim_single_instance():  # SABOTAGE\n        opened, why = open_and_wait(port)",
        gate=[*PYTEST, "tests/test_tray.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="tray-opens-a-dead-port",
        why=(
            "the entry opens the browser without starting the service, so a "
            "person who stopped Eugene for a game clicks Eugene Plexus and "
            "gets connection refused -- which reads as broken, not stopped."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "tray.py",
        old="    state = query_state()\n    if state == ServiceState.stopped:\n        started, why = start_service()",
        new="    state = query_state()\n    if False:  # SABOTAGE\n        started, why = start_service()",
        gate=[*PYTEST, "tests/test_tray.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="tray-hide-is-a-one-way-door",
        why=(
            "'Hide this icon' stops naming where it comes back from. Before "
            "the Start menu entry existed this was literally a one-way door; "
            "the label is the fix's visible half."
        ),
        path=AGENT / "src" / "eugene_plexus_agent" / "tray.py",
        old='(_ID_QUIT, "Hide this icon (it is in your Start menu)", True),',
        new='(_ID_QUIT, "Hide this icon", True),  # SABOTAGE',
        gate=[*PYTEST, "tests/test_tray.py"],
        cwd=AGENT,
    ),
    Sabotage(
        name="installer-no-start-menu",
        why=(
            "no Start menu entry, so a stopped Eugene has no discoverable way "
            "back: the URL answers connection refused and the icon may have "
            "been hidden."
        ),
        path=SPECS / "scripts" / "install.ps1",
        old="    Add-StartMenuShortcut",
        new="    # SABOTAGE: no Start menu entry",
        gate=["bash", "scripts/r26-acceptance.sh"],
        cwd=SPECS,
    ),
    # --- the UI -----------------------------------------------------------
    Sabotage(
        name="ui-starts-when-silent",
        why=(
            "the Reach card stops saying what starts Eugene -- back to the "
            "state where a service and a logon task are indistinguishable "
            "from every screen in the product."
        ),
        path=UI / "src" / "lib" / "reach.ts",
        old="  const detail = reach?.restart?.detail?.trim();\n  return detail ? detail : null;",
        new="  return null; // SABOTAGE",
        gate=[*VITEST, "src/app/page.test.tsx"],
        cwd=UI,
    ),
    Sabotage(
        name="ui-starts-when-invents",
        why=(
            "an agent that said nothing gets a sentence anyway. A confident "
            "wrong claim about how a machine boots is the one thing on that "
            "card somebody would plan around."
        ),
        path=UI / "src" / "lib" / "reach.ts",
        old="  const detail = reach?.restart?.detail?.trim();\n  return detail ? detail : null;",
        new='  return reach?.restart?.detail?.trim() || "This agent starts at boot."; // SABOTAGE',
        gate=[*VITEST, "src/app/page.test.tsx"],
        cwd=UI,
    ),
    Sabotage(
        name="ui-password-blanked",
        why=(
            "the editor sends an empty string for an untouched row, so every "
            "edit anywhere on the page clears the stored password."
        ),
        path=UI / "src" / "components" / "ConfigField.tsx",
        old="        password: r.password,",
        new='        password: r.password ?? "", // SABOTAGE',
        gate=[*VITEST, "src/components/ShareCredentials.test.tsx"],
        cwd=UI,
    ),
    Sabotage(
        name="ui-stored-not-seeded",
        why=(
            "the bug writing the test actually found: `stored` starts "
            "all-false, so every row the server already holds renders as a "
            "row with no password -- the exact confusion the flag prevents."
        ),
        path=UI / "src" / "components" / "ConfigField.tsx",
        old="  const [stored, setStored] = useState<boolean[]>(() =>\n    incoming.map((r) => r.host.trim().length > 0),\n  );",
        new="  const [stored, setStored] = useState<boolean[]>(incoming.map(() => false)); // SABOTAGE",
        gate=[*VITEST, "src/components/ShareCredentials.test.tsx"],
        cwd=UI,
    ),
    # --- the installer -----------------------------------------------------
    Sabotage(
        name="installer-detect-exits",
        why=(
            "`-Detect` goes back to `exit 3`, which inside a scriptblock ends "
            "the CALLER'S process -- closing the operator's terminal in "
            "exactly the case the switch exists to report."
        ),
        path=SPECS / "scripts" / "install.ps1",
        old="    if (-not $clean -and -not $Migrate) { $global:LASTEXITCODE = 3 }",
        new="    if (-not $clean -and -not $Migrate) { exit 3 }",
        gate=["bash", "scripts/r26-acceptance.sh"],
        cwd=SPECS,
    ),
    Sabotage(
        name="installer-no-service-default",
        why=(
            "the default goes back to elevation-decides, so an ordinary "
            "`irm | iex` produces the logon task that cannot keep the promise."
        ),
        path=SPECS / "scripts" / "install.ps1",
        old="$WantsService = -not ($NoService -or $Uninstall)",
        new="$WantsService = $IsElevated -and -not ($NoService -or $Uninstall)",
        gate=["bash", "scripts/r26-acceptance.sh"],
        cwd=SPECS,
    ),
    Sabotage(
        name="installer-no-sdset",
        why=(
            "the tray gets no permission to stop the service, so every click "
            "is Access denied and 'turn Eugene off to play a game' becomes "
            "'acknowledge a UAC prompt to play a game'."
        ),
        path=SPECS / "scripts" / "install.ps1",
        old="        Grant-ServiceControl",
        new="        # SABOTAGE: no grant",
        gate=["bash", "scripts/r26-acceptance.sh"],
        cwd=SPECS,
    ),
    Sabotage(
        name="installer-pins-disagree",
        why=(
            "install.sh and install.ps1 pin different commits, so the two "
            "platforms ship different installs and nobody notices until one "
            "of them misbehaves."
        ),
        path=SPECS / "scripts" / "install.sh",
        old="PIN_AGENT=",
        new="PIN_AGENT=0000000000000000000000000000000000000000  # SABOTAGE\nPIN_AGENT_REAL=",
        gate=["bash", "scripts/r26-acceptance.sh"],
        cwd=SPECS,
    ),
]


def _resolve(argv: list[str]) -> list[str]:
    """Windows `CreateProcess` will not find `npx` or `bash` by name.

    `shutil.which` finds the `.cmd` shim and the Git Bash exe that a
    shell would; `shell=True` would find them too and would also hand
    the whole command line to `cmd`, which is a quoting problem this
    script does not need.
    """
    found = shutil.which(argv[0])
    return [found, *argv[1:]] if found else argv


def run_gate(sab: Sabotage) -> tuple[bool, str]:
    """Run the gate. `(passed, tail)`."""
    done = subprocess.run(
        _resolve(sab.gate), cwd=sab.cwd, capture_output=True, text=True, timeout=900, shell=False
    )
    output = (done.stdout or "") + (done.stderr or "")
    return done.returncode == 0, output[-600:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()

    chosen = [s for s in SABOTAGES if not args.only or s.name in args.only]
    if args.list:
        for sab in chosen:
            print(f"{sab.name:34s} {sab.why.splitlines()[0]}")
        return 0

    # **The baseline, and it is not a formality.** If the gate is already
    # red, every sabotage below "is caught" for a reason that has nothing
    # to do with it -- which is precisely how this project's first
    # sabotage run produced a page of meaningless passes.
    print("== baseline: every gate green before anything is sabotaged")
    baseline_failed = []
    for gate, cwd in {(tuple(s.gate), s.cwd) for s in chosen}:
        passed, tail = run_gate(Sabotage("", "", Path(), "", "", list(gate), cwd))
        label = " ".join(gate[-2:])
        if passed:
            print(f"  OK      {label}")
        else:
            print(f"  BROKEN  {label}\n{tail}")
            baseline_failed.append(label)
    if baseline_failed:
        print("\nrefusing to sabotage against a red gate:", ", ".join(baseline_failed))
        return 1

    caught, escaped = [], []
    for sab in chosen:
        print(f"\n== {sab.name}\n   {sab.why}")
        if not sab.path.exists():
            print(f"   SKIP  no such file: {sab.path}")
            continue
        original = sab.path.read_text(encoding="utf-8")
        if sab.old not in original:
            print("   SKIP  the code to sabotage is not there any more (did it move?)")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            # A COPY, never `git checkout --`.
            backup = Path(tmp) / sab.path.name
            shutil.copy2(sab.path, backup)
            try:
                sab.path.write_text(original.replace(sab.old, sab.new, 1), encoding="utf-8")
                passed, tail = run_gate(sab)
            finally:
                shutil.copy2(backup, sab.path)
        if passed:
            print("   ESCAPED" + (f" (expected: {sab.expected_escape})" if sab.expected_escape else ""))
            if not sab.expected_escape:
                print(f"   ...gate output tail:\n{tail}")
            escaped.append(sab)
        else:
            print("   caught")
            caught.append(sab)

    unexpected = [s for s in escaped if not s.expected_escape]
    print(f"\n{len(caught)} caught, {len(escaped)} escaped "
          f"({len(unexpected)} unexpectedly)")
    for sab in escaped:
        marker = "expected" if sab.expected_escape else "UNEXPECTED"
        print(f"  {marker}: {sab.name}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
