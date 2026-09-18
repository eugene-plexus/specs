<#
.SYNOPSIS
  R2.2, the Windows half -- what `install.ps1` does when this machine
  already holds an install, and what it leaves behind when it stops.

.DESCRIPTION
  Roadmap: docs/design/release-roadmap.md section 3.2. Findings: review
  6.1 #10 (re-running elevated builds a second install and strands the
  first), 6.3 #31 (uninstall leaves two keyring entries), 6.2 #24 (the
  bind-port override never reaches the autostart), 6.2 #30
  (`--advertise` is honoured only in the join branch).

  **IT DRIVES A COPY WHOSE TASK AND SERVICE NAMES ARE REWRITTEN, AND
  THAT IS THE ONLY EDIT.** `install.ps1` refers to one fixed task name,
  `EugenePlexusAgent` -- which on this box is the live worker's task.
  The finding is precisely that the installer unregisters a task by that
  name without looking at whose it is, so reproducing it against the
  shipped names would stop Troy's own agent. The copy under the work
  directory carries `EugenePlexusR22Probe` instead, a decoy task is
  registered under that name, and everything destructive happens to the
  decoy.

  Registering a logon task for the current user needs no Administrator.
  Nothing here elevates, so the service branch is asserted by reading
  the script rather than by running it, and says so.

  **The keyring half is real.** The entries are stored, for real, in
  Windows Credential Manager, under a username scoped by a salt no other
  install has -- so the live install's own entry cannot be the subject
  and cannot be the casualty.
#>
[CmdletBinding()]
param(
    [string]$Work = (Join-Path $env:TEMP "ep-r22-ps"),
    [string]$AgentRepo = "d:\py\eugene-plexus\agent"
)

$ErrorActionPreference = "Stop"
$script:Failures = 0
function Say { param($m) Write-Host "`n== $m" }
function Ok { param($m) Write-Host "  PASS  $m" }
function Bad { param($m) Write-Host "  FAIL  $m"; $script:Failures++ }

$Here = Split-Path -Parent $PSCommandPath
$Source = Join-Path $Here "install.ps1"
if (-not (Test-Path $Source)) { throw "no install.ps1 beside this script" }

$ProbeTask = "EugenePlexusR22Probe"
$ProbeService = "EugenePlexusR22ProbeSvc"

