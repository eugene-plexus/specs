<#
.SYNOPSIS
  Eugene Plexus -- one-command install for Windows.

.DESCRIPTION
  The Windows half of install-paths section 9 step 3. Same six steps as
  `install.sh`, in the same order, so that reading one is reading both:

    1. fetch `uv` into the install prefix and nowhere else,
    2. make a virtualenv there with a Python `uv` downloads itself,
    3. install the seven Eugene Plexus packages into it,
    4. check that what landed can actually serve -- see VERIFY below,
    5. register autostart (a service, or a per-user scheduled task),
    6. start it and wait for the agent to answer.

  It touches nothing outside the prefix except the one autostart entry,
  and `-Uninstall` removes both.

  A WINDOWS INSTALL IS A SERVICE (R2.6, 2026-09-18). It asks for
  Administrator once, installs into %ProgramData%\EugenePlexus, and
  registers a real service that starts at boot with nobody logged in.

  That is a change, and the reason is that the old default could not
  keep the promise the product makes. A logon scheduled task dies at
  sign-out, dies at a user switch, and never starts after a reboot that
  lands on the lock screen -- so an install that says it "comes back
  working without you" answered a phone at 7 am with connection refused
  and had no screen that could explain why. Decision 4 of the release
  roadmap: the promise is the requirement, so the mechanism changes
  rather than the sentence.

  `-NoService` keeps the whole unelevated path: %LOCALAPPDATA% and a
  logon task, exactly as before, for anyone who wants it.

  `-Migrate` also copies completed engine builds from the invoking user's
  legacy engine store, including on a retry after the service is installed.
  `-MigrateEngineRoot <path>` selects a custom source. Existing destination
  builds and the original files are preserved.

  WHAT THE SERVICE COSTS, AND WHAT IT NO LONGER COSTS. It runs as
  LocalSystem, which holds none of the credentials the person installing
  it collected by hand -- so an authenticated file share needs a row in
  `shareCredentials` (Config -> Agent -> Storage), and a migrated
  install comes back sealed exactly once because its master key is in
  the installing user's Credential Manager and not in SYSTEM's. Both are
  reported below before they happen.

  It no longer costs the graceful stop. `install-paths` section 7 ruled
  out a service with `AllocConsole()` on the grounds that it would make
  the agent's logs vanish; that cost was asserted and never measured,
  and measuring it (R2.6, section 0.3 of the design) found a real
  `llama-server` exiting in 0.036 s on `CTRL_BREAK_EVENT` with the log
  file still being written. The agent allocates a console at service
  start and children are asked to stop, not killed.

  THE LOGON TASK DOES NOT DISAPPEAR, IT CHANGES JOB. It now starts the
  notification-area icon, which is the one part of this that belongs in
  a person's own session -- session 0 isolation means a service cannot
  draw anything on a desktop. Stop Eugene from the icon to free the
  graphics card for a game, start it again afterwards. `-NoTray` skips
  it.

  -UPDATE IS HOW THE APP UPDATES AN INSTALL (2026-09-27). The agent starts
  this script from a one-shot scheduled task -- as SYSTEM for the service,
  as the person for a per-user install -- because the first thing an
  upgrade does is stop the agent. It replaces the packages with the ones
  this script pins, refreshes the service host, starts Eugene again, and
  keeps everything else about the install exactly as it is: its autostart,
  the tray icon, who may start and stop it, and its folder's permissions.
  Run as SYSTEM, an ordinary run would re-register those for SYSTEM.

  WHERE THE PACKAGES COME FROM. GitHub source archives at pinned
  commits -- the same mechanism `SPECS_REF` has used in every consumer
  since M0. No package registry, no release. The UI pin points at the
  `ui` repo's `dist` branch and not at `main`, because the wheel's
  payload is `next build` output that `main` gitignores: installing from
  a `main` archive succeeds and produces a package with no UI in it.

.EXAMPLE
  irm https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.ps1 | iex

.EXAMPLE
  # With options (iex cannot pass arguments):
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.ps1))) -NoService

.EXAMPLE
  # Disposable acceptance/development install beside an existing service.
  # Requires a new directory. Does not register startup or persist environment.
  .\install.ps1 -Prefix "$env:TEMP\EugeneAcceptance-new" -NoService -NoStart -Isolated
#>
[CmdletBinding()]
param(
    [string]$Prefix,
    [switch]$NoService,
    [switch]$NoTray,
    [switch]$NoElevate,
    [switch]$NoStart,
    [switch]$Isolated,
    [switch]$Uninstall,
    [switch]$Verify,
    [switch]$Detect,
    [switch]$Migrate,
    [string]$MigrateEngineRoot,
    [switch]$PurgeDownloads,
    [switch]$PurgeModelCopies,
    [string]$Join,
    [string]$Token,
    [string]$NodeName,
    [string]$Advertise,
    [switch]$Update
)

$ErrorActionPreference = "Stop"
# Read before `$Prefix` is given its default below: -Uninstall with no
# -Prefix finds the install wherever it is.
$PrefixGiven = [bool]$Prefix

# --- pins -------------------------------------------------------------
# Keep in lockstep with install.sh. One commit per repo.
$PIN = @{
    "agent"            = "9ac7b7e6194246ac980cc9463745747f14caba97"
    "control"          = "919157644755ef08233bdbc09afd3fe525342cdd"
    "gateway"          = "744964c5118c30a894c2f08886206a713569afca"
    "inference-driver" = "f5cf2e07261675627d1d9cff9bf49722158c456f"
    "library"          = "812201750e908b7fc2452c18458417459903f535"
    "tool-driver"      = "49c289fdaba3703a50d362801b1a9e682ad4d954"
    "ui"               = "b93bbde7bd7faddd5627ac86af30167d26335936"  # branch `dist`, not `main`
}
$DIST = @{
    "agent"            = "eugene-plexus-agent"
    "control"          = "eugene-plexus-control"
    "gateway"          = "eugene-plexus-gateway"
    "inference-driver" = "eugene-plexus-inference-driver"
    "library"          = "eugene-plexus-library"
    "tool-driver"      = "eugene-plexus-tool-driver"
    "ui"               = "eugene-plexus-ui"
}

$PyVersion = "3.12"
$ServiceName = "EugenePlexusAgent"
$TaskName = "EugenePlexusAgent"
# **A different name, because it is a different thing** (R2.6). Before
# this, `$TaskName -eq $ServiceName` and the task WAS the agent. It now
# starts the tray icon, which has no business being unregistered by
# something cleaning up an agent -- and `Get-AutostartExecutable` reads
# the task as evidence of where the install is, which a tray icon in a
# user's session is not.
$TrayTaskName = "EugenePlexusTray"
# Quoted in messages that tell a person which command to run next.
$InstallerUrl = "https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.ps1"

function Say { param($m) Write-Host "==> $m" -ForegroundColor Cyan }
function Warn { param($m) Write-Host "warning: $m" -ForegroundColor Yellow }
# **`Die` throws; it does NOT call `exit`.** The documented way to run
# this script with options is
# `& ([scriptblock]::Create((irm ...))) -Join ...`, and a scriptblock
# invoked that way runs in the CALLER'S PROCESS -- so `exit 1` closed
# the operator's terminal, taking the error message with it and leaving
# no way to find out what went wrong. Reported from a VS Code terminal
# that vanished on every failure. A throw is catchable, prints, and
# still yields exit code 1 under `powershell -File`.
#
# **And the throw is marked, so nothing prints it a second time.** An
# uncaught throw in a scriptblock run at a person's prompt is printed as
# a whole ErrorRecord -- the message again, "At line:145 char:71", a
# snippet of this function, CategoryInfo, FullyQualifiedErrorId -- after
# the message has already been said (2026-09-26). The script-level
# `trap` below step 1 recognises this id and stops the run quietly.
function Die {
    param($m)
    Write-Host "error: $m" -ForegroundColor Red
    throw [Management.Automation.ErrorRecord]::new(
        [Exception]::new($m), 'EugenePlexusInstallFailed', 'NotSpecified', $null)
}

# Acceptance/development installs must never take over the live service or
# account environment. Require a fresh, explicitly named prefix and no startup.
if ($Isolated) {
    if (-not $Prefix -or -not $NoService -or -not $NoStart -or
        $Migrate -or $Uninstall -or $Join -or $Verify -or $Detect) {
        Die "-Isolated requires -Prefix, -NoService and -NoStart; migration, joining and maintenance actions cannot be combined with it"
    }
    if (Test-Path -LiteralPath $Prefix) {
        Die "-Isolated requires a new prefix; the target already exists"
    }
}

# And every early return below is `return`, never `exit` -- measured,
# not assumed: `exit 0` inside a scriptblock ends the host session too,
# so the SUCCESS path closed the terminal as surely as a failure did.

# **Native commands and $ErrorActionPreference = "Stop" do not mix.**
# In Windows PowerShell 5.1, an exe writing to stderr while its output
# is piped raises a terminating NativeCommandError -- so `npm` printing
# an ordinary DeprecationWarning killed this script twice before this
# helper existed. The exit code is the truth about a native command;
# stderr is not. Run them all through here.
function Invoke-Native {
    param([Parameter(Mandatory)][string]$Exe, [string[]]$Arguments, [string]$FailMessage)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $output = @(& $Exe @Arguments 2>&1 | ForEach-Object { "$_" }) }
    finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) {
        $output | ForEach-Object { Write-Host $_ }
        if ($FailMessage) { Die "$FailMessage (exit code $LASTEXITCODE)" }
    }
}

function Set-ServiceBootstrap {
    # Service-local values apply immediately; SCM can retain the machine
    # environment from boot even after SetEnvironmentVariable updates it.
    $values = @(
        "EUGENE_PLEXUS_AGENT_CONFIG_FILE=$Config",
        "EUGENE_PLEXUS_AGENT_BIND_PORT=$Port",
        "EUGENE_PLEXUS_AGENT_ENGINE_ROOT=$(Join-Path $Prefix 'engines')",
        "EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS=$(Join-Path $Prefix 'models')"
    )
    New-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName" `
        -Name Environment -PropertyType MultiString -Value $values -Force | Out-Null
}

# Replay the elevated run's transcript: what the person would have seen in
# the window that was hidden, and nothing else. Start-Transcript wraps the
# output in two banners of asterisks (the second repeats every
# environment detail, the first carries the whole -EncodedCommand), and
# logs every terminating error as a "PS>TerminatingError(...)" line.
function Show-InstallerLog {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $inBanner = $false
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line -match '^\*{10,}$') { $inBanner = -not $inBanner; continue }
        if ($inBanner) { continue }
        if ($line -match '^(PS>|>> )TerminatingError\(') { continue }
        if ($line -like 'error:*') { Write-Host $line -ForegroundColor Red }
        elseif ($line -like 'warning:*') { Write-Host $line -ForegroundColor Yellow }
        elseif ($line -like '==>*') { Write-Host $line -ForegroundColor Cyan }
        else { Write-Host $line }
    }
}

function Invoke-ElevatedInstaller {
    param([string]$ScriptText, [System.Collections.IDictionary]$Parameters,
        [string]$WorkDirectory = ([IO.Path]::GetTempPath()))
    $stem = Join-Path $WorkDirectory ("eugene-plexus-install-" + [guid]::NewGuid().ToString('N'))
    $self = "$stem.ps1"
    $parameterFile = "$stem.clixml"
    $logFile = "$stem.log"
    # Windows PowerShell needs a BOM to read non-ASCII script text correctly.
    [IO.File]::WriteAllText($self, $ScriptText, (New-Object Text.UTF8Encoding $true))
    $arguments = @{}
    foreach ($entry in $Parameters.GetEnumerator()) {
        $arguments[$entry.Key] = if ($entry.Value -is [switch]) { $entry.Value.IsPresent } else { $entry.Value }
    }
    $arguments | Export-Clixml -LiteralPath $parameterFile
    # Paths only in the process command line/transcript header. Parameter values
    # (including a join token) live in the temporary file, deleted in finally.
    $runner = @'
$ErrorActionPreference = 'Stop'
$result = 0
try {
    Start-Transcript -LiteralPath '__LOG__' -Force | Out-Null
    $parameters = Import-Clixml -LiteralPath '__PARAMETERS__'
    $global:EugenePlexusInstallFailed = $false
    & '__SCRIPT__' @parameters
    # The script's trap stops a failed run without throwing, and says so
    # here; $LASTEXITCODE cannot, because a native command earlier in a
    # successful run can leave it non-zero.
    if ($global:EugenePlexusInstallFailed) { $result = 1 }
}
catch {
    # Reached only when the script could not start at all. One line, not
    # the whole ErrorRecord.
    Write-Host "error: the installer could not run: $($_.Exception.Message)" -ForegroundColor Red
    $result = 1
}
finally {
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
}
exit $result
'@
    $runner = $runner.Replace('__LOG__', $logFile.Replace("'", "''")).Replace('__PARAMETERS__', $parameterFile.Replace("'", "''")).Replace('__SCRIPT__', $self.Replace("'", "''"))
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($runner))
    Say "$(if ($Parameters['Uninstall']) { 'Uninstalling' } else { 'Installing' }) now... Installer log: $logFile"
    try {
        $elevated = Start-Process -FilePath 'powershell.exe' `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded) `
            -Verb RunAs -WindowStyle Hidden -Wait -PassThru
        # The elevated window is hidden, so its output is only in the log.
        # Shown after every run, success too -- otherwise a successful
        # install said nothing but "done" -- and without the transcript's
        # own banners, which carried a screenful of -EncodedCommand base64.
        Show-InstallerLog $logFile
        if ($elevated.ExitCode -ne 0) {
            Die "the install did not finish (see above). Log: $logFile"
        }
        Say "done. Installer log: $logFile"
    }
    finally {
        Remove-Item -LiteralPath $self, $parameterFile -Force -ErrorAction SilentlyContinue
    }
}

