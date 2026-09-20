# Exercise the real read-only installer prefix. Stop before the first install
# write; mock OS discovery, never register a task or start an elevated process.
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'install.ps1'))
$preflight = [scriptblock]::Create($source.Substring(0, $source.IndexOf('# --- 1. uv ')))
# Import only helper definitions for tests that launch harmless child scripts.
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$null, [ref]$null)
$ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Say', 'Die', 'Invoke-Native', 'Invoke-ElevatedInstaller', 'Set-ServiceBootstrap') }, $false) |
    ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }

Describe 'Installer failure reporting' {
    BeforeEach {
        Mock Write-Host {}
        # Execute the actual generated wrapper, without UAC or install actions.
        Mock Start-Process {
            param($FilePath, $ArgumentList)
            $start = New-Object Diagnostics.ProcessStartInfo
            $start.FileName = $FilePath
            $start.Arguments = $ArgumentList -join ' '
            $start.UseShellExecute = $false
            $start.CreateNoWindow = $true
            $process = [Diagnostics.Process]::Start($start)
            if (-not $process.WaitForExit(20000)) { $process.Kill(); throw 'test child timed out' }
            [pscustomobject]@{ ExitCode = $process.ExitCode }
        }
    }

    It 'keeps native stderr and the failing exit code' {
        $probe = Join-Path $TestDrive 'native.ps1'
        [IO.File]::WriteAllText($probe, "[Console]::Error.WriteLine('native failure detail'); exit 7")
        { Invoke-Native powershell.exe @('-NoProfile', '-File', $probe) 'native command failed' } |
            Should Throw 'exit code 7'
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*native failure detail*' }
    }

    It 'gives the service its config and paths without waiting for a reboot' {
        $Prefix = 'C:\a service install'
        $Config = Join-Path $Prefix 'agent.yaml'
        $Port = 18779
        $ServiceName = 'EPTestOnly'
        Mock New-ItemProperty {}
        Set-ServiceBootstrap
        Assert-MockCalled New-ItemProperty -Times 1 -Exactly -Scope It -ParameterFilter {
            $LiteralPath -eq 'HKLM:\SYSTEM\CurrentControlSet\Services\EPTestOnly' -and
            $Name -eq 'Environment' -and $PropertyType -eq 'MultiString' -and
            $Value -contains 'EUGENE_PLEXUS_AGENT_CONFIG_FILE=C:\a service install\agent.yaml' -and
            $Value -contains 'EUGENE_PLEXUS_AGENT_BIND_PORT=18779' -and
            $Value -contains 'EUGENE_PLEXUS_AGENT_ENGINE_ROOT=C:\a service install\engines' -and
            $Value -contains 'EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS=C:\a service install\models'
        }
    }

    It 'reports the child exception and preserves its log after the child exits' {
        { Invoke-ElevatedInstaller -ScriptText "throw 'child failure detail'" -Parameters @{} -WorkDirectory $TestDrive } |
            Should Throw 'Log:'
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*child failure detail*' }
        $log = @(Get-ChildItem $TestDrive -Filter '*.log')
        $log.Count | Should Be 1
        [IO.File]::ReadAllText($log[0].FullName) | Should Match 'child failure detail'
        @(Get-ChildItem $TestDrive -Filter '*.clixml').Count | Should Be 0
        @(Get-ChildItem $TestDrive -Filter 'eugene-plexus-install-*.ps1').Count | Should Be 0
    }

    It 'forwards parameters without shell quoting or leaking their values in the log' {
        $output = Join-Path $TestDrive 'arguments.json'
        $text = @'
param([switch]$Migrate, [switch]$NoTray, [string]$Prefix, [string]$Token, [string]$Output)
@{ Migrate = $Migrate.IsPresent; NoTray = $NoTray.IsPresent; Prefix = $Prefix; Token = $Token } |
    ConvertTo-Json | Set-Content -LiteralPath $Output
'@
        $prefix = "C:\an apostrophe's path with spaces\"
        $token = 'only-for-parameter-test-$()'
        Invoke-ElevatedInstaller -ScriptText $text -Parameters @{
            Migrate = [switch]$true; NoTray = [switch]$false; Prefix = $prefix; Token = $token; Output = $output
        } -WorkDirectory $TestDrive
        $result = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
        $result.Migrate | Should Be $true
        $result.NoTray | Should Be $false
        $result.Prefix | Should Be $prefix
        $result.Token | Should Be $token
        Get-ChildItem $TestDrive -Filter '*.log' | ForEach-Object {
            [IO.File]::ReadAllText($_.FullName) | Should Not Match ([regex]::Escape($token))
        }
    }
}

Describe 'Windows installer migration preflight' {
    BeforeEach {
        $script:ExistingPrefix = Join-Path $TestDrive 'existing install'
        New-Item -ItemType Directory -Force -Path $script:ExistingPrefix | Out-Null
        [IO.File]::WriteAllText((Join-Path $script:ExistingPrefix 'agent.yaml'), 'firstRunComplete: true')
        $script:RequestedPrefix = Join-Path $TestDrive 'service install'
        Mock Get-CimInstance { $null }
        Mock Get-Service { $null }
        Mock Get-ScheduledTask {
            [pscustomobject]@{ Actions = @([pscustomobject]@{
                Execute = Join-Path $script:ExistingPrefix 'venv\Scripts\eugene-plexus-agent.exe'
            }) }
        }
        Mock Start-Process { throw 'TEST: elevation must not be reached' }
        Mock Write-Host {}
    }

    It 'explains the existing install before asking for elevation' {
        { & $preflight -Prefix $script:RequestedPrefix -NoElevate } |
            Should Throw 'refusing to build a second install'
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*-Migrate*' }
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*-NoService*' }
        Assert-MockCalled Start-Process -Times 0 -Exactly -Scope It
        Test-Path $script:RequestedPrefix | Should Be $false
    }

    It 'explains an in-place service conversion before asking for elevation' {
        { & $preflight -Prefix $script:ExistingPrefix -NoElevate } |
            Should Throw 'refusing to make this install a service'
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*PASSPHRASE ONCE*' }
        Assert-MockCalled Start-Process -Times 0 -Exactly -Scope It
    }

    It 'allows an ordinary update of the existing per-user install' {
        { & $preflight -Prefix $script:ExistingPrefix -NoService -NoElevate } | Should Not Throw
        Assert-MockCalled Start-Process -Times 0 -Exactly -Scope It
    }

    It 'keeps detection read-only and available without elevation' {
        { & $preflight -Prefix $script:RequestedPrefix -Detect } | Should Not Throw
        Assert-MockCalled Start-Process -Times 0 -Exactly -Scope It
        Test-Path $script:RequestedPrefix | Should Be $false
    }
}
