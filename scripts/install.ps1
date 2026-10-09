<#
.SYNOPSIS
  Eugene Plexus -- one-command install for Windows.

.DESCRIPTION
  The Windows half of install-paths section 9 step 3. Same six steps as
  `install.sh`, in the same order, so that reading one is reading both:

    1. fetch `uv` into the install prefix and nowhere else -- and fetch it
       again over one older than $UvMinimum,
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
    [switch]$PurgeData,
    [switch]$Interactive,
    [switch]$PurgeModelCopies,
    [string]$Join,
    [string]$Token,
    [string]$NodeName,
    [string]$Advertise,
    [switch]$JobSite,
    [string]$Owner,
    [string]$RootKey,
    [string]$SiteAccount,
    # J30: answer the join's question about commands ahead (J9).
    [switch]$SiteCommands,
    [switch]$SiteNoCommands,
    [switch]$Update
)

$ErrorActionPreference = "Stop"

if (($PurgeDownloads -or $PurgeModelCopies -or $PurgeData -or $Interactive) -and -not $Uninstall) {
    throw 'Removal options require -Uninstall. Nothing was installed or removed.'
}

# Read before `$Prefix` is given its default below: -Uninstall with no
# -Prefix finds the install wherever it is.
$PrefixGiven = [bool]$Prefix

# --- pins -------------------------------------------------------------
# Generated from release/manifest.json by scripts/release-inputs.py.
$PIN = @{
    "agent"            = "b88dd3a8460d5e23d4f0666311195e6e92bdae64"
    "control"          = "2b2ae246fbfa48a5306a695e6c9ca104ca4a1ead"
    "gateway"          = "a1e61884c1fdea066d531a50b5c556e342e950c7"
    "inference-driver" = "7d22ac92317d536e5e1ffa028fb51eb6881bb072"
    "library"          = "9ea692a7cbb1239b3e6a1ec5b29cef7107c828d5"
    "tool-driver"      = "7081c79ad655cae5916ddf0007cdf519718a5698"
    "ui"               = "aadccf2f8a6872ee78c817e37ec7b0add9d80409"  # branch `dist`, not `main`
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
# **The oldest uv this installer keeps** (2026-10-03). An install keeps the
# uv it was first made with until something replaces it, and the app's own
# updates re-run this script, so this is where an old one is replaced
# (step 1). 0.12.18 fixes GHSA-2cv4-cqwr-gwf7: on Windows, uv 0.12.7 to
# 0.12.17 can write outside the target directory while unpacking a wheel,
# with no workaround -- and the agent uses this uv to install apps, as
# LocalSystem on a service install. Kept equal to install.sh's UV_MINIMUM.
$UvMinimum = [version]"0.12.18"
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

# **Windows PowerShell started from PowerShell 7 inherits PowerShell 7's
# module folders** (found 2026-10-01, C1's Windows runner run). PSModulePath
# names them first, so 5.1 autoloads modules built for 7 and fails to load
# them: uv's installer died on "Get-ExecutionPolicy ... the module could
# not be loaded". Dropping those folders from this process's path keeps
# 5.1 on its own modules, and every child it starts inherits the fix.
# Only 7's folders go: `\PowerShell\Modules` and `\PowerShell\7*\Modules`,
# never `\WindowsPowerShell\Modules`.
if ($PSVersionTable.PSEdition -ne "Core" -and $env:PSModulePath) {
    $env:PSModulePath = (($env:PSModulePath -split ';') | Where-Object {
            $_ -and $_ -notmatch '(?i)\\PowerShell\\(?:7[^\\]*\\)?Modules\\?$'
        }) -join ';'
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
    # Apps run as services of their own (C1, docs/design/workbench.md),
    # each as its virtual account. They are Windows', not the agent's, so
    # they would outlive this install if nothing removed them here. Only
    # services whose program is this install's launcher go.
    if ($IsElevated) {
        $launcher = Join-Path $Prefix "apps\launcher\app_launcher.py"
        Get-CimInstance Win32_Service -Filter "Name LIKE 'EugenePlexusApp-%'" -ErrorAction SilentlyContinue |
            Where-Object { $_.PathName -and $_.PathName.Contains($launcher) } |
            ForEach-Object {
                Say "removing the app service $($_.Name)"
                Stop-Service -Name $_.Name -Force -ErrorAction SilentlyContinue
                & sc.exe delete $_.Name | Out-Null
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
        param([string]$Path, [bool]$AnyContent, [bool]$Registered = $false)
        if (-not $Path) { return }
        try { $full = [IO.Path]::GetFullPath($Path).TrimEnd('\') } catch { return }
        if ($seen -contains $full) { return }
        if (-not (Test-Path -LiteralPath $full -PathType Container)) { return }
        $holds = if ($Registered) { $true }
        elseif ($AnyContent) {
            [bool](Get-ChildItem -LiteralPath $full -Force -ErrorAction SilentlyContinue |
                Select-Object -First 1)
        }
        else { Test-LooksLikeInstall $full }
        if ($holds) { [void]$seen.Add($full) }
    }
    $exe = Get-AutostartExecutable
    # <prefix>\venv\Scripts\<exe> -- three levels up is the prefix.
    if ($exe) { & $consider (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $exe))) $false $true }
    foreach ($scope in @("User", "Machine")) {
        $cfg = [Environment]::GetEnvironmentVariable($ConfigVariable, $scope)
        if ($cfg) { & $consider (Split-Path -Parent $cfg) $false }
    }
    & $consider $Prefix $true
    & $consider (Join-Path $env:ProgramData "EugenePlexus") $false
    & $consider (Join-Path $env:LOCALAPPDATA "EugenePlexus") $false
    foreach ($location in @(Get-RegisteredInstallLocation)) { & $consider $location $false $true }
    return $seen.ToArray()
}

# Seams, so the Pester suite can drive the set-aside and the restore
# without a real service on the machine running it.
function Get-RegisteredInstallLocation {
    # Where each Apps & features entry says an install is, in either scope.
    # A seam since specs#15: read for real, the suite found the developer's
    # own install, and every count was off by one.
    foreach ($hive in @('HKCU:', 'HKLM:')) {
        Get-ChildItem -Path "$hive\Software\Microsoft\Windows\CurrentVersion\Uninstall\EugenePlexus-*" -ErrorAction SilentlyContinue |
            ForEach-Object {
                $registered = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
                if ($registered.InstallLocation) { $registered.InstallLocation }
            }
    }
}
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
# **`aka.ms/vc14`, not `aka.ms/vs/17`** (found 2026-10-03, the upstream
# drift audit). The `vs/17` link is Visual Studio 2022's, and it now serves
# that line's final runtime, 14.44. `vc14` follows the current Visual
# Studio: on 2026-10-03 it redirected to `vs/18` and served 14.51.36247,
# signed by Microsoft.
$VcRedistArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
$VcRedistUrl = "https://aka.ms/vc14/vc_redist.$VcRedistArch.exe"

# **The oldest runtime llama.cpp's Windows builds start on.** Upstream
# builds them with Visual Studio 2026, whose runtime is 14.50. Microsoft
# supports a program on a runtime newer than the one it was built with,
# never an older one, so a machine with only the 2022 runtime (14.44) has
# all three DLLs and can still fail to start the engine. Before 2026-10-03
# this checked only that the DLLs existed.
$VcRuntimeMinimum = [version]"14.50"

function Get-NativeSystemDirectory {
    # A 32-bit PowerShell sees SysWOW64 as System32; the engine is 64-bit.
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        return (Join-Path $env:windir "Sysnative")
    }
    return [Environment]::GetFolderPath("System")
}

# A file's version from its four numbers, not its FileVersion text, which
# some Microsoft DLLs follow with words ("14.44.35211.0 built by: ...").
function Get-DllVersion {
    param([string]$Path)
    $info = (Get-Item -LiteralPath $Path).VersionInfo
    return [version]::new($info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart, $info.FilePrivatePart)
}

# The runtime's version, read from msvcp140.dll, or $null when any of its
# three DLLs is missing.
function Get-VcRuntimeVersion {
    $system = Get-NativeSystemDirectory
    foreach ($dll in @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")) {
        if (-not (Test-Path -LiteralPath (Join-Path $system $dll))) { return $null }
    }
    return (Get-DllVersion (Join-Path $system "msvcp140.dll"))
}

# Present AND new enough. [version] compares number by number, so 14.100
# is newer than 14.50, which a comparison of the text gets backwards.
function Test-VcRuntime {
    $version = Get-VcRuntimeVersion
    return ($null -ne $version -and $version -ge $VcRuntimeMinimum)
}

# Download Microsoft's redistributable, refuse it unless Microsoft signed it,
# and run it silently. Returns its installer's exit code; throws, with what
# went wrong, on any failure.
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
        return $run.ExitCode
    }
    finally {
        Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
    }
}

# The version a uv says it is -- its words are `uv 0.12.22 (...)` -- as a
# [version], which compares number by number: 0.12.9 is older than 0.12.18,
# which a comparison of the text gets backwards. $null for a uv that is not
# there or cannot say what it is.
function Get-UvVersion {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $words = "$(& $Path --version 2>&1)" }
    catch { return $null }
    finally { $ErrorActionPreference = $prev }
    if ($words -match '^uv (\d+)\.(\d+)\.(\d+)') {
        return [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
    }
    return $null
}

# Step 1: a uv in the prefix, $UvMinimum or newer.
#
# **An install kept the uv it was first made with, forever** (found
# 2026-10-03, the upstream drift audit). This step skipped the download
# whenever a uv was there, and the app's updates re-run this script, so
# nothing ever replaced one. A uv older than $UvMinimum, or one that cannot
# say its version, is fetched again by the same official installer, over
# the old one; one new enough is left alone, exactly as before. Not
# `uv self update`: UV_UNMANAGED_INSTALL, which keeps uv inside the prefix,
# also turns uv's self-updater off (its installer writes no receipt, and
# self update refuses a uv without one).
function Install-Uv {
    $have = Get-UvVersion $UvExe
    if ($have -and $have -ge $UvMinimum) {
        Say "uv already present ($(& $UvExe --version))"
        return
    }
    if ($have) { Say "uv $have is older than $UvMinimum, the oldest this installer keeps (GHSA-2cv4-cqwr-gwf7); fetching a newer one" }
    elseif (Test-Path $UvExe) { Say "the uv at $UvExe does not say its version; fetching uv again" }
    else { Say "fetching uv" }
    # UV_UNMANAGED_INSTALL puts uv exactly here and edits no PATH and no
    # profile. The installer owns its own copy, so nothing the user
    # already has is touched and removing the prefix is complete.
    $env:UV_UNMANAGED_INSTALL = Join-Path $Prefix "bin"
    # **In a child process, never in this one** (found 2026-10-01, C1's
    # first Windows runner run). uv's installer catches any error of its
    # own, writes the reason to the information stream and calls
    # `exit 1`. Run here, that exit ended THIS installer, and the
    # silencing it needed took the reason with it: the run stopped after
    # "fetching uv" with exit code 1 and no words. A child's exit is its
    # own, and Invoke-Native prints what it said when it fails.
    $uvScript = Join-Path ([IO.Path]::GetTempPath()) "eugene-plexus-uv-install-$PID.ps1"
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 -OutFile $uvScript
    }
    catch {
        Die "could not download https://astral.sh/uv/install.ps1 -- $($_.Exception.Message)"
    }
    try {
        Invoke-Native -Exe (Get-Process -Id $PID).Path `
            -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $uvScript) `
            -FailMessage "uv's installer (https://astral.sh/uv/install.ps1) failed; its words are above"
    }
    finally {
        Remove-Item -LiteralPath $uvScript -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path $UvExe)) { Die "uv did not land at $UvExe" }
    # Said rather than assumed: a replacement that did not happen (a uv.exe
    # another program held open, say) leaves the old one in place.
    $now = Get-UvVersion $UvExe
    if (-not $now -or $now -lt $UvMinimum) {
        Die "the uv at $UvExe is $(if ($now) { $now } else { 'one that does not say its version' }) after fetching it again, and this installer needs $UvMinimum or newer. Close anything using it, or put a uv $UvMinimum or newer there yourself, then run this again."
    }
    Say "uv $((& $UvExe --version) -replace '^uv ')"
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

