# Roadmap & feature status

This file is the **persistent project checklist**. Update it whenever a feature lands, so progress survives across sessions.

Legend: ✅ done & tested · 🟡 partial (see note) · ⬜ not started

## Phase 1 — Foundation ✅

- ✅ Environment inspection, architecture, repo structure
- ✅ Versioned project schema (v1) with semantic validation and a migration hook
- ✅ Safe media import: streaming upload, size/quota limits, extension allow-list, FFprobe validation, SHA-256 de-dup, read-only originals
- ✅ FFmpeg/FFprobe integration (argument lists, protocol + demuxer whitelists, timeouts, measured progress, cancel)
- ✅ Thumbnails, waveforms, browser preview proxies (background jobs)
- ✅ Dark UI shell: Dashboard, AI Auto Editor, Manual Editor, Projects, Export, Settings
- ✅ Initial tests (backend unit + integration, frontend engine, browser E2E)

## Phase 2 — Manual editor foundation ✅ (core) / 🟡 (rest)

- ✅ Media library (import, drag-to-timeline, double-click append, remove unused, status chips)
- ✅ Multitrack timeline with real data model (video stacking, linked A/V clips)
- ✅ Program-monitor playback of the timeline, multi-track audio preview, frame step
- ✅ Move (incl. across tracks), trim both edges, split, delete, ripple delete, duplicate
- ✅ Snapping (clip edges, playhead, zero), zoom (anchored Ctrl+wheel, slider, fit), scroll
- ✅ Track mute / hide / lock, add / remove tracks
- ✅ Undo / redo (200 steps, labelled)
- ✅ Clip speed, volume, scale, position
- ✅ Autosave, crash-safe writes, cross-window conflict detection, reopen
- ✅ Export presets (1080p, 720p, 4K, 9:16, 1:1, custom), fps, letterbox/crop, quality, validation report
- 🟡 Preview fidelity: shows only the top video layer, no transform preview, volume capped at 100% in preview (export is exact)
- ⬜ Multi-clip drag (move several selected clips at once)
- ⬜ Relink missing media (detection ✅, relink UI ⬜)
- ⬜ Unlink / relink A/V clips
- ⬜ Timeline markers

## Phase 3 — Automatic editing engine ✅ (signal-based) / 🟡 (transcript features)

