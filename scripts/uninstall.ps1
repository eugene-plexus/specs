<# Offline removal, also used by Windows Settings > Apps.
   The installer embeds this file. Tests import functions without running main. #>
[CmdletBinding()]
param(
    [string]$Prefix = (Split-Path -Parent $PSScriptRoot),
    [switch]$Interactive,
    [switch]$PurgeDownloads,
    [switch]$PurgeData,
    [switch]$Register,
    [switch]$SystemInstall
)
$ErrorActionPreference = 'Stop'

function Get-RemovalId([string]$Path) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($Path).ToLowerInvariant())))).Replace('-', '').Substring(0, 16) }
    finally { $hash.Dispose() }
}

function Test-RemovalAdmin {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RemovalCommand([string]$Path, [bool]$Elevate) {
    $file = (Join-Path $Path 'uninstall\remove.ps1').Replace("'", "''")
    $body = "& '$file' -Interactive"
    if ($Elevate) {
        $inner = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($body))
        $body = "try { `$p = Start-Process powershell.exe -ArgumentList '-NoProfile -ExecutionPolicy Bypass -EncodedCommand $inner' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit `$p.ExitCode } catch { exit 1 }"
    }
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($body))
    return ('"{0}" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand {1}' -f (Join-Path $PSHOME 'powershell.exe'), $encoded)
}

function Register-Removal([string]$Path, [bool]$ForMachine) {
    $hive = if ($ForMachine) { 'HKLM:' } else { 'HKCU:' }
    $key = "$hive\Software\Microsoft\Windows\CurrentVersion\Uninstall\EugenePlexus-$(Get-RemovalId $Path)"
    New-Item -Path $key -Force | Out-Null
    $values = @{
        DisplayName = 'Eugene Plexus'; Publisher = 'Eugene Plexus'; InstallLocation = $Path
        UninstallString = (Get-RemovalCommand $Path $ForMachine)
        URLInfoAbout = 'https://eugeneplexus.com'; Comments = 'Remove Eugene; choose whether to keep settings and downloads.'
    }
    foreach ($name in $values.Keys) { New-ItemProperty -LiteralPath $key -Name $name -Value $values[$name] -PropertyType String -Force | Out-Null }
    foreach ($name in @('NoModify', 'NoRepair')) { New-ItemProperty -LiteralPath $key -Name $name -Value 1 -PropertyType DWord -Force | Out-Null }
    $engine = if ($ForMachine) { Join-Path $Path 'engines' } elseif ($env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT) { $env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT } else { Join-Path $env:USERPROFILE '.eugene-plexus\engines' }
    [IO.File]::WriteAllText((Join-Path $Path 'uninstall\install-info.json'), (@{ engineRoot = $engine } | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}

function Test-RemovalWithin([string]$Path, [string]$Root) {
    $p = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $r = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    return $p.Equals($r, [StringComparison]::OrdinalIgnoreCase) -or $p.StartsWith($r + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-RemovalPath([string]$Path, [string]$Root, [switch]$External) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if (-not $full -or $full -eq [IO.Path]::GetPathRoot($full).TrimEnd('\') -or
        (Test-RemovalWithin $rootFull $full) -or $full -eq $env:USERPROFILE -or
        $full -eq $env:ProgramData -or (Test-RemovalWithin $full $env:windir)) {
        throw "Refusing unsafe removal path: $full"
    }
    if (-not $External -and -not (Test-RemovalWithin $full $rootFull)) { throw "Removal path is outside $rootFull`: $full" }
    # A receipt cannot redirect deletion through a parent junction.
    $cursor = $full
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Kept linked path: $full" }
        $cursor = Split-Path -Parent $cursor
    }
    return $full
}

function Remove-RemovalTree([string]$Path) {
    # Do not use PS 5.1 recursive deletion across junctions. Remove links,
    # never their targets; every top-level path was checked by the caller.
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return }
    if ($item.PSIsContainer) {
        if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            foreach ($child in Get-ChildItem -LiteralPath $Path -Force) { Remove-RemovalTree $child.FullName }
        }
        [IO.Directory]::Delete($item.FullName)
    } else { Remove-Item -LiteralPath $item.FullName -Force }
}

function Get-RemovalSize([string[]]$Paths) {
    [long]$size = 0
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        if (-not $item -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
        if ($item.PSIsContainer) { $size += Get-RemovalSize @((Get-ChildItem -LiteralPath $path -Force -ErrorAction Stop).FullName) }
        else { $size += $item.Length }
    }
    return $size
}

function Format-RemovalSize([string[]]$Paths) {
    try { return "$([math]::Round((Get-RemovalSize $Paths) / 1GB, 2)) GB" }
    catch { return 'size unavailable' }
}

function Show-RemovalChoice($Plan, [string]$Path) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object Windows.Forms.Form
    $form.Text = 'Remove Eugene Plexus'; $form.ClientSize = New-Object Drawing.Size(580, 340)
    $form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false
    $label = New-Object Windows.Forms.Label
    $label.SetBounds(20, 18, 540, 102)
    $softwareSize = Format-RemovalSize @($Plan.software)
    $label.Text = "Remove Eugene from this computer?`r`n`r`nSoftware: $softwareSize`r`n$Path`r`nOriginal model folders will be kept."
    $form.Controls.Add($label)
    $data = New-Object Windows.Forms.CheckBox
    $data.SetBounds(20, 125, 540, 48)
    $data.Text = "Also delete settings, app data and logs`r`n$(Format-RemovalSize @($Plan.data))"
    $downloads = New-Object Windows.Forms.CheckBox
    $downloads.SetBounds(20, 179, 540, 48)
    $downloads.Text = "Also delete downloaded engines and model copies`r`n$(Format-RemovalSize @($Plan.downloads))"
    $form.Controls.AddRange(@($data, $downloads))
    $remove = New-Object Windows.Forms.Button
    $remove.Text = 'Remove Eugene'; $remove.SetBounds(315, 280, 135, 34); $remove.DialogResult = 'OK'
    $cancel = New-Object Windows.Forms.Button
    $cancel.Text = 'Cancel'; $cancel.SetBounds(460, 280, 100, 34); $cancel.DialogResult = 'Cancel'
    $form.Controls.AddRange(@($remove, $cancel)); $form.CancelButton = $cancel; $form.AcceptButton = $cancel
    try {
        if ($form.ShowDialog() -ne 'OK') { return $null }
        return @{ Data = $data.Checked; Downloads = $downloads.Checked }
    } finally { $form.Dispose() }
}