if (Test-Path $Work) { Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $Work | Out-Null

# The copy, with only the two names changed.
$Copy = Join-Path $Work "install-probe.ps1"
$text = [IO.File]::ReadAllText($Source)
$text = $text.Replace('$ServiceName  = "EugenePlexusAgent"', "`$ServiceName  = `"$ProbeService`"")
$text = $text.Replace('$TaskName     = "EugenePlexusAgent"', "`$TaskName     = `"$ProbeTask`"")
[IO.File]::WriteAllText($Copy, $text, (New-Object Text.UTF8Encoding $false))
if ($text -match '\$TaskName\s+=\s+"EugenePlexusAgent"') {
    throw "the task name was not rewritten; refusing to run against the live install's task"
}

# A decoy install, and a decoy task that points into it.
$Decoy = Join-Path $Work "decoy"
New-Item -ItemType Directory -Force -Path (Join-Path $Decoy "venv\Scripts") | Out-Null
$DecoyExe = Join-Path $Decoy "venv\Scripts\eugene-plexus-agent.exe"
Copy-Item "$env:SystemRoot\System32\cmd.exe" $DecoyExe -Force
[IO.File]::WriteAllText((Join-Path $Decoy "agent.yaml"), "firstRunComplete: true`n")

function Remove-Probe {
    Get-ScheduledTask -TaskName $ProbeTask -ErrorAction SilentlyContinue |
        ForEach-Object { Unregister-ScheduledTask -TaskName $ProbeTask -Confirm:$false }
}
function Register-Decoy {
    Remove-Probe
    $a = New-ScheduledTaskAction -Execute $DecoyExe -Argument "--unattended" -WorkingDirectory $Decoy
    $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries
    Register-ScheduledTask -TaskName $ProbeTask -Action $a -Trigger $t -Settings $s `
        -Description "R2.2 decoy -- delete me" | Out-Null
}

# Run the copy and capture everything it said, plus its exit status.
function Invoke-Probe {
    param([string[]]$Arguments)
    # A refusal writes to stderr, and under $ErrorActionPreference =
    # "Stop" a native command's stderr is a terminating NativeCommandError
    # in PowerShell 5.1 -- so the check would die on the very behaviour it
    # is here to observe.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Copy @Arguments 2>&1 |
            ForEach-Object { "$_" }
        $script:ProbeRc = $LASTEXITCODE
    } finally { $ErrorActionPreference = $prev }
    return ($out -join "`n")
}

$LiveTask = Get-ScheduledTask -TaskName "EugenePlexusAgent" -ErrorAction SilentlyContinue

# **The installer writes account-wide variables, and this box is a
# worker node.** A probe run that ends normally repoints
# EUGENE_PLEXUS_AGENT_CONFIG_FILE at a throwaway prefix, which is the
# live install's identity gone -- the same shape as
# `acceptance-scripts-must-clear-the-environment`, one scope over.
# Snapshot every variable the installer touches and put them back
# whatever happens.
$ScopedVars = @("EUGENE_PLEXUS_AGENT_CONFIG_FILE", "EUGENE_PLEXUS_AGENT_BIND_HOST",
                "EUGENE_PLEXUS_AGENT_BIND_PORT", "EUGENE_PLEXUS_AGENT_ENGINE_ROOT",
                "EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS")
$Saved = @{}
foreach ($n in $ScopedVars) { $Saved[$n] = [Environment]::GetEnvironmentVariable($n, "User") }

# **The uninstall can now delete the engine store, and the default one
# on this box belongs to the live worker.** Point every probe at a
# throwaway before anything runs -- the child PowerShell inherits it, and
# `-PurgeDownloads` then removes a directory this script created.
$env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT = Join-Path $Work "engines"

try {
    # ------------------------------------------------------------------
    Say "1. the live install's task is untouched by anything here"
    if ($null -ne $LiveTask) {
        Ok "this box holds a real EugenePlexusAgent task; the probe uses $ProbeTask instead"
    } else {
        Ok "no live task on this box (the probe is isolated regardless)"
    }

    # ------------------------------------------------------------------
    Say "2. #10 -- a second prefix is detected rather than silently adopted"
    Register-Decoy
    $fresh = Join-Path $Work "second"
    $out = Invoke-Probe @("-Detect", "-Prefix", $fresh)
    if ($out -match [regex]::Escape($Decoy)) {
        Ok "-Detect names the install already on this machine"
    } else {
        Bad "-Detect does not name the other install"
        $out -split "`n" | Select-Object -Last 8 | ForEach-Object { Write-Host "      $_" }
    }
    if ($out -match "(?i)refus|different install|another install") {
        Ok "and says an ordinary run would not proceed"
    } else {
        Bad "-Detect does not say what an ordinary run would do"
    }

    # ------------------------------------------------------------------
    Say "3. #10 -- an ordinary run into a second prefix refuses, and takes nothing with it"
    Register-Decoy
    $out = Invoke-Probe @("-Prefix", $fresh, "-NoStart")
    if ($script:ProbeRc -ne 0) {
        Ok "the run stops with a non-zero status"
    } else {
        Bad "the run proceeded and built a second install"
    }
    $still = Get-ScheduledTask -TaskName $ProbeTask -ErrorAction SilentlyContinue
    if ($null -ne $still) {
        Ok "the other install's autostart is still registered"
    } else {
        Bad "the other install's autostart was unregistered without a word -- this is the finding"
    }
    if ($out -match "(?i)-Migrate|--migrate|migrate") {
        Ok "and the refusal names the way forward"
    } else {
        Bad "the refusal offers no way forward"
    }
    if (-not (Test-Path (Join-Path $fresh "venv"))) {
        Ok "nothing was installed into the second prefix"
    } else {
        Bad "the second prefix was populated before the refusal"
    }

    # ------------------------------------------------------------------
    Say "4. #10 -- the same prefix is recognised as this install and proceeds"
    Register-Decoy
    $out = Invoke-Probe @("-Detect", "-Prefix", $Decoy)
    if ($out -match "(?i)this install|same install|upgrade") {
        Ok "a run into the prefix the task already points at is an upgrade, not a second install"
    } else {
        Bad "the installer cannot tell its own install from somebody else's"
        $out -split "`n" | Select-Object -Last 8 | ForEach-Object { Write-Host "      $_" }
    }

    # ------------------------------------------------------------------
    Say "5. #10 -- -Migrate proceeds and says what it took over"
    Register-Decoy
    $out = Invoke-Probe @("-Detect", "-Prefix", $fresh, "-Migrate")
    if ($script:ProbeRc -eq 0 -and $out -match "(?i)migrat") {
        Ok "-Migrate is an explicit answer rather than a silent default"
    } else {
        Bad "-Migrate does not change the verdict"
    }

    # ------------------------------------------------------------------
    Say "5b. #10 -- an uninstall does not take somebody else's autostart"
    # **A sabotage named this check.** Removing the guard inside
    # `Remove-Autostart` was caught by nothing, because on the install
    # path `Assert-OwnInstall` refuses first -- so the guard, which is
    # the only thing protecting the autostart on the UNINSTALL path
    # (where refusing outright would be wrong: removing a named prefix
    # is how an operator recovers from #10), was never the subject.
    Register-Decoy
    $strayPrefix = Join-Path $Work "stray"
    New-Item -ItemType Directory -Force -Path $strayPrefix | Out-Null
    $out = Invoke-Probe @("-Uninstall", "-Prefix", $strayPrefix)
    $still = Get-ScheduledTask -TaskName $ProbeTask -ErrorAction SilentlyContinue
    if ($null -ne $still) {
        Ok "the other install's task survives an uninstall aimed elsewhere"
    } else {
        Bad "uninstalling one prefix unregistered another install's autostart"
    }
    if ($script:ProbeRc -ne 0) {
        Ok "and the uninstall says so rather than reporting success"
    } else {
        Bad "the uninstall reported success after refusing to touch the autostart"
    }

    # ------------------------------------------------------------------
    Say "5c. #10 -- a sibling virtualenv is not this install"
    # **A second sabotage named this one.** Loosening the comparison to
    # a bare StartsWith passed everything, because the only negative
    # case was a decoy in a different directory. `venv2` beside `venv`
    # is the realistic shape -- the same looseness a sabotage found in
    # S5's reach detector, which is why it was worth trying here.
    Remove-Probe
    $siblingExe = Join-Path $Decoy "venv2\Scripts\eugene-plexus-agent.exe"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $siblingExe) | Out-Null
    Copy-Item "$env:SystemRoot\System32\cmd.exe" $siblingExe -Force
    $a = New-ScheduledTaskAction -Execute $siblingExe -Argument "--unattended"
    $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    Register-ScheduledTask -TaskName $ProbeTask -Action $a -Trigger $t `
        -Description "R2.2 sibling probe -- delete me" | Out-Null
    $out = Invoke-Probe @("-Detect", "-Prefix", $Decoy)
    if ($script:ProbeRc -ne 0 -and $out -match "(?i)DIFFERENT install") {
        Ok "a task running from venv2 is not the install whose venv is venv"
    } else {
        Bad "venv2 beside venv reads as the same install"
    }

    # ------------------------------------------------------------------
    Say "6. #31 -- uninstall removes both keyring entries, for real"
    $py = Join-Path $AgentRepo ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Write-Host "  SKIP  no agent virtualenv at $py; the keyring half needs a real python"
    } else {
        $prefix = Join-Path $Work "keyring"
        New-Item -ItemType Directory -Force -Path $prefix | Out-Null
        # A junction to the agent's own virtualenv, because a copied
        # `python.exe` has no `pyvenv.cfg` beside it and dies before it
        # can import `keyring`. A junction needs no Administrator.
        New-Item -ItemType Junction -Path (Join-Path $prefix "venv") `
            -Target (Join-Path $AgentRepo ".venv") | Out-Null
        # A salt no install has, so the live install's entry is neither
        # the subject nor the casualty.
        $salt = "cjIyLXByb2JlLXNhbHQtMTY="
        [IO.File]::WriteAllText((Join-Path $prefix "agent.yaml"),
            "firstRunComplete: true`nauth:`n  masterSalt: $salt`n  passphraseHash: x`n",
            (New-Object Text.UTF8Encoding $false))

        $seed = @"
import base64, hashlib, keyring
salt = "$salt"
u = "master-key-" + hashlib.sha256(base64.b64decode(salt)).hexdigest()[:12]
for s in ("eugene-plexus-agent", "eugene-plexus-control"):
    keyring.set_password(s, u, "not-a-real-key")
print(u)
"@
        $seedFile = Join-Path $Work "seed.py"
        [IO.File]::WriteAllText($seedFile, $seed, (New-Object Text.UTF8Encoding $false))
        $username = (& $py $seedFile | Select-Object -Last 1).Trim()

        $probeScript = @"
import keyring
for s in ("eugene-plexus-agent", "eugene-plexus-control"):
    print(s, keyring.get_password(s, "$username") is not None)
"@
        $probeFile = Join-Path $Work "probe.py"
        [IO.File]::WriteAllText($probeFile, $probeScript, (New-Object Text.UTF8Encoding $false))

        $before = (& $py $probeFile) -join " "
        if ($before -match "eugene-plexus-agent True" -and $before -match "eugene-plexus-control True") {
            Ok "two entries are in Credential Manager before the uninstall"
        } else {
            Bad "the fixture did not land ($before); the check below would prove nothing"
        }

        Remove-Probe
        $out = Invoke-Probe @("-Uninstall", "-Prefix", $prefix)
        $after = (& $py $probeFile) -join " "
        if ($after -match "eugene-plexus-agent False") {
            Ok "the agent's entry is gone"
        } else {
            Bad "the agent's keyring entry outlived the install"
        }
        if ($after -match "eugene-plexus-control False") {
            Ok "the control root's entry is gone too -- the one the review did not count"
        } else {
            Bad "the control root's keyring entry outlived the install"
        }
        # Whatever happened, do not leave a secret behind.
        $cleanup = @"
import keyring, contextlib
for s in ("eugene-plexus-agent", "eugene-plexus-control"):
    with contextlib.suppress(Exception):
        keyring.delete_password(s, "$username")
"@
        $cleanupFile = Join-Path $Work "cleanup.py"
        [IO.File]::WriteAllText($cleanupFile, $cleanup, (New-Object Text.UTF8Encoding $false))
        & $py $cleanupFile | Out-Null
    }

    # ------------------------------------------------------------------
    Say "7. #31 -- the model copy directory is named and not deleted unasked"
    $prefix2 = Join-Path $Work "copies"
    $copyDir = Join-Path $Work "copystore"
    New-Item -ItemType Directory -Force -Path $prefix2, (Join-Path $copyDir "sub") | Out-Null
    Set-Content -LiteralPath (Join-Path $copyDir "sub\model.gguf") -Value "x" -Encoding Ascii
    [IO.File]::WriteAllText((Join-Path $prefix2 "agent.yaml"),
        "modelCopyEnabled: true`nmodelCopyDir: $copyDir`n",
        (New-Object Text.UTF8Encoding $false))
    New-Item -ItemType Directory -Force -Path (Join-Path $env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT "llama.cpp\b11026") | Out-Null
    Set-Content -LiteralPath (Join-Path $env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT "llama.cpp\b11026\llama-server.exe") -Value "x" -Encoding Ascii
    Remove-Probe
    $out = Invoke-Probe @("-Uninstall", "-Prefix", $prefix2)
    if ($out -match [regex]::Escape($env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT)) {
        Ok "the engine store outside the prefix is named"
    } else {
        Bad "the engine builds this install downloaded are left behind unmentioned"
    }
    if ($out -match [regex]::Escape($copyDir)) {
        Ok "the uninstall names the node-local model copy directory"
    } else {
        Bad "the model copy directory is left behind unmentioned"
    }
    if (Test-Path (Join-Path $copyDir "sub\model.gguf")) {
        Ok "and does not delete it without being asked"
    } else {
        Bad "the uninstall deleted the copies with no switch asking it to"
    }
    # The uninstall above moved the prefix aside, so the purge run needs
    # its own agent.yaml -- otherwise it would find no modelCopyDir and
    # "the directory is still there" would prove nothing.
    New-Item -ItemType Directory -Force -Path $prefix2 | Out-Null
    [IO.File]::WriteAllText((Join-Path $prefix2 "agent.yaml"),
        "modelCopyEnabled: true`nmodelCopyDir: $copyDir`n",
        (New-Object Text.UTF8Encoding $false))
    Remove-Probe
    $out = Invoke-Probe @("-Uninstall", "-Prefix", $prefix2, "-PurgeDownloads")
    if (-not (Test-Path $copyDir)) {
        Ok "-PurgeDownloads removes what we made"
    } else {
        Bad "-PurgeDownloads left the directory in place"
    }
    if (-not (Test-Path $env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT)) {
        Ok "and so is the engine store"
    } else {
        Bad "-PurgeDownloads left the engine store in place"
    }

    # ------------------------------------------------------------------
    Say "8. #24 -- the bind port reaches the autostart's environment"
    $portPrefix = Join-Path $Work "port"
    $savedPort = [Environment]::GetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", "User")
    try {
        Register-Decoy
        $env:EUGENE_PLEXUS_AGENT_BIND_PORT = "8179"
        $out = Invoke-Probe @("-Prefix", $portPrefix, "-NoStart", "-NoService", "-Migrate")
        $written = [Environment]::GetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", "User")
        if ($written -eq "8179") {
            Ok "the port the installer was told to use is where the autostart will read it"
        } else {
            Bad "the port override reaches nothing the autostart reads (got '$written')"
        }
        if ($out -match "8179") {
            Ok "and the closing lines point at the port the agent will answer on"
        } else {
            Bad "the closing lines name a port the agent will not be on"
        }
    } finally {
        $env:EUGENE_PLEXUS_AGENT_BIND_PORT = $null
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", $savedPort, "User")
    }

    # ------------------------------------------------------------------
    Say "9. #30 -- -Advertise is honoured with no -Join"
    $advPrefix = Join-Path $Work "adv"
    Register-Decoy
    $out = Invoke-Probe @("-Prefix", $advPrefix, "-NoStart", "-NoService", "-Migrate",
                          "-Advertise", "http://10.4.4.4:8079")
    $cfg = Join-Path $advPrefix "agent.yaml"
    if ((Test-Path $cfg) -and ((Get-Content -Raw $cfg) -match "advertiseUrl:\s*http://10\.4\.4\.4:8079")) {
        Ok "agent.yaml carries the address the operator asked for"
    } else {
        Bad "-Advertise was accepted and dropped on the floor outside the join branch"
    }
    if ((Test-Path $cfg) -and ([IO.File]::ReadAllBytes($cfg)[0] -ne 0xEF)) {
        Ok "and the file has no BOM -- yaml.safe_load would not survive one"
    } else {
        Bad "agent.yaml was written with a BOM"
    }

    # ------------------------------------------------------------------
    Say "10. #34 -- a non-ASCII install prefix survives the task read, live"
    # The unit test encodes the path the way the console does; this
    # registers a real task under a real accented directory and asks the
    # agent's own detector about it. Nothing simulated.
    $accented = Join-Path $Work ([char]0x00E9 + "quipe\venv")
    New-Item -ItemType Directory -Force -Path (Join-Path $accented "Scripts") | Out-Null
    $accentExe = Join-Path $accented "Scripts\eugene-plexus-agent.exe"
    Copy-Item "$env:SystemRoot\System32\cmd.exe" $accentExe -Force
    Remove-Probe
    $a = New-ScheduledTaskAction -Execute $accentExe -Argument "--unattended"
    $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    Register-ScheduledTask -TaskName $ProbeTask -Action $a -Trigger $t `
        -Description "R2.2 accent probe -- delete me" | Out-Null

    $pyA = Join-Path $AgentRepo ".venv\Scripts\python.exe"
    if (Test-Path $pyA) {
        $probe = @"
import sys
sys.path.insert(0, r"$AgentRepo\src")
from eugene_plexus_agent import reach

name = "$ProbeTask"
prefix = r"$accented"
com = reach._task_action_via_com(name)
text = reach._task_query_via_schtasks(name)
print("COM:", "MATCH" if (com and reach.task_runs_from_prefix(com, prefix)) else "miss", com)
print("TEXT:", "MATCH" if (text and reach.task_runs_from_prefix(text, prefix)) else "miss")
print("OEM:", reach.oem_encoding())
"@
        $f = Join-Path $Work "accent.py"
        [IO.File]::WriteAllText($f, $probe, (New-Object Text.UTF8Encoding $false))
        $got = (& $pyA $f 2>&1) -join "`n"
        if ($got -match "COM:\s+MATCH") {
            Ok "the COM reader matches a task whose program is under an accented prefix"
        } else {
            Bad "the COM reader missed it"
            $got -split "`n" | ForEach-Object { Write-Host "      $_" }
        }
        $oem = if ($got -match "OEM:\s+(\S+)") { $Matches[1] } else { "?" }
        if ($oem -ne "cp65001") {
            Ok "and this console writes $oem, not UTF-8, which is why the read had to be COM"
        } else {
            Write-Host "  NOTE  this box's OEM code page is UTF-8, so the text path would have worked here too"
        }
    } else {
        Write-Host "  SKIP  no agent virtualenv; the live half of #34 needs one"
    }
    Remove-Probe

    # ------------------------------------------------------------------
    Say "11. #10 -- a LocalSystem service is not offered the SYSTEM profile"
    # **A sabotage named this too.** Matching the variable NAMES passed
    # against a script that had stopped setting them, because the
    # uninstall lists the same names when it clears them. Match the
    # statement that sets each one to a Machine-scope value instead.
    $src = [IO.File]::ReadAllText($Source)
    $setsEngine = $src -match
        'SetEnvironmentVariable\("EUGENE_PLEXUS_AGENT_ENGINE_ROOT",\s*\$engineRoot,\s*"Machine"\)'
    $setsRoots = $src -match
        'SetEnvironmentVariable\("EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS",\s*\$modelRoot,\s*"Machine"\)'
    if ($setsEngine -and $setsRoots) {
        Ok "the elevated branch pins the engine root and the library's default roots"
    } else {
        Bad "an elevated install leaves both under config\systemprofile (engine=$setsEngine roots=$setsRoots)"
    }
    # The mechanism the fix relies on, exercised for real: the library's
    # roots really do default from that variable. Asserting the script
    # sets it proves nothing about whether setting it works.
    $libPy = Join-Path (Split-Path -Parent $AgentRepo) "library\.venv\Scripts\python.exe"
    if (Test-Path $libPy) {
        $probe = @"
import os
os.environ["EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS"] = r"C:\ProgramData\EugenePlexus\models"
from eugene_plexus_library.settings import load_settings
print(load_settings().default_model_roots)
"@
        $f = Join-Path $Work "libroots.py"
        [IO.File]::WriteAllText($f, $probe, (New-Object Text.UTF8Encoding $false))
        $got = (& $libPy $f 2>&1) -join " "
        if ($got -match "ProgramData") {
            Ok "and the library really takes its default roots from that variable"
        } else {
            Bad "the library does not read the variable the installer sets ($got)"
        }
    } else {
        Write-Host "  SKIP  no library virtualenv; the variable's effect is unexercised here"
    }
} finally {
    Remove-Probe
    $env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT = $null
    foreach ($n in $ScopedVars) {
        [Environment]::SetEnvironmentVariable($n, $Saved[$n], "User")
    }
    $restored = [Environment]::GetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", "User")
    Write-Host "`n   (account-wide variables restored; config file = '$restored')"
}

Write-Host ""
if ($script:Failures -eq 0) {
    Write-Host "R2.2 (Windows half): all checks passed"
    exit 0
} else {
    Write-Host "R2.2 (Windows half): $($script:Failures) FAILED"
    exit 1
}
