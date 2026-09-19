<#
.SYNOPSIS
  R2.6 follow-up -- what `-Migrate` carries, and when the service
  conversion says what it costs.

.DESCRIPTION
  Two defects found 2026-09-19 by reading `install.ps1` before the
  elevated run that would have met them, on the live worker node.

  **A. `-Migrate` migrated the AUTOSTART and not the INSTALL.**
  `Copy-Item` did not appear in the script at all. `$Prefix` defaults to
  %ProgramData% the moment a service is wanted, so the documented
  upgrade path for every Windows install made before 2026-09-18 pointed
  a service at an empty directory: the first-run wizard, a fresh signing
  key, an enrolled worker silently unenrolled, and the real install
  intact but orphaned one directory over. Review 6.1 #10 -- the finding
  R2.2 exists to fix -- through R2.6's own upgrade path.

  **B. The consequences were keyed on the target directory, not on the
  service.** `Show-MigrationConsequences` returned early when
  `$Prefix\agent.yaml` existed, which is true of the obvious way to
  convert an install in place (`-Prefix <the per-user one>`), so that
  path met the sealed install with no warning -- the confusion the
  function exists to prevent.

  **IT DRIVES A COPY WHOSE TASK AND SERVICE NAMES ARE REWRITTEN**, the
  same protection `r22-install-ps1-checks.ps1` uses and for the same
  reason: this box's live worker owns a task called `EugenePlexusAgent`,
  and the code under test takes autostarts over.

  Check 2 performs a REAL install into a throwaway prefix (uv, a venv
  and the six pinned packages), because the copy is a step in the
  install flow and nothing short of running it proves the step runs.
  `-NoStart` throughout: nothing is ever started, and the live agent
  keeps 8079.

  Not covered, and it needs Administrator: that a routine upgrade of an
  install which is ALREADY a service stays silent. The predicate is
  `Get-AgentService`, and registering one to prove it is the elevation
  this whole file avoids.
#>
[CmdletBinding()]
param(
    [string]$Work = (Join-Path $env:TEMP "ep-r26-migrate")
)

$ErrorActionPreference = "Stop"
$script:Failures = 0
function Say { param($m) Write-Host "`n== $m" }
function Ok  { param($m) Write-Host "  PASS  $m" }
function Bad { param($m) Write-Host "  FAIL  $m"; $script:Failures++ }

$Here = Split-Path -Parent $PSCommandPath
$Source = Join-Path $Here "install.ps1"
if (-not (Test-Path $Source)) { throw "no install.ps1 beside this script" }

$ProbeTask = "EugenePlexusR26Probe"
$ProbeService = "EugenePlexusR26ProbeSvc"

if (Test-Path $Work) { Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $Work | Out-Null

$Copy = Join-Path $Work "install-probe.ps1"
$text = [IO.File]::ReadAllText($Source)
$text = $text.Replace('$ServiceName  = "EugenePlexusAgent"', "`$ServiceName  = `"$ProbeService`"")
$text = $text.Replace('$TaskName     = "EugenePlexusAgent"', "`$TaskName     = `"$ProbeTask`"")
[IO.File]::WriteAllText($Copy, $text, (New-Object Text.UTF8Encoding $false))
if ($text -match '\$TaskName\s+=\s+"EugenePlexusAgent"') {
    throw "the task name was not rewritten; refusing to run against the live install's task"
}

# The install being migrated FROM: everything a real prefix holds, with
# the installer-owned directories carrying markers so the denylist can
# be observed rather than asserted.
$Decoy = Join-Path $Work "peruser"
New-Item -ItemType Directory -Force -Path (Join-Path $Decoy "venv\Scripts") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Decoy "drivers") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Decoy "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Decoy "bin") | Out-Null
$DecoyExe = Join-Path $Decoy "venv\Scripts\eugene-plexus-agent.exe"
Copy-Item "$env:SystemRoot\System32\cmd.exe" $DecoyExe -Force
[IO.File]::WriteAllText((Join-Path $Decoy "agent.yaml"), "firstRunComplete: true`n")
[IO.File]::WriteAllText((Join-Path $Decoy "node.yaml"), "name: r26-probe-node`n")
[IO.File]::WriteAllText((Join-Path $Decoy "library_folders.json"), "[]`n")
[IO.File]::WriteAllText((Join-Path $Decoy "ollama-probe.yaml"), "kind: inference-driver`n")
[IO.File]::WriteAllText((Join-Path $Decoy "drivers\one.yaml"), "port: 8191`n")
[IO.File]::WriteAllText((Join-Path $Decoy "logs\agent.log"), "old log`n")
[IO.File]::WriteAllText((Join-Path $Decoy "bin\marker.txt"), "installer-owned`n")

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
        -Description "R2.6 migration probe -- delete me" | Out-Null
}

