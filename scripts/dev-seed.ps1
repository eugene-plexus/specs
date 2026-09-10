<#
.SYNOPSIS
  Seed a working development install: auth, topology, and one engine runtime.

.DESCRIPTION
  The honest first draft of first-run.

  Until now the only path from nothing to a running stack was an
  acceptance script — `scripts/m6-acceptance.sh` builds a throwaway
  install in $TMPDIR, uses it, and deletes it. Nothing built an install
  an operator could keep, so the config in a developer's checkout was
  never exercised and drifted for four milestones without anyone
  noticing.

  This does the same work against a *durable* dev install and leaves it
  running. It is deliberately not a wizard: every step here is a step
  the real first-run flow has to take, and the ones that are awkward in
  PowerShell are the ones that are still missing from the product.

  Two phases, because one of them needs the agent already running:

    Write   offline. Creates the install directory and each component's
            own config file. Safe before the agent starts; idempotent.
    Seed    online. Initializes the operator passphrase, declares the
            topology over `POST /v1/components`, initializes the control
            root, and declares one llama.cpp runtime — which is what
            makes the alias routable, because the agent declares the
            companion inference-driver itself (M6).

  What this does NOT do, and what the wizard still owes: pick a model,
  fetch an engine, or explain any of it. It takes paths.

.PARAMETER Action
  Write, Seed, or All (default). `All` runs Write then Seed.

.PARAMETER InstallPath
  Where the install lives. Defaults to `.dev-install` beside the repo
  checkouts, or $env:EUGENE_PLEXUS_DEV_INSTALL. This is install state,
  not source — it is deliberately outside every git checkout, because
  putting it inside one is how the last install came to be a fossil
  nobody could see.

.PARAMETER Model
  Absolute path to a .gguf. The operator's own path, in the operator's
  own layout — never copied, never renamed.

.PARAMETER Binary
  Path to llama-server(.exe). When it is missing the topology is still
  seeded and the runtime is skipped with a reason: three components and
  no engine is a legitimate state, and the agent can fetch an engine
  itself (M1).

.PARAMETER SkipRuntime
  Seed auth and the topology only.

.EXAMPLE
  # 1. Run the "Eugene Plexus: Start" task, then:
  .\scripts\dev-seed.ps1
