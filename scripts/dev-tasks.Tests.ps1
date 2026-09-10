$helper = Join-Path $PSScriptRoot 'dev-tasks.ps1'
. $helper
. (Join-Path $PSScriptRoot 'dev-seed.ps1')

Describe 'Workspace task health' {
    BeforeEach {
        $script:HealthStatus = 'ok'
        $script:RuntimeStatus = 'ready'
        $script:ComponentStatus = 'running'
        $script:SafeMode = $false
        $script:TopologyFailure = $false
        $script:UiFailure = $false
        $script:ObservedToken = $null
        Mock Write-Host {}
        Mock Invoke-WebRequest {
            if ($script:UiFailure) { throw 'Connection refused' }
            [pscustomobject]@{ StatusCode = 200 }
        }
        Mock Get-TaskJson {
            param($Url, $Headers)
            if ($Url -like '*/v1/components') {
                if ($script:TopologyFailure) { throw 'Unauthorized' }
                $script:ObservedToken = $Headers.Authorization
                return @{ components = @(@{ name = 'replica'; status = $script:ComponentStatus; url = 'http://localhost:19001'; advertiseUrl = 'http://node:29001' }) }
            }
            if ($Url -like '*/v1/runtimes') { return @{ runtimes = @(@{ name = 'engine'; status = $script:RuntimeStatus; driver = 'replica' }) } }
            return @{ status = $script:HealthStatus; safeMode = $script:SafeMode }
        }
    }

    It 'uses discovered advertised ports and sends credentials only to topology' {
        Test-StackHealth 'http://agent:18079' 'http://localhost:3300/' 'test-token' | Should Be $true
        Assert-MockCalled Get-TaskJson -Times 1 -Exactly -Scope It -ParameterFilter { $Url -eq 'http://node:29001/healthz' -and -not $Headers.Authorization }
        $script:ObservedToken | Should Be 'Bearer test-token'
    }

    It 'fails degraded health even with HTTP success' {
        $script:HealthStatus = 'degraded'
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $false
    }

    It 'fails when topology is unauthorized or unreachable' {
        $script:TopologyFailure = $true
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $false
    }

    It 'fails when the UI is down' {
        $script:UiFailure = $true
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $false
    }

    It 'does not fail an intentionally unloaded runtime but still probes its companion' {
        # The companion driver keeps running while its engine is stopped -
        # that is what lets the gateway list an on-demand model - so a dead
        # companion has to surface, not be skipped as "intentional".
        $script:RuntimeStatus = 'stopped'
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $true
        Assert-MockCalled Get-TaskJson -Times 1 -Exactly -Scope It -ParameterFilter { $Url -eq 'http://node:29001/healthz' }
    }

    It 'fails a stopped runtime whose companion driver is down' {
        $script:RuntimeStatus = 'stopped'
        $script:ComponentStatus = 'crashed'
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $false
    }

    It 'does not fail a runtime that is still loading' {
        $script:RuntimeStatus = 'loading'
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $true
    }

    It 'fails a crashed runtime' {
        $script:RuntimeStatus = 'crashed'
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $false
    }

    It 'fails safe mode even when health reports ok' {
        $script:SafeMode = $true
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $false
    }

    It 'fails a component that is still starting' {
        $script:ComponentStatus = 'starting'
        Test-StackHealth 'http://agent' 'http://ui' | Should Be $false
    }
}

