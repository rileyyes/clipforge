<#
  Builds the Windows portable package: a folder (and zip) that runs RJClip with
  nothing installed — no Python, Node, Git or FFmpeg needed on the PC.

    powershell -ExecutionPolicy Bypass -File scripts\windows\build_portable.ps1 [-NoAI] [-Out portable]

  Needs (on the build machine only): Python 3.13 with pip (its version must match
  -PythonVersion's minor version, so the wheels fit), Node (to build the UI) and internet.
  CI builds it on a clean Windows runner and smoke-tests the result (see ci.yml).

  Contents:
    RJClip.bat           double-click to start
    python\                 the official Windows "embeddable" Python, with the packages
    backend\app\            RJClip itself
    frontend\dist\          the built web UI
    ffmpeg\                 ffmpeg.exe + ffprobe.exe (GPL build by BtbN) + their licence
    THIRD-PARTY.txt         where everything came from + licences
#>
param(
  [string]$Out = "portable",
  [string]$PythonVersion = "3.13.1",
  [string]$FfmpegZip = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip",
  [switch]$NoAI
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is 10x slower with the progress bar
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Pkg = Join-Path $Root "$Out\RJClip"
$Tmp = Join-Path $Root "$Out\_download"

function Say($m) { Write-Host "[portable] $m" }
# Run a program. Windows PowerShell 5.1 turns a program's stderr lines (pip/npm notices) into
# errors when its own output is redirected, which "Stop" would treat as fatal: run with
# "Continue", pass every line through as text, and judge by the exit code instead.
function Native([string]$what, [scriptblock]$cmd) {
  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $cmd 2>&1 | ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" } }
  } finally { $ErrorActionPreference = $old }
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}
function Sha256($path) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($path))) -replace "-", "" }
  finally { $sha.Dispose() }
}
function Download($url, $dest) {
  Say "downloading $url"
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $dest
  $h = Sha256 $dest
  Say "  sha256 $h"
  return $h
}

if (Test-Path (Join-Path $Root $Out)) { Remove-Item -Recurse -Force (Join-Path $Root $Out) }
New-Item -ItemType Directory -Force $Pkg, $Tmp | Out-Null

# ---- host Python must match the embeddable one (same minor version -> same wheels)
$hostVer = (Native "python" { python -c "import sys; print('%d.%d' % sys.version_info[:2])" } | Select-Object -Last 1).Trim()
$want = ($PythonVersion -split "\.")[0..1] -join "."
if ($hostVer -ne $want) { throw "Build with Python $want (this is $hostVer) so the packages match the bundled Python." }

# ---- 1. embeddable Python
$pyZip = Join-Path $Tmp "python.zip"
$pyHash = Download "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" $pyZip
$PyDir = Join-Path $Pkg "python"
Expand-Archive $pyZip $PyDir
$pth = Get-ChildItem $PyDir -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "no ._pth file in the embeddable Python" }
$zipName = (Get-ChildItem $PyDir -Filter "python*.zip" | Select-Object -First 1).Name
# search path: the stdlib zip, the folder itself, site-packages, and RJClip's backend
Set-Content -Encoding ASCII $pth.FullName "$zipName`r`n.`r`nLib\site-packages`r`n..\backend`r`nimport site`r`n"

# ---- 2. packages (only the runtime ones; tests aren't shipped)
$req = Join-Path $Tmp "requirements.txt"
$lines = @()
foreach ($l in Get-Content (Join-Path $Root "backend\requirements.txt")) {
  if ($l -match "^# dev") { break }
  $lines += $l
}
if (-not $NoAI) { $lines += Get-Content (Join-Path $Root "backend\requirements-ai.txt") }
Set-Content -Encoding ASCII $req $lines
Say "installing packages"
$site = Join-Path $PyDir "Lib\site-packages"
Native "pip install" { python -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: --target $site -r $req }
Native "pip freeze" { python -m pip freeze --path $site } | Set-Content -Encoding UTF8 (Join-Path $Pkg "packages.txt")

# ---- 3. RJClip + built UI
Say "building the UI"
Push-Location (Join-Path $Root "frontend")
try {
  if (-not (Test-Path "node_modules")) { Native "npm install" { npm install --no-audit --no-fund } }
  Native "UI build" { node build.mjs }
} finally { Pop-Location }
New-Item -ItemType Directory -Force (Join-Path $Pkg "backend"), (Join-Path $Pkg "frontend") | Out-Null
Copy-Item -Recurse (Join-Path $Root "backend\app") (Join-Path $Pkg "backend\app")
Get-ChildItem (Join-Path $Pkg "backend\app") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item -Recurse (Join-Path $Root "frontend\dist") (Join-Path $Pkg "frontend\dist")
foreach ($f in "LICENSE", "README.md") { if (Test-Path (Join-Path $Root $f)) { Copy-Item (Join-Path $Root $f) $Pkg } }

