<#
.SYNOPSIS
  Bootstrap a full Eugene Plexus dev environment on Python 3.12 (Windows).

.DESCRIPTION
  Clones every component repo as a sibling of this `specs` checkout, then for
  each Python repo creates a 3.12 virtualenv, installs the package editable
  with dev extras, and activates the pre-commit hooks. Sets up `ui` with
  npm + codegen. Python 3.12 is the project's target (every pyproject pins
  `requires-python = ">=3.12"`, ruff `py312`, mypy `3.12`) and the version CI
  runs — develop on 3.12 so local matches CI.

  Idempotent: re-running skips repos already cloned and venvs already built.

.PREREQUISITES
  - Python 3.12 reachable via the `py` launcher
        winget install Python.Python.3.12
  - git, and gh authenticated:  gh auth login
  - Node.js + npm (for the `ui` repo)

.EXAMPLE
  gh repo clone eugene-plexus/specs
  .\specs\scripts\bootstrap.ps1
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.12"
)
$ErrorActionPreference = "Stop"

# This script lives in specs/scripts/. The polyrepo root (where sibling repos
# live) is the parent of the specs checkout.
$specsRoot = (Resolve-Path "$PSScriptRoot\..").Path
$root = (Resolve-Path "$specsRoot\..").Path
Write-Host "Polyrepo root: $root"
Write-Host "Target Python: $PythonVersion`n"

$pythonRepos = @("hemisphere-driver", "orchestrator", "memory", "watchdog", "identity", "connector")
$allRepos = @("specs") + $pythonRepos + @("ui")

# --- Prerequisite checks ---
$pyOk = $false
try { & py "-$PythonVersion" --version *> $null; $pyOk = $true } catch {}
if (-not $pyOk) {
    throw "Python $PythonVersion not found via the 'py' launcher. Install it (winget install Python.Python.3.12) and reopen the shell."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git not found on PATH." }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "gh (GitHub CLI) not found. Install it and run 'gh auth login'." }
$npmOk = [bool](Get-Command npm -ErrorAction SilentlyContinue)
if (-not $npmOk) { Write-Warning "npm not found - the 'ui' repo will be skipped." }

# pre-commit is invoked as `py -<ver> -m pre_commit`, so install it under the
# target Python once.
& py "-$PythonVersion" -m pip install --quiet --upgrade pre-commit

# --- Clone any missing repos as siblings ---
foreach ($r in $allRepos) {
    $dir = Join-Path $root $r
    if (Test-Path $dir) { Write-Host "[$r] already present" }
    else { Write-Host "[$r] cloning..."; gh repo clone "eugene-plexus/$r" $dir }
}

# --- Set up each Python repo (3.12 venv + dev deps + hooks) ---
foreach ($r in $pythonRepos) {
    $dir = Join-Path $root $r
    $venv = Join-Path $dir ".venv"
    $py = Join-Path $venv "Scripts\python.exe"
    Write-Host "`n=== [$r] ==="
    if (-not (Test-Path $py)) { & py "-$PythonVersion" -m venv $venv }
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -e "$dir[dev]"
    Push-Location $dir
    try { & py "-$PythonVersion" -m pre_commit install | Out-Null } finally { Pop-Location }
    Write-Host "[$r] ready ($(& $py --version))"
}

# --- Set up ui (node + codegen + hooks) ---
if ($npmOk) {
    $uiDir = Join-Path $root "ui"
    Write-Host "`n=== [ui] ==="
    Push-Location $uiDir
    try {
        npm install
        npm run codegen
        & py "-$PythonVersion" -m pre_commit install | Out-Null
    }
    finally { Pop-Location }
    Write-Host "[ui] ready"
}

Write-Host "`nDone. All repos set up on Python $PythonVersion under $root."
Write-Host "Activate a repo's environment with, e.g.:  .\memory\.venv\Scripts\Activate.ps1"
