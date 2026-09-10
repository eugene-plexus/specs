<#
.SYNOPSIS
  Finish a development install without clicking: passphrase, model roots,
  and one engine runtime.

.DESCRIPTION
  Optional. Nothing requires this script.

  The agent declares and spawns the control root, gateway and library on
  its first boot (see the agent's `default_topology.py`), so starting the
  agent is the whole of "get a control plane running". What is left after
  that is genuinely the operator's: choosing a passphrase, saying where
  their models live, and launching one. The browser UI is where those
  belong.

  This is the unattended equivalent, for a dev loop or CI that should not
  need a browser. It does exactly what the UI would do, over the same
  endpoints - there is no privileged path here and nothing is written to
  disk by hand.

  It used to declare the topology too. That is why it existed at all, and
  the agent doing it instead is the reason this file shrank rather than
  grew.

.PARAMETER Model
  Absolute path to a .gguf. The operator's own path, in the operator's own
  layout - never copied, never renamed. Its directory becomes the
  library's model root.

.PARAMETER Binary
  Path to llama-server(.exe). Without it the passphrase and model root are
  still set and the runtime is skipped with a reason; the agent can fetch
  an engine itself (M1).

.PARAMETER SkipRuntime
  Set the passphrase and model roots, launch nothing.

.EXAMPLE
  # Start the agent (the "Eugene Plexus: Start" task), then:
  .\scripts\dev-seed.ps1
#>
[CmdletBinding()]
param(
    [string]$Model,
    [string]$Binary,
    [string]$RuntimeName = 'qwen3-a',
    [string]$Alias,
    [switch]$SkipRuntime
)

$ErrorActionPreference = 'Stop'
$script:WorkspaceRoot = Split-Path $PSScriptRoot -Parent
$script:PolyrepoRoot = Split-Path $script:WorkspaceRoot -Parent

. (Join-Path $PSScriptRoot 'dev-common.ps1')

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Url,
        $Body,
        [string]$Token
    )

    $headers = @{}
    if ($Token) { $headers.Authorization = "Bearer $Token" }
    $request = @{
        Uri             = $Url
        Method          = $Method
        Headers         = $headers
        UseBasicParsing = $true
        TimeoutSec      = 30
    }
    if ($null -ne $Body) {
        $request.ContentType = 'application/json'
        $request.Body = ($Body | ConvertTo-Json -Depth 8 -Compress)
    }
    try {
        $response = Invoke-WebRequest @request
        $parsed = $null
        if ($response.Content) { try { $parsed = $response.Content | ConvertFrom-Json } catch { $parsed = $null } }
        return @{ Code = [int]$response.StatusCode; Body = $parsed }
    } catch {
        $response = $_.Exception.Response
        # No response at all: refused, reset, or DNS. That is a state worth
        # reporting, not an exception - a component being restarted underneath
        # us is normal and used to kill this script outright.
        if (-not $response) { return @{ Code = 0; Body = $null } }
        $code = [int]$response.StatusCode
        $text = $null
        try {
            $reader = New-Object IO.StreamReader($response.GetResponseStream())
            $text = $reader.ReadToEnd()
        } catch { $text = $null }
        $parsed = $null
        if ($text) { try { $parsed = $text | ConvertFrom-Json } catch { $parsed = $null } }
        return @{ Code = $code; Body = $parsed }
    } finally {
        $headers.Clear()
    }
}

function Wait-Healthy {
    param([string]$Url, [int]$TimeoutSeconds = 60)

    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "$($Url.TrimEnd('/'))/healthz" -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 1
    }
    return $false
}