$IsElevated = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# **What kind of install this is, decided before anything is written.**
# R2.6 inverted the default: a Windows install is a service unless the
# operator asks otherwise, because a logon task cannot keep the promise
# the product makes. `-NoService` is the whole of the old unelevated
# path and is the only way to get it.
#
# `-Uninstall` is the exception, and only it. It must work at whatever
# elevation it was started with, or removing a per-user install would
# demand Administrator it does not need -- so it keeps the old rule and
# picks its prefix by elevation.
#
# `-Verify` and `-Detect` are deliberately NOT exceptions, although both
# are read-only and neither elevates. They REPORT on the install, and an
# install report that describes a shape an ordinary run would not
# produce is worse than no report: `-Detect` exists to answer "is this a
# second install?", and it can only answer that about the prefix the
# next run will actually use.
$WantsService = -not ($NoService -or $Uninstall)

if (-not $Prefix) {
    $Prefix =
    if ($Uninstall) {
        if ($IsElevated) { Join-Path $env:ProgramData "EugenePlexus" }
        else { Join-Path $env:LOCALAPPDATA "EugenePlexus" }
    }
    elseif ($WantsService) {
        Join-Path $env:ProgramData "EugenePlexus"
    }
    else {
        Join-Path $env:LOCALAPPDATA "EugenePlexus"
    }
}

$Venv = Join-Path $Prefix "venv"
$PyBin = Join-Path $Venv "Scripts\python.exe"
$AgentEx = Join-Path $Venv "Scripts\eugene-plexus-agent.exe"
$UvExe = Join-Path $Prefix "bin\uv.exe"
$Config = Join-Path $Prefix "agent.yaml"
$Port = if ($env:EUGENE_PLEXUS_AGENT_BIND_PORT) { $env:EUGENE_PLEXUS_AGENT_BIND_PORT } else { 8079 }

# --- -Update ----------------------------------------------------------
# An upgrade of the install at -Prefix and nothing else: see the top of
# this file. Refused for anything that is not already an install, so an
# update can never be the thing that makes a second one.
if ($Update) {
    if ($Join -or $Uninstall -or $Migrate -or $Isolated) {
        Die "-Update upgrades the install at $Prefix; it cannot be combined with -Join, -Uninstall, -Migrate or -Isolated"
    }
    if (-not (Test-Path -LiteralPath $PyBin) -or -not (Test-Path -LiteralPath $Config)) {
        Die "-Update found no install at $Prefix to update"
    }
}

# --- -Verify ----------------------------------------------------------
# The two commands that close the one gap this installer cannot close
# itself. Printed rather than run, because running them needs the
# elevation that is the whole point.
if ($Verify) {
    Write-Host @"
R2.6 INVERTED WHICH PATH IS THE UNVERIFIED ONE, and this text says so
rather than being quietly updated. The scheduled-task path is covered by
scripts/install-acceptance.sh and has been since step 3. The SERVICE
path -- which is now what an ordinary Windows install GETS -- needs
Administrator and a reboot, and neither is reachable from a
non-interactive harness. These are the six checks that close it. Run
them in an ELEVATED PowerShell, on a machine you are willing to reboot.

1. It registers, answers, and stops.

    & "$PyBin" -m eugene_plexus_agent.winservice install
    Start-Service $ServiceName
    Invoke-RestMethod http://127.0.0.1:$Port/healthz
    Stop-Service $ServiceName

2. THE CONSOLE, WHICH IS THE ONE MEASUREMENT SESSION 1 COULD NOT MAKE.
   `process_signals.ensure_console()` was measured in an interactive
   session: a console-less parent that allocates one gets its child out
   in 0.036 s on CTRL_BREAK_EVENT. A service runs in SESSION 0 and that
   has not been measured anywhere. With the service running and a model
   loaded, stop the runtime and read $Prefix\logs\agent.log:

     want: 'child shutdown: children are stopped with CTRL_BREAK_EVENT'
     not:  'child shutdown: ... no console ...'

   The second line means AllocConsole did not work in session 0 and the
   graceful stop is gone -- which is survivable, and is the thing to
   find out here rather than from somebody's truncated answer.

3. The master key, in the service's own store. Sign in once after
   installing; restart the service; confirm it comes back unlocked
   without asking again.

4. A share, if this machine reads models over one. Add the server under
   Config -> Agent -> Storage -> Logins for file servers, press Test,
   then restart the service and confirm a model still loads. A service
   has none of your Credential Manager entries -- Windows answers
   error 1272 even for a folder with no password on it.

5. THE ONE THAT IS THE POINT. Reboot. Do not sign in. From another
   machine: Invoke-RestMethod http://<this host>:$Port/healthz

6. The icon: stop and start Eugene from it with no Administrator
   prompt. If it says access is denied, `sc sdset` did not take -- see
   Grant-ServiceControl in this script.

ALL OF THE ABOVE EXCEPT 5 ARE SCRIPTED. From an elevated PowerShell:

    .\scripts\r26-service-checks.ps1 -Migrate

It runs 1, 2, 3, 4 and 6, prints PASS or FAIL for each, and prints the
agent.log lines that decided each one so you are not grepping. Afterwards
`-AfterReboot` reads check 5's evidence out of the log, so the reboot and
a phone are the only manual parts left.
"@
    return
}