Describe 'Workspace task ownership' {
    BeforeEach {
        $script:StateDirectory = $TestDrive
        Mock Write-Host {}
        Mock Get-Process { [pscustomobject]@{ Id = 12345; ProcessName = 'powershell'; StartTime = [datetime]'2026-09-10T12:00:00Z' } }
        Mock Get-CimInstance { [pscustomobject]@{ CommandLine = "powershell -File $script:HelperPath -Action Agent" } }
        $record = @{ processId = 12345; startTicks = ([datetime]'2026-09-10T12:00:00Z').ToUniversalTime().Ticks.ToString() }
        $record | ConvertTo-Json | Set-Content (Join-Path $TestDrive 'Agent.json')
    }

    It 'recognizes the exact recorded launcher' {
        (Get-TaskOwner (Join-Path $TestDrive 'Agent.json')).Id | Should Be 12345
    }

    It 'rejects a reused PID' {
        Mock Get-Process { [pscustomobject]@{ Id = 12345; ProcessName = 'powershell'; StartTime = [datetime]'2026-09-10T13:00:00Z' } }
        Get-TaskOwner (Join-Path $TestDrive 'Agent.json') | Should BeNullOrEmpty
    }

    It 'rejects an unrelated command even with matching PID and creation time' {
        Mock Get-CimInstance { [pscustomobject]@{ CommandLine = 'powershell -File unrelated.ps1' } }
        { Get-TaskOwner (Join-Path $TestDrive 'Agent.json') } | Should Throw
    }

    It 'ignores a launcher that has already exited' {
        Mock Get-Process { $null }
        Get-TaskOwner (Join-Path $TestDrive 'Agent.json') | Should BeNullOrEmpty
    }

    It 'does not launch a duplicate task' {
        { Start-OwnedTask 'Agent' (Get-Command powershell.exe).Source @('-NoProfile') $TestDrive } | Should Throw
    }
}

