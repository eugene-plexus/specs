"""J14b + 2b.4 sabotage pass: signed calls and commands, and only the code
that changed (`person-held-keys.md` §13).

Restores from a COPY, never `git checkout --`, and opens with a baseline per
gate. Each entry puts one rule of the slice back, or takes one check out, and
names the gate that must notice:

- `site`: the site host's suites for the changed files, on Windows;
- `linux`: the command runner and the signed calls in WSL2's Linux, with the
  harness venv at `~/.cache/ep-job-sites/venv` (pytest added with `uv pip`)
  importing the working tree (`PYTHONPATH=src`);
- `control`: the root's relay of approvals and held answers;
- `workbench`: Workbench's signing wait;
- `web`: Workbench's page (vitest, started from `D:`: from `d:` it loads
  jest-dom twice);
- `agent`: the administrator's consent, the join's question and the tray.

Usage: python specs/scripts/j14b-sabotage.py [--gate NAME ...] [--label TEXT ...]
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
TIMEOUT = 600

SH = "site-host"
PKG = "site-host/src/eugene_plexus_site_host/"
HOST = PKG + "host.py"
CALLS = PKG + "calls.py"
COMMANDS = PKG + "commands.py"
WORKER = PKG + "worker.py"
CT_ROUTES = "control/src/eugene_plexus_control/routes/sites.py"
WB = "workbench/src/eugene_plexus_workbench/"
WEB = "workbench/web/src/components/"
AG = "agent/src/eugene_plexus_agent/"

SITE_TESTS = (
    "tests/test_signed_calls.py",
    "tests/test_commands.py",
    "tests/test_people.py",
    "tests/test_host.py",
)
LINUX_TESTS = ("tests/test_commands.py", "tests/test_signed_calls.py")

GATES: dict[str, tuple[str, list[str]]] = {
    "site": (SH, [
        str(ROOT / SH / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *SITE_TESTS,
    ]),
    "linux": (SH, [
        "wsl", "-e", "bash", "-lc",
        "cd /mnt/d/py/eugene-plexus/site-host && PYTHONPATH=src "
        "~/.cache/ep-job-sites/venv/bin/python -m pytest -q -x --no-header -p no:cacheprovider "
        + " ".join(LINUX_TESTS),
    ]),
    "control": ("control", [
        str(ROOT / "control" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_site_calls.py", "tests/test_site_people.py",
    ]),
    "workbench": ("workbench", [
        str(ROOT / "workbench" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_signed_calls.py",
    ]),
    "web": ("workbench/web", [
        "cmd", "/c", "npx", "vitest", "run",
        "src/components/ToolCalls.test.tsx", "src/components/JobSites.test.tsx",
    ]),
    "agent": ("agent", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_site_consent.py", "tests/test_tray.py",
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the site's checks (J81, J86, J90, J91) ------------------------------------------
    ("THE RULE: an ask call needs only a window, not its own signature", "site", HOST,
     'need = "call" if rule == "ask" or tool in file_server.COMMANDS else "window"',
     'need = "window"'),
    ("THE RULE: an allowed call runs with no window open", "site", HOST,
     '        window = self.calls.window(subject)\n        if need == "window" and window is not None:',
     '        window = self.calls.window(subject)\n        if need == "window":\n'
     '            return "no window"\n        if need == "window" and window is not None:'),
    ("a signature for one call runs another", "site", HOST,
     'if item.kind == "call" and not item.matches(server, tool, arguments):', "if False:"),
    ("THE RULE: a held call named again runs unsigned", "site", HOST,
     "            if item.signed is None:\n                raise Held(self._held_answer(item, call), poll=True)",
     "            if False:\n                raise Held(self._held_answer(item, call), poll=True)"),
    ("a signed call runs twice", "site", HOST,
     "            self.calls.remove(item.id)\n            if item.kind == \"call\":",
     "            pass\n            if item.kind == \"call\":"),
    ("a passkey's sequence is not spent", "site", HOST,
     "                self.sequence.accept(item.subject, seq)\n                self.passkeys.counted",
     "                pass\n                self.passkeys.counted"),
    ("THE RULE: a passkey assertion is not verified", "site", HOST,
     "                count = pk.verify_assertion(\n                    found,\n"
     "                    approval.envelope,",
     "                count = 0 and pk.verify_assertion(\n                    found,\n"
     "                    approval.envelope,"),
    ("a poll for a held call is recorded every time", "site", HOST,
     "            if not held.poll:", "            if True:"),
    ("a window never ends", "site", CALLS,
     "Window(time.time() + 60 * span, how)", "Window(time.time() + 10**9, how)"),
    ("closing a window leaves it open", "site", CALLS,
     "return self._windows.pop(subject, None) is not None", "return True"),
    # --- commands (J9, J84, J87-J89) -----------------------------------------------------
    ("THE RULE: commands offered without the administrator's consent", "site", HOST,
     "return self._keyed(subject) and self.consent.allowed()", "return self._keyed(subject)"),
    ("the worker starts commands without the consent it reads itself", "site", WORKER,
     "runs = bool(commandable) and await asyncio.to_thread(",
     "runs = bool(commandable) or await asyncio.to_thread("),
    ("a read-only workspace takes a command rule", "site", HOST,
     'if not writable and groups["command"] != "deny":', "if False:"),
    ("a workspace from before commands runs them", "site", HOST,
     '"command": rules.command.value if rules.command is not None else "deny",',
     '"command": rules.command.value if rules.command is not None else "ask",'),
    ("more than four commands run at once", "site", COMMANDS,
     "if self.running() >= MAX_RUNNING:", "if False:"),
    ("Eugene's own variables reach a command", "site", COMMANDS,
     'if not k.upper().startswith(("EUGENE_PLEXUS_", "SITE_HOST_"))', "if True"),
    ("an answer is not cut to its budget", "site", COMMANDS,
     "if answer_bytes(value) <= ANSWER_BUDGET or shown <= 1000:", "if True:"),
    ("a native program's exit code is not passed through (Windows)", "site", COMMANDS,
     '_EPILOGUE = "\\nif (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE } else { exit 1 } }\\nexit 0\\n"',
     '_EPILOGUE = "\\n"'),
    ("a command past its limit runs on", "site", COMMANDS,
     "await asyncio.wait_for(self._exited(entry.process), LIMIT_SECONDS)",
     "await self._exited(entry.process)"),
    ("what a command leaves running outlives it (Linux)", "linux", COMMANDS,
     "            # What it left behind goes with it, and with that its hold on the pipe.\n"
     "            entry.kill()\n",
     "            # What it left behind goes with it, and with that its hold on the pipe.\n"
     "            pass\n"),
    # Not `terminate()`'s group signal alone: the kill after any exit ends the
    # group too, so that one is redundant (it escaped, 2026-10-09). The group
    # kill itself is what both rest on.
    ("a command's tree is not killed as a group (Linux)", "linux", COMMANDS,
     "os.killpg(self.process.pid, signal.SIGKILL)", "os.kill(self.process.pid, signal.SIGKILL)"),
    # --- the root (control) -----------------------------------------------------------------
    ("THE RULE: the root drops the person's approval", "control", CT_ROUTES,
     "            approval=approval,\n        )", "            approval=None,\n        )"),
    ("the root does not relay what to sign", "control", CT_ROUTES,
     'for key in ("message", "response", "held"):', 'for key in ("message", "response"):'),
    ("an older site is asked to close a window", "control", CT_ROUTES,
     'if "commands" not in summary:', "if False:"),
    ("a linked person takes back the owner's consent", "control", CT_ROUTES,
     "    _, _, record = _own_site(request, body.refreshToken, site)\n    _checks_calls(request, record)\n"
     '    await _manage(request, body.refreshToken, site, "commands.withdraw", {})',
     "    _, _, record, _ = _my_site(request, body.refreshToken, site)\n    _checks_calls(request, record)\n"
     '    await _manage(request, body.refreshToken, site, "commands.withdraw", {}, mine=True)'),
    ("an absent command rule is sent as null (an older site refuses it)", "control", CT_ROUTES,
     'arguments["rules"] = body.rules.model_dump(mode="json", exclude_none=True)',
     'arguments["rules"] = body.rules.model_dump(mode="json")'),
    # --- Workbench ------------------------------------------------------------------------
    ("Workbench asks first where the site checks the signature", "workbench", WB + "tools.py",
     "        if signed:\n            # The site holds", "        if False:\n            # The site holds"),
    ("Workbench never sends a held call again", "workbench", WB + "answers.py",
     "                # it was signed at the machine.\n                return {\"held\": ident}",
     "                # it was signed at the machine.\n                return None"),
    ("Workbench runs a call the person did not sign", "workbench", WB + "answers.py",
     "            if not signed:\n                return None", "            if False:\n                return None"),
    ("the page offers commands without asking", "web", WEB + "Workspaces.tsx",
     "        choices={COMMAND_DECISIONS}", "        choices={DECISIONS}"),
    ("the page drops the command rule for a new workspace", "web", WEB + "Workspaces.tsx",
     '              ...(commands ? { command: writable ? command : "deny" } : {}),',
     "              ...{},"),
    ("the page hides what the machine holds", "web", WEB + "ToolCalls.tsx",
     '{call.status === "signing" && message.status === "running" && !readOnly && (',
     "{false && ("),
    # --- the agent (J30, J89) ----------------------------------------------------------------
    ("THE RULE: anyone records the consent", "agent", AG + "site_cli.py",
     "    if not elevated():\n        raise SiteError(\n            \"Allowing commands",
     "    if False:\n        raise SiteError(\n            \"Allowing commands"),
    ("adding a server drops the consent", "agent", AG + "site_cli.py",
     'write_list(config_dir, {**read_list(config_dir), "servers": servers})',
     'write_list(config_dir, {"servers": servers})'),
    ("the join consents with nobody to answer", "agent", AG + "site_cli.py",
     "            # Nobody to ask: no consent is given without an answer.\n            answer = False",
     "            # Nobody to ask: no consent is given without an answer.\n            answer = True"),
    ("the tray offers commands off a job site", "agent", AG + "tray.py",
     'return config if (Path(config).parent / "site").is_dir() else None', "return config"),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, command = GATES[name]
    where = str(ROOT / repo)
    try:
        done = subprocess.run(command, cwd=where, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:] + (done.stderr or "")[-500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="append", choices=sorted(GATES))
    parser.add_argument("--label", action="append", help="run only entries whose label has this")
    args = parser.parse_args()
    chosen = [
        s
        for s in SABOTAGES
        if (not args.gate or s[1] in args.gate)
        and (not args.label or any(part in s[0] for part in args.label))
    ]
    gates = sorted({s[1] for s in chosen})
    backup = Path(tempfile.mkdtemp(prefix="j14b-sabotage-"))
    for _label, _gate, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
    print(f"copy in {backup}\n")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, gate, relative, old, new in chosen:
        path = ROOT / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, _out = run_gate(gate)
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] ({gate}) {label}")
            caught += 1
        else:
            print(f"[ESCAPED] ({gate}) {label}")
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
