<#
.SYNOPSIS
  Helpers shared by the workspace task launcher and the dev seeder.

.DESCRIPTION
  This file has no `param` block on purpose. Dot-sourcing runs the
  sourced file in the caller's scope, so a `param` block here would
  silently overwrite the caller's own parameters - `dev-tasks.ps1
  -Action Ui` would find its `$Action` reset to the seeder's default
  and quietly do nothing at all. Keep this file parameterless.

  It exists so the task that starts the agent and the script that seeds
  it cannot disagree about which install directory or which ports they
  mean.
#>

# The dev install. Deliberately outside every git checkout: the agent
# persists agent.yaml, node.yaml, logs/ and its companion drivers'
# configs beside its config file, and keeping that inside a source
# checkout is how the previous install became a fossil that no
# acceptance run ever loaded and nobody noticed for four milestones.
#
# PolyrepoRoot is a parameter rather than derived from $PSScriptRoot,
# because inside a dot-sourced function $PSScriptRoot resolves to
# whoever sourced it, not to where the function was written.
function Get-DevInstallPath {
    param([string]$PolyrepoRoot, [string]$Explicit)

    if ($Explicit) { return $Explicit }
    if ($env:EUGENE_PLEXUS_DEV_INSTALL) { return $env:EUGENE_PLEXUS_DEV_INSTALL }
    return (Join-Path $PolyrepoRoot '.dev-install')
}

# Defaults are the specs' `servers` entries, which are authoritative.
function Get-DevPorts {
    return @{
        Agent   = if ($env:EUGENE_PLEXUS_AGENT_BIND_PORT) { [int]$env:EUGENE_PLEXUS_AGENT_BIND_PORT } else { 8079 }
        Gateway = if ($env:EUGENE_PLEXUS_GATEWAY_PORT) { [int]$env:EUGENE_PLEXUS_GATEWAY_PORT } else { 8080 }
        Library = if ($env:EUGENE_PLEXUS_LIBRARY_PORT) { [int]$env:EUGENE_PLEXUS_LIBRARY_PORT } else { 8082 }
        Control = if ($env:EUGENE_PLEXUS_CONTROL_PORT) { [int]$env:EUGENE_PLEXUS_CONTROL_PORT } else { 8083 }
    }
}

# UTF-8 without a BOM, always. A BOM in a config file a component reads
# is the same class of bug as the one that broke SPECS_REF archive URLs.
function Write-TextFile {
    param([string]$Path, [string]$Content)

    [IO.File]::WriteAllText($Path, $Content, (New-Object Text.UTF8Encoding $false))
}