function Get-RemovalPlan([string]$Path) {
    $receipt = Join-Path $Path 'uninstall\receipt'
    $file = Join-Path $receipt 'inventory.json'
    $python = Join-Path $Path 'venv\Scripts\python.exe'
    if ((Test-Path -LiteralPath $file) -and ((Test-Path -LiteralPath (Join-Path $receipt 'removed.txt')) -or -not (Test-Path -LiteralPath $python))) {
        return (Get-Content -Raw -Encoding UTF8 -LiteralPath $file | ConvertFrom-Json)
    }
    New-Item -ItemType Directory -Path $receipt -Force | Out-Null
    if (Test-Path -LiteralPath $python) {
        & $python -I (Join-Path $Path 'uninstall\inventory.py') --prefix $Path --output $file
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $file)) { throw 'Could not inventory this installation. Nothing was removed.' }
        return (Get-Content -Raw -Encoding UTF8 -LiteralPath $file | ConvertFrom-Json)
    }
    # Broken installation: remove only known software; never guess which
    # external folders or personal data belonged to it.
    $plan = @{ version = 1; prefix = $Path; software = @('venv','pythons','bin','.cache\uv','update') | ForEach-Object { Join-Path $Path $_ }
        data = @(); downloads = @(); protected = @((Join-Path $Path 'models'))
        warnings = @('Python is missing. Settings, downloads and credentials were kept; review the remaining folder.') }
    [IO.File]::WriteAllText($file, ($plan | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    return [pscustomobject]$plan
}

function Stop-RemovalProcesses([string]$Path) {
    $processes = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and $_.ExecutablePath -and (Test-RemovalWithin $_.ExecutablePath $Path)
    })
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $process.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
    }
    if (Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.ExecutablePath -and (Test-RemovalWithin $_.ExecutablePath $Path) }) {
        throw 'A Eugene process is still running. Close it and run removal again.'
    }
}

function Remove-RemovalCredentials([string]$Path, [bool]$AsSystem) {
    $python = Join-Path $Path 'venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { return @('Credential cleanup could not run: the installed Python is missing.') }
    $helper = Join-Path $Path 'uninstall\inventory.py'
    $output = Join-Path $Path "uninstall\receipt\credentials-$(if ($AsSystem) { 'system' } else { 'user' }).json"
    if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Force }
    $argsText = '-I "{0}" --keyring-only --prefix "{1}" --output "{2}"' -f $helper, $Path, $output
    if ($AsSystem) {
        $task = 'EugenePlexusRemoval-' + [guid]::NewGuid().ToString('N')
        try {
            $action = New-ScheduledTaskAction -Execute $python -Argument $argsText
            $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
            Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Force | Out-Null
            Start-ScheduledTask -TaskName $task
            $deadline = (Get-Date).AddSeconds(45)
            do { Start-Sleep -Milliseconds 250 } while (-not (Test-Path -LiteralPath $output) -and (Get-Date) -lt $deadline)
            if (-not (Test-Path -LiteralPath $output)) { throw 'SYSTEM credential cleanup did not finish in 45 seconds.' }
        } finally {
            Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
        }
    } else {
        & $python -I $helper --keyring-only --prefix $Path --output $output
        if ($LASTEXITCODE -ne 0) { throw 'User credential cleanup failed.' }
    }
    $result = Get-Content -Raw -Encoding UTF8 -LiteralPath $output | ConvertFrom-Json
    return @($result.warnings)
}

