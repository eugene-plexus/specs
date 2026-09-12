<#
.SYNOPSIS
  Eugene Plexus -- developer environment for Windows.

.DESCRIPTION
  Path A of install-paths section 4, and the Windows half of
  `bootstrap.sh`. The two do the same things in the same order, because
  two dev scripts that build different environments are a maintenance
  trap rather than a convenience.

  Clones every active repo as a sibling of this `specs` checkout, gives
  each Python repo its own 3.12 virtualenv with `[dev]` installed and
  pre-commit hooks active, sets up the Node repos, and -- the step that
  is easy to forget and breaks everything -- installs every component
  into the AGENT's virtualenv, because that is the interpreter the
  supervisor spawns children with.

  This is NOT the end-user installer. That is `install.ps1` beside it:
  one prefix, pinned releases, autostart. This script builds editable
  checkouts you intend to change.

.PREREQUISITES
  `git`, and an internet connection. That is the whole list.

  NOT Python: `uv` downloads its own 3.12 if this machine has none,
  exactly as `install.ps1` does. This used to demand
  `winget install Python.Python.3.12` first.

  NOT an authenticated `gh`: every repo is public and is cloned over
  HTTPS. Section 4 has said so since the design was written, while this
  script used `gh repo clone` -- which is the difference between "a
  contributor can run this" and "a contributor needs a GitHub CLI login
  first".

  Node is optional and only `ui` and `website` need it. Without it they
  are skipped and the script says what that costs.

  Idempotent: re-running skips what is already there.

.EXAMPLE
  git clone https://github.com/eugene-plexus/specs
  .\specs\scripts\bootstrap.ps1

.EXAMPLE
  # Against a throwaway directory, which is how this script is tested:
  .\specs\scripts\bootstrap.ps1 -Root D:\tmp\ep-boot
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.12",
    [string]$Root,
    [switch]$NoNode
)
$ErrorActionPreference = "Stop"

$Org = "https://github.com/eugene-plexus"

# This script lives in specs/scripts/. The polyrepo root -- where sibling
# repos live -- is the parent of the specs checkout unless told
# otherwise. `-Root` exists so this can be run against a throwaway
# directory, which is the only way it has ever been tested.
$specsRoot = (Resolve-Path "$PSScriptRoot\..").Path
if (-not $Root) { $Root = (Resolve-Path "$specsRoot\..").Path }
New-Item -ItemType Directory -Force -Path $Root | Out-Null
$Root = (Resolve-Path $Root).Path

function Say  { param($m) Write-Host "==> $m" -ForegroundColor Cyan }
function Warn { param($m) Write-Host "warning: $m" -ForegroundColor Yellow }
# Throws rather than exits, for the reason install.ps1 records at
# length: `exit` inside a scriptblock ends the HOST session, and a
# script that closes the terminal takes its own error message with it.
# `-File` still reports exit code 1 from an uncaught throw.
function Die  { param($m) Write-Host "error: $m" -ForegroundColor Red; throw $m }

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

# The live control plane. `connector` is deferred, `memory`/`identity`
# and the five training repos are retired -- see
# docs/maintenance/repository-audit-2026-09-10.md for the inventory.
$agentRepo      = "agent"
$componentRepos = @("control", "gateway", "inference-driver", "library")
$pythonRepos    = @($agentRepo) + $componentRepos
# `website` is the project site (Astro, GitHub Pages, eugeneplexus.com).
# Not part of the control plane, cloned anyway: a repo nobody clones is
# a repo nobody discovers.
$nodeRepos      = @("ui", "website")
$allRepos       = @("specs") + $pythonRepos + $nodeRepos

$Boot = Join-Path $Root ".bootstrap"
$UvExe = Join-Path $Boot "bin\uv.exe"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git not found on PATH." }

Say "polyrepo root: $Root"
Say "target Python: $PythonVersion"
New-Item -ItemType Directory -Force -Path (Join-Path $Boot "bin") | Out-Null

