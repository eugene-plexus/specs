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

  ELEVATION DECIDES THE SHAPE OF THE INSTALL, and this is the one place
  the two platforms genuinely differ. Windows has no per-user service,
  so:

    not elevated -> %LOCALAPPDATA%\EugenePlexus + a logon scheduled task.
                    Needs no Administrator. A task has a console, so
                    supervised children keep the graceful stop.
    elevated     -> %ProgramData%\EugenePlexus + a real Windows service.
                    Starts at boot with no one logged in; `sc stop` and
                    a recovery policy work. A service has NO console, so
                    supervised children get a hard kill -- decided,
                    accepted, and announced by the agent at every boot
                    (install-paths section 12, step 2).

  Both are supported. Run it however you want the machine to behave.

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
    "agent"            = "0e78b2a9f678a125738525d4b26377d3169402b3"
    "control"          = "92e8b28ea8603e10153df2506e444ecbd8252efc"
    "gateway"          = "6d0e62b6d678e286f4c49ddbd3aabd22fd1144bb"
    "inference-driver" = "e4ac3c1d2f917c683212e148f0ab01b1f59e6610"
    "library"          = "beb7ddc930d86ea9442169e6fa6546e08c34d6af"
    "ui"               = "bc37ecc55d034839f546f162726c21527f650dd8"  # branch `dist`, not `main`
}
$DIST = @{
    "agent"            = "eugene-plexus-agent"
    "control"          = "eugene-plexus-control"
    "gateway"          = "eugene-plexus-gateway"
    "inference-driver" = "eugene-plexus-inference-driver"
    "library"          = "eugene-plexus-library"
    "ui"               = "eugene-plexus-ui"
}

$PyVersion    = "3.12"
$ServiceName  = "EugenePlexusAgent"
$TaskName     = "EugenePlexusAgent"

function Say  { param($m) Write-Host "==> $m" -ForegroundColor Cyan }
function Warn { param($m) Write-Host "warning: $m" -ForegroundColor Yellow }
# **`Die` throws; it does NOT call `exit`.** The documented way to run
# this script with options is
# `& ([scriptblock]::Create((irm ...))) -Join ...`, and a scriptblock
# invoked that way runs in the CALLER'S PROCESS -- so `exit 1` closed
# the operator's terminal, taking the error message with it and leaving
# no way to find out what went wrong. Reported from a VS Code terminal
# that vanished on every failure. A throw is catchable, prints, and
# still yields exit code 1 under `powershell -File`.
function Die  { param($m) Write-Host "error: $m" -ForegroundColor Red; throw $m }

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

if (-not $Prefix) {
    $Prefix = if ($IsElevated) { Join-Path $env:ProgramData "EugenePlexus" }
              else             { Join-Path $env:LOCALAPPDATA "EugenePlexus" }
}

$Venv    = Join-Path $Prefix "venv"
$PyBin   = Join-Path $Venv "Scripts\python.exe"
$AgentEx = Join-Path $Venv "Scripts\eugene-plexus-agent.exe"
$UvExe   = Join-Path $Prefix "bin\uv.exe"
$Config  = Join-Path $Prefix "agent.yaml"
$Port    = if ($env:EUGENE_PLEXUS_AGENT_BIND_PORT) { $env:EUGENE_PLEXUS_AGENT_BIND_PORT } else { 8079 }

# --- -Verify ----------------------------------------------------------
# The two commands that close the one gap this installer cannot close
# itself. Printed rather than run, because running them needs the
# elevation that is the whole point.
if ($Verify) {
    Write-Host @"
The scheduled-task path is verified by scripts/install-acceptance.sh.
The SERVICE path is not: registering one needs Administrator, which the
session that wrote this did not have. To close it, in an ELEVATED
PowerShell:

    & "$PyBin" -m eugene_plexus_agent.winservice install
    Start-Service $ServiceName
    Invoke-RestMethod http://127.0.0.1:$Port/healthz
    Stop-Service $ServiceName
    & "$PyBin" -m eugene_plexus_agent.winservice remove

Expected: /healthz answers, and the agent's log carries the line
'child shutdown: ... no console ...' as a WARNING -- a service has no
console, so supervised children are hard-killed. That warning is the
badge, not a bug.
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
    } catch { return $false }
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
    } else {
        Write-Host "autostart runs:       (nothing registered under $TaskName / $ServiceName)"
    }
    $other = Get-OtherInstall
    if ($null -eq $other) {
        if ($exe) {
            Say "this install: an ordinary run is an upgrade of the install already here"
        } else {
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
    Write-Host "  To upgrade the install that is already here:"
    Write-Host "      ... -Prefix '$($other.Prefix)'"
    Write-Host "  To move this machine to $Prefix on purpose, taking the autostart with it:"
    Write-Host "      ... -Prefix '$Prefix' -Migrate"
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
        } else {
            & sc.exe delete $ServiceName | Out-Null
        }
    }
    if (Get-AgentTask) {
        Say "removing the scheduled task"
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
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
    if (-not $clean -and -not $Migrate) { exit 3 }
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
        } else {
            Say "this node's model copies are at $copyDir ($gib GiB) -- they are copies, so"
            Say "  deleting them loses nothing. Re-run with -PurgeDownloads, or remove it yourself."
        }
    } elseif ($copyDir) {
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
        } else {
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
    } else {
        Say "nothing installed at $Prefix"
    }
    return
}