function Remove-RemovalFirewall {
    $rules = @(Get-NetFirewallRule -ErrorAction Stop | Where-Object { $_.DisplayName -eq 'Eugene Plexus' })
    if (-not $rules.Count) { return }
    if (Test-RemovalAdmin) { $rules | Remove-NetFirewallRule -ErrorAction Stop; return }
    # Only this machine-wide firewall operation needs elevation for a
    # per-user install; do not switch accounts for its data or vault.
    $code = "try { Get-NetFirewallRule -ErrorAction Stop | Where-Object { `$_.DisplayName -eq 'Eugene Plexus' } | Remove-NetFirewallRule -ErrorAction Stop } catch { exit 1 }"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
    $child = Start-Process powershell.exe -ArgumentList "-NoProfile -EncodedCommand $encoded" -Verb RunAs -WindowStyle Hidden -Wait -PassThru
    if ($child.ExitCode -ne 0) { throw 'Administrator firewall cleanup failed or was cancelled.' }
}

function Remove-RemovalIntegration([string]$Path) {
    $services = @(Get-CimInstance Win32_Service | Where-Object {
        ($_.Name -eq 'EugenePlexusAgent' -or $_.Name -like 'EugenePlexusApp-*') -and
        $_.PathName -and $_.PathName.IndexOf($Path.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    foreach ($service in $services) {
        if ($service.State -ne 'Stopped') { Stop-Service -Name $service.Name -Force }
        & sc.exe delete $service.Name | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Windows could not unregister $($service.Name)." }
    }
    foreach ($name in @('EugenePlexusAgent', 'EugenePlexusTray')) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task -and @($task.Actions | Where-Object { $_.Execute -and (Test-RemovalWithin $_.Execute $Path) }).Count) {
            Stop-ScheduledTask -TaskName $name
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
        }
    }
    Stop-RemovalProcesses $Path
    foreach ($scope in @('User', 'Machine')) {
        if ($scope -eq 'Machine' -and -not (Test-RemovalAdmin)) { continue }
        $cfg = [Environment]::GetEnvironmentVariable('EUGENE_PLEXUS_AGENT_CONFIG_FILE', $scope)
        if ($cfg -and (Test-RemovalWithin $cfg $Path)) {
            foreach ($name in @('EUGENE_PLEXUS_AGENT_CONFIG_FILE','EUGENE_PLEXUS_AGENT_BIND_HOST','EUGENE_PLEXUS_AGENT_BIND_PORT','EUGENE_PLEXUS_AGENT_ENGINE_ROOT','EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS')) {
                [Environment]::SetEnvironmentVariable($name, $null, $scope)
            }
        }
    }
    foreach ($programs in @((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'), (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'))) {
        $link = Join-Path $programs 'Eugene Plexus.lnk'
        if (Test-Path -LiteralPath $link) {
            $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
            if ($shortcut.TargetPath -and (Test-RemovalWithin $shortcut.TargetPath $Path)) { Remove-Item -LiteralPath $link -Force }
        }
    }
}

function Remove-RemovalFiles($Plan, [string]$Path, [bool]$Downloads, [bool]$Data) {
    $warnings = New-Object Collections.Generic.List[string]
    foreach ($kind in @('software', 'downloads', 'data')) {
        if (($kind -eq 'downloads' -and -not $Downloads) -or ($kind -eq 'data' -and -not $Data)) { continue }
        foreach ($original in $Plan.$kind) {
            $candidate = if (Test-RemovalWithin $original $Plan.prefix) { $Path + $original.Substring($Plan.prefix.TrimEnd('\').Length) } else { $original }
            try {
                $full = Assert-RemovalPath $candidate $Path -External:($kind -eq 'downloads')
                foreach ($protected in $Plan.protected) {
                    $protectedPath = if (Test-RemovalWithin $protected $Plan.prefix) { $Path + $protected.Substring($Plan.prefix.TrimEnd('\').Length) } else { $protected }
                    if ((Test-RemovalWithin $full $protectedPath) -or (Test-RemovalWithin $protectedPath $full)) { throw "Kept $full`: it overlaps an original model folder." }
                }
                Remove-RemovalTree $full
            } catch { $warnings.Add($_.Exception.Message) }
        }
    }
    return $warnings.ToArray()
}

function Invoke-Removal([string]$Path, [bool]$ShowWindow, [bool]$Downloads, [bool]$Data) {
    $Path = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not (Test-Path -LiteralPath $Path)) { Write-Host "Nothing installed at $Path"; return }
    if ($Path -eq $env:USERPROFILE -or $Path -eq $env:ProgramData -or
        $Path -eq $env:ProgramFiles -or (Test-RemovalWithin $Path $env:windir) -or
        $Path -eq [IO.Path]::GetPathRoot($Path).TrimEnd('\')) { throw "Not an installation folder: $Path" }
    if (-not ((Test-Path -LiteralPath (Join-Path $Path 'agent.yaml')) -or
        (Test-Path -LiteralPath (Join-Path $Path 'node.yaml')) -or
        (Test-Path -LiteralPath (Join-Path $Path 'bin\uv.exe')) -or
        (Test-Path -LiteralPath (Join-Path $Path 'uninstall\receipt\inventory.json')))) {
        throw "No Eugene installation or removal receipt at $Path. Nothing was removed."
    }
    $cursor = $Path
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Refusing a linked installation folder: $Path" }
        $cursor = Split-Path -Parent $cursor
    }
    $plan = Get-RemovalPlan $Path
    if ($ShowWindow) {
        $display = @{}
        foreach ($kind in @('software','data','downloads')) {
            $display[$kind] = @($plan.$kind | ForEach-Object {
                if (Test-RemovalWithin $_ $plan.prefix) { $Path + $_.Substring($plan.prefix.TrimEnd('\').Length) } else { $_ }
            })
        }
        $choice = Show-RemovalChoice $display $Path
        if ($null -eq $choice) { return }
        $Downloads = $choice.Downloads; $Data = $choice.Data
    }
    $warnings = New-Object Collections.Generic.List[string]
    foreach ($warning in $plan.warnings) { $warnings.Add($warning) }
    $removedBefore = Test-Path -LiteralPath (Join-Path $Path 'uninstall\receipt\removed.txt')
    if (-not $removedBefore) {
        $service = Get-CimInstance Win32_Service -Filter "Name='EugenePlexusAgent'" | Where-Object { $_.PathName -and $_.PathName.IndexOf($Path + '\', [StringComparison]::OrdinalIgnoreCase) -ge 0 }
        # Stop first, while Python and the service account's credential vault
        # still exist. A temporary SYSTEM task opens that account's vault.
        if ($service -and $service.State -ne 'Stopped') { Stop-Service -Name $service.Name -Force }
        try { foreach ($w in @(Remove-RemovalCredentials $Path $false)) { $warnings.Add($w) } } catch { $warnings.Add($_.Exception.Message) }
        if ($service -and $service.StartName -eq 'LocalSystem') {
            try { foreach ($w in @(Remove-RemovalCredentials $Path $true)) { $warnings.Add($w) } } catch { $warnings.Add($_.Exception.Message) }
        }
        Remove-RemovalIntegration $Path
        try {
            # The legacy rule is shared: retain it while another Eugene
            # service/task still uses this machine.
            $other = @(Get-CimInstance Win32_Service -Filter "Name='EugenePlexusAgent'" | Where-Object { $_.PathName -and $_.PathName.IndexOf($Path + '\', [StringComparison]::OrdinalIgnoreCase) -lt 0 }).Count -gt 0 -or
                [bool](Get-ScheduledTask -TaskName 'EugenePlexusAgent' -ErrorAction SilentlyContinue)
            if (-not $other) {
                Remove-RemovalFirewall
            } else { $warnings.Add('The shared Eugene firewall rule was kept for another installation.') }
        } catch { $warnings.Add("Firewall cleanup failed: $($_.Exception.Message). Remove the 'Eugene Plexus' rule in Windows Defender Firewall.") }
        [IO.File]::WriteAllLines((Join-Path $Path 'uninstall\receipt\integration-warnings.txt'), $warnings.ToArray())
    } else {
        $prior = Join-Path $Path 'uninstall\receipt\integration-warnings.txt'
        if (Test-Path -LiteralPath $prior) {
            foreach ($w in Get-Content -LiteralPath $prior) { $warnings.Add("Previously reported: $w") }
        }
    }
    foreach ($w in @(Remove-RemovalFiles $plan $Path $Downloads $Data)) { $warnings.Add($w) }
    # Retain the offline helper with the data, but remove the OS app entry.
    foreach ($hive in @('HKCU:', 'HKLM:')) {
        if ($hive -eq 'HKLM:' -and -not (Test-RemovalAdmin)) { continue }
        $key = "$hive\Software\Microsoft\Windows\CurrentVersion\Uninstall\EugenePlexus-$(Get-RemovalId $plan.prefix)"
        if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force }
    }
    $keep = $Path
    if (-not $removedBefore -and $Path -notmatch '\.removed-\d+$') {
        $keep = "$Path.removed-$(Get-Date -Format yyyyMMddHHmmss)"
        # Verify the sibling destination and source before the directory move.
        if ((Split-Path -Parent $keep) -ne (Split-Path -Parent $Path)) { throw 'Invalid removal destination.' }
        try { [IO.Directory]::Move($Path, $keep) }
        catch {
            $detail = "Startup is disabled, but retained files could not be moved from $Path`: $($_.Exception.Message). Close programs using that folder and run its uninstall\remove.ps1 again."
            [IO.File]::WriteAllText((Join-Path $Path 'uninstall\receipt\report.txt'), $detail + "`r`n" + ($warnings -join "`r`n"), [Text.UTF8Encoding]::new($false))
            throw $detail
        }
    }
    $receipt = Join-Path $keep 'uninstall\receipt'
    [IO.File]::WriteAllText((Join-Path $receipt 'removed.txt'), 'Startup disabled; see report.txt for any remaining work.')
    $remainingDownloads = @($plan.downloads | ForEach-Object {
        if (Test-RemovalWithin $_ $plan.prefix) { $keep + $_.Substring($plan.prefix.TrimEnd('\').Length) } else { $_ }
    } | Where-Object { Test-Path -LiteralPath $_ })
    $report = "Eugene's removal finished$(if ($warnings.Count) { ' with items to review' }).`r`nRetained files and cleanup utility: $keep`r`nOriginal model folders were kept.`r`n"
    if ($remainingDownloads.Count) { $report += "Retained downloads:`r`n$($remainingDownloads -join "`r`n")`r`n" }
    $report += "To change your cleanup choices, open PowerShell$(if (Test-RemovalAdmin) { ' using Run as administrator' }) and run:`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$keep\uninstall\remove.ps1`" -Interactive`r`n"
    if ($warnings.Count) { $report += "Items to review:`r`n$($warnings -join "`r`n")`r`n" }
    [IO.File]::WriteAllText((Join-Path $receipt 'report.txt'), $report, [Text.UTF8Encoding]::new($false))
    Write-Host $report
    if ($ShowWindow) { [Windows.Forms.MessageBox]::Show($report, 'Eugene removal', 'OK', $(if ($warnings.Count) { 'Warning' } else { 'Information' })) | Out-Null }
    if ($warnings.Count) { $global:EugeneRemovalIncomplete = $true }
}

# --- removal entrypoint (tests import only the functions above) ---
try {
    if ($Register) { Register-Removal $Prefix $SystemInstall; return }
    $service = Get-CimInstance Win32_Service -Filter "Name='EugenePlexusAgent'" -ErrorAction SilentlyContinue
    $needsAdmin = (Test-RemovalWithin $Prefix $env:ProgramData) -or
        ($service -and $service.PathName -and $service.PathName.IndexOf($Prefix.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -ge 0)
    if ($needsAdmin -and -not (Test-RemovalAdmin)) {
        $body = "& '$($PSCommandPath.Replace("'", "''"))' -Prefix '$($Prefix.Replace("'", "''"))' -Interactive:`$$($Interactive.IsPresent) -PurgeDownloads:`$$($PurgeDownloads.IsPresent) -PurgeData:`$$($PurgeData.IsPresent)"
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($body))
        $child = Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded" -Verb RunAs -WindowStyle Hidden -Wait -PassThru
        exit $child.ExitCode
    }
    Set-Location -LiteralPath ([IO.Path]::GetTempPath())
    Invoke-Removal $Prefix $Interactive $PurgeDownloads $PurgeData
    if ($global:EugeneRemovalIncomplete) { exit 1 }
} catch {
    $message = "Removal did not finish: $($_.Exception.Message)"
    Write-Host $message -ForegroundColor Red
    if ($Interactive) { Add-Type -AssemblyName System.Windows.Forms; [Windows.Forms.MessageBox]::Show($message, 'Eugene removal', 'OK', 'Error') | Out-Null }
    exit 1
}