# BEGIN GENERATED OFFLINE REMOVAL
# Source: scripts/uninstall*; regenerate with python scripts/embed-uninstall.py.
function Write-RemovalBundle {
    param([string]$Path)
    $dir = Join-Path $Path 'uninstall'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $dir 'inventory.py'), [Convert]::FromBase64String('IiIiUmVhZCBhbiBpbnN0YWxsJ3MgcmVtb3ZhbCBpbnZlbnRvcnkgYmVmb3JlIGl0cyBQeXRob24gaXMgcmVtb3ZlZC4KCkluc3RhbGxlZCB2ZXJiYXRpbSBieSBib3RoIGluc3RhbGxlcnMuIFRoaXMgcHJvZ3JhbSBuZXZlciBkZWxldGVzIGZpbGVzLgpUaGUgbmF0aXZlIHVuaW5zdGFsbGVycyByZXRhaW4gaXRzIHBsYWluLXRleHQgaW52ZW50b3J5IGZvciBvZmZsaW5lIGNsZWFudXAuCiIiIgoKZnJvbSBfX2Z1dHVyZV9fIGltcG9ydCBhbm5vdGF0aW9ucwoKaW1wb3J0IGFyZ3BhcnNlCmltcG9ydCBiYXNlNjQKaW1wb3J0IGhhc2hsaWIKaW1wb3J0IGpzb24KaW1wb3J0IG9zCmZyb20gcGF0aGxpYiBpbXBvcnQgUGF0aAppbXBvcnQgcGxpc3RsaWIKaW1wb3J0IHNobGV4CmltcG9ydCBzeXMKCgpkZWYgYWJzb2x1dGUocGF0aDogc3RyIHwgUGF0aCkgLT4gUGF0aDoKICAgIHJldHVybiBQYXRoKG9zLnBhdGguYWJzcGF0aChvcy5wYXRoLmV4cGFuZHVzZXIoc3RyKHBhdGgpKSkpCgoKZGVmIG92ZXJsYXBzKGE6IFBhdGgsIGI6IFBhdGgpIC0+IGJvb2w6CiAgICBhLCBiID0gYS5yZXNvbHZlKCksIGIucmVzb2x2ZSgpCiAgICByZXR1cm4gYSA9PSBiIG9yIGEgaW4gYi5wYXJlbnRzIG9yIGIgaW4gYS5wYXJlbnRzCgoKZGVmIHJlYWRfY29uZmlnKHBhdGg6IFBhdGgsIHdhcm5pbmdzOiBsaXN0W3N0cl0pIC0+IGRpY3Q6CiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4ge30KICAgIHRyeToKICAgICAgICBpbXBvcnQgeWFtbAoKICAgICAgICB2YWx1ZSA9IHlhbWwuc2FmZV9sb2FkKHBhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOC1zaWciKSkgb3Ige30KICAgICAgICBpZiBub3QgaXNpbnN0YW5jZSh2YWx1ZSwgZGljdCk6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoImV4cGVjdGVkIGEgbWFwcGluZyIpCiAgICAgICAgcmV0dXJuIHZhbHVlCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4YzoKICAgICAgICB3YXJuaW5ncy5hcHBlbmQoCiAgICAgICAgICAgIGYiQ291bGQgbm90IHJlYWQge3BhdGh9ICh7dHlwZShleGMpLl9fbmFtZV9ffSkuIEN1c3RvbSBkb3dubG9hZHMgYXJlIGtlcHQuIgogICAgICAgICkKICAgICAgICByZXR1cm4ge30KCgpkZWYgaW52ZW50b3J5KHByZWZpeDogUGF0aCkgLT4gZGljdDoKICAgIHdhcm5pbmdzOiBsaXN0W3N0cl0gPSBbXQogICAgYWdlbnQgPSByZWFkX2NvbmZpZyhwcmVmaXggLyAiYWdlbnQueWFtbCIsIHdhcm5pbmdzKQogICAgcHJvdGVjdGVkID0gW3ByZWZpeCAvICJtb2RlbHMiLCBQYXRoLmhvbWUoKSAvICJFdWdlbmUgTW9kZWxzIl0KCiAgICAjIExpYnJhcnkgc3RhdGUgY29udGFpbnMgbW9kZWxSb290cyBhbmQsIG9uIG5ld2VyIGluc3RhbGxhdGlvbnMsIGZvbGRlcnMuCiAgICBkZWYgcm9vdHModmFsdWU6IG9iamVjdCwga2V5OiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICBpZiBpc2luc3RhbmNlKHZhbHVlLCBkaWN0KToKICAgICAgICAgICAgZm9yIGssIHYgaW4gdmFsdWUuaXRlbXMoKToKICAgICAgICAgICAgICAgIGlmIGsgaW4gKCJtb2RlbFJvb3RzIiwgImRlZmF1bHRNb2RlbFJvb3RzIikgYW5kIGlzaW5zdGFuY2UodiwgbGlzdCk6CiAgICAgICAgICAgICAgICAgICAgcHJvdGVjdGVkLmV4dGVuZChhYnNvbHV0ZShwKSBmb3IgcCBpbiB2IGlmIGlzaW5zdGFuY2UocCwgc3RyKSkKICAgICAgICAgICAgICAgICAgICByb290cyh2LCBrKQogICAgICAgICAgICAgICAgZWxpZiAoCiAgICAgICAgICAgICAgICAgICAgayBpbiAoInBhdGgiLCAibG9jYWxQYXRoIikKICAgICAgICAgICAgICAgICAgICBhbmQga2V5IGluICgiZm9sZGVycyIsICJtb2RlbFJvb3RzIikKICAgICAgICAgICAgICAgICAgICBhbmQgaXNpbnN0YW5jZSh2LCBzdHIpCiAgICAgICAgICAgICAgICApOgogICAgICAgICAgICAgICAgICAgIHByb3RlY3RlZC5hcHBlbmQoYWJzb2x1dGUodikpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHJvb3RzKHYsIGspCiAgICAgICAgZWxpZiBpc2luc3RhbmNlKHZhbHVlLCBsaXN0KToKICAgICAgICAgICAgZm9yIHYgaW4gdmFsdWU6CiAgICAgICAgICAgICAgICByb290cyh2LCBrZXkpCgogICAgZm9yIGNvbmZpZyBpbiBwcmVmaXguZ2xvYigibGlicmFyeSoueWFtbCIpOgogICAgICAgIHJvb3RzKHJlYWRfY29uZmlnKGNvbmZpZywgd2FybmluZ3MpKQogICAgcm9vdHMoYWdlbnQpCiAgICBzb2Z0d2FyZSA9IFsKICAgICAgICBwcmVmaXggLyBuYW1lIGZvciBuYW1lIGluICgidmVudiIsICJweXRob25zIiwgImJpbiIsICIuY2FjaGUvdXYiLCAidXBkYXRlIikKICAgIF0KICAgIHNvZnR3YXJlICs9IFsKICAgICAgICBwcmVmaXggLyBuYW1lIGZvciBuYW1lIGluICgiaW5zdGFsbC1jaGVjay5weSIsICJyZWxlYXNlLXJlcXVpcmVtZW50cy5sb2NrIikKICAgIF0KICAgIGFwcHMgPSBwcmVmaXggLyAiYXBwcyIKICAgIHNvZnR3YXJlICs9IFthcHBzIC8gbmFtZSBmb3IgbmFtZSBpbiAoInB5dGhvbnMiLCAibGF1bmNoZXIiLCAiY3RsIildCiAgICBkYXRhID0gW3ByZWZpeCAvIG5hbWUgZm9yIG5hbWUgaW4gKCJsb2dzIiwgInBhc3NwaHJhc2UiLCAiY29udHJvbC1zdGF0ZSIpXQogICAgZm9yIGFwcCBpbiBhcHBzLml0ZXJkaXIoKSBpZiBhcHBzLmlzX2RpcigpIGFuZCBub3QgYXBwcy5pc19zeW1saW5rKCkgZWxzZSBbXToKICAgICAgICBpZiAoCiAgICAgICAgICAgIGFwcC5pc19kaXIoKQogICAgICAgICAgICBhbmQgbm90IGFwcC5pc19zeW1saW5rKCkKICAgICAgICAgICAgYW5kIGFwcC5uYW1lIG5vdCBpbiAoInB5dGhvbnMiLCAibGF1bmNoZXIiLCAiY3RsIikKICAgICAgICApOgogICAgICAgICAgICBzb2Z0d2FyZSArPSBbYXBwIC8gInZlcnNpb25zIiwgYXBwIC8gInB5dGhvbiJdCiAgICAgICAgICAgIGRhdGEgKz0gW3AgZm9yIHAgaW4gYXBwLml0ZXJkaXIoKSBpZiBwLm5hbWUgbm90IGluICgidmVyc2lvbnMiLCAicHl0aG9uIildCiAgICBmb3IgaXRlbSBpbiBwcmVmaXguaXRlcmRpcigpOgogICAgICAgIGlmIGl0ZW0uaXNfZmlsZSgpIGFuZCAoCiAgICAgICAgICAgIGl0ZW0uc3VmZml4CiAgICAgICAgICAgIGluICgKICAgICAgICAgICAgICAgICIueWFtbCIsCiAgICAgICAgICAgICAgICAiLmpzb24iLAogICAgICAgICAgICAgICAgIi5zcWxpdGUzIiwKICAgICAgICAgICAgICAgICIuZGIiLAogICAgICAgICAgICAgICAgIi5zcWxpdGUzLXdhbCIsCiAgICAgICAgICAgICAgICAiLnNxbGl0ZTMtc2htIiwKICAgICAgICAgICAgICAgICIuZGItd2FsIiwKICAgICAgICAgICAgICAgICIuZGItc2htIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBvciBpdGVtLm5hbWUuc3RhcnRzd2l0aCgKICAgICAgICAgICAgICAgICgKICAgICAgICAgICAgICAgICAgICAiLnVwZGF0ZS1jaGFubmVsIiwKICAgICAgICAgICAgICAgICAgICAiYWdlbnQueWFtbC4iLAogICAgICAgICAgICAgICAgICAgICJub2RlLnlhbWwuIiwKICAgICAgICAgICAgICAgICAgICAiY29udHJvbC55YW1sLiIsCiAgICAgICAgICAgICAgICAgICAgImdhdGV3YXkueWFtbC4iLAogICAgICAgICAgICAgICAgICAgICJsaWJyYXJ5LnlhbWwuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgKQogICAgICAgICk6CiAgICAgICAgICAgIGRhdGEuYXBwZW5kKGl0ZW0pCiAgICBpZiBhcHBzLmlzX2RpcigpOgogICAgICAgIGRhdGEgKz0gW3AgZm9yIHAgaW4gYXBwcy5pdGVyZGlyKCkgaWYgcC5pc19maWxlKCldCiAgICBkb3dubG9hZHMgPSBbcHJlZml4IC8gImVuZ2luZXMiXQogICAgZW5naW5lID0gb3MuZW52aXJvbi5nZXQoIkVVR0VORV9QTEVYVVNfQUdFTlRfRU5HSU5FX1JPT1QiKQogICAgIyBTZXJ2aWNlIGluc3RhbGxzIG93biBwcmVmaXgvZW5naW5lcy4gRG8gbm90IGFsc28gc3dlZXAgdGhlIGludm9raW5nCiAgICAjIGFkbWluaXN0cmF0b3IncyBwZXItdXNlciBzdG9yZSAod2hpY2ggbWF5IGJlbG9uZyB0byBhbm90aGVyIGluc3RhbGwpLgogICAgaW5mb19wYXRoID0gcHJlZml4IC8gInVuaW5zdGFsbC9pbnN0YWxsLWluZm8uanNvbiIKICAgIGlmIGluZm9fcGF0aC5leGlzdHMoKToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlY29yZGVkX2VuZ2luZSA9IGpzb24ubG9hZHMoaW5mb19wYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSlbCiAgICAgICAgICAgICAgICAiZW5naW5lUm9vdCIKICAgICAgICAgICAgXQogICAgICAgICAgICBkb3dubG9hZHMuYXBwZW5kKGFic29sdXRlKHJlY29yZGVkX2VuZ2luZSkpCiAgICAgICAgZXhjZXB0IChPU0Vycm9yLCBWYWx1ZUVycm9yLCBLZXlFcnJvciwgVHlwZUVycm9yKToKICAgICAgICAgICAgd2FybmluZ3MuYXBwZW5kKAogICAgICAgICAgICAgICAgIkNvdWxkIG5vdCByZWFkIHRoZSBpbnN0YWxsZWQgZG93bmxvYWQgbG9jYXRpb24uIEV4dGVybmFsIGVuZ2luZXMgd2VyZSBrZXB0LiIKICAgICAgICAgICAgKQogICAgZWxpZiBub3QgKHByZWZpeCAvICJlbmdpbmVzIikuZXhpc3RzKCk6CiAgICAgICAgaWYgZW5naW5lIGFuZCBhYnNvbHV0ZShlbmdpbmUpICE9IHByZWZpeCAvICJlbmdpbmVzIjoKICAgICAgICAgICAgd2FybmluZ3MuYXBwZW5kKAogICAgICAgICAgICAgICAgZiJFeHRlcm5hbCBlbmdpbmUgc3RvcmUga2VwdDoge2VuZ2luZX0uIEl0cyBvd25lcnNoaXAgY2Fubm90IGJlIGNvbmZpcm1lZCBmcm9tIHRoaXMgaW5zdGFsbGF0aW9uLiIKICAgICAgICAgICAgKQogICAgICAgIGVsaWYgbm90IGVuZ2luZToKICAgICAgICAgICAgZG93bmxvYWRzLmFwcGVuZChQYXRoLmhvbWUoKSAvICIuZXVnZW5lLXBsZXh1cy9lbmdpbmVzIikKICAgIGNvcGllcyA9IGFnZW50LmdldCgibW9kZWxDb3B5RGlyIikKICAgIGlmIGlzaW5zdGFuY2UoY29waWVzLCBzdHIpIGFuZCBjb3BpZXM6CiAgICAgICAgaWYgUGF0aChjb3BpZXMpLmV4cGFuZHVzZXIoKS5pc19hYnNvbHV0ZSgpOgogICAgICAgICAgICBkb3dubG9hZHMuYXBwZW5kKGFic29sdXRlKGNvcGllcykpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgd2FybmluZ3MuYXBwZW5kKAogICAgICAgICAgICAgICAgZiJSZWxhdGl2ZSBtb2RlbC1jb3B5IGxvY2F0aW9uIGtlcHQ6IHtjb3BpZXN9LiBJdHMgd29ya2luZyBkaXJlY3RvcnkgY2Fubm90IGJlIGNvbmZpcm1lZC4iCiAgICAgICAgICAgICkKICAgIGlmIGFueSh3LnN0YXJ0c3dpdGgoIkNvdWxkIG5vdCByZWFkIikgZm9yIHcgaW4gd2FybmluZ3MpOgogICAgICAgIGRvd25sb2FkcyA9IFtdCiAgICAgICAgd2FybmluZ3MuYXBwZW5kKAogICAgICAgICAgICAiRG93bmxvYWRzIHdlcmUga2VwdCBiZWNhdXNlIHRoZSBjb25maWd1cmF0aW9uIGNvdWxkIG5vdCBiZSByZWFkIHNhZmVseS4iCiAgICAgICAgKQogICAgcmVzdWx0OiBkaWN0ID0geyJ2ZXJzaW9uIjogMSwgInByZWZpeCI6IHN0cihwcmVmaXgpLCAid2FybmluZ3MiOiB3YXJuaW5nc30KICAgIGZvciBraW5kLCBjYW5kaWRhdGVzIGluICgKICAgICAgICAoInNvZnR3YXJlIiwgc29mdHdhcmUpLAogICAgICAgICgiZGF0YSIsIGRhdGEpLAogICAgICAgICgiZG93bmxvYWRzIiwgZG93bmxvYWRzKSwKICAgICk6CiAgICAgICAga2VwdCA9IFtdCiAgICAgICAgZm9yIHBhdGggaW4gZGljdC5mcm9ta2V5cyhhYnNvbHV0ZShwKSBmb3IgcCBpbiBjYW5kaWRhdGVzKToKICAgICAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCkgYW5kIG5vdCBwYXRoLmlzX3N5bWxpbmsoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmICJcbiIgaW4gc3RyKHBhdGgpIG9yICJcciIgaW4gc3RyKHBhdGgpOgogICAgICAgICAgICAgICAgd2FybmluZ3MuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiS2VwdCBhIHtraW5kfSBwYXRoIGNvbnRhaW5pbmcgYSBuZXdsaW5lOyByZW1vdmUgaXQgbWFudWFsbHkuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgKAogICAgICAgICAgICAgICAgcGF0aCA9PSBwcmVmaXgKICAgICAgICAgICAgICAgIG9yIHBhdGggaW4gcHJlZml4LnBhcmVudHMKICAgICAgICAgICAgICAgIG9yIHBhdGggPT0gYWJzb2x1dGUoUGF0aC5ob21lKCkpCiAgICAgICAgICAgICAgICBvciBsZW4ocGF0aC5wYXJ0cykgPCAzCiAgICAgICAgICAgICk6CiAgICAgICAgICAgICAgICB3YXJuaW5ncy5hcHBlbmQoZiJLZXB0IHVuc2FmZSB7a2luZH0gcGF0aDoge3BhdGh9IikKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGFueShvdmVybGFwcyhwYXRoLCBwKSBmb3IgcCBpbiBwcm90ZWN0ZWQpOgogICAgICAgICAgICAgICAgd2FybmluZ3MuYXBwZW5kKGYiS2VwdCB7cGF0aH06IGl0IG92ZXJsYXBzIGFuIG9yaWdpbmFsIG1vZGVsIGZvbGRlci4iKQogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgIyBOZXZlciB0cmF2ZXJzZSBhIHN5bWxpbmsvanVuY3Rpb24gdG8gbWFrZSBhIGRlbGV0aW9uIGludmVudG9yeS4KICAgICAgICAgICAgaWYgYW55KAogICAgICAgICAgICAgICAgcC5pc19zeW1saW5rKCkgb3IgKGhhc2F0dHIocCwgImlzX2p1bmN0aW9uIikgYW5kIHAuaXNfanVuY3Rpb24oKSkKICAgICAgICAgICAgICAgIGZvciBwIGluIChwYXRoLCAqcGF0aC5wYXJlbnRzKQogICAgICAgICAgICApOgogICAgICAgICAgICAgICAgd2FybmluZ3MuYXBwZW5kKGYiS2VwdCB7cGF0aH06IGl0IHVzZXMgYSBsaW5rIG9yIGp1bmN0aW9uLiIpCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBrZXB0LmFwcGVuZChzdHIocGF0aCkpCiAgICAgICAgcmVzdWx0W2tpbmRdID0ga2VwdAogICAgcmVzdWx0WyJwcm90ZWN0ZWQiXSA9IGxpc3QoZGljdC5mcm9ta2V5cyhzdHIoYWJzb2x1dGUocCkpIGZvciBwIGluIHByb3RlY3RlZCkpCiAgICByZXR1cm4gcmVzdWx0CgoKZGVmIGtleXJpbmdfY2xlYW51cChwcmVmaXg6IFBhdGgpIC0+IGRpY3Q6CiAgICB3YXJuaW5nczogbGlzdFtzdHJdID0gW10KICAgIGNvbmZpZyA9IHJlYWRfY29uZmlnKHByZWZpeCAvICJhZ2VudC55YW1sIiwgd2FybmluZ3MpCiAgICBhdXRoID0gY29uZmlnLmdldCgiYXV0aCIpIG9yIHt9CiAgICBpZiBub3QgaXNpbnN0YW5jZShhdXRoLCBkaWN0KToKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAicmVtb3ZlZCI6IDAsCiAgICAgICAgICAgICJ3YXJuaW5ncyI6IFsiQ3JlZGVudGlhbHMga2VwdDogdGhlIGF1dGggY29uZmlndXJhdGlvbiBpcyBub3QgcmVhZGFibGUuIl0sCiAgICAgICAgfQogICAgc2FsdCA9IGF1dGguZ2V0KCJtYXN0ZXJTYWx0IikKICAgIG5hbWVzID0gW10KICAgIGlmIHNhbHQ6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBmaW5nZXJwcmludCA9IGhhc2hsaWIuc2hhMjU2KAogICAgICAgICAgICAgICAgYmFzZTY0LmI2NGRlY29kZShzYWx0LCB2YWxpZGF0ZT1UcnVlKQogICAgICAgICAgICApLmhleGRpZ2VzdCgpWzoxMl0KICAgICAgICAgICAgIyBUaGUgYXBwbGljYXRpb24gdXNlcyBhIGNvbG9uLiBUaGUgb2xkIHVuaW5zdGFsbC90ZXN0IGNvZGUKICAgICAgICAgICAgIyBpbmNvcnJlY3RseSB1c2VkIGEgZGFzaDsgYWxzbyByZW1vdmUgdGhhdCBoaXN0b3JpY2FsIHNwZWxsaW5nLgogICAgICAgICAgICBuYW1lcyA9IFsibWFzdGVyLWtleToiICsgZmluZ2VycHJpbnQsICJtYXN0ZXIta2V5LSIgKyBmaW5nZXJwcmludF0KICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4YzoKICAgICAgICAgICAgd2FybmluZ3MuYXBwZW5kKGYiQ291bGQgbm90IGlkZW50aWZ5IHRoaXMgaW5zdGFsbCdzIGNyZWRlbnRpYWxzOiB7ZXhjfSIpCiAgICBlbGlmIGNvbmZpZy5nZXQoImF1dGgiKToKICAgICAgICAjIEEgbGVnYWN5IGVudHJ5IGlzIHNoYXJlZDsgZG8gbm90IGRlbGV0ZSBhIGRpZmZlcmVudCBpbnN0YWxsJ3Mga2V5LgogICAgICAgIHdhcm5pbmdzLmFwcGVuZCgKICAgICAgICAgICAgIkxlZ2FjeSB1bnNjb3BlZCBjcmVkZW50aWFscyB3ZXJlIGtlcHQuIFJldmlldyBFdWdlbmUgZW50cmllcyBpbiB0aGUgT1MgY3JlZGVudGlhbCBzdG9yZS4iCiAgICAgICAgKQogICAgcmVtb3ZlZCA9IDAKICAgIGlmIG5hbWVzOgogICAgICAgIHRyeToKICAgICAgICAgICAgaW1wb3J0IGtleXJpbmcKCiAgICAgICAgICAgIGZvciBzZXJ2aWNlIGluICgiZXVnZW5lLXBsZXh1cy1hZ2VudCIsICJldWdlbmUtcGxleHVzLWNvbnRyb2wiKToKICAgICAgICAgICAgICAgIGZvciBuYW1lIGluIG5hbWVzOgogICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgaWYga2V5cmluZy5nZXRfcGFzc3dvcmQoc2VydmljZSwgbmFtZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBrZXlyaW5nLmRlbGV0ZV9wYXNzd29yZChzZXJ2aWNlLCBuYW1lKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYga2V5cmluZy5nZXRfcGFzc3dvcmQoc2VydmljZSwgbmFtZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiZW50cnkgaXMgc3RpbGwgcHJlc2VudCBhZnRlciBkZWxldGlvbiIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZW1vdmVkICs9IDEKICAgICAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4YzoKICAgICAgICAgICAgICAgICAgICAgICAgd2FybmluZ3MuYXBwZW5kKGYiQ3JlZGVudGlhbCBsZWZ0OiB7c2VydmljZX0ve25hbWV9OiB7ZXhjfSIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleGM6CiAgICAgICAgICAgIHdhcm5pbmdzLmFwcGVuZChmIkNvdWxkIG5vdCBvcGVuIHRoZSBPUyBjcmVkZW50aWFsIHN0b3JlOiB7ZXhjfSIpCiAgICByZXR1cm4geyJyZW1vdmVkIjogcmVtb3ZlZCwgIndhcm5pbmdzIjogd2FybmluZ3N9CgoKZGVmIG1haW4oKSAtPiBOb25lOgogICAgcGFyc2VyID0gYXJncGFyc2UuQXJndW1lbnRQYXJzZXIoZGVzY3JpcHRpb249X19kb2NfXykKICAgIHBhcnNlci5hZGRfYXJndW1lbnQoIi0tcHJlZml4IiwgdHlwZT1QYXRoLCByZXF1aXJlZD1UcnVlKQogICAgcGFyc2VyLmFkZF9hcmd1bWVudCgiLS1vdXRwdXQiLCB0eXBlPVBhdGgpCiAgICBwYXJzZXIuYWRkX2FyZ3VtZW50KCItLWtleXJpbmctb25seSIsIGFjdGlvbj0ic3RvcmVfdHJ1ZSIpCiAgICBwYXJzZXIuYWRkX2FyZ3VtZW50KCItLWluc3RhbGwtbWFjb3MiLCBhY3Rpb249InN0b3JlX3RydWUiKQogICAgYXJncyA9IHBhcnNlci5wYXJzZV9hcmdzKCkKICAgIHByZWZpeCA9IGFic29sdXRlKGFyZ3MucHJlZml4KQogICAgaWYgYXJncy5pbnN0YWxsX21hY29zOgogICAgICAgIGluc3RhbGxfbWFjb3MocHJlZml4KQogICAgICAgIHJldHVybgogICAgaWYgYXJncy5vdXRwdXQgaXMgTm9uZToKICAgICAgICBwYXJzZXIuZXJyb3IoIi0tb3V0cHV0IGlzIHJlcXVpcmVkIikKICAgIHJlc3VsdCA9IGtleXJpbmdfY2xlYW51cChwcmVmaXgpIGlmIGFyZ3Mua2V5cmluZ19vbmx5IGVsc2UgaW52ZW50b3J5KHByZWZpeCkKICAgIHRlbXBvcmFyeSA9IGFyZ3Mub3V0cHV0LndpdGhfc3VmZml4KCIudG1wIikKICAgIHRlbXBvcmFyeS53cml0ZV90ZXh0KGpzb24uZHVtcHMocmVzdWx0LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCiAgICB0ZW1wb3JhcnkucmVwbGFjZShhcmdzLm91dHB1dCkKICAgIGlmIG5vdCBhcmdzLmtleXJpbmdfb25seToKICAgICAgICBmb3Iga2luZCBpbiAoInNvZnR3YXJlIiwgImRhdGEiLCAiZG93bmxvYWRzIiwgInByb3RlY3RlZCIpOgogICAgICAgICAgICAoYXJncy5vdXRwdXQucGFyZW50IC8gZiJ7a2luZH0udHh0Iikud3JpdGVfdGV4dCgKICAgICAgICAgICAgICAgICIiLmpvaW4ocCArICJcbiIgZm9yIHAgaW4gcmVzdWx0W2tpbmRdKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICAgICApCiAgICAgICAgKGFyZ3Mub3V0cHV0LnBhcmVudCAvICJvcmlnaW5hbC1wcmVmaXgudHh0Iikud3JpdGVfdGV4dCgKICAgICAgICAgICAgc3RyKHByZWZpeCkgKyAiXG4iLCBlbmNvZGluZz0idXRmLTgiCiAgICAgICAgKQogICAgICAgIChhcmdzLm91dHB1dC5wYXJlbnQgLyAid2FybmluZ3MudHh0Iikud3JpdGVfdGV4dCgKICAgICAgICAgICAgIlxuIi5qb2luKHJlc3VsdFsid2FybmluZ3MiXSksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCiAgICAgICAgcHJvZ3JhbXMgPSBbcHJlZml4IC8gInZlbnYvYmluL3B5dGhvbiIsIFBhdGgoc3lzLmV4ZWN1dGFibGUpLnJlc29sdmUoKV0KICAgICAgICBvd25lZF9wcm9ncmFtcyA9IFsKICAgICAgICAgICAgc3RyKHApIGZvciBwIGluIHByb2dyYW1zIGlmIHAucmVzb2x2ZSgpLmlzX3JlbGF0aXZlX3RvKHByZWZpeC5yZXNvbHZlKCkpCiAgICAgICAgXQogICAgICAgIChhcmdzLm91dHB1dC5wYXJlbnQgLyAiZmlyZXdhbGwudHh0Iikud3JpdGVfdGV4dCgKICAgICAgICAgICAgIiIuam9pbihwICsgIlxuIiBmb3IgcCBpbiBkaWN0LmZyb21rZXlzKG93bmVkX3Byb2dyYW1zKSksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCiAgICAgICAgYXBwX3JlY29yZCA9IHByZWZpeCAvICJ1bmluc3RhbGwvbWFjLWFwcC50eHQiCiAgICAgICAgaWYgYXBwX3JlY29yZC5leGlzdHMoKToKICAgICAgICAgICAgKGFyZ3Mub3V0cHV0LnBhcmVudCAvICJtYWMtYXBwLnR4dCIpLndyaXRlX3RleHQoCiAgICAgICAgICAgICAgICBhcHBfcmVjb3JkLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICAgICApCiAgICBmb3Igd2FybmluZyBpbiByZXN1bHRbIndhcm5pbmdzIl06CiAgICAgICAgcHJpbnQoZiJ3YXJuaW5nOiB7d2FybmluZ30iLCBmaWxlPXN5cy5zdGRlcnIpCgoKZGVmIGluc3RhbGxfbWFjb3MocHJlZml4OiBQYXRoKSAtPiBOb25lOgogICAgIiIiQSBGaW5kZXItdmlzaWJsZSBsb2NhbCB1dGlsaXR5OyBubyBpbnRlcnByZXRlciBvciBuZXR3b3JrIGF0IGxhdW5jaC4iIiIKICAgIHN1ZmZpeCA9ICgKICAgICAgICAiIgogICAgICAgIGlmIHByZWZpeCA9PSBQYXRoLmhvbWUoKSAvICIubG9jYWwvc2hhcmUvZXVnZW5lLXBsZXh1cyIKICAgICAgICBlbHNlICIgIiArIGhhc2hsaWIuc2hhMjU2KHN0cihwcmVmaXgpLmVuY29kZSgpKS5oZXhkaWdlc3QoKVs6OF0KICAgICkKICAgIGFwcCA9IFBhdGguaG9tZSgpIC8gIkFwcGxpY2F0aW9ucyIgLyBmIlJlbW92ZSBFdWdlbmUgUGxleHVze3N1ZmZpeH0uYXBwIgogICAgY29udGVudHMgPSBhcHAgLyAiQ29udGVudHMiCiAgICAoY29udGVudHMgLyAiTWFjT1MiKS5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAoY29udGVudHMgLyAiUmVzb3VyY2VzIikubWtkaXIoZXhpc3Rfb2s9VHJ1ZSkKICAgIChjb250ZW50cyAvICJJbmZvLnBsaXN0Iikud3JpdGVfYnl0ZXMoCiAgICAgICAgcGxpc3RsaWIuZHVtcHMoCiAgICAgICAgICAgIHsKICAgICAgICAgICAgICAgICJDRkJ1bmRsZUlkZW50aWZpZXIiOiAiY29tLmV1Z2VuZXBsZXh1cy5yZW1vdmUiICsgc3VmZml4LnN0cmlwKCksCiAgICAgICAgICAgICAgICAiQ0ZCdW5kbGVOYW1lIjogIlJlbW92ZSBFdWdlbmUgUGxleHVzIiwKICAgICAgICAgICAgICAgICJDRkJ1bmRsZURpc3BsYXlOYW1lIjogIlJlbW92ZSBFdWdlbmUgUGxleHVzIiwKICAgICAgICAgICAgICAgICJDRkJ1bmRsZUV4ZWN1dGFibGUiOiAicmVtb3ZlIiwKICAgICAgICAgICAgICAgICJDRkJ1bmRsZVBhY2thZ2VUeXBlIjogIkFQUEwiLAogICAgICAgICAgICAgICAgIkNGQnVuZGxlVmVyc2lvbiI6ICIxIiwKICAgICAgICAgICAgICAgICJMU1VJRWxlbWVudCI6IFRydWUsCiAgICAgICAgICAgIH0KICAgICAgICApCiAgICApCiAgICBleGVjdXRhYmxlID0gY29udGVudHMgLyAiTWFjT1MvcmVtb3ZlIgogICAgZXhlY3V0YWJsZS53cml0ZV90ZXh0KAogICAgICAgICIjIS9iaW4vc2hcbmV4ZWMgL2Jpbi9zaCAiCiAgICAgICAgKyBzaGxleC5xdW90ZShzdHIocHJlZml4IC8gInVuaW5zdGFsbC9yZW1vdmUuc2giKSkKICAgICAgICArICIgLS1pbnRlcmFjdGl2ZVxuIiwKICAgICAgICBlbmNvZGluZz0idXRmLTgiLAogICAgKQogICAgZXhlY3V0YWJsZS5jaG1vZCgwbzc1NSkKICAgIChjb250ZW50cyAvICJSZXNvdXJjZXMvcHJlZml4LnR4dCIpLndyaXRlX3RleHQoc3RyKHByZWZpeCkgKyAiXG4iLCBlbmNvZGluZz0idXRmLTgiKQogICAgKHByZWZpeCAvICJ1bmluc3RhbGwvbWFjLWFwcC50eHQiKS53cml0ZV90ZXh0KHN0cihhcHApICsgIlxuIiwgZW5jb2Rpbmc9InV0Zi04IikKICAgIGVuZ2luZSA9IG9zLmVudmlyb24uZ2V0KCJFVUdFTkVfUExFWFVTX0FHRU5UX0VOR0lORV9ST09UIikgb3Igc3RyKAogICAgICAgIFBhdGguaG9tZSgpIC8gIi5ldWdlbmUtcGxleHVzL2VuZ2luZXMiCiAgICApCiAgICAocHJlZml4IC8gInVuaW5zdGFsbC9pbnN0YWxsLWluZm8uanNvbiIpLndyaXRlX3RleHQoCiAgICAgICAganNvbi5kdW1wcyh7ImVuZ2luZVJvb3QiOiBlbmdpbmV9KSwgZW5jb2Rpbmc9InV0Zi04IgogICAgKQogICAgcHJpbnQoZiJSZW1vdmFsIHV0aWxpdHk6IHthcHB9IikKCgppZiBfX25hbWVfXyA9PSAiX19tYWluX18iOgogICAgbWFpbigpCg=='))
    [IO.File]::WriteAllBytes((Join-Path $dir 'remove.ps1'), [Convert]::FromBase64String('PCMgT2ZmbGluZSByZW1vdmFsLCBhbHNvIHVzZWQgYnkgV2luZG93cyBTZXR0aW5ncyA+IEFwcHMuCiAgIFRoZSBpbnN0YWxsZXIgZW1iZWRzIHRoaXMgZmlsZS4gVGVzdHMgaW1wb3J0IGZ1bmN0aW9ucyB3aXRob3V0IHJ1bm5pbmcgbWFpbi4gIz4KW0NtZGxldEJpbmRpbmcoKV0KcGFyYW0oCiAgICBbc3RyaW5nXSRQcmVmaXggPSAoU3BsaXQtUGF0aCAtUGFyZW50ICRQU1NjcmlwdFJvb3QpLAogICAgW3N3aXRjaF0kSW50ZXJhY3RpdmUsCiAgICBbc3dpdGNoXSRQdXJnZURvd25sb2FkcywKICAgIFtzd2l0Y2hdJFB1cmdlRGF0YSwKICAgIFtzd2l0Y2hdJFJlZ2lzdGVyLAogICAgW3N3aXRjaF0kU3lzdGVtSW5zdGFsbAopCiRFcnJvckFjdGlvblByZWZlcmVuY2UgPSAnU3RvcCcKCmZ1bmN0aW9uIEdldC1SZW1vdmFsSWQoW3N0cmluZ10kUGF0aCkgewogICAgJGhhc2ggPSBbU2VjdXJpdHkuQ3J5cHRvZ3JhcGh5LlNIQTI1Nl06OkNyZWF0ZSgpCiAgICB0cnkgeyByZXR1cm4gKFtCaXRDb252ZXJ0ZXJdOjpUb1N0cmluZygkaGFzaC5Db21wdXRlSGFzaChbVGV4dC5FbmNvZGluZ106OlVURjguR2V0Qnl0ZXMoW0lPLlBhdGhdOjpHZXRGdWxsUGF0aCgkUGF0aCkuVG9Mb3dlckludmFyaWFudCgpKSkpKS5SZXBsYWNlKCctJywgJycpLlN1YnN0cmluZygwLCAxNikgfQogICAgZmluYWxseSB7ICRoYXNoLkRpc3Bvc2UoKSB9Cn0KCmZ1bmN0aW9uIFRlc3QtUmVtb3ZhbEFkbWluIHsKICAgIHJldHVybiAoW1NlY3VyaXR5LlByaW5jaXBhbC5XaW5kb3dzUHJpbmNpcGFsXVtTZWN1cml0eS5QcmluY2lwYWwuV2luZG93c0lkZW50aXR5XTo6R2V0Q3VycmVudCgpKS5Jc0luUm9sZShbU2VjdXJpdHkuUHJpbmNpcGFsLldpbmRvd3NCdWlsdEluUm9sZV06OkFkbWluaXN0cmF0b3IpCn0KCmZ1bmN0aW9uIEdldC1SZW1vdmFsQ29tbWFuZChbc3RyaW5nXSRQYXRoLCBbYm9vbF0kRWxldmF0ZSkgewogICAgJGZpbGUgPSAoSm9pbi1QYXRoICRQYXRoICd1bmluc3RhbGxccmVtb3ZlLnBzMScpLlJlcGxhY2UoIiciLCAiJyciKQogICAgJGJvZHkgPSAiJiAnJGZpbGUnIC1JbnRlcmFjdGl2ZSIKICAgIGlmICgkRWxldmF0ZSkgewogICAgICAgICRpbm5lciA9IFtDb252ZXJ0XTo6VG9CYXNlNjRTdHJpbmcoW1RleHQuRW5jb2RpbmddOjpVbmljb2RlLkdldEJ5dGVzKCRib2R5KSkKICAgICAgICAkYm9keSA9ICJ0cnkgeyBgJHAgPSBTdGFydC1Qcm9jZXNzIHBvd2Vyc2hlbGwuZXhlIC1Bcmd1bWVudExpc3QgJy1Ob1Byb2ZpbGUgLUV4ZWN1dGlvblBvbGljeSBCeXBhc3MgLUVuY29kZWRDb21tYW5kICRpbm5lcicgLVZlcmIgUnVuQXMgLVdpbmRvd1N0eWxlIEhpZGRlbiAtV2FpdCAtUGFzc1RocnU7IGV4aXQgYCRwLkV4aXRDb2RlIH0gY2F0Y2ggeyBleGl0IDEgfSIKICAgIH0KICAgICRlbmNvZGVkID0gW0NvbnZlcnRdOjpUb0Jhc2U2NFN0cmluZyhbVGV4dC5FbmNvZGluZ106OlVuaWNvZGUuR2V0Qnl0ZXMoJGJvZHkpKQogICAgcmV0dXJuICgnInswfSIgLU5vUHJvZmlsZSAtV2luZG93U3R5bGUgSGlkZGVuIC1FeGVjdXRpb25Qb2xpY3kgQnlwYXNzIC1FbmNvZGVkQ29tbWFuZCB7MX0nIC1mIChKb2luLVBhdGggJFBTSE9NRSAncG93ZXJzaGVsbC5leGUnKSwgJGVuY29kZWQpCn0KCmZ1bmN0aW9uIFJlZ2lzdGVyLVJlbW92YWwoW3N0cmluZ10kUGF0aCwgW2Jvb2xdJEZvck1hY2hpbmUpIHsKICAgICRoaXZlID0gaWYgKCRGb3JNYWNoaW5lKSB7ICdIS0xNOicgfSBlbHNlIHsgJ0hLQ1U6JyB9CiAgICAka2V5ID0gIiRoaXZlXFNvZnR3YXJlXE1pY3Jvc29mdFxXaW5kb3dzXEN1cnJlbnRWZXJzaW9uXFVuaW5zdGFsbFxFdWdlbmVQbGV4dXMtJChHZXQtUmVtb3ZhbElkICRQYXRoKSIKICAgIE5ldy1JdGVtIC1QYXRoICRrZXkgLUZvcmNlIHwgT3V0LU51bGwKICAgICR2YWx1ZXMgPSBAewogICAgICAgIERpc3BsYXlOYW1lID0gJ0V1Z2VuZSBQbGV4dXMnOyBQdWJsaXNoZXIgPSAnRXVnZW5lIFBsZXh1cyc7IEluc3RhbGxMb2NhdGlvbiA9ICRQYXRoCiAgICAgICAgVW5pbnN0YWxsU3RyaW5nID0gKEdldC1SZW1vdmFsQ29tbWFuZCAkUGF0aCAkRm9yTWFjaGluZSkKICAgICAgICBVUkxJbmZvQWJvdXQgPSAnaHR0cHM6Ly9ldWdlbmVwbGV4dXMuY29tJzsgQ29tbWVudHMgPSAnUmVtb3ZlIEV1Z2VuZTsgY2hvb3NlIHdoZXRoZXIgdG8ga2VlcCBzZXR0aW5ncyBhbmQgZG93bmxvYWRzLicKICAgIH0KICAgIGZvcmVhY2ggKCRuYW1lIGluICR2YWx1ZXMuS2V5cykgeyBOZXctSXRlbVByb3BlcnR5IC1MaXRlcmFsUGF0aCAka2V5IC1OYW1lICRuYW1lIC1WYWx1ZSAkdmFsdWVzWyRuYW1lXSAtUHJvcGVydHlUeXBlIFN0cmluZyAtRm9yY2UgfCBPdXQtTnVsbCB9CiAgICBmb3JlYWNoICgkbmFtZSBpbiBAKCdOb01vZGlmeScsICdOb1JlcGFpcicpKSB7IE5ldy1JdGVtUHJvcGVydHkgLUxpdGVyYWxQYXRoICRrZXkgLU5hbWUgJG5hbWUgLVZhbHVlIDEgLVByb3BlcnR5VHlwZSBEV29yZCAtRm9yY2UgfCBPdXQtTnVsbCB9CiAgICAkZW5naW5lID0gaWYgKCRGb3JNYWNoaW5lKSB7IEpvaW4tUGF0aCAkUGF0aCAnZW5naW5lcycgfSBlbHNlaWYgKCRlbnY6RVVHRU5FX1BMRVhVU19BR0VOVF9FTkdJTkVfUk9PVCkgeyAkZW52OkVVR0VORV9QTEVYVVNfQUdFTlRfRU5HSU5FX1JPT1QgfSBlbHNlIHsgSm9pbi1QYXRoICRlbnY6VVNFUlBST0ZJTEUgJy5ldWdlbmUtcGxleHVzXGVuZ2luZXMnIH0KICAgIFtJTy5GaWxlXTo6V3JpdGVBbGxUZXh0KChKb2luLVBhdGggJFBhdGggJ3VuaW5zdGFsbFxpbnN0YWxsLWluZm8uanNvbicpLCAoQHsgZW5naW5lUm9vdCA9ICRlbmdpbmUgfSB8IENvbnZlcnRUby1Kc29uKSwgW1RleHQuVVRGOEVuY29kaW5nXTo6bmV3KCRmYWxzZSkpCn0KCmZ1bmN0aW9uIFRlc3QtUmVtb3ZhbFdpdGhpbihbc3RyaW5nXSRQYXRoLCBbc3RyaW5nXSRSb290KSB7CiAgICAkcCA9IFtJTy5QYXRoXTo6R2V0RnVsbFBhdGgoJFBhdGgpLlRyaW1FbmQoJ1wnKQogICAgJHIgPSBbSU8uUGF0aF06OkdldEZ1bGxQYXRoKCRSb290KS5UcmltRW5kKCdcJykKICAgIHJldHVybiAkcC5FcXVhbHMoJHIsIFtTdHJpbmdDb21wYXJpc29uXTo6T3JkaW5hbElnbm9yZUNhc2UpIC1vciAkcC5TdGFydHNXaXRoKCRyICsgJ1wnLCBbU3RyaW5nQ29tcGFyaXNvbl06Ok9yZGluYWxJZ25vcmVDYXNlKQp9CgpmdW5jdGlvbiBBc3NlcnQtUmVtb3ZhbFBhdGgoW3N0cmluZ10kUGF0aCwgW3N0cmluZ10kUm9vdCwgW3N3aXRjaF0kRXh0ZXJuYWwpIHsKICAgICRmdWxsID0gW0lPLlBhdGhdOjpHZXRGdWxsUGF0aCgkUGF0aCkuVHJpbUVuZCgnXCcpCiAgICAkcm9vdEZ1bGwgPSBbSU8uUGF0aF06OkdldEZ1bGxQYXRoKCRSb290KS5UcmltRW5kKCdcJykKICAgIGlmICgtbm90ICRmdWxsIC1vciAkZnVsbCAtZXEgW0lPLlBhdGhdOjpHZXRQYXRoUm9vdCgkZnVsbCkuVHJpbUVuZCgnXCcpIC1vcgogICAgICAgIChUZXN0LVJlbW92YWxXaXRoaW4gJHJvb3RGdWxsICRmdWxsKSAtb3IgJGZ1bGwgLWVxICRlbnY6VVNFUlBST0ZJTEUgLW9yCiAgICAgICAgJGZ1bGwgLWVxICRlbnY6UHJvZ3JhbURhdGEgLW9yIChUZXN0LVJlbW92YWxXaXRoaW4gJGZ1bGwgJGVudjp3aW5kaXIpKSB7CiAgICAgICAgdGhyb3cgIlJlZnVzaW5nIHVuc2FmZSByZW1vdmFsIHBhdGg6ICRmdWxsIgogICAgfQogICAgaWYgKC1ub3QgJEV4dGVybmFsIC1hbmQgLW5vdCAoVGVzdC1SZW1vdmFsV2l0aGluICRmdWxsICRyb290RnVsbCkpIHsgdGhyb3cgIlJlbW92YWwgcGF0aCBpcyBvdXRzaWRlICRyb290RnVsbGA6ICRmdWxsIiB9CiAgICAjIEEgcmVjZWlwdCBjYW5ub3QgcmVkaXJlY3QgZGVsZXRpb24gdGhyb3VnaCBhIHBhcmVudCBqdW5jdGlvbi4KICAgICRjdXJzb3IgPSAkZnVsbAogICAgd2hpbGUgKCRjdXJzb3IpIHsKICAgICAgICAkaXRlbSA9IEdldC1JdGVtIC1MaXRlcmFsUGF0aCAkY3Vyc29yIC1Gb3JjZSAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQogICAgICAgIGlmICgkaXRlbSAtYW5kICgkaXRlbS5BdHRyaWJ1dGVzIC1iYW5kIFtJTy5GaWxlQXR0cmlidXRlc106OlJlcGFyc2VQb2ludCkpIHsgdGhyb3cgIktlcHQgbGlua2VkIHBhdGg6ICRmdWxsIiB9CiAgICAgICAgJGN1cnNvciA9IFNwbGl0LVBhdGggLVBhcmVudCAkY3Vyc29yCiAgICB9CiAgICByZXR1cm4gJGZ1bGwKfQoKZnVuY3Rpb24gUmVtb3ZlLVJlbW92YWxUcmVlKFtzdHJpbmddJFBhdGgpIHsKICAgICMgRG8gbm90IHVzZSBQUyA1LjEgcmVjdXJzaXZlIGRlbGV0aW9uIGFjcm9zcyBqdW5jdGlvbnMuIFJlbW92ZSBsaW5rcywKICAgICMgbmV2ZXIgdGhlaXIgdGFyZ2V0czsgZXZlcnkgdG9wLWxldmVsIHBhdGggd2FzIGNoZWNrZWQgYnkgdGhlIGNhbGxlci4KICAgICRpdGVtID0gR2V0LUl0ZW0gLUxpdGVyYWxQYXRoICRQYXRoIC1Gb3JjZSAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQogICAgaWYgKC1ub3QgJGl0ZW0pIHsgcmV0dXJuIH0KICAgIGlmICgkaXRlbS5QU0lzQ29udGFpbmVyKSB7CiAgICAgICAgaWYgKC1ub3QgKCRpdGVtLkF0dHJpYnV0ZXMgLWJhbmQgW0lPLkZpbGVBdHRyaWJ1dGVzXTo6UmVwYXJzZVBvaW50KSkgewogICAgICAgICAgICBmb3JlYWNoICgkY2hpbGQgaW4gR2V0LUNoaWxkSXRlbSAtTGl0ZXJhbFBhdGggJFBhdGggLUZvcmNlKSB7IFJlbW92ZS1SZW1vdmFsVHJlZSAkY2hpbGQuRnVsbE5hbWUgfQogICAgICAgIH0KICAgICAgICBbSU8uRGlyZWN0b3J5XTo6RGVsZXRlKCRpdGVtLkZ1bGxOYW1lKQogICAgfSBlbHNlIHsgUmVtb3ZlLUl0ZW0gLUxpdGVyYWxQYXRoICRpdGVtLkZ1bGxOYW1lIC1Gb3JjZSB9Cn0KCmZ1bmN0aW9uIEdldC1SZW1vdmFsU2l6ZShbc3RyaW5nW11dJFBhdGhzKSB7CiAgICBbbG9uZ10kc2l6ZSA9IDAKICAgIGZvcmVhY2ggKCRwYXRoIGluICRQYXRocykgewogICAgICAgIGlmICgtbm90IChUZXN0LVBhdGggLUxpdGVyYWxQYXRoICRwYXRoKSkgeyBjb250aW51ZSB9CiAgICAgICAgJGl0ZW0gPSBHZXQtSXRlbSAtTGl0ZXJhbFBhdGggJHBhdGggLUZvcmNlIC1FcnJvckFjdGlvbiBTdG9wCiAgICAgICAgaWYgKC1ub3QgJGl0ZW0gLW9yICgkaXRlbS5BdHRyaWJ1dGVzIC1iYW5kIFtJTy5GaWxlQXR0cmlidXRlc106OlJlcGFyc2VQb2ludCkpIHsgY29udGludWUgfQogICAgICAgIGlmICgkaXRlbS5QU0lzQ29udGFpbmVyKSB7ICRzaXplICs9IEdldC1SZW1vdmFsU2l6ZSBAKChHZXQtQ2hpbGRJdGVtIC1MaXRlcmFsUGF0aCAkcGF0aCAtRm9yY2UgLUVycm9yQWN0aW9uIFN0b3ApLkZ1bGxOYW1lKSB9CiAgICAgICAgZWxzZSB7ICRzaXplICs9ICRpdGVtLkxlbmd0aCB9CiAgICB9CiAgICByZXR1cm4gJHNpemUKfQoKZnVuY3Rpb24gRm9ybWF0LVJlbW92YWxTaXplKFtzdHJpbmdbXV0kUGF0aHMpIHsKICAgIHRyeSB7IHJldHVybiAiJChbbWF0aF06OlJvdW5kKChHZXQtUmVtb3ZhbFNpemUgJFBhdGhzKSAvIDFHQiwgMikpIEdCIiB9CiAgICBjYXRjaCB7IHJldHVybiAnc2l6ZSB1bmF2YWlsYWJsZScgfQp9CgpmdW5jdGlvbiBTaG93LVJlbW92YWxDaG9pY2UoJFBsYW4sIFtzdHJpbmddJFBhdGgpIHsKICAgIEFkZC1UeXBlIC1Bc3NlbWJseU5hbWUgU3lzdGVtLldpbmRvd3MuRm9ybXMKICAgIEFkZC1UeXBlIC1Bc3NlbWJseU5hbWUgU3lzdGVtLkRyYXdpbmcKICAgICRmb3JtID0gTmV3LU9iamVjdCBXaW5kb3dzLkZvcm1zLkZvcm0KICAgICRmb3JtLlRleHQgPSAnUmVtb3ZlIEV1Z2VuZSBQbGV4dXMnOyAkZm9ybS5DbGllbnRTaXplID0gTmV3LU9iamVjdCBEcmF3aW5nLlNpemUoNTgwLCAzNDApCiAgICAkZm9ybS5TdGFydFBvc2l0aW9uID0gJ0NlbnRlclNjcmVlbic7ICRmb3JtLkZvcm1Cb3JkZXJTdHlsZSA9ICdGaXhlZERpYWxvZyc7ICRmb3JtLk1heGltaXplQm94ID0gJGZhbHNlCiAgICAkbGFiZWwgPSBOZXctT2JqZWN0IFdpbmRvd3MuRm9ybXMuTGFiZWwKICAgICRsYWJlbC5TZXRCb3VuZHMoMjAsIDE4LCA1NDAsIDEwMikKICAgICRzb2Z0d2FyZVNpemUgPSBGb3JtYXQtUmVtb3ZhbFNpemUgQCgkUGxhbi5zb2Z0d2FyZSkKICAgICRsYWJlbC5UZXh0ID0gIlJlbW92ZSBFdWdlbmUgZnJvbSB0aGlzIGNvbXB1dGVyP2ByYG5gcmBuU29mdHdhcmU6ICRzb2Z0d2FyZVNpemVgcmBuJFBhdGhgcmBuT3JpZ2luYWwgbW9kZWwgZm9sZGVycyB3aWxsIGJlIGtlcHQuIgogICAgJGZvcm0uQ29udHJvbHMuQWRkKCRsYWJlbCkKICAgICRkYXRhID0gTmV3LU9iamVjdCBXaW5kb3dzLkZvcm1zLkNoZWNrQm94CiAgICAkZGF0YS5TZXRCb3VuZHMoMjAsIDEyNSwgNTQwLCA0OCkKICAgICRkYXRhLlRleHQgPSAiQWxzbyBkZWxldGUgc2V0dGluZ3MsIGFwcCBkYXRhIGFuZCBsb2dzYHJgbiQoRm9ybWF0LVJlbW92YWxTaXplIEAoJFBsYW4uZGF0YSkpIgogICAgJGRvd25sb2FkcyA9IE5ldy1PYmplY3QgV2luZG93cy5Gb3Jtcy5DaGVja0JveAogICAgJGRvd25sb2Fkcy5TZXRCb3VuZHMoMjAsIDE3OSwgNTQwLCA0OCkKICAgICRkb3dubG9hZHMuVGV4dCA9ICJBbHNvIGRlbGV0ZSBkb3dubG9hZGVkIGVuZ2luZXMgYW5kIG1vZGVsIGNvcGllc2ByYG4kKEZvcm1hdC1SZW1vdmFsU2l6ZSBAKCRQbGFuLmRvd25sb2FkcykpIgogICAgJGZvcm0uQ29udHJvbHMuQWRkUmFuZ2UoQCgkZGF0YSwgJGRvd25sb2FkcykpCiAgICAkcmVtb3ZlID0gTmV3LU9iamVjdCBXaW5kb3dzLkZvcm1zLkJ1dHRvbgogICAgJHJlbW92ZS5UZXh0ID0gJ1JlbW92ZSBFdWdlbmUnOyAkcmVtb3ZlLlNldEJvdW5kcygzMTUsIDI4MCwgMTM1LCAzNCk7ICRyZW1vdmUuRGlhbG9nUmVzdWx0ID0gJ09LJwogICAgJGNhbmNlbCA9IE5ldy1PYmplY3QgV2luZG93cy5Gb3Jtcy5CdXR0b24KICAgICRjYW5jZWwuVGV4dCA9ICdDYW5jZWwnOyAkY2FuY2VsLlNldEJvdW5kcyg0NjAsIDI4MCwgMTAwLCAzNCk7ICRjYW5jZWwuRGlhbG9nUmVzdWx0ID0gJ0NhbmNlbCcKICAgICRmb3JtLkNvbnRyb2xzLkFkZFJhbmdlKEAoJHJlbW92ZSwgJGNhbmNlbCkpOyAkZm9ybS5DYW5jZWxCdXR0b24gPSAkY2FuY2VsOyAkZm9ybS5BY2NlcHRCdXR0b24gPSAkY2FuY2VsCiAgICB0cnkgewogICAgICAgIGlmICgkZm9ybS5TaG93RGlhbG9nKCkgLW5lICdPSycpIHsgcmV0dXJuICRudWxsIH0KICAgICAgICByZXR1cm4gQHsgRGF0YSA9ICRkYXRhLkNoZWNrZWQ7IERvd25sb2FkcyA9ICRkb3dubG9hZHMuQ2hlY2tlZCB9CiAgICB9IGZpbmFsbHkgeyAkZm9ybS5EaXNwb3NlKCkgfQp9CgpmdW5jdGlvbiBHZXQtUmVtb3ZhbFBsYW4oW3N0cmluZ10kUGF0aCkgewogICAgJHJlY2VpcHQgPSBKb2luLVBhdGggJFBhdGggJ3VuaW5zdGFsbFxyZWNlaXB0JwogICAgJGZpbGUgPSBKb2luLVBhdGggJHJlY2VpcHQgJ2ludmVudG9yeS5qc29uJwogICAgJHB5dGhvbiA9IEpvaW4tUGF0aCAkUGF0aCAndmVudlxTY3JpcHRzXHB5dGhvbi5leGUnCiAgICBpZiAoKFRlc3QtUGF0aCAtTGl0ZXJhbFBhdGggJGZpbGUpIC1hbmQgKChUZXN0LVBhdGggLUxpdGVyYWxQYXRoIChKb2luLVBhdGggJHJlY2VpcHQgJ3JlbW92ZWQudHh0JykpIC1vciAtbm90IChUZXN0LVBhdGggLUxpdGVyYWxQYXRoICRweXRob24pKSkgewogICAgICAgIHJldHVybiAoR2V0LUNvbnRlbnQgLVJhdyAtRW5jb2RpbmcgVVRGOCAtTGl0ZXJhbFBhdGggJGZpbGUgfCBDb252ZXJ0RnJvbS1Kc29uKQogICAgfQogICAgTmV3LUl0ZW0gLUl0ZW1UeXBlIERpcmVjdG9yeSAtUGF0aCAkcmVjZWlwdCAtRm9yY2UgfCBPdXQtTnVsbAogICAgaWYgKFRlc3QtUGF0aCAtTGl0ZXJhbFBhdGggJHB5dGhvbikgewogICAgICAgICYgJHB5dGhvbiAtSSAoSm9pbi1QYXRoICRQYXRoICd1bmluc3RhbGxcaW52ZW50b3J5LnB5JykgLS1wcmVmaXggJFBhdGggLS1vdXRwdXQgJGZpbGUKICAgICAgICBpZiAoJExBU1RFWElUQ09ERSAtbmUgMCAtb3IgLW5vdCAoVGVzdC1QYXRoIC1MaXRlcmFsUGF0aCAkZmlsZSkpIHsgdGhyb3cgJ0NvdWxkIG5vdCBpbnZlbnRvcnkgdGhpcyBpbnN0YWxsYXRpb24uIE5vdGhpbmcgd2FzIHJlbW92ZWQuJyB9CiAgICAgICAgcmV0dXJuIChHZXQtQ29udGVudCAtUmF3IC1FbmNvZGluZyBVVEY4IC1MaXRlcmFsUGF0aCAkZmlsZSB8IENvbnZlcnRGcm9tLUpzb24pCiAgICB9CiAgICAjIEJyb2tlbiBpbnN0YWxsYXRpb246IHJlbW92ZSBvbmx5IGtub3duIHNvZnR3YXJlOyBuZXZlciBndWVzcyB3aGljaAogICAgIyBleHRlcm5hbCBmb2xkZXJzIG9yIHBlcnNvbmFsIGRhdGEgYmVsb25nZWQgdG8gaXQuCiAgICAkcGxhbiA9IEB7IHZlcnNpb24gPSAxOyBwcmVmaXggPSAkUGF0aDsgc29mdHdhcmUgPSBAKCd2ZW52JywncHl0aG9ucycsJ2JpbicsJy5jYWNoZVx1dicsJ3VwZGF0ZScpIHwgRm9yRWFjaC1PYmplY3QgeyBKb2luLVBhdGggJFBhdGggJF8gfQogICAgICAgIGRhdGEgPSBAKCk7IGRvd25sb2FkcyA9IEAoKTsgcHJvdGVjdGVkID0gQCgoSm9pbi1QYXRoICRQYXRoICdtb2RlbHMnKSkKICAgICAgICB3YXJuaW5ncyA9IEAoJ1B5dGhvbiBpcyBtaXNzaW5nLiBTZXR0aW5ncywgZG93bmxvYWRzIGFuZCBjcmVkZW50aWFscyB3ZXJlIGtlcHQ7IHJldmlldyB0aGUgcmVtYWluaW5nIGZvbGRlci4nKSB9CiAgICBbSU8uRmlsZV06OldyaXRlQWxsVGV4dCgkZmlsZSwgKCRwbGFuIHwgQ29udmVydFRvLUpzb24gLURlcHRoIDUpLCBbVGV4dC5VVEY4RW5jb2RpbmddOjpuZXcoJGZhbHNlKSkKICAgIHJldHVybiBbcHNjdXN0b21vYmplY3RdJHBsYW4KfQoKZnVuY3Rpb24gU3RvcC1SZW1vdmFsUHJvY2Vzc2VzKFtzdHJpbmddJFBhdGgpIHsKICAgICRwcm9jZXNzZXMgPSBAKEdldC1DaW1JbnN0YW5jZSBXaW4zMl9Qcm9jZXNzIHwgV2hlcmUtT2JqZWN0IHsKICAgICAgICAkXy5Qcm9jZXNzSWQgLW5lICRQSUQgLWFuZCAkXy5FeGVjdXRhYmxlUGF0aCAtYW5kIChUZXN0LVJlbW92YWxXaXRoaW4gJF8uRXhlY3V0YWJsZVBhdGggJFBhdGgpCiAgICB9KQogICAgZm9yZWFjaCAoJHByb2Nlc3MgaW4gJHByb2Nlc3NlcykgewogICAgICAgIFN0b3AtUHJvY2VzcyAtSWQgJHByb2Nlc3MuUHJvY2Vzc0lkIC1Gb3JjZSAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQogICAgICAgIFdhaXQtUHJvY2VzcyAtSWQgJHByb2Nlc3MuUHJvY2Vzc0lkIC1UaW1lb3V0IDE1IC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlCiAgICB9CiAgICBpZiAoR2V0LUNpbUluc3RhbmNlIFdpbjMyX1Byb2Nlc3MgfCBXaGVyZS1PYmplY3QgeyAkXy5Qcm9jZXNzSWQgLW5lICRQSUQgLWFuZCAkXy5FeGVjdXRhYmxlUGF0aCAtYW5kIChUZXN0LVJlbW92YWxXaXRoaW4gJF8uRXhlY3V0YWJsZVBhdGggJFBhdGgpIH0pIHsKICAgICAgICB0aHJvdyAnQSBFdWdlbmUgcHJvY2VzcyBpcyBzdGlsbCBydW5uaW5nLiBDbG9zZSBpdCBhbmQgcnVuIHJlbW92YWwgYWdhaW4uJwogICAgfQp9CgpmdW5jdGlvbiBSZW1vdmUtUmVtb3ZhbENyZWRlbnRpYWxzKFtzdHJpbmddJFBhdGgsIFtib29sXSRBc1N5c3RlbSkgewogICAgJHB5dGhvbiA9IEpvaW4tUGF0aCAkUGF0aCAndmVudlxTY3JpcHRzXHB5dGhvbi5leGUnCiAgICBpZiAoLW5vdCAoVGVzdC1QYXRoIC1MaXRlcmFsUGF0aCAkcHl0aG9uKSkgeyByZXR1cm4gQCgnQ3JlZGVudGlhbCBjbGVhbnVwIGNvdWxkIG5vdCBydW46IHRoZSBpbnN0YWxsZWQgUHl0aG9uIGlzIG1pc3NpbmcuJykgfQogICAgJGhlbHBlciA9IEpvaW4tUGF0aCAkUGF0aCAndW5pbnN0YWxsXGludmVudG9yeS5weScKICAgICRvdXRwdXQgPSBKb2luLVBhdGggJFBhdGggInVuaW5zdGFsbFxyZWNlaXB0XGNyZWRlbnRpYWxzLSQoaWYgKCRBc1N5c3RlbSkgeyAnc3lzdGVtJyB9IGVsc2UgeyAndXNlcicgfSkuanNvbiIKICAgIGlmIChUZXN0LVBhdGggLUxpdGVyYWxQYXRoICRvdXRwdXQpIHsgUmVtb3ZlLUl0ZW0gLUxpdGVyYWxQYXRoICRvdXRwdXQgLUZvcmNlIH0KICAgICRhcmdzVGV4dCA9ICctSSAiezB9IiAtLWtleXJpbmctb25seSAtLXByZWZpeCAiezF9IiAtLW91dHB1dCAiezJ9IicgLWYgJGhlbHBlciwgJFBhdGgsICRvdXRwdXQKICAgIGlmICgkQXNTeXN0ZW0pIHsKICAgICAgICAkdGFzayA9ICdFdWdlbmVQbGV4dXNSZW1vdmFsLScgKyBbZ3VpZF06Ok5ld0d1aWQoKS5Ub1N0cmluZygnTicpCiAgICAgICAgdHJ5IHsKICAgICAgICAgICAgJGFjdGlvbiA9IE5ldy1TY2hlZHVsZWRUYXNrQWN0aW9uIC1FeGVjdXRlICRweXRob24gLUFyZ3VtZW50ICRhcmdzVGV4dAogICAgICAgICAgICAkcHJpbmNpcGFsID0gTmV3LVNjaGVkdWxlZFRhc2tQcmluY2lwYWwgLVVzZXJJZCAnU1lTVEVNJyAtTG9nb25UeXBlIFNlcnZpY2VBY2NvdW50IC1SdW5MZXZlbCBIaWdoZXN0CiAgICAgICAgICAgIFJlZ2lzdGVyLVNjaGVkdWxlZFRhc2sgLVRhc2tOYW1lICR0YXNrIC1BY3Rpb24gJGFjdGlvbiAtUHJpbmNpcGFsICRwcmluY2lwYWwgLUZvcmNlIHwgT3V0LU51bGwKICAgICAgICAgICAgU3RhcnQtU2NoZWR1bGVkVGFzayAtVGFza05hbWUgJHRhc2sKICAgICAgICAgICAgJGRlYWRsaW5lID0gKEdldC1EYXRlKS5BZGRTZWNvbmRzKDQ1KQogICAgICAgICAgICBkbyB7IFN0YXJ0LVNsZWVwIC1NaWxsaXNlY29uZHMgMjUwIH0gd2hpbGUgKC1ub3QgKFRlc3QtUGF0aCAtTGl0ZXJhbFBhdGggJG91dHB1dCkgLWFuZCAoR2V0LURhdGUpIC1sdCAkZGVhZGxpbmUpCiAgICAgICAgICAgIGlmICgtbm90IChUZXN0LVBhdGggLUxpdGVyYWxQYXRoICRvdXRwdXQpKSB7IHRocm93ICdTWVNURU0gY3JlZGVudGlhbCBjbGVhbnVwIGRpZCBub3QgZmluaXNoIGluIDQ1IHNlY29uZHMuJyB9CiAgICAgICAgfSBmaW5hbGx5IHsKICAgICAgICAgICAgU3RvcC1TY2hlZHVsZWRUYXNrIC1UYXNrTmFtZSAkdGFzayAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQogICAgICAgICAgICBVbnJlZ2lzdGVyLVNjaGVkdWxlZFRhc2sgLVRhc2tOYW1lICR0YXNrIC1Db25maXJtOiRmYWxzZSAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQogICAgICAgIH0KICAgIH0gZWxzZSB7CiAgICAgICAgJiAkcHl0aG9uIC1JICRoZWxwZXIgLS1rZXlyaW5nLW9ubHkgLS1wcmVmaXggJFBhdGggLS1vdXRwdXQgJG91dHB1dAogICAgICAgIGlmICgkTEFTVEVYSVRDT0RFIC1uZSAwKSB7IHRocm93ICdVc2VyIGNyZWRlbnRpYWwgY2xlYW51cCBmYWlsZWQuJyB9CiAgICB9CiAgICAkcmVzdWx0ID0gR2V0LUNvbnRlbnQgLVJhdyAtRW5jb2RpbmcgVVRGOCAtTGl0ZXJhbFBhdGggJG91dHB1dCB8IENvbnZlcnRGcm9tLUpzb24KICAgIHJldHVybiBAKCRyZXN1bHQud2FybmluZ3MpCn0KCmZ1bmN0aW9uIFJlbW92ZS1SZW1vdmFsRmlyZXdhbGwgewogICAgJHJ1bGVzID0gQChHZXQtTmV0RmlyZXdhbGxSdWxlIC1FcnJvckFjdGlvbiBTdG9wIHwgV2hlcmUtT2JqZWN0IHsgJF8uRGlzcGxheU5hbWUgLWVxICdFdWdlbmUgUGxleHVzJyB9KQogICAgaWYgKC1ub3QgJHJ1bGVzLkNvdW50KSB7IHJldHVybiB9CiAgICBpZiAoVGVzdC1SZW1vdmFsQWRtaW4pIHsgJHJ1bGVzIHwgUmVtb3ZlLU5ldEZpcmV3YWxsUnVsZSAtRXJyb3JBY3Rpb24gU3RvcDsgcmV0dXJuIH0KICAgICMgT25seSB0aGlzIG1hY2hpbmUtd2lkZSBmaXJld2FsbCBvcGVyYXRpb24gbmVlZHMgZWxldmF0aW9uIGZvciBhCiAgICAjIHBlci11c2VyIGluc3RhbGw7IGRvIG5vdCBzd2l0Y2ggYWNjb3VudHMgZm9yIGl0cyBkYXRhIG9yIHZhdWx0LgogICAgJGNvZGUgPSAidHJ5IHsgR2V0LU5ldEZpcmV3YWxsUnVsZSAtRXJyb3JBY3Rpb24gU3RvcCB8IFdoZXJlLU9iamVjdCB7IGAkXy5EaXNwbGF5TmFtZSAtZXEgJ0V1Z2VuZSBQbGV4dXMnIH0gfCBSZW1vdmUtTmV0RmlyZXdhbGxSdWxlIC1FcnJvckFjdGlvbiBTdG9wIH0gY2F0Y2ggeyBleGl0IDEgfSIKICAgICRlbmNvZGVkID0gW0NvbnZlcnRdOjpUb0Jhc2U2NFN0cmluZyhbVGV4dC5FbmNvZGluZ106OlVuaWNvZGUuR2V0Qnl0ZXMoJGNvZGUpKQogICAgJGNoaWxkID0gU3RhcnQtUHJvY2VzcyBwb3dlcnNoZWxsLmV4ZSAtQXJndW1lbnRMaXN0ICItTm9Qcm9maWxlIC1FbmNvZGVkQ29tbWFuZCAkZW5jb2RlZCIgLVZlcmIgUnVuQXMgLVdpbmRvd1N0eWxlIEhpZGRlbiAtV2FpdCAtUGFzc1RocnUKICAgIGlmICgkY2hpbGQuRXhpdENvZGUgLW5lIDApIHsgdGhyb3cgJ0FkbWluaXN0cmF0b3IgZmlyZXdhbGwgY2xlYW51cCBmYWlsZWQgb3Igd2FzIGNhbmNlbGxlZC4nIH0KfQoKZnVuY3Rpb24gUmVtb3ZlLVJlbW92YWxJbnRlZ3JhdGlvbihbc3RyaW5nXSRQYXRoKSB7CiAgICAkc2VydmljZXMgPSBAKEdldC1DaW1JbnN0YW5jZSBXaW4zMl9TZXJ2aWNlIHwgV2hlcmUtT2JqZWN0IHsKICAgICAgICAoJF8uTmFtZSAtZXEgJ0V1Z2VuZVBsZXh1c0FnZW50JyAtb3IgJF8uTmFtZSAtbGlrZSAnRXVnZW5lUGxleHVzQXBwLSonKSAtYW5kCiAgICAgICAgJF8uUGF0aE5hbWUgLWFuZCAkXy5QYXRoTmFtZS5JbmRleE9mKCRQYXRoLlRyaW1FbmQoJ1wnKSArICdcJywgW1N0cmluZ0NvbXBhcmlzb25dOjpPcmRpbmFsSWdub3JlQ2FzZSkgLWdlIDAKICAgIH0pCiAgICBmb3JlYWNoICgkc2VydmljZSBpbiAkc2VydmljZXMpIHsKICAgICAgICBpZiAoJHNlcnZpY2UuU3RhdGUgLW5lICdTdG9wcGVkJykgeyBTdG9wLVNlcnZpY2UgLU5hbWUgJHNlcnZpY2UuTmFtZSAtRm9yY2UgfQogICAgICAgICYgc2MuZXhlIGRlbGV0ZSAkc2VydmljZS5OYW1lIHwgT3V0LU51bGwKICAgICAgICBpZiAoJExBU1RFWElUQ09ERSAtbmUgMCkgeyB0aHJvdyAiV2luZG93cyBjb3VsZCBub3QgdW5yZWdpc3RlciAkKCRzZXJ2aWNlLk5hbWUpLiIgfQogICAgfQogICAgZm9yZWFjaCAoJG5hbWUgaW4gQCgnRXVnZW5lUGxleHVzQWdlbnQnLCAnRXVnZW5lUGxleHVzVHJheScpKSB7CiAgICAgICAgJHRhc2sgPSBHZXQtU2NoZWR1bGVkVGFzayAtVGFza05hbWUgJG5hbWUgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUKICAgICAgICBpZiAoJHRhc2sgLWFuZCBAKCR0YXNrLkFjdGlvbnMgfCBXaGVyZS1PYmplY3QgeyAkXy5FeGVjdXRlIC1hbmQgKFRlc3QtUmVtb3ZhbFdpdGhpbiAkXy5FeGVjdXRlICRQYXRoKSB9KS5Db3VudCkgewogICAgICAgICAgICBTdG9wLVNjaGVkdWxlZFRhc2sgLVRhc2tOYW1lICRuYW1lCiAgICAgICAgICAgIFVucmVnaXN0ZXItU2NoZWR1bGVkVGFzayAtVGFza05hbWUgJG5hbWUgLUNvbmZpcm06JGZhbHNlCiAgICAgICAgfQogICAgfQogICAgU3RvcC1SZW1vdmFsUHJvY2Vzc2VzICRQYXRoCiAgICBmb3JlYWNoICgkc2NvcGUgaW4gQCgnVXNlcicsICdNYWNoaW5lJykpIHsKICAgICAgICBpZiAoJHNjb3BlIC1lcSAnTWFjaGluZScgLWFuZCAtbm90IChUZXN0LVJlbW92YWxBZG1pbikpIHsgY29udGludWUgfQogICAgICAgICRjZmcgPSBbRW52aXJvbm1lbnRdOjpHZXRFbnZpcm9ubWVudFZhcmlhYmxlKCdFVUdFTkVfUExFWFVTX0FHRU5UX0NPTkZJR19GSUxFJywgJHNjb3BlKQogICAgICAgIGlmICgkY2ZnIC1hbmQgKFRlc3QtUmVtb3ZhbFdpdGhpbiAkY2ZnICRQYXRoKSkgewogICAgICAgICAgICBmb3JlYWNoICgkbmFtZSBpbiBAKCdFVUdFTkVfUExFWFVTX0FHRU5UX0NPTkZJR19GSUxFJywnRVVHRU5FX1BMRVhVU19BR0VOVF9CSU5EX0hPU1QnLCdFVUdFTkVfUExFWFVTX0FHRU5UX0JJTkRfUE9SVCcsJ0VVR0VORV9QTEVYVVNfQUdFTlRfRU5HSU5FX1JPT1QnLCdFVUdFTkVfUExFWFVTX0xJQlJBUllfREVGQVVMVF9NT0RFTF9ST09UUycpKSB7CiAgICAgICAgICAgICAgICBbRW52aXJvbm1lbnRdOjpTZXRFbnZpcm9ubWVudFZhcmlhYmxlKCRuYW1lLCAkbnVsbCwgJHNjb3BlKQogICAgICAgICAgICB9CiAgICAgICAgfQogICAgfQogICAgZm9yZWFjaCAoJHByb2dyYW1zIGluIEAoKEpvaW4tUGF0aCAkZW52OkFQUERBVEEgJ01pY3Jvc29mdFxXaW5kb3dzXFN0YXJ0IE1lbnVcUHJvZ3JhbXMnKSwgKEpvaW4tUGF0aCAkZW52OlByb2dyYW1EYXRhICdNaWNyb3NvZnRcV2luZG93c1xTdGFydCBNZW51XFByb2dyYW1zJykpKSB7CiAgICAgICAgJGxpbmsgPSBKb2luLVBhdGggJHByb2dyYW1zICdFdWdlbmUgUGxleHVzLmxuaycKICAgICAgICBpZiAoVGVzdC1QYXRoIC1MaXRlcmFsUGF0aCAkbGluaykgewogICAgICAgICAgICAkc2hvcnRjdXQgPSAoTmV3LU9iamVjdCAtQ29tT2JqZWN0IFdTY3JpcHQuU2hlbGwpLkNyZWF0ZVNob3J0Y3V0KCRsaW5rKQogICAgICAgICAgICBpZiAoJHNob3J0Y3V0LlRhcmdldFBhdGggLWFuZCAoVGVzdC1SZW1vdmFsV2l0aGluICRzaG9ydGN1dC5UYXJnZXRQYXRoICRQYXRoKSkgeyBSZW1vdmUtSXRlbSAtTGl0ZXJhbFBhdGggJGxpbmsgLUZvcmNlIH0KICAgICAgICB9CiAgICB9Cn0KCmZ1bmN0aW9uIFJlbW92ZS1SZW1vdmFsRmlsZXMoJFBsYW4sIFtzdHJpbmddJFBhdGgsIFtib29sXSREb3dubG9hZHMsIFtib29sXSREYXRhKSB7CiAgICAkd2FybmluZ3MgPSBOZXctT2JqZWN0IENvbGxlY3Rpb25zLkdlbmVyaWMuTGlzdFtzdHJpbmddCiAgICBmb3JlYWNoICgka2luZCBpbiBAKCdzb2Z0d2FyZScsICdkb3dubG9hZHMnLCAnZGF0YScpKSB7CiAgICAgICAgaWYgKCgka2luZCAtZXEgJ2Rvd25sb2FkcycgLWFuZCAtbm90ICREb3dubG9hZHMpIC1vciAoJGtpbmQgLWVxICdkYXRhJyAtYW5kIC1ub3QgJERhdGEpKSB7IGNvbnRpbnVlIH0KICAgICAgICBmb3JlYWNoICgkb3JpZ2luYWwgaW4gJFBsYW4uJGtpbmQpIHsKICAgICAgICAgICAgJGNhbmRpZGF0ZSA9IGlmIChUZXN0LVJlbW92YWxXaXRoaW4gJG9yaWdpbmFsICRQbGFuLnByZWZpeCkgeyAkUGF0aCArICRvcmlnaW5hbC5TdWJzdHJpbmcoJFBsYW4ucHJlZml4LlRyaW1FbmQoJ1wnKS5MZW5ndGgpIH0gZWxzZSB7ICRvcmlnaW5hbCB9CiAgICAgICAgICAgIHRyeSB7CiAgICAgICAgICAgICAgICAkZnVsbCA9IEFzc2VydC1SZW1vdmFsUGF0aCAkY2FuZGlkYXRlICRQYXRoIC1FeHRlcm5hbDooJGtpbmQgLWVxICdkb3dubG9hZHMnKQogICAgICAgICAgICAgICAgZm9yZWFjaCAoJHByb3RlY3RlZCBpbiAkUGxhbi5wcm90ZWN0ZWQpIHsKICAgICAgICAgICAgICAgICAgICAkcHJvdGVjdGVkUGF0aCA9IGlmIChUZXN0LVJlbW92YWxXaXRoaW4gJHByb3RlY3RlZCAkUGxhbi5wcmVmaXgpIHsgJFBhdGggKyAkcHJvdGVjdGVkLlN1YnN0cmluZygkUGxhbi5wcmVmaXguVHJpbUVuZCgnXCcpLkxlbmd0aCkgfSBlbHNlIHsgJHByb3RlY3RlZCB9CiAgICAgICAgICAgICAgICAgICAgaWYgKChUZXN0LVJlbW92YWxXaXRoaW4gJGZ1bGwgJHByb3RlY3RlZFBhdGgpIC1vciAoVGVzdC1SZW1vdmFsV2l0aGluICRwcm90ZWN0ZWRQYXRoICRmdWxsKSkgeyB0aHJvdyAiS2VwdCAkZnVsbGA6IGl0IG92ZXJsYXBzIGFuIG9yaWdpbmFsIG1vZGVsIGZvbGRlci4iIH0KICAgICAgICAgICAgICAgIH0KICAgICAgICAgICAgICAgIFJlbW92ZS1SZW1vdmFsVHJlZSAkZnVsbAogICAgICAgICAgICB9IGNhdGNoIHsgJHdhcm5pbmdzLkFkZCgkXy5FeGNlcHRpb24uTWVzc2FnZSkgfQogICAgICAgIH0KICAgIH0KICAgIHJldHVybiAkd2FybmluZ3MuVG9BcnJheSgpCn0KCmZ1bmN0aW9uIEludm9rZS1SZW1vdmFsKFtzdHJpbmddJFBhdGgsIFtib29sXSRTaG93V2luZG93LCBbYm9vbF0kRG93bmxvYWRzLCBbYm9vbF0kRGF0YSkgewogICAgJFBhdGggPSBbSU8uUGF0aF06OkdldEZ1bGxQYXRoKCRQYXRoKS5UcmltRW5kKCdcJykKICAgIGlmICgtbm90IChUZXN0LVBhdGggLUxpdGVyYWxQYXRoICRQYXRoKSkgeyBXcml0ZS1Ib3N0ICJOb3RoaW5nIGluc3RhbGxlZCBhdCAkUGF0aCI7IHJldHVybiB9CiAgICBpZiAoJFBhdGggLWVxICRlbnY6VVNFUlBST0ZJTEUgLW9yICRQYXRoIC1lcSAkZW52OlByb2dyYW1EYXRhIC1vcgogICAgICAgICRQYXRoIC1lcSAkZW52OlByb2dyYW1GaWxlcyAtb3IgKFRlc3QtUmVtb3ZhbFdpdGhpbiAkUGF0aCAkZW52OndpbmRpcikgLW9yCiAgICAgICAgJFBhdGggLWVxIFtJTy5QYXRoXTo6R2V0UGF0aFJvb3QoJFBhdGgpLlRyaW1FbmQoJ1wnKSkgeyB0aHJvdyAiTm90IGFuIGluc3RhbGxhdGlvbiBmb2xkZXI6ICRQYXRoIiB9CiAgICBpZiAoLW5vdCAoKFRlc3QtUGF0aCAtTGl0ZXJhbFBhdGggKEpvaW4tUGF0aCAkUGF0aCAnYWdlbnQueWFtbCcpKSAtb3IKICAgICAgICAoVGVzdC1QYXRoIC1MaXRlcmFsUGF0aCAoSm9pbi1QYXRoICRQYXRoICdub2RlLnlhbWwnKSkgLW9yCiAgICAgICAgKFRlc3QtUGF0aCAtTGl0ZXJhbFBhdGggKEpvaW4tUGF0aCAkUGF0aCAnYmluXHV2LmV4ZScpKSAtb3IKICAgICAgICAoVGVzdC1QYXRoIC1MaXRlcmFsUGF0aCAoSm9pbi1QYXRoICRQYXRoICd1bmluc3RhbGxccmVjZWlwdFxpbnZlbnRvcnkuanNvbicpKSkpIHsKICAgICAgICB0aHJvdyAiTm8gRXVnZW5lIGluc3RhbGxhdGlvbiBvciByZW1vdmFsIHJlY2VpcHQgYXQgJFBhdGguIE5vdGhpbmcgd2FzIHJlbW92ZWQuIgogICAgfQogICAgJGN1cnNvciA9ICRQYXRoCiAgICB3aGlsZSAoJGN1cnNvcikgewogICAgICAgICRpdGVtID0gR2V0LUl0ZW0gLUxpdGVyYWxQYXRoICRjdXJzb3IgLUZvcmNlIC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlCiAgICAgICAgaWYgKCRpdGVtIC1hbmQgKCRpdGVtLkF0dHJpYnV0ZXMgLWJhbmQgW0lPLkZpbGVBdHRyaWJ1dGVzXTo6UmVwYXJzZVBvaW50KSkgeyB0aHJvdyAiUmVmdXNpbmcgYSBsaW5rZWQgaW5zdGFsbGF0aW9uIGZvbGRlcjogJFBhdGgiIH0KICAgICAgICAkY3Vyc29yID0gU3BsaXQtUGF0aCAtUGFyZW50ICRjdXJzb3IKICAgIH0KICAgICRwbGFuID0gR2V0LVJlbW92YWxQbGFuICRQYXRoCiAgICBpZiAoJFNob3dXaW5kb3cpIHsKICAgICAgICAkZGlzcGxheSA9IEB7fQogICAgICAgIGZvcmVhY2ggKCRraW5kIGluIEAoJ3NvZnR3YXJlJywnZGF0YScsJ2Rvd25sb2FkcycpKSB7CiAgICAgICAgICAgICRkaXNwbGF5WyRraW5kXSA9IEAoJHBsYW4uJGtpbmQgfCBGb3JFYWNoLU9iamVjdCB7CiAgICAgICAgICAgICAgICBpZiAoVGVzdC1SZW1vdmFsV2l0aGluICRfICRwbGFuLnByZWZpeCkgeyAkUGF0aCArICRfLlN1YnN0cmluZygkcGxhbi5wcmVmaXguVHJpbUVuZCgnXCcpLkxlbmd0aCkgfSBlbHNlIHsgJF8gfQogICAgICAgICAgICB9KQogICAgICAgIH0KICAgICAgICAkY2hvaWNlID0gU2hvdy1SZW1vdmFsQ2hvaWNlICRkaXNwbGF5ICRQYXRoCiAgICAgICAgaWYgKCRudWxsIC1lcSAkY2hvaWNlKSB7IHJldHVybiB9CiAgICAgICAgJERvd25sb2FkcyA9ICRjaG9pY2UuRG93bmxvYWRzOyAkRGF0YSA9ICRjaG9pY2UuRGF0YQogICAgfQogICAgJHdhcm5pbmdzID0gTmV3LU9iamVjdCBDb2xsZWN0aW9ucy5HZW5lcmljLkxpc3Rbc3RyaW5nXQogICAgZm9yZWFjaCAoJHdhcm5pbmcgaW4gJHBsYW4ud2FybmluZ3MpIHsgJHdhcm5pbmdzLkFkZCgkd2FybmluZykgfQogICAgJHJlbW92ZWRCZWZvcmUgPSBUZXN0LVBhdGggLUxpdGVyYWxQYXRoIChKb2luLVBhdGggJFBhdGggJ3VuaW5zdGFsbFxyZWNlaXB0XHJlbW92ZWQudHh0JykKICAgIGlmICgtbm90ICRyZW1vdmVkQmVmb3JlKSB7CiAgICAgICAgJHNlcnZpY2UgPSBHZXQtQ2ltSW5zdGFuY2UgV2luMzJfU2VydmljZSAtRmlsdGVyICJOYW1lPSdFdWdlbmVQbGV4dXNBZ2VudCciIHwgV2hlcmUtT2JqZWN0IHsgJF8uUGF0aE5hbWUgLWFuZCAkXy5QYXRoTmFtZS5JbmRleE9mKCRQYXRoICsgJ1wnLCBbU3RyaW5nQ29tcGFyaXNvbl06Ok9yZGluYWxJZ25vcmVDYXNlKSAtZ2UgMCB9CiAgICAgICAgIyBTdG9wIGZpcnN0LCB3aGlsZSBQeXRob24gYW5kIHRoZSBzZXJ2aWNlIGFjY291bnQncyBjcmVkZW50aWFsIHZhdWx0CiAgICAgICAgIyBzdGlsbCBleGlzdC4gQSB0ZW1wb3JhcnkgU1lTVEVNIHRhc2sgb3BlbnMgdGhhdCBhY2NvdW50J3MgdmF1bHQuCiAgICAgICAgaWYgKCRzZXJ2aWNlIC1hbmQgJHNlcnZpY2UuU3RhdGUgLW5lICdTdG9wcGVkJykgeyBTdG9wLVNlcnZpY2UgLU5hbWUgJHNlcnZpY2UuTmFtZSAtRm9yY2UgfQogICAgICAgIHRyeSB7IGZvcmVhY2ggKCR3IGluIEAoUmVtb3ZlLVJlbW92YWxDcmVkZW50aWFscyAkUGF0aCAkZmFsc2UpKSB7ICR3YXJuaW5ncy5BZGQoJHcpIH0gfSBjYXRjaCB7ICR3YXJuaW5ncy5BZGQoJF8uRXhjZXB0aW9uLk1lc3NhZ2UpIH0KICAgICAgICBpZiAoJHNlcnZpY2UgLWFuZCAkc2VydmljZS5TdGFydE5hbWUgLWVxICdMb2NhbFN5c3RlbScpIHsKICAgICAgICAgICAgdHJ5IHsgZm9yZWFjaCAoJHcgaW4gQChSZW1vdmUtUmVtb3ZhbENyZWRlbnRpYWxzICRQYXRoICR0cnVlKSkgeyAkd2FybmluZ3MuQWRkKCR3KSB9IH0gY2F0Y2ggeyAkd2FybmluZ3MuQWRkKCRfLkV4Y2VwdGlvbi5NZXNzYWdlKSB9CiAgICAgICAgfQogICAgICAgIFJlbW92ZS1SZW1vdmFsSW50ZWdyYXRpb24gJFBhdGgKICAgICAgICB0cnkgewogICAgICAgICAgICAjIFRoZSBsZWdhY3kgcnVsZSBpcyBzaGFyZWQ6IHJldGFpbiBpdCB3aGlsZSBhbm90aGVyIEV1Z2VuZQogICAgICAgICAgICAjIHNlcnZpY2UvdGFzayBzdGlsbCB1c2VzIHRoaXMgbWFjaGluZS4KICAgICAgICAgICAgJG90aGVyID0gQChHZXQtQ2ltSW5zdGFuY2UgV2luMzJfU2VydmljZSAtRmlsdGVyICJOYW1lPSdFdWdlbmVQbGV4dXNBZ2VudCciIHwgV2hlcmUtT2JqZWN0IHsgJF8uUGF0aE5hbWUgLWFuZCAkXy5QYXRoTmFtZS5JbmRleE9mKCRQYXRoICsgJ1wnLCBbU3RyaW5nQ29tcGFyaXNvbl06Ok9yZGluYWxJZ25vcmVDYXNlKSAtbHQgMCB9KS5Db3VudCAtZ3QgMCAtb3IKICAgICAgICAgICAgICAgIFtib29sXShHZXQtU2NoZWR1bGVkVGFzayAtVGFza05hbWUgJ0V1Z2VuZVBsZXh1c0FnZW50JyAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZSkKICAgICAgICAgICAgaWYgKC1ub3QgJG90aGVyKSB7CiAgICAgICAgICAgICAgICBSZW1vdmUtUmVtb3ZhbEZpcmV3YWxsCiAgICAgICAgICAgIH0gZWxzZSB7ICR3YXJuaW5ncy5BZGQoJ1RoZSBzaGFyZWQgRXVnZW5lIGZpcmV3YWxsIHJ1bGUgd2FzIGtlcHQgZm9yIGFub3RoZXIgaW5zdGFsbGF0aW9uLicpIH0KICAgICAgICB9IGNhdGNoIHsgJHdhcm5pbmdzLkFkZCgiRmlyZXdhbGwgY2xlYW51cCBmYWlsZWQ6ICQoJF8uRXhjZXB0aW9uLk1lc3NhZ2UpLiBSZW1vdmUgdGhlICdFdWdlbmUgUGxleHVzJyBydWxlIGluIFdpbmRvd3MgRGVmZW5kZXIgRmlyZXdhbGwuIikgfQogICAgICAgIFtJTy5GaWxlXTo6V3JpdGVBbGxMaW5lcygoSm9pbi1QYXRoICRQYXRoICd1bmluc3RhbGxccmVjZWlwdFxpbnRlZ3JhdGlvbi13YXJuaW5ncy50eHQnKSwgJHdhcm5pbmdzLlRvQXJyYXkoKSkKICAgIH0gZWxzZSB7CiAgICAgICAgJHByaW9yID0gSm9pbi1QYXRoICRQYXRoICd1bmluc3RhbGxccmVjZWlwdFxpbnRlZ3JhdGlvbi13YXJuaW5ncy50eHQnCiAgICAgICAgaWYgKFRlc3QtUGF0aCAtTGl0ZXJhbFBhdGggJHByaW9yKSB7CiAgICAgICAgICAgIGZvcmVhY2ggKCR3IGluIEdldC1Db250ZW50IC1MaXRlcmFsUGF0aCAkcHJpb3IpIHsgJHdhcm5pbmdzLkFkZCgiUHJldmlvdXNseSByZXBvcnRlZDogJHciKSB9CiAgICAgICAgfQogICAgfQogICAgZm9yZWFjaCAoJHcgaW4gQChSZW1vdmUtUmVtb3ZhbEZpbGVzICRwbGFuICRQYXRoICREb3dubG9hZHMgJERhdGEpKSB7ICR3YXJuaW5ncy5BZGQoJHcpIH0KICAgICMgUmV0YWluIHRoZSBvZmZsaW5lIGhlbHBlciB3aXRoIHRoZSBkYXRhLCBidXQgcmVtb3ZlIHRoZSBPUyBhcHAgZW50cnkuCiAgICBmb3JlYWNoICgkaGl2ZSBpbiBAKCdIS0NVOicsICdIS0xNOicpKSB7CiAgICAgICAgaWYgKCRoaXZlIC1lcSAnSEtMTTonIC1hbmQgLW5vdCAoVGVzdC1SZW1vdmFsQWRtaW4pKSB7IGNvbnRpbnVlIH0KICAgICAgICAka2V5ID0gIiRoaXZlXFNvZnR3YXJlXE1pY3Jvc29mdFxXaW5kb3dzXEN1cnJlbnRWZXJzaW9uXFVuaW5zdGFsbFxFdWdlbmVQbGV4dXMtJChHZXQtUmVtb3ZhbElkICRwbGFuLnByZWZpeCkiCiAgICAgICAgaWYgKFRlc3QtUGF0aCAtTGl0ZXJhbFBhdGggJGtleSkgeyBSZW1vdmUtSXRlbSAtTGl0ZXJhbFBhdGggJGtleSAtUmVjdXJzZSAtRm9yY2UgfQogICAgfQogICAgJGtlZXAgPSAkUGF0aAogICAgaWYgKC1ub3QgJHJlbW92ZWRCZWZvcmUgLWFuZCAkUGF0aCAtbm90bWF0Y2ggJ1wucmVtb3ZlZC1cZCskJykgewogICAgICAgICRrZWVwID0gIiRQYXRoLnJlbW92ZWQtJChHZXQtRGF0ZSAtRm9ybWF0IHl5eXlNTWRkSEhtbXNzKSIKICAgICAgICAjIFZlcmlmeSB0aGUgc2libGluZyBkZXN0aW5hdGlvbiBhbmQgc291cmNlIGJlZm9yZSB0aGUgZGlyZWN0b3J5IG1vdmUuCiAgICAgICAgaWYgKChTcGxpdC1QYXRoIC1QYXJlbnQgJGtlZXApIC1uZSAoU3BsaXQtUGF0aCAtUGFyZW50ICRQYXRoKSkgeyB0aHJvdyAnSW52YWxpZCByZW1vdmFsIGRlc3RpbmF0aW9uLicgfQogICAgICAgIHRyeSB7IFtJTy5EaXJlY3RvcnldOjpNb3ZlKCRQYXRoLCAka2VlcCkgfQogICAgICAgIGNhdGNoIHsKICAgICAgICAgICAgJGRldGFpbCA9ICJTdGFydHVwIGlzIGRpc2FibGVkLCBidXQgcmV0YWluZWQgZmlsZXMgY291bGQgbm90IGJlIG1vdmVkIGZyb20gJFBhdGhgOiAkKCRfLkV4Y2VwdGlvbi5NZXNzYWdlKS4gQ2xvc2UgcHJvZ3JhbXMgdXNpbmcgdGhhdCBmb2xkZXIgYW5kIHJ1biBpdHMgdW5pbnN0YWxsXHJlbW92ZS5wczEgYWdhaW4uIgogICAgICAgICAgICBbSU8uRmlsZV06OldyaXRlQWxsVGV4dCgoSm9pbi1QYXRoICRQYXRoICd1bmluc3RhbGxccmVjZWlwdFxyZXBvcnQudHh0JyksICRkZXRhaWwgKyAiYHJgbiIgKyAoJHdhcm5pbmdzIC1qb2luICJgcmBuIiksIFtUZXh0LlVURjhFbmNvZGluZ106Om5ldygkZmFsc2UpKQogICAgICAgICAgICB0aHJvdyAkZGV0YWlsCiAgICAgICAgfQogICAgfQogICAgJHJlY2VpcHQgPSBKb2luLVBhdGggJGtlZXAgJ3VuaW5zdGFsbFxyZWNlaXB0JwogICAgW0lPLkZpbGVdOjpXcml0ZUFsbFRleHQoKEpvaW4tUGF0aCAkcmVjZWlwdCAncmVtb3ZlZC50eHQnKSwgJ1N0YXJ0dXAgZGlzYWJsZWQ7IHNlZSByZXBvcnQudHh0IGZvciBhbnkgcmVtYWluaW5nIHdvcmsuJykKICAgICRyZW1haW5pbmdEb3dubG9hZHMgPSBAKCRwbGFuLmRvd25sb2FkcyB8IEZvckVhY2gtT2JqZWN0IHsKICAgICAgICBpZiAoVGVzdC1SZW1vdmFsV2l0aGluICRfICRwbGFuLnByZWZpeCkgeyAka2VlcCArICRfLlN1YnN0cmluZygkcGxhbi5wcmVmaXguVHJpbUVuZCgnXCcpLkxlbmd0aCkgfSBlbHNlIHsgJF8gfQogICAgfSB8IFdoZXJlLU9iamVjdCB7IFRlc3QtUGF0aCAtTGl0ZXJhbFBhdGggJF8gfSkKICAgICRyZXBvcnQgPSAiRXVnZW5lJ3MgcmVtb3ZhbCBmaW5pc2hlZCQoaWYgKCR3YXJuaW5ncy5Db3VudCkgeyAnIHdpdGggaXRlbXMgdG8gcmV2aWV3JyB9KS5gcmBuUmV0YWluZWQgZmlsZXMgYW5kIGNsZWFudXAgdXRpbGl0eTogJGtlZXBgcmBuT3JpZ2luYWwgbW9kZWwgZm9sZGVycyB3ZXJlIGtlcHQuYHJgbiIKICAgIGlmICgkcmVtYWluaW5nRG93bmxvYWRzLkNvdW50KSB7ICRyZXBvcnQgKz0gIlJldGFpbmVkIGRvd25sb2FkczpgcmBuJCgkcmVtYWluaW5nRG93bmxvYWRzIC1qb2luICJgcmBuIilgcmBuIiB9CiAgICAkcmVwb3J0ICs9ICJUbyBjaGFuZ2UgeW91ciBjbGVhbnVwIGNob2ljZXMsIG9wZW4gUG93ZXJTaGVsbCQoaWYgKFRlc3QtUmVtb3ZhbEFkbWluKSB7ICcgdXNpbmcgUnVuIGFzIGFkbWluaXN0cmF0b3InIH0pIGFuZCBydW46YHJgbnBvd2Vyc2hlbGwuZXhlIC1Ob1Byb2ZpbGUgLUV4ZWN1dGlvblBvbGljeSBCeXBhc3MgLUZpbGUgYCIka2VlcFx1bmluc3RhbGxccmVtb3ZlLnBzMWAiIC1JbnRlcmFjdGl2ZWByYG4iCiAgICBpZiAoJHdhcm5pbmdzLkNvdW50KSB7ICRyZXBvcnQgKz0gIkl0ZW1zIHRvIHJldmlldzpgcmBuJCgkd2FybmluZ3MgLWpvaW4gImByYG4iKWByYG4iIH0KICAgIFtJTy5GaWxlXTo6V3JpdGVBbGxUZXh0KChKb2luLVBhdGggJHJlY2VpcHQgJ3JlcG9ydC50eHQnKSwgJHJlcG9ydCwgW1RleHQuVVRGOEVuY29kaW5nXTo6bmV3KCRmYWxzZSkpCiAgICBXcml0ZS1Ib3N0ICRyZXBvcnQKICAgIGlmICgkU2hvd1dpbmRvdykgeyBbV2luZG93cy5Gb3Jtcy5NZXNzYWdlQm94XTo6U2hvdygkcmVwb3J0LCAnRXVnZW5lIHJlbW92YWwnLCAnT0snLCAkKGlmICgkd2FybmluZ3MuQ291bnQpIHsgJ1dhcm5pbmcnIH0gZWxzZSB7ICdJbmZvcm1hdGlvbicgfSkpIHwgT3V0LU51bGwgfQogICAgaWYgKCR3YXJuaW5ncy5Db3VudCkgeyAkZ2xvYmFsOkV1Z2VuZVJlbW92YWxJbmNvbXBsZXRlID0gJHRydWUgfQp9CgojIC0tLSByZW1vdmFsIGVudHJ5cG9pbnQgKHRlc3RzIGltcG9ydCBvbmx5IHRoZSBmdW5jdGlvbnMgYWJvdmUpIC0tLQp0cnkgewogICAgaWYgKCRSZWdpc3RlcikgeyBSZWdpc3Rlci1SZW1vdmFsICRQcmVmaXggJFN5c3RlbUluc3RhbGw7IHJldHVybiB9CiAgICAkc2VydmljZSA9IEdldC1DaW1JbnN0YW5jZSBXaW4zMl9TZXJ2aWNlIC1GaWx0ZXIgIk5hbWU9J0V1Z2VuZVBsZXh1c0FnZW50JyIgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUKICAgICRuZWVkc0FkbWluID0gKFRlc3QtUmVtb3ZhbFdpdGhpbiAkUHJlZml4ICRlbnY6UHJvZ3JhbURhdGEpIC1vcgogICAgICAgICgkc2VydmljZSAtYW5kICRzZXJ2aWNlLlBhdGhOYW1lIC1hbmQgJHNlcnZpY2UuUGF0aE5hbWUuSW5kZXhPZigkUHJlZml4LlRyaW1FbmQoJ1wnKSArICdcJywgW1N0cmluZ0NvbXBhcmlzb25dOjpPcmRpbmFsSWdub3JlQ2FzZSkgLWdlIDApCiAgICBpZiAoJG5lZWRzQWRtaW4gLWFuZCAtbm90IChUZXN0LVJlbW92YWxBZG1pbikpIHsKICAgICAgICAkYm9keSA9ICImICckKCRQU0NvbW1hbmRQYXRoLlJlcGxhY2UoIiciLCAiJyciKSknIC1QcmVmaXggJyQoJFByZWZpeC5SZXBsYWNlKCInIiwgIicnIikpJyAtSW50ZXJhY3RpdmU6YCQkKCRJbnRlcmFjdGl2ZS5Jc1ByZXNlbnQpIC1QdXJnZURvd25sb2FkczpgJCQoJFB1cmdlRG93bmxvYWRzLklzUHJlc2VudCkgLVB1cmdlRGF0YTpgJCQoJFB1cmdlRGF0YS5Jc1ByZXNlbnQpIgogICAgICAgICRlbmNvZGVkID0gW0NvbnZlcnRdOjpUb0Jhc2U2NFN0cmluZyhbVGV4dC5FbmNvZGluZ106OlVuaWNvZGUuR2V0Qnl0ZXMoJGJvZHkpKQogICAgICAgICRjaGlsZCA9IFN0YXJ0LVByb2Nlc3MgcG93ZXJzaGVsbC5leGUgLUFyZ3VtZW50TGlzdCAiLU5vUHJvZmlsZSAtRXhlY3V0aW9uUG9saWN5IEJ5cGFzcyAtRW5jb2RlZENvbW1hbmQgJGVuY29kZWQiIC1WZXJiIFJ1bkFzIC1XaW5kb3dTdHlsZSBIaWRkZW4gLVdhaXQgLVBhc3NUaHJ1CiAgICAgICAgZXhpdCAkY2hpbGQuRXhpdENvZGUKICAgIH0KICAgIFNldC1Mb2NhdGlvbiAtTGl0ZXJhbFBhdGggKFtJTy5QYXRoXTo6R2V0VGVtcFBhdGgoKSkKICAgIEludm9rZS1SZW1vdmFsICRQcmVmaXggJEludGVyYWN0aXZlICRQdXJnZURvd25sb2FkcyAkUHVyZ2VEYXRhCiAgICBpZiAoJGdsb2JhbDpFdWdlbmVSZW1vdmFsSW5jb21wbGV0ZSkgeyBleGl0IDEgfQp9IGNhdGNoIHsKICAgICRtZXNzYWdlID0gIlJlbW92YWwgZGlkIG5vdCBmaW5pc2g6ICQoJF8uRXhjZXB0aW9uLk1lc3NhZ2UpIgogICAgV3JpdGUtSG9zdCAkbWVzc2FnZSAtRm9yZWdyb3VuZENvbG9yIFJlZAogICAgaWYgKCRJbnRlcmFjdGl2ZSkgeyBBZGQtVHlwZSAtQXNzZW1ibHlOYW1lIFN5c3RlbS5XaW5kb3dzLkZvcm1zOyBbV2luZG93cy5Gb3Jtcy5NZXNzYWdlQm94XTo6U2hvdygkbWVzc2FnZSwgJ0V1Z2VuZSByZW1vdmFsJywgJ09LJywgJ0Vycm9yJykgfCBPdXQtTnVsbCB9CiAgICBleGl0IDEKfQo='))
}
# END GENERATED OFFLINE REMOVAL