# --- which install is this? -------------------------------------------
# **A machine can hold two installs, and this script could not tell**
# (review 6.1 #10). Line 427 below tells an unelevated user to re-run
# from an elevated PowerShell to get a service -- and doing exactly that
# switched the prefix from %LOCALAPPDATA% to %ProgramData%, unregistered
# the first install's task **by name and without a word**, repointed the
# config-file variable, and started a service with no agent.yaml: the
# wizard again, a second trust root, and the first install's passphrase,
# models folder, keyring entry and enrolled workers stranded.
#
# The discriminator is the one `reach.py` already uses for the same
# question: the autostart's own program path against this run's
# virtualenv. An installer that is about to replace a venv has to know
# whether the thing pointing at it is its own.
function Get-AgentService {
    Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
}
function Get-AgentTask {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

# The program an autostart runs, or $null. Read through the scheduler's
# own object model rather than `schtasks` output -- a console program's
# stdout is the OEM code page, so a prefix with an accent in it comes
# back mangled (review 6.3 #34, the same trap this installer's agent
# had).
function Get-AutostartExecutable {
    $svc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
    if ($svc -and $svc.PathName) {
        $path = $svc.PathName.Trim()
        if ($path.StartsWith('"')) { return $path.Substring(1, $path.IndexOf('"', 1) - 1) }
        return ($path -split ' ')[0]
    }
    $task = Get-AgentTask
    if ($task) {
        $exe = @($task.Actions)[0].Execute
        if ($exe) { return $exe.Trim('"') }
    }
    return $null
}

# Is that program inside the virtualenv this run is about to write?
# `$Venv` itself is not a match -- only something under it -- so
# `EugenePlexus-dev\venv` beside `EugenePlexus\venv` is somebody else's.
function Test-RunsFromThisInstall {
    param([string]$Executable)
    if (-not $Executable) { return $false }
    try {
        $a = [IO.Path]::GetFullPath($Executable)
        $b = [IO.Path]::GetFullPath($Venv)
    }
    catch { return $false }
    return $a.StartsWith($b.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

# Everything this machine can tell us about an install that is not the
# one being asked for, in the order the roadmap ranks the markers:
# the autostart's action path, the config-file variable, a prefix with
# an agent.yaml in it.
function Get-OtherInstall {
    $exe = Get-AutostartExecutable
    if ($exe -and -not (Test-RunsFromThisInstall $exe)) {
        # <prefix>\venv\Scripts\<exe> -- two levels up is the prefix.
        $other = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $exe))
        return [pscustomobject]@{ Prefix = $other; Why = "the autostart on this machine runs $exe" }
    }
    if ($exe) { return $null }  # the autostart is ours; nothing else can outrank it
    foreach ($scope in @("User", "Machine")) {
        $cfg = [Environment]::GetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", $scope)
        if ($cfg -and (Test-Path $cfg)) {
            $otherPrefix = Split-Path -Parent $cfg
            if ([IO.Path]::GetFullPath($otherPrefix).TrimEnd('\') -ne
                [IO.Path]::GetFullPath($Prefix).TrimEnd('\')) {
                return [pscustomobject]@{
                    Prefix = $otherPrefix
                    Why    = "EUGENE_PLEXUS_AGENT_CONFIG_FILE ($scope) points at $cfg"
                }
            }
            return $null
        }
    }
    foreach ($candidate in @((Join-Path $env:LOCALAPPDATA "EugenePlexus"),
            (Join-Path $env:ProgramData "EugenePlexus"))) {
        if (-not $candidate) { continue }
        if ([IO.Path]::GetFullPath($candidate).TrimEnd('\') -eq
            [IO.Path]::GetFullPath($Prefix).TrimEnd('\')) { continue }
        if (Test-Path (Join-Path $candidate "agent.yaml")) {
            return [pscustomobject]@{
                Prefix = $candidate
                Why    = "there is an agent.yaml at $candidate"
            }
        }
    }
    return $null
}

function Show-InstallVerdict {
    $exe = Get-AutostartExecutable
    Write-Host "prefix for this run:  $Prefix"
    Write-Host "elevated:             $IsElevated"
    if ($exe) {
        Write-Host "autostart runs:       $exe"
    }
    else {
        Write-Host "autostart runs:       (nothing registered under $TaskName / $ServiceName)"
    }
    $other = Get-OtherInstall
    if ($null -eq $other) {
        if ($exe) {
            Say "this install: an ordinary run is an upgrade of the install already here"
        }
        else {
            Say "no install found on this machine: an ordinary run is a first install"
        }
        return $true
    }
    Warn "a DIFFERENT install is already on this machine, at $($other.Prefix)"
    Write-Host "  because $($other.Why)"
    Write-Host ""
    Write-Host "  An ordinary run would take its autostart over and leave that install's"
    Write-Host "  passphrase, models folder, keyring entry and enrolled workers behind,"
    Write-Host "  with a second trust root asking for a new passphrase. So it refuses."
    Write-Host ""
    # **After R2.6, the commonest reason to be standing here is not a
    # mistake.** Every install made before 2026-09-18 is a per-user one,
    # and the default moved to a service -- so the first upgrade on any
    # existing Windows box reads as "a DIFFERENT install", correctly,
    # and the answer is usually to migrate rather than to refuse. The
    # order below says so; `-Migrate` prints what it costs before it
    # does anything (see Show-MigrationConsequences).
    if ($WantsService -and
        $other.Prefix -and
        [IO.Path]::GetFullPath($other.Prefix) -ne [IO.Path]::GetFullPath($Prefix)) {
        Write-Host "  To move this install to a Windows service, so it starts at boot"
        Write-Host "  before anyone signs in (this is the upgrade path):"
        Write-Host "      ... -Migrate"
        Write-Host "  To keep it exactly as it is -- starting when you log in:"
        Write-Host "      ... -Prefix '$($other.Prefix)' -NoService"
    }
    else {
        Write-Host "  To upgrade the install that is already here:"
        Write-Host "      ... -Prefix '$($other.Prefix)'"
        Write-Host "  To move this machine to $Prefix on purpose, taking the autostart with it:"
        Write-Host "      ... -Prefix '$Prefix' -Migrate"
    }
    Write-Host "  To remove the old one first:"
    Write-Host "      ... -Prefix '$($other.Prefix)' -Uninstall"
    return $false
}

# Called before anything is written, and before the uninstall touches an
# autostart it may not own.
function Assert-OwnInstall {
    $other = Get-OtherInstall
    if ($null -eq $other) { return }
    if ($Migrate) {
        Warn "migrating: the autostart at $($other.Prefix) will be replaced by this install"
        return
    }
    Show-InstallVerdict | Out-Null
    Die "refusing to build a second install on this machine (see above; -Migrate overrides)"
}

# **Say what a service install costs BEFORE it costs it** (R2.6).
#
# A LocalSystem service holds none of the per-user things this install
# keeps in the installing person's profile, and there are three of them.
# Two are handled by the installer and one cannot be:
#
#   * the config-file variable moves from User scope to Machine scope,
#     below -- without it the service resolves its own default path,
#     finds no agent.yaml and RAISES A SECOND INSTALL;
#   * a share credential becomes a row in `shareCredentials`, because
#     the entry the person typed into Explorer is in their profile;
#   * the MASTER KEY is in their Credential Manager and cannot be
#     written into SYSTEM's from here. The install comes back sealed
#     exactly once. Signing in re-seals it into the service's own store
#     and every boot after that is unattended.
#
# The third is why this function exists. An install that comes back
# sealed with no warning is indistinguishable from an install that
# broke, and this product has already shipped that exact confusion once
# (the container restart of 2026-09-12: initialized but locked, with
# every health check green).
# **Let the person who installed it stop it, without a UAC prompt.**
#
# Stopping a service needs SERVICE_STOP, which by default is granted to
# Administrators and nobody else -- so a tray icon in an ordinary
# session gets `Access is denied` on every click, and "turn Eugene off
# to play a game" becomes "acknowledge a UAC prompt to play a game".
#
# The grant is deliberately the narrow one: rights on THIS ONE SERVICE
# for THIS ONE ACCOUNT. It is not `SeServiceLogonRight`, it is not a
# group, and it changes nothing about any other service on the machine.
#
# `sc sdset` REPLACES the descriptor rather than adding to it, so the
# string below has to carry the default ACEs too or the SCM itself
# loses access to its own service. Read it as: system and admins get
# everything they had, and the installing user additionally gets
# RP (start), WP (stop) and DT (pause) on top of the read rights
# every authenticated user already has.
function Grant-ServiceControl {
    $sid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
    # The Windows default descriptor for a service, verbatim, plus one
    # ACE. Taken from `sc sdshow` on a stock service rather than written
    # from memory -- a hand-built descriptor that merely looks right is
    # how a service becomes unmanageable by anything including the SCM.
    $default = "D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)" +
    "(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)"
    $mine = "(A;;CCLCSWRPWPDTLOCRRC;;;$sid)"
    $sacl = "S:(AU;FA;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;WD)"
    $sddl = "$default$mine$sacl"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & sc.exe sdset $ServiceName $sddl 2>&1 | Out-Null }
    finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) {
        # Not fatal: the install works, the icon does not. Saying which
        # beats failing the whole install over a convenience.
        Warn ("could not grant $env:USERNAME permission to start and stop the service " +
            "(sc sdset exited $LASTEXITCODE). The tray icon will ask for Administrator; " +
            "everything else is unaffected.")
        return $false
    }
    Say "$env:USERNAME may start and stop Eugene without a prompt"
    return $true
}

# **The prefix is private, and this is the only thing that makes it so
# on Windows** (2026-09-24). `_private_files` in the agent, control and
# the library makes a secret owner-only on POSIX from its first byte and
# calls the Windows half "the installer's business"; until now no
# installer took it. `%ProgramData%` hands every folder under it
# `BUILTIN\Users:(OI)(CI)(RX)` and `(CI)(WD,AD)`, so on the service
# install every local account could read node.yaml -- the install's
# signing key, which mints operator tokens for every node -- and add
# files anywhere under the prefix, which for a `.pth` in the venv is
# code that runs as LocalSystem at the next start. A per-user install
# inherits whatever the profile hands out; on the machine this was found
# on, a sandbox group had Modify.
#
# So the prefix gets a PROTECTED ACL: nothing inherited, SYSTEM and
# Administrators in full, and on a per-user install the person, because
# the agent runs as them. Everything written under it afterwards -- by
# the agent, control, the library or a driver, through a temp file and a
# rename -- inherits exactly that. A service install then opens three
# doors, each the narrowest that works:
#   * Users may LIST the prefix itself, this folder only, so that a
#     non-elevated run of this script still finds the install
#     (`Get-OtherInstall` tests for agent.yaml) rather than starting a
#     second one beside it. A name is not a secret, and listing a folder
#     grants no read of the files in it;
#   * Users may READ venv\ and pythons\, because the tray icon and the
#     Start menu entry run from them in the person's own session.
#     Reading Python is not a secret; adding to it is what this closes;
#   * the person who installed may CHANGE models\, because it is their
#     model folder (differentiator #3) and a service's defaults put it
#     here.
#
# Out of reach of any ACL, and not attempted: a Windows administrator,
# and a program running as the same account as the agent. The agent's
# `install_permissions` check reports what this leaves at every start.
# Never fatal: a prefix on a volume without ACLs installs and says so.
function Protect-InstallDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$Service,
        [string]$PersonSid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
    )
    $all = [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
    $thisFolder = [Security.AccessControl.InheritanceFlags]::None
    $rule = {
        param([string]$Sid, [string]$Rights, $Inheritance)
        New-Object Security.AccessControl.FileSystemAccessRule(
            (New-Object Security.Principal.SecurityIdentifier $Sid),
            [Security.AccessControl.FileSystemRights]$Rights,
            $Inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow)
    }
    # `Directory.SetAccessControl` is .NET Framework only; PowerShell 7
    # has the same call as an extension method, which it will not bind
    # as one. Either persists only the DACL, and propagates the change
    # to every child that inherits.
    $persist = {
        param([string]$Target, $Acl)
        if ($PSVersionTable.PSEdition -eq "Core") {
            [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($Target), $Acl)
        }
        else { [IO.Directory]::SetAccessControl($Target, $Acl) }
    }
    try {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)
        $acl.AddAccessRule((& $rule "S-1-5-18" "FullControl" $all))
        $acl.AddAccessRule((& $rule "S-1-5-32-544" "FullControl" $all))
        if ($Service) { $acl.AddAccessRule((& $rule "S-1-5-32-545" "ReadAndExecute" $thisFolder)) }
        else { $acl.AddAccessRule((& $rule $PersonSid "FullControl" $all)) }
        & $persist $Path $acl
        if ($Service) {
            $doors = @(
                @{ Name = "venv"; Sid = "S-1-5-32-545"; Rights = "ReadAndExecute" },
                @{ Name = "pythons"; Sid = "S-1-5-32-545"; Rights = "ReadAndExecute" },
                @{ Name = "models"; Sid = $PersonSid; Rights = "Modify" }
            )
            foreach ($door in $doors) {
                $sub = Join-Path $Path $door.Name
                if (-not (Test-Path -LiteralPath $sub -PathType Container)) { continue }
                $subAcl = Get-Acl -LiteralPath $sub
                $subAcl.AddAccessRule((& $rule $door.Sid $door.Rights $all))
                & $persist $sub $subAcl
            }
        }
        return $true
    }
    catch {
        Warn ("could not make $Path private ($($_.Exception.Message)). Other accounts on " +
            "this machine may be able to read this install's signing key; the agent says so " +
            "in its log at every start.")
        return $false
    }
}

# **A way back in, because stopping Eugene takes the web UI with it.**
#
# Asked 2026-09-19 (Troy): *"does it register as a Program the user can
# run again from the Start menu, since the UI goes with it?"* It did
# not, and that made the tray's own "Hide this icon" a ONE-WAY DOOR:
# stop Eugene, hide the icon, and the only ways back were services.msc,
# an elevated Start-Service, or signing out and in. Nothing in Start,
# nothing on the desktop, and a URL that answers connection refused.
#
# The shortcut runs the tray with `--open`, which starts the service if
# it is stopped, waits for `/healthz`, opens the browser, and leaves an
# icon behind -- so the one entry covers "I want Eugene" and "give me
# my icon back" without the person having to know they are different
# questions.
#
# **All Users, for a service install.** The service serves everybody on
# the box, so the entry belongs where everybody can see it. A per-user
# install puts it in that user's own Start menu, which is the only place
# it could be true.
function Get-StartMenuShortcutPath {
    $programs = if ($WantsService) {
        Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs"
    }
    else {
        Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    }
    return (Join-Path $programs "Eugene Plexus.lnk")
}

function Add-StartMenuShortcut {
    $trayExe = Join-Path $Venv "Scripts\eugene-plexus-tray.exe"
    if (-not (Test-Path $trayExe)) {
        Warn "no Start menu entry: $trayExe is missing (the [tray] extra did not install)"
        return
    }
    $link = Get-StartMenuShortcutPath
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $link) | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($link)
        $shortcut.TargetPath = $trayExe
        # `--no-icon` where the operator asked for no tray icon: the
        # entry still starts Eugene and opens it, which is the half that
        # is useful either way.
        $shortcut.Arguments = if ($NoTray) { "--open --no-icon --port $Port" }
        else { "--open --port $Port" }
        $shortcut.WorkingDirectory = $Prefix
        $shortcut.Description = "Open Eugene Plexus, starting it first if it is stopped"
        $shortcut.Save()
        Say "added 'Eugene Plexus' to the Start menu"
    }
    catch {
        # Never fatal: the install works, it is just less findable.
        Warn "could not add a Start menu entry ($($_.Exception.Message))"
    }
}

