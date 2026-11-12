<#
Collect a minimal Windows environment report for debugging.
No usernames, personal paths, device names/instance IDs, raw command output,
old logs, mappings, audio or dictated text are included in the archive.
#>
param(
    [string]$App = "",
    [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"
$Desktop = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Project = Split-Path -Parent $Desktop
if (-not $OutDir) { $OutDir = Join-Path $Project "artifacts" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$RunId = [Guid]::NewGuid().ToString("N")
$Work = Join-Path $env:TEMP "remotehub-diagnostics-$RunId"
New-Item -ItemType Directory -Path $Work | Out-Null

function Save-Json($Name, $Value) {
    $Path = Join-Path $Work $Name
    $Value | ConvertTo-Json -Depth 6 | Set-Content -Path $Path -Encoding utf8
}

# Report model/count information, never hardware instance IDs or friendly names.
function Device-Summary($Devices) {
    $Items = @($Devices | Where-Object { $null -ne $_ })
    return [ordered]@{
        Count = $Items.Count
        Ready = @($Items | Where-Object { $_.Status -eq 'OK' }).Count
        Other = @($Items | Where-Object { $_.Status -ne 'OK' }).Count
    }
}

try {
    Save-Json "system-os.json" (Get-CimInstance Win32_OperatingSystem |
        Select-Object Caption, Version, BuildNumber, OSArchitecture)
} catch { Save-Json "system-os.json" @{ Error = "query_failed" } }
Save-Json "system-session.json" ([pscustomobject]@{
    PowerShell = $PSVersionTable.PSVersion.ToString()
    IsAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
})

try {
    $Devices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop)
    Save-Json "usb-0416.json" (Device-Summary @($Devices |
        Where-Object { $_.InstanceId -like 'USB\VID_0416&PID_0602*' }))
    foreach ($Class in @('HIDClass', 'AudioEndpoint', 'MEDIA')) {
        Save-Json "$Class-summary.json" (Device-Summary @($Devices |
            Where-Object { $_.Class -eq $Class }))
    }
    $Voice = $Devices | Where-Object { $_.InstanceId -like 'USB\VID_0416&PID_0602&MI_03*' } |
        Select-Object -First 1
    $Driver = [ordered]@{ Present = [bool]$Voice; Service = "unknown"; Version = "unknown" }
    if ($Voice) {
        try {
            $Service = [string](Get-PnpDeviceProperty -InstanceId $Voice.InstanceId -KeyName 'DEVPKEY_Device_Service' -ErrorAction Stop).Data
            $Driver.Service = if ($Service -in @('WinUSB', 'HidUsb', 'USBCCGP')) { $Service } else { "other" }
            $Version = [string](Get-PnpDeviceProperty -InstanceId $Voice.InstanceId -KeyName 'DEVPKEY_Device_DriverVersion' -ErrorAction Stop).Data
            if ($Version -match '^\d+(\.\d+){1,3}$') { $Driver.Version = $Version }
        } catch { $Driver.Service = "query_failed" }
    }
    Save-Json "voice-interface-driver.json" $Driver
} catch { Save-Json "devices-error.json" @{ Error = "query_failed" } }

# Do not invoke older applications' --diagnose: their reports can contain paths.
$Candidates = @()
if ($App) { $Candidates += $App }
$Candidates += (Join-Path $Desktop "dist\windows\10RemoteHub\10RemoteHub.exe")
$Candidates += (Join-Path $env:LOCALAPPDATA "Programs\10RemoteHub\10RemoteHub.exe")
$Exe = $Candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if ($Exe) {
    try {
        Save-Json "app-file.json" @{ Found = $true; SHA256 = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash }
    } catch { Save-Json "app-file.json" @{ Error = "query_failed" } }
} else { Save-Json "app-file.json" @{ Found = $false } }

$Zip = Join-Path $OutDir "windows-environment-$RunId.zip"
Compress-Archive -Path (Join-Path $Work "*") -DestinationPath $Zip -CompressionLevel Optimal
Write-Output "REPORT: $Zip"
Write-Output "Review before sharing. Includes OS versions, device counts, driver status and application hash; no raw logs."
