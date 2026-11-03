<#
  ClipForge launcher for Windows. Double-click "Start ClipForge.bat" in the repo folder,
  or run:  powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1 [-Update] [-WithAI] [-NoBrowser]

  First run: creates backend\.venv, installs Python packages, installs + builds the UI.
  Later runs: only reinstalls/rebuilds when something changed, then starts ClipForge and
  opens http://127.0.0.1:8765.  -Update pulls the latest version from GitHub first.
  -WithAI also installs the free speech-to-text (for bleeps and captions).
  Everything stays on this computer.
#>
param([switch]$Update, [switch]$WithAI, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Port = if ($env:CLIPFORGE_PORT) { $env:CLIPFORGE_PORT } else { "8765" }
$Url = "http://127.0.0.1:$Port"

function Say($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Fail($msg) {
  Write-Host ""
  Write-Host "  $msg" -ForegroundColor Red
  Write-Host ""
  Read-Host "  Press Enter to close"
  exit 1
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function FileHash($path) { if (Test-Path $path) { (Get-FileHash $path -Algorithm SHA256).Hash } else { "" } }
function Stamp($name) { Join-Path $Root ".launcher-$name" }
function Changed($name, $value) { -not (Test-Path (Stamp $name)) -or (Get-Content (Stamp $name) -Raw).Trim() -ne $value }
function Mark($name, $value) { Set-Content -Path (Stamp $name) -Value $value -NoNewline }

Write-Host ""
Write-Host "  ClipForge" -ForegroundColor White
Write-Host ""

# ---- already running? just open it
try {
  $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$Url/api/health"
  if ($r.StatusCode -eq 200) {
    Say "ClipForge is already running."
    if (-not $NoBrowser) { Start-Process $Url }
    exit 0
  }
} catch { }

# ---- update
if ($Update) {
  if (-not (Have git)) { Fail "Git isn't installed, so -Update can't pull. Install it: winget install Git.Git" }
  Say "Getting the latest version from GitHub..."
  git pull --ff-only
  if ($LASTEXITCODE -ne 0) { Fail "git pull failed (see above). If you changed files yourself, run 'git status' to see them." }
}

# ---- tools
$Py = $null
foreach ($c in @("py", "python")) {
  if (Have $c) {
    $probe = if ($c -eq "py") { @("-3", "-c") } else { @("-c") }
    $v = & $c @probe "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]"3.11") { $Py = $c; $PyArgs = if ($c -eq "py") { @("-3") } else { @() }; break }
  }
}
if (-not $Py) { Fail "Python 3.11 or newer is needed. Install it: winget install Python.Python.3.13  (then open a new window)" }
if (-not (Have node) -or -not (Have npm)) { Fail "Node.js is needed to build the screen part. Install it: winget install OpenJS.NodeJS.LTS  (then open a new window)" }

# ---- Python environment
$Venv = Join-Path $Root "backend\.venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
  Say "First run: creating the Python environment..."
  & $Py @PyArgs -m venv $Venv
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
    if ($LASTEXITCODE -ne 0) { Fail "Installing speech-to-text failed (see above). ClipForge still works without it." }
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

# ---- FFmpeg (ClipForge also finds winget/Chocolatey/Scoop installs that aren't on PATH)
$ff = & $VenvPy -c "import sys; sys.path.insert(0, 'backend'); from app.config import find_tool; print(find_tool('ffmpeg'))"
if (-not (Have $ff) -and -not (Test-Path $ff)) {
  Write-Host "  FFmpeg wasn't found. Install it with:  winget install Gyan.FFmpeg   (ClipForge finds it automatically)" -ForegroundColor Yellow
}

# ---- start
Say "Starting ClipForge at $Url  (close this window or press Ctrl+C to stop)"
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