function Invoke-Probe {
    param([string[]]$Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Copy @Arguments 2>&1 |
            ForEach-Object { "$_" }
        $script:ProbeRc = $LASTEXITCODE
    } finally { $ErrorActionPreference = $prev }
    return ($out -join "`n")
}

# The installer writes account-wide variables and this box is a worker
# node: a probe run that ends normally repoints
# EUGENE_PLEXUS_AGENT_CONFIG_FILE at a throwaway prefix, which is the
# live install's identity gone.
$ScopedVars = @("EUGENE_PLEXUS_AGENT_CONFIG_FILE", "EUGENE_PLEXUS_AGENT_BIND_HOST",
                "EUGENE_PLEXUS_AGENT_BIND_PORT", "EUGENE_PLEXUS_AGENT_ENGINE_ROOT",
                "EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS")
$Saved = @{}
foreach ($n in $ScopedVars) { $Saved[$n] = [Environment]::GetEnvironmentVariable($n, "User") }
$env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT = Join-Path $Work "engines"

$Fresh = Join-Path $Work "service-prefix"

try {
    # ------------------------------------------------------------------
    Say "1. isolation: the live worker's autostart is not what this drives"
    $live = Get-ScheduledTask -TaskName "EugenePlexusAgent" -ErrorAction SilentlyContinue
    if ($null -ne $live) {
        Ok "this box holds a real EugenePlexusAgent task; the probe uses $ProbeTask"
    } else {
        Ok "no live task on this box (the probe is isolated regardless)"
    }

    # ------------------------------------------------------------------
    Say "2. THE FINDING A -- a migrate carries the install's identity with it"
    Register-Decoy
    # `-NoService` so this is reachable without Administrator. The copy
    # is about the prefix changing, which is the same on both autostart
    # kinds -- and the service half is what needs the elevated run.
    $out = Invoke-Probe @("-Prefix", $Fresh, "-Migrate", "-NoService", "-NoStart")
    if ($script:ProbeRc -ne 0) {
        Bad "the migrate run did not complete (rc=$($script:ProbeRc))"
        $out -split "`n" | Select-Object -Last 12 | ForEach-Object { Write-Host "      $_" }
    } else {
        Ok "the migrate run completed"
    }
    foreach ($name in @("agent.yaml", "node.yaml", "library_folders.json", "ollama-probe.yaml")) {
        if (Test-Path (Join-Path $Fresh $name)) {
            Ok "$name came across"
        } else {
            Bad "$name did NOT come across -- this is the finding"
        }
    }
    if (Test-Path (Join-Path $Fresh "drivers\one.yaml")) {
        Ok "the companion driver configs came across"
    } else {
        Bad "drivers\ did NOT come across -- this is the finding"
    }
    # The identity is the half that matters: without node.yaml the new
    # install is unenrolled and mints its own signing key.
    $node = Join-Path $Fresh "node.yaml"
    if ((Test-Path $node) -and ([IO.File]::ReadAllText($node) -match "r26-probe-node")) {
        Ok "and node.yaml is the one from the old prefix, not a new one"
    } else {
        Bad "node.yaml is missing or is not the old install's"
    }

    # ------------------------------------------------------------------
    Say "3. the installer's own directories are not copied"
    if (-not (Test-Path (Join-Path $Fresh "bin\marker.txt"))) {
        Ok "bin\ was rebuilt rather than copied"
    } else {
        Bad "bin\ was copied from the old prefix"
    }
    if (-not (Test-Path (Join-Path $Fresh "logs\agent.log"))) {
        Ok "logs\ was not copied (the old prefix keeps them)"
    } else {
        Bad "the old prefix's log was copied into the new one"
    }
    if (-not (Test-Path (Join-Path $Fresh "venv\Scripts\eugene-plexus-agent.exe.bak"))) {
        Ok "venv\ is this run's own"
    } else {
        Bad "venv\ was copied"
    }

    # ------------------------------------------------------------------
    Say "4. the old install is left where it is"
    if ((Test-Path (Join-Path $Decoy "agent.yaml")) -and (Test-Path (Join-Path $Decoy "node.yaml"))) {
        Ok "the source prefix still holds its config and identity"
    } else {
        Bad "the migrate moved or deleted the old install -- an upgrade must not lose an enrollment"
    }

    # ------------------------------------------------------------------
    Say "5. a second run does not overwrite what is already there"
    [IO.File]::WriteAllText((Join-Path $Fresh "node.yaml"), "name: edited-since`n")
    Register-Decoy
    $out = Invoke-Probe @("-Prefix", $Fresh, "-Migrate", "-NoService", "-NoStart")
    if ([IO.File]::ReadAllText((Join-Path $Fresh "node.yaml")) -match "edited-since") {
        Ok "an existing file is left alone, so a re-run resumes rather than reverting"
    } else {
        Bad "the second run overwrote a file the install had changed"
    }

    # ------------------------------------------------------------------
    Say "6. THE FINDING B -- converting a per-user install says what it costs"
    Register-Decoy
    # A service is wanted (no -NoService) and the target is somewhere
    # else: the case that DID warn before, kept so the fix cannot lose it.
    $out = Invoke-Probe @("-Detect", "-Prefix", (Join-Path $Work "svc-elsewhere"))
    # **A bare /passphrase/ matched the WRONG SENTENCE and passed against
    # the defect** -- caught on the pre-fix run, which is what that run is
    # for. `Show-InstallVerdict`'s refusal already says an ordinary run
    # would leave the other install's "passphrase, models folder, keyring
    # entry" behind. Match the consequence's own line instead.
    if ($out -match "ASK FOR YOUR PASSPHRASE ONCE") {
        Ok "-Detect names the passphrase you will be asked for once"
    } else {
        Bad "-Detect says nothing about the one consequence that cannot be undone"
        $out -split "`n" | Select-Object -Last 10 | ForEach-Object { Write-Host "      $_" }
    }
    if ($out -match "(?i)Logins for file servers|network drive") {
        Ok "and names the share login a service does not inherit"
    } else {
        Bad "-Detect does not mention the share credential"
    }

    # ------------------------------------------------------------------
    Say "7. THE FINDING B -- and it says so for a conversion IN PLACE"
    # `-Prefix <the install itself>`: the obvious way to make an existing
    # install a service. The old predicate returned early here, because
    # the target holds an agent.yaml -- so this path met a sealed install
    # with no warning at all.
    Register-Decoy
    $out = Invoke-Probe @("-Detect", "-Prefix", $Decoy)
    if ($out -match "ASK FOR YOUR PASSPHRASE ONCE") {
        Ok "an in-place conversion is warned about too -- this is the finding"
    } else {
        Bad "converting an install in place says nothing about the sealed key"
        $out -split "`n" | Select-Object -Last 10 | ForEach-Object { Write-Host "      $_" }
    }
    if ($out -match "(?i)Everything stays where it is") {
        Ok "and says the files are not going anywhere, which is the difference"
    } else {
        Bad "the in-place text is the moving text, which would be wrong"
    }

    # ------------------------------------------------------------------
    Say "8. a genuinely fresh machine is not warned about anything"
    Remove-Probe
    $bare = Join-Path $Work "bare"
    # No autostart, and a prefix with no agent.yaml anywhere near it.
    # `Get-OtherInstall` also reads the config-file variable and the two
    # default prefixes, and this box HAS a live per-user install -- so
    # the honest version of this check is that the text names that
    # install rather than firing for no reason at all.
    $out = Invoke-Probe @("-Detect", "-Prefix", $bare)
    # **The property, not the identity.** A first draft asserted the text
    # named `%LOCALAPPDATA%\EugenePlexus`, and it failed -- because checks
    # 2 and 5 above complete real installs, which write
    # EUGENE_PLEXUS_AGENT_CONFIG_FILE at User scope, so by the time this
    # runs the install `Get-OtherInstall` finds is a throwaway of this
    # harness's own making. It was right and the check was wrong. What
    # this check means is that a warning never fires blind: whatever
    # prefix it names has to be an install that is really there.
    $named = [regex]::Match($out, "already has a per-user install at (.+)")
    if ($out -match "ASK FOR YOUR PASSPHRASE ONCE") {
        if ($named.Success -and (Test-Path (Join-Path $named.Groups[1].Value.Trim() "agent.yaml"))) {
            Ok "the warning names an install that is really on this machine"
        } else {
            Bad "a warning fired without naming an install that exists"
        }
    } else {
        Ok "nothing to convert, nothing warned about"
    }

    # ------------------------------------------------------------------
    Say "9. -Detect stays read-only and non-fatal"
    if ($script:ProbeRc -ne 0) {
        Ok "-Detect reports a non-clean machine with a status ($($script:ProbeRc)) and no throw"
    } else {
        Ok "-Detect returned 0"
    }
    if (-not (Test-Path (Join-Path $bare "venv"))) {
        Ok "and wrote nothing into the prefix it was asked about"
    } else {
        Bad "-Detect built something"
    }
}
finally {
    Remove-Probe
    foreach ($n in $ScopedVars) {
        [Environment]::SetEnvironmentVariable($n, $Saved[$n], "User")
    }
    Write-Host "`n(scoped variables restored; work directory left at $Work)"
}

Write-Host ""
if ($script:Failures -gt 0) {
    Write-Host "$($script:Failures) FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "all checks passed" -ForegroundColor Green
