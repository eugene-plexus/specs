# Real file operations, OS integration mocked. No live installs are inspected.
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'uninstall.ps1'))
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$null, [ref]$null)
$ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false) |
    ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }

function Write-Fixture([string]$Path, [string]$Text = 'fixture') {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

Describe 'Offline Windows removal' {
    BeforeEach {
        $script:Fixture = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:Prefix = Join-Path $Fixture "Eugene's files"
        $script:Copies = Join-Path $Fixture 'model copies'
        $script:Plan = [pscustomobject]@{
            version = 1; prefix = $Prefix; warnings = @()
            software = @((Join-Path $Prefix 'venv'), (Join-Path $Prefix 'pythons'), (Join-Path $Prefix 'apps\chat\versions'))
            data = @((Join-Path $Prefix 'agent.yaml'), (Join-Path $Prefix 'apps\chat\data'), (Join-Path $Prefix 'logs'))
            downloads = @((Join-Path $Prefix 'engines'), $Copies)
            protected = @((Join-Path $Prefix 'models'))
        }
        foreach ($file in @('venv\package.dll','pythons\runtime.dll','apps\chat\versions\1\package.dll',
                'apps\chat\data\chat.sqlite3','models\original.gguf','engines\llama\server.exe','logs\log.txt','agent.yaml')) {
            Write-Fixture (Join-Path $Prefix $file)
        }
        Write-Fixture (Join-Path $Copies 'copy.gguf')
        Write-Fixture (Join-Path $Prefix 'uninstall\receipt\inventory.json') ($Plan | ConvertTo-Json -Depth 5)
        $global:EugeneRemovalIncomplete = $false
        Mock Write-Host {}
        Mock Remove-RemovalCredentials { @() }
        Mock Remove-RemovalIntegration {}
        Mock Get-CimInstance { @() }
        Mock Get-ScheduledTask { $null }
        Mock Get-NetFirewallRule { @() }
        Mock Test-RemovalAdmin { $false }
        Mock Test-Path { $false } -ParameterFilter { $LiteralPath -like 'HK*:*' }
    }

    It 'removes software, keeps personal data, then purges offline using the original receipt' {
        Invoke-Removal $Prefix $false $false $false
        $kept = (Get-ChildItem -LiteralPath $Fixture -Directory -Filter '*.removed-*').FullName
        Test-Path -LiteralPath (Join-Path $kept 'venv') | Should Be $false
        Test-Path -LiteralPath (Join-Path $kept 'pythons') | Should Be $false
        Test-Path -LiteralPath (Join-Path $kept 'apps\chat\versions') | Should Be $false
        Test-Path -LiteralPath (Join-Path $kept 'agent.yaml') | Should Be $true
        Test-Path -LiteralPath (Join-Path $kept 'apps\chat\data\chat.sqlite3') | Should Be $true
        Test-Path -LiteralPath $Copies | Should Be $true
        Invoke-Removal $kept $false $true $true
        Test-Path -LiteralPath (Join-Path $kept 'agent.yaml') | Should Be $false
        Test-Path -LiteralPath (Join-Path $kept 'engines') | Should Be $false
        Test-Path -LiteralPath $Copies | Should Be $false
        Test-Path -LiteralPath (Join-Path $kept 'apps\chat\data') | Should Be $false
        Test-Path -LiteralPath (Join-Path $kept 'models\original.gguf') | Should Be $true
        [IO.File]::ReadAllText((Join-Path $kept 'models\original.gguf')) | Should Be 'fixture'
        Invoke-Removal $kept $false $true $true
        $global:EugeneRemovalIncomplete | Should Be $false
        Assert-MockCalled Remove-RemovalIntegration -Times 1 -Exactly -Scope It
    }

    It 'makes cancellation leave the install and OS registration alone' {
        Mock Show-RemovalChoice { $null }
        Invoke-Removal $Prefix $true $false $false
        Test-Path -LiteralPath (Join-Path $Prefix 'venv\package.dll') | Should Be $true
        Assert-MockCalled Remove-RemovalIntegration -Times 0 -Exactly -Scope It
        Assert-MockCalled Remove-RemovalCredentials -Times 0 -Exactly -Scope It
    }

    It 'keeps original models even if a receipt incorrectly lists them as downloads' {
        $Plan.downloads += Join-Path $Prefix 'models'
        $warnings = @(Remove-RemovalFiles $Plan $Prefix $true $true)
        ($warnings -join ' ') | Should Match 'original model folder'
        Test-Path -LiteralPath (Join-Path $Prefix 'models\original.gguf') | Should Be $true
    }

    It 'refuses parent folders and paths outside the specified software root' {
        { Assert-RemovalPath $Fixture $Prefix -External } | Should Throw 'unsafe'
        { Assert-RemovalPath $env:USERPROFILE $Prefix -External } | Should Throw 'unsafe'
        { Assert-RemovalPath $Copies $Prefix } | Should Throw 'outside'
    }

    It 'does not traverse a junction inserted after the inventory was recorded' {
        $outside = Join-Path $Fixture 'outside'
        Write-Fixture (Join-Path $outside 'keep.txt')
        $linked = Join-Path $Prefix 'linked'
        New-Item -ItemType Junction -Path $linked -Target $outside | Out-Null
        try {
            { Assert-RemovalPath (Join-Path $linked 'keep.txt') $Prefix } | Should Throw 'linked'
            # A junction nested inside an owned tree is unlinked, not followed.
            $full = Assert-RemovalPath (Join-Path $Prefix 'venv') $Prefix
            New-Item -ItemType Junction -Path (Join-Path $full 'link') -Target $outside | Out-Null
            Remove-RemovalTree $full
            Test-Path -LiteralPath (Join-Path $outside 'keep.txt') | Should Be $true
        } finally { [IO.Directory]::Delete($linked) }
    }

    It 'keeps cleanup failures visible in the saved report and on a later pass' {
        Mock Remove-RemovalCredentials { @('Credential left: test vault is locked') }
        Invoke-Removal $Prefix $false $false $false
        $kept = (Get-ChildItem -LiteralPath $Fixture -Directory -Filter '*.removed-*').FullName
        $report = Join-Path $kept 'uninstall\receipt\report.txt'
        [IO.File]::ReadAllText($report) | Should Match 'vault is locked'
        $global:EugeneRemovalIncomplete | Should Be $true
        Invoke-Removal $kept $false $true $true
        [IO.File]::ReadAllText($report) | Should Match 'Previously reported.*vault is locked'
    }

    It 'opens the SYSTEM credential vault for a LocalSystem installation' {
        Mock Get-CimInstance { [pscustomobject]@{ PathName = "$Prefix\venv\Scripts\pythonservice.exe"; State = 'Stopped'; StartName = 'LocalSystem'; Name = 'EugenePlexusAgent' } }
        Invoke-Removal $Prefix $false $false $false
        Assert-MockCalled Remove-RemovalCredentials -Times 1 -Exactly -Scope It -ParameterFilter { $AsSystem }
        Assert-MockCalled Remove-RemovalCredentials -Times 1 -Exactly -Scope It -ParameterFilter { -not $AsSystem }
    }

    It 'reports a firewall refusal rather than claiming complete cleanup' {
        Mock Get-NetFirewallRule { throw 'firewall access denied' }
        Invoke-Removal $Prefix $false $false $false
        $kept = (Get-ChildItem -LiteralPath $Fixture -Directory -Filter '*.removed-*').FullName
        [IO.File]::ReadAllText((Join-Path $kept 'uninstall\receipt\report.txt')) | Should Match 'firewall access denied'
        $global:EugeneRemovalIncomplete | Should Be $true
    }

    It 'registers an offline command and scopes it to the install' {
        Mock New-Item {}
        Mock New-ItemProperty {}
        Register-Removal $Prefix $true
        Assert-MockCalled New-ItemProperty -Scope It -Times 1 -ParameterFilter { $Name -eq 'UninstallString' -and $Value -match 'EncodedCommand' -and $Value -notmatch 'https?://' }
        $command = Get-RemovalCommand $Prefix $true
        $body = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String(($command -split ' ')[-1]))
        $body | Should Match 'RunAs'
        $command | Should Not Match 'curl|irm|iex'
        (Get-RemovalId $Prefix) | Should Not Be (Get-RemovalId $Copies)
    }

    It 'asks for firewall elevation only for the per-user cleanup operation' {
        Mock Get-NetFirewallRule { [pscustomobject]@{ DisplayName = 'Eugene Plexus' } }
        Mock Start-Process { [pscustomobject]@{ ExitCode = 0 } }
        Remove-RemovalFirewall
        Assert-MockCalled Start-Process -Times 1 -Exactly -Scope It -ParameterFilter { $Verb -eq 'RunAs' -and $WindowStyle -eq 'Hidden' }
    }

    It 'never removes unrelated firewall rules' {
        Mock Get-NetFirewallRule { [pscustomobject]@{ DisplayName = 'Some other application' } }
        Mock Start-Process { throw 'should not elevate' }
        Remove-RemovalFirewall
        Assert-MockCalled Start-Process -Times 0 -Exactly -Scope It
    }

    It 'uses a fresh SYSTEM task result and removes the temporary task' {
        Write-Fixture (Join-Path $Prefix 'venv\Scripts\python.exe')
        Write-Fixture (Join-Path $Prefix 'uninstall\receipt\credentials-system.json') '{"warnings":["stale"]}'
        # Construct typed task descriptions only; registration/start are mocked.
        $script:RemovalTestAction = New-ScheduledTaskAction -Execute 'fixture.exe'
        $script:RemovalTestPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Mock New-ScheduledTaskAction { $script:RemovalTestAction }
        Mock New-ScheduledTaskPrincipal { $script:RemovalTestPrincipal }
        Mock Register-ScheduledTask {}
        Mock Start-ScheduledTask {
            Write-Fixture (Join-Path $Prefix 'uninstall\receipt\credentials-system.json') '{"removed":2,"warnings":[]}'
        }
        Mock Stop-ScheduledTask {}
        Mock Unregister-ScheduledTask {}
        $definition = $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Remove-RemovalCredentials' }, $false)
        $body = $definition.Body.Extent.Text
        $realCleanup = [scriptblock]::Create('param([string]$Path, [bool]$AsSystem)' + "`n" + $body.Substring(1, $body.Length - 2))
        $warnings = @(& $realCleanup $Prefix $true)
        $warnings.Count | Should Be 0
        Assert-MockCalled New-ScheduledTaskPrincipal -Times 1 -Exactly -Scope It -ParameterFilter { $UserId -eq 'SYSTEM' -and $LogonType -eq 'ServiceAccount' }
        Assert-MockCalled Unregister-ScheduledTask -Times 1 -Exactly -Scope It
    }

    It 'embeds exactly the reviewed offline files in the downloadable installer' {
        $installer = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'install.ps1'))
        $tree = [Management.Automation.Language.Parser]::ParseInput($installer, [ref]$null, [ref]$null)
        $definition = $tree.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-RemovalBundle' }, $false)
        . ([scriptblock]::Create($definition.Extent.Text))
        Write-RemovalBundle $Prefix
        [IO.File]::ReadAllText((Join-Path $Prefix 'uninstall\remove.ps1')).Replace("`r`n", "`n") | Should Be ($source.Replace("`r`n", "`n"))
        [IO.File]::ReadAllText((Join-Path $Prefix 'uninstall\inventory.py')).Replace("`r`n", "`n") | Should Be ([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'uninstall_inventory.py')).Replace("`r`n", "`n"))
    }
}
