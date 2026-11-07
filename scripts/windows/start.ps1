<#
  RJClip launcher for Windows. Double-click "Start RJClip.bat" in the repo folder,
  or run:  powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1 [-Update] [-WithAI] [-NoBrowser]

  First run: creates backend\.venv, installs Python packages, installs + builds the UI.
  Later runs: only reinstalls/rebuilds when something changed, then starts RJClip and
  opens http://127.0.0.1:8765.  -Update pulls the latest version from GitHub first.
  -WithAI also installs the free speech-to-text (for bleeps and captions).
  Everything stays on this computer.
#>
param([switch]$Update, [switch]$WithAI, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Port = if ($env:RJCLIP_PORT) { $env:RJCLIP_PORT } else { "8765" }
$Url = "http://127.0.0.1:$Port"

function Say($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Fail($msg) {
  Write-Host ""
  Write-Host "  $msg" -ForegroundColor Red
  Write-Host ""
  if (-not $env:CI) { Read-Host "  Press Enter to close" }
  exit 1
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function FileHash($path) {  # plain .NET (works even where the Get-FileHash cmdlet isn't available)
  if (-not (Test-Path $path)) { return "" }
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes((Resolve-Path $path)))) -replace "-", "" }
  finally { $sha.Dispose() }
}
function Stamp($name) { Join-Path $Root ".launcher-$name" }
function Changed($name, $value) { -not (Test-Path (Stamp $name)) -or (Get-Content (Stamp $name) -Raw).Trim() -ne $value }
function Mark($name, $value) { Set-Content -Path (Stamp $name) -Value $value -NoNewline }

Write-Host ""
Write-Host "  RJClip" -ForegroundColor White
Write-Host ""

# ---- already running? just open it
try {
  $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$Url/api/health"
  if ($r.StatusCode -eq 200) {
    Say "RJClip is already running."
    if (-not $NoBrowser) { Start-Process $Url }
    exit 0
  }
} catch { }

