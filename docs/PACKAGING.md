# Packaging & distribution

**Status:** two ways to run RJClip on Windows, both tested by CI on a clean Windows machine on every push:

1. **Portable package** (nothing to install), described below. Not code-signed yet.
2. **From source** with the one-click launcher (`Start RJClip.bat`).

## Portable package (shipped, Phase 8)

A zip (`RJClip-portable-win64.zip`, built by `scripts/windows/build_portable.ps1`) containing:

| Folder | What |
|---|---|
| `RJClip.bat` | Double-click to start; opens the browser. Close the window to stop RJClip |
| `python\` | The official Windows "embeddable" Python 3.13 from python.org, with RJClip's packages (and faster-whisper for speech-to-text) installed inside |
| `backend\app\`, `frontend\dist\` | RJClip and its built web UI |
| `ffmpeg\` | `ffmpeg.exe` + `ffprobe.exe` (GPL build by BtbN, with libx264) and its licence |
| `THIRD-PARTY.txt`, `packages.txt` | Where everything came from (with download checksums), and every bundled package version |

**How to get it:** open the latest green run of the CI workflow on GitHub (Actions tab → *CI* → the run → *Artifacts*) and download **RJClip-portable-win64**. You need to be signed in to GitHub to download artifacts; they're kept 14 days. Unzip anywhere and double-click `RJClip.bat`.

**Your projects are not inside the folder.** They stay in `%USERPROFILE%\RJClipWorkspace` (or your existing `ClipForgeWorkspace` from before the rename), shared with the from-source version, so updating means deleting the old folder and unzipping the new one.

**How it's tested:** CI unzips the package into a fresh folder and starts it with PATH set to Windows' own folders only, so no Python, Node or FFmpeg from the build machine can be used. Then `scripts/smoke_export.py` drives the real API: imports a generated clip, exports it, checks the validation report, exports again and checks every block came from the cache.

**Known limits:**
- Not code-signed, so SmartScreen warns the first time: *More info → Run anyway*. Signing needs a certificate.
- Size: about 280 MB zipped (278.5 MB on 2026-11-04), mostly FFmpeg, OpenCV and the speech-to-text engine. `-NoAI` builds a smaller one without speech-to-text. CI prints the exact size on every run.
- Local AI (Ollama) and Stable Diffusion aren't bundled; they're separate apps you install if you want them.
- "Update RJClip.bat" is a from-source feature. The portable package is updated by downloading a new zip.

## Today: the launcher (shipped)

`Start RJClip.bat` runs `scripts/windows/start.ps1`, which:

- checks for Python ≥ 3.11, Node.js and FFmpeg, with exact `winget` commands if one is missing
- creates `backend\.venv` and installs packages, again only when `requirements.txt` changes
- runs `npm install` when `package.json` changes and rebuilds the UI when its source changes
- opens the existing window if RJClip is already running; otherwise it starts RJClip and opens the browser

`Update RJClip.bat` does `git pull` first and also installs the free speech-to-text.

**Trade-off:** you need Python, Node and Git installed. One `winget` line each, but it's still three tools.

## Options for a real installer

| Option | What it is | Pros | Cons | Verdict |
|---|---|---|---|---|
| **Embedded Python + prebuilt UI in a zip / Inno Setup installer** | Ship python-embed (~15 MB), the wheels, the built `dist/`, plus FFmpeg (GPL/LGPL build ~90 MB) | No Python/Node needed. The app works exactly as tested. Simple to build in CI | ~150–250 MB download. Must follow FFmpeg's licence (ship its licence and source offer). Updates are a new installer | **Recommended next step** |
| PyInstaller one-file exe | Freezes Python + app | One file | Antivirus false positives are common. Slow start (unpacks every launch). OpenCV/numpy make it 300 MB+ | No |
| Tauri wrapper | Rust shell with a system WebView, launching the Python server as a "sidecar" | Real desktop window, small shell (~10 MB), auto-update support | Still has to ship Python + FFmpeg as sidecars. Adds a Rust toolchain to the build. WebView2 differences from Chrome (MediaRecorder formats, codecs) need retesting | Later, if a native window matters |
| Electron | Chromium + Node shell | Same browser engine as tested | +150 MB per install, and still needs Python | No |

**Done:** the first option, as a zip (above), built and smoke-tested in a GitHub Actions Windows job. An Inno Setup installer around the same folder (Start-menu shortcut, uninstaller) is a small step on top; it's worth doing together with code signing, since an unsigned installer gets the same SmartScreen warning.

## Licences to respect when bundling

- FFmpeg is LGPL/GPL, depending on the build. A bundle must include the licence and say where to get the source.
- faster-whisper and CTranslate2 are MIT. Whisper models are MIT.
- OpenCV is Apache 2.0, Pillow is HPND, numpy is BSD, Starlette is BSD, Pydantic is MIT, React is MIT.
