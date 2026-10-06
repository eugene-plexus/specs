# Exercise the real read-only installer prefix. Stop before the first install
# write; mock OS discovery, never register a task or start an elevated process.
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'install.ps1'))
$preflight = [scriptblock]::Create($source.Substring(0, $source.IndexOf('# --- 1. uv ')))
# Import only helper definitions for tests that launch harmless child scripts.
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$null, [ref]$null)
$ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Say', 'Warn', 'Die', 'Invoke-Native', 'Show-InstallerLog', 'Invoke-ElevatedInstaller', 'Set-ServiceBootstrap', 'Copy-EngineBuilds', 'Protect-InstallDirectory',
        'Stop-ProcessUnder', 'Test-LooksLikeInstall', 'Test-UnderProgramData', 'Get-EugeneInstall',
        'Remove-AgentServiceRegistration', 'Get-AgentServiceEnvironment', 'Get-InstalledPort', 'Register-AgentServiceFrom',
        'Suspend-EugeneInstall', 'Restore-EugeneInstall', 'Show-SetAsideNote', 'Assert-UpgradeableInstall',
        'Get-ServiceConversionSource', 'Get-AutostartExecutable', 'Get-AgentService', 'Get-AgentTask',
        'Remove-Autostart', 'Remove-StartMenuShortcut', 'Test-RunsFromThisInstall', 'Get-OtherInstall',
        'Grant-ServiceControl', 'Move-Folder', 'Get-ErrorText',
        'Get-NativeSystemDirectory', 'Test-VcRuntime', 'Install-VcRuntime',
        'Get-DllVersion', 'Get-VcRuntimeVersion', 'Get-UvVersion', 'Install-Uv', 'Write-RemovalBundle') }, $false) |
    ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }

Describe 'Installer failure reporting' {
    BeforeEach {
        Mock Write-Host {}
        # Execute the actual generated wrapper, without UAC or install actions.
        # 60 s, not 20: a busy windows-latest runner once took longer than
        # 20 s to start and run the child (specs #14).
        Mock Start-Process {
            param($FilePath, $ArgumentList)
            $start = New-Object Diagnostics.ProcessStartInfo
            $start.FileName = $FilePath
            $start.Arguments = $ArgumentList -join ' '
            $start.UseShellExecute = $false
            $start.CreateNoWindow = $true
            $process = [Diagnostics.Process]::Start($start)
            if (-not $process.WaitForExit(60000)) { $process.Kill(); throw 'test child timed out' }
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
        # CREATOR OWNER hands the file's OWNER full control too. That is
        # this shell's account unelevated, and Administrators elevated --
        # an elevated admin token's default owner -- which is what CI is.
        $node = Join-Path $script:Root 'node.yaml'
        $owner = (Get-Acl -LiteralPath $node).GetOwner([Security.Principal.SecurityIdentifier]).Value
        if (-not $Elevated) { $owner | Should Be $Me }
        Get-Sids $node | Should Be (Join-Sids $owner $USERS $SYSTEM $ADMINS)
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
        # Amended 2026-09-27: both calls are skipped on -Update, because a
        # run as SYSTEM would grant the install's folder to SYSTEM instead of
        # the person. The guard is asserted, not only allowed.
        $calls = @([regex]::Matches($source, '(?m)^if \(.*Protect-InstallDirectory -Path \$Prefix -Service:\$WantsService.*$'))
        $calls.Count | Should Be 2
        @($calls | Where-Object { $_.Value -notmatch '-not \$Update' }).Count | Should Be 0
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

Describe 'A join takes over whatever is here' {
    # 2026-09-26: getting Amish_Station into a new install took an
    # afternoon of refusals. `-Join` now finds every install on the
    # machine, sets each aside, installs fresh and joins -- and a failure
    # before the join succeeds puts every one of them back.
    #
    # **Nothing here may touch this machine's own install.** Discovery
    # reads the environment and the service manager, and on a developer's
    # box both name a live install. So the default locations are pointed
    # at the test drive, the config variable has a name of its own, every
    # service and task cmdlet is mocked, and a move, delete or process stop
    # outside the temp folder throws.
    $joinBlock = $ast.Find({ param($node)
            $node -is [System.Management.Automation.Language.IfStatementAst] -and
            $node.Clauses[0].Item1.Extent.Text -eq '$Join' }, $true)
    $runJoin = [scriptblock]::Create($joinBlock.Extent.Text)

    BeforeEach {
        # TestDrive is shared by every test in a Describe, so each test gets
        # a root of its own and cannot see another's folders.
        $script:Root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:SavedEnv = @{}
        foreach ($name in 'ProgramData', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE') {
            $script:SavedEnv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            $dir = Join-Path $script:Root $name
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            [Environment]::SetEnvironmentVariable($name, $dir, 'Process')
        }
        $script:ConfigVariable = 'EUGENE_PLEXUS_TEST_ONLY_CONFIG_FILE'
        $script:BindHostVariable = 'EUGENE_PLEXUS_TEST_ONLY_BIND_HOST'
        $script:EngineRootVariable = 'EUGENE_PLEXUS_TEST_ONLY_ENGINE_ROOT'
        $script:InstallVariables = @($script:ConfigVariable, $script:BindHostVariable, $script:EngineRootVariable)
        $script:ServiceName = 'EPTestOnlyService'
        $script:TaskName = 'EPTestOnlyTask'
        $script:TrayTaskName = 'EPTestOnlyTray'
        $script:IsElevated = $true
        $script:WantsService = $true
        $script:InstallerUrl = 'https://example.invalid/install.ps1'
        $temp = [IO.Path]::GetTempPath()
        Mock Move-Folder { throw "TEST: refused to move $From" } -ParameterFilter {
            -not ("$From".StartsWith($temp, 'OrdinalIgnoreCase') -and
                "$To".StartsWith($temp, 'OrdinalIgnoreCase')) }
        Mock Remove-Item { throw "TEST: refused to remove $LiteralPath" } -ParameterFilter {
            -not "$LiteralPath".StartsWith($temp, 'OrdinalIgnoreCase') }
        Mock Stop-Process { throw 'TEST: no process may be stopped' }
        Mock Get-CimInstance { $null }
        Mock Get-AutostartExecutable { $null }
        Mock Get-AgentService { $null }
        Mock Get-ScheduledTask { $null }
        Mock Stop-Service {}
        Mock Start-Service {}
        Mock Remove-AgentServiceRegistration {}
        Mock Register-AgentServiceFrom {}
        Mock Get-AgentServiceEnvironment { @('EUGENE_PLEXUS_AGENT_BIND_PORT=18279') }
        Mock Stop-ScheduledTask {}
        Mock Unregister-ScheduledTask {}
        Mock Register-ScheduledTask {}
        Mock Start-ScheduledTask {}
        Mock Export-ScheduledTask { '<Task>saved</Task>' }
        Mock Grant-ServiceControl { $true }
        Mock Write-Host {}
    }

    AfterEach {
        foreach ($name in $script:SavedEnv.Keys) {
            [Environment]::SetEnvironmentVariable($name, $script:SavedEnv[$name], 'Process')
        }
        [Environment]::SetEnvironmentVariable('EUGENE_PLEXUS_TEST_ONLY_CONFIG_FILE', $null, 'User')
    }

    function New-FakeInstall {
        param([string]$Path, [string]$Marker = 'agent.yaml', [string]$Content = 'firstRunComplete: true')
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
        if ($Marker -eq 'venv') { New-Item -ItemType Directory -Force -Path (Join-Path $Path 'venv') | Out-Null }
        else { [IO.File]::WriteAllText((Join-Path $Path $Marker), $Content) }
        return $Path
    }

    It 'never sees a live install through the real config variable' {
        # The guard every case below relies on: if this fails, the suite
        # was about to read the developer's own install.
        Get-EugeneInstall | Should BeNullOrEmpty
        $env:ProgramData | Should Match ([regex]::Escape($Root))
    }

    It 'finds the autostart''s install first, then the variable''s, the target and both defaults' {
        $service = New-FakeInstall (Join-Path $Root 'svc') 'venv'
        Mock Get-AutostartExecutable { Join-Path $Root 'svc\venv\Scripts\eugene-plexus-agent.exe' }
        $pointed = New-FakeInstall (Join-Path $Root 'pointed') 'node.yaml'
        [Environment]::SetEnvironmentVariable($ConfigVariable, (Join-Path $pointed 'agent.yaml'), 'User')
        $Prefix = Join-Path $Root 'target'
        New-Item -ItemType Directory -Force -Path (Join-Path $Prefix 'logs') | Out-Null
        $machine = New-FakeInstall (Join-Path $env:ProgramData 'EugenePlexus')
        $perUser = New-FakeInstall (Join-Path $env:LOCALAPPDATA 'EugenePlexus') 'venv'

        $found = @(Get-EugeneInstall)

        $found.Count | Should Be 5
        $found[0] | Should Be $service
        $found[1] | Should Be $pointed
        $found[2] | Should Be $Prefix
        ($found -contains $machine) | Should Be $true
        ($found -contains $perUser) | Should Be $true
    }

    It 'passes over a folder that holds no install, and an empty target' {
        $Prefix = Join-Path $Root 'empty target'
        New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
        $other = Join-Path $env:ProgramData 'EugenePlexus'
        New-Item -ItemType Directory -Force -Path $other | Out-Null
        [IO.File]::WriteAllText((Join-Path $other 'notes.txt'), 'not an install')
        @(Get-EugeneInstall).Count | Should Be 0
    }

    It 'sets each install aside, deletes nothing, and puts each back when the join fails' {
        $Prefix = New-FakeInstall (Join-Path $env:ProgramData 'EugenePlexus') 'agent.yaml' 'the old install'
        $perUser = New-FakeInstall (Join-Path $env:LOCALAPPDATA 'EugenePlexus') 'node.yaml' 'signingKey: old'

        $record = Suspend-EugeneInstall -Installs @($Prefix, $perUser)

        Test-Path $Prefix | Should Be $false
        Test-Path $perUser | Should Be $false
        $aside = @($record.Moved | ForEach-Object { $_.To })
        $aside.Count | Should Be 2
        [IO.File]::ReadAllText((Join-Path $aside[0] 'agent.yaml')) | Should Be 'the old install'
        $aside[0] | Should Match '\.replaced-\d{14}$'

        # The fresh install the run went on to make, then a refused join.
        New-Item -ItemType Directory -Force -Path (Join-Path $Prefix 'venv') | Out-Null
        [IO.File]::WriteAllText((Join-Path $Prefix 'fresh.txt'), 'new')
        Restore-EugeneInstall $record | Should Be $true

        [IO.File]::ReadAllText((Join-Path $Prefix 'agent.yaml')) | Should Be 'the old install'
        Test-Path (Join-Path $Prefix 'fresh.txt') | Should Be $false
        [IO.File]::ReadAllText((Join-Path $perUser 'node.yaml')) | Should Be 'signingKey: old'
        @(Get-ChildItem $env:ProgramData, $env:LOCALAPPDATA -Filter '*.replaced-*').Count | Should Be 0
    }

    It 'leaves nothing behind on a machine that had no install' {
        $Prefix = Join-Path $env:ProgramData 'EugenePlexus'
        $record = Suspend-EugeneInstall -Installs @()
        New-Item -ItemType Directory -Force -Path (Join-Path $Prefix 'venv') | Out-Null
        Restore-EugeneInstall $record | Out-Null
        Test-Path $Prefix | Should Be $false
    }

    It 'registers the service again from the old install and starts it, when it was running' {
        $Prefix = New-FakeInstall (Join-Path $env:ProgramData 'EugenePlexus') 'venv'
        Mock Get-AgentService { [pscustomobject]@{ Status = 'Running' } }
        Mock Get-AutostartExecutable { Join-Path $env:ProgramData 'EugenePlexus\venv\Scripts\eugene-plexus-agent.exe' }

        $record = Suspend-EugeneInstall -Installs @($Prefix)
        Assert-MockCalled Stop-Service -Scope It -Times 1
        Assert-MockCalled Remove-AgentServiceRegistration -Scope It -Times 1

        Mock Get-AutostartExecutable { $null }
        Restore-EugeneInstall $record | Should Be $true
        Assert-MockCalled Register-AgentServiceFrom -Scope It -Times 1 -Exactly -ParameterFilter {
            $ServicePrefix -eq $Prefix -and $Environment -contains 'EUGENE_PLEXUS_AGENT_BIND_PORT=18279' }
        Assert-MockCalled Start-Service -Scope It -Times 1 -Exactly
    }

    It 'registers a stopped service again without starting it' {
        $Prefix = New-FakeInstall (Join-Path $env:ProgramData 'EugenePlexus') 'venv'
        Mock Get-AgentService { [pscustomobject]@{ Status = 'Stopped' } }
        Mock Get-AutostartExecutable { Join-Path $env:ProgramData 'EugenePlexus\venv\Scripts\eugene-plexus-agent.exe' }
        $record = Suspend-EugeneInstall -Installs @($Prefix)
        Mock Get-AutostartExecutable { $null }
        Restore-EugeneInstall $record | Out-Null
        Assert-MockCalled Register-AgentServiceFrom -Scope It -Times 1 -Exactly
        Assert-MockCalled Start-Service -Scope It -Times 0 -Exactly
    }

    It 'puts a per-user install''s task and the tray icon back from their own definitions' {
        $Prefix = New-FakeInstall (Join-Path $env:LOCALAPPDATA 'EugenePlexus') 'venv'
        Mock Get-ScheduledTask { [pscustomobject]@{ State = 'Running' } }
        $record = Suspend-EugeneInstall -Installs @($Prefix)
        Assert-MockCalled Unregister-ScheduledTask -Scope It -Times 2 -Exactly
        Restore-EugeneInstall $record | Out-Null
        Assert-MockCalled Register-ScheduledTask -Scope It -Times 2 -Exactly -ParameterFilter { $Xml -eq '<Task>saved</Task>' }
        Assert-MockCalled Start-ScheduledTask -Scope It -Times 2 -Exactly
    }

    It 'clears the install''s variables and puts them back' {
        $Prefix = New-FakeInstall (Join-Path $env:LOCALAPPDATA 'EugenePlexus')
        [Environment]::SetEnvironmentVariable($ConfigVariable, (Join-Path $Prefix 'agent.yaml'), 'User')
        $record = Suspend-EugeneInstall -Installs @($Prefix)
        [Environment]::GetEnvironmentVariable($ConfigVariable, 'User') | Should BeNullOrEmpty
        Restore-EugeneInstall $record | Out-Null
        [Environment]::GetEnvironmentVariable($ConfigVariable, 'User') | Should Be (Join-Path $Prefix 'agent.yaml')
    }

    It 'puts the Start menu entry back' {
        $Prefix = New-FakeInstall (Join-Path $env:LOCALAPPDATA 'EugenePlexus')
        $programs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
        New-Item -ItemType Directory -Force -Path $programs | Out-Null
        $link = Join-Path $programs 'Eugene Plexus.lnk'
        [IO.File]::WriteAllText($link, 'shortcut')
        $record = Suspend-EugeneInstall -Installs @($Prefix)
        Test-Path $link | Should Be $false
        Restore-EugeneInstall $record | Out-Null
        [IO.File]::ReadAllText($link) | Should Be 'shortcut'
    }

    It 'stops what runs from each install, its pythons and engines included' {
        $Prefix = New-FakeInstall (Join-Path $env:ProgramData 'EugenePlexus')
        $script:Stopped = @()
        Mock Get-CimInstance {
            if (@($script:Stopped).Count -gt 0) { return $null }
            @(
                [pscustomobject]@{ Name = 'python.exe'; ProcessId = 101; ExecutablePath = Join-Path $env:ProgramData 'EugenePlexus\pythons\cpython-3.12\python.exe' },
                [pscustomobject]@{ Name = 'llama-server.exe'; ProcessId = 102; ExecutablePath = Join-Path $env:USERPROFILE '.eugene-plexus\engines\llama_cpp\b1\llama-server.exe' },
                [pscustomobject]@{ Name = 'python.exe'; ProcessId = 103; ExecutablePath = 'C:\Somebody Else\python.exe' }
            )
        }
        Mock Stop-Process { $script:Stopped += $Id }
        Suspend-EugeneInstall -Installs @($Prefix) | Out-Null
        ($script:Stopped | Sort-Object) -join ',' | Should Be '101,102'
    }

    It 'puts back what it moved when a folder cannot be moved, and says why' {
        $first = New-FakeInstall (Join-Path $env:ProgramData 'EugenePlexus')
        $second = New-FakeInstall (Join-Path $env:LOCALAPPDATA 'EugenePlexus')
        $Prefix = $first
        Mock Start-Sleep {}
        $held = [IO.File]::Open((Join-Path $second 'agent.yaml'), 'Open', 'Read', 'None')
        try {
            { Suspend-EugeneInstall -Installs @($first, $second) } | Should Throw 'could not move'
        }
        finally { $held.Dispose() }
        [IO.File]::ReadAllText((Join-Path $first 'agent.yaml')) | Should Be 'firstRunComplete: true'
        Test-Path $second | Should Be $true
        @(Get-ChildItem $env:ProgramData, $env:LOCALAPPDATA -Filter '*.replaced-*').Count | Should Be 0
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*back as it was*' }
    }

    It 'refuses an unelevated join that meets a service install, before touching it' {
        $IsElevated = $false
        $Prefix = New-FakeInstall (Join-Path $env:ProgramData 'EugenePlexus')
        { Suspend-EugeneInstall -Installs @($Prefix) } | Should Throw 'needs Administrator'
        Test-Path (Join-Path $Prefix 'agent.yaml') | Should Be $true
        Assert-MockCalled Stop-Service -Scope It -Times 0 -Exactly
    }

    It 'says to make a NEW token when the root refused this one, and restores first' {
        $Join = 'http://192.168.16.252:8283'; $Token = 't'; $Config = Join-Path $Root 'agent.yaml'
        $AgentEx = Join-Path $Root 'agent-stub.ps1'
        [IO.File]::WriteAllText($AgentEx, 'exit 3')
        $SetAside = [pscustomobject]@{ Moved = @(); Restored = $false }
        Mock Restore-EugeneInstall { $true }
        $threw = $null
        try { . $runJoin } catch { $threw = $_.Exception.Message }
        $threw | Should Match 'refused the join token'
        $threw | Should Match 'Make a new one on its Nodes page'
        $threw | Should Match 'back as it was'
        $threw | Should Not Match 'again'
        Assert-MockCalled Restore-EugeneInstall -Scope It -Times 1 -Exactly
        $lines = @($threw -split "`n")
        ('error: ' + $lines[0]).Length | Should BeLessThan 81
        @($lines | Select-Object -Skip 1 | Where-Object { $_.Length -gt 80 }).Count | Should Be 0
    }

    It 'says to run it again after any other failure, and restores first' {
        $Join = 'http://192.168.16.252:8283'; $Token = 't'; $Config = Join-Path $Root 'agent.yaml'
        $AgentEx = Join-Path $Root 'agent-stub.ps1'
        [IO.File]::WriteAllText($AgentEx, 'exit 1')
        $SetAside = [pscustomobject]@{ Moved = @(); Restored = $false }
        Mock Restore-EugeneInstall { $true }
        { . $runJoin } | Should Throw 'Fix what it says, then run this command again'
        Assert-MockCalled Restore-EugeneInstall -Scope It -Times 1 -Exactly
    }

    It 'commits once the join succeeds, and carries the old engine builds over' {
        $Join = 'http://192.168.16.252:8283'; $Token = 't'; $Config = Join-Path $Root 'agent.yaml'
        $AgentEx = Join-Path $Root 'agent-stub.ps1'
        [IO.File]::WriteAllText($AgentEx, 'exit 0')
        $JoinCommitted = $false
        $SetAside = [pscustomobject]@{ Moved = @([pscustomobject]@{ From = 'a'; To = (Join-Path $Root 'old.replaced-1') }) }
        Mock Restore-EugeneInstall { $true }
        Mock Copy-EngineBuilds {}
        . $runJoin
        $JoinCommitted | Should Be $true
        Assert-MockCalled Restore-EugeneInstall -Scope It -Times 0 -Exactly
        Assert-MockCalled Copy-EngineBuilds -Scope It -Times 1 -Exactly -ParameterFilter {
            $Source -eq (Join-Path $Root 'old.replaced-1\engines') }
    }

    It 'sets installs aside after the trap that restores them and before anything is written' {
        # Text, because the steps between talk to uv and the network.
        $uv = $source.IndexOf('# --- 1. uv ')
        $trap = $source.IndexOf('trap {', $uv)
        $suspend = $source.IndexOf('$SetAside = Suspend-EugeneInstall', $uv)
        $firstWrite = $source.IndexOf('Say "installing into $Prefix', $uv)
        ($uv -lt $trap -and $trap -lt $suspend -and $suspend -lt $firstWrite) | Should Be $true
        $source | Should Match '(?s)trap \{.*if \(\$SetAside -and -not \$SetAside\.Restored -and -not \$JoinCommitted\) \{\s*Restore-EugeneInstall'
    }
}

Describe 'An install from alpha.2 or earlier' {
    BeforeEach {
        $script:Root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        Mock Write-Host {}
        $script:InstallerUrl = 'https://example.invalid/install.ps1'
    }

    It 'is refused in plain words, with the command that removes it' {
        $Prefix = Join-Path $Root 'old'
        New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
        [IO.File]::WriteAllText((Join-Path $Prefix 'node.yaml'), "name: Amish_Station`nsigningKey: c2VjcmV0`nsigningKeyId: '1'`n")
        $threw = $null
        try { Assert-UpgradeableInstall } catch { $threw = $_.Exception.Message }
        $threw | Should Match 'alpha\.2 or earlier'
        $threw | Should Match '-Uninstall'
        $threw | Should Match 'No model file is deleted'
        # Every line fits a console except the command, which is copied.
        $lines = @($threw -split "`n" | Select-Object -Skip 1)
        @($lines | Where-Object { $_ -notmatch 'scriptblock' -and $_.Length -gt 80 }).Count | Should Be 0
    }

    It 'lets an install with per-node keys through' {
        $Prefix = Join-Path $Root 'new'
        New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
        [IO.File]::WriteAllText((Join-Path $Prefix 'node.yaml'), "name: box`ntokenPrivateKey: a2V5`nsigningPrivateKey: a2V5`n")
        { Assert-UpgradeableInstall } | Should Not Throw
    }

    It 'lets a machine with no node file through' {
        $Prefix = Join-Path $Root 'none'
        { Assert-UpgradeableInstall } | Should Not Throw
    }
}

Describe 'An update started from the app' {
    # 2026-09-27: the agent runs this script with -Update from a one-shot
    # scheduled task. It may only ever upgrade the install that is there.
    BeforeEach {
        $script:Existing = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:Existing 'venv\Scripts') | Out-Null
        [IO.File]::WriteAllText((Join-Path $script:Existing 'agent.yaml'), 'firstRunComplete: true')
        [IO.File]::WriteAllText((Join-Path $script:Existing 'venv\Scripts\python.exe'), '')
        Mock Get-CimInstance { $null }
        Mock Get-Service { $null }
        Mock Get-ScheduledTask {
            [pscustomobject]@{ Actions = @([pscustomobject]@{
                Execute = Join-Path $script:Existing 'venv\Scripts\eugene-plexus-agent.exe'
            }) }
        }
        Mock Start-Process { throw 'TEST: elevation must not be reached' }
        Mock Write-Host {}
    }

    It 'upgrades the per-user install that is here' {
        { & $preflight -Prefix $script:Existing -NoService -Update -NoElevate } | Should Not Throw
    }

    It 'never makes a second install' {
        $empty = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        { & $preflight -Prefix $empty -NoService -Update -NoElevate } |
            Should Throw '-Update found no install'
        Test-Path (Join-Path $empty 'venv') | Should Be $false
    }

    It 'never touches an autostart that runs a different install' {
        $source -match '(?s)if \(\$Update\) \{\s+# \*\*Only the autostart that runs THIS install' | Should Be $true
        $guard = $source.IndexOf('-Update only updates the install its autostart runs')
        $stop = $source.IndexOf('if (Get-AgentService) { Stop-Service')
        $guard | Should BeGreaterThan 0
        $guard | Should BeLessThan $stop
    }

    It 'keeps the port the service already starts on' {
        Mock Get-AgentService { [pscustomobject]@{ Name = 'EugenePlexusAgent' } }
        Mock Get-AgentServiceEnvironment {
            @('EUGENE_PLEXUS_AGENT_CONFIG_FILE=C:\x\agent.yaml', 'EUGENE_PLEXUS_AGENT_BIND_PORT=18279')
        }
        Get-InstalledPort | Should Be 18279
        Mock Get-AgentServiceEnvironment { @('EUGENE_PLEXUS_AGENT_CONFIG_FILE=C:\x\agent.yaml') }
        Get-InstalledPort | Should Be 8079
    }

    It 'reads that port before writing the service environment back' {
        # CI checks the script out with CRLF; this box has LF.
        $text = $source -replace "`r`n", "`n"
        $block = $text.Substring($text.IndexOf("if (`$Update) {`n    # Before Set-ServiceBootstrap"))
        $read = $block.IndexOf('$Port = Get-InstalledPort')
        $write = $block.IndexOf("`n        Set-ServiceBootstrap`n")
        $read | Should BeGreaterThan 0
        $read | Should BeLessThan $write
    }

    It 'is only ever an upgrade' {
        foreach ($other in @(@{ Join = 'http://root:8083' }, @{ Migrate = $true }, @{ Isolated = $true })) {
            { & $preflight -Prefix $script:Existing -NoService -Update -NoElevate @other } |
                Should Throw 'cannot be combined'
        }
    }
}

Describe 'Re-registering a service install whose service is gone' {
    # Amish_Station, 2026-09-26: a failed join had removed the service, and
    # re-running the installer asked for -Migrate as though a per-user
    # install were being turned into a service.
    BeforeEach {
        $script:Root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:SavedProgramData = $env:ProgramData
        $env:ProgramData = Join-Path $script:Root 'ProgramData'
        $script:WantsService = $true
        Mock Get-AgentService { $null }
        Mock Get-OtherInstall { $null }
    }
    AfterEach { $env:ProgramData = $script:SavedProgramData }

    It 'is no conversion when the install already lives in ProgramData' {
        $Prefix = Join-Path $env:ProgramData 'EugenePlexus'
        New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
        [IO.File]::WriteAllText((Join-Path $Prefix 'agent.yaml'), 'firstRunComplete: true')
        Get-ServiceConversionSource | Should BeNullOrEmpty
    }

    It 'is still a conversion for a per-user install' {
        $Prefix = Join-Path $Root 'LocalAppData\EugenePlexus'
        New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
        [IO.File]::WriteAllText((Join-Path $Prefix 'agent.yaml'), 'firstRunComplete: true')
        Get-ServiceConversionSource | Should Be $Prefix
    }
}

Describe 'Uninstall finds the install wherever it is' {
    # 2026-09-26: an ordinary PowerShell looked only in %LOCALAPPDATA% and
    # said "nothing installed" with a service install in %ProgramData%.
    $uninstallBlock = $ast.Find({ param($node)
            $node -is [System.Management.Automation.Language.IfStatementAst] -and
            $node.Clauses[0].Item1.Extent.Text -eq '$Uninstall' -and
            $node.Extent.Text -match 'Get-EugeneInstall' }, $true)
    $runUninstall = [scriptblock]::Create($uninstallBlock.Extent.Text)

    BeforeEach {
        # TestDrive is shared by every test in a Describe, so each test gets
        # a root of its own and cannot see another's folders.
        $script:Root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:SavedEnv = @{}
        foreach ($name in 'ProgramData', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE') {
            $script:SavedEnv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            $dir = Join-Path $script:Root $name
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            [Environment]::SetEnvironmentVariable($name, $dir, 'Process')
        }
        $script:ConfigVariable = 'EUGENE_PLEXUS_TEST_ONLY_CONFIG_FILE'
        $script:BindHostVariable = 'EUGENE_PLEXUS_TEST_ONLY_BIND_HOST'
        $script:EngineRootVariable = 'EUGENE_PLEXUS_TEST_ONLY_ENGINE_ROOT'
        $script:InstallVariables = @($script:ConfigVariable, $script:BindHostVariable, $script:EngineRootVariable)
        $script:ServiceName = 'EPTestOnlyService'
        $script:TaskName = 'EPTestOnlyTask'
        $script:TrayTaskName = 'EPTestOnlyTray'
        $temp = [IO.Path]::GetTempPath()
        Mock Move-Folder { throw "TEST: refused to move $From" } -ParameterFilter {
            -not ("$From".StartsWith($temp, 'OrdinalIgnoreCase') -and
                "$To".StartsWith($temp, 'OrdinalIgnoreCase')) }
        Mock Stop-Process { throw 'TEST: no process may be stopped' }
        Mock Get-CimInstance { $null }
        Mock Get-AutostartExecutable { $null }
        Mock Get-AgentService { $null }
        Mock Get-AgentTask { $null }
        Mock Get-ScheduledTask { $null }
        Mock Invoke-ElevatedInstaller {}
        Mock Write-RemovalBundle {}
        Mock Invoke-Native {}
        Mock Write-Host {}
    }
    AfterEach {
        foreach ($name in $script:SavedEnv.Keys) {
            [Environment]::SetEnvironmentVariable($name, $script:SavedEnv[$name], 'Process')
        }
    }

    It 'asks for Administrator itself when the install is a service install' {
        $Uninstall = $true; $IsElevated = $false; $PrefixGiven = $false; $NoElevate = $false
        $Prefix = Join-Path $env:LOCALAPPDATA 'EugenePlexus'
        $machine = Join-Path $env:ProgramData 'EugenePlexus'
        New-Item -ItemType Directory -Force -Path $machine | Out-Null
        [IO.File]::WriteAllText((Join-Path $machine 'agent.yaml'), 'x')
        . $runUninstall
        Assert-MockCalled Invoke-ElevatedInstaller -Scope It -Times 1 -Exactly
        Test-Path (Join-Path $machine 'agent.yaml') | Should Be $true
        Assert-MockCalled Write-Host -Scope It -Times 0 -ParameterFilter { $Object -like '*nothing*' }
    }

    It 'passes each discovered install to its offline removal utility' {
        $Uninstall = $true; $IsElevated = $false; $PrefixGiven = $false; $NoElevate = $false
        $Prefix = Join-Path $env:LOCALAPPDATA 'EugenePlexus'
        $elsewhere = Join-Path $Root 'elsewhere\EugenePlexus'
        foreach ($dir in $Prefix, $elsewhere) {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            [IO.File]::WriteAllText((Join-Path $dir 'agent.yaml'), 'x')
        }
        [Environment]::SetEnvironmentVariable($ConfigVariable, (Join-Path $elsewhere 'agent.yaml'), 'User')
        try { . $runUninstall }
        finally { [Environment]::SetEnvironmentVariable($ConfigVariable, $null, 'User') }
        Assert-MockCalled Write-RemovalBundle -Times 1 -Exactly -Scope It -ParameterFilter { $Path -eq $Prefix }
        Assert-MockCalled Write-RemovalBundle -Times 1 -Exactly -Scope It -ParameterFilter { $Path -eq $elsewhere }
        Assert-MockCalled Invoke-Native -Times 2 -Exactly -Scope It -ParameterFilter { $Exe -eq 'powershell.exe' -and $Arguments -contains '-Prefix' }
    }

    It 'says where it looked when there is nothing to remove' {
        $Uninstall = $true; $IsElevated = $false; $PrefixGiven = $false; $NoElevate = $false
        $Prefix = Join-Path $env:LOCALAPPDATA 'EugenePlexus'
        . $runUninstall
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { $Object -like '*nothing to remove*' }
        Assert-MockCalled Invoke-ElevatedInstaller -Scope It -Times 0 -Exactly
    }
}

Describe 'The Visual C++ runtime llama.cpp needs' {
    # 2026-09-26: a freshly reinstalled Windows has no VCRUNTIME140.dll,
    # VCRUNTIME140_1.dll or MSVCP140.dll, so llama-server died at start and
    # every model read "crashed". Nothing here downloads or installs
    # anything: every command that would is mocked.
    $vcBlock = $ast.Find({ param($node)
            $node -is [System.Management.Automation.Language.IfStatementAst] -and
            $node.Clauses[0].Item1.Extent.Text -eq '-not (Test-VcRuntime)' }, $true)
    $runVcBlock = [scriptblock]::Create($vcBlock.Extent.Text)

    BeforeEach {
        $script:VcRedistArch = 'x64'
        $script:VcRedistUrl = 'https://aka.ms/vc14/vc_redist.x64.exe'
        $script:VcRuntimeMinimum = [version]'14.50'
        Mock Write-Host {}
        Mock Invoke-WebRequest {}
        Mock Remove-Item {}
        Mock Get-AuthenticodeSignature {
            [pscustomobject]@{ Status = 'Valid'; SignerCertificate = [pscustomobject]@{ Subject = 'CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US' } }
        }
        Mock Start-Process { [pscustomobject]@{ ExitCode = 0 } }
        # The runner's own System32 is never read: every case says what
        # msvcp140.dll's version is.
        Mock Get-DllVersion { [version]'14.51.36247.0' }
    }

    It 'is missing when any one of its three DLLs is' {
        Mock Test-Path { $LiteralPath -notlike '*vcruntime140_1.dll' }
        Test-VcRuntime | Should Be $false
        Mock Test-Path { $true }
        Test-VcRuntime | Should Be $true
    }

    # 2026-10-03, the upstream drift audit: llama.cpp's Windows builds come
    # from Visual Studio 2026 (runtime 14.50+), and the installer fetched
    # Visual Studio 2022's final runtime, 14.44, and asked only whether the
    # DLLs existed -- so a machine with the 2022 runtime was never upgraded.
    It 'fetches the current runtime, not Visual Studio 2022''s' {
        $source | Should Match '(?m)^\$VcRedistUrl = "https://aka\.ms/vc14/vc_redist\.\$VcRedistArch\.exe"'
        $source | Should Match '(?m)^\$VcRuntimeMinimum = \[version\]"14\.50"'
        $source | Should Not Match 'https://aka\.ms/vs/'
    }

    It 'is too old when msvcp140.dll is older than 14.50, though all three DLLs are there' {
        Mock Test-Path { $true }
        Mock Get-DllVersion { [version]'14.44.35211.0' }
        Get-VcRuntimeVersion | Should Be ([version]'14.44.35211.0')
        Test-VcRuntime | Should Be $false
    }

    It 'is new enough at 14.50 and after, compared as numbers' {
        Mock Test-Path { $true }
        foreach ($ok in '14.50.35719.0', '14.51.36247.0', '14.100.0.0') {
            Mock Get-DllVersion { [version]$ok }
            Test-VcRuntime | Should Be $true
        }
    }

    It 'reads the version from msvcp140.dll in the native System32' {
        Mock Test-Path { $true }
        $null = Get-VcRuntimeVersion
        Assert-MockCalled Get-DllVersion -Scope It -Times 1 -Exactly -ParameterFilter {
            $Path -eq (Join-Path (Get-NativeSystemDirectory) 'msvcp140.dll') }
    }

    It 'installs quietly from Microsoft when Microsoft signed it' {
        Install-VcRuntime | Should Be 0
        Assert-MockCalled Invoke-WebRequest -Scope It -Times 1 -Exactly -ParameterFilter { $Uri -eq 'https://aka.ms/vc14/vc_redist.x64.exe' }
        Assert-MockCalled Start-Process -Scope It -Times 1 -Exactly -ParameterFilter { ($ArgumentList -join ' ') -eq '/install /quiet /norestart' }
    }

    It 'refuses a download that Microsoft did not sign, and never runs it' {
        Mock Get-AuthenticodeSignature { [pscustomobject]@{ Status = 'HashMismatch'; SignerCertificate = $null } }
        { Install-VcRuntime } | Should Throw 'not signed by Microsoft'
        Assert-MockCalled Start-Process -Scope It -Times 0 -Exactly
    }

    It 'takes "a newer one is there" and "restart pending" as installed' {
        foreach ($code in 1638, 3010) {
            Mock Start-Process { [pscustomobject]@{ ExitCode = $code } }
            { Install-VcRuntime } | Should Not Throw
        }
    }

    It 'says what the redistributable''s installer said when it fails' {
        Mock Start-Process { [pscustomobject]@{ ExitCode = 1603 } }
        { Install-VcRuntime } | Should Throw 'exited with code 1603'
    }

    It 'installs it on an elevated run when it is missing' {
        $IsElevated = $true; $Isolated = $false
        Mock Test-VcRuntime { $false }
        Mock Get-VcRuntimeVersion { $null }
        Mock Install-VcRuntime {}
        . $runVcBlock
        Assert-MockCalled Install-VcRuntime -Scope It -Times 1 -Exactly
    }

    It 'upgrades an old one on an elevated run, and says which it found' {
        $IsElevated = $true; $Isolated = $false
        Mock Test-VcRuntime { $false }
        Mock Get-VcRuntimeVersion { [version]'14.44.35211.0' }
        Mock Install-VcRuntime { 0 }
        . $runVcBlock
        Assert-MockCalled Install-VcRuntime -Scope It -Times 1 -Exactly
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*Visual C++ runtime 14.44.35211.0, older than the 14.50*' }
    }

    It 'says a restart finishes it when Windows replaces the old runtime at the next restart' {
        $IsElevated = $true; $Isolated = $false
        Mock Test-VcRuntime { $false }
        Mock Get-VcRuntimeVersion { [version]'14.44.35211.0' }
        Mock Install-VcRuntime { 3010 }
        . $runVcBlock
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*finishes replacing the old one when this machine restarts*' }
        Assert-MockCalled Write-Host -Scope It -Times 0 -Exactly -ParameterFilter { "$Object" -like '*DLLs are not in place*' }
    }

    It 'says where to get it on a per-user run, which cannot install it' {
        $IsElevated = $false; $Isolated = $false
        Mock Test-VcRuntime { $false }
        Mock Get-VcRuntimeVersion { $null }
        Mock Install-VcRuntime {}
        . $runVcBlock
        Assert-MockCalled Install-VcRuntime -Scope It -Times 0 -Exactly
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*no Microsoft Visual C++ runtime*aka.ms/vc14/vc_redist.x64.exe*' }
    }

    It 'says an old one is too old on a per-user run, and where the current one is' {
        $IsElevated = $false; $Isolated = $false
        Mock Test-VcRuntime { $false }
        Mock Get-VcRuntimeVersion { [version]'14.44.35211.0' }
        Mock Install-VcRuntime {}
        . $runVcBlock
        Assert-MockCalled Install-VcRuntime -Scope It -Times 0 -Exactly
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*runtime 14.44.35211.0, older than the 14.50*aka.ms/vc14/vc_redist.x64.exe*' }
    }

    It 'changes nothing on an isolated run, and says so' {
        $IsElevated = $true; $Isolated = $true
        Mock Test-VcRuntime { $false }
        Mock Get-VcRuntimeVersion { $null }
        Mock Install-VcRuntime {}
        . $runVcBlock
        Assert-MockCalled Install-VcRuntime -Scope It -Times 0 -Exactly
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*isolated install changes nothing*' }
    }

    It 'says nothing and installs nothing when it is already there' {
        $IsElevated = $true; $Isolated = $false
        Mock Test-VcRuntime { $true }
        Mock Install-VcRuntime {}
        . $runVcBlock
        Assert-MockCalled Install-VcRuntime -Scope It -Times 0 -Exactly
        Assert-MockCalled Write-Host -Scope It -Times 0 -Exactly
    }

    It 'warns rather than failing the install when it cannot install it' {
        $IsElevated = $true; $Isolated = $false
        Mock Test-VcRuntime { $false }
        Mock Get-VcRuntimeVersion { $null }
        Mock Install-VcRuntime { throw 'the network is down' }
        { . $runVcBlock } | Should Not Throw
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*could not install the Microsoft Visual C++ runtime (the network is down)*' }
    }
}

Describe 'uv is fetched again when it is older than the installer keeps' {
    # 2026-10-03, the upstream drift audit: step 1 skipped the download
    # whenever a uv was there, and the app's updates re-run this script, so
    # an install kept its first uv forever -- and uv 0.12.7 to 0.12.17 can
    # write outside the target directory while unpacking a wheel on Windows
    # (GHSA-2cv4-cqwr-gwf7). A uv stand-in here is a .cmd that says a
    # version in uv's own words; nothing is downloaded and nothing runs.
    BeforeEach {
        $script:Prefix = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:Prefix 'bin') | Out-Null
        $script:UvExe = Join-Path $script:Prefix 'bin\uv.cmd'
        $script:UvMinimum = [version]'0.12.18'
        $script:SavedUnmanaged = $env:UV_UNMANAGED_INSTALL
        # What a fetch leaves at $UvExe; a case changes it.
        $script:Fetched = '0.12.22'
        Mock Write-Host {}
        Mock Invoke-RestMethod {}
        $script:UnmanagedAtFetch = $null
        Mock Invoke-Native {
            $script:UnmanagedAtFetch = $env:UV_UNMANAGED_INSTALL
            [IO.File]::WriteAllText($script:UvExe, "@echo uv $($script:Fetched) (x86_64-pc-windows-msvc)")
        }
    }
    AfterEach { $env:UV_UNMANAGED_INSTALL = $script:SavedUnmanaged }

    function Set-Uv([string]$Words) { [IO.File]::WriteAllText($script:UvExe, "@echo $Words") }

    It 'reads the version from uv''s own words' {
        Set-Uv 'uv 0.12.17 (x86_64-pc-windows-msvc)'
        Get-UvVersion $UvExe | Should Be ([version]'0.12.17')
        Set-Uv 'uv: no version here'
        Get-UvVersion $UvExe | Should BeNullOrEmpty
        Get-UvVersion (Join-Path $Prefix 'bin\absent.cmd') | Should BeNullOrEmpty
    }

    It 'keeps a uv that is new enough, and says so in the words it always did' {
        foreach ($have in '0.12.22', '0.12.18', '0.13.0', '1.0.0') {
            Set-Uv "uv $have (x86_64-pc-windows-msvc)"
            Install-Uv
            Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like "*uv already present (uv $have (*" }
        }
        Assert-MockCalled Invoke-RestMethod -Scope It -Times 0 -Exactly
        Assert-MockCalled Invoke-Native -Scope It -Times 0 -Exactly
    }

    It 'fetches a newer one over a uv that is too old, compared as numbers, and says why' {
        foreach ($have in '0.12.17', '0.12.7', '0.12.9', '0.9.30') {
            Set-Uv "uv $have (x86_64-pc-windows-msvc)"
            Install-Uv
            Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like "*uv $have is older than 0.12.18*" }
            Get-UvVersion $UvExe | Should Be ([version]'0.12.22')
        }
        Assert-MockCalled Invoke-Native -Scope It -Times 4 -Exactly
    }

    It 'uses uv''s own installer, kept inside the prefix' {
        Set-Uv 'uv 0.12.17 (x86_64-pc-windows-msvc)'
        Install-Uv
        Assert-MockCalled Invoke-RestMethod -Scope It -Times 1 -Exactly -ParameterFilter { $Uri -eq 'https://astral.sh/uv/install.ps1' }
        Assert-MockCalled Invoke-Native -Scope It -Times 1 -Exactly -ParameterFilter {
            ($Arguments -join ' ') -like '-NoProfile -ExecutionPolicy Bypass -File *eugene-plexus-uv-install-*.ps1' }
        $script:UnmanagedAtFetch | Should Be (Join-Path $Prefix 'bin')
    }

    It 'fetches one again over a uv that cannot say its version' {
        Set-Uv 'uv: no version here'
        Install-Uv
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*does not say its version; fetching uv again*' }
        Assert-MockCalled Invoke-Native -Scope It -Times 1 -Exactly
    }

    It 'fetches one where there is none, as before' {
        Install-Uv
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -eq '==> fetching uv' }
        Assert-MockCalled Invoke-Native -Scope It -Times 1 -Exactly
    }

    It 'stops, naming both versions, when the fetch left the old uv in place' {
        Set-Uv 'uv 0.12.17 (x86_64-pc-windows-msvc)'
        $script:Fetched = '0.12.17'
        { Install-Uv } | Should Throw 'is 0.12.17 after fetching it again, and this installer needs 0.12.18 or newer'
    }

    It 'stops with the download''s own reason, and keeps the old uv, when it cannot fetch' {
        Set-Uv 'uv 0.12.17 (x86_64-pc-windows-msvc)'
        Mock Invoke-RestMethod { throw 'the remote name could not be resolved' }
        { Install-Uv } | Should Throw 'could not download https://astral.sh/uv/install.ps1 -- the remote name could not be resolved'
        Assert-MockCalled Invoke-Native -Scope It -Times 0 -Exactly
        Get-UvVersion $UvExe | Should Be ([version]'0.12.17')
    }

    It 'is step 1, and both installers keep the same minimum' {
        $text = $source -replace "`r`n", "`n"
        $step = $text.IndexOf('# --- 1. uv ')
        $call = $text.IndexOf("`nInstall-Uv`n")
        $venv = $text.IndexOf('# --- 2. venv ')
        ($step -lt $call -and $call -lt $venv) | Should Be $true
        $text | Should Match '(?m)^\$UvMinimum = \[version\]"0\.12\.18"'
        # A Windows checkout may carry install.sh with CRLF, and `$` under
        # (?m) does not match before a `\r` (CI, 2026-10-03).
        ([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'install.sh')) -replace "`r`n", "`n") |
            Should Match '(?m)^UV_MINIMUM=0\.12\.18$'
    }
}