# Waits rather than failing fast, and waits BEFORE anything is asked of the
# operator. The tasks are independent by design - VS Code's dependsOn on a
# background task resolves on a log pattern, which is a worse thing to
# depend on than a health endpoint - so this may legitimately be started
# first. Prompting for a passphrase and only then discovering there is no
# agent throws away what the operator typed, which is how this was found.
function Wait-ForAgent {
    param([string]$AgentUrl, [int]$TimeoutSeconds = 180)

    if (Wait-Healthy $AgentUrl 1) { return $true }
    Write-Host "Waiting for the agent at $AgentUrl."
    Write-Host '  Start it with the "Eugene Plexus: Start" task (or Agent alone); this will continue on its own.'
    Write-Host "  Giving up after $TimeoutSeconds seconds. Ctrl+C to stop waiting."
    if (Wait-Healthy $AgentUrl $TimeoutSeconds) {
        Write-Host '  agent is up.'
        return $true
    }
    return $false
}

# The passphrase travels as a SecureString and is unwrapped only into the
# request body. There is no recovery path for it by design, so it is also
# never written to disk, echoed, or put in a process command line.
function ConvertTo-PlainText {
    param([securestring]$Secure)

    return (New-Object System.Net.NetworkCredential('', $Secure)).Password
}

# Initialize if fresh, log in if not. A dev install gets set up more than
# once and the second run must not be a puzzle.
function Get-OperatorToken {
    param([string]$AgentUrl, [securestring]$Passphrase)

    $result = Invoke-Api POST "$AgentUrl/v1/auth/initialize" @{ passphrase = (ConvertTo-PlainText $Passphrase) }
    if ($result.Code -eq 200 -or $result.Code -eq 201) { return @{ Token = $result.Body.sessionToken; Fresh = $true } }
    $login = Invoke-Api POST "$AgentUrl/v1/auth/login" @{ passphrase = (ConvertTo-PlainText $Passphrase) }
    if ($login.Code -eq 200 -and $login.Body.sessionToken) { return @{ Token = $login.Body.sessionToken; Fresh = $false } }
    throw "Could not obtain an operator session (initialize: $($result.Code), login: $($login.Code)). If this install already has a different passphrase, delete the install directory or supply the right one."
}

