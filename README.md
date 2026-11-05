# ClipForge

A local-first, AI-assisted video editor for making YouTube videos. Import a raw recording, let the AI Auto Editor cut it down to a target length (e.g. 2 hours → 30 minutes), refine it on a real multitrack timeline, and export a validated, YouTube-ready MP4.

> **Status: Phases 1–6 working and tested; Phase 7 done except two items this dev environment blocks (see ROADMAP); Phases 8–10 built and tested automatically, waiting for hands-on testing** (Shorts maker, Publish page, YouTube upload, library suggestions, Thumbnail Maker cut-outs, fast re-exports, Windows portable package; face cam with sync by sound and optional background removal, smoother jump cuts, 9 new transitions; edit by transcript, filler/retake removal, titles, privacy blur, music beat sync). Transcription is optional and experimental. See [ROADMAP.md](ROADMAP.md) for the live checklist.

## What works today

### AI Auto Editor
- Analyses loudness, pauses, on-screen motion and scene cuts **locally** (~7 min for a 2-hour 720p recording on a 2-core laptop, < 50 MB RAM).
- Target length as a duration, a percentage, or "original" (just remove dead air). Warns when a target is unrealistic.
- Pause presets (off / conservative / balanced / aggressive). Short natural pauses are always kept, and cuts only happen in silence, never mid-sentence.
- Styles: balanced, excitement, reactions, information, visual action (humor/story are approximations without a transcript).
- Every moment gets a score **and the reasons**. Keep or drop any moment, preview it, or play the whole rough cut.
- **Send to Manual Editor** turns the edit into normal linked clips. The previous edit is saved as a version first, and the source file is never touched.
- **One click, fully finished**: tick *Finishing touches* (bleep swears, comedy edits, captions, audio polish) and they're applied together with the cut. You're told exactly what was added or skipped.
- Optional transcription: `pip install faster-whisper` adds word timestamps (experimental, see ROADMAP).

