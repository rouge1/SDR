<#
    One-shot Windows setup for the launcher: conda, the 'gnu' environment, and
    a check that GNU Radio and the HackRF backend actually import.

    Idempotent - re-run it after a pull and it updates the environment in place
    rather than rebuilding it.

        powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1

    It does NOT bind the WinUSB driver to the HackRF; that needs a physical
    device present and is a one-time manual step with Zadig. The script says so
    at the end.
#>
[CmdletBinding()]
param(
    # Where to put conda if none is installed. Keep it free of spaces: the
    # Miniforge installer is NSIS and its /D= switch cannot be quoted.
    [string]$CondaRoot = "$env:USERPROFILE\miniforge3",
    [string]$EnvName   = 'gnu',
    [switch]$Force      # rebuild the environment from scratch
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Repo 'environment-windows.yml'

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }

if (-not (Test-Path $EnvFile)) { throw "environment-windows.yml not found next to the repo at $Repo" }

# ---------------------------------------------------------------- conda -----
function Find-Conda {
    if ($env:CONDA_EXE -and (Test-Path $env:CONDA_EXE)) { return $env:CONDA_EXE }
    $candidates = @(
        "$CondaRoot\Scripts\conda.exe",
        "$env:USERPROFILE\miniforge3\Scripts\conda.exe",
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "$env:LOCALAPPDATA\miniforge3\Scripts\conda.exe",
        "C:\ProgramData\miniforge3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $cmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$conda = Find-Conda
if (-not $conda) {
    Say "no conda found - installing Miniforge to $CondaRoot"
    # Miniforge rather than Miniconda: it defaults to conda-forge, which is the
    # only channel carrying GNU Radio, and carries no Anaconda terms-of-service
    # prompt to trip a non-interactive install.
    $url = 'https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe'
    $exe = Join-Path $env:TEMP 'Miniforge3-Windows-x86_64.exe'
    Say "downloading $url"
    $ProgressPreference = 'SilentlyContinue'   # the progress bar makes this ~10x slower
    Invoke-WebRequest -Uri $url -OutFile $exe
    Say "installing silently (this takes a couple of minutes)"
    # /D= must come last and must not be quoted - NSIS parses the rest of the
    # line as the path.
    $p = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList `
        "/S", "/InstallationType=JustMe", "/RegisterPython=0", "/AddToPath=0", "/D=$CondaRoot"
    if ($p.ExitCode -ne 0) { throw "Miniforge installer exited $($p.ExitCode)" }
    Remove-Item $exe -ErrorAction SilentlyContinue
    $conda = Find-Conda
    if (-not $conda) { throw "Miniforge installed but conda.exe still not found under $CondaRoot" }
}
Say "conda: $conda"
& $conda --version

# ------------------------------------------------------------ environment ---
$envExists = (& $conda env list) -match "^\s*$([regex]::Escape($EnvName))\s"

if ($envExists -and $Force) {
    Say "removing existing '$EnvName' environment (-Force)"
    & $conda env remove -n $EnvName -y
    $envExists = $false
}

if ($envExists) {
    Say "updating existing '$EnvName' environment from environment-windows.yml"
    & $conda env update -n $EnvName -f $EnvFile --prune
} else {
    Say "creating '$EnvName' environment - this pulls ~2 GB and takes a while"
    & $conda env create -f $EnvFile -n $EnvName
}
if ($LASTEXITCODE -ne 0) { throw "conda failed to build the environment (exit $LASTEXITCODE)" }

# ---------------------------------------------------------------- verify ----
Say "verifying the install"
$check = @'
import sys, os
print("python      ", sys.version.split()[0], sys.executable)
import numpy, scipy, PIL
print("numpy       ", numpy.__version__)
print("scipy       ", scipy.__version__)
print("pillow      ", PIL.__version__)
from PyQt5 import QtCore
print("PyQt5       ", QtCore.PYQT_VERSION_STR)
from gnuradio import gr, analog, filter, blocks, audio
print("gnuradio    ", gr.version())
from gnuradio import qtgui, soapy
print("gr-qtgui    ", "ok")
print("gr-soapy    ", "ok")
import SoapySDR
print("SoapySDR    ", SoapySDR.getAPIVersion())
mods = SoapySDR.listModules()
print("soapy mods  ", len(mods))
has_hackrf = any("hackrf" in m.lower() for m in mods)
print("hackrf mod  ", "present" if has_hackrf else "MISSING")
devs = SoapySDR.Device.enumerate()
print("soapy devs  ", len(devs))
for d in devs:
    print("             ", dict(d))
'@
$checkFile = Join-Path $env:TEMP 'sdr_verify.py'
Set-Content -Path $checkFile -Value $check -Encoding UTF8
& $conda run -n $EnvName --no-capture-output python $checkFile
$verifyCode = $LASTEXITCODE
Remove-Item $checkFile -ErrorAction SilentlyContinue

Write-Host ""
if ($verifyCode -ne 0) {
    Warn "verification failed - the environment built but something does not import."
    exit 1
}

Say "environment is ready"
Write-Host @"

Next:

  1. Start the launcher:
         powershell -ExecutionPolicy Bypass -File .\start_app.ps1

  2. For the HackRF, bind the WinUSB driver once, with the radio plugged in:
         - get Zadig from https://zadig.akeo.ie
         - Options > List All Devices
         - pick 'HackRF One', choose WinUSB, Install/Replace Driver
     Until that is done 'soapy devs' above reads 0 and the launcher reports
     'No HackRF One was detected on USB'.

  3. Point Settings > media directory at a folder of .wav files for the
     audio-fed apps.

"@
