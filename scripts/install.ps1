<#
.SYNOPSIS
  Eugene Plexus -- one-command install for Windows.

.DESCRIPTION
  The Windows half of install-paths section 9 step 3. Same six steps as
  `install.sh`, in the same order, so that reading one is reading both:

    1. fetch `uv` into the install prefix and nowhere else,
    2. make a virtualenv there with a Python `uv` downloads itself,
    3. install the six Eugene Plexus packages into it,
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
#>
[CmdletBinding()]
param(
    [string]$Prefix,
    [switch]$NoService,
    [switch]$NoTray,
    [switch]$NoElevate,
    [switch]$NoStart,
    [switch]$Uninstall,
    [switch]$Verify,
    [switch]$Detect,
    [switch]$Migrate,
    [switch]$PurgeDownloads,
    [switch]$PurgeModelCopies,
    [string]$Join,
    [string]$Token,
    [string]$NodeName,
    [string]$Advertise
)

$ErrorActionPreference = "Stop"

# --- pins -------------------------------------------------------------
# Keep in lockstep with install.sh. One commit per repo.
$PIN = @{
    "agent"            = "c5ad280d45ba9730189f816c97e56595ea6e2a9d"
    "control"          = "5cd8733d5e91c003f03097db517057f809006846"
    "gateway"          = "e232fce030eb851d9d55f832956b9e8a260d345a"
    "inference-driver" = "4dc12fe2f0b1bd49a37870848731f6945ab6ff61"
    "library"          = "337c987c382d9d0bb794cdf49496aa9c88897a98"
    "ui"               = "bd0b45613498b2623c88c49b2eb805245df7ff0f"  # branch `dist`, not `main`
}
$DIST = @{
    "agent"            = "eugene-plexus-agent"
    "control"          = "eugene-plexus-control"
    "gateway"          = "eugene-plexus-gateway"
    "inference-driver" = "eugene-plexus-inference-driver"
    "library"          = "eugene-plexus-library"
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
function Die { param($m) Write-Host "error: $m" -ForegroundColor Red; throw $m }

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
    try { & $Exe @Arguments 2>&1 | Out-Null }
    finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0 -and $FailMessage) { Die $FailMessage }
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
    if (Test-Path (Join-Path $Prefix "agent.yaml")) { return $Prefix }
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
    Get-CimInstance Win32_Process -Filter "Name='eugene-plexus-tray.exe'" |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Venv, 'OrdinalIgnoreCase') } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    # A task's process keeps running after the task is unregistered.
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='eugene-plexus-agent.exe'" |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Venv, 'OrdinalIgnoreCase') } |
    ForEach-Object {
        Say "stopping pid $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
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
    # **Deliberately no `Assert-OwnInstall` here.** Removing a named
    # prefix is a legitimate thing to do on a machine whose autostart
    # belongs to a different install -- it is, in fact, exactly how the
    # operator recovers from #10. What must not happen is taking that
    # other install's autostart away, and `Remove-Autostart` is where
    # that is refused.
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
    $names = @("EUGENE_PLEXUS_AGENT_CONFIG_FILE", "EUGENE_PLEXUS_AGENT_BIND_HOST",
        "EUGENE_PLEXUS_AGENT_BIND_PORT", "EUGENE_PLEXUS_AGENT_ENGINE_ROOT",
        "EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS")
    foreach ($scope in @("User", "Machine")) {
        if ($scope -eq "Machine" -and -not $IsElevated) { continue }
        $cfg = [Environment]::GetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", $scope)
        $mine = $cfg -and ([IO.Path]::GetFullPath($cfg) -eq [IO.Path]::GetFullPath($Config))
        # BIND_HOST is cleared whatever it points at: this installer
        # stopped setting it on 2026-09-11, every install made before
        # then did, and an account-wide widened bind outliving the
        # install that set it is the thing that made it a defect.
        if (-not $mine) {
            [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_HOST", $null, $scope)
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
        Move-Item -LiteralPath $Prefix -Destination $keep
        Say "removed. Your config and logs are at $keep -- delete it when you are sure."
    }
    else {
        Say "nothing installed at $Prefix"
    }
    return
}

# Explain ownership and migration in the calling terminal before UAC. An
# elevated -File window closes on failure, taking its useful refusal with it.
# The elevated run repeats these read-only checks against its own context.
Assert-OwnInstall
Show-MigrationConsequences

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
    $self = Join-Path ([IO.Path]::GetTempPath()) "eugene-plexus-install-$PID.ps1"
    # WriteAllText, never Set-Content -Encoding utf8: the BOM is what
    # breaks a SPECS_REF archive URL, and a BOM in front of `<#` here
    # would break the help block just as reliably.
    [IO.File]::WriteAllText($self, $MyInvocation.MyCommand.ScriptBlock.ToString())
    $forwarded = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $self)
    foreach ($entry in $PSBoundParameters.GetEnumerator()) {
        if ($entry.Value -is [switch]) {
            if ($entry.Value.IsPresent) { $forwarded += "-$($entry.Key)" }
        }
        elseif ($null -ne $entry.Value -and "$($entry.Value)" -ne "") {
            $forwarded += @("-$($entry.Key)", "$($entry.Value)")
        }
    }
    try {
        $elevated = Start-Process -FilePath "powershell.exe" -ArgumentList $forwarded `
            -Verb RunAs -Wait -PassThru
    }
    catch {
        Remove-Item $self -ErrorAction SilentlyContinue
        Die @"
Windows would not start an elevated PowerShell ($($_.Exception.Message)).
    Start one yourself and run this again, or install the per-user
    version, which starts when you log in rather than at boot:
        ... -NoService
"@
    }
    Remove-Item $self -ErrorAction SilentlyContinue
    if ($elevated.ExitCode -ne 0) {
        Die "the elevated install exited with code $($elevated.ExitCode); see its window for why"
    }
    Say "done (installed by the elevated run above)"
    return
}

# --- 1. uv ------------------------------------------------------------
Say "installing into $Prefix$(if ($WantsService) { ' (a Windows service: starts at boot)' } else { ' (per-user: starts when you log in)' })"
New-Item -ItemType Directory -Force -Path (Join-Path $Prefix "bin"), (Join-Path $Prefix "logs") | Out-Null

# Before uv, before the venv, before anything can read a config: if this
# run is taking over an install that lives somewhere else, its identity
# comes with it. A half-built prefix that already holds the right
# `node.yaml` is recoverable by re-running; one that gets a venv first
# and an identity never is a second install.
if ($Migrate) {
    $migrateFrom = Get-OtherInstall
    if ($migrateFrom) { Copy-InstallState -Source $migrateFrom.Prefix }
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
# also what an upgrade of a supervised install means.
if ((Get-AgentTask) -or (Get-AgentService)) {
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
Say "all six packages present, with a web UI"

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
    if ($LASTEXITCODE -ne 0) { Die "enrollment failed; nothing was started" }

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
if (-not $NoService) {
    Remove-Autostart
    if ($WantsService) {
        Say "registering the $ServiceName service"
        # pywin32 ships the DLLs the service host needs under
        # site-packages; its postinstall is what makes them findable
        # from a service context. Harmless when already done.
        $post = Join-Path $Venv "Scripts\pywin32_postinstall.py"
        if (Test-Path $post) { & $PyBin $post -install -silent *>&1 | Out-Null }
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
    }
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
if ($autostart -ne "none") {
    Add-StartMenuShortcut
}

if ($autostart -eq "service" -and -not $NoTray) {
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
[Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", $Config, "User")
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
if ($Port -ne 8079) {
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
