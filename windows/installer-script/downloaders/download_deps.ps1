# Install the bundled version, or update to the latest stable fork release.

param(
    [Parameter()]
    [string]$RequirementsFile=(Join-Path $PSScriptRoot "..\script\requirements.txt"),
    [Parameter()]
    [string]$PythonPath="python.exe",
    [Parameter()]
    [switch]$Update = $false,
    [Parameter()]
    [switch]$NoMirror = $false
)

$ErrorActionPreference = "Stop"
$ExitCode = 1
$TempDirectory = $null
$WheelPath = $null
try {
    $Requirement = (Get-Content -LiteralPath $RequirementsFile -Raw).Trim()
    if ($Requirement -notmatch '\Aembykeeper==(?<version>\d+\.\d+\.\d+)\z') {
        throw "The installer requirements must pin one stable embykeeper version."
    }
    $BundledVersion = $Matches.version
    $BundledWheels = Join-Path $PSScriptRoot "..\wheels"
    if (!(Test-Path -LiteralPath (Join-Path $BundledWheels "pyaes-1.6.1-py3-none-any.whl") -PathType Leaf)) {
        throw "The bundled PyAES wheel is missing. Download and extract the complete Windows release ZIP."
    }
    $Repository = "Elykia093/emby-keeper"
    $ReleasePath = if ($Update) { "latest" } else { "tags/v$BundledVersion" }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $Request = @{TimeoutSec=30; UserAgent="Embykeeper-Windows-Installer"}
    $Release = Invoke-RestMethod @Request -Uri "https://api.github.com/repos/$Repository/releases/$ReleasePath"
    if ($Release.draft -ne $false -or $Release.prerelease -ne $false -or $Release.tag_name -cnotmatch '\Av\d+\.\d+\.\d+\z') {
        throw "GitHub did not return a stable release."
    }
    $Version = $Release.tag_name.Substring(1)
    if ((!$Update -and $Version -ne $BundledVersion) -or ([version]$Version -lt [version]$BundledVersion)) {
        throw "The release version does not match this installer."
    }
    if ($Update) {
        $InstalledVersion = & $PythonPath -c "from importlib.metadata import version; print(version('embykeeper'))"
        if ($LASTEXITCODE -ne 0 -or $InstalledVersion -notmatch '\A\d+\.\d+\.\d+\z') {
            throw "Cannot read the installed version; run Embykeeper.bat to repair the installation."
        }
        if ([version]$Version -lt [version]$InstalledVersion) {
            throw "The latest GitHub release is older than the installed version; refusing to downgrade."
        }
    }
    $WheelName = "embykeeper-$Version-py3-none-any.whl"
    $WheelUrl = "https://github.com/$Repository/releases/download/v$Version/$WheelName"
    $Assets = @($Release.assets | Where-Object { $_.name -ceq $WheelName -and $_.state -eq "uploaded" })
    if ($Assets.Count -ne 1) {
        throw "The wheel for v$Version is not published yet. Retry after the release build finishes."
    }
    $Asset = $Assets[0]
    if ($Asset.browser_download_url -cne $WheelUrl -or $Asset.size -le 0) {
        throw "GitHub returned an invalid release asset."
    }
    $TempDirectory = Join-Path ([IO.Path]::GetTempPath()) ("embykeeper-install-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $TempDirectory | Out-Null
    $WheelPath = Join-Path $TempDirectory $WheelName
    Write-Host "Downloading Embykeeper v$Version from $Repository"
    Invoke-WebRequest @Request -UseBasicParsing -Uri $WheelUrl -OutFile $WheelPath
    if ((Get-Item -LiteralPath $WheelPath).Length -ne $Asset.size) {
        throw "The downloaded wheel is incomplete."
    }
    if ($Asset.digest) {
        $Digest = "sha256:" + (Get-FileHash -LiteralPath $WheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Asset.digest -cne $Digest) { throw "The wheel checksum does not match GitHub." }
    }
    $PipArguments = @("-m", "pip", "install", $WheelPath, "--find-links", $BundledWheels, "--only-binary=pyaes", "--no-warn-script-location")
    if ($Update) { $PipArguments += "--upgrade" }
    if (!$NoMirror) { $PipArguments += @("--index-url", "https://mirrors.aliyun.com/pypi/simple") }
    & $PythonPath @PipArguments
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -eq 0) {
        Write-Host "Done installing Embykeeper v$Version"
    } else {
        Write-Host "Failed to install Embykeeper, exit code: $ExitCode"
    }
} catch {
    Write-Error "Installation failed: $($_.Exception.Message)" -ErrorAction Continue
} finally {
    if ($WheelPath) { Remove-Item -LiteralPath $WheelPath -Force -ErrorAction SilentlyContinue }
    if ($TempDirectory -and (Test-Path -LiteralPath $TempDirectory)) {
        try { [IO.Directory]::Delete($TempDirectory) } catch { Write-Warning "Could not remove temporary installer files." }
    }
}
exit $ExitCode