function Wait-ComponentsRunning {
    param([string]$AgentUrl, [string]$Token, [int]$TimeoutSeconds = 90)

    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        $result = Invoke-Api GET "$AgentUrl/v1/components" $null $Token
        if ($result.Code -eq 200) {
            $components = @($result.Body.components)
            if ($components.Count -gt 0 -and -not ($components | Where-Object { $_.status -ne 'running' })) {
                return $true
            }
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Set-LibraryRoot {
    param([string]$LibraryUrl, [string]$Token, [string]$ModelDirectory)

    # Through the library's own config endpoint, which is what the UI uses.
    # Model directories are the operator's to choose and we never relocate
    # what is in them; this only points at one.
    $result = Invoke-Api PATCH "$LibraryUrl/v1/config" @{ modelRoots = @($ModelDirectory) } $Token
    if ($result.Code -eq 200) {
        Write-Host "  library scanning $ModelDirectory"
        return $true
    }
    Write-Host "  WARNING: could not set the library's model roots (HTTP $($result.Code))"
    return $false
}

function Add-DevRuntime {
    param([string]$AgentUrl, [string]$Token, [hashtable]$Spec)

    $result = Invoke-Api POST "$AgentUrl/v1/runtimes" $Spec $Token
    if ($result.Code -eq 409) {
        Write-Host "  runtime $($Spec.name) already declared"
        return $true
    }
    if ($result.Code -ne 201) {
        # Admission refuses with the arithmetic (M6). Show it: the numbers
        # are the whole point of the refusal.
        Write-Host "  FAILED to declare runtime $($Spec.name): HTTP $($result.Code) $($result.Body.detail)"
        return $false
    }
    Write-Host "  declared runtime $($Spec.name) (admission: $($result.Body.status)); companion driver '$($result.Body.driver)'"
    if (-not $result.Body.driver) {
        Write-Host '  WARNING: no companion driver was reported - the alias will not be routable.'
    }
    return $true
}

function Wait-RuntimeReady {
    param([string]$AgentUrl, [string]$Token, [string]$Name, [int]$TimeoutSeconds = 180)

    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        $result = Invoke-Api GET "$AgentUrl/v1/runtimes" $null $Token
        if ($result.Code -eq 200) {
            $runtime = $result.Body.runtimes | Where-Object { $_.name -eq $Name }
            if ($runtime) {
                if ($runtime.status -eq 'ready') { return @{ Ready = $true; Status = 'ready' } }
                if ($runtime.status -eq 'crashed') { return @{ Ready = $false; Status = 'crashed'; Error = $runtime.lastError } }
            }
        }
        Start-Sleep -Seconds 1
    }
    return @{ Ready = $false; Status = 'timeout' }
}

function Invoke-DevSeed {
    param(
        [securestring]$Passphrase,
        [string]$ModelPath,
        [string]$BinaryPath,
        [string]$RuntimeName,
        [string]$ModelAlias,
        [switch]$SkipRuntime
    )

    $ports = Get-DevPorts
    $agentUrl = "http://127.0.0.1:$($ports.Agent)"
    $controlUrl = "http://127.0.0.1:$($ports.Control)"
    $libraryUrl = "http://127.0.0.1:$($ports.Library)"
    $ok = $true

    Write-Host "`n== operator session"
    if (-not (Wait-Healthy $agentUrl 10)) {
        throw "The agent at $agentUrl stopped answering. Check its task terminal."
    }
    $session = Get-OperatorToken $agentUrl $Passphrase
    $token = $session.Token
    if ($session.Fresh) { Write-Host '  install initialized; operator session issued' }
    else { Write-Host '  install was already initialized; logged in' }

    # Obtaining a session makes the master key available, and the agent
    # restarts every supervised child so they pick it up (M5's
    # restart-on-login; the control root is deliberately exempt). Reading the
    # topology inside that window sees `crashed` for components that are
    # merely being respawned, and talking to one gets a connection refusal.
    Write-Host "`n== topology (declared by the agent, not by this script)"
    if (-not (Wait-ComponentsRunning $agentUrl $token)) {
        Write-Host '  WARNING: not every component came back after the restart-on-login.'
        $ok = $false
    }
    $components = Invoke-Api GET "$agentUrl/v1/components" $null $token
    if ($components.Code -ne 200) {
        Write-Host "  WARNING: could not read the topology (HTTP $($components.Code))"
        $ok = $false
    } else {
        foreach ($c in $components.Body.components) {
            Write-Host "  $($c.name) ($($c.kind)): $($c.status)"
        }
        foreach ($kind in 'control', 'gateway', 'library') {
            if (-not ($components.Body.components | Where-Object { $_.kind -eq $kind })) {
                Write-Host "  WARNING: no $kind in the topology. The agent declares one on a first"
                Write-Host "           boot unless its package is missing from the agent's venv."
                $ok = $false
            }
        }
    }

    Write-Host "`n== control root"
    if (Wait-Healthy $controlUrl 60) {
        $init = Invoke-Api POST "$controlUrl/v1/auth/initialize" @{ passphrase = (ConvertTo-PlainText $Passphrase) }
        if ($init.Code -eq 204 -or $init.Code -eq 200) { Write-Host '  control root initialized with the same passphrase' }
        elseif ($init.Code -eq 409) { Write-Host '  control root was already initialized' }
        else { Write-Host "  WARNING: control initialize returned HTTP $($init.Code)"; $ok = $false }
    } else {
        Write-Host "  WARNING: control never answered on $controlUrl"
        $ok = $false
    }

    if ($ModelPath -and (Test-Path -LiteralPath $ModelPath)) {
        Write-Host "`n== model directory"
        if (-not (Set-LibraryRoot $libraryUrl $token (Split-Path $ModelPath -Parent))) { $ok = $false }
    }

    # Seeding IS this install's first run. Leaving the flag false sends the
    # UI to /setup for an install that already has an operator.
    Write-Host "`n== first run"
    $flip = Invoke-Api PATCH "$agentUrl/v1/config" @{ firstRunComplete = $true } $token
    if ($flip.Code -eq 200) { Write-Host '  marked first-run complete; the UI opens on the dashboard' }
    else { Write-Host "  WARNING: could not set firstRunComplete (HTTP $($flip.Code))"; $ok = $false }

    if ($SkipRuntime) {
        Write-Host "`n== runtime skipped by request"
        return $ok
    }
    if (-not $BinaryPath -or -not (Test-Path -LiteralPath $BinaryPath)) {
        Write-Host "`n== runtime skipped: no llama-server binary"
        Write-Host '  Pass -Binary, or fetch one through the UI (Engines).'
        Write-Host '  The control plane above is running and usable without it.'
        return $ok
    }
    if (-not $ModelPath -or -not (Test-Path -LiteralPath $ModelPath)) {
        Write-Host "`n== runtime skipped: no model at $ModelPath"
        Write-Host '  Pass -Model with an absolute path to a .gguf.'
        return $ok
    }

    Write-Host "`n== engine runtime"
    $spec = @{
        name              = $RuntimeName
        engine            = 'llama_cpp'
        modelPath         = $ModelPath
        modelAlias        = $ModelAlias
        binary            = $BinaryPath
        flags             = @{ contextSize = 4096; gpuLayers = 99; parallelSlots = 1 }
        idleUnloadSeconds = 600
        startOnDemand     = $true
    }
    if (-not (Add-DevRuntime $agentUrl $token $spec)) { return $false }

    Write-Host '  waiting for the engine to load...'
    $ready = Wait-RuntimeReady $agentUrl $token $RuntimeName
    if ($ready.Ready) {
        Write-Host "  runtime $RuntimeName is ready; '$ModelAlias' is routable through the gateway"
    } else {
        Write-Host "  FAILED: runtime $RuntimeName is $($ready.Status). $($ready.Error)"
        $ok = $false
    }
    return $ok
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        if (-not $Model) {
            $Model = if ($env:EUGENE_PLEXUS_DEV_MODEL) { $env:EUGENE_PLEXUS_DEV_MODEL } else { Join-Path $script:PolyrepoRoot 'smoke-test\models\Qwen3-1.7B-Q8_0.gguf' }
        }
        if (-not $Binary) {
            $Binary = if ($env:EUGENE_PLEXUS_DEV_LLAMA_SERVER) { $env:EUGENE_PLEXUS_DEV_LLAMA_SERVER } else { 'C:\Users\troyc\OneDrive\Desktop\llamacpp\llama-server.exe' }
        }
        if (-not $Alias) {
            $Alias = if ($Model) { [IO.Path]::GetFileNameWithoutExtension($Model).ToLowerInvariant() } else { $RuntimeName }
        }

        # Before the prompt, not after it.
        $agentUrl = "http://127.0.0.1:$((Get-DevPorts).Agent)"
        if (-not (Wait-ForAgent $agentUrl)) {
            throw "No agent at $agentUrl. Run the `"Eugene Plexus: Start`" task, then run this again - re-running is safe and nothing was asked of you."
        }
        if ($env:EUGENE_PLEXUS_DEV_PASSPHRASE) {
            $passphrase = ConvertTo-SecureString $env:EUGENE_PLEXUS_DEV_PASSPHRASE -AsPlainText -Force
        } else {
            $passphrase = Read-Host 'Operator passphrase for this dev install (not saved)' -AsSecureString
        }
        if (-not $passphrase -or $passphrase.Length -eq 0) {
            throw 'A passphrase is required. There is no recovery path for it, by design.'
        }
        $seeded = Invoke-DevSeed -Passphrase $passphrase -ModelPath $Model `
            -BinaryPath $Binary -RuntimeName $RuntimeName -ModelAlias $Alias -SkipRuntime:$SkipRuntime
        $passphrase.Dispose()
        if (-not $seeded) {
            Write-Host "`nFinished with warnings. Run the health check for detail."
            exit 1
        }
        Write-Host "`nDone. Run `"Eugene Plexus: Health Check`", or open the UI."
    } catch {
        Write-Error $_
        exit 1
    }
}
