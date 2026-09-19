<#
.SYNOPSIS
  R2.6's owed elevated checks 1, 2, 3, 4 and 6, run in one go, with the
  agent.log lines that decide each one printed rather than searched for.

.DESCRIPTION
  `docs/acceptance/windows-service-run.md` §0 lists six checks the R2.6
  build could not take, because the session was unelevated and nothing
  non-interactive can reboot a machine and then not sign in. Five of the
  six are scriptable from an elevated session. This is that script.

  **Check 5 is not here, and cannot be**: it is the reboot. What IS here
  is `-AfterReboot`, which reads the evidence out of the log afterwards,
  so the manual part is the reboot itself and a phone, not the forensics.

  **Check 2 is the one measurement nobody has.** `ensure_console()` was
  measured in session 1 (three arms, §3 of the record). A service runs in
  SESSION 0 and `AllocConsole()` there has never been observed. The tell
  is a log line, and it is printed here in full either way, because
  "AllocConsole is refused in session 0" is a real and survivable answer
  that the product already has words for -- it is the finding, not a
  failure of this script.

  **Check 6 runs UNELEVATED or it proves nothing.** An elevated process
  can always stop a service, so a check that stops it from here would
  pass whether or not `sc sdset` took. It goes through a scheduled task
  registered with `-RunLevel Limited`, which is the tray's own context,
  and the child asserts `IsUserAnAdmin() == 0` before it does anything --
  otherwise this would be the project's signature defect (a check green
  for the wrong reason) in a script written to close one.

  It calls the product's own `tray.stop_service` / `tray.start_service`
  rather than shelling out to `sc` itself, for the same reason: what is
  under test is the code the icon runs.

.PARAMETER Migrate
  Run `install.ps1 -Migrate` first. Without it, a machine with no service
  registered fails preflight and prints the command.

.PARAMETER SkipRuntime
  Skip check 2's engine half. The default restarts a llama.cpp runtime,
  which pays the model load again (about 21 s on this box with the
  node-local copy, minutes over SMB without it).

.PARAMETER AfterReboot
  Check 5's forensics only. Run it after the reboot, once signed back in.
  Reads nothing but the log, the OS boot time and the logon time.

.EXAMPLE
  # elevated
  .\scripts\r26-service-checks.ps1 -Migrate

.EXAMPLE
  # elevated, after the reboot, signed back in
  .\scripts\r26-service-checks.ps1 -AfterReboot
#>
[CmdletBinding()]
param(
    [string]$Prefix,
    [int]$Port = 8079,
    [switch]$Migrate,
    [switch]$SkipRuntime,
    [switch]$AfterReboot,
    [string]$SharePath,
    [string]$OffHostAddress = "192.168.16.252",
    [System.Security.SecureString]$Passphrase,
    # A test seam, and the only one. Dot-source with `-LoadOnly` to get
    # the functions without the elevation gate or any of the actions, so
    # `Get-OffHostRequests` can be exercised against a real agent.log on
    # an ordinary session. It is the half of check 5 that can be wrong
    # silently, and testing a copy of it would be testing a copy.
    [switch]$LoadOnly
)

$ErrorActionPreference = "Stop"

$ServiceName  = "EugenePlexusAgent"
$TaskName     = "EugenePlexusAgent"
$TrayTaskName = "EugenePlexusTray"
$Check6Task   = "EugenePlexusR26Check6"

$script:Failures = 0
$script:Skips    = 0
$script:Checks   = @()

function Say  { param($m) Write-Host ""; Write-Host "== $m" -ForegroundColor Cyan }
function Note { param($m) Write-Host "       $m" }
function Ok   { param($m) Write-Host "  PASS $m" -ForegroundColor Green; $script:Checks += "PASS $m" }
function Bad  { param($m) Write-Host "  FAIL $m" -ForegroundColor Red;   $script:Checks += "FAIL $m"; $script:Failures++ }
function Skip { param($m) Write-Host "  SKIP $m" -ForegroundColor Yellow; $script:Checks += "SKIP $m"; $script:Skips++ }
function Warn { param($m) Write-Host "  warn $m" -ForegroundColor Yellow }
function Die  { param($m) Write-Host ""; Write-Host "STOP: $m" -ForegroundColor Red; exit 2 }

# --------------------------------------------------------------------- #
# the log, read while something else is writing it
# --------------------------------------------------------------------- #
# `Get-Content` on a file a service holds open is a coin toss. A
# FileStream opened with FileShare.ReadWrite is not. The offset is kept
# so every dump below shows only what the action under test produced --
# this log carries three engine health probes a second and a dump of the
# whole thing would be exactly the searching this script exists to avoid.

$script:LogPath = $null
$script:Mark    = 0

function Get-LogLength {
    if (-not $script:LogPath) { return 0 }
    if (-not (Test-Path -LiteralPath $script:LogPath)) { return 0 }
    return (Get-Item -LiteralPath $script:LogPath).Length
}

function Set-LogMark {
    $script:Mark = Get-LogLength
}

