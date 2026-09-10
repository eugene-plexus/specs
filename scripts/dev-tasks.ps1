[CmdletBinding()]
param(
    [ValidateSet('Agent', 'Ui', 'Stop', 'Health')]
    [string]$Action = 'Health'
)

$ErrorActionPreference = 'Stop'
$script:WorkspaceRoot = Split-Path $PSScriptRoot -Parent
$script:StateDirectory = Join-Path $script:WorkspaceRoot '.vscode/task-state'
$script:HelperPath = $PSCommandPath

# Install-path and port resolution are shared with the seeder so the two
# cannot disagree about which install they mean. dev-common.ps1 has no
# param block; sourcing one here would overwrite $Action.
. (Join-Path $PSScriptRoot 'dev-common.ps1')

function Get-TaskOwner {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $record = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $process = Get-Process -Id $record.processId -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    if ($process.StartTime.ToUniversalTime().Ticks.ToString() -ne $record.startTicks) { return $null }
    if ($process.ProcessName -notin 'powershell', 'pwsh') { return $null }
    $command = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.processId)"
    $escapedPath = [regex]::Escape($script:HelperPath)
    if ($command.CommandLine -notmatch "(?i)(?:^|\s)-File\s+(?:`"$escapedPath`"|$escapedPath(?=\s|$))") {
        throw "Cannot verify task ownership from $Path; no process was stopped."
    }
    return $process
}

function Start-OwnedTask {
    param([string]$Name, [string]$Executable, [string[]]$Arguments, [string]$WorkingDirectory)

    if (-not (Test-Path -LiteralPath $Executable)) { throw "Missing $Executable. Install this repo's development prerequisites first." }
    New-Item -ItemType Directory -Path $script:StateDirectory -Force | Out-Null
    $path = Join-Path $script:StateDirectory "$Name.json"
    if (Test-Path -LiteralPath $path) {
        if (Get-TaskOwner $path) { throw "$Name is already running as a workspace task." }
        Remove-Item -LiteralPath $path
    }
    $process = Get-Process -Id $PID
    $record = @{ processId = $PID; startTicks = $process.StartTime.ToUniversalTime().Ticks.ToString() }
    $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($record | ConvertTo-Json -Compress))
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        Push-Location $WorkingDirectory
        try {
            & $Executable @Arguments
            if ($LASTEXITCODE -ne 0) { throw "$Name exited with code $LASTEXITCODE." }
        } finally { Pop-Location }
    } finally {
        $stream.Dispose()
        Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue
    }
}

function Stop-OwnedTasks {
    foreach ($name in 'Ui', 'Agent') {
        $path = Join-Path $script:StateDirectory "$name.json"
        $process = Get-TaskOwner $path
        if ($process) {
            Write-Host "Stopping task-owned $name process tree ($($process.Id))."
            & taskkill.exe /PID $process.Id /T /F
            if ($LASTEXITCODE -ne 0) { throw "Could not stop $name; its ownership record was retained." }
        } else {
            Write-Host "$name has no running task-owned launcher."
        }
        Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue
    }
}

function Get-TaskJson {
    param([string]$Url, [hashtable]$Headers = @{})

    $response = Invoke-WebRequest -Uri $Url -Headers $Headers -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0
    return ($response.Content | ConvertFrom-Json)
}

function Test-ServiceHealth {
    param([string]$Name, [string]$Url)

    try {
        $health = Get-TaskJson "$($Url.TrimEnd('/'))/healthz"
        if ($health.status -ne 'ok' -or $health.safeMode -eq $true) {
            Write-Host "FAIL $Name health: $($health.status) (safe mode: $($health.safeMode -eq $true))"
            return $false
        }
        Write-Host "OK   $Name"
        return $true
    } catch {
        Write-Host "FAIL $Name health endpoint unavailable or invalid."
        return $false
    }
}

function Test-StackHealth {
    param([string]$AgentUrl, [string]$UiUrl, [string]$Token, [switch]$PromptForToken)

    $healthy = Test-ServiceHealth 'agent' $AgentUrl
    $headers = @{}
    if ($Token) { $headers.Authorization = "Bearer $Token" }
    try {
        try {
            $topology = Get-TaskJson "$($AgentUrl.TrimEnd('/'))/v1/components" $headers
        } catch {
            if (-not $Token -and $PromptForToken -and $_.Exception.Response.StatusCode -eq 401) {
                $secret = Read-Host 'Operator token (not saved; obtain through the UI login)' -AsSecureString
                $credential = New-Object System.Net.NetworkCredential('', $secret)
                $headers.Authorization = "Bearer $($credential.Password)"
                $topology = Get-TaskJson "$($AgentUrl.TrimEnd('/'))/v1/components" $headers
            } else { throw }
        }
        $runtimeList = Get-TaskJson "$($AgentUrl.TrimEnd('/'))/v1/runtimes" $headers
        if ($null -eq $topology.components -or $null -eq $runtimeList.runtimes) { throw 'Invalid topology response.' }
        foreach ($runtime in $runtimeList.runtimes) {
            Write-Host "Runtime $($runtime.name): $($runtime.status)"
            # `stopped` is a healthy state: idle unload is policy working,
            # and start-on-demand will wake it. `loading` is a snapshot of
            # something in progress, not a fault - an engine can hold the
            # port without answering for minutes. Neither fails the check.
            if ($runtime.status -eq 'loading') {
                Write-Host "     still loading; re-run to confirm it settles."
            } elseif ($runtime.status -ne 'ready' -and $runtime.status -ne 'stopped') {
                $healthy = $false
            }
        }
        # A companion driver is probed whether or not its runtime is loaded.
        # Per the agent spec, the companion deliberately keeps running while
        # the engine is stopped - that is precisely what lets the gateway
        # keep listing an on-demand model - so a dead one breaks wake-on-
        # demand and must not be reported as merely skipped.
        foreach ($component in $topology.components) {
            if ($component.status -ne 'running') {
                Write-Host "FAIL $($component.name) topology status: $($component.status)"
                $healthy = $false
            }
            $url = $component.advertiseUrl
            if (-not $url) { $url = $component.url }
            if (-not (Test-ServiceHealth $component.name $url)) { $healthy = $false }
        }
    } catch {
        Write-Host 'FAIL topology unavailable. Supply a valid operator token via EUGENE_PLEXUS_DEV_TOKEN or the private prompt; check the agent URL.'
        $healthy = $false
    } finally { $headers.Clear() }

    try {
        $response = Invoke-WebRequest -Uri $UiUrl -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -ne 200) { throw 'UI did not return 200.' }
        Write-Host 'OK   UI'
    } catch {
        Write-Host 'FAIL UI unavailable.'
        $healthy = $false
    }
    return $healthy
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $polyrepoRoot = Split-Path $script:WorkspaceRoot -Parent
        $uiPort = if ($env:EUGENE_PLEXUS_DEV_UI_PORT) { [int]$env:EUGENE_PLEXUS_DEV_UI_PORT } else { 3000 }
        $agentPort = if ($env:EUGENE_PLEXUS_AGENT_BIND_PORT) { $env:EUGENE_PLEXUS_AGENT_BIND_PORT } else { '8079' }
        $agentUrl = if ($env:AGENT_URL) { $env:AGENT_URL } else { "http://127.0.0.1:$agentPort" }
        switch ($Action) {
            'Agent' {
                $root = Join-Path $polyrepoRoot 'agent'
                # The agent's cwd is the install, not the checkout. Everything
                # it persists - agent.yaml, node.yaml, logs/, the companion
                # drivers' configs - lands beside its config file, and putting
                # that inside a source checkout is how the previous install
                # became a fossil that no acceptance run ever loaded.
                $install = Get-DevInstallPath $polyrepoRoot
                New-Item -ItemType Directory -Path $install -Force | Out-Null
                Start-OwnedTask 'Agent' (Join-Path $root '.venv/Scripts/python.exe') @('-m', 'eugene_plexus_agent') $install
            }
            'Ui' {
                $root = Join-Path $polyrepoRoot 'ui'
                $node = (Get-Command node.exe -ErrorAction Stop).Source
                $next = Join-Path $root 'node_modules/next/dist/bin/next'
                if (-not (Test-Path -LiteralPath $next)) { throw 'Missing UI dependencies. Run npm ci in the ui repo.' }
                if (-not $env:AGENT_URL) { $env:AGENT_URL = $agentUrl }
                Start-OwnedTask 'Ui' $node @($next, 'dev', '--port', "$uiPort") $root
            }
            'Stop' { Stop-OwnedTasks }
            'Health' {
                if (-not (Test-StackHealth $agentUrl "http://127.0.0.1:$uiPort/" $env:EUGENE_PLEXUS_DEV_TOKEN -PromptForToken)) { exit 1 }
            }
        }
    } catch {
        Write-Error $_
        exit 1
    }
}