Describe 'Real isolated task shutdown' {
    It 'checks real health exit codes and stops only its task tree on arbitrary ports' {
        $fixtureRoot = Join-Path $TestDrive 'polyrepo with spaces'
        $fixtureScripts = Join-Path $fixtureRoot 'specs/scripts'
        $fixtureNext = Join-Path $fixtureRoot 'ui/node_modules/next/dist/bin'
        New-Item -ItemType Directory -Path $fixtureScripts, $fixtureNext -Force | Out-Null
        Copy-Item $helper (Join-Path $fixtureScripts 'dev-tasks.ps1')
        # dev-tasks.ps1 dot-sources dev-common.ps1, so the fixture is only a
        # faithful copy if both travel together.
        Copy-Item (Join-Path $PSScriptRoot 'dev-common.ps1') (Join-Path $fixtureScripts 'dev-common.ps1')
        @'
const { spawn } = require('node:child_process');
const child = spawn(process.execPath, ['-e', 'process.stdin.resume()']);
const server = require('node:http').createServer((request, response) => {
    response.setHeader('Content-Type', 'application/json');
    if (request.url.startsWith('/v1/') && request.headers.authorization !== 'Bearer test-token') {
        response.writeHead(401).end('{}');
    } else if (request.url === '/v1/components') {
        response.end(JSON.stringify({ components: [{ name: 'fixture', status: 'running', url: `http://127.0.0.1:${server.address().port}/component` }] }));
    } else if (request.url === '/v1/runtimes') {
        response.end(JSON.stringify({ runtimes: [] }));
    } else {
        response.end(JSON.stringify({ status: 'ok' }));
    }
});
server.listen(0, '127.0.0.1', () => {
  console.log(JSON.stringify({ parent: process.pid, child: child.pid, port: server.address().port }));
});
'@ | Set-Content (Join-Path $fixtureNext 'next') -Encoding ASCII

        $sentinelInfo = New-Object Diagnostics.ProcessStartInfo
        $sentinelInfo.FileName = (Get-Command node.exe).Source
        $sentinelInfo.Arguments = '-e "process.stdin.resume()"'
        $sentinelInfo.UseShellExecute = $false
        $sentinelInfo.RedirectStandardInput = $true
        $sentinel = [Diagnostics.Process]::Start($sentinelInfo)

        $launcherInfo = New-Object Diagnostics.ProcessStartInfo
        $launcherInfo.FileName = (Get-Command powershell.exe).Source
        $fixtureHelper = Join-Path $fixtureScripts 'dev-tasks.ps1'
        $launcherInfo.Arguments = "-NoProfile -File `"$fixtureHelper`" -Action Ui"
        $launcherInfo.UseShellExecute = $false
        $launcherInfo.RedirectStandardOutput = $true
        $launcherInfo.RedirectStandardError = $true
        $launcher = [Diagnostics.Process]::Start($launcherInfo)
        $originalHelperPath = $script:HelperPath
        try {
            $line = $launcher.StandardOutput.ReadLineAsync()
            if (-not $line.Wait(15000)) { throw 'Synthetic launcher did not become ready.' }
            $message = $line.GetAwaiter().GetResult()
            if (-not $message) { throw $launcher.StandardError.ReadToEnd() }
            $started = $message | ConvertFrom-Json
            $parent = Get-Process -Id $started.parent
            $child = Get-Process -Id $started.child
            $script:StateDirectory = Join-Path $fixtureRoot 'specs/.vscode/task-state'
            $script:HelperPath = $fixtureHelper

            foreach ($token in 'test-token', 'invalid-token') {
                $healthInfo = New-Object Diagnostics.ProcessStartInfo
                $healthInfo.FileName = (Get-Command powershell.exe).Source
                $healthInfo.Arguments = "-NoProfile -File `"$fixtureHelper`" -Action Health"
                $healthInfo.UseShellExecute = $false
                $healthInfo.RedirectStandardOutput = $true
                $healthInfo.RedirectStandardError = $true
                $healthInfo.EnvironmentVariables['AGENT_URL'] = "http://127.0.0.1:$($started.port)"
                $healthInfo.EnvironmentVariables['EUGENE_PLEXUS_DEV_UI_PORT'] = "$($started.port)"
                $healthInfo.EnvironmentVariables['EUGENE_PLEXUS_DEV_TOKEN'] = $token
                $health = [Diagnostics.Process]::Start($healthInfo)
                try {
                    if (-not $health.WaitForExit(15000)) { throw 'Health check did not exit.' }
                    $expected = if ($token -eq 'test-token') { 0 } else { 1 }
                    $health.ExitCode | Should Be $expected
                    $health.StandardOutput.ReadToEnd() | Should Not Match $token
                }
                finally {
                    if (-not $health.HasExited) { $health.Kill(); $health.WaitForExit() }
                    $health.Dispose()
                }
            }

            Stop-OwnedTasks | Out-Null

            $launcher.WaitForExit(5000) | Should Be $true
            $parent.WaitForExit(5000) | Should Be $true
            $child.WaitForExit(5000) | Should Be $true
            $sentinel.HasExited | Should Be $false
            Test-Path (Join-Path $script:StateDirectory 'Ui.json') | Should Be $false
        }
        finally {
            $script:HelperPath = $originalHelperPath
            if (-not $launcher.HasExited) { & taskkill.exe /PID $launcher.Id /T /F | Out-Null }
            if (-not $sentinel.HasExited) { $sentinel.Kill(); $sentinel.WaitForExit() }
            $launcher.Dispose()
            $sentinel.Dispose()
        }
    }
}