# --- uv ---------------------------------------------------------------
# One copy for the whole polyrepo, inside `.bootstrap\` so removing that
# directory undoes everything this script installed outside the repos.
# An existing `uv` on PATH is used as-is.
$onPath = Get-Command uv -ErrorAction SilentlyContinue
if ($onPath) {
    $UvExe = $onPath.Source
    Say "using uv already on PATH ($(& $UvExe --version))"
} elseif (Test-Path $UvExe) {
    Say "uv already present ($(& $UvExe --version))"
} else {
    Say "fetching uv"
    $env:UV_UNMANAGED_INSTALL = Join-Path $Boot "bin"
    try {
        & ([scriptblock]::Create((Invoke-RestMethod https://astral.sh/uv/install.ps1))) *>&1 | Out-Null
    } catch {
        Die "could not install uv from https://astral.sh/uv/install.ps1 -- $($_.Exception.Message)"
    }
    if (-not (Test-Path $UvExe)) { Die "uv did not land at $UvExe" }
    Say "uv $((& $UvExe --version) -replace '^uv ')"
}

# Unlike `install.ps1`, this does NOT force `only-managed`. An end-user
# install wants to be self-contained; a developer who already runs
# $PythonVersion should get their own interpreter, which is uv's default
# preference.

# --- clone ------------------------------------------------------------
Say "cloning"
foreach ($r in $allRepos) {
    $dir = Join-Path $Root $r
    if (Test-Path (Join-Path $dir ".git")) {
        Write-Host ("  {0,-18} already present" -f $r)
    } else {
        Write-Host ("  {0,-18} cloning" -f $r)
        Invoke-Native git @("clone", "-q", "$Org/$r.git", $dir) "could not clone $r"
    }
}

# --- pre-commit -------------------------------------------------------
# In its own environment rather than a system Python, which this script
# no longer requires to exist.
$PreCommit = Join-Path $Boot "venv\Scripts\pre-commit.exe"
if (-not (Test-Path $PreCommit)) {
    Say "installing pre-commit"
    Invoke-Native $UvExe @("venv", "-q", "--python", $PythonVersion, (Join-Path $Boot "venv")) "could not create the tooling virtualenv"
    Invoke-Native $UvExe @("pip", "install", "-q", "--python", (Join-Path $Boot "venv\Scripts\python.exe"), "pre-commit") "could not install pre-commit"
}

function Install-Hooks {
    param($repo)
    $dir = Join-Path $Root $repo
    if (-not (Test-Path (Join-Path $dir ".pre-commit-config.yaml"))) { return }
    Push-Location $dir
    try { & $PreCommit install | Out-Null }
    catch { Warn "[$repo] pre-commit hooks were not installed" }
    finally { Pop-Location }
}

# --- Python repos -----------------------------------------------------
foreach ($r in $pythonRepos) {
    Say "[$r]"
    $dir  = Join-Path $Root $r
    $venv = Join-Path $dir ".venv"
    $py   = Join-Path $venv "Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Invoke-Native $UvExe @("venv", "-q", "--python", $PythonVersion, $venv) "[$r] could not create $venv"
        if (-not (Test-Path $py)) { Die "[$r] could not create $venv" }
    }
    Invoke-Native $UvExe @("pip", "install", "-q", "--python", $py, "-e", "$dir[dev]") "[$r] editable install failed"
    Install-Hooks $r
    Write-Host "  ready ($(& $py --version))"
}

# --- Node repos -------------------------------------------------------
$nodeOk = $false
if (-not $NoNode) {
    $hasNode = [bool](Get-Command node -ErrorAction SilentlyContinue)
    $hasNpm  = [bool](Get-Command npm  -ErrorAction SilentlyContinue)
    if ($hasNode -and $hasNpm) {
        $nodeOk = $true
        foreach ($r in $nodeRepos) {
            Say "[$r]"
            Push-Location (Join-Path $Root $r)
            try {
                Invoke-Native npm @("install", "--no-fund", "--no-audit", "--loglevel=error") "[$r] npm install failed"
            } finally { Pop-Location }
            Install-Hooks $r
            Write-Host "  ready"
        }
        # Codegen then the static export, in that order: the export is
        # built from generated types.
        Say "[ui] codegen and static export"
        Push-Location (Join-Path $Root "ui")
        try {
            Invoke-Native npm @("run", "--silent", "codegen") "[ui] codegen failed"
            Invoke-Native npm @("run", "--silent", "build:python") "[ui] build:python failed"
        } finally { Pop-Location }
    } else {
        Warn "no usable node/npm -- skipping ui and website. The dev agent will serve the API and a 'no web UI installed' page, because since install-paths step 1 the UI is a Python package whose payload is a next build export."
    }
}

# --- the agent's venv is the install's runtime ------------------------
#
# The agent spawns every component with its own `sys.executable`, and
# `default_topology` decides what to declare by calling `find_spec`
# against that same interpreter. Without this the agent starts, cannot
# import the gateway, and declines to declare it: a working supervisor
# with nothing to supervise.
Say "[agent] installing every component into the supervisor's virtualenv"
$agentPy = Join-Path $Root "$agentRepo\.venv\Scripts\python.exe"
foreach ($r in $componentRepos) {
    Invoke-Native $UvExe @("pip", "install", "-q", "--python", $agentPy, "-e", (Join-Path $Root $r)) "[agent] could not install $r"
    Write-Host "  + $r"
}

# The browser half, editable on purpose: `static_dir()` then resolves
# into the checkout, so `npm run build:python` in `ui` is immediately
# visible to a running agent with no reinstall.
if ($nodeOk) {
    Invoke-Native $UvExe @("pip", "install", "-q", "--python", $agentPy, "-e", (Join-Path $Root "ui")) "[agent] could not install ui"
    Write-Host "  + ui (editable: rebuild with npm run build:python)"
}

# --- assert -----------------------------------------------------------
# This script used to assert the imports and nothing else, which was the
# whole story before the UI became a Python package. It is not now: an
# agent that imports every component and serves no browser is a
# half-installed dev environment that looks complete.
Say "checking"
$check = @'
import importlib.util, sys
from pathlib import Path

want_ui = sys.argv[1] == "1"
bad = []
for mod in (
    "eugene_plexus_agent",
    "eugene_plexus_control",
    "eugene_plexus_gateway",
    "eugene_plexus_inference_driver",
    "eugene_plexus_library",
):
    if importlib.util.find_spec(mod) is None:
        bad.append(f"{mod} is not importable from {sys.executable}")

if want_ui:
    try:
        import eugene_plexus_ui
        static = Path(eugene_plexus_ui.static_dir())
        if not (static / "index.html").is_file():
            bad.append(f"the web UI package has no build output at {static}")
    except Exception as exc:
        bad.append(f"the web UI package is not usable: {exc}")

for line in bad:
    print(f"  - {line}", file=sys.stderr)
raise SystemExit(1 if bad else 0)
'@
$checkFile = Join-Path $Boot "bootstrap-check.py"
[IO.File]::WriteAllText($checkFile, $check)
& $agentPy $checkFile $(if ($nodeOk) { "1" } else { "0" })
$rc = $LASTEXITCODE
Remove-Item $checkFile -Force
if ($rc -ne 0) { Die "the developer environment is incomplete" }

Write-Host ""
Say "done -- every repo is set up under $Root"
Write-Host ""
Write-Host "Start a dev control plane from a directory you want the install to live in:"
Write-Host "    mkdir ~\ep-dev; cd ~\ep-dev"
Write-Host "    & '$agentPy' -m eugene_plexus_agent"
Write-Host ""
Write-Host "It declares and spawns the control root, gateway and library on first"
Write-Host "boot, and serves the UI at http://127.0.0.1:8079/."
if ($nodeOk) {
    Write-Host ""
    Write-Host "For UI hot reload instead: 'npm run dev' in $Root\ui."
}