#>
[CmdletBinding()]
param(
    [ValidateSet('Write', 'Seed', 'All')]
    [string]$Action = 'All',
    [string]$InstallPath,
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

function Write-DevInstall {
    param([string]$Path, [string]$ModelPath)

    New-Item -ItemType Directory -Path $Path -Force | Out-Null

    # No agent.yaml. The components are declared over HTTP below, so this
    # exercises POST /v1/components rather than a hand-written topology —
    # the wizard cannot create components yet, and pretending otherwise
    # here would hide that.
    Write-TextFile (Join-Path $Path 'control.yaml') "logLevel: INFO`n"

    # Short intervals so a developer sees routing and idle-unload decisions
    # inside a session rather than a coffee break. Production defaults are
    # the spec's, not these.
    Write-TextFile (Join-Path $Path 'gateway.yaml') @"
logLevel: INFO
routingRefreshSeconds: 3
idleCheckSeconds: 5
swapWaitSeconds: 120
"@

    $roots = @()
    if ($ModelPath) { $roots += (Split-Path $ModelPath -Parent) }
    $rootLines = ($roots | ForEach-Object { "  - $_" }) -join "`n"
    $libraryBody = "logLevel: INFO`n"
    if ($rootLines) { $libraryBody += "modelRoots:`n$rootLines`n" }
    Write-TextFile (Join-Path $Path 'library.yaml') $libraryBody

    Write-Host "Install directory prepared at $Path"
    Write-Host '  control.yaml, gateway.yaml, library.yaml written; topology is seeded over HTTP.'
}

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
        if (-not $response) { throw }
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

# The passphrase travels as a SecureString and is unwrapped only into the
# request body. There is no recovery path for it by design, so it is also
# never written to disk, echoed, or put in a process command line.
function ConvertTo-PlainText {
    param([securestring]$Secure)

    return (New-Object System.Net.NetworkCredential('', $Secure)).Password
}

# Initialize if fresh, log in if not. A dev install gets seeded more than
# once and the second run must not be a puzzle.
function Get-OperatorToken {
    param([string]$AgentUrl, [securestring]$Passphrase)

    $result = Invoke-Api POST "$AgentUrl/v1/auth/initialize" @{ passphrase = (ConvertTo-PlainText $Passphrase) }
    if ($result.Code -eq 200 -or $result.Code -eq 201) { return @{ Token = $result.Body.sessionToken; Fresh = $true } }
    $login = Invoke-Api POST "$AgentUrl/v1/auth/login" @{ passphrase = (ConvertTo-PlainText $Passphrase) }
    if ($login.Code -eq 200 -and $login.Body.sessionToken) { return @{ Token = $login.Body.sessionToken; Fresh = $false } }
    throw "Could not obtain an operator session (initialize: $($result.Code), login: $($login.Code)). If this install already has a different passphrase, delete the install directory or supply the right one."
}

function Add-DevComponent {
    param([string]$AgentUrl, [string]$Token, [hashtable]$Entry)

    $result = Invoke-Api POST "$AgentUrl/v1/components" $Entry $Token
    switch ($result.Code) {
        201 { Write-Host "  declared $($Entry.name) ($($Entry.kind)) at $($Entry.url)"; return $true }
        409 { Write-Host "  $($Entry.name) already declared"; return $true }
        default {
            Write-Host "  FAILED to declare $($Entry.name): HTTP $($result.Code) $($result.Body.detail)"
            return $false
        }
    }
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
        Write-Host '  WARNING: no companion driver was reported — the alias will not be routable.'
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
        [string]$InstallPath,
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
    $ok = $true

    Write-Host "`n== operator session"
    if (-not (Wait-Healthy $agentUrl 30)) {
        throw "No agent at $agentUrl. Run the `"Eugene Plexus: Start`" task first."
    }
    $session = Get-OperatorToken $agentUrl $Passphrase
    $token = $session.Token
    if ($session.Fresh) { Write-Host '  install initialized; operator session issued' }
    else { Write-Host '  install was already initialized; logged in' }

    Write-Host "`n== topology"
    $components = @(
        @{ name = 'control'; kind = 'control'; url = "http://127.0.0.1:$($ports.Control)"; spawn = @{ configFile = 'control.yaml' } },
        @{ name = 'gateway'; kind = 'gateway'; url = "http://127.0.0.1:$($ports.Gateway)"; spawn = @{ configFile = 'gateway.yaml' } },
        @{ name = 'library'; kind = 'library'; url = "http://127.0.0.1:$($ports.Library)"; spawn = @{ configFile = 'library.yaml' } }
    )
    foreach ($entry in $components) {
        if (-not (Add-DevComponent $agentUrl $token $entry)) { $ok = $false }
    }

    Write-Host "`n== control root"
    if (Wait-Healthy $controlUrl 60) {
        # 204 fresh, 409 already initialized. Both mean the root has an
        # operator; it mints its own signing key either way.
        $init = Invoke-Api POST "$controlUrl/v1/auth/initialize" @{ passphrase = (ConvertTo-PlainText $Passphrase) }
        if ($init.Code -eq 204 -or $init.Code -eq 200) { Write-Host '  control root initialized with the same passphrase' }
        elseif ($init.Code -eq 409) { Write-Host '  control root was already initialized' }
        else { Write-Host "  WARNING: control initialize returned HTTP $($init.Code)"; $ok = $false }
    } else {
        Write-Host "  WARNING: control never answered on $controlUrl"
        $ok = $false
    }

    # Seeding IS this install's first run. Leaving the flag false sends the
    # UI to /setup, where the wizard's first act is POST /v1/auth/initialize
    # on an install that already has an operator — a dead end.
    Write-Host "`n== first run"
    $flip = Invoke-Api PATCH "$agentUrl/v1/config" @{ firstRunComplete = $true } $token
    if ($flip.Code -eq 200) { Write-Host '  marked first-run complete; the UI opens on the dashboard' }
    else { Write-Host "  WARNING: could not set firstRunComplete (HTTP $($flip.Code)); the UI will open the wizard"; $ok = $false }

    if ($SkipRuntime) {
        Write-Host "`n== runtime skipped by request"
        return $ok
    }
    if (-not $BinaryPath -or -not (Test-Path -LiteralPath $BinaryPath)) {
        Write-Host "`n== runtime skipped: no llama-server binary"
        Write-Host '  Pass -Binary, or let the agent fetch one through the UI (Engines).'
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
        Write-Host "  runtime $RuntimeName is ready; '$ModelAlias' should now be routable through the gateway"
    } else {
        Write-Host "  FAILED: runtime $RuntimeName is $($ready.Status). $($ready.Error)"
        $ok = $false
    }
    return $ok
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $installPath = Get-DevInstallPath $script:PolyrepoRoot $InstallPath
        if (-not $Model) {
            $Model = if ($env:EUGENE_PLEXUS_DEV_MODEL) { $env:EUGENE_PLEXUS_DEV_MODEL } else { Join-Path $script:PolyrepoRoot 'smoke-test\models\Qwen3-1.7B-Q8_0.gguf' }
        }
        if (-not $Binary) {
            $Binary = if ($env:EUGENE_PLEXUS_DEV_LLAMA_SERVER) { $env:EUGENE_PLEXUS_DEV_LLAMA_SERVER } else { 'C:\Users\troyc\OneDrive\Desktop\llamacpp\llama-server.exe' }
        }
        if (-not $Alias) {
            $Alias = if ($Model) { [IO.Path]::GetFileNameWithoutExtension($Model).ToLowerInvariant() } else { $RuntimeName }
        }

        if ($Action -eq 'Write' -or $Action -eq 'All') {
            Write-DevInstall $installPath $Model
        }
        if ($Action -eq 'Seed' -or $Action -eq 'All') {
            if ($env:EUGENE_PLEXUS_DEV_PASSPHRASE) {
                $passphrase = ConvertTo-SecureString $env:EUGENE_PLEXUS_DEV_PASSPHRASE -AsPlainText -Force
            } else {
                $passphrase = Read-Host 'Operator passphrase for this dev install (not saved)' -AsSecureString
            }
            if (-not $passphrase -or $passphrase.Length -eq 0) {
                throw 'A passphrase is required. There is no recovery path for it, by design.'
            }
            $seeded = Invoke-DevSeed -InstallPath $installPath -Passphrase $passphrase -ModelPath $Model `
                -BinaryPath $Binary -RuntimeName $RuntimeName -ModelAlias $Alias -SkipRuntime:$SkipRuntime
            $passphrase.Dispose()
            if (-not $seeded) {
                Write-Host "`nSeeding finished with failures. Run the health check for detail."
                exit 1
            }
            Write-Host "`nSeeded. Run `"Eugene Plexus: Health Check`", or open the UI."
        }
    } catch {
        Write-Error $_
        exit 1
    }
}
