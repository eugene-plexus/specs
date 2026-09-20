<# Execute the installer's actual isolation guards with side-effect spies.
   No service, registry write, package install or elevation is performed. #>
[CmdletBinding()]
param([string]$Installer)
$ErrorActionPreference = 'Stop'
if (-not $Installer) { $Installer = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'install.ps1' }
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Installer, [ref]$null, [ref]$errors)
if ($errors) { throw $errors }
$ifs = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.IfStatementAst] }, $true))
function Block([string]$needle) {
    $matches = @($ifs | Where-Object { $_.Extent.Text.Contains($needle) } | Sort-Object { $_.Extent.Text.Length })
    if (-not $matches) { throw "No guard containing $needle" }
    return $matches[0].Extent.Text
}
function Die($message) { throw $message }
function Say($message) {}
function Test-Path { param($LiteralPath) return $script:Existing }
function Get-AgentTask { return $true }
function Get-AgentService { return $true }
function Remove-Autostart { $script:Stopped = $true }
function Record-Write { $script:Writes++ }
function Get-OtherInstall { return @{ Prefix = 'C:\existing-install' } }

# The parameter guard is the OUTER if, not the rejection nested inside it.
$parameter = @($ifs | Where-Object {
    $_.Extent.StartLineNumber -lt 180 -and $_.Condition -eq $null -and
    $_.Extent.Text.StartsWith('if ($Isolated)')
})[0].Extent.Text
if (-not $parameter) { throw 'No isolated parameter guard' }
$Prefix = 'C:\new-acceptance-prefix'
$NoService = $true; $NoStart = $true; $Isolated = $true
$Migrate = $false; $Uninstall = $false; $Join = ''; $Verify = $false; $Detect = $false
$Existing = $false
& ([scriptblock]::Create($parameter))
foreach ($variable in @('NoService','NoStart','Prefix','Migrate','Uninstall','Join','Verify','Detect','Existing')) {
    $saved = Get-Variable $variable -ValueOnly
    $bad = switch ($variable) {
        'NoService' { $false }; 'NoStart' { $false }; 'Prefix' { '' }; 'Join' { 'http://root' }; default { $true }
    }
    Set-Variable $variable $bad
    $refused = $false
    try { & ([scriptblock]::Create($parameter)) } catch { $refused = $true }
    Set-Variable $variable $saved
    if (-not $refused) { throw "Isolated install accepted invalid $variable" }
}

$overlap = @($ifs | Where-Object {
    $_.Extent.Text.StartsWith('if ($Isolated)') -and
    $_.Extent.Text.Contains('the isolated prefix must be outside the existing install')
})[0].Extent.Text
if (-not $overlap) { throw 'No isolated prefix overlap guard' }
foreach ($candidate in @('C:\existing-install\child', 'C:\EXISTING-INSTALL', 'C:\')) {
    $Prefix = $candidate
    $refused = $false
    try { & ([scriptblock]::Create($overlap)) } catch { $refused = $true }
    if (-not $refused) { throw "Isolated install accepted overlapping prefix $candidate" }
}
$Prefix = 'C:\existing-install-other'
& ([scriptblock]::Create($overlap))

$stopGuard = Block 'stopping the running agent so its files can be replaced'
$envGuard = Block '[Environment]::SetEnvironmentVariable("EUGENE_PLEXUS_AGENT_CONFIG_FILE", $Config, "User")'
$portGuard = Block 'isolated install: no service, task, tray or persistent environment was changed'
foreach ($isolatedValue in @($true, $false)) {
    $Isolated = $isolatedValue
    $Stopped = $false; $Writes = 0; $Port = 19001; $IsElevated = $true
    & ([scriptblock]::Create($stopGuard))
    foreach ($guard in @($envGuard, $portGuard)) {
        # Replace only the external static call, preserving the real condition.
        $safe = $guard -replace '\[Environment\]::SetEnvironmentVariable\([^\r\n]+\)', 'Record-Write'
        & ([scriptblock]::Create($safe))
    }
    if ($Isolated -and ($Stopped -or $Writes)) { throw 'Isolated install touched shared state' }
    if (-not $Isolated -and (-not $Stopped -or $Writes -ne 3)) { throw 'Ordinary install behavior was lost' }
}
Write-Output 'PASS: isolated argument refusals, no autostart stop or persistent writes, ordinary behavior retained'