# --- uninstall --------------------------------------------------------
if ($Uninstall) {
    $targets = @($Prefix)
    if (-not $PrefixGiven) {
        $targets = @(Get-EugeneInstall)
        # A second cleanup must find the receipts left by the first one.
        if ($PurgeDownloads -or $PurgeModelCopies -or $PurgeData) {
            foreach ($base in @((Join-Path $env:ProgramData 'EugenePlexus'), (Join-Path $env:LOCALAPPDATA 'EugenePlexus'))) {
                $parent = Split-Path -Parent $base
                $leaf = Split-Path -Leaf $base
                $targets += @(Get-ChildItem -LiteralPath $parent -Directory -Filter "$leaf.removed-*" -ErrorAction SilentlyContinue |
                    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'uninstall\receipt\inventory.json') } |
                    ForEach-Object { $_.FullName })
            }
        }
    }
    $targets = @($targets | Select-Object -Unique)
    if ($targets.Count -eq 0) { Say 'nothing to remove: no Eugene installation found'; return }
    $needsAdmin = [bool](Get-AgentService) -or @($targets | Where-Object { Test-UnderProgramData $_ }).Count -gt 0
    if ($needsAdmin -and -not $IsElevated) {
        if ($NoElevate) { Die 'Removing this installation needs Administrator; run without -NoElevate.' }
        Invoke-ElevatedInstaller -ScriptText $MyInvocation.MyCommand.ScriptBlock.ToString() -Parameters $PSBoundParameters
        return
    }
    foreach ($target in $targets) {
        if (-not (Test-Path -LiteralPath $target)) { Say "nothing installed at $target"; continue }
        Write-RemovalBundle $target
        $removalArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $target 'uninstall\remove.ps1'), '-Prefix', $target)
        if ($Interactive) { $removalArgs += '-Interactive' }
        if ($PurgeDownloads -or $PurgeModelCopies) { $removalArgs += '-PurgeDownloads' }
        if ($PurgeData) { $removalArgs += '-PurgeData' }
        Invoke-Native 'powershell.exe' $removalArgs 'Eugene removal needs attention; see the report above'
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