Describe 'Shared task definitions' {
    It 'uses existing helper actions and task dependencies' {
        $tasks = Get-Content (Join-Path $PSScriptRoot '../.vscode/tasks.json') -Raw | ConvertFrom-Json
        foreach ($task in $tasks.tasks) {
            foreach ($dependency in $task.dependsOn) { $tasks.tasks.label -contains $dependency | Should Be $true }
            if ($task.type) {
                $task.type | Should Be 'process'
                $taskScript = $task.args | Where-Object { $_ -like '*${workspaceFolder}/scripts/*' }
                $taskScript | Should Not BeNullOrEmpty
                $taskScript -in '${workspaceFolder}/scripts/dev-tasks.ps1', '${workspaceFolder}/scripts/dev-seed.ps1' | Should Be $true
                Test-Path (Join-Path $PSScriptRoot ('../' + $taskScript.Replace('${workspaceFolder}/', ''))) | Should Be $true
                if ($taskScript -like '*dev-tasks.ps1') {
                    $task.args[-1] -in 'Agent', 'Ui', 'Stop', 'Health' | Should Be $true
                }
            }
            if ($task.isBackground) {
                $pattern = $task.problemMatcher.pattern
                $sample = [regex]::Match('C:/test/source.ts:12: error: test diagnostic', $pattern.regexp)
                $sample.Success | Should Be $true
                $sample.Groups[$pattern.file].Value | Should Be 'C:/test/source.ts'
                $sample.Groups[$pattern.message].Value | Should Be 'test diagnostic'
                $task.runOptions.instanceLimit | Should Be 1
            }
        }
    }
}
Describe 'Script encoding' {
    It 'keeps every helper script pure ASCII' {
        # Windows PowerShell 5.1 reads a .ps1 without a BOM as the system ANSI
        # codepage, not UTF-8. A single em dash inside a string literal is
        # enough to break the parse with errors that name the wrong line.
        # Adding a BOM would break other readers, so the rule is ASCII only.
        foreach ($name in 'dev-tasks.ps1', 'dev-seed.ps1', 'dev-common.ps1', 'dev-tasks.Tests.ps1') {
            $bytes = [IO.File]::ReadAllBytes((Join-Path $PSScriptRoot $name))
            $high = @($bytes | Where-Object { $_ -gt 127 })
            if ($high.Count -ne 0) { throw "$name contains $($high.Count) non-ASCII byte(s)" }
            $high.Count | Should Be 0
        }
    }

    It 'parses every helper script with the Windows PowerShell parser' {
        foreach ($name in 'dev-tasks.ps1', 'dev-seed.ps1', 'dev-common.ps1') {
            $errors = $null
            [void][Management.Automation.PSParser]::Tokenize(
                (Get-Content (Join-Path $PSScriptRoot $name) -Raw), [ref]$errors)
            if ($errors -and $errors.Count) { throw "$name : $($errors[0].Message)" }
            $errors.Count | Should Be 0
        }
    }
}

