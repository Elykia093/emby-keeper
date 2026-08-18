# A script to download and install dependencies listed in a requirements file from pip
# Usage: .\download_deps.ps1 [-RequirementsFile <RequirementsFile>] [-PipPath <PipPath>]
# Example: .\download_deps.ps1 requirements.txt C:\Python\3.12.10\Scripts\pip.exe

param(
    [Parameter()]
    [string]$RequirementsFile="requirements.txt",
    [Parameter()]
    [string]$PythonPath="python.exe",
    [Parameter()]
    [switch]$Update = $false,
    [Parameter()]
    [switch]$NoMirror = $false
)

Write-Host "Installing dependencies"
if ($Update) {
    if ($NoMirror) {
        & $PythonPath -m pip install -U embykeeper --no-warn-script-location
    } else {
        & $PythonPath -m pip install -i "https://mirrors.aliyun.com/pypi/simple" -U embykeeper --no-warn-script-location
    }
} else {
    if ($NoMirror) {
        & $PythonPath -m pip install -r $RequirementsFile --no-warn-script-location
    } else {
        & $PythonPath -m pip install -i "https://mirrors.aliyun.com/pypi/simple" -r $RequirementsFile --no-warn-script-location
    }
}

$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "Done installing dependencies"
} else {
    Write-Host "Failed to install dependencies, exit code: $exitCode"
}
exit $exitCode
