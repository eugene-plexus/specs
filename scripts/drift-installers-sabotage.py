"""Upstream drift audit 2026-10-03, the Windows half: put each defect back.

Two installer defects, found by `docs/maintenance/upstream-drift-2026-10-03.md`:

* **uv was never refreshed.** Step 1 skipped the download whenever a uv was
  there, and in-app updates re-run the installer, so an install kept its
  first uv forever -- through GHSA-2cv4-cqwr-gwf7, a path traversal in
  uv 0.12.7 to 0.12.17 on Windows. A uv older than `$UvMinimum` is now
  fetched again.
* **The Visual C++ runtime link was frozen at 14.44.** `aka.ms/vs/17` is
  Visual Studio 2022's final runtime, while llama.cpp's Windows builds come
  from Visual Studio 2026 (14.50+), and `Test-VcRuntime` asked only whether
  the DLLs existed. Now `aka.ms/vc14`, and msvcp140.dll must be 14.50+.

The gate is `install-preflight.Tests.ps1`'s two Describes for them, run
under Pester 3.4 (what CI's `dev-tasks` job imports). The POSIX half of the
uv fix is in `r37-sabotage.py`, which CI runs.

Works on a COPY: install.ps1, install.sh and the Pester file are copied to
a temporary directory and mutated there, so nothing in the working tree is
edited and nothing needs restoring. Opens with a baseline that must pass,
because a sabotage "caught" by an already-red gate proves nothing.

    python scripts/drift-installers-sabotage.py               # 13 sabotages
    python scripts/drift-installers-sabotage.py --before-ref REF
        # the gate against REF's installers: must FAIL (the defect, reproduced)

Windows only (it runs Windows PowerShell 5.1 and Pester 3.4.0).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
FILES = ("install.ps1", "install.sh", "install-preflight.Tests.ps1")
DESCRIBES = (
    "The Visual C++ runtime llama.cpp needs",
    "uv is fetched again when it is older than the installer keeps",
)

# (label, file, old, new): each a plausible wrong implementation.
SABOTAGES: list[tuple[str, str, str, str]] = [
    # --- uv ------------------------------------------------------------------
    (
        "uv: the download is skipped whenever any uv is present (the finding)",
        "install.ps1",
        "    if ($have -and $have -ge $UvMinimum) {\n",
        "    if (Test-Path $UvExe) {\n",
    ),
    (
        "uv: versions are compared as text",
        "install.ps1",
        "    if ($have -and $have -ge $UvMinimum) {\n",
        '    if ($have -and "$have" -ge "$UvMinimum") {\n',
    ),
    (
        "uv: a uv that is new enough is fetched again anyway",
        "install.ps1",
        "    if ($have -and $have -ge $UvMinimum) {\n",
        "    if ($false) {\n",
    ),
    (
        "uv: what the fetch left behind is never checked",
        "install.ps1",
        "    if (-not $now -or $now -lt $UvMinimum) {\n",
        "    if (-not $now) {\n",
    ),
    (
        "uv: uv's installer is no longer kept inside the prefix",
        "install.ps1",
        '    $env:UV_UNMANAGED_INSTALL = Join-Path $Prefix "bin"\n',
        "",
    ),
    (
        "uv: install.ps1's minimum drifts from install.sh's",
        "install.ps1",
        '$UvMinimum = [version]"0.12.18"',
        '$UvMinimum = [version]"0.12.7"',
    ),
    # --- the Visual C++ runtime ---------------------------------------------
    (
        "VC++: the Visual Studio 2022 link is back (the finding)",
        "install.ps1",
        '$VcRedistUrl = "https://aka.ms/vc14/vc_redist.$VcRedistArch.exe"',
        '$VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.$VcRedistArch.exe"',
    ),
    (
        "VC++: three DLLs present is enough again, whatever their version (the finding)",
        "install.ps1",
        "    return ($null -ne $version -and $version -ge $VcRuntimeMinimum)\n",
        "    return ($null -ne $version)\n",
    ),
    (
        "VC++: versions are compared as text",
        "install.ps1",
        "    return ($null -ne $version -and $version -ge $VcRuntimeMinimum)\n",
        '    return ($null -ne $version -and "$version" -ge "$VcRuntimeMinimum")\n',
    ),
    (
        "VC++: the minimum is Visual Studio 2022's",
        "install.ps1",
        '$VcRuntimeMinimum = [version]"14.50"',
        '$VcRuntimeMinimum = [version]"14.0"',
    ),
    (
        "VC++: an old runtime is reported as no runtime at all",
        "install.ps1",
        "    $vcLacks = if ($vcFound) {\n",
        "    $vcLacks = if ($false) {\n",
    ),
    (
        "VC++: a pending restart is reported as DLLs not in place",
        "install.ps1",
        "            elseif ($vcExit -eq 3010) {\n",
        "            elseif ($false) {\n",
    ),
    (
        "VC++: the version is read from a DLL other than msvcp140.dll",
        "install.ps1",
        '    return (Get-DllVersion (Join-Path $system "msvcp140.dll"))\n',
        '    return (Get-DllVersion (Join-Path $system "vcruntime140.dll"))\n',
    ),
]


def gate(root: Path) -> tuple[int, str]:
    tests = root / "install-preflight.Tests.ps1"
    names = ",".join(f"'{name}'" for name in DESCRIBES)
    # A gate that cannot run must fail: no result and no tests are both 99.
    command = (
        "$ErrorActionPreference = 'Stop'; Import-Module Pester -RequiredVersion 3.4.0; "
        f"$r = Invoke-Pester -Script '{tests}' -TestName {names} -PassThru -Quiet; "
        "if ($null -eq $r -or $r.TotalCount -eq 0) { exit 99 }; "
        "$r.TestResult | Where-Object { -not $_.Passed } | ForEach-Object { 'FAIL ' + $_.Describe + ': ' + $_.Name }; "
        "'TOTAL ' + $r.TotalCount + ' FAILED ' + $r.FailedCount; exit $r.FailedCount"
    )
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    return done.returncode, done.stdout


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before-ref", help="run the gate against this revision's installers")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ep-drift-installers-") as temporary:
        root = Path(temporary)
        for name in FILES:
            shutil.copy2(SCRIPTS / name, root / name)

        if args.before_ref:
            for name in ("install.ps1", "install.sh"):
                source = subprocess.check_output(
                    ["git", "show", f"{args.before_ref}:scripts/{name}"], cwd=SCRIPTS
                )
                (root / name).write_bytes(source)
            code, out = gate(root)
            print(out, end="")
            if code in (0, 99):
                print(f"the gate did not fail against {args.before_ref} (exit {code})")
                return 1
            print(f"the defects are reproduced against {args.before_ref}")
            return 0

        originals = {name: (root / name).read_bytes() for name in FILES}
        code, out = gate(root)
        print(f"[baseline] {'PASS' if code == 0 else 'FAIL'}  {out.strip().splitlines()[-1]}")
        if code != 0:
            print(out)
            return 1

        escaped = []
        for label, name, old, new in SABOTAGES:
            path = root / name
            source = originals[name].decode("ascii")
            text = source.replace("\r\n", "\n")
            if text.count(old) != 1:
                print(f"[DRIFTED] {label}: anchor matched {text.count(old)} times")
                escaped.append(label)
                continue
            try:
                path.write_bytes(text.replace(old, new).encode("ascii"))
                code, out = gate(root)
            finally:
                path.write_bytes(originals[name])
            caught = code not in (0, 99)
            print(f"[{'caught ' if caught else 'ESCAPED'}] {label}", flush=True)
            if not caught:
                escaped.append(label)

        code, out = gate(root)
        print(f"[restored] {'PASS' if code == 0 else 'FAIL'}")
        print(f"{len(SABOTAGES) - len(escaped)}/{len(SABOTAGES)} caught")
        return 0 if code == 0 and not escaped else 1


if __name__ == "__main__":
    sys.exit(main())
