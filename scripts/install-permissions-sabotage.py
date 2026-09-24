"""Install-permissions sabotage pass: put each hole back and prove a check notices.

Found 2026-09-24: `%ProgramData%\\EugenePlexus` inherited
`BUILTIN\\Users:(OI)(CI)(RX)` and `(CI)(WD,AD)`, so every local account
could read node.yaml (the install's signing key) and add files the
LocalSystem service would run. The fix is `Protect-InstallDirectory` in
install.ps1 and `install_permissions` in the agent.

Restores from a COPY, never `git checkout --`, and opens with a baseline
assertion that both gates pass unsabotaged (memory:
`sabotage-runs-restore-from-a-copy`). Each sabotage is a plausible wrong
implementation, not a random mutation.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
INSTALLER = ("specs", "scripts/install.ps1")
CHECK = ("agent", "src/eugene_plexus_agent/install_permissions.py")
APP = ("agent", "src/eugene_plexus_agent/app.py")
HEALTH = ("agent", "src/eugene_plexus_agent/routes/health.py")
FILES = (INSTALLER, CHECK, APP, HEALTH)
TIMEOUT = 600

# (label, (repo, file), old, new)
SABOTAGES: list[tuple[str, tuple[str, str], str, str]] = [
    # --- the installer -------------------------------------------------------
    (
        "the prefix keeps what %ProgramData% hands down",
        INSTALLER,
        "        $acl.SetAccessRuleProtection($true, $false)\n",
        "        $acl.SetAccessRuleProtection($false, $true)\n",
    ),
    (
        "Users may list the prefix AND read every file created in it",
        INSTALLER,
        '"S-1-5-32-545" "ReadAndExecute" $thisFolder',
        '"S-1-5-32-545" "ReadAndExecute" $all',
    ),
    (
        "Users may add files to the venv, not only read it",
        INSTALLER,
        '@{ Name = "venv"; Sid = "S-1-5-32-545"; Rights = "ReadAndExecute" },',
        '@{ Name = "venv"; Sid = "S-1-5-32-545"; Rights = "Modify" },',
    ),
    (
        "the doors open the folder but not the files in it",
        INSTALLER,
        "        $subAcl.AddAccessRule((& $rule $door.Sid $door.Rights $all))\n",
        "        $subAcl.AddAccessRule((& $rule $door.Sid $door.Rights $thisFolder))\n",
    ),
    (
        "the person's model folder is closed to them",
        INSTALLER,
        '@{ Name = "models"; Sid = $PersonSid; Rights = "Modify" }',
        '@{ Name = "models"; Sid = "S-1-5-18"; Rights = "Modify" }',
    ),
    (
        "a per-user install forgets the person it runs as",
        INSTALLER,
        '        else { $acl.AddAccessRule((& $rule $PersonSid "FullControl" $all)) }\n',
        "",
    ),
    (
        "a volume without ACLs stops the install",
        INSTALLER,
        "    catch {\n        Warn (\"could not make $Path private",
        "    catch {\n        throw $_\n        Warn (\"could not make $Path private",
    ),
    (
        "the installer never protects before the venv is written",
        INSTALLER,
        "Protect-InstallDirectory -Path $Prefix -Service:$WantsService | Out-Null\n",
        "",
    ),
    # --- the agent's check ---------------------------------------------------
    (
        "an object-inherit read on the folder is not a finding",
        CHECK,
        "            if holds_secrets and ace.flags & OBJECT_INHERIT_ACE and ace.mask & _READ:\n",
        "            if False:\n",
    ),
    (
        "adding files to the folder is not a finding",
        CHECK,
        "            if effective and ace.mask & _WRITE:\n",
        "            if False:\n",
    ),
    (
        "an inherit-only ACE counts on the folder itself",
        CHECK,
        "        effective = not ace.flags & INHERIT_ONLY_ACE\n",
        "        effective = True\n",
    ),
    (
        "the agent's own account is a stranger",
        CHECK,
        "    trusted = _TRUSTED | {own_sid}\n",
        "    trusted = _TRUSTED\n",
    ),
    (
        "a deny ACE is read as a grant",
        CHECK,
        "        if ace.type != ACCESS_ALLOWED_ACE_TYPE or ace.sid in trusted:\n",
        "        if ace.sid in trusted:\n",
    ),
    (
        "reading the interpreter is a finding",
        CHECK,
        "            if holds_secrets and ace.flags & OBJECT_INHERIT_ACE",
        "            if ace.flags & OBJECT_INHERIT_ACE",
    ),
    (
        "node.yaml itself is never read",
        CHECK,
        '_SECRET_FILES = ("node.yaml", "agent.yaml")\n',
        '_SECRET_FILES = ("agent.yaml",)\n',
    ),
    (
        "the check's findings never reach app.state",
        APP,
        "    app.state.install_permissions = [grant.sentence() for grant in grants]\n",
        "",
    ),
    (
        "healthz says nothing about them",
        HEALTH,
        '    return {"installPermissions": sentences} if sentences else {}\n',
        "    return {}\n",
    ),
]


def run(repo: str) -> tuple[int, str]:
    if repo == "agent":
        py = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"
        argv = [
            str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
            "tests/test_install_permissions.py", "tests/test_health.py",
        ]
    else:
        tests = ROOT / "specs" / "scripts" / "install-preflight.Tests.ps1"
        # `-Quiet`, not `-Show None`: this box has Pester 3.4, where `-Show`
        # does not exist -- and the first version of this gate used it, so
        # Invoke-Pester errored, `$r` was null, `exit $null.FailedCount` was
        # exit 0, and all eight installer sabotages "escaped". A gate that
        # cannot run must fail, so no result and no tests run are both 99.
        argv = [
            "powershell.exe", "-NoProfile", "-Command",
            "$ErrorActionPreference = 'Stop'; "
            f"$r = Invoke-Pester -Path '{tests}' -PassThru -Quiet; "
            "if ($null -eq $r -or $r.TotalCount -eq 0) { exit 99 }; exit $r.FailedCount",
        ]
    try:
        done = subprocess.run(
            argv, cwd=ROOT / repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    backup = Path(tempfile.mkdtemp(prefix="install-permissions-sabotage-"))
    for repo, relative in FILES:
        destination = backup / repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")

    for repo in ("agent", "specs"):
        code, out = run(repo)
        print(f"[baseline {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()

    caught = escaped = 0
    for label, (repo, relative), old, new in SABOTAGES:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run(repo)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")
    for repo in ("agent", "specs"):
        code, out = run(repo)
        print(f"[restored {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
