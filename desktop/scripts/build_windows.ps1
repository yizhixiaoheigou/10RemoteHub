<#
Build the Windows debug package on the Windows machine.

Runs the automated checks, packages the app with PyInstaller, writes the zip
next to the build and records a read-only diagnose report. Nothing is installed,
no driver is bound and no system setting is changed.
#>
# -IndexUrl: empty tries pypi.org first, then the Tsinghua mirror used on CN networks.
param(
    [string]$Python = "py",
    [switch]$SkipTests,
    [string]$IndexUrl = "",
    [Parameter(Mandatory=$true)][string]$LicenseSupplement
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
$Desktop = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Project = Split-Path -Parent $Desktop
$Artifacts = Join-Path $Project "artifacts"
New-Item -ItemType Directory -Force -Path $Artifacts | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $Artifacts "windows-build-$Stamp.log"
Start-Transcript -Path $Log -Force
try {
    Set-Location $Desktop
    $Venv = Join-Path $Desktop ".venv-win"
    $ProjectPython = Join-Path $Venv "Scripts\python.exe"
    if (!(Test-Path $ProjectPython)) {
        if ($Python -eq "py") { & py -3.12 -m venv $Venv } else { & $Python -m venv $Venv }
        if ($LASTEXITCODE -ne 0) { throw "Cannot create project Python environment" }
    }
    # The venv already ships pip and setuptools; only the project deps matter.
    function Install-Project([string]$Index) {
        $Extra = if ($Index) { @("--index-url", $Index) } else { @() }
        # Pipe pip output to the host: native stdout otherwise becomes part of
        # the function's return value and the exit code is read as an array.
        & $ProjectPython -m pip install --upgrade "pip>=26.2" @Extra | Out-Host
        if ($LASTEXITCODE -ne 0) { return $LASTEXITCODE }
        & $ProjectPython -m pip install --require-hashes -r requirements-windows-x64.lock @Extra | Out-Host
        if ($LASTEXITCODE -ne 0) { return $LASTEXITCODE }
        & $ProjectPython -m pip install --no-deps --no-build-isolation -e . | Out-Host
        return $LASTEXITCODE
    }
    if ($IndexUrl) {
        $Code = Install-Project $IndexUrl
    } else {
        $Code = Install-Project ""
        if ($Code -ne 0) {
            Write-Output "pypi.org unreachable; retrying with the Tsinghua mirror."
            $Code = Install-Project "https://pypi.tuna.tsinghua.edu.cn/simple"
        }
    }
    if ($Code -ne 0) { throw "Project dependency installation failed" }

    if (-not $SkipTests) {
        & $ProjectPython scripts/verify.py --output (Join-Path $Artifacts "verification-windows.json")
        if ($LASTEXITCODE -ne 0) { throw "Windows verification failed; build stopped" }
    }

    $Candidate = Join-Path $Desktop "dist\windows-candidate-$Stamp"
    if (Test-Path $Candidate) { throw "Candidate output already exists: $Candidate" }
    & $ProjectPython scripts/build.py --license-supplement $LicenseSupplement --dist-dir $Candidate
    if ($LASTEXITCODE -ne 0) { throw "Windows packaging failed" }

    $Dist = Join-Path $Candidate "10RemoteHub"
    $Exe = Join-Path $Dist "10RemoteHub.exe"
    if (!(Test-Path $Exe)) { throw "Packaging did not produce $Exe" }

    $Version = (Get-Content (Join-Path $Desktop "VERSION")).Trim()
    $Zip = Join-Path $Candidate "10RemoteHub-$Version-win-x64.zip"
    & $ProjectPython scripts/package_windows_zip.py $Dist $Zip
    if ($LASTEXITCODE -ne 0) { throw "ZIP creation failed" }
    & $ProjectPython scripts/release_policy.py $Zip
    if ($LASTEXITCODE -ne 0) { throw "Release content/license verification failed" }
    $Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash.toLower()
    Set-Content -Path (Join-Path $Candidate "SHA256SUMS") `
        -Value "$Hash  $(Split-Path -Leaf $Zip)" -Encoding ascii

    # Read-only report for the next round; no UI, no device capture.
    $Diagnose = Join-Path $Artifacts "windows-diagnose-$Stamp.json"
    $Process = Start-Process -FilePath $Exe -ArgumentList @('--diagnose', ('"' + $Diagnose + '"')) -Wait -PassThru
    if ($Process.ExitCode -ne 0 -or !(Test-Path -LiteralPath $Diagnose)) { throw "Packaged diagnostics failed" }

    Write-Output "EXE   : $Exe"
    Write-Output "ZIP   : $Zip"
    Write-Output "SHA256: $Hash"
    Write-Output "LOG   : $Log"
    Write-Output "No driver, system setting or startup item was installed or changed."
}
finally {
    Stop-Transcript
}