Describe 'How a failed run ends' {
    # 2026-09-26: a failure ended in the message and then the whole
    # ErrorRecord -- "At line:145 char:71", CategoryInfo,
    # FullyQualifiedErrorId -- once from the elevated child and again from
    # the person's own prompt. `-Isolated` with nothing else refuses before
    # anything is written, so it is safe to run the real script here.
    $installer = Join-Path $PSScriptRoot 'install.ps1'

    It 'says the one line at a prompt, keeps the prompt, and sets the exit code' {
        Mock Write-Host {}
        $global:LASTEXITCODE = 0
        $threw = $null
        try { & ([scriptblock]::Create($source)) -Isolated } catch { $threw = $_ }
        $threw | Should Be $null
        $global:LASTEXITCODE | Should Be 1
        Assert-MockCalled Write-Host -Times 1 -Exactly -Scope It
        Assert-MockCalled Write-Host -Times 1 -Exactly -Scope It -ParameterFilter { $Object -like 'error: -Isolated requires*' }
    }

    It 'exits 1 with the one line under powershell -File, which CI reads' {
        $out = & powershell.exe -NoProfile -File $installer -Isolated 2>&1 | ForEach-Object { "$_" }
        $LASTEXITCODE | Should Be 1
        ($out -join "`n") | Should Match '^error: -Isolated requires'
        @($out | Where-Object { $_ -match 'FullyQualifiedErrorId|CategoryInfo|At line:|char:' }).Count | Should Be 0
        @($out | Where-Object { $_.Trim() }).Count | Should Be 1
    }

    It 'fails the elevated run when the script stopped itself without throwing' {
        Mock Write-Host {}
        Mock Start-Process {
            param($FilePath, $ArgumentList)
            $start = New-Object Diagnostics.ProcessStartInfo
            $start.FileName = $FilePath
            $start.Arguments = $ArgumentList -join ' '
            $start.UseShellExecute = $false
            $start.CreateNoWindow = $true
            $process = [Diagnostics.Process]::Start($start)
            if (-not $process.WaitForExit(60000)) { $process.Kill(); throw 'test child timed out' }
            [pscustomobject]@{ ExitCode = $process.ExitCode }
        }
        { Invoke-ElevatedInstaller -ScriptText '$global:EugenePlexusInstallFailed = $true' -Parameters @{} -WorkDirectory $TestDrive } |
            Should Throw 'did not finish'
    }

    It 'replays the hidden run without the transcript banners or error noise' {
        Mock Write-Host {}
        $log = Join-Path $TestDrive 'replay.log'
        [IO.File]::WriteAllLines($log, @(
                '**********************', 'Windows PowerShell transcript start',
                'Host Application: powershell.exe -EncodedCommand JABFAHIAcgBvAHIA', '**********************',
                '==> installing', 'error: the join failed', 'PS>TerminatingError(): "the join failed"',
                '>> TerminatingError(): "the join failed"',
                '**********************', 'Windows PowerShell transcript end', '**********************'))
        Show-InstallerLog $log
        Assert-MockCalled Write-Host -Times 2 -Exactly -Scope It
        Assert-MockCalled Write-Host -Times 1 -Exactly -Scope It -ParameterFilter { $Object -eq 'error: the join failed' }
        Assert-MockCalled Write-Host -Times 0 -Exactly -Scope It -ParameterFilter { "$Object" -match 'EncodedCommand|TerminatingError|transcript' }
    }
}