### Effects, audio & transitions (free & local)
- **Swear bleeps** from the transcript, with beep, boing, scratch, honk, quack or mute. The word is removed from the audio, not just covered. Every bleep can be reviewed.
- **Comedy edits** auto-placed on reactions (zooms, shakes, pop-up text, sound effects) or added at the playhead, plus your own images.
- **Animated captions** (bold pop / word highlight / clean) burned in, plus `.srt` export. Censored words are masked.
- **Audio polish**: loudness normalised to YouTube's −14 LUFS (verified in the export report), background-noise removal, voice enhancement, music that ducks under your voice.
- **Transitions & fades**: 30 transitions between clips (crossfade, dips, wipes, slides, circle, zoom, pixelize, blur, whip pan, spin, glitch, RGB split, light leak, flash cut, shake cut…; audio follows), fades from/to black, volume fades for music.
- **Smoother jump cuts**: zoom punch-ins, quick blends or whip pans wherever talking was cut out of one shot.
- **My sounds & images**: record your own sounds with the mic (or import MP3/WAV/M4A/OGG, or a video's audio) and your own images. Use them as the bleep sound, as sound effects, or as pop-ups, in every project.
- Needs the free transcriber for bleeps/captions: `pip install -r requirements-ai.txt`. See [docs/EFFECTS.md](docs/EFFECTS.md).

### Edit by text, titles, blur, beat
- **Script tab**: your video as text. Select words and cut them; remove "um"s and retakes in one click.
- **Titles**: lower thirds, big titles, banners, a subscribe button, chapter cards — animated.
- **Privacy blur**: blur, pixelate or black-box a face, plate or chat; draw it on the preview, one-click face blur, and it can follow what moves.
- **Beat sync**: finds the beat of your music, shows it on the timeline and moves cuts onto it.

### Face cam
- Import your webcam video: it sits in a corner and **follows every cut** of the main recording, so it stays in sync.
- **Line up by sound** when it was recorded separately; corner, size, square/rounded/circle, border, shadow; **crop to your face**.
- Hide it for a stretch, or let it fill the screen on your biggest reactions.
- Optional **AI background removal** (just you over the video, no green screen; on your computer, off by default).
- Shorts can stack it on top of the video.

### Shorts & publishing
- **Shorts maker**: finds the best 15–60 s moments and turns each into a 9:16 project whose crop follows you (face detection, or movement), with captions.
- **Publish page**: chapters checked against YouTube's rules, title ideas, a description, and tags, written from what's said. Edit and keep them with the project.
- **Upload to YouTube** with your own Google account (private by default, asks every time). Setup: [docs/YOUTUBE.md](docs/YOUTUBE.md). Tested against a fake Google server only so far.
- **Optional local AI** (Ollama or any OpenAI-compatible server on your PC) rates moments and polishes titles. Nothing is sent online; everything works without it.

### Thumbnail Maker (basic, free & local)
- Pulls representative frames from your **final edit** (trims, order, overlays applied), proposes 3 distinct concepts with headline ideas, and builds an editable layered design.
- Studio: text, shapes, image adjustments, layers, undo/redo, small-size previews, plain-language refinements, saved versions.
- Exports a validated 1280×720 JPEG/PNG (≤ 2 MB). Optional free AI artwork with local Stable Diffusion. See [docs/THUMBNAILS.md](docs/THUMBNAILS.md).

### Manual editor & export

- **Import** video/audio (MP4, MOV, MKV, WebM, AVI, MP3, WAV, M4A, FLAC, OGG) with streaming upload and real progress. Files are validated with FFprobe, checksummed, de-duplicated and stored read-only.
- **Background preparation**: thumbnails, audio waveforms, and browser-playable preview proxies for formats like MKV.
- **Multitrack timeline**: video and audio tracks, linked picture + sound, move (including across tracks), trim both edges, split, delete, ripple delete, duplicate, snapping, zoom and scroll, track mute/hide/lock, add/remove tracks, undo/redo.
- **Clip properties**: speed (0.25–4×, audio pitch preserved), volume, scale, position, rotation, opacity, crop (e.g. picture-in-picture on V2).
- **Keyframes** (◆) for scale, position, rotation, opacity and volume, with linear / ease / hold. Slow zooms, moving picture-in-picture, music that dips under talking.
- **Colour**: brightness, contrast, saturation, gamma, temperature, plus looks (warm, cool, B&W, vintage, vivid, faded, cinematic, noir).
- **Program monitor** that plays the *timeline* with every video layer, transforms, crop, colour and keyframes, stereo audio meters, and a **Light preview** mode (540p copies) for slower computers.
- **Render cache + block rendering**: exporting again after a small change only re-renders the clips and the 20-second stretches of the final video that changed; everything else is copied. An unchanged re-export of a 3-minute edit took 42 s instead of 87 s.
- **Autosave** with crash-safe atomic writes, a backup copy, and conflict detection across windows.
- **Version history** (Editor → History): save named versions, automatic checkpoints, one-click restore (undoable), and a side-by-side compare showing which footage was cut or added and what changed.
- **Export**: 1080p, 720p, 4K, 9:16 vertical, 1:1 square or custom; 24–60 fps; letterbox or crop (never stretched); H.264 + AAC MP4. Hardware encoders are used when one actually works, with libx264 as the fallback.
- **Export validation**: codec, resolution, duration, A/V sync, exact frame count, and a full decode check, shown in the UI.
- **Projects**: create, open, rename, duplicate, delete. Dashboard shows recent projects, running jobs and storage use.

## Quick start

**Windows, no installing at all:** download the **portable package** (GitHub → Actions → the latest green *CI* run → *Artifacts* → `ClipForge-portable-win64`), unzip it and double-click **`ClipForge.bat`**. It has Python, FFmpeg and speech-to-text inside. It isn't code-signed yet, so Windows may warn the first time (*More info → Run anyway*). Details: [docs/PACKAGING.md](docs/PACKAGING.md).

**Windows, from source:** install the three tools once:

```powershell
winget install Python.Python.3.13
winget install OpenJS.NodeJS.LTS
winget install Gyan.FFmpeg
```

Then double-click **`Start ClipForge.bat`** in the `clipforge` folder. The first run sets everything up (a few minutes); later runs start in seconds and open the browser. **`Update ClipForge.bat`** gets the latest version from GitHub (and the free speech-to-text) and then starts ClipForge.

**Manual setup (any OS).** Requirements: **Python 3.11+**, **Node.js 18+**, **FFmpeg 6+** (with `ffprobe`) on your PATH.

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
scripts/verify_all.sh                   # everything below, in one go
cd backend && python -m pytest          # 161 backend tests (unit, integration, auto-edit, effects, thumbnails)
cd frontend && npm test                 # timeline engine: 20 unit tests + randomized fuzz
cd frontend && npm run typecheck        # strict TS check of the editing engine
python scripts/e2e_browser.py           # browser E2E: manual editor (needs Playwright)
python scripts/e2e_autoedit.py          # browser E2E: AI auto editor
python scripts/e2e_thumbnails.py        # browser E2E: thumbnail maker
python scripts/e2e_effects.py           # browser E2E: bleeps, comedy edits, captions
python scripts/e2e_audio.py             # browser E2E: transitions, fades, ducking, loudness
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
CLIPFORGE_TRANSCRIBER=auto                 # 'off' to skip transcription even if installed
CLIPFORGE_WHISPER_MODEL=small              # faster-whisper model size
CLIPFORGE_SDWEBUI_URL=http://127.0.0.1:7860 # optional free local AI thumbnail art
CLIPFORGE_WHISPER_DEVICE=cpu               # 'cuda' to transcribe on an NVIDIA GPU
CLIPFORGE_FONT=C:\\Windows\\Fonts\\impact.ttf  # font for pop-ups and captions
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
- [docs/EFFECTS.md](docs/EFFECTS.md) – bleeps, comedy edits, captions, transcriber setup
- [docs/THUMBNAILS.md](docs/THUMBNAILS.md) – Thumbnail Maker, free local AI setup
- [docs/API.md](docs/API.md) – REST API reference
- [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) – dependency, license and cost inventory
