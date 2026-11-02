# ClipForge

A local-first, AI-assisted video editor for making YouTube videos. Import a raw recording, cut it on a real multitrack timeline, and export a validated, YouTube-ready MP4. An automatic editing engine (turn a 2-hour recording into a tight 30-minute video) is the next major phase.

> **Status: Phase 1 + core Phase 2 complete.** The manual editor and export pipeline work end-to-end and are tested. The AI Auto Editor is **not built yet** — see [ROADMAP.md](ROADMAP.md) for the live feature checklist.

## What works today

- **Import** video/audio (MP4, MOV, MKV, WebM, AVI, MP3, WAV, M4A, FLAC, OGG) with streaming upload and real progress. Files are validated with FFprobe, checksummed, de-duplicated and stored read-only.
- **Background preparation**: thumbnails, audio waveforms, and browser-playable preview proxies for formats like MKV.
- **Multitrack timeline**: video and audio tracks, linked picture + sound, move (including across tracks), trim both edges, split, delete, ripple delete, duplicate, snapping, zoom and scroll, track mute/hide/lock, add/remove tracks, undo/redo.
- **Clip properties**: speed (0.25–4×, audio pitch preserved), volume, scale and position (e.g. picture-in-picture on V2).
- **Program monitor** that plays the *timeline* (switching clips and mixing audio tracks), with frame stepping.
- **Autosave** with crash-safe atomic writes, a backup copy, and conflict detection across windows.
- **Export**: 1080p, 720p, 4K, 9:16 vertical, 1:1 square or custom; 24–60 fps; letterbox or crop (never stretched); H.264 + AAC MP4. Hardware encoders are used when one actually works, with libx264 as the fallback.
- **Export validation**: codec, resolution, duration, A/V sync, exact frame count, and a full decode check, shown in the UI.
- **Projects**: create, open, rename, duplicate, delete. Dashboard shows recent projects, running jobs and storage use.

## Quick start

Requirements: **Python 3.11+**, **Node.js 18+**, **FFmpeg 6+** (with `ffprobe`) on your PATH.

```bash
git clone https://github.com/rileyyes/clipforge && cd clipforge

# backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# frontend
cd ../frontend
npm install
npm run build

# run (serves the UI + API on http://127.0.0.1:8765)
cd ../backend
python -m app.main
```

Open **http://127.0.0.1:8765**. Media and projects go to `~/ClipForgeWorkspace` by default.

**Installing FFmpeg:** Windows `winget install Gyan.FFmpeg` · macOS `brew install ffmpeg` · Ubuntu `sudo apt install ffmpeg`.

## Development

```bash
# terminal 1 – rebuild the UI on change
cd frontend && npm run dev
# terminal 2 – API server (restart after backend changes)
cd backend && python -m app.main
```

Tests (see [TESTING.md](TESTING.md)):

```bash
cd backend && python -m pytest          # 46 backend unit + integration tests
cd frontend && npm test                 # 20 timeline-engine tests
cd frontend && npm run typecheck        # strict TS check of the editing engine
python scripts/e2e_browser.py           # headless browser end-to-end flow (needs Playwright)
```

## Configuration

All settings are environment variables, read at startup (the web UI can't change where files go). Example `.env`-style values:

```bash
CLIPFORGE_WORKSPACE=D:\ClipForgeWorkspace   # where projects/media/exports live
CLIPFORGE_PORT=8765
CLIPFORGE_MAX_UPLOAD_MB=20480               # 20 GB per file
CLIPFORGE_MAX_WORKSPACE_GB=200              # soft storage quota
CLIPFORGE_RENDER_TIMEOUT_S=21600            # max time for one processing step
CLIPFORGE_JOB_WORKERS=1                     # parallel background jobs
CLIPFORGE_FFMPEG=/opt/ffmpeg/bin/ffmpeg     # optional custom binaries
CLIPFORGE_FFPROBE=/opt/ffmpeg/bin/ffprobe
```

## Keyboard shortcuts (editor)

| Key | Action | Key | Action |
|---|---|---|---|
| Space | Play / pause | S | Split at playhead |
| Del | Delete | Shift+Del | Ripple delete |
| Ctrl+D | Duplicate | Ctrl+Z / Ctrl+Shift+Z | Undo / redo |
| ← / → | Step one frame | Home / End | Jump to start / end |
| N | Toggle snapping | Alt (while dragging) | Bypass snapping |
| Ctrl + wheel | Zoom timeline | Ctrl+S | Save now |

Drag media from the library onto a track, or double-click it to append.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Frontend not built` page | `cd frontend && npm install && npm run build` |
| Import fails with "not a readable media file" | The file is corrupt or not a supported audio/video file. Try re-exporting it from the recorder. |
| Preview says "a preview copy is being prepared" | MKV/AVI/HEVC files get an MP4 preview proxy in the background. Watch the chip in the media library. Export always uses the original. |
| Export fails | Click **Details** on the failed job for FFmpeg's message. Check free disk space, and that the original files still exist (missing files are flagged in red). |
| "Changed elsewhere" in the editor | The project is open in two tabs. Reload to continue from the latest saved version. |
| Exports are slow | Software encoding (libx264) is CPU-bound. Use **Draft** quality for test exports. A working NVENC/QSV/VideoToolbox GPU is used automatically. |
| Disk filling up | Settings → **Clean up temporary files**, and delete old exports/projects. |

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) – components, data model, render pipeline, decisions
- [ROADMAP.md](ROADMAP.md) – phases and the **feature status checklist**
- [SECURITY.md](SECURITY.md) – threat model and controls
- [TESTING.md](TESTING.md) – test strategy, fixtures, how to run
- [docs/API.md](docs/API.md) – REST API reference
- [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) – dependency, license and cost inventory
