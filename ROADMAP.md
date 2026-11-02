# Roadmap & feature status

This file is the **persistent project checklist**. Update it whenever a feature lands, so progress survives across sessions.

Legend: ✅ done & tested · 🟡 partial (see note) · ⬜ not started

## Phase 1 — Foundation ✅

- ✅ Environment inspection, architecture, repo structure
- ✅ Versioned project schema (v1) with semantic validation and a migration hook
- ✅ Safe media import: streaming upload, size/quota limits, extension allow-list, FFprobe validation, SHA-256 de-dup, read-only originals
- ✅ FFmpeg/FFprobe integration (argument lists, protocol + demuxer whitelists, timeouts, measured progress, cancel)
- ✅ Thumbnails, waveforms, browser preview proxies (background jobs)
- ✅ Dark UI shell: Dashboard, AI Auto Editor (status page), Manual Editor, Projects, Export, Settings
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

## Phase 3 — Automatic editing engine ⬜ ← **next milestone**

- ⬜ Audio extraction for analysis (16 kHz mono, chunked)
- ⬜ Transcription with word timestamps (faster-whisper, local, CPU-capable) behind a provider interface
- ⬜ Silence / pause detection with conservative / balanced / aggressive presets and minimum retained pause
- ⬜ Scene / shot detection on a low-res proxy (chunked, memory-bounded)
- ⬜ Audio energy, speech rate, laughter/reaction heuristics
- ⬜ Highlight candidates with explainable, weighted scores (humor / excitement / information / story / reactions / balanced)
- ⬜ Duration planner (target length, % reduction, original; feasibility warnings; natural boundaries; setup→payoff preservation)
- ⬜ Structured, validated, deterministic edit decision list (EDL)
- ⬜ Review UI: accept / reject / adjust each cut with its reason
- ⬜ "Send to Manual Editor" → EDL becomes normal timeline clips
- ⬜ Optional LLM provider (local or API) for context reasoning; rule-based mode works without it

## Phase 4 — YouTube entertainment features ⬜

- ⬜ Captions: subtitle track, styling, dynamic/animated captions, SRT/VTT import/export, burn-in
- ⬜ Profanity censoring at the audio level (beep / boing / record scratch / mute / custom), word-boundary padding, review warnings, matching subtitle censoring
- ⬜ Punch-ins / zooms, text callouts, chapter cards
- ⬜ Sound effects & music library with license metadata; ducking
- ⬜ Transitions (crossfade, dip to black)
- ⬜ Audio enhancement: loudness normalization (EBU R128 / −14 LUFS), noise reduction, dialogue EQ, fades
- ⬜ Intensity presets: minimal / balanced (default) / highly edited
- ⬜ Licensed/traceable visual inserts only

## Phase 5 — AI + manual integration ⬜

- ⬜ Open AI rough cut in the timeline, edit, re-render
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

- Preview shows only the top-most visible video track and doesn't show scale/position. Export is correct.
- Browser preview volume can't exceed 100%. Export applies up to 400%.
- Rotation is in the schema but rejected until it's implemented.
- Upload copies the file into the workspace (2× disk use for huge recordings). "Import by reference" is planned with a safe folder allow-list.
- Single-user, single-machine. Two tabs editing the same project get a conflict prompt instead of a merge.
