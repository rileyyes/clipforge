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

## Phase 4 — YouTube entertainment features ⬜ ← **next milestone**

- ⬜ Captions: subtitle track, styling, dynamic/animated captions, SRT/VTT import/export, burn-in
- ⬜ Profanity censoring at the audio level (beep / boing / record scratch / mute / custom), word-boundary padding, review warnings, matching subtitle censoring
- ⬜ Punch-ins / zooms, text callouts, chapter cards
- ⬜ Sound effects & music library with license metadata; ducking
- ⬜ Transitions (crossfade, dip to black)
- ⬜ Audio enhancement: loudness normalization (EBU R128 / −14 LUFS), noise reduction, dialogue EQ, fades
- ⬜ Intensity presets: minimal / balanced (default) / highly edited
- ⬜ Licensed/traceable visual inserts only

## Phase 4b — Thumbnail Maker 🟡 basic version (back burner)

- ✅ Timeline-aware frames from the final edit (cached), honest analysis summary with unknowns
- ✅ Built-in creative director: 3 distinct concepts, grounded headline ideas, workflow recommendation, asks for context when needed
- ✅ Layered studio (text, shapes, image adjustments, layers, undo/redo, small previews), rule-based refinements, versions, staleness warning
- ✅ Validated 1280×720 JPEG/PNG export (YouTube rules), saved to project
- 🟡 Free local Stable Diffusion + optional OpenAI Images + Ollama/OpenAI text model: integrated, contract-tested against fake servers, **not run against real services**
- ⬜ Design scoring/review, text-model refinement in UI, image upload UI, crop handles, version compare, subject cut-outs

## Phase 5 — AI + manual integration 🟡

- ✅ Open AI rough cut in the timeline, edit, re-render (tested in browser E2E)
- ⬜ Project history / versions and comparison

## Phase 6 — Advanced editor ⬜

- ⬜ Keyframes (transform, volume), rotation, crop
- ⬜ Advanced transitions & effects, color correction
- ⬜ Proxy editing toggle, background render cache
- ⬜ Waveform zoom detail, audio meters

## Phase 7 — Production readiness ⬜

- ⬜ FastAPI migration (see ARCHITECTURE.md) + OpenAPI docs
- ⬜ Vite dev server + React types + component tests (Testing Library)
- ⬜ Performance benchmarks on 2-hour sources (memory, time)
- ⬜ Packaging (Tauri wrapper evaluation, Windows installer)
- ⬜ Dependency scanning in CI (pip-audit, npm audit), GitHub Actions
- ⬜ Cloud deployment design (separate threat model)

## Known limitations / bugs

- Without a transcript, "humor" and "story" styles are approximations (the UI says so).
- Very long timelines render one FFmpeg process per clip. Correct and memory-safe, but a 140-clip, 29-minute timeline took ~7 min on 2 cores.

- Preview shows only the top-most visible video track and doesn't show scale/position. Export is correct.
- Browser preview volume can't exceed 100%. Export applies up to 400%.
- Rotation is in the schema but rejected until it's implemented.
- Upload copies the file into the workspace (2× disk use for huge recordings). "Import by reference" is planned with a safe folder allow-list.
- Single-user, single-machine. Two tabs editing the same project get a conflict prompt instead of a merge.