# ---- the app was renamed ClipForge -> RJClip: rename this folder too, once this window is closed
# (it can't be renamed while RJClip runs from inside it). Projects aren't in here, so nothing moves.
$Leaf = Split-Path $Root -Leaf
$NewRoot = Join-Path (Split-Path $Root -Parent) "RJClip"
if ($Leaf -ieq "clipforge" -and -not (Test-Path $NewRoot) -and -not $env:CI) {
  $helper = @"
Wait-Process -Id $PID -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
for (`$i = 0; `$i -lt 20; `$i++) {
  try { Rename-Item -LiteralPath '$Root' -NewName 'RJClip' -ErrorAction Stop; break } catch { Start-Sleep -Seconds 3 }
}
"@
  $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($helper))
  Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-EncodedCommand", $enc
  Write-Host "  ClipForge is now called RJClip. When you close this window, this folder becomes" -ForegroundColor Yellow
  Write-Host "  $NewRoot  -  next time, double-click 'Start RJClip.bat' in there." -ForegroundColor Yellow
  Write-Host ""
}

# ---- update
if ($Update) {
  if (-not (Have git)) { Fail "Git isn't installed, so -Update can't pull. Install it: winget install Git.Git" }
  Say "Getting the latest version from GitHub..."
  # the GitHub repo was renamed clipforge -> rjclip (GitHub redirects the old address too)
  $origin = (git remote get-url origin 2>$null)
  if ($origin -match "rileyyes/clipforge(\.git)?$") {
    # only switch once the renamed repo exists (until then, keep pulling from the old address)
    git ls-remote --exit-code "https://github.com/rileyyes/rjclip.git" HEAD *> $null
    if ($LASTEXITCODE -eq 0) { git remote set-url origin "https://github.com/rileyyes/rjclip.git" }
  }
  git pull --ff-only
  if ($LASTEXITCODE -ne 0) { Fail "git pull failed (see above). If you changed files yourself, run 'git status' to see them." }
}

# ---- tools
# Find one concrete python.exe (3.11+), preferring versions every dependency has wheels for.
# (Arguments are always passed literally; no splatting, which Windows PowerShell 5.1 mangles.)
function PyVersion($exe) {
  try { $v = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { return $null }
  if ($LASTEXITCODE -ne 0 -or -not $v) { return $null }
  return [version]("$v".Trim())
}
$PyExe = $null
$candidates = @()
if (Have python) { $candidates += (Get-Command python).Source }
if (Have py) {
  foreach ($ver in @("3.13", "3.12", "3.11", "3.14", "3")) {
    try { $exe = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null } catch { $exe = $null }
    if ($LASTEXITCODE -eq 0 -and $exe) { $candidates += "$exe".Trim() }
  }
}
foreach ($exe in $candidates) {
  if ($exe -like "*WindowsApps*") { continue }  # the Microsoft Store "python" stub
  $ver = PyVersion $exe
  if ($ver -and $ver -ge [version]"3.11" -and $ver -lt [version]"3.15") { $PyExe = $exe; break }
}
if (-not $PyExe) {
  foreach ($exe in $candidates) {  # a newer Python is OK as a last resort
    $ver = PyVersion $exe
    if ($ver -and $ver -ge [version]"3.11") { $PyExe = $exe; break }
  }
}
if (-not $PyExe) { Fail "Python 3.11 or newer is needed. Install it: winget install Python.Python.3.13  (then open a new window)" }
Say "Using Python $(PyVersion $PyExe) at $PyExe"
if (-not (Have node) -or -not (Have npm)) { Fail "Node.js is needed to build the screen part. Install it: winget install OpenJS.NodeJS.LTS  (then open a new window)" }

# ---- Python environment
$Venv = Join-Path $Root "backend\.venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
  Say "First run: creating the Python environment..."
  & $PyExe -m venv "$Venv"
  if ($LASTEXITCODE -ne 0) { Fail "Couldn't create backend\.venv" }
}
$req = FileHash (Join-Path $Root "backend\requirements.txt")
if (Changed "pip" $req) {
  Say "Installing Python packages (first run or they changed)..."
  & $VenvPy -m pip install --disable-pip-version-check -q -r backend\requirements.txt
  if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see above)." }
  Mark "pip" $req
}
if ($WithAI) {
  $ai = FileHash (Join-Path $Root "backend\requirements-ai.txt")
  if (Changed "pip-ai" $ai) {
    Say "Installing the free speech-to-text (one time; the first transcription also downloads its model)..."
    & $VenvPy -m pip install --disable-pip-version-check -q -r backend\requirements-ai.txt
    if ($LASTEXITCODE -ne 0) { Fail "Installing speech-to-text failed (see above). RJClip still works without it." }
    Mark "pip-ai" $ai
  }
}

# ---- UI: install packages when package.json changes, rebuild when the source changes
Push-Location (Join-Path $Root "frontend")
try {
  $pkg = FileHash "package.json"
  if (-not (Test-Path "node_modules") -or (Changed "npm" $pkg)) {
    Say "Installing UI packages..."
    npm install --no-audit --no-fund --loglevel=error
    if ($LASTEXITCODE -ne 0) { Fail "npm install failed (see above)." }
    Mark "npm" $pkg
  }
  $src = (Get-ChildItem -Recurse -File src, build.mjs, index.html -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc.Ticks
  if (-not (Test-Path "dist\index.html") -or (Changed "build" "$src")) {
    Say "Building the UI..."
    npm run build --silent
    if ($LASTEXITCODE -ne 0) { Fail "Building the UI failed (see above)." }
    Mark "build" "$src"
  }
} finally { Pop-Location }

# ---- FFmpeg (RJClip also finds winget/Chocolatey/Scoop installs that aren't on PATH)
$ff = & $VenvPy -c "import sys; sys.path.insert(0, 'backend'); from app.config import find_tool; print(find_tool('ffmpeg'))"
if (-not (Have $ff) -and -not (Test-Path $ff)) {
  Write-Host "  FFmpeg wasn't found. Install it with:  winget install Gyan.FFmpeg   (RJClip finds it automatically)" -ForegroundColor Yellow
}

# ---- start
Say "Starting RJClip at $Url  (close this window or press Ctrl+C to stop)"
if (-not $NoBrowser) {
  Start-Job -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 60; $i++) {
      try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$u/api/health").StatusCode -eq 200) { Start-Process $u; break } } catch { }
      Start-Sleep -Milliseconds 500
    }
  } -ArgumentList $Url | Out-Null
}
Push-Location (Join-Path $Root "backend")
try { & $VenvPy -m app.main } finally { Pop-Location }