Describe 'Dev install seeding' {
    It 'prefers an explicit path, then the environment, then the polyrepo default' {
        Get-DevInstallPath 'C:\poly' 'C:\explicit' | Should Be 'C:\explicit'
        $env:EUGENE_PLEXUS_DEV_INSTALL = 'C:\from-env'
        try { Get-DevInstallPath 'C:\poly' | Should Be 'C:\from-env' }
        finally { Remove-Item Env:\EUGENE_PLEXUS_DEV_INSTALL }
        Get-DevInstallPath 'C:\poly' | Should Be 'C:\poly\.dev-install'
    }

    Context 'writing the install directory' {
        BeforeEach {
            $script:Install = Join-Path $env:TEMP ([guid]::NewGuid().ToString())
            Mock Write-Host {}
        }
        AfterEach {
            if (Test-Path -LiteralPath $script:Install) { Remove-Item -LiteralPath $script:Install -Recurse -Force }
        }

        It 'writes one config per spawned component and roots the library at the model directory' {
            Write-DevInstall $script:Install 'D:\models\pool\Qwen3-1.7B-Q8_0.gguf'
            foreach ($name in 'control.yaml', 'gateway.yaml', 'library.yaml') {
                Test-Path (Join-Path $script:Install $name) | Should Be $true
            }
            # -like, not -match: a Windows path is not a regex.
            (Get-Content (Join-Path $script:Install 'library.yaml') -Raw) -like '*D:\models\pool*' | Should Be $true
            # No agent.yaml: the topology is declared over HTTP, so a stale
            # one on disk can never be what the agent silently loads.
            Test-Path (Join-Path $script:Install 'agent.yaml') | Should Be $false
        }

        It 'writes UTF-8 without a byte order mark' {
            Write-DevInstall $script:Install 'D:\models\pool\model.gguf'
            $bytes = [IO.File]::ReadAllBytes((Join-Path $script:Install 'gateway.yaml'))
            ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) | Should Be $false
        }

        It 'omits modelRoots entirely when there is no model' {
            Write-DevInstall $script:Install ''
            (Get-Content (Join-Path $script:Install 'library.yaml') -Raw) -match 'modelRoots' | Should Be $false
        }
    }

    Context 'waiting for the agent' {
        BeforeEach { Mock Write-Host {} }

        It 'returns immediately and says nothing when the agent is already up' {
            Mock Wait-Healthy { $true }
            Wait-ForAgent 'http://agent' | Should Be $true
            Assert-MockCalled Write-Host -Times 0 -Exactly -Scope It
        }

        It 'waits, explains what it is waiting for, and succeeds when the agent appears' {
            $script:Probe = 0
            Mock Wait-Healthy { $script:Probe++; return ($script:Probe -gt 1) }
            Wait-ForAgent 'http://agent' 5 | Should Be $true
            Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*Eugene Plexus: Start*' }
        }

        It 'gives up rather than hanging forever' {
            Mock Wait-Healthy { $false }
            Wait-ForAgent 'http://agent' 1 | Should Be $false
        }
    }

    Context 'obtaining an operator session' {
        BeforeEach { Mock Write-Host {} }

        It 'initializes a fresh install' {
            Mock Invoke-Api { @{ Code = 200; Body = @{ sessionToken = 'fresh' } } }
            $session = Get-OperatorToken 'http://agent' (ConvertTo-SecureString 'pass' -AsPlainText -Force)
            $session.Token | Should Be 'fresh'
            $session.Fresh | Should Be $true
        }

        It 'logs in when the install is already initialized' {
            Mock Invoke-Api {
                param($Method, $Url)
                if ($Url -like '*initialize') { return @{ Code = 409; Body = $null } }
                return @{ Code = 200; Body = @{ sessionToken = 'returning' } }
            }
            $session = Get-OperatorToken 'http://agent' (ConvertTo-SecureString 'pass' -AsPlainText -Force)
            $session.Token | Should Be 'returning'
            $session.Fresh | Should Be $false
        }

        It 'throws a directed error when the passphrase does not match' {
            Mock Invoke-Api { @{ Code = 401; Body = $null } }
            { Get-OperatorToken 'http://agent' (ConvertTo-SecureString 'wrong' -AsPlainText -Force) } | Should Throw
        }
    }

    Context 'declaring topology and runtimes' {
        BeforeEach { Mock Write-Host {} }

        It 'treats an already-declared component as success' {
            Mock Invoke-Api { @{ Code = 409; Body = $null } }
            Add-DevComponent 'http://agent' 't' @{ name = 'gateway'; kind = 'gateway'; url = 'http://x' } | Should Be $true
        }

        It 'fails a component the agent rejects' {
            Mock Invoke-Api { @{ Code = 400; Body = @{ detail = 'bad kind' } } }
            Add-DevComponent 'http://agent' 't' @{ name = 'gateway'; kind = 'gateway'; url = 'http://x' } | Should Be $false
        }

        It 'fails a runtime that admission refuses' {
            Mock Invoke-Api { @{ Code = 409; Body = @{ detail = 'will not fit' } } }
            # 409 on a runtime means the name is taken, which is success;
            # a refusal arrives as 400 with the arithmetic.
            Add-DevRuntime 'http://agent' 't' @{ name = 'r' } | Should Be $true
            Mock Invoke-Api { @{ Code = 400; Body = @{ detail = '36.0 GiB required, 26.5 GiB free' } } }
            Add-DevRuntime 'http://agent' 't' @{ name = 'r' } | Should Be $false
        }

        It 'warns when a launch produced no companion driver' {
            Mock Invoke-Api { @{ Code = 201; Body = @{ status = 'starting'; driver = $null } } }
            Add-DevRuntime 'http://agent' 't' @{ name = 'r' } | Should Be $true
            Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*not be routable*' }
        }
    }
}