# --- 0. is this machine already somebody's install? -------------------
# Before the first byte is written, and before step 3 stops a running
# agent -- which is where an unguarded run took the other install's
# task away (review 6.1 #10).
Assert-OwnInstall

# --- 1. uv ------------------------------------------------------------
Say "installing into $Prefix$(if ($IsElevated) { ' (elevated: a Windows service)' } else { ' (per-user: a logon task)' })"
New-Item -ItemType Directory -Force -Path (Join-Path $Prefix "bin"), (Join-Path $Prefix "logs") | Out-Null

if (Test-Path $UvExe) {
    Say "uv already present ($(& $UvExe --version))"
} else {
    Say "fetching uv"
    # UV_UNMANAGED_INSTALL puts uv exactly here and edits no PATH and no
    # profile. The installer owns its own copy, so nothing the user
    # already has is touched and removing the prefix is complete.
    $env:UV_UNMANAGED_INSTALL = Join-Path $Prefix "bin"
    try {
        & ([scriptblock]::Create((Invoke-RestMethod https://astral.sh/uv/install.ps1))) *>&1 | Out-Null
    } catch {
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
} else {
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
    $extra = if ($repo -eq "agent") { "[service]" } else { "" }
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
    if ($NodeName)  { $joinArgs += @("--name", $NodeName) }
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
} elseif ($Token) {
    Die "-Token needs -Join <control-root-url>"
} elseif ($Advertise) {
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
    } else { @() }
    $lines += "advertiseUrl: $Advertise"
    [IO.File]::WriteAllText($Config, ($lines -join "`n") + "`n",
        (New-Object Text.UTF8Encoding $false))
}

# --- 5. autostart -----------------------------------------------------
$autostart = "none"
if (-not $NoService) {
    Remove-Autostart
    if ($IsElevated) {
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
        $modelRoot  = Join-Path $Prefix "models"
        New-Item -ItemType Directory -Force -Path $engineRoot, $modelRoot | Out-Null
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_ENGINE_ROOT", $engineRoot, "Machine")
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS", $modelRoot, "Machine")
        $env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT = $engineRoot
        $env:EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS = $modelRoot
        $autostart = "service"
        Warn "a Windows service has no console, so supervised children are stopped with a hard kill. The agent says so at every boot. Run with '-Verify' for how to confirm the service end to end."
    } else {
        Say "registering the $TaskName logon task (no Administrator needed)"
        # **`--unattended`, and this is the line that needed it.** A
        # scheduled task runs its process WITH a console attached --
        # measured 2026-09-11, both stdin and stdout report isatty()
        # True inside one. So the agent's first-boot question printed
        # into a console nobody can see and blocked on input() forever:
        # nothing listening, no log written, and the task cheerfully
        # reporting Running. The installer asks instead (see -Join).
        $action  = New-ScheduledTaskAction -Execute $AgentEx -Argument "--unattended" `
                       -WorkingDirectory $Prefix
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Settings $settings -Description "Eugene Plexus node agent" | Out-Null
        $autostart = "task"
        Warn "this agent starts when you log in, not at boot. Re-run this installer from an elevated PowerShell to install it as a service instead."
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
} else {
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
    } else {
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
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    Die "the agent did not answer on port $Port within 60s. Check $Prefix\logs\agent.log"
}

Say "installed. Start it with:"
if ($autostart -eq "service")   { Write-Host "    Start-Service $ServiceName" }
elseif ($autostart -eq "task")  { Write-Host "    Start-ScheduledTask -TaskName $TaskName" }
else { Write-Host "    `$env:EUGENE_PLEXUS_AGENT_CONFIG_FILE = '$Config'; & '$AgentEx'" }
Write-Host "    then open http://127.0.0.1:$Port/"
Write-Host "    logs:  $Prefix\logs\    config: $Config"