# ---- 4. FFmpeg
$ffZip = Join-Path $Tmp "ffmpeg.zip"
try { $ffHash = Download $FfmpegZip $ffZip }
catch {
  # release file names change now and then: ask GitHub for the current GPL win64 build
  Say "  not found ($($_.Exception.Message)); looking up the current BtbN release"
  $rel = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest" -Headers @{ "User-Agent" = "rjclip-build" }
  $asset = $rel.assets | Where-Object { $_.name -match "^ffmpeg-n[0-9.]+-latest-win64-gpl-[0-9.]+\.zip$" } | Sort-Object name -Descending | Select-Object -First 1
  if (-not $asset) { $asset = $rel.assets | Where-Object { $_.name -eq "ffmpeg-master-latest-win64-gpl.zip" } | Select-Object -First 1 }
  if (-not $asset) { throw "no Windows GPL FFmpeg build found in the BtbN release" }
  $FfmpegZip = $asset.browser_download_url
  $ffHash = Download $FfmpegZip $ffZip
}
$ffTmp = Join-Path $Tmp "ffmpeg"
Expand-Archive $ffZip $ffTmp
$bin = Get-ChildItem $ffTmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $bin) { throw "ffmpeg.exe not found in $FfmpegZip" }
$FfDir = Join-Path $Pkg "ffmpeg"
New-Item -ItemType Directory -Force $FfDir | Out-Null
Copy-Item (Join-Path $bin.DirectoryName "ffmpeg.exe"), (Join-Path $bin.DirectoryName "ffprobe.exe") $FfDir
$lic = Get-ChildItem $ffTmp -Recurse -Filter "LICENSE*" | Select-Object -First 1
if ($lic) { Copy-Item $lic.FullName (Join-Path $FfDir "LICENSE.txt") }
$ffExe = Join-Path $FfDir "ffmpeg.exe"
$ffVer = (Native "ffmpeg -version" { & $ffExe -version } | Select-Object -First 1)
Say $ffVer
$enc = (Native "ffmpeg -encoders" { & $ffExe -hide_banner -encoders }) -join "`n"
if ($enc -notmatch "libx264") { throw "this FFmpeg build has no libx264" }

# ---- 5. launcher + notes
$bat = @'
@echo off
rem RJClip portable: double-click to start. Close this window to stop RJClip.
setlocal
set "HERE=%~dp0"
set "RJCLIP_FFMPEG=%HERE%ffmpeg\ffmpeg.exe"
set "RJCLIP_FFPROBE=%HERE%ffmpeg\ffprobe.exe"
set "PATH=%HERE%ffmpeg;%PATH%"
set "PYTHONUTF8=1"
if "%RJCLIP_PORT%"=="" set "RJCLIP_PORT=8765"
set "URL=http://127.0.0.1:%RJCLIP_PORT%"
powershell -NoProfile -Command "try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%/api/health').StatusCode -eq 200) { exit 0 } } catch { }; exit 1" >nul 2>&1
if not errorlevel 1 (
  echo RJClip is already running: %URL%
  if /i not "%~1"=="-NoBrowser" start "" "%URL%"
  exit /b 0
)
if /i not "%~1"=="-NoBrowser" start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for ($i = 0; $i -lt 90; $i++) { try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%/api/health').StatusCode -eq 200) { Start-Process '%URL%'; break } } catch { }; Start-Sleep 1 }"
echo.
echo   RJClip is starting at %URL%  (close this window to stop it)
echo.
cd /d "%HERE%backend"
"%HERE%python\python.exe" -m app.main
if errorlevel 1 if not defined CI pause
'@
Set-Content -Encoding ASCII (Join-Path $Pkg "RJClip.bat") $bat

$commit = ""
try { $commit = (Native "git" { git -C $Root rev-parse --short HEAD } | Select-Object -Last 1).Trim() } catch { }
$third = @"
RJClip portable package (commit $commit, built $(Get-Date -Format yyyy-MM-dd))

Your projects are stored in %USERPROFILE%\RJClipWorkspace (or ClipForgeWorkspace from before the rename) (set RJCLIP_WORKSPACE
to change it), not in this folder, so you can replace this folder with a newer one.

Bundled software
- Python $PythonVersion embeddable package, from python.org (PSF License).
    sha256 of the download: $pyHash
- Python packages: see packages.txt (each keeps its licence inside python\Lib\site-packages).
- FFmpeg: $ffVer
    Build by BtbN: https://github.com/BtbN/FFmpeg-Builds (GPL build; licence in ffmpeg\LICENSE.txt).
    Source code: https://ffmpeg.org/download.html and the build scripts at the link above.
    sha256 of the download: $ffHash
$(if ($NoAI) { "- Speech-to-text is NOT included in this build." } else { "- faster-whisper (MIT). The speech model (~480 MB) downloads the first time you transcribe." })
"@
Set-Content -Encoding UTF8 (Join-Path $Pkg "THIRD-PARTY.txt") $third

# ---- 6. zip
$zip = Join-Path $Root "$Out\RJClip-portable-win64.zip"
Say "zipping"
Compress-Archive -Path $Pkg -DestinationPath $zip -CompressionLevel Optimal
Remove-Item -Recurse -Force $Tmp
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Say "done: $zip ($mb MB)"
