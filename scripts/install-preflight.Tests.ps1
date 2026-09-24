# Exercise the real read-only installer prefix. Stop before the first install
# write; mock OS discovery, never register a task or start an elevated process.
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'install.ps1'))
$preflight = [scriptblock]::Create($source.Substring(0, $source.IndexOf('# --- 1. uv ')))
# Import only helper definitions for tests that launch harmless child scripts.
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$null, [ref]$null)
$ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Say', 'Warn', 'Die', 'Invoke-Native', 'Invoke-ElevatedInstaller', 'Set-ServiceBootstrap', 'Copy-EngineBuilds', 'Protect-InstallDirectory') }, $false) |
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

Describe 'Managed engine migration' {
    It 'recovers external builds on retry without replacing existing builds or the source' {
        $Prefix = Join-Path $TestDrive 'service'
        $legacy = Join-Path $TestDrive 'legacy engines'
        $old = Join-Path $legacy 'llama_cpp\b1'
        New-Item -ItemType Directory -Force -Path $old | Out-Null
        [IO.File]::WriteAllText((Join-Path $old 'install.json'), '{"binary":"llama-server.exe"}')
        [IO.File]::WriteAllText((Join-Path $old 'llama-server.exe'), 'original')
        Copy-EngineBuilds -Source $legacy
        $copied = Join-Path $Prefix 'engines\llama_cpp\b1\llama-server.exe'
        [IO.File]::ReadAllText($copied) | Should Be 'original'
        [IO.File]::WriteAllText($copied, 'keep destination')
        Copy-EngineBuilds -Source $legacy
        [IO.File]::ReadAllText($copied) | Should Be 'keep destination'
        [IO.File]::ReadAllText((Join-Path $old 'llama-server.exe')) | Should Be 'original'
        @(Get-ChildItem (Join-Path $Prefix 'engines\llama_cpp') -Directory).Count | Should Be 1
    }

    It 'does not publish incomplete legacy builds' {
        $Prefix = Join-Path $TestDrive 'empty service'
        $legacy = Join-Path $TestDrive 'incomplete engines'
        New-Item -ItemType Directory -Force -Path (Join-Path $legacy 'llama_cpp\b2') | Out-Null
        Copy-EngineBuilds -Source $legacy
        Test-Path (Join-Path $Prefix 'engines\llama_cpp\b2') | Should Be $false
    }

    It 'keeps a failed copy outside every discoverable version directory' {
        $Prefix = Join-Path $TestDrive 'interrupted service'
        $legacy = Join-Path $TestDrive 'complete source'
        $build = Join-Path $legacy 'llama_cpp\b3'
        New-Item -ItemType Directory -Force -Path $build | Out-Null
        [IO.File]::WriteAllText((Join-Path $build 'install.json'), '{}')
        Mock Copy-Item {
            param($LiteralPath, $Destination)
            # A directory with metadata and a binary but missing DLLs would
            # already look installed if staged among the engine's versions.
            New-Item -ItemType Directory -Force -Path $Destination | Out-Null
            [IO.File]::WriteAllText((Join-Path $Destination 'install.json'), '{}')
            [IO.File]::WriteAllText((Join-Path $Destination 'llama-server.exe'), 'partial')
            throw 'simulated interrupted copy'
        }
        { Copy-EngineBuilds -Source $legacy } | Should Throw 'simulated interrupted copy'
        @(Get-ChildItem -LiteralPath (Join-Path $Prefix 'engines\llama_cpp') -Directory).Count | Should Be 0
        Test-Path (Join-Path $build 'install.json') | Should Be $true
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

# 2026-09-24: `%ProgramData%` hands every folder under it Users read and
# Users add, so on a service install every local account could read the
# install's signing key and plant code the service runs. These run on
# REAL folders under `%ProgramData%`, unelevated, so the inherited grants
# are the ones a real install gets -- and the first case asserts they
# are there before anything else asserts they are gone.
Describe 'The install directory is private' {
    $SYSTEM = 'S-1-5-18'
    $ADMINS = 'S-1-5-32-544'
    $USERS = 'S-1-5-32-545'
    $Rights = [Security.AccessControl.FileSystemRights]
    $Me = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
    # Elevated, Administrators can read anything and the "another account
    # cannot read it" assertions would be about this shell, not the ACL.
    $Elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)

    function Get-Grants([string]$Path) {
        (Get-Acl -LiteralPath $Path).GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) |
            Where-Object { $_.AccessControlType -eq 'Allow' } |
            ForEach-Object {
                [pscustomobject]@{
                    Sid         = $_.IdentityReference.Value
                    Rights      = $_.FileSystemRights
                    Inheritance = [string]$_.InheritanceFlags
                    Inherited   = $_.IsInherited
                }
            }
    }
    # Joined, because Pester 3.4's `Should Be` against an array passes when
    # every actual item is IN the expected set -- a subset check that
    # would wave through an ACL missing an account it should have.
    function Get-Sids([string]$Path) { (Get-Grants $Path | ForEach-Object Sid | Sort-Object -Unique) -join ',' }
    function Join-Sids { ($args | Sort-Object -Unique) -join ',' }
    function Test-Writable([string]$File) {
        try { [IO.File]::WriteAllText($File, 'x'); return $true } catch { return $false }
    }

    BeforeEach {
        Mock Write-Host {}
        $script:Root = Join-Path $env:ProgramData ('EP-acl-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Path $script:Root | Out-Null
        foreach ($d in 'venv', 'pythons', 'models', 'engines', 'logs') {
            New-Item -ItemType Directory -Path (Join-Path $script:Root $d) | Out-Null
        }
        [IO.File]::WriteAllText((Join-Path $script:Root 'node.yaml'), "signingKey: not-a-real-key`n")
        [IO.File]::WriteAllText((Join-Path $script:Root 'venv\site.py'), "# python`n")
    }
    AfterEach {
        # This shell made everything here and an owner may always rewrite
        # a DACL: take full control back, then delete.
        & icacls.exe $script:Root /grant "*$($Me):(OI)(CI)F" /T /C /Q | Out-Null
        Remove-Item -LiteralPath $script:Root -Recurse -Force
    }

    It 'starts from what %ProgramData% hands down: Users may read and may add' {
        $usersAces = @(Get-Grants $script:Root | Where-Object Sid -eq $USERS)
        @($usersAces | Where-Object { $_.Inheritance -match 'ObjectInherit' -and ($_.Rights -band $Rights::ReadData) }).Count |
            Should BeGreaterThan 0
        @($usersAces | Where-Object { $_.Rights -band $Rights::CreateFiles }).Count | Should BeGreaterThan 0
        # CREATOR OWNER hands the file's maker full control too: this shell.
        Get-Sids (Join-Path $script:Root 'node.yaml') | Should Be (Join-Sids $Me $USERS $SYSTEM $ADMINS)
    }

    It 'a service install: nobody else reads the secrets or adds a file, and three doors stay open' {
        Protect-InstallDirectory -Path $script:Root -Service -PersonSid $Me | Should Be $true

        (Get-Acl -LiteralPath $script:Root).AreAccessRulesProtected | Should Be $true
        $root = @(Get-Grants $script:Root)
        $root.Count | Should Be 3
        @($root | Where-Object { $_.Sid -eq $USERS -and $_.Inheritance -eq 'None' }).Count | Should Be 1
        @($root | Where-Object { $_.Sid -eq $USERS -and ($_.Rights -band $Rights::CreateFiles) }).Count | Should Be 0

        $node = Join-Path $script:Root 'node.yaml'
        Get-Sids $node | Should Be (Join-Sids $SYSTEM $ADMINS)
        # A non-elevated run of the installer still finds this install.
        Test-Path -LiteralPath $node | Should Be $true
        if (-not $Elevated) {
            { [IO.File]::ReadAllText($node) } | Should Throw
            Test-Writable (Join-Path $script:Root 'planted.txt') | Should Be $false
            Test-Writable (Join-Path $script:Root 'venv\evil.pth') | Should Be $false
        }
        # The tray icon runs from these.
        [IO.File]::ReadAllText((Join-Path $script:Root 'venv\site.py')) | Should Be "# python`n"
        foreach ($door in 'venv', 'pythons') {
            @(Get-Grants (Join-Path $script:Root $door) | Where-Object { $_.Sid -eq $USERS -and -not $_.Inherited }).Count |
                Should Be 1
        }
        # The person's model folder is theirs to fill.
        Test-Writable (Join-Path $script:Root 'models\mine.gguf') | Should Be $true
        foreach ($closed in 'engines', 'logs') {
            Get-Sids (Join-Path $script:Root $closed) | Should Be (Join-Sids $SYSTEM $ADMINS)
        }
    }

    It 'a per-user install: the person keeps everything and a stranger grant on the folder goes' {
        # A grant made on the folder itself, the way the profile's
        # sandbox group arrived: explicit ACEs are removed too, not only
        # inherited ones.
        & icacls.exe $script:Root /grant "*$($USERS):(OI)(CI)M" /Q | Out-Null
        Protect-InstallDirectory -Path $script:Root -PersonSid $Me | Should Be $true

        (Get-Acl -LiteralPath $script:Root).AreAccessRulesProtected | Should Be $true
        Get-Sids $script:Root | Should Be (Join-Sids $Me $SYSTEM $ADMINS)
        Get-Sids (Join-Path $script:Root 'node.yaml') | Should Be (Join-Sids $Me $SYSTEM $ADMINS)
        [IO.File]::WriteAllText((Join-Path $script:Root 'agent.yaml'), "later: true`n")
        Get-Sids (Join-Path $script:Root 'agent.yaml') | Should Be (Join-Sids $Me $SYSTEM $ADMINS)
        [IO.File]::ReadAllText((Join-Path $script:Root 'node.yaml')) | Should Match 'signingKey'
    }

    It 'running it again adds nothing' {
        Protect-InstallDirectory -Path $script:Root -Service -PersonSid $Me | Should Be $true
        Protect-InstallDirectory -Path $script:Root -Service -PersonSid $Me | Should Be $true
        @(Get-Grants $script:Root).Count | Should Be 3
        @(Get-Grants (Join-Path $script:Root 'venv') | Where-Object { $_.Sid -eq $USERS -and -not $_.Inherited }).Count |
            Should Be 1
    }

    # The cases above call the function; this is what says the installer
    # does. Before the venv, so nothing is ever written unprotected, and
    # after the service block, which is what creates models\.
    It 'the installer calls it before anything is written and again once the doors exist' {
        $calls = @([regex]::Matches($source, '(?m)^(?:if \()?Protect-InstallDirectory -Path \$Prefix -Service:\$WantsService'))
        $calls.Count | Should Be 2
        $calls[0].Index | Should BeGreaterThan $source.IndexOf('# --- 1. uv ')
        $calls[0].Index | Should BeLessThan $source.IndexOf('# --- 2. venv')
        $calls[1].Index | Should BeGreaterThan $source.IndexOf('# --- 5. autostart')
        $calls[1].Index | Should BeLessThan $source.IndexOf('# --- 5b. the tray icon')
    }

    It 'a folder it cannot protect warns and does not stop the install' {
        Protect-InstallDirectory -Path (Join-Path $script:Root 'no such folder') -Service | Should Be $false
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*could not make*private*' }
    }
}
