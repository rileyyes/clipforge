# Packaging & distribution

**Status:** ClipForge runs from source using the one-click launcher (`Start ClipForge.bat`). CI tests the launcher on a clean Windows machine. There is no installer yet. This page records the options and the recommendation.

## Today: the launcher (shipped)

`Start ClipForge.bat` runs `scripts/windows/start.ps1`, which:

- checks for Python ≥ 3.11, Node.js and FFmpeg, with exact `winget` commands if one is missing
- creates `backend\.venv` and installs packages, again only when `requirements.txt` changes
- runs `npm install` when `package.json` changes and rebuilds the UI when its source changes
- opens the existing window if ClipForge is already running; otherwise it starts ClipForge and opens the browser

`Update ClipForge.bat` does `git pull` first and also installs the free speech-to-text.

**Trade-off:** you need Python, Node and Git installed. One `winget` line each, but it's still three tools.

## Options for a real installer

| Option | What it is | Pros | Cons | Verdict |
|---|---|---|---|---|
| **Embedded Python + prebuilt UI in a zip / Inno Setup installer** | Ship python-embed (~15 MB), the wheels, the built `dist/`, plus FFmpeg (GPL/LGPL build ~90 MB) | No Python/Node needed. The app works exactly as tested. Simple to build in CI | ~150–250 MB download. Must follow FFmpeg's licence (ship its licence and source offer). Updates are a new installer | **Recommended next step** |
| PyInstaller one-file exe | Freezes Python + app | One file | Antivirus false positives are common. Slow start (unpacks every launch). OpenCV/numpy make it 300 MB+ | No |
| Tauri wrapper | Rust shell with a system WebView, launching the Python server as a "sidecar" | Real desktop window, small shell (~10 MB), auto-update support | Still has to ship Python + FFmpeg as sidecars. Adds a Rust toolchain to the build. WebView2 differences from Chrome (MediaRecorder formats, codecs) need retesting | Later, if a native window matters |
| Electron | Chromium + Node shell | Same browser engine as tested | +150 MB per install, and still needs Python | No |

**Why not now:** none of these can be built or tested in the current development environment (no Windows packaging tools, no code-signing certificate). An unsigned installer would also trigger SmartScreen warnings. Shipping one untested would break the project's rule against untested features.

**Plan:** build the zip/Inno Setup package in a GitHub Actions Windows job:

1. python-embed and wheels
2. the `dist/` build
3. a pinned Gyan FFmpeg essentials build with its licence
4. a smoke test that starts the installed copy, like the launcher job does today

Code signing comes once there's a certificate.

## Licences to respect when bundling

- FFmpeg is LGPL/GPL, depending on the build. A bundle must include the licence and say where to get the source.
- faster-whisper and CTranslate2 are MIT. Whisper models are MIT.
- OpenCV is Apache 2.0, Pillow is HPND, numpy is BSD, Starlette is BSD, Pydantic is MIT, React is MIT.
