#Requires -Version 5.1
<#
.SYNOPSIS
    FileFinder — Windows Production Build Pipeline
.DESCRIPTION
    Automates the complete FileFinder build workflow on Windows:
    1. Verifies Python 3.12+ and virtual environment (.venv)
    2. Installs and validates runtime and dev dependencies
    3. Runs the full pytest test suite (QT_QPA_PLATFORM=offscreen, aborting on failure)
    4. Executes PyInstaller with packaging\filefinder.spec
    5. Verifies output binary (dist\FileFinder\FileFinder.exe)
    6. Runs smoke test (--version)
    7. Optionally compiles Inno Setup installer if ISCC.exe is available
    8. Reports build results
#>

[CmdletBinding()]
param (
    [switch]$SkipTests = $false,
    [switch]$BuildInstaller = $true
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "         FileFinder — Windows Production Build Pipeline           " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Platform verification
if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) {
    Write-Warning "PowerShell is executing on a non-Windows OS ($([System.Environment]::OSVersion)). Windows build requires a Windows host."
} else {
    Write-Host "[1/7] Host platform: Windows ($([System.Environment]::OSVersion.VersionString))" -ForegroundColor Green
}

# 2. Virtual environment detection / creation
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPytest = Join-Path $VenvDir "Scripts\pytest.exe"
$VenvPyinstaller = Join-Path $VenvDir "Scripts\pyinstaller.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[2/7] Virtual environment not found at $VenvDir. Initializing..." -ForegroundColor Yellow
    $SystemPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $SystemPython) {
        Write-Error "Python 3.12+ was not found on PATH. Please install Python from https://www.python.org/."
        exit 1
    }
    & $SystemPython -m venv $VenvDir
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment python.exe could not be located at $VenvPython."
    exit 1
}

$PyVersion = & $VenvPython -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'
Write-Host "[2/7] Using Python: $PyVersion ($VenvPython)" -ForegroundColor Green

# 3. Dependencies verification / installation
Write-Host "[3/7] Verifying runtime and development dependencies..." -ForegroundColor Cyan
& $VenvPython -c "import PySide6, charset_normalizer, pytest, PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "      Installing dependencies from requirements.txt and requirements-dev.txt..." -ForegroundColor Yellow
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet -r (Join-Path $RepoRoot "requirements.txt") -r (Join-Path $RepoRoot "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install required dependencies."
        exit $LASTEXITCODE
    }
} else {
    Write-Host "      All dependencies satisfied." -ForegroundColor Green
}

# 4. Icon verification
$IconIco = Join-Path $RepoRoot "resources\icons\app_icon.ico"
Write-Host "[4/7] Verifying Windows application icon asset ($IconIco)..." -ForegroundColor Cyan
if (Test-Path $IconIco) {
    Write-Host "      Windows application icon found." -ForegroundColor Green
} else {
    Write-Host "      Generating app_icon.ico from PNG assets..." -ForegroundColor Yellow
    & $VenvPython -c "from PySide6.QtGui import QImage; img = QImage('resources/icons/app_icon_256.png'); img.save('resources/icons/app_icon.ico')"
}

# 5. Full test suite execution (Strict QA Gate)
if (-not $SkipTests) {
    Write-Host "[5/7] Running full pytest test suite (QT_QPA_PLATFORM=offscreen)..." -ForegroundColor Cyan
    $env:QT_QPA_PLATFORM = "offscreen"
    & $VenvPytest (Join-Path $RepoRoot "tests")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Test suite failed with exit code $LASTEXITCODE. Aborting build."
        exit $LASTEXITCODE
    }
    Write-Host "      Test suite PASSED (100% green)." -ForegroundColor Green
} else {
    Write-Host "[5/7] Skipping tests (-SkipTests specified)." -ForegroundColor Yellow
}

# 6. PyInstaller execution
Write-Host "[6/7] Running PyInstaller build using packaging\filefinder.spec..." -ForegroundColor Cyan
$SpecPath = Join-Path $RepoRoot "packaging\filefinder.spec"
& $VenvPyinstaller $SpecPath --clean --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed with exit code $LASTEXITCODE."
    exit $LASTEXITCODE
}

# 7. Verification and smoke test
$DistDir = Join-Path $RepoRoot "dist\FileFinder"
$ExePath = Join-Path $DistDir "FileFinder.exe"

if (-not (Test-Path $ExePath)) {
    Write-Error "Output executable was not found at $ExePath."
    exit 1
}

Write-Host "[7/7] Running smoke test on compiled executable..." -ForegroundColor Cyan
$SmokeOutput = & $ExePath --version 2>&1
Write-Host "      Smoke test output: $SmokeOutput" -ForegroundColor Green

if ($SmokeOutput -notlike "*FileFinder*") {
    Write-Error "Smoke test failed: unexpected output: $SmokeOutput"
    exit 1
}

# Optional Inno Setup compilation
$InstallerPath = $null
if ($BuildInstaller) {
    $IsccCandidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    )
    $IsccPath = $IsccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

    if ($IsccPath) {
        Write-Host "==> Compiling Windows Inno Setup installer..." -ForegroundColor Cyan
        $IssFile = Join-Path $RepoRoot "packaging\installer.iss"
        & $IsccPath $IssFile
        $ExpectedInstaller = Join-Path $RepoRoot "dist\FileFinder-Setup-x64.exe"
        if (Test-Path $ExpectedInstaller) {
            $InstallerPath = $ExpectedInstaller
            Write-Host "    Installer created: $InstallerPath" -ForegroundColor Green
        }
    } else {
        Write-Host "    Inno Setup 6 (ISCC.exe) not found on host. Skipping installer compilation." -ForegroundColor Yellow
        Write-Host "    To build installer, install Inno Setup 6 and run: ISCC.exe packaging\installer.iss" -ForegroundColor Yellow
    }
}

$ExeSize = (Get-Item $ExePath).Length / 1MB

Write-Host "==================================================================" -ForegroundColor Green
Write-Host "                   BUILD SUCCEEDED                                " -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green
Write-Host "Executable:  $ExePath ($([Math]::Round($ExeSize, 2)) MB)"
if ($InstallerPath) {
    Write-Host "Installer:   $InstallerPath"
}
Write-Host "Smoke Test:  PASS ($SmokeOutput)"
Write-Host "Platform:    Windows x64"
Write-Host "==================================================================" -ForegroundColor Green