function Remove-StartMenuShortcut {
    # Both scopes, because an install may have changed shape since the
    # shortcut was written -- a per-user install migrated to a service
    # leaves one behind in the user's own Start menu otherwise.
    foreach ($programs in @(
            (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs"),
            (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
        )) {
        $link = Join-Path $programs "Eugene Plexus.lnk"
        if (Test-Path $link) {
            Remove-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
        }
    }
}

# The install that is about to become a service, or $null.
#
# **The discriminator is the SERVICE, not the target directory**, and
# getting that wrong is what made this function silent on the path an
# operator is most likely to take (found 2026-09-19, before the elevated
# run that would have met it). The old test was "does $Prefix already
# hold an agent.yaml" -- meant to stop the warning firing on every
# routine upgrade of a service install, and true of a far wider set than
# that. Point a service at an install that is already there --
# `-Prefix <the per-user one>`, which is the obvious way to convert one
# in place -- and the target holds an agent.yaml, so the function
# returned and the operator met the sealed install with no warning at
# all. That is the confusion this product shipped once already and the
# whole reason the text exists.
#
# A registered service means the consequences have been paid. Nothing
# else does.
function Get-ServiceConversionSource {
    if (-not $WantsService) { return $null }
    if (Get-AgentService) { return $null }
    $other = Get-OtherInstall
    if ($other -and $other.Prefix -and (Test-Path (Join-Path $other.Prefix "agent.yaml"))) {
        return $other.Prefix
    }
    if (Test-Path (Join-Path $Prefix "agent.yaml")) {
        # **An install under %ProgramData% already WAS a service** -- only
        # an elevated run puts one there -- so registering it again costs
        # none of the two things below: its key is in the service's store
        # and it never used this person's file-server logins. Found
        # 2026-09-26 on Amish_Station, whose service had been removed by a
        # failed join: re-running the installer asked for -Migrate.
        if (Test-UnderProgramData $Prefix) { return $null }
        return $Prefix
    }
    return $null
}

function Show-MigrationConsequences {
    # `-ReportOnly` is for `-Detect`, which must print and never throw:
    # `Die` throws, and a `-Detect` that throws takes the operator's
    # terminal with it -- the exact defect the `$global:LASTEXITCODE`
    # comment below this function was written about.
    param([switch]$ReportOnly)
    $source = Get-ServiceConversionSource
    if (-not $source) { return }
    $moving = [IO.Path]::GetFullPath($source).TrimEnd('\') -ne
    [IO.Path]::GetFullPath($Prefix).TrimEnd('\')

    Write-Host ""
    if ($moving) {
        Warn "this machine already has a per-user install at $source"
        Write-Host "  Its config, enrollment and driver settings are copied to $Prefix,"
        Write-Host "  and $source is left where it is. Two things do NOT come across,"
        Write-Host "  because a service runs as the system rather than as you:"
    }
    else {
        Warn "this turns the install at $source into a Windows service"
        Write-Host "  Everything stays where it is. Two things change, because a service"
        Write-Host "  runs as the system rather than as you:"
    }
    Write-Host ""
    Write-Host "  1. IT WILL ASK FOR YOUR PASSPHRASE ONCE, on the first sign-in after this."
    Write-Host "     Eugene's key is in YOUR Windows Credential Manager and the service"
    Write-Host "     cannot read it. Signing in once puts a copy where the service can, and"
    Write-Host "     every start after that is unattended again. Nothing is lost -- but if"
    Write-Host "     you have forgotten the passphrase, stop here: there is no recovery."
    Write-Host ""
    Write-Host "  2. A MODEL FOLDER ON A NETWORK DRIVE WILL NEED A LOGIN. The service is not"
    Write-Host "     signed in as you, so the password you once typed into File Explorer is"
    Write-Host "     not available to it -- and Windows refuses an anonymous visitor even"
    Write-Host "     when the folder has no password of its own. Add the server under"
    Write-Host "     Config -> Agent -> Storage -> Logins for file servers."
    Write-Host ""
    if (-not $Migrate -and -not $ReportOnly) {
        Die @"
refusing to make this install a service without being asked to. Re-run with
    -Migrate once you have read the two points above, or keep it starting when
    you log in with:
        ... -NoService
"@
    }
}

# **What a migration actually has to carry, and did not (found
# 2026-09-19).** `-Migrate` migrated the AUTOSTART and nothing else.
# `$Prefix` defaults to %ProgramData% as soon as a service is wanted, so
# the documented upgrade path for every Windows install made before
# 2026-09-18 pointed a service at an empty directory: first-run wizard, a
# fresh signing key, an enrolled worker silently unenrolled, and the real
# install intact but orphaned one directory over. That is review 6.1 #10
# -- the finding R2.2 exists to fix -- coming back through R2.6's own
# upgrade path.
#
# **A denylist, deliberately.** The four names below are the ones the
# installer itself created and can recreate; everything else in a prefix
# is state, and that set is open-ended -- `agent.yaml`, `node.yaml`,
# `client_keys.json`, `library_folders.json`, one `<name>.yaml` per
# companion driver, and whatever the next milestone adds. An allowlist
# would silently drop the file nobody remembered to add to it, which is
# the failure being fixed here.
#
# `logs` is excluded for a different reason: the source directory is left
# in place, so nothing is lost by not copying it, and a service writing
# into a copy of a per-user log is just confusing.
#
# Never overwrites, so a re-run after a failure resumes rather than
# reverting; never deletes, so an upgrade cannot be the thing that loses
# an enrollment -- the same rule the uninstall follows.
function Copy-InstallState {
    param([string]$Source)
    if (-not $Source) { return }
    if ([IO.Path]::GetFullPath($Source).TrimEnd('\') -eq
        [IO.Path]::GetFullPath($Prefix).TrimEnd('\')) { return }
    if (-not (Test-Path (Join-Path $Source "agent.yaml"))) { return }

    $installerOwned = @("venv", "bin", "pythons", "logs")
    $copied = @()
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        if ($installerOwned -contains $item.Name) { continue }
        $target = Join-Path $Prefix $item.Name
        if (Test-Path -LiteralPath $target) { continue }
        Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force
        $copied += $item.Name
    }
    if ($copied.Count -gt 0) {
        Say "carried over from $Source : $($copied -join ', ')"
        Say "  $Source is left where it is -- delete it once this install is proven."
    }
}

function Copy-EngineBuilds {
    param([string]$Source)
    if (-not $Source -or -not (Test-Path -LiteralPath $Source)) { return }
    $destination = [IO.Path]::GetFullPath((Join-Path $Prefix 'engines')).TrimEnd('\')
    if ([IO.Path]::GetFullPath($Source).TrimEnd('\') -eq $destination) { return }
    foreach ($engine in Get-ChildItem -LiteralPath $Source -Directory) {
        foreach ($build in Get-ChildItem -LiteralPath $engine.FullName -Directory) {
            # Only complete managed builds; their metadata uses relative paths.
            if (-not (Test-Path -LiteralPath (Join-Path $build.FullName 'install.json'))) { continue }
            $engineDir = Join-Path $destination $engine.Name
            $target = [IO.Path]::GetFullPath((Join-Path $engineDir $build.Name))
            if (Test-Path -LiteralPath $target) { continue }
            # Outside the engine's version directory: ManagedStore examines
            # every child there, including one with a dot-prefixed name.
            $stage = [IO.Path]::GetFullPath((Join-Path $destination ('.migrate-' + [guid]::NewGuid().ToString('N'))))
            if (-not $target.StartsWith($destination + '\', 'OrdinalIgnoreCase') -or
                -not $stage.StartsWith($destination + '\', 'OrdinalIgnoreCase')) {
                Die 'engine migration target is outside this install'
            }
            New-Item -ItemType Directory -Force -Path $engineDir | Out-Null
            Copy-Item -LiteralPath $build.FullName -Destination $stage -Recurse -Force
            Move-Item -LiteralPath $stage -Destination $target
            Say "carried over engine $($engine.Name) $($build.Name) from $Source"
        }
    }
}

function Remove-Autostart {
    # **Only an autostart that belongs to this prefix.** The name is
    # fixed, so removing by name alone is how #10 stranded the first
    # install -- and how an acceptance run on a worker node would stop
    # the operator's real agent.
    $exe = Get-AutostartExecutable
    if ($exe -and -not (Test-RunsFromThisInstall $exe) -and -not $Migrate) {
        Die "the autostart on this machine runs $exe, which is not this install. Use -Migrate to take it over."
    }
    if (Get-AgentService) {
        Say "removing the Windows service"
        if (-not $IsElevated) { Die "removing the service needs Administrator" }
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        if (Test-Path $PyBin) {
            & $PyBin -m eugene_plexus_agent.winservice remove 2>&1 | Out-Null
        }
        else {
            & sc.exe delete $ServiceName | Out-Null
        }
    }
    if (Get-AgentTask) {
        Say "removing the scheduled task"
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    # The tray icon, which is a task of this install's too (R2.6) and
    # would otherwise sit in the notification area of every future
    # sign-in, pointing at a service that is gone. Removed unelevated
    # as well: it is the invoking user's own task, and its whole point
    # is that it needs no Administrator.
    if (Get-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue) {
        Say "removing the tray icon's logon task"
        Stop-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TrayTaskName -Confirm:$false
    }
    Remove-StartMenuShortcut
    # A task's process keeps running after the task is unregistered.
    # **Everything under the prefix, not only the venv** (2026-09-26): a
    # venv's python.exe is a launcher, and the interpreter it starts runs
    # from `pythons\`, as does every engine under `engines\`. Matching the
    # venv alone left those holding files open, and the move below failed
    # on them.
    Stop-ProcessUnder -Paths @($Prefix)
}

# **A rename, never a copy** (measured 2026-09-26). `Move-Item` on a
# folder holding a file another process has open fails AFTER creating the
# destination, and a second attempt then moves the folder INTO that empty
# directory rather than renaming it. `Directory.Move` renames or changes
# nothing. Also the seam the Pester suite guards: no test may move a
# folder outside the temp directory.
function Move-Folder {
    param([string]$From, [string]$To)
    [IO.Directory]::Move($From, $To)
}

# What went wrong, without .NET's "Exception calling ... with 2 argument(s)".
function Get-ErrorText {
    param($ErrorRecord)
    $e = $ErrorRecord.Exception
    while ($e.InnerException) { $e = $e.InnerException }
    return $e.Message
}

# Stop every process whose program lives under one of `Paths`, and wait
# for them to go. Matched by the program's path, so nothing else on the
# machine can be caught by a name that happens to match.
function Stop-ProcessUnder {
    param([string[]]$Paths)
    $roots = @($Paths | Where-Object { $_ } | ForEach-Object {
            [IO.Path]::GetFullPath($_).TrimEnd('\') + '\'
        })
    if ($roots.Count -eq 0) { return }
    $isUnder = {
        param($Process)
        $exe = $Process.ExecutablePath
        if (-not $exe) { return $false }
        foreach ($root in $roots) {
            if ($exe.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return $true }
        }
        return $false
    }
    $running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { & $isUnder $_ })
    foreach ($process in $running) {
        Say "stopping $($process.Name) (pid $($process.ProcessId))"
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($running.Count -eq 0) { return }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        $left = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { & $isUnder $_ })
        if ($left.Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    }
}

# --- a join takes over whatever Eugene is already here ------------------
# **Someone running a join command with a valid token knows what they are
# doing** (Troy, 2026-09-26). Getting Amish_Station into a new install took
# an afternoon of refusals, each correct on its own terms: a second
# install, a service conversion, an install someone had set up, a token
# that expired while the refusals were being read. So `-Join` no longer
# asks what to do with what it finds. It stops every Eugene install on the
# machine, moves each folder aside -- nothing is deleted -- installs fresh
# and joins. If anything fails before the join succeeds, every install it
# moved is put back and whatever was running is started again, so a bad
# token leaves the machine exactly as it was.

# The variables an install sets, in both scopes. One list, because the
# uninstall clears these and a join sets them aside and puts them back.
# The config-file variable is named once so the Pester suite can point
# discovery at a name of its own: on a developer's machine the real one
# names a live install.
$ConfigVariable = "EUGENE_PLEXUS_AGENT_CONFIG_FILE"
$BindHostVariable = "EUGENE_PLEXUS_AGENT_BIND_HOST"
$EngineRootVariable = "EUGENE_PLEXUS_AGENT_ENGINE_ROOT"
$InstallVariables = @($ConfigVariable, $BindHostVariable,
    "EUGENE_PLEXUS_AGENT_BIND_PORT", $EngineRootVariable,
    "EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS")

function Test-LooksLikeInstall {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
    foreach ($marker in @("agent.yaml", "node.yaml", "venv", "bin\uv.exe")) {
        if (Test-Path -LiteralPath (Join-Path $Path $marker)) { return $true }
    }
    return $false
}

function Test-UnderProgramData {
    param([string]$Path)
    if (-not $Path -or -not $env:ProgramData) { return $false }
    $root = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\') + '\'
    return [IO.Path]::GetFullPath($Path).StartsWith($root, [StringComparison]::OrdinalIgnoreCase)
}

# Every Eugene install on this machine, the autostart's first. Each is a
# prefix: where the autostart runs from, where either scope's config-file
# variable points, and the two default locations. `$Prefix` is included
# when it holds anything at all, because a join installs there and must
# start from an empty folder; the others only when they hold an install.
function Get-EugeneInstall {
    $seen = New-Object Collections.ArrayList
    $consider = {
        param([string]$Path, [bool]$AnyContent)
        if (-not $Path) { return }
        try { $full = [IO.Path]::GetFullPath($Path).TrimEnd('\') } catch { return }
        if ($seen -contains $full) { return }
        if (-not (Test-Path -LiteralPath $full -PathType Container)) { return }
        $holds = if ($AnyContent) {
            [bool](Get-ChildItem -LiteralPath $full -Force -ErrorAction SilentlyContinue |
                Select-Object -First 1)
        }
        else { Test-LooksLikeInstall $full }
        if ($holds) { [void]$seen.Add($full) }
    }
    $exe = Get-AutostartExecutable
    # <prefix>\venv\Scripts\<exe> -- three levels up is the prefix.
    if ($exe) { & $consider (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $exe))) $false }
    foreach ($scope in @("User", "Machine")) {
        $cfg = [Environment]::GetEnvironmentVariable($ConfigVariable, $scope)
        if ($cfg) { & $consider (Split-Path -Parent $cfg) $false }
    }
    & $consider $Prefix $true
    & $consider (Join-Path $env:ProgramData "EugenePlexus") $false
    & $consider (Join-Path $env:LOCALAPPDATA "EugenePlexus") $false
    return $seen.ToArray()
}

# Seams, so the Pester suite can drive the set-aside and the restore
# without a real service on the machine running it.
function Remove-AgentServiceRegistration { & sc.exe delete $ServiceName | Out-Null }
function Get-AgentServiceEnvironment {
    (Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName" `
        -Name Environment -ErrorAction SilentlyContinue).Environment
}
function Get-InstalledPort {
    # The port an install's autostart already starts the agent on. -Update
    # keeps it, and must not take it from its own environment: the update
    # runs from a task Windows builds an environment for, and a service
    # reads its port from its own registry entry, not from that.
    if (Get-AgentService) {
        foreach ($line in @(Get-AgentServiceEnvironment)) {
            if ("$line" -match '^EUGENE_PLEXUS_AGENT_BIND_PORT=(\d+)$') { return [int]$Matches[1] }
        }
        return 8079
    }
    $account = [Environment]::GetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", "User")
    if ($account -match '^\d+$') { return [int]$account }
    return 8079
}
function Register-AgentServiceFrom {
    param([string]$ServicePrefix, [string[]]$Environment)
    $python = Join-Path $ServicePrefix "venv\Scripts\python.exe"
    & $python -m eugene_plexus_agent.winservice install 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "registering it exited $LASTEXITCODE" }
    & sc.exe config $ServiceName start= auto | Out-Null
    & sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null
    if ($Environment) {
        New-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName" `
            -Name Environment -PropertyType MultiString -Value $Environment -Force | Out-Null
    }
    Grant-ServiceControl | Out-Null
}

# Stop every install in `Installs` and move each one aside. Returns what
# `Restore-EugeneInstall` needs to put the machine back. Nothing on disk is
# deleted: each folder becomes `<prefix>.replaced-<time>`.
function Suspend-EugeneInstall {
    param([string[]]$Installs)
    $record = [pscustomobject]@{
        Moved       = New-Object Collections.ArrayList
        Service     = $null
        AgentTask   = $null
        TrayTask    = $null
        Links       = New-Object Collections.ArrayList
        Variables   = New-Object Collections.ArrayList
        FreshPrefix = $Prefix
        Restored    = $false
    }
    $installs = @($Installs | Where-Object { $_ })
    $service = Get-AgentService
    $adminOnly = $service -or @($installs | Where-Object { Test-UnderProgramData $_ }).Count -gt 0
    if ($adminOnly -and -not $IsElevated) {
        Die @"
Eugene is already installed on this machine as a Windows service, and
       moving it aside needs Administrator. Run this command again from an
       elevated PowerShell, or without -NoService.
"@
    }
    $stamp = Get-Date -Format yyyyMMddHHmmss
    try {
        # The autostart and the icon first, remembered so they can come back.
        if ($service) {
            $exe = Get-AutostartExecutable
            $record.Service = [pscustomobject]@{
                Prefix      = if ($exe) { Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $exe)) } else { $null }
                Environment = @(Get-AgentServiceEnvironment)
                Running     = ($service.Status -eq 'Running')
            }
            Say "stopping the $ServiceName service"
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            Remove-AgentServiceRegistration
        }
        foreach ($name in @($TaskName, $TrayTaskName)) {
            $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            if (-not $task) { continue }
            $saved = [pscustomobject]@{
                Xml     = (Export-ScheduledTask -TaskName $name)
                Running = ($task.State -eq 'Running')
            }
            if ($name -eq $TaskName) { $record.AgentTask = $saved } else { $record.TrayTask = $saved }
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
        }
        foreach ($programs in @(
                (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs"),
                (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
            $link = Join-Path $programs "Eugene Plexus.lnk"
            if (-not (Test-Path -LiteralPath $link)) { continue }
            $backup = Join-Path ([IO.Path]::GetTempPath()) ("eugene-plexus-" + [guid]::NewGuid().ToString('N') + ".lnk")
            Copy-Item -LiteralPath $link -Destination $backup -Force
            Remove-Item -LiteralPath $link -Force
            [void]$record.Links.Add([pscustomobject]@{ Path = $link; Backup = $backup })
        }

        # Its engines too: a per-user install keeps them outside the prefix.
        $engines = [Environment]::GetEnvironmentVariable($EngineRootVariable, "User")
        if (-not $engines -and $env:USERPROFILE) { $engines = Join-Path $env:USERPROFILE ".eugene-plexus\engines" }
        Stop-ProcessUnder -Paths (@($installs) + @($engines))

        foreach ($scope in @("User", "Machine")) {
            if ($scope -eq "Machine" -and -not $IsElevated) { continue }
            foreach ($name in $InstallVariables) {
                $value = [Environment]::GetEnvironmentVariable($name, $scope)
                if ($null -eq $value) { continue }
                [void]$record.Variables.Add([pscustomobject]@{ Scope = $scope; Name = $name; Value = $value })
                [Environment]::SetEnvironmentVariable($name, $null, $scope)
            }
        }

        foreach ($path in $installs) {
            $aside = "$path.replaced-$stamp"
            $attempt = 0
            while ($true) {
                try {
                    Move-Folder -From $path -To $aside
                    break
                }
                catch {
                    # A process that was just stopped can hold a file for a
                    # moment after it is gone.
                    $attempt += 1
                    if ($attempt -ge 8) { throw "could not move $path aside: $(Get-ErrorText $_)" }
                    Start-Sleep -Milliseconds 500
                }
            }
            [void]$record.Moved.Add([pscustomobject]@{ From = $path; To = $aside })
            Say "set aside the install at $path; nothing deleted"
            Write-Host "    it is now at $aside"
        }
    }
    catch {
        $why = $_.Exception.Message
        Restore-EugeneInstall $record | Out-Null
        Die @"
$why
       Nothing was installed, and whatever was here is back as it was. Close
       anything that has files open in that folder, then run this again.
"@
    }
    return $record
}

# Put the machine back as `Suspend-EugeneInstall` found it: the new
# install removed, every folder moved back, the variables, the Start menu
# entry, the service or task registered again and started if it was
# running. Never throws; what it could not do, it says, with where the
# files are.
function Restore-EugeneInstall {
    param($Record)
    if (-not $Record -or $Record.Restored) { return $true }
    $Record.Restored = $true
    $problems = New-Object Collections.ArrayList

    $fresh = $Record.FreshPrefix
    if ($fresh -and (Test-Path -LiteralPath $fresh)) {
        # Only a folder this run made. `FreshPrefix` is $Prefix, which was
        # either moved aside above or did not exist, so what is there now
        # is the new install and nothing a person put there.
        $exe = Get-AutostartExecutable
        if ($exe -and $exe.StartsWith($fresh.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            Remove-AgentServiceRegistration
        }
        Stop-ProcessUnder -Paths @($fresh)
        try { Remove-Item -LiteralPath $fresh -Recurse -Force -ErrorAction Stop }
        catch { [void]$problems.Add("could not remove the new install at $fresh ($($_.Exception.Message))") }
    }

    for ($i = $Record.Moved.Count - 1; $i -ge 0; $i--) {
        $move = $Record.Moved[$i]
        if (Test-Path -LiteralPath $move.From) {
            [void]$problems.Add("$($move.From) exists again, so the old install was left at $($move.To)")
            continue
        }
        try {
            Move-Folder -From $move.To -To $move.From
            Say "put back the Eugene install at $($move.From)"
        }
        catch { [void]$problems.Add("could not move $($move.To) back to $($move.From) ($(Get-ErrorText $_))") }
    }
    foreach ($variable in $Record.Variables) {
        try { [Environment]::SetEnvironmentVariable($variable.Name, $variable.Value, $variable.Scope) }
        catch { [void]$problems.Add("could not restore $($variable.Name) ($($variable.Scope))") }
    }
    foreach ($link in $Record.Links) {
        try {
            Copy-Item -LiteralPath $link.Backup -Destination $link.Path -Force -ErrorAction Stop
            Remove-Item -LiteralPath $link.Backup -Force -ErrorAction SilentlyContinue
        }
        catch { [void]$problems.Add("could not restore the Start menu entry $($link.Path)") }
    }
    if ($Record.Service -and $Record.Service.Prefix) {
        try {
            Register-AgentServiceFrom -ServicePrefix $Record.Service.Prefix -Environment $Record.Service.Environment
            if ($Record.Service.Running) {
                Start-Service -Name $ServiceName -ErrorAction Stop
                Say "the $ServiceName service is running again"
            }
        }
        catch {
            [void]$problems.Add("could not register the $ServiceName service again ($($_.Exception.Message)); re-run the installer with -Prefix '$($Record.Service.Prefix)' to do it")
        }
    }
    foreach ($pair in @(@($TaskName, $Record.AgentTask), @($TrayTaskName, $Record.TrayTask))) {
        $name = $pair[0]
        $saved = $pair[1]
        if (-not $saved) { continue }
        try {
            Register-ScheduledTask -TaskName $name -Xml $saved.Xml -ErrorAction Stop | Out-Null
            if ($saved.Running) { Start-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue }
        }
        catch { [void]$problems.Add("could not register the $name task again ($($_.Exception.Message))") }
    }
    foreach ($problem in $problems) { Warn $problem }
    return ($problems.Count -eq 0)
}

# The Visual C++ runtime llama.cpp's Windows build links against (see step
# 4c). Microsoft's own permanent links, one per processor architecture.
$VcRedistArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
$VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.$VcRedistArch.exe"

function Get-NativeSystemDirectory {
    # A 32-bit PowerShell sees SysWOW64 as System32; the engine is 64-bit.
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        return (Join-Path $env:windir "Sysnative")
    }
    return [Environment]::GetFolderPath("System")
}

function Test-VcRuntime {
    $system = Get-NativeSystemDirectory
    foreach ($dll in @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")) {
        if (-not (Test-Path -LiteralPath (Join-Path $system $dll))) { return $false }
    }
    return $true
}

# Download Microsoft's redistributable, refuse it unless Microsoft signed it,
# and run it silently. Throws, with what went wrong, on any failure.
function Install-VcRuntime {
    $file = Join-Path ([IO.Path]::GetTempPath()) "eugene-plexus-vc_redist.$VcRedistArch.exe"
    try {
        Invoke-WebRequest -Uri $VcRedistUrl -OutFile $file -UseBasicParsing
        $signature = Get-AuthenticodeSignature -LiteralPath $file
        if ($signature.Status -ne "Valid" -or
            "$($signature.SignerCertificate.Subject)" -notmatch "O=Microsoft Corporation") {
            throw "the file from $VcRedistUrl is not signed by Microsoft ($($signature.Status))"
        }
        $run = Start-Process -FilePath $file -ArgumentList @("/install", "/quiet", "/norestart") -Wait -PassThru
        # 0: installed. 1638: a newer one is already there. 3010: installed,
        # and Windows wants a restart for something else it replaced.
        if ($run.ExitCode -notin @(0, 1638, 3010)) {
            throw "its installer exited with code $($run.ExitCode)"
        }
    }
    finally {
        Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
    }
}

# After a join, where each old install went -- said last, so it is seen.
function Show-SetAsideNote {
    if (-not $SetAside -or -not $JoinCommitted) { return }
    foreach ($move in $SetAside.Moved) {
        Say "the install that was here before is kept at $($move.To)"
        Write-Host "    Delete it once this machine is working."
    }
}

# **An install from alpha.2 or earlier cannot be upgraded, and says so**
# (Troy, 2026-09-26: alpha.3 requires a fresh install). Per-node token
# keys (2026-09-25) deleted the install-wide signing key rather than
# converting it, so an old install upgraded in place does not come back:
# its control root cannot read its own log, and sign-in says the root
# "did not answer" -- which sent this project's own NAS hunting for a
# network fault. The marker is the old key itself: `node.yaml` held the
# install's `signingKey`, and nothing written since does. A join never
# gets here; it sets the old install aside instead.
function Assert-UpgradeableInstall {
    $identity = Join-Path $Prefix "node.yaml"
    if (-not (Test-Path -LiteralPath $identity)) { return }
    $text = try { [IO.File]::ReadAllText($identity) } catch { "" }
    if ($text -notmatch '(?m)^signingKey:') { return }
    Die @"
the Eugene install at $Prefix
       is from alpha.2 or earlier, and this version cannot upgrade it: how
       machines prove who they are changed, and the old keys do not carry
       over. Start fresh: remove it (its files are kept, moved aside), then
       run this command again.
         & ([scriptblock]::Create((irm $InstallerUrl))) -Uninstall
       No model file is deleted. Any in its own models folder move aside
       with it; the uninstall says where, so you can move them into the new
       install's. You will choose a new passphrase, and machines that were
       joined to it will need to join again.
"@
}

# --- -Detect ----------------------------------------------------------
# Read-only. Prints what this machine already holds and what an ordinary
# run would do about it, so the answer to "is this a second install?" is
# available without running one.
if ($Detect) {
    $clean = Show-InstallVerdict
    # **"What would happen" has to include what it costs.** `-Detect` is
    # the switch for asking before doing, and until 2026-09-19 the one
    # consequence an operator cannot undo -- being asked for a passphrase
    # they may not have written down -- was printed only by the install
    # itself, seconds before charging it. Same text, same predicate, one
    # step earlier.
    Show-MigrationConsequences -ReportOnly
    # **`$global:LASTEXITCODE`, never `exit`** -- found while R2.6 was
    # reading this file. The rule is stated forty lines above and this
    # line broke it: `-Detect` is only reachable as
    # `& ([scriptblock]::Create((irm ...))) -Detect`, which runs in the
    # CALLER'S process, so `exit 3` closed the operator's terminal in
    # exactly the case the switch exists to report. Under
    # `powershell -File` the variable is the process exit code, which is
    # what a script checking this wants; in a live shell it is a
    # variable, which is what a person wants.
    if (-not $clean -and -not $Migrate) { $global:LASTEXITCODE = 3 }
    return
}

# --- uninstall --------------------------------------------------------
if ($Uninstall) {
    # **Wherever the install is** (2026-09-26). Run with no -Prefix, this
    # removes every Eugene install on the machine and asks for
    # Administrator itself when one of them needs it. Before, the prefix
    # came from how the shell was started: an ordinary PowerShell looked
    # only in %LOCALAPPDATA% and said "nothing installed" with a service
    # install sitting in %ProgramData%. `-Prefix` still names exactly one.
    $targets = @($Prefix)
    if (-not $PrefixGiven) {
        $targets = @(Get-EugeneInstall)
        if ($targets.Count -eq 0) {
            Say "nothing to remove: no Eugene install in $(Join-Path $env:ProgramData 'EugenePlexus'),"
            Write-Host "    $(Join-Path $env:LOCALAPPDATA 'EugenePlexus'), or behind a $ServiceName service or task."
            return
        }
        $needsAdmin = [bool](Get-AgentService) -or
        @($targets | Where-Object { Test-UnderProgramData $_ }).Count -gt 0
        if ($needsAdmin -and -not $IsElevated) {
            if ($NoElevate) {
                Die "removing the Eugene service needs Administrator, and -NoElevate was given. Run this from an elevated PowerShell."
            }
            Say "removing Eugene needs Administrator -- asking for it now"
            Invoke-ElevatedInstaller -ScriptText $MyInvocation.MyCommand.ScriptBlock.ToString() -Parameters $PSBoundParameters
            return
        }
        # An autostart whose install has gone: nothing below owns it.
        $orphan = Get-AutostartExecutable
        if ($orphan -and -not (Test-Path -LiteralPath $orphan)) {
            $Venv = Split-Path -Parent (Split-Path -Parent $orphan)
            Remove-Autostart
        }
    }
    foreach ($target in $targets) {
        $Prefix = $target
        $Venv = Join-Path $Prefix "venv"
        $PyBin = Join-Path $Venv "Scripts\python.exe"
        $Config = Join-Path $Prefix "agent.yaml"
        # **Deliberately no `Assert-OwnInstall` here.** Removing a named
        # prefix is a legitimate thing to do on a machine whose autostart
        # belongs to a different install -- it is, in fact, exactly how the
        # operator recovers from #10. What must not happen is taking that
        # other install's autostart away, and `Remove-Autostart` is where
        # that is refused. With no -Prefix the autostart's own install comes
        # first, so by the time any other is removed there is none left.
        Remove-Autostart
        # The installer sets the config path; the installer takes it back.
        # Found by checking after an acceptance run: the User-scope variable
        # outlived the uninstall and would have pointed the next
        # hand-started agent at a prefix that no longer exists.
        #
        # BIND_HOST is still cleared even though this installer stopped
        # setting it on 2026-09-11, because every install made before then
        # did -- and that variable is account-wide, so leaving it behind
        # keeps widening the bind of every other agent on the account long
        # after this one is gone.
        # **Only the variables that pointed at THIS prefix.** They are
        # account-wide, so clearing them while uninstalling some other
        # prefix would unpoint a live install -- which is the same mistake
        # as #10, one scope over.
        $names = $InstallVariables
        foreach ($scope in @("User", "Machine")) {
            if ($scope -eq "Machine" -and -not $IsElevated) { continue }
            $cfg = [Environment]::GetEnvironmentVariable($ConfigVariable, $scope)
            $mine = $cfg -and ([IO.Path]::GetFullPath($cfg) -eq [IO.Path]::GetFullPath($Config))
            # BIND_HOST is cleared whatever it points at: this installer
            # stopped setting it on 2026-09-11, every install made before
            # then did, and an account-wide widened bind outliving the
            # install that set it is the thing that made it a defect.
            if (-not $mine) {
                [Environment]::SetEnvironmentVariable($BindHostVariable, $null, $scope)
                continue
            }
            foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $null, $scope) }
        }

        # **Two keyring entries, not one** (review 6.3 #31). The agent
        # stores its master key under `eugene-plexus-agent` and the control
        # root stores the install's signing key under
        # `eugene-plexus-control`, each scoped by a fingerprint of this
        # install's master salt (S0). The salt goes into the `.removed-`
        # directory with everything else, so after this runs nothing can
        # work out what to delete -- it has to happen here or not at all.
        if ((Test-Path $PyBin) -and (Test-Path $Config)) {
            Say "clearing this install's OS keyring entries"
            $drop = @'
import base64, hashlib, sys

try:
    import keyring
    import yaml
except Exception as exc:
    print(f"  could not open the OS keyring ({exc}); entries left in place")
    raise SystemExit(0)

try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8").read()) or {}
    salt = ((doc.get("auth") or {}).get("masterSalt")) or ""
except Exception as exc:
    print(f"  could not read agent.yaml ({exc}); keyring entries left in place")
    raise SystemExit(0)

names = ["master-key"]
if salt:
    try:
        names.append("master-key-" + hashlib.sha256(base64.b64decode(salt)).hexdigest()[:12])
    except Exception:
        pass

removed = 0
for service in ("eugene-plexus-agent", "eugene-plexus-control"):
    for username in names:
        try:
            if keyring.get_password(service, username) is not None:
                keyring.delete_password(service, username)
                print(f"  removed the {service} keyring entry")
                removed += 1
        except Exception:
            pass
if removed == 0:
    print("  no keyring entries belonged to this install")
'@
            $dropFile = Join-Path $env:TEMP "eugene-plexus-uninstall-keyring.py"
            [IO.File]::WriteAllText($dropFile, $drop, (New-Object Text.UTF8Encoding $false))
            & $PyBin $dropFile $Config
            Remove-Item $dropFile -Force -ErrorAction SilentlyContinue
        }

        # **The node-local model copy directory is ours and is not under the
        # prefix** (review 6.3 #31). The agent creates it, fills it with
        # whole model files and deletes from it; a Library folder is the
        # operator's and is never written to. So it is the one thing an
        # uninstall can offer to remove -- offered, not taken, because tens
        # of gigabytes is not a thing to delete on somebody's behalf.
        $purge = $PurgeDownloads -or $PurgeModelCopies
        $copyDir = $null
        if (Test-Path $Config) {
            $line = Select-String -LiteralPath $Config -Pattern '^modelCopyDir:\s*(.+)$' |
            Select-Object -First 1
            if ($line) {
                $raw = $line.Matches[0].Groups[1].Value.Trim()
                # `yaml.safe_dump` writes a Windows path as a plain scalar,
                # backslashes and all. A double-quoted one is the only form
                # that escapes them.
                if ($raw.StartsWith('"')) { $copyDir = $raw.Trim('"').Replace('\\', '\') }
                else { $copyDir = $raw.Trim("'") }
            }
        }
        if ($copyDir -and (Test-Path $copyDir)) {
            $bytes = (Get-ChildItem -LiteralPath $copyDir -Recurse -File -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum
            $gib = if ($bytes) { [math]::Round($bytes / 1GB, 1) } else { 0 }
            if ($purge) {
                Say "removing this node's model copies at $copyDir ($gib GiB)"
                Remove-Item -LiteralPath $copyDir -Recurse -Force -ErrorAction SilentlyContinue
            }
            else {
                Say "this node's model copies are at $copyDir ($gib GiB) -- they are copies, so"
                Say "  deleting them loses nothing. Re-run with -PurgeDownloads, or remove it yourself."
            }
        }
        elseif ($copyDir) {
            Say "no model copies on disk (modelCopyDir was $copyDir)"
        }

        # **The engine store is ours too, and it is not under the prefix.**
        # The agent downloads llama.cpp builds into `~/.eugene-plexus/engines`
        # (or wherever EUGENE_PLEXUS_AGENT_ENGINE_ROOT says -- which an
        # elevated install now pins under the prefix, so this is the
        # per-user case), keeps two of them, and nothing else on the machine
        # writes there.
        $engineRootPath = $env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT
        if (-not $engineRootPath) {
            $engineRootPath = Join-Path $env:USERPROFILE ".eugene-plexus\engines"
        }
        if (Test-Path $engineRootPath) {
            $eb = (Get-ChildItem -LiteralPath $engineRootPath -Recurse -File -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum
            $egib = if ($eb) { [math]::Round($eb / 1GB, 1) } else { 0 }
            if ($purge) {
                Say "removing the engine store at $engineRootPath ($egib GiB)"
                Remove-Item -LiteralPath $engineRootPath -Recurse -Force -ErrorAction SilentlyContinue
            }
            else {
                Say "the engine builds this install downloaded are at $engineRootPath ($egib GiB) --"
                Say "  re-run with -PurgeDownloads, or remove it yourself."
            }
        }
        if (Test-Path $Prefix) {
            # agent.yaml and node.yaml are the install's identity and logs\
            # are the only record of what it did. Move the prefix aside
            # rather than delete it: an uninstall must not be the thing that
            # loses an enrollment.
            $keep = "$Prefix.removed-$(Get-Date -Format yyyyMMddHHmmss)"
            try { Move-Folder -From $Prefix -To $keep }
            catch {
                Die @"
could not move $Prefix aside: $(Get-ErrorText $_)
       A program still has files open in it. Close it, or restart Windows,
       then run -Uninstall again. Its service and autostart are already off.
"@
            }
            Say "removed the install at $Prefix."
            Write-Host "    Its config and logs are at $keep -- delete it when you are sure."
            # A service install's default models folder is inside the prefix,
            # so its models moved too. Say where, before anyone deletes it.
            $movedModels = Join-Path $keep "models"
            if (Get-ChildItem -LiteralPath $movedModels -Recurse -File -ErrorAction SilentlyContinue |
                Select-Object -First 1) {
                Say "the models that were in $(Join-Path $Prefix 'models') moved with it, to"
                Write-Host "    $movedModels"
                Write-Host "    Move them into a new install's models folder to use them there."
            }
        }
        else {
            Say "nothing installed at $Prefix"
        }
    }
    return
}

# Explain ownership and migration in the calling terminal before UAC. An
# elevated -File window closes on failure, taking its useful refusal with it.
# The elevated run repeats these read-only checks against its own context.
if ($Isolated) {
    # A fresh child directory inside the real install is not isolated either.
    $other = Get-OtherInstall
    if ($other) {
        $candidateRoot = [IO.Path]::GetFullPath($Prefix).TrimEnd('\') + '\'
        $installedRoot = [IO.Path]::GetFullPath($other.Prefix).TrimEnd('\') + '\'
        if ($candidateRoot.StartsWith($installedRoot, [StringComparison]::OrdinalIgnoreCase) -or
            $installedRoot.StartsWith($candidateRoot, [StringComparison]::OrdinalIgnoreCase)) {
            Die "the isolated prefix must be outside the existing install"
        }
    }
}
elseif (-not $Join) {
    # A join asks neither: it sets every install aside below, so there is
    # no second install to refuse and no conversion to warn about.
    Assert-OwnInstall
    Show-MigrationConsequences
}

# Capture the invoking user's legacy engine store before elevation. A retry
# after migration must still recover it even when the service already belongs
# to the new prefix. User installs historically kept builds outside the prefix.
if ($Migrate -and $WantsService -and -not $MigrateEngineRoot) {
    $MigrateEngineRoot = [Environment]::GetEnvironmentVariable('EUGENE_PLEXUS_AGENT_ENGINE_ROOT', 'User')
    if (-not $MigrateEngineRoot) { $MigrateEngineRoot = Join-Path $env:USERPROFILE '.eugene-plexus\engines' }
    $PSBoundParameters['MigrateEngineRoot'] = $MigrateEngineRoot
}

# --- 0a. Administrator, once, or say plainly why not ------------------
# `SC_MANAGER_CREATE_SERVICE` is granted to nobody but Administrators,
# so "the service is the default" and "no Administrator needed" cannot
# both be true. Asking is honest; asking TWICE, or silently building a
# second install because the first ask was declined, is not -- and the
# second of those is exactly review 6.1 #10, which R2.2 fixed and which
# this must not reintroduce from the other direction.
#
# Re-launching needs the script's own text, and under
# `irm ... | iex` there is no file on disk to re-run. So the text is
# written to a temp file and handed to a new elevated PowerShell with
# every argument this run received. `-NoElevate` refuses the relaunch
# and explains, for a shell where UAC cannot appear at all.
if ($WantsService -and -not $IsElevated) {
    if ($NoElevate) {
        Die @"
a Windows service needs Administrator, and -NoElevate was given.
    Either start an elevated PowerShell and run this again, or install
    the per-user version, which starts when you log in rather than at
    boot:
        ... -NoService
"@
    }
    Say "a Windows service needs Administrator -- asking for it now"
    Invoke-ElevatedInstaller -ScriptText $MyInvocation.MyCommand.ScriptBlock.ToString() -Parameters $PSBoundParameters
    return
}

# --- 1. uv ------------------------------------------------------------

# **How a failed run ends** (2026-09-26). A PowerShell trap covers its
# whole scope wherever it is written, so this one also handles every
# `Die` above it. It sits here, below the `# --- 1. uv` line, because
# install-preflight.Tests.ps1 runs the text ABOVE that line on its own
# and asserts that each refusal throws.
#
#   * A refusal `Die` made has already printed its message. Stop there:
#     no ErrorRecord, no "At line:145 char:71", no FullyQualifiedErrorId.
#   * Anything else is a defect or something the machine threw. Say it in
#     two lines -- what and where -- instead of the raw record.
#
# Then end the run without closing the person's terminal. Run as a file
# (`powershell -File`, and the elevated child), `exit 1` ends only that
# script and is the exit code every caller reads. Run as a scriptblock at
# a prompt, `exit` would close the prompt, so it returns with
# $LASTEXITCODE set instead -- the rule this file already keeps for
# `-Detect`. The global flag is what the elevated runner checks.
trap {
    $global:EugenePlexusInstallFailed = $true
    if ($_.FullyQualifiedErrorId -notlike 'EugenePlexusInstallFailed*') {
        Write-Host "error: the installer stopped unexpectedly: $($_.Exception.Message)" -ForegroundColor Red
        $where = $_.InvocationInfo
        if ($where -and $where.ScriptLineNumber) {
            Write-Host "       at line $($where.ScriptLineNumber): $($where.Line.Trim())" -ForegroundColor Red
        }
        Write-Host "       This is a defect in the installer; please report it with this output." -ForegroundColor Red
    }
    # A join that set installs aside and did not get as far as joining
    # puts them back, whatever stopped it (see Suspend-EugeneInstall).
    if ($SetAside -and -not $SetAside.Restored -and -not $JoinCommitted) {
        Restore-EugeneInstall $SetAside | Out-Null
        Write-Host "       This machine is back as it was." -ForegroundColor Red
    }
    if ($PSCommandPath) { exit 1 }
    $global:LASTEXITCODE = 1
    return
}

# --- 0b. what is already here -------------------------------------------
# Below the trap, so a refusal ends cleanly, and below `# --- 1. uv`, so
# the preflight suite, which runs the text above that line, never sets a
# real install aside.
$SetAside = $null
$JoinCommitted = $false
if ($Join -and -not $Isolated) {
    if (-not $Token) { Die "-Join needs -Token (mint one at the control root: Nodes -> Add a node)" }
    $SetAside = Suspend-EugeneInstall -Installs (Get-EugeneInstall)
}
elseif (-not $Isolated) {
    Assert-UpgradeableInstall
}

Say "installing into $Prefix$(if ($WantsService) { ' (a Windows service: starts at boot)' } else { ' (per-user: starts when you log in)' })"
New-Item -ItemType Directory -Force -Path (Join-Path $Prefix "bin"), (Join-Path $Prefix "logs") | Out-Null
# Before anything else is written, so that nothing -- a venv, a
# node.yaml from -Join, a copied agent.yaml -- ever exists here with
# another account able to read or add to it. Run again after step 5,
# once the folders the service's doors open onto exist. Not on -Update:
# the install already has its permissions, and a run as SYSTEM would
# grant them to SYSTEM instead of the person.
if (-not $Update) { Protect-InstallDirectory -Path $Prefix -Service:$WantsService | Out-Null }

# Before uv, before the venv, before anything can read a config: if this
# run is taking over an install that lives somewhere else, its identity
# comes with it. A half-built prefix that already holds the right
# `node.yaml` is recoverable by re-running; one that gets a venv first
# and an identity never is a second install.
if ($Migrate) {
    $migrateFrom = Get-OtherInstall
    if ($migrateFrom) { Copy-InstallState -Source $migrateFrom.Prefix }
    if ($WantsService) { Copy-EngineBuilds -Source $MigrateEngineRoot }
}

if (Test-Path $UvExe) {
    Say "uv already present ($(& $UvExe --version))"
}
else {
    Say "fetching uv"
    # UV_UNMANAGED_INSTALL puts uv exactly here and edits no PATH and no
    # profile. The installer owns its own copy, so nothing the user
    # already has is touched and removing the prefix is complete.
    $env:UV_UNMANAGED_INSTALL = Join-Path $Prefix "bin"
    try {
        & ([scriptblock]::Create((Invoke-RestMethod https://astral.sh/uv/install.ps1))) *>&1 | Out-Null
    }
    catch {
        Die "could not install uv from https://astral.sh/uv/install.ps1 -- $($_.Exception.Message)"
    }
    if (-not (Test-Path $UvExe)) { Die "uv did not land at $UvExe" }
    Say "uv $((& $UvExe --version) -replace '^uv ')"
}

# Keep uv's downloaded interpreters inside the prefix too: one directory
# to remove.
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Prefix "pythons"

# --- 2. venv ----------------------------------------------------------
if (Test-Path $PyBin) {
    Say "virtualenv already present"
}
else {
    Say "creating a Python $PyVersion virtualenv (uv downloads the interpreter; none is required on this machine)"
    # `only-managed` rather than uv's default, which prefers a matching
    # interpreter already on the machine -- as this box has, which made
    # the sentence above false the first time this ran. It would also
    # tie the install to a Python the user can upgrade or remove out
    # from under it.
    #
    # No `*>&1` on a native command: in Windows PowerShell 5.1 that
    # wraps each stderr line in an ErrorRecord and, under
    # $ErrorActionPreference = "Stop", turns uv's ordinary progress
    # output into a terminating error. `-q` instead.
    Invoke-Native $UvExe @("venv", "-q", "--python", $PyVersion, "--python-preference", "only-managed", $Venv)
    if (-not (Test-Path $PyBin)) { Die "could not create a virtualenv at $Venv" }
}

# --- 3. packages ------------------------------------------------------
if (Test-Path $Config) {
    Warn "Before updating an initialized install, keep a stopped-install checkpoint: https://github.com/eugene-plexus/specs/blob/main/docs/recovery.md"
    Warn "Rollback restores matching software AND state; installing an older release does not undo data migrations."
}
# **Stop a running install before replacing its files.** The logon task
# and the service both execute `Scripts\eugene-plexus-agent.exe`, and a
# Windows process holds its own executable open, so `uv pip install`
# fails on an upgrade with "failed to remove file ... being used by
# another process" (os error 32). Found 2026-09-15 upgrading the live
# worker; the earlier upgrade that morning had passed only because the
# console script happened not to change. Linux has no such lock, which
# is why install.sh needs nothing here. The autostart is registered
# again in step 5 and the agent restarted in step 6, so a running
# install pauses across the upgrade rather than surviving it -- which is
# also what an upgrade of a supervised install means. (A join never
# finds one running: 0b set every install aside.)
if ($Update) {
    # **Only the autostart that runs THIS install.** The service and task
    # names are fixed, so without this an update pointed at any other
    # folder would stop this machine's real Eugene and re-point its service
    # at that folder -- the same guard Remove-Autostart keeps, for the same
    # reason.
    $exe = Get-AutostartExecutable
    if ($exe -and -not (Test-RunsFromThisInstall $exe)) {
        Die "the autostart on this machine runs $exe, which is not the install at $Prefix; -Update only updates the install its autostart runs"
    }
    # Stopped, never unregistered: the autostart, the tray icon and who may
    # start and stop the service all stay exactly as they are.
    Say "stopping the running agent so its files can be replaced"
    if (Get-AgentService) { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue }
    if (Get-AgentTask) { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue }
    Stop-ProcessUnder -Paths @($Prefix)
}
elseif (-not $Isolated -and ((Get-AgentTask) -or (Get-AgentService))) {
    Say "stopping the running agent so its files can be replaced"
    Remove-Autostart
}
Say "installing Eugene Plexus"
$specs = foreach ($repo in $DIST.Keys) {
    # Both extras resolve to the same `pywin32`, so naming both costs
    # nothing and the names stay meaningful: `service` is how the
    # install comes back after a reboot, `tray` is how a person turns it
    # off to play a game. `-NoTray` skips the task, not the dependency --
    # a person who changes their mind should not need a reinstall.
    $extra = if ($repo -eq "agent") { "[service,tray]" } else { "" }
    "$($DIST[$repo])$extra @ https://github.com/eugene-plexus/$repo/archive/$($PIN[$repo]).tar.gz"
}
Invoke-Native $UvExe (@("pip", "install", "-q", "--python", $PyBin) + $specs) "package install failed"

# --- 4. VERIFY --------------------------------------------------------
# "pip install exited 0" is not the claim. Three things can be true of a
# successful install and still leave a machine that serves nothing, and
# each has bitten this project:
#
#   * a component is importable, but `default_topology` looks for it
#     with `find_spec` against *this* interpreter, so an install into
#     the wrong one declares an empty control plane and supervises
#     nothing;
#   * `eugene-plexus-ui` can install with an empty payload, and the
#     symptom is a browser page rather than an installer error;
#   * the console script is what autostart executes, so its absence is
#     a failure that only appears at boot.
Say "checking the install"
$check = @'
import importlib.util, sys
from pathlib import Path

bad = []
for mod, what in [
    ("eugene_plexus_agent", "the node agent"),
    ("eugene_plexus_control", "the control root"),
    ("eugene_plexus_gateway", "the gateway"),
    ("eugene_plexus_inference_driver", "the inference driver"),
    ("eugene_plexus_library", "the model library"),
    ("eugene_plexus_tool_driver", "the web-search tool driver"),
]:
    if importlib.util.find_spec(mod) is None:
        bad.append(f"{what} ({mod}) is not importable from {sys.executable}")

try:
    import eugene_plexus_ui
    static = Path(eugene_plexus_ui.static_dir())
    if not (static / "index.html").is_file():
        bad.append(
            f"the web UI package installed but carries no build output ({static}); "
            "the UI pin must point at the `dist` branch, not `main`"
        )
except Exception as exc:
    bad.append(f"the web UI package is not usable: {exc}")

if importlib.util.find_spec("win32serviceutil") is None:
    bad.append("pywin32 is missing, so the Windows service cannot be registered")

for line in bad:
    print(f"  - {line}", file=sys.stderr)
raise SystemExit(1 if bad else 0)
'@
$checkFile = Join-Path $Prefix "install-check.py"
[IO.File]::WriteAllText($checkFile, $check)
& $PyBin $checkFile
$checkRc = $LASTEXITCODE
Remove-Item $checkFile -Force
if ($checkRc -ne 0) { Die "the install is incomplete -- see above" }
if (-not (Test-Path $AgentEx)) { Die "the eugene-plexus-agent command did not install" }
Say "all seven packages present, with a web UI"

# --- 4c. what the engine needs from Windows ---------------------------
# **llama.cpp's Windows build needs the Microsoft Visual C++ runtime and
# does not ship it** (found 2026-09-26). `llama-server.exe` and its DLLs
# import VCRUNTIME140.dll, VCRUNTIME140_1.dll and MSVCP140.dll. Those come
# from the Visual C++ Redistributable, which a freshly installed Windows
# does not have; Eugene's own Python carries its own copy, so everything
# else works. On a friend's newly reinstalled machine every model died at
# start, and the screen said only "crashed". The service install is
# elevated, so it installs the runtime from Microsoft. A per-user install
# says where to get it, because installing it needs Administrator.
if (-not (Test-VcRuntime)) {
    if ($Isolated) {
        Warn "this Windows has no Microsoft Visual C++ runtime, which llama.cpp needs. An isolated install changes nothing outside its folder, so it was not installed: $VcRedistUrl"
    }
    elseif ($IsElevated) {
        Say "installing the Microsoft Visual C++ runtime, which llama.cpp needs and this Windows does not have"
        try {
            Install-VcRuntime
            if (Test-VcRuntime) { Say "the Visual C++ runtime is installed" }
            else { Warn "the Visual C++ runtime installer finished, but its DLLs are not in place. llama.cpp will not start until they are: $VcRedistUrl" }
        }
        catch {
            Warn "could not install the Microsoft Visual C++ runtime ($(Get-ErrorText $_)). Eugene works, but llama.cpp will not start until it is installed: $VcRedistUrl"
        }
    }
    else {
        Warn "llama.cpp needs the Microsoft Visual C++ runtime, which this Windows does not have. Install it from $VcRedistUrl (it asks for Administrator), then start your models."
    }
}

# --- 4b. join, if this machine is a worker -----------------------------
# **The installer owns the one onboarding question, because this is the
# only moment a human is reliably present.** See the task action below
# for what went wrong when that was left to the agent.
if ($Join) {
    if (-not $Token) { Die "-Join needs -Token (mint one at the control root: Nodes -> Add a node)" }
    Say "joining $Join as a worker node"
    $joinArgs = @("join", "--control", $Join, "--token", $Token)
    if ($NodeName) { $joinArgs += @("--name", $NodeName) }
    if ($Advertise) { $joinArgs += @("--advertise", $Advertise) }
    $env:EUGENE_PLEXUS_AGENT_CONFIG_FILE = $Config
    & $AgentEx @joinArgs
    $joinCode = $LASTEXITCODE
    if ($joinCode -ne 0) {
        # **A failed join leaves the machine as it found it** (2026-09-26):
        # the new install is removed and every install 0b set aside is put
        # back and started. Then the reason, last, where it is read.
        Restore-EugeneInstall $SetAside | Out-Null
        if ($joinCode -eq 3) {
            # The agent's EXIT_TOKEN_REFUSED: unknown, expired or used.
            # Running the same command again cannot work, so it is never
            # what this says.
            Die @"
the control root refused the join token.
       Make a new one on its Nodes page (Add a node) and run the command
       it gives you. This machine is back as it was.
"@
        }
        Die @"
the join failed (see above). This machine is back as it was.
       Fix what it says, then run this command again.
"@
    }
    # The commit point: this machine now belongs to that install, so from
    # here a failure is reported, never undone by bringing the old one back.
    $JoinCommitted = $true
    if ($SetAside -and $WantsService) {
        # Save a download: engine builds are whole directories, and the
        # set-aside install's are exactly what this machine runs.
        foreach ($move in $SetAside.Moved) {
            Copy-EngineBuilds -Source (Join-Path $move.To "engines")
        }
    }

    # **A node that advertises an address must be reachable at it** --
    # found on the first enrollment between two genuinely separate
    # machines: the worker advertised its LAN address, bound 127.0.0.1,
    # and the control root could not call back, so union topology, idle
    # unload and start-on-demand would all have failed while enrollment
    # itself looked perfect. Enrollment is outbound; nothing here tests
    # the other direction.
    #
    # **There is deliberately nothing to set for it here.** The agent
    # enforces the rule itself since 6f88211: `join` has just written the
    # advertised address into node.yaml, and every start path -- the
    # scheduled task and the service both, via `build_server` -- reads it
    # back and binds 0.0.0.0 when it is not loopback.
    #
    # This installer used to set a User-scope
    # EUGENE_PLEXUS_AGENT_BIND_HOST here instead. That is account-wide on
    # Windows, so it widened the bind of every *other* agent the account
    # started, a local dev install included; and it turned a derived
    # decision into an explicit override, which by
    # `easy-default-expert-override` wins outright and so would have
    # outlived an unenrollment. A single-machine install still gets
    # loopback, which is the conservative default and the reason the rule
    # exists at all.
}
elseif ($Token) {
    Die "-Token needs -Join <control-root-url>"
}
elseif ($Advertise) {
    # **`-Advertise` was accepted on any invocation and honoured only in
    # the join branch** (review 6.2 #30), so the standalone case -- one
    # machine, no control root to join, an operator who already knows
    # the address their phone will use -- typed a flag that did nothing
    # and got an install on loopback. It is the same field
    # `PATCH /v1/config` sets and the Reach card writes, and setting it
    # before the first start is what `tailnet.md` has always said
    # matters: a listening socket is fixed for the life of a process.
    #
    # The agent derives its own bind host from this field
    # (`bind_host_for_advertised_node`), so writing it is the whole fix
    # -- there is deliberately no BIND_HOST variable set beside it, for
    # the reason the join block above gives.
    #
    # Written as plain YAML rather than through the install's Python:
    # on a fresh install agent.yaml does not exist yet, and the file is
    # a flat mapping of config keys, so replacing one top-level line is
    # exact. **No BOM** -- `yaml.safe_load` does not survive one, and
    # this repo has been bitten by `Set-Content -Encoding utf8` before.
    Say "advertising this machine at $Advertise"
    New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
    $lines = if (Test-Path $Config) {
        @(Get-Content -LiteralPath $Config | Where-Object { $_ -notmatch '^advertiseUrl:' })
    }
    else { @() }
    $lines += "advertiseUrl: $Advertise"
    [IO.File]::WriteAllText($Config, ($lines -join "`n") + "`n",
        (New-Object Text.UTF8Encoding $false))
}

# --- 5. autostart -----------------------------------------------------
$autostart = "none"
if ($Update) {
    # Before Set-ServiceBootstrap writes it back, and before the wait below.
    $Port = Get-InstalledPort
    if (Get-AgentService) {
        # `update`, not `install`: the service is there, and this refreshes
        # its host in the venv (pythonservice.exe and the DLLs beside it)
        # for the packages just installed.
        Say "refreshing the $ServiceName service"
        & $PyBin -m eugene_plexus_agent.winservice update
        if ($LASTEXITCODE -ne 0) { Die "could not refresh the service" }
        Set-ServiceBootstrap
        $autostart = "service"
    }
    elseif (Get-AgentTask) {
        $autostart = "task"
    }
    else {
        Warn "nothing starts this install automatically, so it was updated and left stopped"
    }
}
elseif (-not $NoService) {
    Remove-Autostart
    if ($WantsService) {
        Say "registering the $ServiceName service"
        # The agent stages its service host and DLLs inside this venv.
        # pywin32_postinstall is for global Python installs, not venvs.
        & $PyBin -m eugene_plexus_agent.winservice install
        if ($LASTEXITCODE -ne 0) { Die "could not register the service" }
        # The agent reads and writes under the prefix, so give it a
        # working directory rather than relying on %SystemRoot%\system32.
        & sc.exe config $ServiceName start= auto | Out-Null
        & sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", $Config, "Machine")
        # **A service runs as LocalSystem, whose home is
        # `C:\Windows\System32\config\systemprofile`** (review 6.1 #10).
        # Left alone, engine builds land there and the wizard's Models
        # screen -- which proposes `<home>\Eugene Models` from the
        # library's own `Home` entry -- offers a folder inside the
        # Windows directory. Both are pinned under the prefix instead,
        # which is where everything else this install owns already
        # lives, and both are cleared by -Uninstall.
        $engineRoot = Join-Path $Prefix "engines"
        $modelRoot = Join-Path $Prefix "models"
        New-Item -ItemType Directory -Force -Path $engineRoot, $modelRoot | Out-Null
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_ENGINE_ROOT", $engineRoot, "Machine")
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS", $modelRoot, "Machine")
        $env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT = $engineRoot
        $env:EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS = $modelRoot
        Set-ServiceBootstrap
        Grant-ServiceControl
        $autostart = "service"
        Say "Eugene will start at boot, before anyone signs in."
    }
    else {
        Say "registering the $TaskName logon task (no Administrator needed)"
        # **`--unattended`, and this is the line that needed it.** A
        # scheduled task runs its process WITH a console attached --
        # measured 2026-09-11, both stdin and stdout report isatty()
        # True inside one. So the agent's first-boot question printed
        # into a console nobody can see and blocked on input() forever:
        # nothing listening, no log written, and the task cheerfully
        # reporting Running. The installer asks instead (see -Join).
        $action = New-ScheduledTaskAction -Execute $AgentEx -Argument "--unattended" `
            -WorkingDirectory $Prefix
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Settings $settings -Description "Eugene Plexus node agent" | Out-Null
        $autostart = "task"
        Warn "this agent starts when you log in, not at boot: a reboot that lands on the lock screen leaves it off until somebody signs in at this keyboard. Re-run without -NoService to make it a service instead."
        # **The per-user layout says what it costs** (2026-09-24). A
        # program running as the agent's account can read its files, its
        # environment and its memory, and no ACL stops that; the service
        # runs under its own account, which does.
        Warn "Eugene runs as you, so any program you run as you -- an AI agent included -- can read its keys and take control of it. The Windows service (re-run without -NoService) runs under its own account instead."
    }
}

# venv\ and pythons\ exist now, and a service's models\ was made above.
if (-not $Update -and (Protect-InstallDirectory -Path $Prefix -Service:$WantsService)) {
    Say "this install's settings and keys are private to $(if ($WantsService) { 'the service and administrators' } else { 'you' })"
}

# --- 5b. the tray icon ------------------------------------------------
# **The logon task did not disappear, it changed job.** A service runs in
# session 0 and nothing it draws reaches a desktop, so the icon is a
# separate process in the signed-in person's own session -- and a
# per-user logon task is exactly the right mechanism for something that
# should exist only while somebody is there to look at it.
#
# Registered for the account that ran the installer, which under
# self-elevation is still that person: `Start-Process -Verb RunAs`
# elevates the same account rather than switching to another. On a box
# with several users it is per-user by design; the others run the
# installer's `-NoService -NoStart` themselves or go without an icon.
# The Start menu entry goes in for every install that has an autostart,
# tray icon or not: it is the only discoverable way back to a Eugene
# that has been stopped, and the URL is not one.
if ($autostart -ne "none" -and -not $Update) {
    Add-StartMenuShortcut
}

if ($autostart -eq "service" -and -not $NoTray -and -not $Update) {
    $trayExe = Join-Path $Venv "Scripts\eugene-plexus-tray.exe"
    if (Test-Path $trayExe) {
        Say "registering the $TrayTaskName logon task (the notification-area icon)"
        if (Get-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TrayTaskName -Confirm:$false
        }
        $trayAction = New-ScheduledTaskAction -Execute $trayExe `
            -Argument "--port $Port" -WorkingDirectory $Prefix
        $trayTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        # **No RestartCount, unlike the agent's task.** An icon a person
        # dismissed with "Hide this icon" must stay dismissed until the
        # next sign-in; a restart policy would put it back within the
        # minute and there would be no way to be rid of it.
        $traySettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName $TrayTaskName -Action $trayAction `
            -Trigger $trayTrigger -Settings $traySettings `
            -Description "Eugene Plexus notification-area icon" | Out-Null
        # Start it now rather than at the next sign-in: the person is
        # sitting here, and an icon that appears tomorrow is an icon
        # they will not connect to what they just did.
        Start-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue
    }
    else {
        Warn "no tray icon: $trayExe is missing (the [tray] extra did not install)"
    }
}

# The config path has to reach the process however it is started. A task
# inherits the user environment; a service reads the machine one, set
# above. The bind host is deliberately not set beside it -- see the join
# block for why the agent derives that one itself.
if (-not $Isolated -and -not $Update) {
    [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", $Config, "User")
}
$env:EUGENE_PLEXUS_AGENT_CONFIG_FILE = $Config

# **The one lever when 8079 is taken, and it reached nothing** (review
# 6.2 #24). `EUGENE_PLEXUS_AGENT_BIND_PORT` was read for the health wait
# at the end of this script and never written anywhere the autostart
# reads, so the install that answered on the chosen port during the run
# came back on 8079 at the next boot -- and the closing line told the
# person to open a port the agent would not be on.
#
# It rides beside the config-file variable, in the same scope, for the
# same reason: a task inherits the user environment and a service reads
# the machine one. **The account-wide blast radius that killed the
# BIND_HOST variable does not apply the same way here** -- BIND_HOST
# widened every other agent on the account to 0.0.0.0, which is a
# security property; this says which port this account's one install
# uses, and a second install on the account is now refused outright
# (#10 above). -Uninstall clears it.
if ($Isolated) {
    Say "isolated install: no service, task, tray or persistent environment was changed"
}
elseif ($Update) {
    # The port this install uses is already where its autostart reads it.
}
elseif ($Port -ne 8079) {
    [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", "$Port", "User")
    if ($IsElevated) {
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", "$Port", "Machine")
    }
}
else {
    # A run that goes back to the default must not leave the old
    # override behind, or the port is sticky per account forever.
    [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", $null, "User")
    if ($IsElevated) {
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_PORT", $null, "Machine")
    }
}

# --- 6. start ---------------------------------------------------------
if (-not $NoStart -and $autostart -ne "none") {
    Say "starting the agent"
    if ($autostart -eq "service") {
        Start-Service -Name $ServiceName
    }
    else {
        Start-ScheduledTask -TaskName $TaskName
    }

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod "http://127.0.0.1:$Port/healthz" -TimeoutSec 2 | Out-Null
            Write-Host ""
            Say "Eugene Plexus is running -- open http://127.0.0.1:$Port/"
            Say "logs:  $Prefix\logs\    config: $Config"
            Show-SetAsideNote
            # Stopping the install stopped the tray icon too (it runs from
            # the venv). Its task belongs to the person, and SYSTEM may run it.
            if ($Update -and (Get-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue)) {
                Start-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue
            }
            return
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    Die "the agent did not answer on port $Port within 60s. Check $Prefix\logs\agent.log"
}

Say "installed. Start it with:"
if ($autostart -eq "service") { Write-Host "    Start-Service $ServiceName" }
elseif ($autostart -eq "task") { Write-Host "    Start-ScheduledTask -TaskName $TaskName" }
else { Write-Host "    `$env:EUGENE_PLEXUS_AGENT_CONFIG_FILE = '$Config'; & '$AgentEx'" }
Write-Host "    then open http://127.0.0.1:$Port/"
Write-Host "    logs:  $Prefix\logs\    config: $Config"
if ($autostart -eq "service") {
    Write-Host "    Eugene starts at boot, before anyone signs in."
    if (-not $NoTray) {
        Write-Host "    There is an icon by the clock: use it to stop Eugene before a game"
        Write-Host "    and start it again after."
    }
    Write-Host "    'Eugene Plexus' is in your Start menu. It starts Eugene if it is"
    Write-Host "    stopped and then opens it, so it is the way back once you have"
    Write-Host "    stopped it -- the web page is not, because stopping Eugene takes"
    Write-Host "    the web page with it."
}
Show-SetAsideNote