# --- 0c. a job site on this node ----------------------------------------
# A job site is its own enrollment (job-sites-own-enrollment.md, J19), added
# to a machine that is already a node without reinstalling or re-joining
# it (J35). A machine that is only a job site waits for the standalone
# install (J21). The site host makes the site's key itself; this script
# never sees the owner's password, which the agent's `site join` asks for.
if ($JobSite) {
    if (-not $Join -or -not $Token -or -not $Owner) {
        Die "a job site's join command gives -Join, -Token and -Owner (copy the whole command from Workbench)"
    }
    # A per-user (logon task) install can be a job site too (J38): there
    # `site join` runs unelevated, as this user, and the site serves only
    # this person. On a service install this run is already elevated.
    if (-not (Test-Path $AgentEx)) {
        Die @"
this machine is not a node yet.
       Install Eugene here and join it to your install first, then run this
       again. A machine that is only a job site waits for the standalone install.
"@
    }
    $siteLabel = if ($NodeName) { $NodeName } else { $env:COMPUTERNAME }
    $siteArgs = @("site", "join", "--url", $Join, "--token", $Token, "--owner", $Owner, "--label", $siteLabel)
    if ($RootKey) { $siteArgs += @("--root-key", $RootKey) }
    if ($SiteAccount) { $siteArgs += @("--site-account", $SiteAccount) }
    # Otherwise the join asks the administrator at this console (J30); the
    # tray's Allow commands, behind UAC, answers later.
    if ($SiteCommands) { $siteArgs += "--commands" }
    elseif ($SiteNoCommands) { $siteArgs += "--no-commands" }
    Say "adding $siteLabel as a job site of $Owner"
    $env:EUGENE_PLEXUS_AGENT_CONFIG_FILE = $Config
    & $AgentEx @siteArgs
    if ($LASTEXITCODE -ne 0) {
        Die "the job site was not added (see above). Nothing else on this machine changed."
    }
    Say "done: $siteLabel is a job site of $Owner. Its owner manages it from Workbench (Job sites)."
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

# Fetched when missing, and fetched again when older than $UvMinimum;
# see Install-Uv.
Install-Uv

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
# BEGIN GENERATED DEPENDENCIES
$ReleaseRequirements = @'
annotated-doc==0.0.5 \
    --hash=sha256:117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101 \
    --hash=sha256:c7e58ce09192557605d8bbd92836d7e1d520ac9580096042c0bfd197efacf1bb
annotated-types==0.8.0 \
    --hash=sha256:13b2beaad985e05e2d6407ee4c4f35590b11f8d693a258a561055cac8f64cab7 \
    --hash=sha256:f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0
anyio==4.15.1 \
    --hash=sha256:6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101 \
    --hash=sha256:9f28306018cbd6d329e64a36d58256edff76dd996fe423bc957326e578b82a94
argon2-cffi==23.1.0 \
    --hash=sha256:879c3e79a2729ce768ebb7d36d4609e3a78a4ca2ec3a9f12286ca057e3d0db08 \
    --hash=sha256:c670642b78ba29641818ab2e68bd4e6a78ba53b7eff7b4c3815ae16abf91c7ea
argon2-cffi-bindings==26.1.0 \
    --hash=sha256:061a6919145bbf282ebf1f9c59d3135d4833c25313c8595c0d68cf7712ddfce2 \
    --hash=sha256:0cc40f7b4050bb93eb67de95d2d759322fc7ce4930b9d645581ecf4913ec651e \
    --hash=sha256:151dfaad9de753f4af2a7854e707e4784f2acc434340ade64239c5b104b2d605 \
    --hash=sha256:19423e5d7ac1cc354baab59eaabf18db2ec04ef6593b5abe5a34f323c4a8f87a \
    --hash=sha256:19b562b1de4b9052ef1214a2821c44b6e6f22945daa102c32ae4eff929d8b6d8 \
    --hash=sha256:1a0a29ed86960e44eaace7e081bdfab4f08b012fd96ec8edba71e2ad020939e4 \
    --hash=sha256:1af817e84578ef8b7295ad17de0f9896e4c8520dbf2233c7aa5aa3d487256fc4 \
    --hash=sha256:1b0bcac4d490a237e18cf91f57352920c29f77f2fa39efd0813fb81298bf17ba \
    --hash=sha256:1d98e33bd8bd67d7206c124e200bf2229c4cfa8c9c19f7b44a897f0fc71837eb \
    --hash=sha256:21ca0396fe5ec995dd54431c32698189666f9224810acfa752e50d2bd94d9df2 \
    --hash=sha256:224865cbbcb7a2bd1356741dff12b0134df726b6d44bb7b500df8e303cbd9e81 \
    --hash=sha256:242bb0cda2ae3650764fc194593d9ea45fc9e72729acd89778c7cfe184cec2a5 \
    --hash=sha256:27f1821903e2ceadcb88ec2b45ef190897b7682449c772f4d9b53e42c520cf29 \
    --hash=sha256:28524438cd3e723f25412f63d4fd516ff5bae9ae5aa56acbe2a1404398a0cf31 \
    --hash=sha256:2b741888c93147444fdfc851abd81cc207f37f7f7da42062a00deb3888e57da8 \
    --hash=sha256:2c36ff87b5dfaa477d0bd51e9d7f6abdae7c8955d2983c97419085d842154b3e \
    --hash=sha256:34b7d9c24a4165a2c61cc8ae11d44d48c9ce2830fb536cb7914e11fdd9962728 \
    --hash=sha256:49d525938467d52c923a890153c99087c9d5a937d1f6b585dbdba34ec82e397a \
    --hash=sha256:4f84cdd868978d7b7350a566c254042d44216d9e37f241f3a6d3b1dfebeede35 \
    --hash=sha256:62ff20cd130c956c7c9144d5fe35228f98b51c579b2439e988b27ef93e16c02a \
    --hash=sha256:63505c71542a44b68b1e38060450fb006404170da375feb31af153e7f9c6205d \
    --hash=sha256:6376d4b3aca039375ca8bf92f770da0ec424a1ce3a37077a8d3c557411aa56ca \
    --hash=sha256:6a4e68eed961a8de6928d1c17ff3dc2a547e0e923c17f8f1cd79fb7bc9502f98 \
    --hash=sha256:6ab674f668d5962a3a4136ae0812519b0f1586874263723a32181d60d64137e1 \
    --hash=sha256:7014ab7e6f5d8511af92544667a0346ea6dfc314ea9a7cad1dba9fdb5c9a6e33 \
    --hash=sha256:76ae29acace5d33355344612844d588e19deaaba4639d8bb01601e4b1418ef36 \
    --hash=sha256:78de2d65e0b9ea7ce9d1b1c3e87297b2d7305a02c266ee2a2d6910daddd7ee69 \
    --hash=sha256:9bacedc04b0402837586a17f0919e3dfdd95291f441f1f56bd80ec274c2840a1 \
    --hash=sha256:a86c069c91a747a2c4e5c51473590aeb48172fff9b2130d23729a42d98665ecb \
    --hash=sha256:ac82fc756a446b6ccd7139ce70efa9d8bbe541e7ad579a12dcb52764b7175c5f \
    --hash=sha256:af11ac37a7c53dc16cb7950a6190851b0870fe218b6c60c0bb7ac355234e3083 \
    --hash=sha256:b70225b5fd1e0d2ef4f7fd30d24658454535f0924dff0caca5dc08efbbbadfbb \
    --hash=sha256:c49e853a3bef9dd10329f31f702e7fa9b5c58229ff9c2ff6d069efaf09177c08 \
    --hash=sha256:ccaf0a46cbb380f1fd102a874e32aa629fd3cb0c0e94f4943fa1f6d5edc5dac6 \
    --hash=sha256:d157ddfab1e8b21f2f1dedda9c09645d98b5ed0b667b0626be600a345d426440 \
    --hash=sha256:d88e5f7e60f28ae0b0cc6b2f16c43e87cd642a196a86f85e0d8bb6fe016fc16d \
    --hash=sha256:db0fcd827ca61622a01b220aadfbece01939acf53888f2cb98cd93e9b1e2c97e \
    --hash=sha256:df612391feca41c44d20118f3b88d1b86419465cd1f5496859f715ca60ec2210 \
    --hash=sha256:f0c3103fcff20183e593459cfea6e012281c0e76ae3ed8b5565ad1b92eac3990 \
    --hash=sha256:f9c4420a7a864fe1b86ce35befc95b8e39fb852493b81cf798671ddc265de638 \
    --hash=sha256:ffff613aaa9ce6236766e2fc6dc560bb5abde7a2e2416e3db1f9ae395a2b4dd4
attrs==26.1.0 \
    --hash=sha256:c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309 \
    --hash=sha256:d03ceb89cb322a8fd706d4fb91940737b6642aa36998fe130a9bc96c985eff32
authlib==1.8.0 \
    --hash=sha256:88aebbd9af6757e14e912d5dc007ae1dc1f3e27e3b2152ce7c552ee2c3b3c121 \
    --hash=sha256:f3ecd5f1da737262fb53bf1a4d95c4ea1ad9dd509316587a255c99ab1838a4f0
certifi==2026.7.22 \
    --hash=sha256:62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775 \
    --hash=sha256:741e2c3b351ddf169a738da9f2c048608ff7f2c5cc02f1ebc6b118bb090d5d55
cffi==2.1.1 \
    --hash=sha256:046bfc24911b37851ee1b51aab8bffe713d89c68c6a057b09484ce9fd5f69b4e \
    --hash=sha256:06c72bb76605a4b0cd0aad6930b69d4baf7dd5d806cfc409b824191099700e66 \
    --hash=sha256:0beceaabe56af686895136a2de78db54ecd8e4046b236b8fd6d6cb61389e9bf2 \
    --hash=sha256:154852545011f779917b11c78db2358d095da62a9a172b78ad0a583ee5adc0d0 \
    --hash=sha256:194cffa889098ced9976c3fc6340305e43f6303657d298da55366907c05c22d6 \
    --hash=sha256:19ee6127ee34de7d83ce3d371ebc5ed91addbdcc39f9ab15ce4eb35a4e534971 \
    --hash=sha256:1a18a57b58cfb21fc28d72e876acf10eaed67a1ed96226f92af4df681d571c4c \
    --hash=sha256:1aa5645c30469b09530c4ebca77ebf8f17618293c58f8549cb1a543a50236e7d \
    --hash=sha256:1dea0e4d7d4f11f619fe8c1d76caf49e24405b4b5743c0e3be16a500ecd930c9 \
    --hash=sha256:208f941bb9d18e768138677f0a6d2ce01f590df56043dda1df1535ac57c88517 \
    --hash=sha256:210019b6c7cf07f081b4c54635c8cf744377001350e29cc0f81c4377b4797735 \
    --hash=sha256:246fa40ce8645a614ff682e0b70f37134e460eaf93a775e0cbe3cca585a67a80 \
    --hash=sha256:25792eac27877609e7bb06d42ff88278a6624fff2ba9bbb523c09616b117e80f \
    --hash=sha256:27350daa11d4f10c540e6e89dada4c54feb7256ad03e9a4dc075ebad7ba360d1 \
    --hash=sha256:28907ab9bfb6aa13184cfc17c6b8e1023c5ab6fd7076d8c20a35e59fe04f8f29 \
    --hash=sha256:2ae64be792b8966f2c69538199728b290e34726562896df1e5dc8ffd8d8188e8 \
    --hash=sha256:31348097ff5bbe827ccc41795d4dd099d9f0625e7def00ee653c137a490c2a6c \
    --hash=sha256:3143d81e29e1e20a9ce10901ec369012947876596f75a222235965f2b7ae832e \
    --hash=sha256:3222ba5d678f80a030e6afbcc33dc1ae5cb45facabb61cee2c7016b8432fde48 \
    --hash=sha256:3311ed60d36f83378794e1009ac6258bafbf81f7888b4caa7b35a521e3f95813 \
    --hash=sha256:334644fbac4eff73d985a17a91226df55d0f394160c4cfb880e084c8f7161cac \
    --hash=sha256:34e261f78cb6ceaaa36f42f2613f4380d94d9c759a9c73c769ee6e0247364632 \
    --hash=sha256:363e05fa78e15116c3c32c210ee36884fd6b9afa6d440e47112c3bd511d64cb6 \
    --hash=sha256:398aff33cee2767e3e781d2554c54bd0dff386bb437581e0d8011fde1a942ec1 \
    --hash=sha256:3d22a20b1fb1632cc72c22f95f7b0d2961c3e1c235f245ba4c606c4771035659 \
    --hash=sha256:42a494cee34437f05546455144f2b5d9ac09b1face62bcfce597d2e521066688 \
    --hash=sha256:42e2f76b9455f5a9a844f770bf3e200ed3da0e15f5df3db9c31fe80b04b3d004 \
    --hash=sha256:42f6930c31dc7f50732c9ae793c2786c7b6b044195967bbdde40bb9be81c4cc0 \
    --hash=sha256:456a61fa52d579ebf9df2e9552ead5129855dbaff6c1e5a9b1bc408809bdc062 \
    --hash=sha256:471cee653ae88de62096552e6d24ccb4a5adb8c8c9f10b5054d0122c15bf2779 \
    --hash=sha256:49cbc70e6542d4ccccb936558d1064a8012541e78f821f955cff24e357776c94 \
    --hash=sha256:4a7c934f7360e8cd64fe9efadcbd10c7c6364f531e432b9a4bf5ccbc9e0e8b50 \
    --hash=sha256:4be96343e422f2dfcd12ab5c9f5aebe03f82f737c6bffeca6830b3875cb44aab \
    --hash=sha256:4f42141fc14250de6dde5ee7ea4432be017252d91f19c5ad043c084cea629cac \
    --hash=sha256:507a24c282e0f42f8ed737cf048572cbf580468da5555764a8331735e9c736b6 \
    --hash=sha256:51b31d1c98274844cfd7838ce00bfc27c7423a4dc00fc0772fc3331c2cc90676 \
    --hash=sha256:58acb8ab8e295e6c5ea12f888cbb13cf21511ef2a3303a23f4325c29d17fe5c1 \
    --hash=sha256:5a59cc1c4442bc3d5c703bf720b51138d0bfc173618807c9ee2490a7541dd3d9 \
    --hash=sha256:5bb4e7ea95dcd6a014a6fef62e62467d67d8e582326443f3d68e71d6320a9fcf \
    --hash=sha256:5c58fe613dc5e5336357eff555824a314d8e43282600435c8d1cb6a7a2fedd13 \
    --hash=sha256:5e7cecbaadb83884793e05828cee59b210b24583b9c7425d0ba6a754fe22eb4e \
    --hash=sha256:616f097f2fe415bc92a247f02e11f634e1f9e9a83d327e3c915c15089c87869e \
    --hash=sha256:63bbfd5ded17c4840ac07cd8f1c21ba9d9708141f840b324f422f41b207e3973 \
    --hash=sha256:64faea20f4e2613363a1a9b9c7dd73058f3ecd00133a511e72ad7c511658f527 \
    --hash=sha256:661c298b4821edebead0c91edd2b00374d67ad7c5a1f7a91d4442633b79d6a72 \
    --hash=sha256:68e62fe11f30d5ca8289242866f0a5291402d8529ca2178ab8afc5c9694ae890 \
    --hash=sha256:6a8dddef476fab96d066d578fc88526767b836ab5ab21754e1d5bf3879c31c7c \
    --hash=sha256:6e192623c49c94421616a5778fba35cf0d5a8d000650c1967ef4448ee5cdd990 \
    --hash=sha256:7225e4514edb64eb6740324353e0da0711954fd8d7da4576755b1c6e09b697cd \
    --hash=sha256:75f80557d1389eddbd0de2681f6a390a0c5338c31ddaa821381c203fc3fd50d9 \
    --hash=sha256:770de9db11e84213beec501cfcaa013b019820ca881e03344dea5844f7876d94 \
    --hash=sha256:7750c6449dff7864bb9bb27ddfb0267756189201a3afc911d82b3caacd70dfc3 \
    --hash=sha256:7bde5e4cc5c10140859842b9d383af292b22639a4dffb725314baf45968cef80 \
    --hash=sha256:7ce713ace7c0e4520535b42b77eaa742c16dab813978064913e5a3cf82973b41 \
    --hash=sha256:7da0c5eff80f0197f3b3d1232ec5a682a9325f4ae9016a78f5f5ca35f9ced1f5 \
    --hash=sha256:7dbb61fe3a7699468030f71bbe5f8a0e326a151daa91beb11a6fc1f980c55e1c \
    --hash=sha256:811bd1e21d32de12efca32393a0ab3f5133b54fce9bd44b8bd77ab07da14bf6a \
    --hash=sha256:8ef53b2de9bcb9197d31854256575d59dbac0cba72ac627bb291ef5eceb74be4 \
    --hash=sha256:937c0052c05a31ca1daf18de3158eed4dbfcb9cc107adbea227728d647be701e \
    --hash=sha256:9d2055050ea716bd38b7f7f1579c275386646b4894c155a3e2f3cd62ed41b7c6 \
    --hash=sha256:9f8d177621de5cb38ee3e731eda45d421db093ec0739f46a5594babda7987a98 \
    --hash=sha256:a2d7755bef5a12ed488f4ef1f1b69ee9191d7396083b755a5d2295f6edb4768b \
    --hash=sha256:a48d62ab9d6f4f98c983223a547af44be6ca3691074c31cecced6facd3ba2dc1 \
    --hash=sha256:a4f00aa42f75d6e4595e8866e748cc1705adc0cddfeb2ca86d0d03993d63ba03 \
    --hash=sha256:a6e721d4b0e45d5b65e87534470e67b18dcd092c83f68fba09f152b9cbc061af \
    --hash=sha256:a730a083190634c65cca36ba5f489531576ebd79bcd5c8e172130f6453127231 \
    --hash=sha256:a931079504ecc49efed7744c476a5c343a92fabf66dec2db95edb1b2fdc770e2 \
    --hash=sha256:aa9511c62d14da7aacc9b4bf51f3f697a621e83b2d6919008243c3aad168eea3 \
    --hash=sha256:ab36d55f9ed2d067327667c2fea18dda018eb628dd6347aa01dda6cf1f5d3836 \
    --hash=sha256:ad2c86c495b899d862ea0f4b42891b8713a3bd45dd4105c7fd51c2a72f39f3a5 \
    --hash=sha256:aeae0e330c9f6acd681f647d46cefd30c29f93e3392882e792e82080c9691399 \
    --hash=sha256:b0431303acaea1089ad4b3e9ce4e6518193def1118d4073ca848635ee4ea2e96 \
    --hash=sha256:b5bdfd1c873d4e093aabc0ca84c4ca6dbc4f752afb5c86f146d9742580c9da2e \
    --hash=sha256:baed1e86cc735622097354b9d1281406caf42ff42a886d29faa8e8d1630333be \
    --hash=sha256:c1453022f490d2459a11819d83ad1d586e9ff65a12ac3e705ffebd46d3685dcf \
    --hash=sha256:c26608d2222fb1e94487e4a387d85f13eb55d5ed725cb25a0c589ac4ee60e7bc \
    --hash=sha256:c7659f22557c5a0bc4855cd635f55edec690cc008a40768527762cb9fb263455 \
    --hash=sha256:c8c69575568085ba0b1b10c0249d779a214aea6f6522e949a0fc9fb0fcb449d0 \
    --hash=sha256:c8d2c9fd1f2d16f780d15127abb050d13d1a76c03a4bd87d7e4980e45e511e12 \
    --hash=sha256:ca82be1a1d406ecfe1d25dc16cb33488e5a16bf4438c9fb590484ea29d92478b \
    --hash=sha256:cc572dace3f60ef98d7b12ff411d20f5362feb31a0439eab0085bbfd349982d7 \
    --hash=sha256:d18e5ac0f2f03f4f518d3e23db0f0cad7faa1da8620e9c09461d443bbf6e6692 \
    --hash=sha256:d28630f5854ab07ab1fd4aba756de52326c82e6be15d414b12793f1975048b54 \
    --hash=sha256:d9c275eaacd24aa73f94ffd6de08fc3f932424d8b6c376f4bed7cde376fe7bc3 \
    --hash=sha256:da0e573f9f97159390c89d9f1a9e41908b66d408cc5b58d08cf3847d844c531b \
    --hash=sha256:dd31f52ea1086513bb9df30f8fcee9b8918323ae067a3d5b78bc826a000712be \
    --hash=sha256:dddad92b554513a31f272570678ba307fb9f618f05e3d4a5eacafff9eae03e1d \
    --hash=sha256:df423d40ee8654634421812bc3b196da3f9bd7d32929da813f8394c4348a5358 \
    --hash=sha256:df913725b79db7bcf03448f36b7bf8815363417d5b58deecf9305e3e30f0f21a \
    --hash=sha256:e0bcb7e0f677f543555d2adff3bf19c05f66cdb4796e5ff602442ab2fe3c4ef7 \
    --hash=sha256:e2d65b31f36619cda3999b78b2aa9632e76b78448e7a56fc4240824200e7c4fc \
    --hash=sha256:e6e8cff14d6fb0be70a09c0bdc58096f501952d04624ebf867e0e56da2df8960 \
    --hash=sha256:f16c709686a78c727bbbf059f92b0bf41c6fc60deec706d2dc19f529175a6125 \
    --hash=sha256:f24fb43132a4c6b4cb4eb029492919b2db645be6808d738f244fd146c03c32cb \
    --hash=sha256:f53e442b08449d42821fa4a4fba000095af9f62742a500f978a9f557ec44339a \
    --hash=sha256:f5cfbc5fe74540d335175b656c725d74d90e3730c626d92575eea35029d9afaa \
    --hash=sha256:f81b3b8f3d4e343550fa4baa0e479bba9f2d29ce9c2e9b51d1ce1718d7442fcf \
    --hash=sha256:f8ec5e643a9a937f64e1999eb9f75d072263751912dc5cd06d3c85f8f44be7c3 \
    --hash=sha256:fb92203a88b3d3053034db775110081c49d28be6551923805e039924093761e4 \
    --hash=sha256:fcd22650c908d7b7da162bbfaab594a1227a15d1643a98c68b122ac642fa2264
click==8.5.0 \
    --hash=sha256:255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360 \
    --hash=sha256:ba0d2089de75ea0310e2dde03160e6ca10009947fb95a182f9b54021bb272e34
cryptography==50.0.2 \
    --hash=sha256:0ddc924c04591c2811ca024d62ecad4f7f6f08af8939c211438f48a16bd23602 \
    --hash=sha256:0ec5f09541743261e66e291b4a0cbf0fb2997aeaab6d9e9c740b9dba1b58d1c2 \
    --hash=sha256:0ecbc5652bdb6fc9eaf89a7d196e20941adfe812f43bc4ca05d9150496821047 \
    --hash=sha256:1981f1db4630889b9ef7803fadef12b056f428cb6b85c27ba57b774793b6093c \
    --hash=sha256:1ba34f04897fcdaa73f74145c25f3ec146fbd56593853e88adc2e811303c5f42 \
    --hash=sha256:241449bf940a5d27309bd317e6f9a2af6932113818bb2b8f5c59ddc7ef16da18 \
    --hash=sha256:25784ce8b9621c90c643efb9e1e2162ab3b0224cae446ad5e70e7fcb1ce18b51 \
    --hash=sha256:3dc4fd8058cea1644971207d530e1a03a184a805ffc8ebdddf0599d78a331b81 \
    --hash=sha256:4061c0079120205fb760c58acab6443e217307dcf05e3702cf970e0689972856 \
    --hash=sha256:4a20ce1e5cb4284a86692fdcba7cb8754185c6b2e5c56fcef3751cf451d3cdc2 \
    --hash=sha256:4e81d95e5bafc2d6e34e4bed780e53e4d5b9a2f928573428aa4d35fbec1eb0de \
    --hash=sha256:58a0c478eeca76fe5e07993c5a0703def34a6dc6a0cda4f5564639b33112ffe7 \
    --hash=sha256:58ddb5a8e3179d12f19e4ea34d2d32e9d63a4baa142c875c1eb59f41b7243acd \
    --hash=sha256:630ebfea3bf689d075f82316324ff7433dc447fe6bc1bfc76524b74b4a9567d2 \
    --hash=sha256:6f8700550aa1474a91e5dc07049c46f98b423b5b1ddd0483e0b51362eeeaf5be \
    --hash=sha256:78198641e5be9521beea5aa782bb551a58068d10e6eb04c9c680c1b69f2e7d45 \
    --hash=sha256:79def8d059362e7831389ed3be0ecdf58a89386e1271e35dd9f5af84e81bffd0 \
    --hash=sha256:7a8701d6b584d76e909e3d305b7d126b41439876a5aaf76cddc67fc230eafa2e \
    --hash=sha256:7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c \
    --hash=sha256:7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5 \
    --hash=sha256:7b75de3c8b3be1cdb1052747c929440c3eea46c1bc2cb8a6e3a48388e9b7b452 \
    --hash=sha256:7c6d0330c472d96f6a6afe24d80dfdf15176c33096f0a4397ae4c60f3dd3be48 \
    --hash=sha256:828d49b0ff5a0e3975865571c5d91dbbdd0d38d8289b249a163e9425413a5e05 \
    --hash=sha256:84f964e537f916e2cc85199e5a88742e964939b575ac8598b3f9d6cc416cdaf1 \
    --hash=sha256:85d0d9a31b9098e98534226d5686b47264b95e62ce459dc2e62fdfc809f9fe93 \
    --hash=sha256:87e9ce85beb6b328ba370cc6e6aea483c92617b4c95b1d33a49297eb662bfb04 \
    --hash=sha256:8c71ba2cd31fc93748c38e1b613200ff1c2665cbfd5341fe3a61cfde35a1430e \
    --hash=sha256:92e665960f25fcdc73725b9cec7a3824f279ba97a98653afe9ffac2e43668f67 \
    --hash=sha256:94e5e9f108ee10471288214d3d233fbfbb492840a8457eb85178d643ddeb32c7 \
    --hash=sha256:9c8402a82ea0dc4ceeab793db05f0fafa8ca139ca34fcde5df0f596103c74107 \
    --hash=sha256:9dab55f57c74c3cad24c323bacbbd04be4705ba6eb0d92e920b1fc4837ed5079 \
    --hash=sha256:a582ab2ae1d34f67112cadc86702774c9ea4374df6bca6afe672817203c99134 \
    --hash=sha256:a6557e5f38e065ca9fbdaf7cfc7435ecb1d113aa81a022d1b51921ee7432e227 \
    --hash=sha256:a9f7355e6fab51f6c369b86fb7571cffa05edee2c2121e0380a37fb9ac1cd5c1 \
    --hash=sha256:ab50ee449bf968271e820086f10a33d101dd060370abc10bcd22279be2656539 \
    --hash=sha256:ac9ed99d81760c62fe89d5f0815cdfa1ba9a35141cf30f1c2d044f04b4803d2e \
    --hash=sha256:b13478603dcd0a2479ff8e87e2c19a7d525734686fe3c49542472293a204212d \
    --hash=sha256:c423ab384a46c4dff7217b2ea5ba2e11cffdeab6441acd04cf65a369caf0366c \
    --hash=sha256:c5e67125c7dca78d199ec4e116aa93dbb83494808ecbb8211a2cb09b1bf41dbd \
    --hash=sha256:c71be1cbfa5cd9a41ee452acf1eccd82b2c05950358b106ec8ceb83411d1a020 \
    --hash=sha256:cbc8738fd8526d80f35cb3a40d41f41a2e7030bb3b18b09a6778ef63d291c2fd \
    --hash=sha256:ce47f66801c20ec6c6632453bb5960fe38939e9306970b48b3a5a26de7745d94 \
    --hash=sha256:d370b8d1dfcdf7130178137f6fbee6140774a1acc6cacefc4b42643ec11d0a3a \
    --hash=sha256:d38cdff612d06fa6a32840d5e1b1f7a27cee4a349aa9085d94a67789d6bfd408 \
    --hash=sha256:d8947001be83df1394050758ce0e745dd74fb134eef0a4b5124208dfc3a68c37 \
    --hash=sha256:deb9fde5c60e437ee4821bc9bc39ff31b42135c27e1dc61ef0a629389c1de62e \
    --hash=sha256:dfe9763530994147d9af1def057a5b9658b00e8f8fe8743d144d1e0911c2e454 \
    --hash=sha256:e105ab60406787da31fccc883fc0f733af1efd78f0136a4599692c4083a73d0c \
    --hash=sha256:e275096ea1e60cc595cda2836fd4a6c725d1125108b868be17f53684d164e2cc \
    --hash=sha256:edc3342adf8f697fc5f59c887a304356f147b397809440ed64e2fa6af2f50f37 \
    --hash=sha256:ee247f5c245c9a2fe7c8e2214e295918838e44e00a45a6718451e4004219e767 \
    --hash=sha256:eef4c2f3423810b3070ab391f85436d2f8bbfcb286ac15cbc73190b3563b1f1a \
    --hash=sha256:f21e8a22c8605750c7af886bab299a363721264061b4ac0a30efb73cfd58efc5 \
    --hash=sha256:f265528741e048bce55c3463ed721fb0aa45a5888d8add8cfeccb3035451bbdc \
    --hash=sha256:f2f9bd7f90c64fe89253f0a2c05e3c4856072660429ce8831b4235bf29403a67 \
    --hash=sha256:f785f6161f202ab04d8ca194158968798e480ca058943907972da5f12e2881e8 \
    --hash=sha256:f9f6143a8c75945eb960d9eb98905a441394abfa24afaae239d514ffb2586480 \
    --hash=sha256:fa8f5efb344d6908a1ce62f4a24e2e5780f825d6f53f5f50ec5ffacac72936cb \
    --hash=sha256:fdd28f912fccfec1846a94e2e1e8f9b0012f557f0c46fe4f3eb0d7a87afcf90b
fastapi==0.142.2 \
    --hash=sha256:06366626f2e70576367714d9ab2fe8472e6c8456dba69b399f9f797ab5e92570 \
    --hash=sha256:bd5f4d81f1e93a88bcd77caf4dfe3c2dbffc3805407a0007e9a114c18b3a670b
h11==0.16.0 \
    --hash=sha256:4e35b956cf45792e4caa5885e69fba00bdbc6ffafbfa020300e549b208ee5ff1 \
    --hash=sha256:63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86
hatchling==1.32.4 \
    --hash=sha256:08ecf7548fb48205e7f213d70c71e67b8271b7242093dc3f1da578b42c734a2c \
    --hash=sha256:c4468f73144c054d2aab4ef0f0378c43b9878bf07f8ffd6b79690e970d375f07
httpcore==1.0.9 \
    --hash=sha256:2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55 \
    --hash=sha256:6e34463af53fd2ab5d807f399a9b45ea31c3dfa2276f15a2c3f00afff6e176e8
httpcore2==2.13.1 ; sys_platform != 'emscripten' \
    --hash=sha256:e0aa977abe17e69a3b820a24542a6fa88702676d83880b8d194dcd18408e5103 \
    --hash=sha256:e1e05d4f25f7d7d496bfb96748f6f4b67657b03da069b3a68c36069f3db73d0a
httptools==0.8.0 \
    --hash=sha256:0770728beb05094c809b98e814edff5fef69d26ad7d21185f2f6d5884a0ba683 \
    --hash=sha256:0ea897f0c729581ebf72131a438a7932d9b14efef72d75ada966700cac3caaeb \
    --hash=sha256:159e9ab5f701ccd42e555a12f1ad8ff69702910fc1c996cf2bb66e5fcb7a231b \
    --hash=sha256:19d1ee275bb59ba2643ba9a3a1e51cc0c788caf2b8df506368e03f56fdd08527 \
    --hash=sha256:20b4aac66ff65f7db06a375808b78f42a94970aa22e826b3cb2b43eb09174124 \
    --hash=sha256:2a021c3a8e65cc125390d72f59b968afca3bdcaff25bd67965e0a055a14946ca \
    --hash=sha256:2c032fa028f46871ec7e1fc59fc15e8023eab3e6bbe6ece786a1611719a5d081 \
    --hash=sha256:2d689918c15a013c65ef52d9fd495d766893ab831a2c8d89f2ac5940a5df847c \
    --hash=sha256:384c17174464c8e873398b7af24f0b1f44d992c820328413951a625323155d77 \
    --hash=sha256:425f83884fd6343828d8c565f046cb72b6d19063f6924093e11bcd8e1548cd09 \
    --hash=sha256:48774d39cbb70e2b1f71f88852a3087ae1d3a1eb80482bb48c13067ab080c14f \
    --hash=sha256:52dd695b865fe96d9d2b16b64a895f3f57bf3cb064e8383cd3b5713a069e8085 \
    --hash=sha256:57278e6fa0424c42a8a3e454828ab4f0aff27b40cddf9679579b98c6dce6a376 \
    --hash=sha256:5931891fb7b441b8a3853cf1b85c82c903defce084dd5f6771ca46e31bf862c5 \
    --hash=sha256:5d7fa4ba7292c1139c0526f0b5aad507c6263c948206ea1b1cbca015c8af1b62 \
    --hash=sha256:5eb911c515b96ee44bbd861e42cbefc488681d450545b1d02127f6136e3a86f5 \
    --hash=sha256:614ceea8ea606848bece2338ac03b3ce5324bcb4be8dc7d377ed708012fa4db8 \
    --hash=sha256:6a43c9dd399758ccc0531acb0a3c4a6c299ee893ee9400e9c893b7bdcfae0681 \
    --hash=sha256:6b2a32f18d97e16e90827d7a819ffa8dbd8cc245fc4e1fa9d1095b54ef4bd999 \
    --hash=sha256:7685df791fad561384bfb139e77fde27a1ffd93134e016f95a0db424ffbf77b1 \
    --hash=sha256:7b71e7d7031928c650e1006e6c03e911bf967f7c69c011d37d541c3e7bf55005 \
    --hash=sha256:880490234c10f70a9830743097e8958d6e4b9f5a0ffc24515023afeef984054d \
    --hash=sha256:88bdd940f2b5d487b4d032c6afa5489a7dc4694410d43de3c38c4fb3af0dc45d \
    --hash=sha256:88eead8ec8680a9f146c655bc88445a325bd7921cfd8194c7337e9467282427d \
    --hash=sha256:9518c406d7b310f05adb1a37f80acabac40504a575d7c0da6d3e365c695ac20d \
    --hash=sha256:9878eb2785ba5eb70631ad269b37976f73d647955e26c91d490eb8a4edfda4ba \
    --hash=sha256:9fc1644f415372cec4f8a5be3a64183737398f10dbb1263602a036427fe75247 \
    --hash=sha256:a1afd7c9fbff0d9f5d489c4ce2768bd09c84a46ddefc7161e6aa82ae35c85745 \
    --hash=sha256:a1b4c8e7a489a0d750d91894e9a8cdc295838f1924c0ca903ae993456fddec07 \
    --hash=sha256:a3b7387147361c3fd47a0bde763c5c91b5b4cd4dc9989b8ece84ff436c99843b \
    --hash=sha256:a6f21e2a3b0067bbe7f67e34cfd16276af556e5e52f4c7503be0cb5f90e905e4 \
    --hash=sha256:b15fc622b0f869d19207c4089a501d9bcc63ca5e071ffdd2f03f922df882dcb2 \
    --hash=sha256:b205e5f5523fa039679da0dfe5a10132b2a4abeae6a86fdd1ddc035f7f836557 \
    --hash=sha256:bbb8caadb2b742d293169d2b458b5c001ef70e3158704aa3d3ef9597624c5d1d \
    --hash=sha256:bf3b6f807c8541503cecfbb8a8dffb385640d0d96102f3d112aa8740f9b7c826 \
    --hash=sha256:c08ffe3e79756e0963cbc8fe410139f38a5884874b6f2e17761bef6563fdcd9b \
    --hash=sha256:c0d726cc107fceb7d45f978483b4b70dd8caa836f5914d3434bb18628eb73813 \
    --hash=sha256:c4a9f1707e4823d54dfec6c33fa3697d302aed536ed352a7ebb5a061ddb869d0 \
    --hash=sha256:cd96f29b4bab1d42fa6e3d008711c75e0f79e94e06827330160e3a304227f150 \
    --hash=sha256:d76ad7b951387e3632c8716a9bb03ac5b45c5f16119aa409db0459520887944e \
    --hash=sha256:da684f2e1aa2ee9bdcb083f3f3a68c5956750b375bc5df864d3a5f0c42a40b77 \
    --hash=sha256:de1ed58a974e75d56560acc7e7fed01a454994429456f65209789992e41f2568 \
    --hash=sha256:de242a49b5d18e0a8776e654e9f6bf6d89f3875a5c35b425a0e7ce940feb3fd6 \
    --hash=sha256:df31ef5494f406ab6cf827b7e64a22841c6e2d654100e6a116ea15b46d02d5e8 \
    --hash=sha256:e93c227b595c6926c1acee96891dd9da4be338cfbe82e5cd3bb9d8dd7dc4ac0b \
    --hash=sha256:eb3028cca2fc0a6d720e52ef61d8ebb62fcbfeb1de56874546d858d3f25a26b7 \
    --hash=sha256:ed377e64805bdba4943c82717333f8f8603a13b09aff9cead2717c6c817fb168 \
    --hash=sha256:ef7c3c97f4311c7be57e2986629df89d49cb434dbff78eafcd48c2bff986b15a \
    --hash=sha256:f256d6ce930c52ca1cb2a960b7da03548c454e7d28b06059ad41bfe789036ce0 \
    --hash=sha256:fe2a4c95aeba2209434e7b31172da572846cae8ca0bf1e7013e61b99fbbf5e72
httpx==0.28.1 \
    --hash=sha256:75e98c5f16b0f35b567856f597f06ff2270a374470a5c2392242528e3e3e42fc \
    --hash=sha256:d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad
httpx2==2.13.1 \
    --hash=sha256:6dff50fabc270ee5fd25d845d0b078ed20564579744d6d962850975996d2f9a4 \
    --hash=sha256:e48744a19e3af5ee48313d0ce5fe941d5422fae5705ea922a4aabf94d7800dfa
httpx2-jsfetch==1.0 ; sys_platform == 'emscripten' \
    --hash=sha256:70a0e3eabfef7cce5ad9c629f7d01ca05e418f586646f4ddf14782e4c1454c60 \
    --hash=sha256:cb916b707601e69a07721aabc8f3f6659be3a6893bc1ff5c6f9e02241df2da32
idna==3.20 \
    --hash=sha256:a7db850025b95ded1eae8a46181a1a6c56c92c96f0e2b005d9ff8dc0210cab44 \
    --hash=sha256:ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c
jaraco-classes==3.4.0 \
    --hash=sha256:47a024b51d0239c0dd8c8540c6c7f484be3b8fcf0b2d85c13825780d3b3f3acd \
    --hash=sha256:f662826b6bed8cace05e7ff873ce0f9283b5c924470fe664fff1c2f00f581790
jaraco-context==6.1.2 \
    --hash=sha256:bf8150b79a2d5d91ae48629d8b427a8f7ba0e1097dd6202a9059f29a36379535 \
    --hash=sha256:f1a6c9d391e661cc5b8d39861ff077a7dc24dc23833ccee564b234b81c82dfe3
jaraco-functools==4.6.0 \
    --hash=sha256:880c577ec9720b3a052d5bc611fb9f2269b3d87902ef42440df443b88e443280 \
    --hash=sha256:99e3dc0060c5cbe8fcd1cdb36258e2a65ca40f1566b2033b12abb1bb44dd3c30
jeepney==0.9.0 ; sys_platform == 'linux' \
    --hash=sha256:97e5714520c16fc0a45695e5365a2e11b81ea79bba796e26f9f1d178cb182683 \
    --hash=sha256:cf0e9e845622b81e4a28df94c40345400256ec608d0e55bb8a3feaa9163f5732
joserfc==1.7.5 \
    --hash=sha256:add2c2c84e8373b084d526a8b53daba5d7a513a118cd2dcd9fc9f979d0922159 \
    --hash=sha256:d5ff536e658e17664f8c1b1ab60dc4aa62aa973fcef1edd33cc44bda45d6f5ea
jsonschema==4.26.0 \
    --hash=sha256:0c26707e2efad8aa1bfc5b7ce170f3fccc2e4918ff85989ba9ffa9facb2be326 \
    --hash=sha256:d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce
jsonschema-specifications==2025.9.1 \
    --hash=sha256:98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe \
    --hash=sha256:b540987f239e745613c7a9176f3edb72b832a4ac465cf02712288397832b5e8d
keyring==25.7.0 \
    --hash=sha256:be4a0b195f149690c166e850609a477c532ddbfbaed96a404d4e43f8d5e2689f \
    --hash=sha256:fe01bd85eb3f8fb3dd0405defdeac9a5b4f6f0439edbb3149577f244a2e8245b
mcp==2.3.0 \
    --hash=sha256:8b147a50441cf059dc88c684e0aeed3687f0aa0f39c6cde7b90330effd2b34d8 \
    --hash=sha256:dd0c44c089d16453e8ae31a3877a0054d7a2314caaa81f5e0541b9b1734b2377
mcp-types==2.3.0 \
    --hash=sha256:968efdbdaedfab06adae40d378a34395f1090c5921d4be3c9cde283aaf76d91d \
    --hash=sha256:d1e46549edb35ee19a94940fcee6d1addd7e589ab7ea92dda83f5d84781fc362
more-itertools==11.1.0 \
    --hash=sha256:48e8f4d9e7e5878571ecf6f2b4e57634f93cd474cc8cfbd2376f2d11b396e30d \
    --hash=sha256:4b65538ae22f6fed0ce4874efd317463a7489796a0939fa66824dd542125a192
opentelemetry-api==1.45.0 \
    --hash=sha256:711ede81773c8025c2c03dac0450bc89f3d30aea6eabcc815c570d4e35a963f7 \
    --hash=sha256:80e068aba7cd56c8b58512d6a36f8d25cb1dfaa0c0a4cc1c938ccf9f362d9cb3
packaging==26.3 \
    --hash=sha256:94edc256424af38762eb31306eed28beb9f0efc50a8837492c9d6fd6004aed79 \
    --hash=sha256:d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c
pathspec==1.1.1 \
    --hash=sha256:17db5ecd524104a120e173814c90367a96a98d07c45b2e10c2f3919fff91bf5a \
    --hash=sha256:a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189
pillow==12.3.0 \
    --hash=sha256:00808c5e14ef63ac5161091d242999076604ff74b883423a11e5d7bbb38bf756 \
    --hash=sha256:04f01d28a6aaff387bf842a13be313df23ba0597a44f1a976c9feb3c6ff4711a \
    --hash=sha256:06ff022112bc9cbf83b60f8e028d94ad87b60621706487e65f673de61610ab59 \
    --hash=sha256:0740a512dc522224c77d9aa5a8d70d8b7d73fb91f2c21125d8d025d3b8990e45 \
    --hash=sha256:0847a763afefb695bc912d7c131e7e0632d4edc1d8698f58ddabec8e46b8b6d3 \
    --hash=sha256:0dd2064cbc55aaec028ef5fbb60fa47bb6c3e7918e07ff17935284b227a9d2df \
    --hash=sha256:0feb2e9d6ad6c9e3c06effe9d00f3f1e618a6643273576b016f591e9315a7139 \
    --hash=sha256:10e41f0fbf1eec8cfd234b8fe17a4caac7c9d0db4c204d3c173a8f9f6ef3232b \
    --hash=sha256:1182d52bc2d5e5d7d0949503aa7e36d12f42205dc287e4883f407b1988820d39 \
    --hash=sha256:164b31cd1a0490ab6efae01aa5df49da7061be0af1b30e035b6e9a1bfe34ee6e \
    --hash=sha256:1657923d2d45afb66526e5b933e5b3052e6bdea196c90d3abb2424e18c77dae8 \
    --hash=sha256:186941b6aef820ad110fb01fb06eb925374dc3a21b17e37ec9a53b250c6fe2d1 \
    --hash=sha256:1cca606cd25738df4ed873d5ad46bbdb3d83b5cbca291f6b4ff13a4df6b0bbe8 \
    --hash=sha256:21900ce7ba264168cd50defae43cd75d25c833ad4ad6e73ffc5596d12e25ac89 \
    --hash=sha256:236ff70b9312fb68943c703aa842ca6a758abfa45ac187a5e7c1452e96ef72b5 \
    --hash=sha256:23aceaa007d6172b02c277f0cd359c79492bbb14f7072b4ede9fbcaf20648130 \
    --hash=sha256:23d27a3e0307ec2244cc51e7287b919aa68d097504ebe19df4e76a98a3eea5bd \
    --hash=sha256:24870b09b224f7ae3c39ed07d10e819d06f8720bc551847b1d623832b5b0e28d \
    --hash=sha256:251bf95b67017e27b13d82f5b326234ca62d70f9cf4c2b9032de2358a3b12c7b \
    --hash=sha256:25b9b82bb22e6e2b3cd07b39c68b7b862001226cb3dff7130d1cb914121b39ed \
    --hash=sha256:28ce87c5ab450a9dd970b52e5aca5fe63ed432d18a2eaddd1979a00a1ba24ace \
    --hash=sha256:300557495eb45ebb8aec96c2da9c4be642fbf7cd937278b4013ba894ea8eb0eb \
    --hash=sha256:30f2aa603c41533cc25c05acd0da21636e84a315768feb631c937177db558931 \
    --hash=sha256:331b624368d4f1d069149002f25f44bc61c8919ce8ddb3c45bdad8f6e2d89510 \
    --hash=sha256:37d6d0a00072fd2948eb22bce7e1475f34569d90c87c59f7a2ec59541b77f7a6 \
    --hash=sha256:37dc8f7bbb66efe481bb60defacef820c950c24713fb44962ed6aa2a50966de1 \
    --hash=sha256:3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce \
    --hash=sha256:3edce1d53195db527e0191f84b71d02022de0540bf43a16ed734ed7537b07385 \
    --hash=sha256:446c34dcc4324b084a53b705127dc15717b22c5e140ae0a3c38349d4efec071e \
    --hash=sha256:4998562bf62a445225f22e07c896bb04b35b1b1f2eb6d760584c9c51d7a5f78c \
    --hash=sha256:4b0a7fe987b14c31ebda6083f74f22b561fd3739bc0ac51e019622e3d72668c7 \
    --hash=sha256:4e8c2a84d977f50b9daed6eeaf3baef67d00d5d74d932288f02cb94518ee3ace \
    --hash=sha256:4f883547d4b7f0495ebe7056b0cc2aea76094e7a4abc8e933540f3271df27d9c \
    --hash=sha256:514435a37670e3e5e08f3945b68718b6ed329bb84367777e16f9f4dfe1e61a0f \
    --hash=sha256:53aa02d20d10c3d814d536aa4e5ac9b84ca0ff5a88377963b085ad6822f93e64 \
    --hash=sha256:5594fc43d548a7ed94949d139aa1341b270f1863f11cfd37f5a6c8b778a6b67f \
    --hash=sha256:571b9fcb07b97ef3a492028fb3d2dc0993ca23a06138b0315286566d29ef718a \
    --hash=sha256:57b3d78c95ba9059768b10e28b813002261d3f3dfc55cc48b0c988f625175827 \
    --hash=sha256:5afb51d599ea772b8365ae807ae557f18bccfe46ab261fd1c2a9ed700fc6eb17 \
    --hash=sha256:6b02afb9b97f65fbca5f31db6a2a3ba21aa93030225f150fa3f249717e938fb4 \
    --hash=sha256:6c0016e7b354317c4e9e525b937ac8596c38d2d232b419529b9cd7a1cd46e39a \
    --hash=sha256:71d6097b330eea8fd15097780c8e89cb1a8ce7838669f48c5bacd6f663dd4701 \
    --hash=sha256:756c768d0c9c2955feb7a56c37ea24aea2e369f8d36a88da270b6a9f19e62b5e \
    --hash=sha256:78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91 \
    --hash=sha256:7a743ff716f746fc19a9557f60dab1600d4613255f8a7aeb3cdde4db7eb15a66 \
    --hash=sha256:85f998ea1848bc6757289e739cfbdda3a04adfd58b02fc018ce54d754a5ce468 \
    --hash=sha256:8728f216dcdb6e6d555cf971cb34076139ad74b31fc2c14da4fafc741c5f6217 \
    --hash=sha256:877c3f311ff35410f690861c4409e7ccbf0cd2f878e50628a28e5a0bb689e658 \
    --hash=sha256:8cd2f7bdda092d99c9fc2fb7391354f306d01443d22785d0cbfafa2e2c8bb418 \
    --hash=sha256:8e95e1385e4998ae9694eeaa4730ba5457ff61185b3a55e2e7bea0880aef452a \
    --hash=sha256:962864dc93511324d51ddbb5b9f8731bf71675b93ca612a07441896f4688fb8c \
    --hash=sha256:9cf95fe4d0f84c82d282745d9bb08ad9f926efa00be4697e767b814ce40d4330 \
    --hash=sha256:9e881fca225083806662a5c43d627d215f258ff43c890f831966c7d7ba9c7402 \
    --hash=sha256:a2b55dd6b2a4c4b7d87ffa56bdb33fdc5fdb9a462173861a7bc097f17d91cb09 \
    --hash=sha256:a45650e8ce7fafffd731db8550230db6b0d306d181a90b67d3e6bca2f1990930 \
    --hash=sha256:a876864214e136f0eb367788dbd7df045f4806801518e2cfe9e13229cfe06d8f \
    --hash=sha256:ae26d61dfa7a47befdc7572b521024e8745f3d809bd95ca9505a7bba9ef849ec \
    --hash=sha256:af8d94b0db561cf68b88a267c5c44b49e134f525d0dc2cb7ed413a66bc23559a \
    --hash=sha256:b343699e8308bdc51978310e1c959c584e7869cc8c40780058c87da7781a1e94 \
    --hash=sha256:b3c777e849237620b022f7f297dd67705f9f5cf1685f09f02e46f93e92725468 \
    --hash=sha256:b629de27fda84b42cde7edef0d85f13b958b47f6e9bbcbba9b673c562a89bd8b \
    --hash=sha256:ba09209fbe443b4acccebe845d8a138b89a8f4fbaeedd44953490b5315d5e965 \
    --hash=sha256:ba54cfebe86920a559a7c4d6b9050791c20513650a1952ebe3368c7dc70306f8 \
    --hash=sha256:bcb46e2f9feff8d06323983bd83ed00c201fdcab3d74973e7072a889b3979fcd \
    --hash=sha256:bcc33feacfaefce60c12fd500a277533bdc02b10a19f7f6d348763d8140bbba7 \
    --hash=sha256:bf16ba1b4d0b6b7c8e534936632270cf70eb00dbe09005bc345b2677b726855c \
    --hash=sha256:cf1845d02ad822a369a49f2bb9345b1614744267682e7a03527dc3bf6eea1777 \
    --hash=sha256:d69141514cc30b774ceea5e3ed3a6635c8d8a96edf664689b890f4089111fb35 \
    --hash=sha256:d9c7f76c0673154f044e9d78c8655fb4213f6ca31a836df48b40fe5d187717b9 \
    --hash=sha256:dbce0b29841537a2fa4a214c2bbf14de3587c9680caa9b4e217568472490b28f \
    --hash=sha256:dc624f6bc473dacdf7ef7eb8678d0d08edf15cd94fad6ae5c7d6cc67a4e4902f \
    --hash=sha256:e158cb00350dc278f3b91551101aa7d12415a66ebf2c91d8d5ac14e56ddd3ad0 \
    --hash=sha256:e491916b378fba47242221bb9ead245211b70d504f495d105d17b14a24b4907c \
    --hash=sha256:e795b7eb908249c4e43c7c99fac7c2c75dab0c43566e37db472a355f63693d71 \
    --hash=sha256:e7e480451b9fa137494bccd3a7d69adbe8ac65a87d97be61e11f1b1050a5bac3 \
    --hash=sha256:e91206ee562682b51b98ef4b26a6ef48fd84e15fd4c4bc5ec768eb641d206838 \
    --hash=sha256:e9871b1ffbfa9656b60aeee92ed5136a5742696006fa322b29ea3d8da0ecc9cf \
    --hash=sha256:e9aeb04d6aef139de265b29683e119b638208f88cf73cdd1658aa07221165321 \
    --hash=sha256:ebaea975e03d3141d9d3a507df75c9b3ec90fa9d2ffd07567b3a978d9d790b26 \
    --hash=sha256:f0606c8bf2cdefea14a43530f7657cbbb7ecf1c4222512492ef4a4434a9501ec \
    --hash=sha256:f13c32a3abd6079a66d9526e18dad9b6d280384d49d7c54040cd57b6424041d9 \
    --hash=sha256:f7401aebd7f581d7f83a439d87d474999317ee099218e5ad25d125290990ba65 \
    --hash=sha256:fa4ecea169a355be7a3ade2c783e2ed12f0e40d2c5621cda8b3297faf7fbb9f5 \
    --hash=sha256:fbd139c8447d25dd750ab79ee274cc5e1fe80fc56340ab10b18a195e1b6eca3e \
    --hash=sha256:fdafc9cce40277e0f7a0feabce0ee50dd2fa1800f3b38015e51296b5e814048d \
    --hash=sha256:fe3cca2e4e8a592be0f269a1ca4835c25199d9f3ce815c8491048f785b0a0198 \
    --hash=sha256:ffd0c5368496f41b0944be820fcb7a838aa6e623d250b01acf2643939c3f99d7
pluggy==1.6.0 \
    --hash=sha256:7dcc130b76258d33b90f61b658791dede3486c3e6bfb003ee5c9bfb396dd22f3 \
    --hash=sha256:e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746
pycparser==3.0 ; implementation_name != 'PyPy' \
    --hash=sha256:600f49d217304a5902ac3c37e1281c9fe94e4d0489de643a9504c5cdfdfc6b29 \
    --hash=sha256:b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992
pydantic==2.13.5 \
    --hash=sha256:346a034f080da3755d8e9cb5e00e8b07de1d39e4f6e2c87d8ab7cafa0b269a73 \
    --hash=sha256:51a9c5f7b2f8e636f04c6cada605d9b6a3bf1348fdf945a3d8869b19bba0ee08
pydantic-core==2.46.5 \
    --hash=sha256:013d6f3483d81e02e7c328831808f336c8596ee33b4bd4026b9ffb1e960b8942 \
    --hash=sha256:03b9666e41e35d8909852ba191a0607520f81b74eaf12ccf8737005dbb313821 \
    --hash=sha256:045ab3b6d308439e32b81cc173bba5b9018bc6ed896afd0c65b3b009b1699af5 \
    --hash=sha256:0bddb4020d8f04175865ccd17eff3040874fc11fb593f424edb452653b4b947c \
    --hash=sha256:0cdbada856a1c69a7624a64d3d9aefe79300bd6ef827b43a4f265010b9b55184 \
    --hash=sha256:0fc5be0abd4a407e200d844b404e33639a554e7bd0d448e7b9ae181be4789ac2 \
    --hash=sha256:10416c15b8839ecc4ef4d0885da76da6fd0f67333a0eb8aff6d93c4b8f2910fc \
    --hash=sha256:15f4a94963c95accac15b7b657bb177d3ad82bb90b0d0526d9a9b85079925db5 \
    --hash=sha256:18a09e1e1011b462f2e32774f25859ef1223d5c2b0546a633cf56654710721e0 \
    --hash=sha256:193375f3548919d3f0b60936ca113ada3e38f264f91b9b8e0508efaad57be931 \
    --hash=sha256:1a353f84de772f423b5ffb11d7ae352fbbef0f446f3c0b0af0f8236d7233606e \
    --hash=sha256:1e449def1945a462c464331254e5a44fca7c3b4f9aedf59ec2f50f8066dd8e25 \
    --hash=sha256:1e5aad1220a1192c42341c8fd4a8686657e73ab2a920c970bdc4de334fe3193d \
    --hash=sha256:200aa3dc9f8d54f0754f43247c0bad0999fdcfbfd2488384dd44f37279271fe6 \
    --hash=sha256:2471fd51c61c610e1dcf7de44d7299283661654d11264ab4802b303368d69c47 \
    --hash=sha256:24922243639cbdac66c75fcb6fd6495a9cb52b213d62f9a0d16f0310b1ff8038 \
    --hash=sha256:28a6a556cd3b6066bea827857f9d9cce027c96f776e512f544a581f9e42161f8 \
    --hash=sha256:2bc9419666990c06d7397831f2126a1ecc3594aaa3ff7de5bf2d066802f4e07b \
    --hash=sha256:2cbd9a5eff05e51c447c34dfa4632145b26b09120cf04bd0c871e44c1a5e1c9a \
    --hash=sha256:2d330aaba8621b1edcec8ae2c4050f63b84ccf6d98723a8f212e9684713abf0e \
    --hash=sha256:2d5d76654becf5efd62c9e51c3756c67b49498b0c9a40884934c40807adbd074 \
    --hash=sha256:337639ba62a11acde6ef3aeb08c8ea755f8ef1fe5e513356c0f36a2b0d7568b0 \
    --hash=sha256:347ec774390c87326a2e4929d58d3f7e8763a104d5d35f4cd595a4c952366433 \
    --hash=sha256:356c8368cbc321050b169595683a2e1d63413b1e0e2868b330af9fc14c616d3f \
    --hash=sha256:37ae34309d7bd8c0d61ab839668058f2a7962ea1fc51d105d2db228fe0618034 \
    --hash=sha256:37ea7b83c935e5b0d68c9449b82651accf78a10828b2c02b2f2d9e9496446c21 \
    --hash=sha256:3a3e26b6a8274211bddee2d0e4d0d42778f17a34510f49d2ec44b58abfc41736 \
    --hash=sha256:3aa166e99c4f2985407fb8714aebede877ecb5455cf321b606adca926d30d5a0 \
    --hash=sha256:3d2652072b2d774947ba5cf78a9e59644ac62ee572daf6dd2e1dfe905e15b2b7 \
    --hash=sha256:40375c2d05acec10323e45dfe2077ac44bc74659008614af5069034e2cfc781c \
    --hash=sha256:413a717a410d0c817ef5b786a059415550b3794e1d0c2abffd9efb93a3d9f7b4 \
    --hash=sha256:46c25dda9d092a06c08db76ffe0a197107904d0dfac653f7d5306bbcd6d6119c \
    --hash=sha256:49776eab08766a08dfff7012f8b422dcd7e25e43b316eedf0477c24fcfa84b7c \
    --hash=sha256:4d44cf99ddebf875f9b68cc267aa684c99b7b44fe63ee1cac4ec163807290069 \
    --hash=sha256:4dedce55295becb61921e386b99d4f2706045306e7fa52249a33004c837379fb \
    --hash=sha256:4f8507560a9284e1370bb048ed4282012fbef4e8d109875b95e884d228552061 \
    --hash=sha256:4fdc8b93a41521988916eeaa271173fcca7fa0803d62f87675aac8dcec1c8e29 \
    --hash=sha256:5086029a57366b8cf81b130a43908738095c270c21a8d7f0e8bdfdb89718e2f3 \
    --hash=sha256:52e24eacdb536cade636aa90fb851835222becff8484b7001fdc78cb0290f2aa \
    --hash=sha256:53feb344243bb9510a9dec7bf3cf1b64d88a98af5dc7872a5160465f8b198c8e \
    --hash=sha256:545f26c504b27c3758439a5e6d9349931f0a04f855668d5fe323c89e82300a38 \
    --hash=sha256:54d510bac3ee52247af28ed4bb18a1e799f040ac60fd2bf5ccd4c92f1fbe786f \
    --hash=sha256:5cb482e9e84c851f4e623fe4acc1ced89168cf1fe18f7089db4548c8f5bbb65b \
    --hash=sha256:5e81740c09e310f5aa5cbd3e434a01c154d4bef93241c7877b39f211d2b78ba8 \
    --hash=sha256:5ee239d575f80b08eca11f6e20f90c4c695de7825c67eefe6091fbf20dda648e \
    --hash=sha256:5f194189415698233dd1114a093a9b56e61e2c57e11b469be3b0506f46f0771c \
    --hash=sha256:5f93c5fe914d75fbec9a49209b00da5f08e9e467d69da2b1510c81940cfd10be \
    --hash=sha256:657b40d6240c0a7b6a64b30f22d1e3aa631c7e846c621b0c0f6d1d75e2e15ea6 \
    --hash=sha256:6d30e1a4f138b8951063e9a394752a9179b51da288ffa507b1e659222f4c1793 \
    --hash=sha256:6f7b393a8b3da82f5c1fc0751e6d01ac6c55b93c18226a60bdfba4a724efafd1 \
    --hash=sha256:701b2e04b560eeb4bddf7a25ab8ca476176e34fdbd9a0e18196f0d12d4685f0b \
    --hash=sha256:771cf63ae0b1b50dd22e5f3e3549fab5f3f4ff1635d352a9e1a97fe01c7b2e64 \
    --hash=sha256:79bdfa52f843137045b2d081cc05c120ba6665d29b7559c2c47690906f39279f \
    --hash=sha256:7ac031912d54f3d83ef3b3eb98dfabc1608802e2202263d25957eeed40b94761 \
    --hash=sha256:7b0fc826b16c55e561e5d2a0c5c77b051ba1d92808118c4e4b5390f5e0cf191d \
    --hash=sha256:7c6be839a5a8312626b32029a415644a0846b420bc8b52b95b28cd92da162168 \
    --hash=sha256:816ff0a6550ffc06c098ccd2e0698600f9aa7da192a79eaa6f9af504a35db869 \
    --hash=sha256:82a36973cf8a2ef5406f4fe2edbf8ed0c99629535d959e0b100c76a32535a111 \
    --hash=sha256:837b396ca3d7b74091ca623f6cbd8351bd42d670a79c2683e79fb089f06a2de5 \
    --hash=sha256:850a08d167dde16db8702c274f320c7be9d7da6f6dff2b58b18f9e815bd94f5b \
    --hash=sha256:8816f3d218beb4b787de5c9759c259b8fa61f9dec42dc7811f320a33771778b7 \
    --hash=sha256:892a881d5f68c2b9ea304b7a6c2c60d9343df578a311b0f86b94bc8f1ffe8129 \
    --hash=sha256:895395f8918627b04efb1ad2a4cf605387143300ba03304cd1dfa6d03f5e095e \
    --hash=sha256:8b10e3e8fd7ddc2bd915848a2768e44c15b22936f1cc54c462ad1164deb02655 \
    --hash=sha256:8e24d8f05fa2d28513d94e877e9c75ad66175376209b3977f916e240e623193c \
    --hash=sha256:8feeac04b5794e513e710af2f9c87d49f31a6dc47967bb264a1fed61a8989bec \
    --hash=sha256:9432f3598db432cb51c5b37fdbf29a60fcccc79e30d37a05022776a6bc4ab689 \
    --hash=sha256:976e1128455aa595ea04c79ccfedff1aaeab96ee013fcc916bed120c4f0ad94f \
    --hash=sha256:978e7b97d4824b5be09c69fb70507cbde3b0323fc147332ca40a94d9a6a0ebbf \
    --hash=sha256:97bf8de4d541598c94a59344eeb988a94c08ff76b5723c41f6567ec18c7892ea \
    --hash=sha256:97cf3eb53a8cccacf9d46686a0926186c9bfb5574f2ed66d3639d5fe117cd3a9 \
    --hash=sha256:9b68938dd5b0c783d88ff8e2dcc69451b5eb936fe212d516b21b9d5567f6d464 \
    --hash=sha256:9c4b71f10dd532fb7a5cbc8f58707779e64f03a258c2bf8bfbaecfcd9970b519 \
    --hash=sha256:9f47b8a949e60f027f0aa0a6f6c7b7e9c55cbf4380d10b344e282fa4e7ab1e1b \
    --hash=sha256:a1dee1b804ff4d11c663636cf15d2ea47e9f79cd56c033fb1cbf08924842a48f \
    --hash=sha256:a2468d93d181667a7abd66e1b64bb9f76f361b0fef8faddf687456453576f5ee \
    --hash=sha256:a2a5e1d0ff29adddc9f6d6821a66302e4493f8ca898b715b6b1182c2c201ea0a \
    --hash=sha256:a39ac25a9a2fa4072efdb429833c4a4c8009a51ff9eea3eeae131713cd27991e \
    --hash=sha256:a445486499897b88a7d6c310c88ed64dd37b1b59bfd7ae9107490bbb362f47d6 \
    --hash=sha256:a91c17edf6eea2402cb5457b4c89e99bc5ed1004aa34c4adf1d4258c1a5c22c2 \
    --hash=sha256:ab4b66edffb32d9e951efb3814bd104b8367a7501b81b955cacb5726d897389f \
    --hash=sha256:aca6c767f552b21b10f774aeac128e828eafb796adfa1b666a18bf6321453c3a \
    --hash=sha256:acf8a67ba51f4ca9ddbd0e6b3000a65ac51ab734661778b3e7ba64d99a710f2f \
    --hash=sha256:b10ec717381bdbfafef34607824db4c91de69ff085e4fca3b2af91b4fa17e68a \
    --hash=sha256:b49924c73a235e969511bf2aabdff3beebf9820931f646c80274d5d780010c47 \
    --hash=sha256:b6acfb46a814762367fb7ba0828b0a17d441b92ce249a0e007474c9072662dda \
    --hash=sha256:b7ca9034437b6022f941f4857459562ee00a560b97e7cce8a0ec5a74fc6766e0 \
    --hash=sha256:b98134087d9de723658d17a42c7d0da8d6e2ef08015dee7dc93889047315f5e4 \
    --hash=sha256:b9fe6fb92520e3fd61f2e49000b6911b188824f089b75973ea06d6267f0b476d \
    --hash=sha256:bce57638e08ac148e5778cce7feb968307a727d66f8e2274a543d0cf0c9ad6a3 \
    --hash=sha256:c14ad3bdc85ee7f318742c457ca3968a92126d144b15721c759033bfb06296c2 \
    --hash=sha256:c1c43ad4339643d70ebb8124e1305a7dab423001eff58bb41a0f731adbc98355 \
    --hash=sha256:c3471e5c4a949c26ec00a77f01df59096aa9495877de76fd60a980f8ee6be461 \
    --hash=sha256:c583b927a8838dab890706a6fa7573fbb8b70e24000ef9f7238e2d6f6435a5ed \
    --hash=sha256:c76fe65e607be28c7fd4d56fc3c42b1583aa058ce3408b7ad0fd540171d31f9f \
    --hash=sha256:c7ea57fc63aa7da93a1bd2d644e6577befae10c52c4e36377635eea1056a74f5 \
    --hash=sha256:cd5214352ae68f3b5e9af7768bdc5253695ee069675db3480518420b3be881f2 \
    --hash=sha256:cdbb78909f52b981d3b2d56b97328d71eb0b974c36bd77c920123a7ebb192829 \
    --hash=sha256:cdc8b74ecc48c0cb1e9607a05ec4e9e88db60a19ffcc9a1d5f9088ede40c8dc0 \
    --hash=sha256:d0a24b40877af2de4950252be9d21eaf7fb07660f3c2cae1f56c6b599ada5266 \
    --hash=sha256:d22a945598fb91236b4dd793a6e42e4f3dd7740bb5aace5ebd7d4c08d13bb575 \
    --hash=sha256:d2f9fc07a8042a8f95925b35c4f04f469707c981fc33245b6ca187cf5d2dd290 \
    --hash=sha256:d625a186a65201c23a9e3b8ed9c47e90a026e03256608cc91851c6709096844f \
    --hash=sha256:d925f3d9afd05a8c0fb3a1031463a8d59ebe5e2afad297e29c78be19e13b4e62 \
    --hash=sha256:e64e88d5585bea9ce95861079de72006c7fa6d3df4e3a3b65ba31eb979c15c9f \
    --hash=sha256:e652ab17569c94bff5475520f907b7148b8c24036a8ebbe5cf7cf7493d28579a \
    --hash=sha256:e7b891faeedeafba41b2983e5001a81b6a915b69544c7e7570d1989ce1c36ac7 \
    --hash=sha256:e80675d75ae2cd14372cb65cad5400d9347a3d3f6c13000183f22dfd027283ed \
    --hash=sha256:e9c134bb666dd54b778b9fc0d2b50cbb7f979b9e3716f26a88c9ab3b6fc1dd0f \
    --hash=sha256:eb7d8d0e5886a89a55d2eef490e272fa965a9d57c6b29a5b5088a7997ec2cad1 \
    --hash=sha256:ecb42011e12ee19cafbc312887cbf3546959fe02fbad44f272d4be5baa997615 \
    --hash=sha256:ef3fbbf161dc9351a2fe0422e51b129f9e97e42385bd0320b309c15f7d287dd8 \
    --hash=sha256:efd62a42486f1bda5d24cb4f63d15a3c7768375fe83d36f9417b4ad7a2fb20b3 \
    --hash=sha256:f077d0b97ab11fa7dcc633fca53515f290bca8a8a633e966d5b6d1879d9ed01a \
    --hash=sha256:f332f0e72a5a0400141f830744e141bf9f97917878dbe968669e8a7fefea78ff \
    --hash=sha256:f7b0ec93a2893de856652154d73b7ba622f26fa97726487dcac373de5f4c6084 \
    --hash=sha256:fa10ef4112775900e7a0661068635eb67b2ab824fbde764de6e0e21982a93db0 \
    --hash=sha256:fc5d783bd4a2387e97b8a2d5ec781cfb92b3d893bf82370548e99db5915935d3 \
    --hash=sha256:fc8515076c11f3cfdf4fb142dcca0fe384b1230a3b5415458ac84f3e0903ec13 \
    --hash=sha256:ff218293c9c806138dca139765e3b067621be52bcd93cdc14c7711be7ddc90a9
pydantic-settings==2.15.0 \
    --hash=sha256:0ba092c291c94baceb5eff768aa0d56400a457585bc0175925a5a5510303da42 \
    --hash=sha256:694b793e84f766ba76a90ebdefc01d0a9a045dab0382bee70393da93712ad117
pyjwt==2.15.1 \
    --hash=sha256:42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193 \
    --hash=sha256:4f259e80cdfb6b3fc18a7de51fd1ef9ec79652f25019bae68975ca2468a34df8
pynacl==1.6.2 \
    --hash=sha256:018494d6d696ae03c7e656e5e74cdfd8ea1326962cc401bcf018f1ed8436811c \
    --hash=sha256:04316d1fc625d860b6c162fff704eb8426b1a8bcd3abacea11142cbd99a6b574 \
    --hash=sha256:22de65bb9010a725b0dac248f353bb072969c94fa8d6b1f34b87d7953cf7bbe4 \
    --hash=sha256:26bfcd00dcf2cf160f122186af731ae30ab120c18e8375684ec2670dccd28130 \
    --hash=sha256:2fef529ef3ee487ad8113d287a593fa26f48ee3620d92ecc6f1d09ea38e0709b \
    --hash=sha256:320ef68a41c87547c91a8b58903c9caa641ab01e8512ce291085b5fe2fcb7590 \
    --hash=sha256:3bffb6d0f6becacb6526f8f42adfb5efb26337056ee0831fb9a7044d1a964444 \
    --hash=sha256:44081faff368d6c5553ccf55322ef2819abb40e25afaec7e740f159f74813634 \
    --hash=sha256:46065496ab748469cdd999246d17e301b2c24ae2fdf739132e580a0e94c94a87 \
    --hash=sha256:5811c72b473b2f38f7e2a3dc4f8642e3a3e9b5e7317266e4ced1fba85cae41aa \
    --hash=sha256:622d7b07cc5c02c666795792931b50c91f3ce3c2649762efb1ef0d5684c81594 \
    --hash=sha256:62985f233210dee6548c223301b6c25440852e13d59a8b81490203c3227c5ba0 \
    --hash=sha256:68be3a09455743ff9505491220b64440ced8973fe930f270c8e07ccfa25b1f9e \
    --hash=sha256:834a43af110f743a754448463e8fd61259cd4ab5bbedcf70f9dabad1d28a394c \
    --hash=sha256:8845c0631c0be43abdd865511c41eab235e0be69c81dc66a50911594198679b0 \
    --hash=sha256:8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c \
    --hash=sha256:8b097553b380236d51ed11356c953bf8ce36a29a3e596e934ecabe76c985a577 \
    --hash=sha256:a84bf1c20339d06dc0c85d9aea9637a24f718f375d861b2668b2f9f96fa51145 \
    --hash=sha256:a9f9932d8d2811ce1a8ffa79dcbdf3970e7355b5c8eb0c1a881a57e7f7d96e88 \
    --hash=sha256:bc4a36b28dd72fb4845e5d8f9760610588a96d5a51f01d84d8c6ff9849968c14 \
    --hash=sha256:c8a231e36ec2cab018c4ad4358c386e36eede0319a0c41fed24f840b1dac59f6 \
    --hash=sha256:c949ea47e4206af7c8f604b8278093b674f7c79ed0d4719cc836902bf4517465 \
    --hash=sha256:d071c6a9a4c94d79eb665db4ce5cedc537faf74f2355e4d502591d850d3913c0 \
    --hash=sha256:d29bfe37e20e015a7d8b23cfc8bd6aa7909c92a1b8f41ee416bbb3e79ef182b2 \
    --hash=sha256:fe9847ca47d287af41e82be1dd5e23023d3c31a951da134121ab02e42ac218c9
python-dotenv==1.2.4 \
    --hash=sha256:42269a8a5b3fd54ffa6f3d84b18abed50064717576b4ecf03dc4a55d8aa04fdc \
    --hash=sha256:f0d53e69935a851c0dcc78f3ab7aaccd8cabef0b92382b576b824212902873c0
python-multipart==0.0.32 \
    --hash=sha256:be54b7f3fa167bb83e4fcd936b887b708f4e57fe75911c02aebf53efaf8d938e \
    --hash=sha256:ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23
pywin32==312 ; sys_platform == 'win32' \
    --hash=sha256:02ebca0f0242b75292e218065004310d6a477407c09fa449bfe4f6022bc0c0fc \
    --hash=sha256:17948aeadbdb091f0ced6ef0841620794e68327b94ee415571c1203594b7215c \
    --hash=sha256:3020656e34f1cf7faeb7bccd2b84653a607c6ff0c55ada85e6487d61716deabd \
    --hash=sha256:59aba5d5940842075343a5ddc6b11f1cdf0d1567fe745290359dfbcc7c2eb831 \
    --hash=sha256:5c1fbe4a937a73ae9297384a3da38518cbc694c68ad8a809b2e19acd350f03ed \
    --hash=sha256:5dbc35d2b5320dc07f25fa31269cfb767471002b17de5eb067d03da68c7cb2db \
    --hash=sha256:6017c58e12f6809fbb0555b75df144c2922a9ffd18e4b9b5afa863b6c1a9d950 \
    --hash=sha256:772235332b5d1024c696f11cea1ae4be7930f0a8b894bb43db14e3f435f1ff7e \
    --hash=sha256:7a27df850933d16a8eabfbaeb73d52b273e2da667f80d70b01a89d1f6828d02c \
    --hash=sha256:9fce94568364e0155e6dfb781ac5d95903be8baf28670632beab1b523f300daa \
    --hash=sha256:a4dd3a848290ef724347b19f301045831d8e802fa4464f491b98b1e0a081432e \
    --hash=sha256:a77a90fbb6881238d2ca9c6fd797b25817f3768fe78d214a90137ff055a75f5b \
    --hash=sha256:a8597d28f267b39074aef51fa593530082b39cbe5a074226096857b1fed2dfb9 \
    --hash=sha256:b2200a054ca6d6625c4842fc56a4976a4b47f96b73dbe5538c3f813a80359f47 \
    --hash=sha256:b457f6d628a47e8a7346ce22acb7e1a46a4a78b52e1d17e1af56871bd19a93bc \
    --hash=sha256:c2f03a0f73f804a13c2735b99392b0cd426bb4f2c4d0178e5ac966a0f21618d5 \
    --hash=sha256:c53e878d15a1c44788082bfe712a905433473aa38f86375b7cf8b45e3acbaaf9 \
    --hash=sha256:d11417d84412f859b722fad0841b3614459ed0047f7542d8362e77884f6b6e8a \
    --hash=sha256:d620900033cc7531e50727c3c8333091df5dd3ffe6d68cdca38c03f5821408d5 \
    --hash=sha256:dab4f65ac9c4e48400a2a0530c46c3c579cd5905ecd11b80692373915269208b \
    --hash=sha256:dc90147579a905b8635e1b0ec6514967dcb07e6e0d9c42f1477feef14cac23bb
pywin32-ctypes==0.2.3 ; sys_platform == 'win32' \
    --hash=sha256:8a1513379d709975552d202d942d9837758905c8d01eb82b8bcc30918929e7b8 \
    --hash=sha256:d162dc04946d704503b2edc4d55f3dba5c1d539ead017afa00142c38b9885755
pyyaml==6.0.3 \
    --hash=sha256:00c4bdeba853cc34e7dd471f16b4114f4162dc03e6b7afcc2128711f0eca823c \
    --hash=sha256:0150219816b6a1fa26fb4699fb7daa9caf09eb1999f3b70fb6e786805e80375a \
    --hash=sha256:02893d100e99e03eda1c8fd5c441d8c60103fd175728e23e431db1b589cf5ab3 \
    --hash=sha256:02ea2dfa234451bbb8772601d7b8e426c2bfa197136796224e50e35a78777956 \
    --hash=sha256:0f29edc409a6392443abf94b9cf89ce99889a1dd5376d94316ae5145dfedd5d6 \
    --hash=sha256:10892704fc220243f5305762e276552a0395f7beb4dbf9b14ec8fd43b57f126c \
    --hash=sha256:16249ee61e95f858e83976573de0f5b2893b3677ba71c9dd36b9cf8be9ac6d65 \
    --hash=sha256:1d37d57ad971609cf3c53ba6a7e365e40660e3be0e5175fa9f2365a379d6095a \
    --hash=sha256:1ebe39cb5fc479422b83de611d14e2c0d3bb2a18bbcb01f229ab3cfbd8fee7a0 \
    --hash=sha256:214ed4befebe12df36bcc8bc2b64b396ca31be9304b8f59e25c11cf94a4c033b \
    --hash=sha256:2283a07e2c21a2aa78d9c4442724ec1eb15f5e42a723b99cb3d822d48f5f7ad1 \
    --hash=sha256:22ba7cfcad58ef3ecddc7ed1db3409af68d023b7f940da23c6c2a1890976eda6 \
    --hash=sha256:27c0abcb4a5dac13684a37f76e701e054692a9b2d3064b70f5e4eb54810553d7 \
    --hash=sha256:28c8d926f98f432f88adc23edf2e6d4921ac26fb084b028c733d01868d19007e \
    --hash=sha256:2e71d11abed7344e42a8849600193d15b6def118602c4c176f748e4583246007 \
    --hash=sha256:34d5fcd24b8445fadc33f9cf348c1047101756fd760b4dacb5c3e99755703310 \
    --hash=sha256:37503bfbfc9d2c40b344d06b2199cf0e96e97957ab1c1b546fd4f87e53e5d3e4 \
    --hash=sha256:3c5677e12444c15717b902a5798264fa7909e41153cdf9ef7ad571b704a63dd9 \
    --hash=sha256:3ff07ec89bae51176c0549bc4c63aa6202991da2d9a6129d7aef7f1407d3f295 \
    --hash=sha256:41715c910c881bc081f1e8872880d3c650acf13dfa8214bad49ed4cede7c34ea \
    --hash=sha256:418cf3f2111bc80e0933b2cd8cd04f286338bb88bdc7bc8e6dd775ebde60b5e0 \
    --hash=sha256:44edc647873928551a01e7a563d7452ccdebee747728c1080d881d68af7b997e \
    --hash=sha256:4a2e8cebe2ff6ab7d1050ecd59c25d4c8bd7e6f400f5f82b96557ac0abafd0ac \
    --hash=sha256:4ad1906908f2f5ae4e5a8ddfce73c320c2a1429ec52eafd27138b7f1cbe341c9 \
    --hash=sha256:501a031947e3a9025ed4405a168e6ef5ae3126c59f90ce0cd6f2bfc477be31b7 \
    --hash=sha256:5190d403f121660ce8d1d2c1bb2ef1bd05b5f68533fc5c2ea899bd15f4399b35 \
    --hash=sha256:5498cd1645aa724a7c71c8f378eb29ebe23da2fc0d7a08071d89469bf1d2defb \
    --hash=sha256:5cf4e27da7e3fbed4d6c3d8e797387aaad68102272f8f9752883bc32d61cb87b \
    --hash=sha256:5e0b74767e5f8c593e8c9b5912019159ed0533c70051e9cce3e8b6aa699fcd69 \
    --hash=sha256:5ed875a24292240029e4483f9d4a4b8a1ae08843b9c54f43fcc11e404532a8a5 \
    --hash=sha256:5fcd34e47f6e0b794d17de1b4ff496c00986e1c83f7ab2fb8fcfe9616ff7477b \
    --hash=sha256:5fdec68f91a0c6739b380c83b951e2c72ac0197ace422360e6d5a959d8d97b2c \
    --hash=sha256:6344df0d5755a2c9a276d4473ae6b90647e216ab4757f8426893b5dd2ac3f369 \
    --hash=sha256:64386e5e707d03a7e172c0701abfb7e10f0fb753ee1d773128192742712a98fd \
    --hash=sha256:652cb6edd41e718550aad172851962662ff2681490a8a711af6a4d288dd96824 \
    --hash=sha256:66291b10affd76d76f54fad28e22e51719ef9ba22b29e1d7d03d6777a9174198 \
    --hash=sha256:66e1674c3ef6f541c35191caae2d429b967b99e02040f5ba928632d9a7f0f065 \
    --hash=sha256:6adc77889b628398debc7b65c073bcb99c4a0237b248cacaf3fe8a557563ef6c \
    --hash=sha256:79005a0d97d5ddabfeeea4cf676af11e647e41d81c9a7722a193022accdb6b7c \
    --hash=sha256:7c6610def4f163542a622a73fb39f534f8c101d690126992300bf3207eab9764 \
    --hash=sha256:7f047e29dcae44602496db43be01ad42fc6f1cc0d8cd6c83d342306c32270196 \
    --hash=sha256:8098f252adfa6c80ab48096053f512f2321f0b998f98150cea9bd23d83e1467b \
    --hash=sha256:850774a7879607d3a6f50d36d04f00ee69e7fc816450e5f7e58d7f17f1ae5c00 \
    --hash=sha256:8d1fab6bb153a416f9aeb4b8763bc0f22a5586065f86f7664fc23339fc1c1fac \
    --hash=sha256:8da9669d359f02c0b91ccc01cac4a67f16afec0dac22c2ad09f46bee0697eba8 \
    --hash=sha256:8dc52c23056b9ddd46818a57b78404882310fb473d63f17b07d5c40421e47f8e \
    --hash=sha256:9149cad251584d5fb4981be1ecde53a1ca46c891a79788c0df828d2f166bda28 \
    --hash=sha256:93dda82c9c22deb0a405ea4dc5f2d0cda384168e466364dec6255b293923b2f3 \
    --hash=sha256:96b533f0e99f6579b3d4d4995707cf36df9100d67e0c8303a0c55b27b5f99bc5 \
    --hash=sha256:9c57bb8c96f6d1808c030b1687b9b5fb476abaa47f0db9c0101f5e9f394e97f4 \
    --hash=sha256:9c7708761fccb9397fe64bbc0395abcae8c4bf7b0eac081e12b809bf47700d0b \
    --hash=sha256:9f3bfb4965eb874431221a3ff3fdcddc7e74e3b07799e0e84ca4a0f867d449bf \
    --hash=sha256:a33284e20b78bd4a18c8c2282d549d10bc8408a2a7ff57653c0cf0b9be0afce5 \
    --hash=sha256:a80cb027f6b349846a3bf6d73b5e95e782175e52f22108cfa17876aaeff93702 \
    --hash=sha256:b30236e45cf30d2b8e7b3e85881719e98507abed1011bf463a8fa23e9c3e98a8 \
    --hash=sha256:b3bc83488de33889877a0f2543ade9f70c67d66d9ebb4ac959502e12de895788 \
    --hash=sha256:b865addae83924361678b652338317d1bd7e79b1f4596f96b96c77a5a34b34da \
    --hash=sha256:b8bb0864c5a28024fac8a632c443c87c5aa6f215c0b126c449ae1a150412f31d \
    --hash=sha256:ba1cc08a7ccde2d2ec775841541641e4548226580ab850948cbfda66a1befcdc \
    --hash=sha256:bdb2c67c6c1390b63c6ff89f210c8fd09d9a1217a465701eac7316313c915e4c \
    --hash=sha256:c1ff362665ae507275af2853520967820d9124984e0f7466736aea23d8611fba \
    --hash=sha256:c2514fceb77bc5e7a2f7adfaa1feb2fb311607c9cb518dbc378688ec73d8292f \
    --hash=sha256:c3355370a2c156cffb25e876646f149d5d68f5e0a3ce86a5084dd0b64a994917 \
    --hash=sha256:c458b6d084f9b935061bc36216e8a69a7e293a2f1e68bf956dcd9e6cbcd143f5 \
    --hash=sha256:d0eae10f8159e8fdad514efdc92d74fd8d682c933a6dd088030f3834bc8e6b26 \
    --hash=sha256:d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f \
    --hash=sha256:ebc55a14a21cb14062aa4162f906cd962b28e2e9ea38f9b4391244cd8de4ae0b \
    --hash=sha256:eda16858a3cab07b80edaf74336ece1f986ba330fdb8ee0d6c0d68fe82bc96be \
    --hash=sha256:ee2922902c45ae8ccada2c5b501ab86c36525b883eff4255313a253a3160861c \
    --hash=sha256:efd7b85f94a6f21e4932043973a7ba2613b059c4a000551892ac9f1d11f5baf3 \
    --hash=sha256:f7057c9a337546edc7973c0d3ba84ddcdf0daa14533c2065749c9075001090e6 \
    --hash=sha256:fa160448684b4e94d80416c0fa4aac48967a969efe22931448d853ada8baf926 \
    --hash=sha256:fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0
referencing==0.37.0 \
    --hash=sha256:381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231 \
    --hash=sha256:44aefc3142c5b842538163acb373e24cce6632bd54bdb01b21ad5863489f50d8
rpds-py==2026.6.3 \
    --hash=sha256:0be972be84cfcaf46c8c6edf690ca0f154ac17babf1f6a955a51579b34ad2dc5 \
    --hash=sha256:127565fead0a10943b282957bd5447804ff3160ad79f2ad2635e6d249e380680 \
    --hash=sha256:127e08c0642d880cf32ca47ec2a4a77b901f7e2dd1ad9762adb13955d72ffcc9 \
    --hash=sha256:166cf54d9f44fc6ceb53c7860258dde44a81406646de79f8ed3234fca3b6e538 \
    --hash=sha256:168c733a7112e071bb7a66460e667edfcff06c017a3c523f7a8a8e08d0140804 \
    --hash=sha256:1967debc37f64f2c4dc90a7f563aec558b471966e12adcac4e1c4240496b6ebf \
    --hash=sha256:1cebd1337c242e4ec2293e541f712b2da849b29f48f0c293684b71c0632625d4 \
    --hash=sha256:1cf01971c4f2c5553b772a542e4aaf191789cd331bc2cd4ff0e6e65ba49e1e97 \
    --hash=sha256:1e5822dfc2f0d4ab7e745eaa6d85945069329beeccef965af3f3bb26058fcab6 \
    --hash=sha256:22bffe6042b9bcb0822bcd1955ec00e245daf17b4344e4ed8e9551b976b63e96 \
    --hash=sha256:23a439f31ccbeff1574e24889128821d1f7917470e830cf6544dced1c662262a \
    --hash=sha256:24e9c5386e16669b674a69c156c8eeefcb578f3b3397b713b08e6d60f3c7b187 \
    --hash=sha256:270b293dae9058fc9fcedab50f13cebf46fb8ed1d1d54e0521a9da5d6b211975 \
    --hash=sha256:29dfa0533a5d4c94d4dfa1b694fcb56c9c63aad8330ffdd816fd225d0a7a162f \
    --hash=sha256:2a9c6f195058cb45335e8cc3802745c603d716eb96bc9625950c1aac71c0c703 \
    --hash=sha256:2bfd04c19ddbd6640de0b51894d764bd2758854d5b75bd102d2ef10cb9c293a9 \
    --hash=sha256:2c54a076ca4d370980ab57bc0e31df57bbe8d41340436a90ef8b1219a3cbb127 \
    --hash=sha256:2c958bf94822e9290a40aaf2a822d4bc5c88099093e3948ad6c571eca9272e5f \
    --hash=sha256:2c99f7e8ccb3dd6e3e4bfeac657a7b208c9bac8075f4b078c02d7404c34107fa \
    --hash=sha256:2f7c26fbc5acd2522b95d4177fe4710ffd8e9b20529e703ffbf8db4d93903f05 \
    --hash=sha256:30c6dc199b24a5e3e81d50da0f00858c5bbdb2617a750395687f4339c5818171 \
    --hash=sha256:38a2fea2787428f811719ceb9114cb78964a3138838320c29ac39526c79c16ba \
    --hash=sha256:3a83ae6c67b7676b9878378547ca8e93ed77a580037bcbcd1d32f739e1e6089c \
    --hash=sha256:3cfe765c1da0072636ca06628261e0ea05688e160d5c8a03e0217c3854037223 \
    --hash=sha256:421aba32367055614287a4292b6a17f1939c9452299f7a0209c117e990b646d4 \
    --hash=sha256:425560c6fa0415f27261727bb20bd097568485e5eb0c121f1949417d1c516885 \
    --hash=sha256:4470ce197d4090875cf6affbf1f853338387428df97c4fb7b7106317b8214698 \
    --hash=sha256:4cf2d36a2357e4d07bb5a4f98801265327b48256867816cfd2ceb001e9754a8f \
    --hash=sha256:4f4bca01b63096f606e095734dd56e74e175f94cfbf24ff3d63281cec61f7bb7 \
    --hash=sha256:501f9f04a588d6a09179368c57071301445191767c64e4b52a6aa9871f1ef5ed \
    --hash=sha256:536bceea4fa4acf7e1c61da2b5786304367c816c8895be71b8f537c480b0ea1f \
    --hash=sha256:538949e262e46caa31ac01bdb3c1e8f642622922cacbabbae6a8445d9dc33eaf \
    --hash=sha256:539d75de9e0d536c84ff18dfeb805398e58227001ce09231a26a08b9aed1ee0e \
    --hash=sha256:54f45a148e28767bf343d33a684693c70e451c6f4c0e9904709a723fafbdfc1f \
    --hash=sha256:55927d532399c2c646100ff7feb48eaa940ad70f42cd68e1328f3ded9f81ca24 \
    --hash=sha256:58eadac9cd119677b60e1cf8ac4052f35949d71b8a9e5556efccbe82533cf22a \
    --hash=sha256:5e8d07bddee435a2ff6f1920e18feff28d0bc4533e42f4bf6927fbd073312c41 \
    --hash=sha256:62698275682bf121181861295c9181e789030a2d516071f5b8f3c23c170cd0fc \
    --hash=sha256:639c8929aa0afe81be836b04de888460d6bed38b9c54cfc18da8f6bfabf5af5d \
    --hash=sha256:67e3a721ffc5d8d2210d3671872298c4a84e4b8035cfe42ffd7cde35d772b146 \
    --hash=sha256:6de4744d05bd1aa1be4ed7ea1189e3979196808008113bbbf899a460966b925e \
    --hash=sha256:6e84adbcf4bf841aed8116a8264b9f50b4cb3e7bd89b516122e616ac56ca269e \
    --hash=sha256:7491ee23305ac3eb59e492b6945881f5cd77a6f731061a3f25b77fd40f9e99a4 \
    --hash=sha256:79486287de1730dbaff3dbd124d0ca4d2ef7f9d29bf2544f1f93c09b5bcbbd12 \
    --hash=sha256:7b689145a1485c335569bd056464f3243a29af7ed3871c7be31ad624ba239bc7 \
    --hash=sha256:7f88d653e7b3b779d71ae7454e20dcc9b6bae903f33c269db9f2be41bda3f261 \
    --hash=sha256:8020133a74bd81b4572dd8e4be028a6b1ebcd70e6726edc3918008c08bee6ee6 \
    --hash=sha256:808345f53cb952433ca2816f1604ff3515608a81784954f38d4452acfe8e61d5 \
    --hash=sha256:83e35b57523816c8613fd0776b40cd8bb9f596b37ddd2692eb4a6bb5ab2f8c93 \
    --hash=sha256:842e7b070435622248c7a2c44ae53fa1440e073cc3023bc919fed570884097a7 \
    --hash=sha256:847927daf4cffbd4e90e42bc890069897101edd015f956cb8721b3473372edda \
    --hash=sha256:882076c00c0a608b131187055ddc5ae29f2e7eaf870d6168980420d58528a5c8 \
    --hash=sha256:8b95977e7211527ab0ba576e286d023389fbeeb32a6b7b771665d333c60e5342 \
    --hash=sha256:8bb68f03f395eb793220b45c097bd4d8c32944393da0fad8b999efac0868fc8c \
    --hash=sha256:8c2642a7603ec0b16ed77da4555db3b4b472341904873788327c0b0d7b95f1bb \
    --hash=sha256:8c3d1e9c15b9d51ca0391e13da1a25a0a4df3c58a37c9dc368e0736cf7f69df0 \
    --hash=sha256:8c6e5a2f750cc71c3e3b11d71661f21d6f9bc6cebc6564b1466417a1ec03ec77 \
    --hash=sha256:8d2294a31386bfa251d8c8a39472beee17db67d4f1a6eabea665d35c9a4461c3 \
    --hash=sha256:8e4320744c1ffdd95a603def63344bfab2d33edeab301c5007e7de9f9f5b3885 \
    --hash=sha256:8e65860d238379ed982fd9ba690579b5e95af2f4840f99c772816dbe573cb826 \
    --hash=sha256:8f2e5c5ee828d42cb11760761c0af6507927bec42d0ad5458f97c9203b054617 \
    --hash=sha256:900a67df3fd1660b035a4761c4ce73c382ea6b35f90f9863c36c6fd8bf8b09bb \
    --hash=sha256:913ca42ccad3f8cc6e292b587ae8ae49c8c823e5dce51a736252fc7c7cdfa577 \
    --hash=sha256:9250a9a0a6fd4648b3f868da8d91a4c52b5811a62df58e753d50ae4454a36f80 \
    --hash=sha256:931908d9fc855d8f74783377822be318edb6dcb19e47169dc038f9a1bf60b06e \
    --hash=sha256:9826217f048f620d9a712672818bf231442c1b35d96b227a07eabd11b4bb6945 \
    --hash=sha256:9891e594296ab9dada6551c8e7b387b2721f27a67eecd528412e8906247a7b90 \
    --hash=sha256:9c1255b302953c86a486b81d330d5ee1d5bd937691ce271b6be0ef0e299eaab7 \
    --hash=sha256:a0811d33247c3d6128a3001d763f2aa056bb3425204335400ac54f89eec3a0d0 \
    --hash=sha256:a136d453475ac0fcbda502ef1e6504bd28d6d904700915d278deeab0d00fe140 \
    --hash=sha256:a214c993455f99a89aaeadc9b21241900037adc9d97203e374d75513c5911822 \
    --hash=sha256:a3086b538543802f84c843911242db20447de00d8752dd0efc936dbcf02218ba \
    --hash=sha256:a3450b693fde92133e9f51060568a4c31fcca76d5e53bbd611e689ca446517e9 \
    --hash=sha256:a550fb4950a06dde3beb4721f5ad4b25bf4513784665b0a8522c792e2bd822a4 \
    --hash=sha256:a9f4645593036b81bbdb36b9c8e0ea0d1c3fee968c4d59db0344c14087ef143a \
    --hash=sha256:aca6c1ef08a82bfe327cc156da694660f599923e2e6665b6d81c9c2d0ac9ffc8 \
    --hash=sha256:acac386b453c2516111b50985d60ce46e7fadb5ea71ae7b25f4c946935bf27cf \
    --hash=sha256:acc992ab27b15f852c76755eb2ab7dce86585ddadba6fa5946e58556088845b4 \
    --hash=sha256:ae3d4fe8c0b9213624fdce7279d70e3b148b682ca20719ebd193a23ebfa47324 \
    --hash=sha256:ae50181a047c871561212bb97f7932a2d45fb53e947bd9b57ebad85b529cbc53 \
    --hash=sha256:ae6dd8f10bd17aad820876d24caec9efdafd80a318d16c0a48edb5e136902c6b \
    --hash=sha256:af05d726809bff6b141be124d4c7ce998f9c9c7f30edb1f46c07aa103d540b41 \
    --hash=sha256:afd70d95892096cdb26f15a00c45907b17817577aa8d1c76b2dcc2788391f9e9 \
    --hash=sha256:b5c2dc92304aa48a4a60443b548bb12f12e119d4b72f314015e67b9e1be97fca \
    --hash=sha256:bc0011654b91cc4fb2ae701bec0a0ba1e552c0714247fa7af6c59e0ccfa3a4e1 \
    --hash=sha256:bcfbcf66006befb9fd2aeaa9e01feaf881b4dc330a02ba07d2322b1c11be7b5d \
    --hash=sha256:bdbd97738551fca3917c1bd7188bec1920bb520104f28e7e1007f9ceb17b7690 \
    --hash=sha256:c60924535c75f1566b6eb75b5c31a48a43fef04fa2d0d201acbad8a9969c6107 \
    --hash=sha256:c7b9a2f8f4d8e90af72571d3d495deebdd7e3c75451f5b41719aee166e940fc2 \
    --hash=sha256:ca6546b66be9dc4738b1b043d5ebd5488c66c578c5ff0fd0e8065313fe3afb76 \
    --hash=sha256:ccffae9a092a00deb7efd545fe5e2c33c33b88e7c054337e9a74c179347d0b7d \
    --hash=sha256:cdc7e35386f3847df728fbcb5e887e2d79c19e2fa1eba9e51b6621d23e3243af \
    --hash=sha256:d15fde0e6fb0d88a60d221204873743e5d9f0b7d29165e62cd86d0413ad74ba6 \
    --hash=sha256:d34c20167764fbcf927194d532dd7e0c56772f0a5f943fa5ef9e9afbba8fb9db \
    --hash=sha256:d483fe17f01ad64b7bf7cc38fcefff1ca9fb83f8c2b2542b68f97ffe0611b369 \
    --hash=sha256:d7469697dce35be237db177d42e2a2ee26e6dcc5fc052078a6fefabd288c6edd \
    --hash=sha256:db08f45aecde626498fb3df07bcf6d2ec040af42e859a4f5040d79c200342911 \
    --hash=sha256:dc319e5a1de4b6913aac94bf6a2f9e847371e0a140a43dd4991db1a09bc2d504 \
    --hash=sha256:de3eceba0b683bcbb1ab93da016d0270df1f9ae7be716b40214c5dafac6ea45a \
    --hash=sha256:dfcc8b909769d19db55c7cc9541eb64b9b774b1057ffffb4f1048070475bb9f9 \
    --hash=sha256:e059c5dde6452b44424bd1834557556c226b57781dee1227af23518459722b13 \
    --hash=sha256:e4316bf32babbed84e691e352faf967ce2f0f024174a8643c37c94a1080374fc \
    --hash=sha256:e52655eaf81e32593abedaa4bfe33170c8cfedf3365ed9be6e11e07f148f0278 \
    --hash=sha256:e55d236be29255554da47abe5c577637db7c24a02b8b46f0ca9524c855801868 \
    --hash=sha256:ea7bb13b7c9a29791f87a0387ba7d3ad3a6d783d827e4d3f27b40a0ff44495e2 \
    --hash=sha256:ea964164cc9afa72d4d9b23cc28dafae93693c0a53e0b42acbff15b22c3f9ddd \
    --hash=sha256:ec829541c45bca16e61c7ae50c20501f213605beb75d1aba91a6ee37fbbb56a4 \
    --hash=sha256:ecabd69db66de867690f9797f2f8fa27ba501bbc24540cbdbdc649cd15888ba6 \
    --hash=sha256:ed0c1e5d10cdc7135537988c74a0188da68e2f3c30813ba3744ab1e42e0480f9 \
    --hash=sha256:f0840b5b17057f7fd918b76183a4b5a0635f43e14eb2ce60dce1d4ee4707ea00 \
    --hash=sha256:f4d78253f6996be4901669ad25319f842f740eccf4d58e3c7f3dd39e6dde1d8f \
    --hash=sha256:f56f1695bc5c0871cbc33dc0130fcf503aab0c57dcc5a6700a4f49eba4f2652e \
    --hash=sha256:f826877d462181e5eb1c26a0026b8d0cab05d99844ecb6d8bf3627a2ca0c0442 \
    --hash=sha256:f8f23ead891a3b762f35ab3b04623da7056545b48aa60d59957e6789914545da \
    --hash=sha256:f90938e92afda60266da758ee7d363447f7f0138c9559f9e1811629580582d90 \
    --hash=sha256:faa679d19a6696fd54259ad321251ad77a13e70e03dd834daa762a44fb6196ef
secretstorage==3.5.0 ; sys_platform == 'linux' \
    --hash=sha256:0ce65888c0725fcb2c5bc0fdb8e5438eece02c523557ea40ce0703c266248137 \
    --hash=sha256:f04b8e4689cbce351744d5537bf6b1329c6fc68f91fa666f60a380edddcd11be
sse-starlette==3.5.0 \
    --hash=sha256:3e6e1070df3f0f5d9cea81496de92dbb72f6721871d99748ece67441dd8b7997 \
    --hash=sha256:75de713aa8a9441513cc283220826da079d982770965b951e9437720e8bafdb2
starlette==1.7.0 \
    --hash=sha256:67f8e99895493dd2911a03f11314af6ceebeae4e704bb9f43dfc6a9db151c93e \
    --hash=sha256:c79f74ea63cff761804fbbfb182f1e0b440c2d07b164d24700c5a1bab5d6ff5d
tomlkit==0.15.1 \
    --hash=sha256:177a05aece5a8ca5266fd3c448abb47b8d352f09d477d3ca8332db4d89b24304 \
    --hash=sha256:e25bbf38843005246210a12982776f27f99cb9be67160e14434d0c0d21ee1e97
trove-classifiers==2026.9.21.13 \
    --hash=sha256:0a9ebc8d4e2f3e8a22848c5258033035bec17a3012ac3fea16dbaa764489eb71 \
    --hash=sha256:8b1ff4f9c191b1040b71c37f1e445ab99732911e3cd91de52838453a854d7a17
truststore==0.10.4 \
    --hash=sha256:9d91bd436463ad5e4ee4aba766628dd6cd7010cf3e2461756b3303710eebc301 \
    --hash=sha256:adaeaecf1cbb5f4de3b1959b42d41f6fab57b2b1666adb59e89cb0b53361d981
typing-extensions==4.16.0 \
    --hash=sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8 \
    --hash=sha256:dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5
typing-inspection==0.4.4 \
    --hash=sha256:547274fa6b0a561ccf549cc9524b999a578e737d015d8709d021f9d0d13bea47 \
    --hash=sha256:65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147
uvicorn==0.54.0 \
    --hash=sha256:505bdb0f318731d45f1f712071fc781a8981f6847a31c902c9f5e652d4f67faf \
    --hash=sha256:a2e33cbfaa0306f8e6b0c13e0cb89d7d7a2da3e62b90c66e18c33d9807b28620
uvloop==0.23.0 ; platform_python_implementation != 'PyPy' and sys_platform != 'cygwin' and sys_platform != 'win32' \
    --hash=sha256:0305871ac712f54b62af73f943dbf21ae3ce80a44bc0f0151424484affa85645 \
    --hash=sha256:090865d8ce7a03986755a3ce711b7dd0d4b44eb14ab74368b717f3fad1180208 \
    --hash=sha256:098a85e1393ef5202767b7e5fb41a32cd8bd81e6ee4af364c179801c4aa3f6d4 \
    --hash=sha256:0efdd55bddbd36bb2fcb842d64c0d5f6407c6958c68088cc25df8c09edc5b5fd \
    --hash=sha256:12634f15e6625f78b3f2922f91404c4d7173487eba11746764153f556e9852dc \
    --hash=sha256:1748321e3c59a14a75404b1ae8d5a8d81c4e201803ea0e14c1b6fd84421024b5 \
    --hash=sha256:19c64108b507cd0bc140e400e3396bacebd9d504956aa7726272bf6de7d9aabb \
    --hash=sha256:1e84575f11873c109cf3962ad0bdf679094466184125f4cadcc41a73febff41f \
    --hash=sha256:24c58ae4a83e93a04c504bcc678125e36a0bfc44af928ad69444880c60f187a5 \
    --hash=sha256:28d160f51ab4da3b187063652e643dea6831072add4adc1e6d62afbe73b6be27 \
    --hash=sha256:2dcff2d69be43e6559e5dad2c5a7a2dbfb60e05a77311b6c4b7a4a8123d86c65 \
    --hash=sha256:31e0cf90bc8fd88784f6802cdba968a51fb1aec1cc3feec74d862b2d371d1330 \
    --hash=sha256:378188efbb1524f2219d05246a3e1e5907217848d2882144dff59585f1b81d55 \
    --hash=sha256:42feced24b9b44b856c633eafb5cc5dec354972da55ce77598db6844c054bc7c \
    --hash=sha256:4448e9124537620f9c25d004c227bb5104440b58955c19bbd312d910af919a63 \
    --hash=sha256:4a08875543bbd4519faf30497506c9cda8a48470467ffdf967c7313c7a5981a8 \
    --hash=sha256:4b8e207c67d207a8608fec57e116511030af3495dc0109b8c333cf9cb412b16f \
    --hash=sha256:4bb7f5d0b62b5afaaaea2b7b60d508921c24b0fe39c22c1438bec1811ffe10ec \
    --hash=sha256:4f1798f56c6f4ba5ac11fa2869e5717926e4470d97a1dd42b4f59219d43b5027 \
    --hash=sha256:514698d3683189031dcbfdc31e87115992e5ce9e1b19fe5359941323f2df800c \
    --hash=sha256:53c2c5d7e2024e46776c2d90e6c637d01102126b61aaf5faa5edaf05f8b5722a \
    --hash=sha256:55d6f4135d914305929fe9e9c44d8b5383a9b3fa1bee3bfcf60ee97e01af07ea \
    --hash=sha256:5a2bbad3a63007f7e9524d4903ba04fee252557c2acd86f9a3d4f91786695254 \
    --hash=sha256:5a3e0f56ec19bfd9ad1605572878dd6ff7f01b325f4fc154812ae70d615c3aff \
    --hash=sha256:5bb9be71d9ee39b4359b832f9569518ec9bc08704194034e79e4958e6bc4d46d \
    --hash=sha256:60ec798c40a1810d282ee046f61ecac1c5675cb898763d9f08d97d53a5e00a81 \
    --hash=sha256:6b3cbc4f96ddfa1fb88a78a69dd851369825b7816d9702eee8c4461505ba172e \
    --hash=sha256:6c7ef4701a96553514b2688e342ef1bf2beae6cfd172d89a76c768292aabf405 \
    --hash=sha256:7337b06a9f9ed9ea3049f04b76f65819db9b19bb832ee598e97b388eadf25e5f \
    --hash=sha256:76345f51367fb1f23e08605c6efb18374f669be5b223658fbab6b17627950507 \
    --hash=sha256:7e35c9bc977760981693e1a7a51493b58ee5a501f9ebb1e547565ee40b6c6208 \
    --hash=sha256:80cac5cb90ed7b9b72a217a1d6982b15b829cdbd0ee6bc19b93e3a9e47fb0ac9 \
    --hash=sha256:8af88fe5c7dd68fe1fec6dea8155caa1a47155d219a750ff34049541cf536a5e \
    --hash=sha256:8fcd721113260ffb5e38bf14a8725b17d431f34209f7d1c7005b667946e630b3 \
    --hash=sha256:93087a845cdfb35753e539354ac9551bdd2ff528c202a98df0ae46e852bcf021 \
    --hash=sha256:93935ab27b6eaef4c3e5489aebc84284f0644592f7ab516df60ee1b27eaf5eb3 \
    --hash=sha256:9bf08e4b6362dd1c08623bbfa2d061e8bac0f1da8fc2007062cfe1dc360a49fa \
    --hash=sha256:a6ac96da66c35bf789bdcde78a88dc7d56b7907d8379648c54adc1c61594575d \
    --hash=sha256:ab17b3a8aa754be0de0e397f7b95f13b14e56f077a4c6ae295e3d4afd199b325 \
    --hash=sha256:b0d106d9314546d69b3df1b5352639aa628530ec3ecef8a98a21942d2a2a64f5 \
    --hash=sha256:b90397a50ad6332ed3e459c648ac20d182cce24a557354363ad85fc9ea4a17cd \
    --hash=sha256:bbbdb8fcd5e7062e546eec1ac78c28bb21ae7df54c18f8e4b06e15a18d661a49 \
    --hash=sha256:bd6f2f81c7b9da99d301c0b16b82044e76fe887086e42e1590ecf520b94dbdac \
    --hash=sha256:be53e1d5f83de43dc175c87612ecc128d444b38e5c56cb3f807f5a73d6887476 \
    --hash=sha256:c3f23f403a273900d57de6ee5ca0614c650f7f58563065dad1a4744498960e53 \
    --hash=sha256:cbe8d03d4efcccdb7fcedecbaa1e1fa02913eaf3a74cb933634a6bc6d2ea9e2a \
    --hash=sha256:ce17bc317d089f361b33521654c13e30eacfd3d2034fd34e613ca9c51c969686 \
    --hash=sha256:d918d6f304a309222a784bbd140b85ec5594d97e4dc0e79f590549d28970663a \
    --hash=sha256:dc61e4f9e37b507069dc7e659ae28bca7adcb04c993c3508214315d12c63f848 \
    --hash=sha256:e095f9e105af76593b4c183bb0bcbdae64bd913a59ec595732dc108b48730ab5 \
    --hash=sha256:e2cba180d6451822763eda8364f342435a873bcfb3849cbd82fdeca248ca65eb \
    --hash=sha256:e49eba8f1e28e7c03648b7a476e1ba05309e087ccdea859fc6dd659564aa8d7e \
    --hash=sha256:f1341c6abcee1c31277cfe28d34e46196f2143ec3d755e6efe7452126e1f626d \
    --hash=sha256:f3fbfe82829d8e381426a289b87e59e585278728361db9ce975b88b51f64f410 \
    --hash=sha256:f50b580fad005a092ed87c5a3a4683459b21d1620497d6a5bccad203bee4c071 \
    --hash=sha256:f5576e8ae1723ece60d8f93c6710abf784714e99388bcf023ba9ca800bc587f6 \
    --hash=sha256:f673d835bdb1a60229cc3609a113fd2c9ce3f4a3c75ad4eaed111180c00199d2 \
    --hash=sha256:f7548ede3ee908cfabc0d068106e303a9a2d811af959cdf6ab85676344cedcda \
    --hash=sha256:fa8ed556fcc87a4091cf61587ef172fa104323dc89ecc085a618ba7ff8629a8f \
    --hash=sha256:fefea5cf8cdda9053b962ca8a90216fb0b1d40907dcb6819382b42e483e6e9f6 \
    --hash=sha256:ff7144d8167e513fe39fbb46bffb4f6f192dfb1f4b0b4e9102e1fd4f212e4747
watchfiles==1.3.0 \
    --hash=sha256:000b9688fc8133037a8b075c8ebf98f32844ff8964dda61e85c1db547dafc441 \
    --hash=sha256:025b108f2d5cc2799cb941f79380df3e8b22bfb589c218e801767fe78d598c95 \
    --hash=sha256:04c5500faa725d69a99b0f63750e80795e455bb951849e9c98a811b4324997c4 \
    --hash=sha256:1acabde19b67e673274e89a04d613b7fb1f122e2c4b8ec9a581e59c149264b61 \
    --hash=sha256:26b81bc515a0f03f66a69a6fea86eea54c8eca4173c46dd7222569f79dd2f977 \
    --hash=sha256:380f513d26cc2e598266b88d66456e07d67ef4be8f0f435a1154d9c44b43d509 \
    --hash=sha256:45726c6b5a8d67c8087eb2933c4398948546d04206ef40f629dc4881d65d23d1 \
    --hash=sha256:4af9c464d410e8c44b58ddf1cbec7c3a02c1cb2c6c80df9c74659ba2fbda0ab5 \
    --hash=sha256:509d9f74d2bec5c1f4cd868ddcfe0c9601f7ea53066dfcb19d8ede742c4de661 \
    --hash=sha256:591de392458bca26f6130fea4e667c06b657e873ad334ea06fad5a79f5086cef \
    --hash=sha256:5ec46a1ff4c1d81405a5fc645abdbff5e4e9388f7c9a6cdb392316a7c29b884f \
    --hash=sha256:6398d250994baff581147ccba846223076fe6492ca93c0d1b3588fcf5355eb5c \
    --hash=sha256:7398930a2b76b9dc67a4e6b8bfc7baf30946892a86f417a3920c07bdd6febc30 \
    --hash=sha256:7c1125e99f84934a92996ae343501285617373acd66f16b59fd5654b27ad8d80 \
    --hash=sha256:81c989d7267bfb7b676cd32c83bec97914e396870983cbf493e29415037bff5e \
    --hash=sha256:99aee4a07847c06820765fd7b1b49ceac4f3f711ccb7d104655a33231de1c207 \
    --hash=sha256:a5b631db08fd3032db57ec6a92d1777cd60f88803287e4e941a4858c53aab1e0 \
    --hash=sha256:a85e243c87109d9f48a2e0d10d6abdee8768cc114848b32281ec83d7f81d86ef \
    --hash=sha256:b5768b49e426fd5b550b012c866db347cdf15c398ef98dc557b6e6b72fa74cd1 \
    --hash=sha256:bbc1198edfdc90fda0600f825aa94150f428dfcbf8138746f55998e0e660d64c \
    --hash=sha256:be9ef3cd403d756a304a0a08a112163c63da7ec72c8c9d083c98818291ff8f29 \
    --hash=sha256:ca39661934749df580d89f3dde266f2af7c6968f4c21c72ce2dc387d299e6aa7 \
    --hash=sha256:d36c72fcdc08f143d87316a4c4c3b064e340da2c7383d39803950740ed418935 \
    --hash=sha256:d4593392e87669836670f87d62fc754059eaeb0e6157af44060a46558cebe5a3 \
    --hash=sha256:d754e049006e81a9be49dc78ba7802081cee426e968cbc63ee19e164fa2d0e39 \
    --hash=sha256:d978cc1dd7ba44f5590d7de74f7a9c8be7262d9e469c2c0efb8bbfc2574321dc \
    --hash=sha256:da213822ec9082b62cadf3008e07a8c690ec7a3c89f6dc5e55a8cf07b56a1b26 \
    --hash=sha256:dd538c71766c59c732e2c5cedc39323c99c11897b99f93eac773438e54af206a \
    --hash=sha256:e0204f90677b7fb8d3a824279a71a01166bea9f6e53923b8056592d87b33b0b6 \
    --hash=sha256:e5871d4a7f788a9f64fb06f5793389d29d171e5c32d37c3ebfd520b017cc7694 \
    --hash=sha256:eb94e40b9a0db19636b5e3fed0a9803452ecc7381df13b385272abb779ee83ca \
    --hash=sha256:ec3cd4bb181a7b6329134204c2277c7144ab5f62cce9c5335d6f901ee7ce8d6a \
    --hash=sha256:f0c9865240e065a2247f4b5248528ae3d01e0e8ae071462c250c884dc16e3ee3
websockets==17.2 \
    --hash=sha256:01420cb1cb47433e8e7075d32cb8017ad3ffed0654bd1e48c0251b865920dec3 \
    --hash=sha256:0198c4ec6a3406a2f7557c032967de426474c2c995c81076585e09d29a9f407b \
    --hash=sha256:0360c4dc13ac569cc245e0efa2f4d4b1e4733d24c47b8ab3f3747227b1356348 \
    --hash=sha256:063508ce9e0db745f30ab52fc652f4e59efc79c2b74934b3837d5cdb974da620 \
    --hash=sha256:06c7386128a9d85de4e1960114604f3031c084d2f4eee8db382637f1634cbab1 \
    --hash=sha256:06e46da092bca3a52e98f0458c66b247993ce501a07cd09c858be3296511ab7d \
    --hash=sha256:06fa3ce9c3154826c33d4395b225b2994aa64f1f3bcd8be8ed932019175d9268 \
    --hash=sha256:08d90cf344bdb971ba3a826b78d4da9bfd56cc6a97a604d9b88cbd40bfa6c735 \
    --hash=sha256:08d97098644728bd1895caa7ecf3090b8e563d70809870d2adb33a107bd061d0 \
    --hash=sha256:0a6220bdf8d5f11af71251a599092d89ac1d6bfac691c7f5951c5b07953947a0 \
    --hash=sha256:0c8600aec354cc259f1691b0b42816f04a9886a953f82cb227246df76057f97a \
    --hash=sha256:1110fbfd530c447380e6e6db88b7e43ffe33d54178f5b0ff0aaa5a280301e668 \
    --hash=sha256:15a7101b660a9f15fac34108c92cefc9848f6753a50acef8869e3cd94148fdb7 \
    --hash=sha256:18b0a46e5e9b315e2b54ce8c3bafdeef0e1388ca363114fa868e6aab2dc58512 \
    --hash=sha256:19e2511412ad3393191de652513bc7a0ca3c93af143b32d96d46e59fbbddf1d4 \
    --hash=sha256:1c27339934109dfaca83f18ab2c23db06714e9d5deca2c8e37e8f492ab90d20b \
    --hash=sha256:1d829946a2e7630f92f9d7b45b62f3abe9f393cc2dea6a35edb3988f865e75f2 \
    --hash=sha256:1fdb8d5a1660307dc6d36d0b7fc725213cbd7f80800904dc4896aa3208b89121 \
    --hash=sha256:214da56dba368f61b3d745c77630b2d03c61c02da7b42fe80ef6efba079d3077 \
    --hash=sha256:222fb626fa15701a850eccc778be17312142b2f6a0e16aea80770b7459adb784 \
    --hash=sha256:27c7a59b5352a8f741b422820adfe89dfe47c8f2d84fb32111e76111edaa0e83 \
    --hash=sha256:2901bdf24f20bc884124b3e88c61f7ece260c20c81e610f2196007395264a4aa \
    --hash=sha256:2ab742249f953d148a9ba696c8b9944361e8cb92e8bc61ba2dd53a178403afd3 \
    --hash=sha256:2ab9af5cb7265899e659f079eb71691375a1025b6d5fbd3caa495dd08f70833a \
    --hash=sha256:2d39c19b1ba6a6791050383fd69efdd3b63533e2254693d0263879cd5f5921ba \
    --hash=sha256:2de1ccf298f5c9e0f27113836d742edb95f015eee3148f004ac386f7ba9a05b1 \
    --hash=sha256:30201a7f69833b015556c72feb69ea501b645986fd0b90dab13f589e995ff428 \
    --hash=sha256:307fc22ea496be8542d67b82ae8c867a978dfd19ac35573d4f15943fd9277dfe \
    --hash=sha256:3117abfd32b183bdb6194df9317766d32c6517f3d1c0aa8c62d5c6ccfda0b4a8 \
    --hash=sha256:313f6703023d53baabab6d6c5c37cf637b2c4fee255acf2ed5e92ad69e28f1b7 \
    --hash=sha256:315551f4ccedbbf9fd4f7e8bf037a5948c976ade0e919ba5d8f581d465f6f725 \
    --hash=sha256:35e0f088ddfd9d9bc5019e27ff3767411779e92b59db5bb1507f2731a5b61158 \
    --hash=sha256:3621f3686397708b8eeabfd0a9d75267c1f29a7537d2fe31e65d099e71587fa4 \
    --hash=sha256:36c2fb94c990cc2545143b12690e2de6c16300f9dbe5b4f33fa300cf57dc8792 \
    --hash=sha256:376a693697ddb695ea282ead76060f4847f90e564b12b4389f2c7589e6fadb9e \
    --hash=sha256:3892d76754b5f36fb40619f3ef09c68e5c3091f1ab8840964518ae5a41f30952 \
    --hash=sha256:3bbc5543e39ee025d524077c5c15c2d67bc11c9f6676afe5b531839e24d701f6 \
    --hash=sha256:3eb44019a2b0b3b91bac95998f1e4e5589730421170e060fe654a2b7be727dc7 \
    --hash=sha256:3f0def1279644acaa9bc861d4234af3f82ea9cee7e460dffac5cb63e691501e9 \
    --hash=sha256:40960554e60eb60c3eec4ff9e42a80f84f8cd3ca9bc80a5481a61f1e64d807c9 \
    --hash=sha256:4173a4b8a025ae44313d9d9b4ecf31e886c7b7faf45386d51a8ca4ff2dcf3f2a \
    --hash=sha256:42cbca10f82a8b2fb1536e8a0830ca6ceeb6bb3d8d64b766e0795369135654a8 \
    --hash=sha256:4497e87c34a2d21cbec1227858fec3af8e514dd70c47625557a122fcebc081dc \
    --hash=sha256:4733fc2d99fe888261417b7e29995403a72d9ffa78629902882325ea141177f2 \
    --hash=sha256:48997ed4431d8006988788ef4b62e1fd3f053c7463b4fa793aa6c4f9e96a3bb7 \
    --hash=sha256:4a49ca342efc0800e6ae94ed5c9cbdcb319308f75e73c21181e4c24d6710e8dd \
    --hash=sha256:4c32eb565ad9ce8a6444248e5b7a19dbb86a81c811fe5fcc2fba7a735aed5163 \
    --hash=sha256:4e312e07557a5ad348f4e83d3419773527f6e790c7f97928b1911d767b6ea1c7 \
    --hash=sha256:50644d8715be7e0ec0682f9d7744b63008e199c5e1618a48fa153756a332235f \
    --hash=sha256:533b7c82bb1eafbeb921dfe131c9f88e55451ddc328d84bde1c9340ba72d2808 \
    --hash=sha256:5436ffea003adb50e283ca0684a3fcaa1396104f841736c3322ee6582bd09e98 \
    --hash=sha256:55c5b9eab079540bfb639b40b07b7b467e5c5a7ecf97a65cc8665781381c9856 \
    --hash=sha256:55f9a808a0e072473337c240c939849818276e288e2374b832255b5b791b0851 \
    --hash=sha256:569ed5db651e420b13279f9333443bb5b84a436cc66b599cbc535697ae4434a0 \
    --hash=sha256:5b43a1f7e4853ce08c3f6d3bf69799ee5b46548bfb71792a8158f7e45d66b547 \
    --hash=sha256:5d459bbb6c22f26dcebea56924a362aba50d453b9867912862c970434fcf0d94 \
    --hash=sha256:5dc29815520c329f5662f6eb3ebadecf0d4f8c82dfa416d4d6efbf8f39245559 \
    --hash=sha256:60deca33e584c09e91f70f8b55a0b1de7d671d6a63f051d154920f48bed717c7 \
    --hash=sha256:61040f6f7da5a279d2f77496c69d51132aba75f701c52bded400d4c639277b18 \
    --hash=sha256:6281c171557ce0e408e19d9a223f22d915117ac38a5a7f32ed83809e7492316c \
    --hash=sha256:63499fc49efe48bccc2fca40723bc7adb198866cbe159093dd979905316994b6 \
    --hash=sha256:63f543463601c1558b755f8dd7618b6ec3dd0934dda051d3b7030d8c76e54de2 \
    --hash=sha256:65a89a5bde227bfe908016f35b5bd347970cd1e5b0360f389502eba1c7fde6e0 \
    --hash=sha256:660aa158127035e741d4b1835dbe79ae18a1fbb21ecd236655f31d60110e68d5 \
    --hash=sha256:6627b913b8586b1c06db9516b31dd0dfbc621de3bb9312616d92a7e44f268a5b \
    --hash=sha256:691780fca2be3dec512cb603cb91060271968cb4af86b51d07c57445c5754a37 \
    --hash=sha256:6aa59f0ef92e796b2db6f5f26550c4713c0e4036899fadf02f55e2ed4db0b7ae \
    --hash=sha256:6c274fc1572edf7c197094a0eb1887d45fdc95254bc80597dc7599550486c06a \
    --hash=sha256:6e9a04e69456015e6ae5e0d486d995137fd435794442122b00ce5f9526ea3ba8 \
    --hash=sha256:74836317b7010b579522bb52426f1e225608b042c9e78cbe2493522bebb8a318 \
    --hash=sha256:761cde41439f0be761aa460e1451a31e2e14baf4a46db6fe4913e5a06a90df66 \
    --hash=sha256:76693a16dead737946b651375ee3109d7db7ad9569a1c55c60aaed3ef85cfcc6 \
    --hash=sha256:77a42cc507993ec5471b5283f7eef869239173b6000031543e3938a86d1af0fd \
    --hash=sha256:7f115d5d804a2163dd89245710049078b0e726a58c1f44a1f86c2c6e79055d76 \
    --hash=sha256:80cbc645af23ac5c12096545c161626960114a1bc10f864760558d3b3e82ba18 \
    --hash=sha256:83abd8beab056aa77a116364811f8fc262dffbcc7abea48de0c85ccbfc6f1428 \
    --hash=sha256:8462395df8f224d2daa3d80db3ae4450d9d4b7243c8483ac79a82862f1599dd6 \
    --hash=sha256:876da8ca5520d65b5d0f2ca6b4e7a00d35bb90ccda35cb2ce3cda4b6c711e84a \
    --hash=sha256:88c6a42c2632ff469e84155e44f6ed92cb15ccb047bf5fcb59225ae5a12fd33d \
    --hash=sha256:89c4898da776193577279173dcf9860487590611d7320d379435a145881b048d \
    --hash=sha256:8a2321bcb73758c44c8076509024d02c15ee484fe77ce04edea4bf4d257492cc \
    --hash=sha256:8a829db795e3f87053904493d184b185c8eb1f497c852f434168ec856aa6f997 \
    --hash=sha256:8be4a87b3baca380ec3c7b1643b2dd268ac9d42c5097c0e8dc9a49342faf4774 \
    --hash=sha256:8da58558bfb0ca6ccac2419773521f1111e40654038b1afabdfc69c02cb82614 \
    --hash=sha256:8e24b878cf54843a63985d90480f163ca7f692689fbcbe9cdbd8165521083a8b \
    --hash=sha256:902ce8cafca2dc14cef9558a6fc3b45dbf7f121d1404bf2ad18a1c894555e48c \
    --hash=sha256:908d81d88bb16141613a6275059b5114656d5c2f0b5400b421d54fe6f1943507 \
    --hash=sha256:916ebdfd82e7fc68041d36b2b5f60361b9abce1e087454da15f8bd004839e090 \
    --hash=sha256:946ac2164d646e733004946ae39536b5af473853183d81da5962e29d36e3ad35 \
    --hash=sha256:9496bff5541086478264678bac73c0a75b2fde94fdf6568893bca1f7c6d50d18 \
    --hash=sha256:96f6c8d0fe21930d1f982bfce2382789d2e8d005d2ab63d21280660f95ef8fe1 \
    --hash=sha256:983bcdc898662f6ba9d6a025c30d29946ff0986d9ad60d400af0da3671f7cbf3 \
    --hash=sha256:98f2d03df74977fd252831c997c388cd6c3f691a8a9d022b266d3cbd9849838f \
    --hash=sha256:9a2a60a7f0ea5f239efb6391d2b28630a640d82dad63e3bee47cf2c623c4495d \
    --hash=sha256:9c393a202df08e96ed619310f0cd78be700e532a57d9a6ceee5f80b4e35bef14 \
    --hash=sha256:9c88697fa943bd4ef67cc919a17d81de6581846f52bfa8c6f64a916098986556 \
    --hash=sha256:9df9d048def11365d170b375b6ffc8b23a7f188c3560acd4418ba088ca2e2705 \
    --hash=sha256:a046227daa7f191e843d26b911c1146233e9a33d249e0c954dcb3ac7c398710e \
    --hash=sha256:a69ce25be5f1330ee1c74eb6fabbbceaa96b384beedd2627cecded7546490c40 \
    --hash=sha256:a7c4bb26de6ef496d24822aee4f6a305d97cd33d21a2b85f290292d69ba1c25e \
    --hash=sha256:a81e19710d48da88653473b6b9c366d47e99fe4f58e37ce415be47966748f31f \
    --hash=sha256:aaead3d926e9ab4124ada727d20cd62d396649917822df4f771d1f07f1079b40 \
    --hash=sha256:ada04d0262ab06527054a2a497f384d102698ff39b3865dc566a7d24b6f4058c \
    --hash=sha256:af4c565b923bb5975401b8e4cedc2e17b2fdbf33b905737ee12384e6a6fd9507 \
    --hash=sha256:b24b83fbb34b2d8de06cf0f0d4bd7737344ef854482a614826d4356c0c3f0c12 \
    --hash=sha256:b25659ab2d655d742701487d5591e3f98e8f8b329fc999e05e3d59691ab344a1 \
    --hash=sha256:b5f79366a8d8dbb981d53ba800bb54a95454595ab8a4548c2b95501b32a08326 \
    --hash=sha256:b789356bc4e2e6c20ba52817f92c3fed74e24657654237ecd536c54843b80c6c \
    --hash=sha256:c08da1f15040bd1e1a6074bd4518a6ef20e67b1594ecfb0aa75e5b45f87e6d6d \
    --hash=sha256:c1c09d5d4646eb96bda2cfb97493bcea21a0956a981de116e6b1f4a9de07f3fd \
    --hash=sha256:c2ec7e51157a3fa0e9cfdb1a8969bab38d1c22ad1ace7c6cea006383b43a1ad4 \
    --hash=sha256:c49c9edd47d0e44d360299e2d8865e2950d2fcf1b4098782c9d7dcd070919e5a \
    --hash=sha256:c63ff5a21f26bd0e6a8464b53fadbe174825c8718ac14180df45665eaacdb6af \
    --hash=sha256:c6590e1eb624ff6b15b872421bc9a10bc6d2057635d69c6cd244ac3f928f85c6 \
    --hash=sha256:c76b4bcbf0f713194591673fc86a42820e14da6bbd1bb445d3d002cc4d1e4521 \
    --hash=sha256:c796a1bb3e4015249639849f30e8e680df8a431b45d417ba8acf843d2451d95f \
    --hash=sha256:c81d6cdbacccda7e0eef3b076a457fd14c3835cdbc5993d2881580c2fb1f5f26 \
    --hash=sha256:c8eea55fdfa9ba65c6981eea38bd20c800bce2f092a2803d82de764ecf0f071a \
    --hash=sha256:cb5e2bf969ac99a6ae3c71208a5eb05cfde973192540ffa6e1068b57fb78c4f8 \
    --hash=sha256:cca2fcb72c007103740fa4fc3df19fdb1a318c641c69f3b0cc47ed63a889336e \
    --hash=sha256:cf8811d285acc91216368df7fb55cc8c9bf6fcd90eea42429c7186c7385a12b9 \
    --hash=sha256:d1a4f9462da6496b6cb79bbb09c60d17f7e63e8a1df136797b3afabec9560e4d \
    --hash=sha256:d4df62fd8448a85c752bbea1803cb3a2785e6fc8352009ab64ad7447af079b3c \
    --hash=sha256:d6605630c2808b33f362d6d08582e79821f77ed2bd3f49f9d467ea70defea06d \
    --hash=sha256:d87091c4347daadbcc0833b65812ff38d7350c67339625d4e4a512cf38e3e8ef \
    --hash=sha256:d8cfe9522ad69b6abb26b413ed1deca43cb915cefc588433d557cb3ae1c783e2 \
    --hash=sha256:dac93bf7a9beb215be3282b8441173cd50806c41c007b8be9bb24e03c60ad563 \
    --hash=sha256:dd9252828073fd0d69e7667af4275a1b17c18d0833b1ab7f59db272f194a6b9a \
    --hash=sha256:e136197f1262620ef2e507afc3ea759c1ae7d221886da20eec5f4c9f2618c2aa \
    --hash=sha256:e1e3bc8090a7eae79fdf634b63bdbfa3c93999991023c37c6fd3b469fc8ff5dc \
    --hash=sha256:e48ac2b302986c6f55cf61e8e36b4dd97d0132c5078a713a697a940934ba422e \
    --hash=sha256:e53d950e16d4bb672a5ff41fe3131e65a4e5d688d694e1c7074c8c9990bb3ceb \
    --hash=sha256:e5855e574804398859c5fbaf4fc7882b96278b7f6572a3d889627e6eb6cfca59 \
    --hash=sha256:eb0023e6cdb4b8ece0b33875188dd16104ad8c335361d396a98394f99e30ff7a \
    --hash=sha256:eb7b737ce8d18c8a08beb68f751572b7bf6a18093ecd1406ca1256b50592552e \
    --hash=sha256:ecb748910e9ba4624ebe2057791df51dcbffb48c37108ab94a3c593472023c9e \
    --hash=sha256:ecd63d0c7ed0d3d719c91b5a3861f0f0b3cec9bf223033ddf69d17aaac74bb6d \
    --hash=sha256:f19ca1a21871f024e38faf4107b433047df27558dff1b72a1dac31481e2c1fe5 \
    --hash=sha256:f2731f9067976c8c4127212c0d2f2ada42d497d935e470419e029802365b12bb \
    --hash=sha256:f2bbf3f28d0b63157577c8b774b9136f076afa6797e1a52a2ecd477f23cad3a8 \
    --hash=sha256:f33c7908a6885dcae9f462a4a8347b637053b4ff2b96beb4c23fba1cf7818e5f \
    --hash=sha256:f60e39adfecf998488166aca8ff24ab1ac406c9ecbecbcf9b3bcfc43cb1ec9a1 \
    --hash=sha256:f7eac84d4969da82166d5e90d9c38d2f416fe24f9708a7013569b193745b9a31 \
    --hash=sha256:f8969ad228115ad8869b5fed801f899e52ab8ad376fdb165ba4760a277c8258a \
    --hash=sha256:f90bad2839c185a1edf8ee22a257cfc8a39e0e337a0490ab185dfa76ef04d1bd \
    --hash=sha256:faa763b677e96f1beccc6b4d7e8c079dfeed2f249f57a19debc321b519ee64ec \
    --hash=sha256:fb78fb4158c12f77a934a003006784108a27a6553cfc0c6f10483c9c02e94f48 \
    --hash=sha256:fcce735ffd72ac4056db05325d9f0232382b74826f0196eb6a15ca903abdaa0f
'@
[System.IO.File]::WriteAllText((Join-Path $Prefix "release-requirements.lock"), ($ReleaseRequirements.Replace("`r`n", "`n") + "`n"), [System.Text.UTF8Encoding]::new($false))
# END GENERATED DEPENDENCIES
Invoke-Native $UvExe @("pip", "install", "-q", "--python", $PyBin, "--require-hashes", "--only-binary", ":all:", "-r", (Join-Path $Prefix "release-requirements.lock")) "locked dependency install failed"
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
Invoke-Native $UvExe (@("pip", "install", "-q", "--python", $PyBin, "--no-deps", "--no-build-isolation") + $specs) "package install failed"

Invoke-Native $UvExe @("pip", "check", "--python", $PyBin) "dependency consistency check failed"

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
# **An old runtime counts as missing** (2026-10-03): llama.cpp's builds
# need $VcRuntimeMinimum or newer, so a machine with only Visual Studio
# 2022's runtime is upgraded, and every message says which it found.
if (-not (Test-VcRuntime)) {
    $vcFound = Get-VcRuntimeVersion
    $vcLacks = if ($vcFound) {
        "the Microsoft Visual C++ runtime $vcFound, older than the $VcRuntimeMinimum llama.cpp needs"
    }
    else { "no Microsoft Visual C++ runtime, which llama.cpp needs" }
    if ($Isolated) {
        Warn "this Windows has $vcLacks. An isolated install changes nothing outside its folder, so it was not installed: $VcRedistUrl"
    }
    elseif ($IsElevated) {
        Say "installing the Microsoft Visual C++ runtime: this Windows has $vcLacks"
        try {
            $vcExit = Install-VcRuntime
            if (Test-VcRuntime) { Say "the Visual C++ runtime is installed" }
            elseif ($vcExit -eq 3010) {
                # An old runtime's DLLs are in use by running programs, and
                # Windows replaces a file in use at the next restart.
                Warn "the Visual C++ runtime is installed, and Windows finishes replacing the old one when this machine restarts. llama.cpp may not start until then."
            }
            else {
                $vcAfter = Get-VcRuntimeVersion
                if ($vcAfter) { Warn "the Visual C++ runtime installer finished, but this Windows still has $vcAfter, older than $VcRuntimeMinimum. llama.cpp may not start until it is updated: $VcRedistUrl" }
                else { Warn "the Visual C++ runtime installer finished, but its DLLs are not in place. llama.cpp will not start until they are: $VcRedistUrl" }
            }
        }
        catch {
            Warn "could not install the Microsoft Visual C++ runtime ($(Get-ErrorText $_)). Eugene works, but llama.cpp will not start until it is installed: $VcRedistUrl"
        }
    }
    else {
        Warn "this Windows has $vcLacks. Install the current one from $VcRedistUrl (it asks for Administrator), then start your models."
    }
}

# --- 4b. join, if this machine is a worker -----------------------------
# **The installer owns the one onboarding question, because this is the
# only moment a human is reliably present.** See the task action below
# for what went wrong when that was left to the agent.
if ($Join) {
    if (-not $Token) { Die "-Join needs -Token (mint one at the control root: Nodes -> Add a node)" }
    $joinArgs = @("join", "--control", $Join, "--token", $Token)
    Say "joining $Join as a worker node"
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

# Save the offline utility before registering it with Windows Settings.
Write-RemovalBundle $Prefix
if (-not $Isolated) {
    & (Join-Path $Prefix 'uninstall\remove.ps1') -Prefix $Prefix -Register -SystemInstall:$WantsService
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