- ✅ Streaming analysis: loudness (20/s), on-screen motion, hard scene cuts. ~3.4 s per minute of 720p on 2 cores, < 50 MB RAM
- ✅ Silence & pacing presets (off / conservative / balanced / aggressive) with a retained pause; natural short pauses never cut
- ✅ Moments ("beats") split only at pauses; size adapts to the target length
- ✅ Explainable weighted scoring: balanced, excitement, reactions, information, visual action (+ humor/story approximations with warning)
- ✅ Duration planner: custom duration, % of original, original length; opening hook; setup-before-payoff context; feasibility warnings
- ✅ Keep / drop overrides per moment; deterministic plans; validated EDL; stale-review protection
- ✅ Review UI: summary, warnings, source strip, per-moment preview, play rough cut
- ✅ Send to Manual Editor / Apply & export (previous timeline backed up to `history/`)
- 🟡 Transcription (faster-whisper adapter written behind a provider interface, **not yet run in tests**: it couldn't be installed in the build environment). Word-boundary snapping is implemented and tested with synthetic word data.
- ⬜ Laughter classifier, repetition detection, transcript keyword/topic scoring
- ⬜ Optional LLM reasoning provider (local or API, opt-in)
- ⬜ Short-form (9:16) auto-reframe

## Phase 4 — YouTube entertainment features ✅

- ✅ Transcription job (faster-whisper, free/local, optional install) — 🟡 not yet run on a real machine
- ✅ Swear censoring at the audio level: strong/mild lists + custom & allow words, padding, review flags, 6 synthesised sounds, masked captions
- ✅ Comedy edits: zoom punch-ins, shake, flash, pop-up text, 10 synthesised SFX, user images; auto-placement on reactions (minimal/balanced/chaotic)
- ✅ Effects pinned to source time (follow trims/moves, vanish when cut); timeline markers; monitor preview; undo/redo; autosave
- ✅ Animated burned-in captions (bold pop / word highlight / clean) + SRT export
- ✅ Two-pass loudness normalisation (−14 LUFS default, verified in the export report), noise removal, voice enhancement
- ✅ Music tracks ducked under dialogue (sidechain), volume fades
- ✅ Transitions: crossfade (with handles; linked audio crossfades) and dip to black; fades from/to black
- ⬜ Transition/fade preview in the live monitor (export is exact)
- ⬜ Built-in music library, animated GIF pop-ups (first frame only today), dragging effects on the timeline

## Phase 4b — Thumbnail Maker 🟡 basic version (back burner)

- ✅ Timeline-aware frames from the final edit (cached), honest analysis summary with unknowns
- ✅ Built-in creative director: 3 distinct concepts, grounded headline ideas, workflow recommendation, asks for context when needed
- ✅ Layered studio (text, shapes, image adjustments, layers, undo/redo, small previews), rule-based refinements, versions, staleness warning
- ✅ Validated 1280×720 JPEG/PNG export (YouTube rules), saved to project
- 🟡 Free local Stable Diffusion + optional OpenAI Images + Ollama/OpenAI text model: integrated, contract-tested against fake servers, **not run against real services**
- ⬜ Design scoring/review, text-model refinement in UI, image upload UI, crop handles, version compare, subject cut-outs

## Phase 5 — AI + manual integration ✅

- ✅ Open AI rough cut in the timeline, edit, re-render (tested in browser E2E)
- ✅ One-click "AI edit + finishing touches": bleeps, comedy edits, captions and audio polish run with the edit. Each step reports whether it was applied or skipped, and why (for example, no transcript). Re-running replaces earlier automatic effects rather than stacking them.
- ✅ Version history (Editor → History):
  - save named versions
  - automatic checkpoints every 10 minutes while editing, and before every AI edit and restore
  - rename and delete versions
  - restore a version (the current edit is saved first, so a restore can be undone)
  - compare any two versions: footage cut or added per source, clip, effect and transition counts, and changed settings
- ✅ Older "history/timeline-*.json" AI backups are imported as versions automatically

## Phase 6 — Advanced editor ✅

- ✅ Keyframes for scale, position, rotation, opacity and volume
  - easing: linear, ease in/out, or hold
  - anchored to the footage, so trims, splits and speed changes keep them in place
  - ◆ marks on the timeline; the preview animates too
- ✅ Rotation, opacity and crop, all previewed live in the monitor, which now shows every video layer
- ✅ 21 transitions: crossfade, dip to black/white, wipes, slides, smooth, cover/reveal, circle, radial, zoom, pixelize, blur
- ✅ Colour correction:
  - brightness, contrast, saturation, gamma, temperature
  - 8 looks: warm, cool, black & white, vintage, vivid, faded, cinematic, noir
- ✅ Light preview toggle: plays 540p proxy copies and makes any that are missing
- ✅ Render cache: re-exports reuse every unchanged segment. It's keyed on the exact FFmpeg arguments and source files, so it's never stale. 4 GB limit, oldest files evicted first
- ✅ Detailed waveforms when zoomed in (100 peaks/s, interpolated past that); "Rebuild previews" upgrades older media
- ✅ Stereo peak audio meters with peak hold and a clip light; preview volume above 100% now works (Web Audio)

## Phase 7 — Production readiness 🟡

- ✅ **My sounds & images**: record sounds with the mic or import audio/video/images into a library shared by all projects. Use them as the bleep sound (Effects panel and the Auto Editor), as sound effects, or as image pop-ups. They're copied into each project that uses them
- ✅ GitHub Actions CI on every push:
  - backend tests on **Ubuntu and Windows**
  - frontend tests, typecheck and build
  - engine → backend cross-check
  - all 8 browser E2E flows
  - a from-scratch Windows launcher run
  - `pip-audit` and `npm audit`
- ✅ Windows bugs found by that CI and fixed:
  - UTF-8 file reading
  - a crash in FFmpeg's denoiser, now with a fallback
- ✅ OpenAPI 3.1 at `/api/openapi.json` and a readable page at `/api/docs`, generated from the routes so they can't drift (the goal of the planned FastAPI move)
- ✅ Performance benchmark on a 2-hour source (`scripts/benchmark.py`; results in [docs/BENCHMARKS.md](docs/BENCHMARKS.md))
- ✅ One-click Windows launcher (`Start ClipForge.bat` / `Update ClipForge.bat`); packaging options evaluated in [docs/PACKAGING.md](docs/PACKAGING.md)
- ✅ Cloud deployment design and threat model ([docs/CLOUD.md](docs/CLOUD.md)); design only, not built
- ⬜ FastAPI migration. **Blocked here:** FastAPI can't be installed in this development environment, and a framework swap that can't be run can't be tested. The generated OpenAPI spec already covers its main benefit
- ⬜ Vite dev server + React types + component tests. **Blocked the same way** (no `vite`, `@types/react` or Testing Library packages available). Typechecking covers the engine; the UI is covered by the 8 browser E2E flows
- ✅ Windows portable package and faster re-exports: done in Phase 8 (8.7)

## Phase 8 — Creator tools 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **8.1 Shorts maker** (Shorts page): suggests the best 15–60 s moments, then makes a 9:16 project per Short. The crop follows you (face detection, or movement when no face is found) with a smooth, steady camera; optional captions and title. Each Short is a normal project you can edit
- ✅ **8.2 Reads what's said**: with a transcript the AI scores laughs, punchlines, questions, exclamations and story beats. Optional **local AI** (Ollama, or any OpenAI-compatible server on your PC) rates moments 0–10 on top; found automatically, off when not running, nothing is sent online
- ✅ **8.3 Publish page**: chapters (from topic changes, checked against YouTube's rules: first at 0:00, ≥ 3, ≥ 10 s apart), title ideas, a description with chapters, and tags (≤ 15, under YouTube's 500-character limit). The local AI can polish them if you run one
- ✅ **8.4 Upload to YouTube**: connect your own Google account with your own free API client (step-by-step in [docs/YOUTUBE.md](docs/YOUTUBE.md)); resumable upload with title, description, tags, category, thumbnail. **Private by default** and it asks before every upload. Your login stays on your PC (owner-only file, never sent to the browser). Tested against a fake Google server, **not yet against the real YouTube**
- ✅ **8.5 Suggestions from your library**: tag your sounds/images ("laugh", "fail", "wow"…) and ClipForge suggests where to drop them, from what's said and the loud reactions
- ✅ **8.6 Thumbnail Maker**: cut out the subject (no AI download needed), use your own images or library images, real face detection (bundled model), title prefilled from Publish, optional local AI for headline ideas
- ✅ **8.7 Faster re-exports**: the final video is encoded in 20-second blocks, each cached. After a small change only the blocks that changed are encoded again; the rest are copied. Checked frame by frame against a one-pass render (identical apart from encoder noise, no dropped/doubled frames at block edges)
- ✅ **8.7 Windows portable package**: a zip with Python, FFmpeg, the UI and speech-to-text inside. Nothing to install: unzip, double-click `ClipForge.bat`. Built on every push by CI, then unzipped on a clean runner with **nothing on PATH** and used to import, export and re-export a video. Unsigned, so Windows SmartScreen will warn the first time ("More info → Run anyway"). See [docs/PACKAGING.md](docs/PACKAGING.md)
- ⬜ Code-signed installer (needs a signing certificate)

## Phase 9 — Face cam & transitions 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Face cam** (Editor → **Cam**): import your webcam video and it sits over the main recording, **following every cut** (yours and the AI's), so it never drifts out of sync
  - **Line up by sound**: if the cam was recorded separately, ClipForge matches the two microphones (accurate to a few ms in tests) and says how sure it is; nudge by a frame or type an offset
  - corner presets (top/bottom, left/right), size, gap to the edge
  - square corners, rounded or **circle**; border colour/width; soft shadow
  - **Crop to my face** (head and shoulders, found with the bundled face detector)
  - **Hide** stretches (it fades out and back in) or make it **fill the screen** for a moment, by hand or on your **biggest reactions**
  - preview in the monitor matches the export (same layout maths, tested against each other)
- ✅ **Optional AI background removal** for the face cam (off by default): shows just you over the video, no green screen. Runs on your computer with a small bundled model (PP-HumanSeg, Apache-2.0, 6 MB); prepared once per recording in the background. Good, not perfect: edges around hair can be rough. Export only (the preview shows the full picture)
- ✅ **Stacked Shorts**: face cam on top, video below (or keep it in its corner, or leave it out)
- ✅ **Smoother jump cuts**: zoom punch-in (alternating close/wide, like a second camera), quick blend, or whip pan. In the Editor toolbar and in the AI's finishing touches. Only undoes changes it made itself
- ✅ **9 new transitions**: whip pan left/right, spin, glitch, RGB split, light leak, zoom blur, flash cut, shake cut (30 in total)
- ⬜ Previewing transitions in the monitor (they still show as cuts there; the export is exact)

## Phase 10 — Modern editing essentials 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Edit by transcript** (Editor → **Script**): your edit as text. Click a word to jump there; drag or Shift+click to select words and **Cut** (or press Delete). Picture and sound are cut together and the gap closes; the music keeps playing (and is trimmed with a fade if it now runs past the end). Titles and blurs move along. Undo works
- ✅ **Filler words & retakes**: "um", "uh", "hmm"… and sentences you started, stopped and said again (the same 3–5 words within 15 s; the later take is kept). Marked in the Script tab, removed in one click there, or as AI finishing touches. ClipForge asks the speech-to-text to write fillers down, but how many it catches depends on the speech
- ✅ **Titles** (Editor → **Text**): lower third, big title, top banner, subscribe button, chapter card; text, second line, colours, position, size; animated in and out. Rendered sharply by the same subtitle engine as captions; previewed in the monitor
- ✅ **Privacy blur** (Editor → **Blur**): blur, pixelate or black box; box or oval; **draw it on the preview**, or **Blur faces here** in one click; **Follow it** tracks what moves (and finds it again after a cut). Works best on things with clear detail; check the preview
- ✅ **Music beat sync** (Editor → **Beat**): finds the tempo and beats of the song on your music track (within about a frame in tests), shows them on the timeline, **snaps nearby cuts onto the beat** (roll edits: nothing else shifts, linked sound follows), and ends the music with the video. No built-in music library (licences); YouTube Studio's Audio Library has free music you can import
- ⬜ Previewing transitions in the monitor (still cuts there)

## Known limitations / bugs

- Without a transcript, "humor" and "story" styles are approximations (the UI says so).
- Very long timelines render one FFmpeg process per clip. Correct and memory-safe, but a 140-clip, 29-minute timeline took ~7 min on 2 cores.
- Block rendering (fast re-exports) is used with the software H.264 encoder. With a GPU encoder the final video is still encoded in one pass (fast already, but not cached).

- Preview colour is a CSS approximation, transitions preview as cuts, face cam background removal only shows in the export, and titles/blur preview with browser styling (close, not pixel-identical). Export is exact.
- Titles and blurs sit at timeline times: cutting with the Script tab moves them, but moving or ripple-deleting clips by hand doesn't.
- Face cam background removal runs per frame on the CPU: preparing it took 0.43× the cam's length on a 2-core VM (a 1-hour webcam recording ≈ 26 minutes), once per recording.
- Long exports are CPU-bound: a 30-minute 1080p edit took 42 min on a 2-core VM with software H.264 (see docs/BENCHMARKS.md). GPU encoders are used automatically when they work.
- Keyframed rotation/scale/opacity render through a transparent warp pass, which is slower than plain clips (about 2–3× for those clips only).
- Upload copies the file into the workspace (2× disk use for huge recordings). "Import by reference" is planned with a safe folder allow-list.
- Single-user, single-machine. Two tabs editing the same project get a conflict prompt instead of a merge.
