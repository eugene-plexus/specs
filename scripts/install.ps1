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
    [string]$Join,
    [string]$Token,
    [string]$NodeName,
    [string]$Advertise
)

$ErrorActionPreference = "Stop"

# --- pins -------------------------------------------------------------
# Keep in lockstep with install.sh. One commit per repo.
$PIN = @{
    "agent"            = "46ac6ef34e2c5f00bf695910636ac47b048ae247"
    "control"          = "6c85e2bbdf1e811a8e646ecba37f0bcb48aef724"
    "gateway"          = "bf2c930609eadf58c5225a5bb7b90bc60cce8e90"
    "inference-driver" = "b2aab879cdfbaa328e2403e0e3ce2601810b2aaf"
    "library"          = "1a59e7e7ca3f5895a092cfeeca4a562c65d76010"
    "ui"               = "1ffbdd25c6c5bde89ce3a04bd1a35158ae8448cc"  # branch `dist`, not `main`
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

# --- autostart plumbing ----------------------------------------------
function Get-AgentService {
    Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
}
function Get-AgentTask {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

function Remove-Autostart {
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

# --- uninstall --------------------------------------------------------
if ($Uninstall) {
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
    [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", $null, "User")
    [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_HOST", $null, "User")
    if ($IsElevated) {
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", $null, "Machine")
        [Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_BIND_HOST", $null, "Machine")
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
