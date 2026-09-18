"""R2.2 sabotage pass: every check must fail when its defect is put back.

Run it after `r22-acceptance.sh`, and before believing either. Roadmap
§3.2; record `docs/acceptance/installer-advice-run.md` §3.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline — all three gates pass unsabotaged — because a
sabotage that "fails" against an already-red gate proves nothing.

**The first five entries are the findings themselves**, each put back
the way the repo actually had it: `sh -c "$(curl ...)"`, `>/dev/null
2>&1` over the package step, a unit with no bind port, `--advertise`
honoured only in the join branch, an uninstall that names one keyring
service, and `schtasks` decoded as UTF-8. The entries after them take
each fix apart one property at a time.

Three gates, because R2.2 is three programs: the agent's own pytest file
for #34's arithmetic, `install.sh` driven under Linux, and `install.ps1`
driven against a decoy scheduled task under Windows.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
SPECS = ROOT / "specs"

SH = "scripts/install.sh"
PS1 = "scripts/install.ps1"
REACH = "src/eugene_plexus_agent/reach.py"

# gate name -> how to run it
POSIX = "posix"
WINDOWS = "windows"
AGENT = "agent"


def _guest(path: Path) -> str:
    s = path.as_posix()
    if len(s) > 2 and s[1] == ":":
        return "/mnt/" + s[0].lower() + s[2:]
    return s


def run_gate(gate: str) -> tuple[int, str]:
    if gate == AGENT:
        py = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
             "tests/test_reach.py"],
            cwd=ROOT / "agent", capture_output=True, text=True, timeout=900,
        )
    elif gate == POSIX:
        done = subprocess.run(
            ["wsl.exe", "--", "bash", _guest(SPECS / "scripts" / "r22-install-sh-checks.sh")],
            capture_output=True, text=True, timeout=900,
        )
    else:
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(SPECS / "scripts" / "r22-install-ps1-checks.ps1")],
            capture_output=True, text=True, timeout=1800,
        )
    return done.returncode, (done.stdout or "")[-2500:] + (done.stderr or "")[-800:]


SABOTAGES: list[tuple[str, str, str, str, str, str]] = [
    # ---- the findings, put back ---------------------------------------
    (
        "install.sh: the uv bootstrap is `sh -c \"$(curl ...)\"` again (#24a, THE finding)",
        "specs", SH,
        '''    if ! curl -fsSL -o "$UV_BOOTSTRAP" https://astral.sh/uv/install.sh \\
            2>"$PREFIX/logs/uv-fetch.err"; then''',
        '''    if false; then''',
        POSIX,
    ),
    (
        "install.sh: the package step's output goes to /dev/null again (#24b/c, THE finding)",
        "specs", SH,
        '''    if "$@" >> "$STEP_LOG" 2>&1; then''',
        '''    if "$@" >/dev/null 2>&1; then''',
        POSIX,
    ),
    (
        "install.sh: the unit carries no bind port again (#24d, THE finding)",
        "specs", SH,
        "Environment=EUGENE_PLEXUS_AGENT_CONFIG_FILE=$CONFIG\n$WIDE_BIND_UNIT\n$PORT_UNIT\n",
        "Environment=EUGENE_PLEXUS_AGENT_CONFIG_FILE=$CONFIG\n$WIDE_BIND_UNIT\n",
        POSIX,
    ),
    (
        "install.sh: --advertise is join-only again (#30, THE finding)",
        "specs", SH,
        'elif [ -n "$JOIN_ADVERTISE" ]; then',
        'elif false; then',
        POSIX,
    ),
    (
        "install.sh: the uninstall knows about one keyring service again (#31, THE finding)",
        "specs", SH,
        'for service in ("eugene-plexus-agent", "eugene-plexus-control"):',
        'for service in ("eugene-plexus-agent",):',
        POSIX,
    ),
    (
        "agent: schtasks output is decoded as UTF-8 again (#34, THE finding)",
        "agent", REACH,
        'return (proc.stdout or b"").decode(oem_encoding(), errors="replace")',
        'return (proc.stdout or b"").decode("utf-8", errors="replace")',
        AGENT,
    ),
    (
        "install.ps1: the autostart is removed by name again (#10, THE finding)",
        "specs", PS1,
        '''    $exe = Get-AutostartExecutable
    if ($exe -and -not (Test-RunsFromThisInstall $exe) -and -not $Migrate) {
        Die "the autostart on this machine runs $exe, which is not this install. Use -Migrate to take it over."
    }''',
        "    # removed",
        WINDOWS,
    ),
    (
        "install.ps1: nothing is asserted before the install begins (#10)",
        "specs", PS1,
        "Assert-OwnInstall\n\n# --- 1. uv ---",
        "# --- 1. uv ---",
        WINDOWS,
    ),
    (
        "install.ps1: the uninstall names one keyring service again (#31)",
        "specs", PS1,
        'for service in ("eugene-plexus-agent", "eugene-plexus-control"):',
        'for service in ("eugene-plexus-agent",):',
        WINDOWS,
    ),
    (
        "install.ps1: -Advertise is join-only again (#30)",
        "specs", PS1,
        "} elseif ($Advertise) {",
        "} elseif ($false) {",
        WINDOWS,
    ),
    (
        "install.ps1: the bind port reaches nothing again (#24)",
        "specs", PS1,
        '''    [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", "$Port", "User")''',
        "    # removed",
        WINDOWS,
    ),
    (
        "install.ps1: an elevated install keeps the SYSTEM profile (#10)",
        "specs", PS1,
        '''        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_ENGINE_ROOT", $engineRoot, "Machine")''',
        "        # removed",
        WINDOWS,
    ),
    # ---- taking each fix apart ----------------------------------------
    (
        # The half a reviewer would assume is the whole fix: curl is
        # checked, but what it said is thrown away, so a TLS-intercepting
        # proxy is still unnamed.
        "install.sh: curl is checked and its stderr discarded",
        "specs", SH,
        '        sed \'s/^/  /\' "$PREFIX/logs/uv-fetch.err" >&2',
        "        :",
        POSIX,
    ),
    (
        "install.sh: a failed step prints no log tail",
        "specs", SH,
        '''    tail -n 20 "$STEP_LOG" | sed 's/^/  /' >&2''',
        "    :",
        POSIX,
    ),
    (
        # The advertise branch writes the file rather than editing it,
        # which loses an existing install's whole state.
        "install.sh: --advertise overwrites agent.yaml instead of editing it",
        "specs", SH,
        '''    if [ -f "$CONFIG" ]; then
        grep -v '^advertiseUrl:' "$CONFIG" > "$CONFIG.tmp"
        printf 'advertiseUrl: %s\\n' "$JOIN_ADVERTISE" >> "$CONFIG.tmp"
        mv "$CONFIG.tmp" "$CONFIG"
    else
        printf 'advertiseUrl: %s\\n' "$JOIN_ADVERTISE" > "$CONFIG"
    fi''',
        '''    printf 'advertiseUrl: %s\\n' "$JOIN_ADVERTISE" > "$CONFIG"''',
        POSIX,
    ),
    (
        # Advertising without binding: the field is set and nothing can
        # reach it, which is the failure `tailnet.md` calls the most
        # important instruction in the document.
        "install.sh: an advertised standalone install still binds loopback",
        "specs", SH,
        'if [ "$JOINED" = 1 ] || [ "$ADVERTISED" = 1 ]; then',
        'if [ "$JOINED" = 1 ]; then',
        POSIX,
    ),
    (
        "install.sh: the uninstall purges the model copies unasked",
        "specs", SH,
        '''        if [ "$DO_PURGE_COPIES" = 1 ]; then
            say "removing this node\'s model copies at $COPIES ($SIZE)"''',
        '''        if true; then
            say "removing this node\'s model copies at $COPIES ($SIZE)"''',
        POSIX,
    ),
    (
        "install.sh: --purge-model-copies does nothing",
        "specs", SH,
        "        --purge-downloads|--purge-model-copies) DO_PURGE_COPIES=1; shift ;;",
        "        --purge-downloads|--purge-model-copies) shift ;;",
        POSIX,
    ),
    (
        "install.sh: the uninstall does not name the copy directory",
        "specs", SH,
        '''            say "this node\'s model copies are at $COPIES ($SIZE) — they are copies, so"
            say "  deleting them loses nothing. Re-run with --purge-model-copies, or: rm -rf $COPIES"''',
        '            say "some files were left behind"',
        POSIX,
    ),
    (
        # The prefix comparison loosened to a bare StartsWith: a sibling
        # install (`venv2` beside `venv`) then reads as this one. The
        # same looseness a sabotage found in S5's reach detector.
        "install.ps1: the prefix comparison accepts a sibling virtualenv",
        "specs", PS1,
        "    return $a.StartsWith($b.TrimEnd('\\') + '\\', [StringComparison]::OrdinalIgnoreCase)",
        "    return $a.StartsWith($b, [StringComparison]::OrdinalIgnoreCase)",
        WINDOWS,
    ),
    (
        "install.ps1: every autostart is treated as this install's",
        "specs", PS1,
        "function Test-RunsFromThisInstall {\n    param([string]$Executable)\n    if (-not $Executable) { return $false }",
        "function Test-RunsFromThisInstall {\n    param([string]$Executable)\n    return $true\n    if (-not $Executable) { return $false }",
        WINDOWS,
    ),
    (
        "install.ps1: -Migrate is not an escape hatch, it is the default",
        "specs", PS1,
        "    if ($Migrate) {\n        Warn \"migrating: the autostart at $($other.Prefix) will be replaced by this install\"\n        return\n    }",
        "    Warn \"migrating: the autostart at $($other.Prefix) will be replaced by this install\"\n    return",
        WINDOWS,
    ),
    (
        "install.ps1: agent.yaml is written with a BOM",
        "specs", PS1,
        '''    [IO.File]::WriteAllText($Config, ($lines -join "`n") + "`n",
        (New-Object Text.UTF8Encoding $false))''',
        '''    [IO.File]::WriteAllText($Config, ($lines -join "`n") + "`n",
        (New-Object Text.UTF8Encoding $true))''',
        WINDOWS,
    ),
    (
        "install.ps1: the uninstall purges the model copies unasked",
        "specs", PS1,
        '''        if ($purge) {
            Say "removing this node's model copies at $copyDir ($gib GiB)"''',
        '''        if ($true) {
            Say "removing this node's model copies at $copyDir ($gib GiB)"''',
        WINDOWS,
    ),
    (
        "agent: the COM reader is never consulted (#34)",
        "agent", REACH,
        "    action = _task_action_via_com(WINDOWS_TASK_NAME)\n    if action is not None:",
        "    action = None\n    if action is not None:",
        AGENT,
    ),
    (
        # A bare path has a drive colon in it, so splitting on the label
        # separator unconditionally eats the drive letter -- the exact
        # trap that made the COM reader need its own comparison.
        "agent: a bare action path is split at its drive colon",
        "agent", REACH,
        "        if action_runs_from_prefix(line, prefix):\n            return True\n",
        "",
        AGENT,
    ),
    (
        "install.sh: the uninstall does not mention the engine store",
        "specs", SH,
        '''    ENGINES=$(engine_root)
    if [ -d "$ENGINES" ]; then''',
        '''    ENGINES=$(engine_root)
    if false; then''',
        POSIX,
    ),
    (
        "install.sh: --purge-downloads leaves the engine store",
        "specs", SH,
        '''            say "removing the engine store at $ENGINES ($ESIZE)"
            rm -rf "$ENGINES"''',
        '''            say "removing the engine store at $ENGINES ($ESIZE)"''',
        POSIX,
    ),
    (
        "install.ps1: the uninstall does not mention the engine store",
        "specs", PS1,
        "    if (Test-Path $engineRootPath) {",
        "    if ($false) {",
        WINDOWS,
    ),
]


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="r22-sabotage-"))
    touched = {(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES}
    for repo, rel in touched:
        dst = backup / repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / rel, dst)
    print(f"copies in {backup}\n")

    gates = sorted({g for *_, g in SABOTAGES})
    failures = []
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            failures.append(f"baseline {gate}\n{out}")
    if failures:
        print("\nBASELINE FAILED - a sabotage result would mean nothing.")
        print("\n".join(failures))
        return 1
    print()

    caught = escaped = 0
    for label, repo, rel, old, new, gate in SABOTAGES:
        path = ROOT / repo / rel
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate(gate)
        finally:
            shutil.copy2(backup / repo / rel, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}\n{out}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")

    for gate in gates:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
