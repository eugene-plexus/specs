# Exercise the real read-only installer prefix. Stop before the first install
# write; mock OS discovery, never register a task or start an elevated process.
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'install.ps1'))
$preflight = [scriptblock]::Create($source.Substring(0, $source.IndexOf('# --- 1. uv ')))

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