function Read-LogFrom {
    param([long]$Offset)
    if (-not $script:LogPath) { return @() }
    if (-not (Test-Path -LiteralPath $script:LogPath)) { return @() }
    $fs = $null
    $reader = $null
    try {
        $fs = [IO.File]::Open($script:LogPath, [IO.FileMode]::Open,
                              [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        # Rotated under us (10 MB, about seven hours on this box). Start
        # over rather than seek past the end and report nothing.
        if ($Offset -gt $fs.Length) { $Offset = 0 }
        [void]$fs.Seek($Offset, [IO.SeekOrigin]::Begin)
        $reader = New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8)
        $text = $reader.ReadToEnd()
        return @($text -split "`r?`n")
    } catch {
        Warn "could not read $($script:LogPath): $($_.Exception.Message)"
        return @()
    } finally {
        if ($reader) { $reader.Dispose() } elseif ($fs) { $fs.Dispose() }
    }
}

function Get-NewLog {
    return Read-LogFrom -Offset $script:Mark
}

function Find-Lines {
    param([string[]]$Lines, [string]$Pattern)
    return @($Lines | Where-Object { $_ -match $Pattern })
}

function Dump {
    param([string]$Title, [string[]]$Lines, [int]$Max = 25)
    Write-Host "       --- $Title ---" -ForegroundColor DarkGray
    if (-not $Lines -or $Lines.Count -eq 0) {
        Write-Host "       (nothing matched)" -ForegroundColor DarkGray
        return
    }
    $shown = $Lines
    if ($Lines.Count -gt $Max) { $shown = $Lines[0..($Max - 1)] }
    foreach ($l in $shown) { Write-Host "       $l" -ForegroundColor DarkGray }
    if ($Lines.Count -gt $Max) {
        Write-Host "       ... and $($Lines.Count - $Max) more" -ForegroundColor DarkGray
    }
}

# --------------------------------------------------------------------- #
# HTTP, without dragging a 104 ms certifi parse into a PowerShell script
# --------------------------------------------------------------------- #

# R1.1's lesson, in a PowerShell script: nothing belongs between this and
# loopback. .NET picks up the user's IE/WinHTTP proxy by default, and the
# Windows logon session this runs in is exactly the one that inherits a
# corporate `HTTP(S)_PROXY` -- review §6 #25, one layer over.
[System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy

function Invoke-Agent {
    param(
        [string]$Path,
        [string]$Method = "GET",
        [string]$Token,
        $Body
    )
    $headers = @{}
    if ($Token) { $headers["Authorization"] = "Bearer $Token" }
    $req = @{
        Uri        = "http://127.0.0.1:$Port$Path"
        Method     = $Method
        Headers    = $headers
        TimeoutSec = 30
    }
    if ($null -ne $Body) {
        $req["Body"] = (ConvertTo-Json $Body -Compress)
        $req["ContentType"] = "application/json"
    }
    return Invoke-RestMethod @req
}

function Invoke-AgentSafe {
    # `(ok, value, why)` without an exception escaping into the middle of
    # a check. PowerShell 5.1's Invoke-RestMethod throws on any non-2xx,
    # and the body of a Problem response is the useful part.
    param([string]$Path, [string]$Method = "GET", [string]$Token, $Body)
    try {
        $v = Invoke-Agent -Path $Path -Method $Method -Token $Token -Body $Body
        return @{ ok = $true; value = $v; why = "" }
    } catch {
        $why = $_.Exception.Message
        $resp = $_.Exception.Response
        if ($resp) {
            try {
                $sr = New-Object IO.StreamReader($resp.GetResponseStream())
                $text = $sr.ReadToEnd()
                $sr.Dispose()
                if ($text) { $why = "$([int]$resp.StatusCode) $text" }
            } catch { }
        }
        return @{ ok = $false; value = $null; why = $why }
    }
}

function Wait-Healthz {
    param([int]$TimeoutSec = 180)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $r = Invoke-AgentSafe -Path "/healthz"
        if ($r.ok) { return $r.value }
        Start-Sleep -Milliseconds 700
    }
    return $null
}

function Wait-NoHealthz {
    param([int]$TimeoutSec = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $r = Invoke-AgentSafe -Path "/healthz"
        if (-not $r.ok) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Wait-ServiceStatus {
    param([string]$Status, [int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq $Status) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function ConvertFrom-SecureStringPlain {
    param([System.Security.SecureString]$S)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($S)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

# ===================================================================== #
# -AfterReboot: check 5's evidence, which is a log and two clocks
# ===================================================================== #

function Get-OffHostRequests {
    <#
      Every request in this log that came from another machine, each with
      the time it happened.

      **Uvicorn's access lines carry no timestamp of their own.** The file
      is a tee of stdout (`console_logging.install_console_capture`) with a
      raw passthrough formatter, so the agent's own records arrive stamped
      by `basicConfig` and uvicorn's arrive exactly as uvicorn prints them:

          2026-09-19 16:50:21,616 INFO httpx: HTTP Request: GET ...
          INFO:     192.168.16.252:44612 - "GET /v1/node HTTP/1.1" 200 OK

      So the clock for an access line is the nearest agent record above it.
      That is sound here for one measured reason: the engine health poller
      writes two `httpx` lines every 1.5-2 s for every ready runtime, so
      the carry is never stale by more than about two seconds, and the
      window this is asked about is minutes wide.

      A child component's access lines arrive prefixed (`[driver: name]
      INFO: ...`) and count: they are also this install answering an
      off-host caller. Loopback does not.
    #>
    param([string[]]$Lines)

    $carried = $null
    $requests = New-Object 'System.Collections.Generic.List[object]'
    $firstLogin = $null
    $invariant = [Globalization.CultureInfo]::InvariantCulture
    foreach ($line in $Lines) {
        if ($line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}') {
            $carried = [datetime]::ParseExact($matches[1], "yyyy-MM-dd HH:mm:ss", $invariant)
            if (-not $firstLogin -and $line -match 'operator login from') {
                $firstLogin = $carried
            }
        }
        if ($line -match 'INFO:\s+(\d{1,3}(?:\.\d{1,3}){3}):\d+ - "([A-Z]+) ([^ "]+)') {
            $addr = $matches[1]
            if ($addr -like "127.*") { continue }
            $requests.Add([pscustomobject]@{
                At      = $carried
                Address = $addr
                Request = "$($matches[2]) $($matches[3])"
                Line    = $line
            })
        }
    }
    return [pscustomobject]@{ Requests = $requests; FirstLogin = $firstLogin }
}

function Test-ControlRootProbing {
    <#
      **Check 5's evidence has a source, and the source can be switched
      off without anything saying so.**

      The plan is: the control root polls this node every ~15 s, so the
      log holds off-host requests from it timestamped between boot and
      login. That is true only while the root is unlocked. A control root
      in a container comes back from a restart **sealed** -- it has no
      keyring -- and a sealed root stops polling while `/healthz` keeps
      answering `{"status":"ok", "initialized":true, "nodes":2}`, every
      word of it true. This install has shipped that exact confusion once
      already (2026-09-12).

      Measured on this box 2026-09-19 while writing this script: the root
      at 192.168.16.252:8283 was sealed, `/v1/nodes` answered 503, and
      the worker's log had no off-host request since 14:29.

      So ask before the reboot rather than conclude afterwards. Without
      this, `-AfterReboot` reports "nothing reached this node" and the
      reader blames the service.
    #>
    param([string]$Prefix)

    $node = Join-Path $Prefix "node.yaml"
    if (-not (Test-Path -LiteralPath $node)) { return }
    $m = [regex]::Match([IO.File]::ReadAllText($node), '(?m)^controlUrl:\s*(\S+)')
    if (-not $m.Success) { return }
    $root = $m.Groups[1].Value.TrimEnd('/')

    try {
        $st = Invoke-RestMethod -Uri "$root/v1/auth/status" -TimeoutSec 8
    } catch {
        Warn "the control root at $root did not answer ($($_.Exception.Message))."
        Note "  It is what polls this node every ~15 s, and those polls are check 5's"
        Note "  evidence. With it down, the phone is the ONLY off-host caller."
        return
    }
    if ($st.unlocked) {
        Ok "the control root at $root is unlocked, so it is polling this node"
        return
    }
    Bad "THE CONTROL ROOT AT $root IS SEALED (unlocked=false, keyringAvailable=$($st.keyringAvailable))"
    Note "  Its /healthz still says ok and initialized -- that is the 2026-09-12 symptom."
    Note "  While it is sealed it polls nothing, so check 5 would find no off-host"
    Note "  request and read as a failure of the service, which it would not be."
    Note ""
    Note "  Unlock it before the reboot, either way:"
    Note "    - sign in to the UI (since 2026-09-13 the login posts to the root too), or"
    Note "    - Invoke-RestMethod -Method Post -Uri $root/v1/auth/login -ContentType application/json -Body (ConvertTo-Json @{passphrase='...'})"
    Note ""
    Note "  The durable fix for a container is securityMode: passphrase_file"
    Note "  (control 0cec9d8) -- a container has no keyring and will do this again."
}

function Invoke-AfterReboot {
    param([string]$Prefix)

    Say "CHECK 5 (after the fact) -- did the service serve before anyone signed in?"

    $script:LogPath = Join-Path $Prefix "logs\agent.log"
    if (-not (Test-Path -LiteralPath $script:LogPath)) {
        Bad "no log at $($script:LogPath) -- is the service install at this prefix?"
        return
    }

    $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    Note "OS booted:            $boot"

    # The interactive logon for this user, after the boot. Type 2 is a
    # console logon, 11 cached-credentials -- a Microsoft account on a
    # workgroup box reports 11 more often than 2, so both count.
    $logon = $null
    try {
        $sessions = Get-CimInstance Win32_LogonSession -Filter "LogonType = 2 OR LogonType = 11" |
                    Where-Object { $_.StartTime -ge $boot } |
                    Sort-Object StartTime
        if ($sessions) { $logon = @($sessions)[0].StartTime }
    } catch { }
    if ($logon) {
        Note "first interactive logon: $logon"
    } else {
        Warn "could not read an interactive logon time; falling back to the agent process start"
    }

    # Corroboration that does not depend on parsing anything: the agent
    # process itself. A service process older than the logon, still
    # running, is the whole claim.
    $svc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
    $agentStart = $null
    if ($svc -and $svc.ProcessId -gt 0) {
        try { $agentStart = (Get-Process -Id $svc.ProcessId -ErrorAction Stop).StartTime } catch { }
    }
    if ($agentStart) { Note "agent process started:   $agentStart (pid $($svc.ProcessId))" }

    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Bad "a logon task named $TaskName still exists, so the service is not the only candidate for what served"
    } else {
        Ok "no logon task registered -- the service is the only thing that could have answered"
    }

    if ($agentStart -and $logon -and $agentStart -lt $logon) {
        Ok "the agent process predates the interactive logon by $([int]($logon - $agentStart).TotalSeconds)s"
    } elseif ($agentStart -and $logon) {
        Bad "the agent process started AFTER the logon -- it was not running while nobody was signed in"
    }

    # Walk the whole log forward carrying the last timestamp seen. Uvicorn
    # access lines have no timestamp of their own (the tee is a raw
    # passthrough and uvicorn's default formatter stamps nothing), so the
    # nearest preceding agent record is the clock. Engine health probes
    # land every 1.5-2 s, so the resolution is about two seconds.
    $walk = Get-OffHostRequests (Read-LogFrom -Offset 0)
    $offHost = $walk.Requests
    $firstEugeneLogin = $walk.FirstLogin

    if ($offHost.Count -eq 0) {
        Bad "no off-host request appears in the log at all -- nothing reached this node from another machine"
        Note "  Before reading that as a failure of the service, ask whether anything"
        Note "  was calling. A sealed control root polls nothing and says ok:"
        Test-ControlRootProbing -Prefix $Prefix
        return
    }

    $addresses = ($offHost | Select-Object -ExpandProperty Address -Unique) -join ", "
    Note "off-host callers seen: $addresses"

    $cutoff = $logon
    if (-not $cutoff) { $cutoff = $firstEugeneLogin }
    if (-not $cutoff) {
        Bad "no logon time and no 'operator login from' line -- cannot bound the not-signed-in window"
        Dump "every off-host request (first 25)" ($offHost | ForEach-Object { "$($_.At)  $($_.Line)" })
        return
    }

    $before = @($offHost | Where-Object { $_.At -and $_.At -ge $boot -and $_.At -lt $cutoff })
    if ($before.Count -gt 0) {
        $addrsBefore = ($before | Select-Object -ExpandProperty Address -Unique) -join ", "
        Ok "$($before.Count) off-host request(s) served between boot and login, from $addrsBefore"
        Dump "the not-signed-in window (earliest first)" ($before | ForEach-Object { "$($_.At)  $($_.Line)" })
    } else {
        Bad "no off-host request lands between $boot and $cutoff"
        Dump "off-host requests found, with their carried timestamps" ($offHost | ForEach-Object { "$($_.At)  $($_.Line)" })
    }

    $fromRoot = @($before | Where-Object { $_.Address -eq $OffHostAddress })
    if ($fromRoot.Count -gt 0) {
        Ok "$($fromRoot.Count) of them are the control root at $OffHostAddress"
    } else {
        Warn "none of them came from $OffHostAddress -- the control root's 15 s probe is the expected source"
    }

    $phones = @($before | Where-Object { $_.Address -ne $OffHostAddress })
    if ($phones.Count -gt 0) {
        $p = ($phones | Select-Object -ExpandProperty Address -Unique) -join ", "
        Ok "a caller other than the control root also got in: $p (the phone, if that is what you used)"
    } else {
        Note "no caller other than the control root in that window -- load http://<this host>:$Port/healthz"
        Note "from a phone during the next one if you want that half on the record."
    }
}

# ===================================================================== #
# main
# ===================================================================== #

if ($LoadOnly) { return }

$IsElevated = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $IsElevated) {
    Die @"
this needs an elevated PowerShell. Every one of these checks is about a
  thing only Administrator can do -- register a service, read SYSTEM's
  credential store, set a service descriptor. Open PowerShell as
  Administrator and run it again.
"@
}

if (-not $Prefix) { $Prefix = Join-Path $env:ProgramData "EugenePlexus" }
$Venv    = Join-Path $Prefix "venv"
$PyBin   = Join-Path $Venv "Scripts\python.exe"
$Config  = Join-Path $Prefix "agent.yaml"

Write-Host "R2.6 -- the six owed checks, minus the reboot" -ForegroundColor White
Note "prefix: $Prefix"
Note "port:   $Port"

if ($AfterReboot) {
    Invoke-AfterReboot -Prefix $Prefix
    Write-Host ""
    Write-Host "----------------------------------------------------------------"
    Write-Host "$($script:Failures) FAIL, $($script:Skips) SKIP"
    exit $script:Failures
}

# --- migration, if asked ---------------------------------------------- #

if ($Migrate) {
    Say "running install.ps1 -Migrate first"
    $installer = Join-Path (Split-Path -Parent $PSCommandPath) "install.ps1"
    if (-not (Test-Path $installer)) { Die "no install.ps1 beside this script" }
    # **Not `$LASTEXITCODE`.** R2.2's own Windows suite already records
    # that `$global:LASTEXITCODE` set inside a script does not become a
    # process exit code, and `&` on a .ps1 leaves whatever a previous
    # native command left. `install.ps1` fails by throwing (`Die`), so
    # catching is the reliable half -- and the state on disk is the other.
    try {
        & $installer -Migrate
    } catch {
        Die "install.ps1 -Migrate failed: $($_.Exception.Message)"
    }
    if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
        Die "install.ps1 -Migrate returned without registering the $ServiceName service"
    }
}

# --- preflight --------------------------------------------------------- #

Say "PREFLIGHT"

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Die @"
no $ServiceName service is registered, so there is nothing to check.
  Convert this install first:
      .\scripts\install.ps1 -Migrate
  or re-run this script with -Migrate, which does the same thing and then
  runs the checks.
"@
}
Note "service: $($svc.Status), start type $($svc.StartType)"

if (-not (Test-Path -LiteralPath $Config)) {
    Die @"
$Config does not exist. A service started against an empty prefix runs
  the first-run wizard and raises a SECOND install -- which is the defect
  8cac628 fixed. Do not start it. Check where -Migrate put the state.
"@
}
Ok "agent.yaml is at $Config"

$node = Join-Path $Prefix "node.yaml"
if (Test-Path -LiteralPath $node) {
    $nodeName = "(unnamed)"
    $m = [regex]::Match([IO.File]::ReadAllText($node), '(?m)^name:\s*(.+)$')
    if ($m.Success) { $nodeName = $m.Groups[1].Value.Trim() }
    Ok "node.yaml carried over -- this install is still $nodeName"
} else {
    Bad "no node.yaml at $($node) -- the enrollment did not come across, and this node will read as unenrolled"
}

$cfgText = [IO.File]::ReadAllText($Config)
if ($cfgText -match '(?m)^securityMode:\s*(\S+)') {
    $securityMode = $matches[1]
    Note "securityMode: $securityMode"
    if ($securityMode -ne "os_keyring") {
        Warn "check 3 is about the OS keyring and this install is on '$securityMode'; it will report SKIP"
    }
} else {
    $securityMode = "(unset)"
}

# **A path inside the migrated state that still names the old prefix.**
# `Copy-InstallState` copies files; it does not rewrite what is in them,
# and a companion driver's `spawn.configFile` is an absolute path. The
# old directory is left in place so this still works -- until somebody
# follows the installer's own advice and deletes it.
$staleSpawn = @([regex]::Matches($cfgText, '(?m)^\s*configFile:\s*(.+)$') |
    ForEach-Object { $_.Groups[1].Value.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase) })
if ($staleSpawn.Count -gt 0) {
    Warn "$($staleSpawn.Count) component spawn path(s) in agent.yaml still name the OLD prefix:"
    foreach ($p in $staleSpawn) { Note "  $p" }
    Note "  They resolve today because -Migrate leaves the source directory in place,"
    Note "  and they break the day it is deleted. The copies already exist under"
    Note "  $Prefix\drivers. Not one of the six checks; recorded here so it is not a surprise."
}

$autostartTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($autostartTask) {
    Bad "a logon task named $TaskName still exists; it and the service will fight over port $Port"
} else {
    Ok "no leftover $TaskName logon task"
}

$machineCfg = [Environment]::GetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", "Machine")
if ($machineCfg -and ($machineCfg -eq $Config)) {
    Ok "EUGENE_PLEXUS_AGENT_CONFIG_FILE (Machine) points at $machineCfg"
} else {
    Bad "EUGENE_PLEXUS_AGENT_CONFIG_FILE (Machine) is '$machineCfg', not '$Config' -- a service reads Machine scope only, so it would find no agent.yaml"
}

$script:LogPath = Join-Path $Prefix "logs\agent.log"
Note "log: $($script:LogPath)"

Test-ControlRootProbing -Prefix $Prefix

# ===================================================================== #
# CHECK 1 -- it registers, answers, and stops
# ===================================================================== #

Say "CHECK 1 -- the service registers, answers /healthz, and stops"

Set-LogMark
if ($svc.Status -ne "Running") {
    Note "starting it"
    try { Start-Service -Name $ServiceName } catch { Bad "Start-Service threw: $($_.Exception.Message)" }
}
if (Wait-ServiceStatus -Status "Running" -TimeoutSec 60) {
    Ok "the SCM reports it Running"
} else {
    Bad "it never reached Running"
}

$health = Wait-Healthz -TimeoutSec 180
if ($health) {
    Ok "/healthz answers: status=$($health.status)"
    if ($health.status -ne "ok") {
        Warn "not ok -- details: $(ConvertTo-Json $health.details -Compress)"
    }
} else {
    Bad "/healthz never answered within 180s"
}

Note "stopping it"
try { Stop-Service -Name $ServiceName -ErrorAction Stop } catch { Warn "Stop-Service: $($_.Exception.Message)" }
if (Wait-ServiceStatus -Status "Stopped" -TimeoutSec 120) {
    Ok "it stops"
} else {
    Bad "it did not reach Stopped within 120s"
}
if (Wait-NoHealthz -TimeoutSec 30) {
    Ok "/healthz stops answering once it is stopped"
} else {
    Bad "something is still answering on port $Port with the service stopped -- another agent?"
}

Dump "check 1, from the log" (Find-Lines (Get-NewLog) 'child shutdown|Uvicorn|Started server|Stopping|shutdown|allocated a console')

# The rest of the run needs it up.
Note "starting it again for the remaining checks"
Set-LogMark
$bootMark = $script:Mark
Start-Service -Name $ServiceName
$health = Wait-Healthz -TimeoutSec 180
if (-not $health) { Die "the service did not come back after check 1; nothing below can run" }

# ===================================================================== #
# sign in once -- checks 2 and 4 need a token, check 3 needs the login
# ===================================================================== #

Say "SIGN IN (once) -- this is also step one of check 3"

if (-not $Passphrase) {
    $Passphrase = Read-Host -AsSecureString "Eugene passphrase"
}
$plain = ConvertFrom-SecureStringPlain $Passphrase
Set-LogMark
$login = Invoke-AgentSafe -Path "/v1/auth/login" -Method "POST" -Body @{ passphrase = $plain }
$plain = $null
if (-not $login.ok) {
    Dump "the login attempt" (Find-Lines (Get-NewLog) 'login|Rate limited')
    Die "login failed: $($login.why)  (three wrong tries rate-limits this address for a while)"
}
$Token = $login.value.sessionToken
Ok "signed in; session expires $($login.value.expiresAt)"
$loginLog = Get-NewLog

# ===================================================================== #
# CHECK 2 -- AllocConsole() in SESSION 0
# ===================================================================== #

Say "CHECK 2 -- AllocConsole in session 0, the measurement nobody has"

$bootLines = Read-LogFrom -Offset $bootMark
$wantConsole = Find-Lines $bootLines 'child shutdown: children are stopped with CTRL_BREAK_EVENT'
$noConsole   = Find-Lines $bootLines 'child shutdown: this agent has no console'
$allocated   = Find-Lines $bootLines 'allocated a console'

if ($wantConsole.Count -gt 0) {
    Ok "2a: the service announced the GRACEFUL stop at boot -- AllocConsole works in session 0"
} elseif ($noConsole.Count -gt 0) {
    Bad "2a: the service announced 'no console' -- AllocConsole is refused in session 0 and children are hard-killed"
    Note "  This is a real answer, not a script fault. It means install-paths §7's"
    Note "  cost column is right after all for a SERVICE, and the badge stays."
} else {
    Bad "2a: no 'child shutdown:' line at all in this boot -- the agent may not have got that far"
}
# **Do not read anything into the absence of `allocated a console`.**
# `SvcDoRun` calls `ensure_console()` BEFORE `build_server`, and
# `build_server` is what installs the stdout tee and calls `basicConfig`
# -- so that INFO record is emitted with no handler attached and is
# dropped. It cannot reach agent.log in a service, and a check that
# treated its absence as a failure would be failing the log's ordering.
# Reported if present (the tee is idempotent and a re-entrant path could
# produce it); never counted.
if ($allocated.Count -gt 0) {
    Note "2a+: an 'allocated a console' line did reach the log: $($allocated[0])"
} else {
    Note "2a+: no 'allocated a console' line, and there cannot be one -- ensure_console()"
    Note "     runs before build_server installs the log tee. The line above is the tell."
}
Dump "2a, the boot announcement" ($wantConsole + $noConsole + $allocated)

# 2b: the event, actually sent, to a real child, in session 0. The boot
# line says a console is attached; only a stop says GenerateConsoleCtrlEvent
# succeeds against a child that inherited it.
$components = Invoke-AgentSafe -Path "/v1/components" -Token $Token
$compName = $null
if ($components.ok -and $components.value.components) {
    $spawned = @($components.value.components | Where-Object { $_.spawn })
    if ($spawned.Count -gt 0) { $compName = $spawned[0].name }
}
if ($compName) {
    Note "restarting component '$compName'"
    Set-LogMark
    $r = Invoke-AgentSafe -Path "/v1/components/$compName/restart" -Method "POST" -Token $Token
    if (-not $r.ok) {
        Bad "2b: the restart was refused: $($r.why)"
    } else {
        Start-Sleep -Seconds 6
        $new = Get-NewLog
        $sent    = Find-Lines $new 'restart requested for .*sent CTRL_BREAK_EVENT to pid'
        $killed  = Find-Lines $new 'restart requested for .*sent TerminateProcess to pid'
        $cannot  = Find-Lines $new 'cannot send a console event'
        $ignored = Find-Lines $new 'ignored the stop request'
        if ($sent.Count -gt 0 -and $cannot.Count -eq 0) {
            Ok "2b: a real child was sent CTRL_BREAK_EVENT from session 0"
        } elseif ($killed.Count -gt 0 -or $cannot.Count -gt 0) {
            Bad "2b: the child got TerminateProcess -- the console event failed in session 0"
        } else {
            Bad "2b: neither tell appeared in the log within 6s of the restart"
        }
        if ($ignored.Count -gt 0) {
            Warn "a child ignored the stop request and was killed after the deadline"
        }
        Dump "2b, the component stop" ($sent + $killed + $cannot + $ignored)
    }
} else {
    Skip "2b: this install supervises no component with a spawn lifecycle"
}

# 2c: the same thing against an engine, which is what the record names --
# a llama.cpp holding 23 GB of VRAM is the case the graceful stop is for.
if ($SkipRuntime) {
    Skip "2c: -SkipRuntime (the engine half; it pays the model load again)"
} else {
    $runtimes = Invoke-AgentSafe -Path "/v1/runtimes" -Token $Token
    $rtName = $null
    if ($runtimes.ok -and $runtimes.value.runtimes) {
        $live = @($runtimes.value.runtimes | Where-Object { $_.status -eq "ready" -or $_.status -eq "loading" })
        if ($live.Count -gt 0) { $rtName = $live[0].name }
    }
    if ($rtName) {
        Note "restarting runtime '$rtName' -- the model load is paid again"
        Set-LogMark
        $r = Invoke-AgentSafe -Path "/v1/runtimes/$rtName/restart" -Method "POST" -Token $Token
        if (-not $r.ok) {
            Bad "2c: the runtime restart was refused: $($r.why)"
        } else {
            Start-Sleep -Seconds 8
            $new = Get-NewLog
            $sent   = Find-Lines $new 'restart requested for .*sent CTRL_BREAK_EVENT to pid'
            $killed = Find-Lines $new 'restart requested for .*sent TerminateProcess to pid'
            $cannot = Find-Lines $new 'cannot send a console event'
            if ($sent.Count -gt 0 -and $cannot.Count -eq 0) {
                Ok "2c: the ENGINE was asked to stop with CTRL_BREAK_EVENT from session 0"
            } elseif ($killed.Count -gt 0 -or $cannot.Count -gt 0) {
                Bad "2c: the engine got TerminateProcess"
            } else {
                Bad "2c: neither tell appeared within 8s"
            }
            Dump "2c, the engine stop" ($sent + $killed + $cannot)
        }
    } else {
        Skip "2c: no runtime is ready or loading, so there is no engine to stop"
    }
}

# ===================================================================== #
# CHECK 3 -- the master key in SYSTEM's own credential store
# ===================================================================== #

Say "CHECK 3 -- the master key lands in SYSTEM's store and survives a restart"

if ($securityMode -ne "os_keyring") {
    Skip "3: securityMode is '$securityMode'; there is no stored key to survive anything"
} else {
    $persisted = Find-Lines $loginLog 'master key persisted to OS keyring'
    $failed    = Find-Lines $loginLog 'keyring write failed'
    if ($persisted.Count -gt 0 -and $failed.Count -eq 0) {
        Ok "3a: the login wrote the key into the service account's keyring"
    } elseif ($failed.Count -gt 0) {
        Bad "3a: the keyring write failed -- LocalSystem could not write a credential"
    } else {
        # `_persist_master_key_if_keyring_mode` runs on EVERY login in
        # this mode and is idempotent, logging one of the two lines each
        # time -- so "neither" is not "it was already there", it is a
        # login that did not reach the keyring at all.
        Bad "3a: neither keyring line appeared on a login in os_keyring mode"
    }
    Dump "3a, the login" ($persisted + $failed)

    Note "restarting the service with nobody signing in afterwards"
    Set-LogMark
    $restartMark = $script:Mark
    try { Stop-Service -Name $ServiceName -ErrorAction Stop } catch { Warn "Stop-Service: $($_.Exception.Message)" }
    [void](Wait-ServiceStatus -Status "Stopped" -TimeoutSec 120)
    Start-Service -Name $ServiceName
    $health = Wait-Healthz -TimeoutSec 180
    if (-not $health) { Die "the service did not come back after check 3's restart" }

    $bootMark = $restartMark
    $bootLines = Read-LogFrom -Offset $restartMark
    $recovered = Find-Lines $bootLines 'master key recovered from OS keyring'
    $missing   = Find-Lines $bootLines 'no stored key was retrievable'
    if ($recovered.Count -gt 0) {
        Ok "3b: it recovered the key from the keyring on the next start"
    } elseif ($missing.Count -gt 0) {
        Bad "3b: 'no stored key was retrievable' -- the key is not in SYSTEM's store"
    } else {
        Bad "3b: neither keyring line appeared at boot"
    }
    Dump "3b, the boot after the restart" ($recovered + $missing)

    $status = Invoke-AgentSafe -Path "/v1/auth/status"
    if ($status.ok -and $status.value.unlocked) {
        Ok "3c: /v1/auth/status reports unlocked with nobody having signed in"
    } elseif ($status.ok) {
        Bad "3c: it came back LOCKED -- every health check is green and it routes nothing (the container symptom of 2026-09-12)"
    } else {
        Bad "3c: /v1/auth/status did not answer: $($status.why)"
    }
}

# ===================================================================== #
# CHECK 4 -- a real share, opened by a service that is not you
# ===================================================================== #

Say "CHECK 4 -- a share opens for LocalSystem"

# 4a: is there a credential row at all, and did it connect at boot?
# `GET /v1/config` is a FLAT document keyed by ConfigField.key -- there is
# no `values` wrapper -- and `shareCredentials` comes back as real rows
# with only the passwords redacted, so the hosts are readable here.
$cfg = Invoke-AgentSafe -Path "/v1/config" -Token $Token
$shareRows = @()
if ($cfg.ok -and $cfg.value.shareCredentials) {
    $shareRows = @($cfg.value.shareCredentials)
}
# `connect_all` logs at INFO on success and WARNING on failure, and the
# agent's formatter puts the level on the line. Matching the LEVEL rather
# than the sentence is what keeps 1219 ("Windows already holds a
# connection to that server as somebody else") on the failing side, which
# is where it belongs -- it means somebody else's session is in the way.
$bootLines = Read-LogFrom -Offset $bootMark
$shareAny  = Find-Lines $bootLines 'share login:'
$shareOk   = Find-Lines $bootLines '\sINFO\s.*share login:'
$shareBad  = Find-Lines $bootLines '\sWARNING\s.*share login:'

if ($shareRows.Count -eq 0) {
    Skip "4a: no shareCredentials configured. Add the server under Config -> Agent -> Storage ->"
    Note "    'Logins for file servers', press Test, then re-run. 4b below still decides whether"
    Note "    the service can open the share WITHOUT one, which is the finding either way."
} else {
    $servers = ($shareRows | ForEach-Object { $_.host }) -join ", "
    Note "shareCredentials: $servers"
    if ($shareOk.Count -gt 0 -and $shareBad.Count -eq 0) {
        Ok "4a: every configured share logged in at boot ($($shareOk.Count) of $($shareRows.Count))"
    } elseif ($shareBad.Count -gt 0) {
        Bad "4a: $($shareBad.Count) share login(s) failed at boot"
    } else {
        Bad "4a: a shareCredentials row exists and nothing logged a 'share login:' line at boot"
    }
    Dump "4a, the share logins" $shareAny
}

# 4b: the thing 1272 actually breaks -- can the SERVICE open the path a
# model is behind? Asked through the agent's own directory listing, which
# is a real open() in the service's process, not a probe from here.
$targets = @()
if ($SharePath) {
    $targets += $SharePath
} else {
    $folders = Join-Path $Prefix "library_folders.json"
    if (Test-Path -LiteralPath $folders) {
        try {
            $j = Get-Content -LiteralPath $folders -Raw | ConvertFrom-Json
            foreach ($f in $j.folders) {
                foreach ($m in $f.mounts) {
                    if ($m -match '^\\\\' -or $m -match '^[A-Za-z]:') { $targets += $m }
                }
            }
        } catch { Warn "could not read $folders : $($_.Exception.Message)" }
    }
}
$targets = @($targets | Select-Object -Unique)

if ($targets.Count -eq 0) {
    Skip "4b: no Windows-shaped library folder mount to open (pass -SharePath to name one)"
} else {
    foreach ($t in $targets) {
        $enc = [uri]::EscapeDataString($t)
        $d = Invoke-AgentSafe -Path "/v1/directories?path=$enc" -Token $Token
        if ($d.ok) {
            $n = 0
            if ($d.value.entries) { $n = @($d.value.entries).Count }
            Ok "4b: the service opened $t ($n entries)"
        } else {
            Bad "4b: the service could not open $t"
            Note "    $($d.why)"
            # **The agent cannot tell you it was 1272, and that is a real
            # gap rather than a gap in this script.** `list_directory`
            # asks `Path.exists()` first, and `Path.exists()` swallows
            # every OSError and answers False -- so a share LocalSystem
            # may not log in to is reported as *does not exist on this
            # machine*, which is the one wrong answer. The discriminator
            # is free: this session is a signed-in user with the
            # Credential Manager entry, so if the path opens HERE and not
            # THERE, the difference is the credential and nothing else.
            $hereOk = $false
            try { $hereOk = Test-Path -LiteralPath $t } catch { $hereOk = $false }
            if ($hereOk) {
                Note "    But $env:USERNAME CAN open it from this session. The difference between"
                Note "    the two is a credential, not a path -- Windows refuses the guest"
                Note "    fallback and a service has none of your Credential Manager entries."
                Note "    Add the server under Config -> Agent -> Storage -> 'Logins for file"
                Note "    servers', press Test, and re-run. (The agent says 'does not exist'"
                Note "    rather than 'error 1272' because Path.exists() swallows the OS error;"
                Note "    worth fixing, and not part of these six checks.)"
            } else {
                Note "    This session cannot open it either, so it is not a credential:"
                Note "    the server or the share is genuinely unreachable from this machine."
            }
        }
    }
}

# ===================================================================== #
# CHECK 6 -- the tray, unelevated, with no UAC prompt
# ===================================================================== #

Say "CHECK 6 -- the icon stops and starts Eugene with no Administrator prompt"

# 6a: the descriptor. Necessary, not sufficient: 6c is what proves it.
$sid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$sdRaw = ""
try { $sdRaw = (& sc.exe sdshow $ServiceName 2>&1 | Out-String).Trim() } catch { }
if ($sdRaw -match [regex]::Escape($sid)) {
    Ok "6a: the service descriptor carries an ACE for $env:USERNAME ($sid)"
} else {
    Bad "6a: no ACE for $sid in the service descriptor -- sc sdset did not take"
}
Note "sdshow: $sdRaw"

# 6b: the way back in, which is the other half of the same complaint.
$link = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\Eugene Plexus.lnk"
if (Test-Path -LiteralPath $link) {
    $target = (New-Object -ComObject WScript.Shell).CreateShortcut($link).TargetPath
    if ($target -and $target.StartsWith($Venv, [StringComparison]::OrdinalIgnoreCase)) {
        Ok "6b: a Start menu entry exists and runs this install's tray"
    } else {
        Bad "6b: the Start menu entry points at $target, which is not under $Venv"
    }
} else {
    Bad "6b: no 'Eugene Plexus' Start menu entry at $link"
}
if (Get-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue) {
    Ok "6b+: the tray's own logon task is registered"
} else {
    Warn "no $TrayTaskName logon task -- installed with -NoTray?"
}

# 6c: THE ONE THAT DECIDES IT, and it must not run elevated.
#
# An elevated process can stop any service, so doing this from here would
# pass whether or not 6a took. A scheduled task with `-RunLevel Limited`
# runs as this user at medium integrity, which is the tray's own context,
# and never prompts. The child asserts it is NOT admin before it acts --
# without that assertion this check could not fail.
# Measured 2026-09-19: the live per-user install on this box has no
# `tray` module at all -- its agent package predates f14ec87. `-Migrate`
# installs the current pins and fixes it, but an install that was merely
# converted by hand would not, and "ImportError" inside a scheduled task
# is the least legible failure this script could produce.
$trayImportable = $false
if (Test-Path -LiteralPath $PyBin) {
    & $PyBin -c "from eugene_plexus_agent import tray" 2>&1 | Out-Null
    $trayImportable = ($LASTEXITCODE -eq 0)
}

if (-not (Test-Path -LiteralPath $PyBin)) {
    Bad "6c: no python at $PyBin, so the tray's own code cannot be driven"
} elseif (-not $trayImportable) {
    Bad "6c: this install's agent package has no 'tray' module, so there is no icon to test"
    Note "    It predates agent f14ec87. Re-run the installer to pick up the pinned build:"
    Note "        .\scripts\install.ps1 -Migrate"
} else {
    $work = Join-Path $env:TEMP "ep-r26-check6"
    if (Test-Path $work) { Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    $childPy = Join-Path $work "check6.py"
    $outJson = Join-Path $work "result.json"

    # Literal here-string: nothing in it is expanded, so the backslashes
    # and quotes arrive as written.
    $py = @'
import ctypes
import json
import sys
import time

from eugene_plexus_agent import tray

port = int(sys.argv[1])
out = sys.argv[2]
r = {}
try:
    r["is_admin"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
except Exception as exc:
    r["is_admin"] = None
    r["is_admin_error"] = str(exc)

r["initial"] = tray.query_state()
ok, why = tray.stop_service()
r["stop_ok"], r["stop_why"] = ok, why
if ok:
    # Only wait for a stop that was accepted. Waiting 90 s for a refusal
    # turns "access is denied" into "the script hung", which is the
    # failure mode reading worst in a terminal somebody is watching.
    deadline = time.time() + 90
    while time.time() < deadline and tray.query_state() != tray.ServiceState.stopped:
        time.sleep(0.5)
r["after_stop"] = tray.query_state()

# Starting a service that never stopped answers 1056 ("an instance is
# already running"), which would read as a second, different failure for
# one cause. Attempt the start only when there is something to start.
if r["after_stop"] == tray.ServiceState.stopped:
    r["start_attempted"] = True
    ok, why = tray.start_service()
    r["start_ok"], r["start_why"] = ok, why
    r["answering"] = tray.wait_until_answering(port, 240) if ok else False
else:
    r["start_attempted"] = False
    r["start_ok"], r["start_why"], r["answering"] = False, "not attempted: it never stopped", False
r["final"] = tray.query_state()

with open(out, "w", encoding="utf-8") as fh:
    json.dump(r, fh)
'@
    [IO.File]::WriteAllText($childPy, $py, (New-Object Text.UTF8Encoding $false))

    if (Get-ScheduledTask -TaskName $Check6Task -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Check6Task -Confirm:$false
    }
    $action = New-ScheduledTaskAction -Execute $PyBin `
        -Argument "`"$childPy`" $Port `"$outJson`"" -WorkingDirectory $work
    # `WindowsIdentity.Name` rather than `$env:USERDOMAIN\$env:USERNAME`:
    # this box's account is a Microsoft account on a workgroup machine,
    # where the two do not always agree, and the scheduler resolves the
    # fully-qualified form it prints.
    $whoami = ([Security.Principal.WindowsIdentity]::GetCurrent()).Name
    $principal = New-ScheduledTaskPrincipal -UserId $whoami `
        -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

    $registered = $false
    try {
        Register-ScheduledTask -TaskName $Check6Task -Action $action `
            -Principal $principal -Settings $settings `
            -Description "R2.6 check 6: stop and start Eugene as the signed-in user, unelevated" | Out-Null
        $registered = $true
    } catch {
        Bad "6c: could not register the unelevated probe task: $($_.Exception.Message)"
    }

    if ($registered) {
        Note "running the tray's own stop/start as $env:USERNAME at medium integrity"
        Set-LogMark
        Start-ScheduledTask -TaskName $Check6Task
        $deadline = (Get-Date).AddMinutes(8)
        while ((Get-Date) -lt $deadline -and -not (Test-Path -LiteralPath $outJson)) {
            Start-Sleep -Seconds 2
        }
        if (-not (Test-Path -LiteralPath $outJson)) {
            $state = (Get-ScheduledTask -TaskName $Check6Task).State
            $info  = Get-ScheduledTaskInfo -TaskName $Check6Task
            Bad "6c: the unelevated probe produced no result (task state $state, last result $($info.LastTaskResult))"
            Note "    If LastTaskResult is 267011 the task never ran; if it is non-zero the"
            Note "    child failed before writing. Run it by hand from a NON-elevated"
            Note "    PowerShell: & '$PyBin' '$childPy' $Port '$outJson'"
        } else {
            $r = Get-Content -LiteralPath $outJson -Raw | ConvertFrom-Json
            if ($r.is_admin -eq $true) {
                Bad "6c: the probe ran ELEVATED, so it proves nothing about the grant"
            } else {
                if ($r.stop_ok -and $r.after_stop -eq "stopped") {
                    Ok "6c: an unelevated $env:USERNAME stopped the service with no prompt"
                } else {
                    Bad "6c: the unelevated stop failed: $($r.stop_why)"
                }
                if (-not $r.start_attempted) {
                    Skip "6c: the start was not attempted, because the stop above never took"
                } elseif ($r.start_ok -and $r.answering) {
                    Ok "6c: and started it again, and it answered /healthz"
                } elseif ($r.start_ok) {
                    Bad "6c: the start was accepted but /healthz never answered within 240s"
                } else {
                    Bad "6c: the unelevated start failed: $($r.start_why)"
                }
            }
            Note "probe: $(ConvertTo-Json $r -Compress)"
        }
        Unregister-ScheduledTask -TaskName $Check6Task -Confirm:$false -ErrorAction SilentlyContinue
        Dump "6c, what the service did while the icon drove it" `
            (Find-Lines (Get-NewLog) 'child shutdown|Uvicorn|Started server|allocated a console|cannot send a console event')
    }
}

# --- leave it running, and say what is left ---------------------------- #

Say "AFTERWARDS"
$health = Wait-Healthz -TimeoutSec 180
if ($health) {
    Ok "the service is up and answering (status=$($health.status))"
} else {
    Bad "the service is NOT answering at the end of the run -- start it before you walk away"
}

Write-Host ""
Write-Host "----------------------------------------------------------------"
Write-Host "$($script:Failures) FAIL, $($script:Skips) SKIP, $(@($script:Checks | Where-Object { $_ -like 'PASS*' }).Count) PASS"
Write-Host ""
Write-Host "CHECK 5 IS YOURS, AND IT IS TWO ACTIONS:" -ForegroundColor White
Write-Host ""
Write-Host "  1. Reboot. Do NOT sign in."
Write-Host "  2. While the lock screen is up, open this on your phone:"
Write-Host "         http://192.168.16.75:$Port/healthz"
Write-Host "     Then sign in and run:"
Write-Host "         .\scripts\r26-service-checks.ps1 -AfterReboot"
Write-Host ""
Write-Host "  You do NOT need a second machine to sit at. The control root at"
Write-Host "  $OffHostAddress probes this node every ~15 s, so the log already"
Write-Host "  holds off-host requests from it timestamped between boot and login."
Write-Host "  -AfterReboot finds them, times them against the OS boot and your"
Write-Host "  logon, and prints them. The phone is the second, independent caller."
Write-Host ""
Write-Host "  ONLY WHILE THE ROOT IS UNLOCKED. Preflight above said which it is."
Write-Host "  A sealed root polls nothing while answering /healthz with ok, so if it"
Write-Host "  is sealed the phone is not corroboration -- it is the whole of check 5."
Write-Host ""
Write-Host "  Do it within a few hours: agent.log rotates at 10 MB, which is about"
Write-Host "  seven hours of engine health probes on this box."

exit $script:Failures
