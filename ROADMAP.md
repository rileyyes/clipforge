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
- ⬜ Windows installer (embedded Python + FFmpeg, Inno Setup), built and smoke-tested in CI. See PACKAGING.md

## Known limitations / bugs

- Without a transcript, "humor" and "story" styles are approximations (the UI says so).
- Very long timelines render one FFmpeg process per clip. Correct and memory-safe, but a 140-clip, 29-minute timeline took ~7 min on 2 cores.

- Preview colour is a CSS approximation, and transitions preview as cuts. Export is exact.
- Keyframed rotation/scale/opacity render through a transparent warp pass, which is slower than plain clips (about 2–3× for those clips only).
- Upload copies the file into the workspace (2× disk use for huge recordings). "Import by reference" is planned with a safe folder allow-list.
- Single-user, single-machine. Two tabs editing the same project get a conflict prompt instead of a merge.
