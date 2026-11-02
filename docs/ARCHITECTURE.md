# Architecture

## Overview

```
 Browser (React UI)                       Python server (Starlette + Pydantic)
 ┌─────────────────────────┐   REST/JSON  ┌──────────────────────────────────────┐
 │ pages/   Dashboard …    │ ───────────► │ api.py        thin routes             │
 │ components/ Timeline,   │ ◄─────────── │ main.py       app, security middleware│
 │   Monitor, Inspector …  │  media/range │ projects.py   project store (JSON)    │
 │ timeline/ops.ts  ◄──────┼── editing    │ media.py      ingest, thumbs, proxies │
 │   (pure edit engine)    │   engine     │ render.py     timeline → MP4          │
 │ timeline/history.ts     │              │ jobs.py       background jobs         │
 └─────────────────────────┘              │ ffmpeg.py     safe FFmpeg wrapper     │
                                          │ storage.py    path safety, atomic IO  │
                                          │ schema.py     project schema (v1)     │
                                          └───────────────┬──────────────────────┘
                                                          │ argument lists only
                                                    FFmpeg / FFprobe
```

**Separation of concerns:** UI ↔ API ↔ services (projects, media, render, jobs) ↔ storage. The future `analysis/` (transcription, silence, scenes) and `decisions/` (highlight scoring, duration planning) packages plug into the same job system and produce data the timeline already understands.

## Source of truth: the project document

`<workspace>/projects/<id>/project.json` (schema in `backend/app/schema.py`, mirrored in `frontend/src/timeline/types.ts`).

- **Non-destructive.** A clip is `{media_id, source_in, source_out, start, speed, volume, transform, link_id}`. Originals are never modified (stored `chmod 0400`).
- **Validated on every save**: ids, overlap per track, in/out within media duration, media kind vs track kind, output dimensions.
- **Versioned**: `schema_version` + `migrate()` chain. Newer files are refused rather than corrupted.
- **Crash-safe**: write to temp → fsync → keep previous as `.bak` → atomic rename. A corrupt main file falls back to `.bak`.
- **Two revisions**: `revision` bumps on any write (including background jobs adding thumbnails). `edit_revision` bumps only on user timeline saves and is the conflict check. That way a background job never makes the user's autosave fail.

### Why JSON files, not a database (yet)

Single-user and local. One document per project, always loaded whole. JSON is human-inspectable, diffable, and trivially backed up. SQLite would add migrations and an ORM without solving a current problem. It becomes worthwhile for **cross-project queries** (media library across projects, search, analytics) or **transcripts/analysis at scale** (millions of words and frames). Those will go in a per-project SQLite file alongside `project.json`. For cloud/multi-user, PostgreSQL behind the same repository interface (`ProjectStore`).

## Editing engine (frontend `timeline/ops.ts`)

Pure, immutable functions return `{timeline}` or `{error}` and never partially apply. Every UI gesture (drag, keyboard, inspector field) goes through them, so the 20 unit tests cover the real behaviour. Undo/redo stores structurally-shared snapshots. Linked clips (video + its audio) move, trim, split, delete and change speed together so sync can't break. Overlaps are rejected, never silently overwritten.

## Render pipeline (`render.py`)

1. **Plan**: every clip/gap boundary is converted to an absolute frame (`round(t·fps)`) and sample (`round(t·48000)`) index. Rounding is from absolute positions, so **drift can't accumulate**: a 300-clip edit stays within ½ frame everywhere (unit-tested).
2. **Segments**: each clip renders independently with input seeking (`-ss` before `-i`), then `fps` → scale (fit/fill) → pad/trim to its exact frame count. Audio uses `atempo` (pitch-preserving speed) → 48 kHz stereo → exact sample count. A 2-hour source is never decoded end-to-end, and no filter graph buffers frames for distant clips. Memory use is bounded.
3. **Assemble**: the base video track and each audio track are joined with the concat demuxer. Upper video tracks are overlaid at their frame offsets. Audio tracks are mixed (`amix normalize=0`).
4. **Encode**: H.264 (working GPU encoder if any, else libx264) + AAC 192k, `+faststart`.
5. **Validate**: ffprobe + full decode. The report is saved next to the export.

Progress is real: per-step FFmpeg `out_time` against expected duration, combined with fixed stage weights (segments 55%, final encode 45%). Steps that can't be measured show a stage label and no percentage.

## Jobs (`jobs.py`)

A thread pool (default 1 worker, so long renders don't fight over 2–4 CPU cores). Job state is persisted as JSON. On restart, running jobs become `interrupted` and can be retried. Cancel kills the FFmpeg process, and partial outputs and work dirs are removed. The UI polls (0.7 s while active, 4 s idle). Polling was chosen over WebSockets for simplicity and robustness, and SSE can replace it without API changes.

## Preview (`Monitor.tsx`)

Master clock → playhead. One `<video>` shows the top visible video clip. One hidden `<audio>` per audio track gives a real multi-track mix. Elements re-seek only on > 0.25 s drift. Non-browser formats play from an H.264 proxy. Rendering always uses originals.

## Decisions & deviations

| Decision | Why |
|---|---|
| **Starlette instead of FastAPI** (for now) | The build environment couldn't install packages. FastAPI is a layer on Starlette, so routes are thin and models are already Pydantic, making the migration mechanical (Phase 7). |
| **esbuild instead of Vite** (for now) | Same reason. Vite uses esbuild internally, and `build.mjs` is ~30 lines. Adding Vite later only adds the dev server/HMR. |
| Custom timeline instead of a library | Evaluated options (e.g. `@xzdarcy/react-timeline-editor`, MIT) are generic "action" timelines without linked A/V, ripple semantics or media-aware trimming. The editing logic would live outside them anyway, and the view is ~350 lines. |
| No Tauri yet | A localhost web app already gives a desktop-like experience. Tauri adds a Rust toolchain and signing for little gain until there's an installer phase. Revisit in Phase 7. |
| No auth | Local single-user app bound to 127.0.0.1. Accounts are designed in SECURITY.md for a future cloud mode. |
| Upload copies media | Safest (no arbitrary path access). Import-by-reference needs an allow-listed folder model. |

## AI Auto Editor (`analysis.py`, `autoedit.py`, `transcription.py`)

**Analysis** (job `analyze`) streams decoded audio (16 kHz mono) and tiny grey frames (64×36 @ 4 fps) out of FFmpeg in chunks. It stores loudness and motion on a 50 ms grid plus hard-cut timestamps in `<project>/analysis/<media_id>.json`. A 2-hour file is ~144k values per signal. An optional `Transcriber` provider adds word timestamps.

**Planning** (`plan()`, pure and deterministic, ~10 ms for 10 min, < 10 s for 2 h):
1. Adaptive threshold between the noise floor (10th percentile) and speech level (90th) → sound regions. Gaps shorter than the preset's minimum silence are bridged (natural pauses stay). Regions are padded by the retained pause. With a transcript, edges are extended so no word is cut.
2. Regions are grouped into *beats*, split only at their longest pause. Beat size adapts to the target (≤ target/4, 4–45 s). A pause-less run over 45 s is split at its quietest point.
3. Features per beat → tie-aware percentile ranks → style weights → score 0–100, plus the top contributing reasons in plain words.
4. Selection: user includes → opening hook (if it fits) → highest scores that fit → setup beats before chosen ones. Chronological EDL.
5. `validate_edl` (inside media, ordered, non-overlapping, ≥ min length) before anything touches a project. `apply` recomputes the plan server-side and refuses if it differs from what the user reviewed.

The EDL becomes ordinary linked clips, so everything the Manual Editor can do applies to an AI edit. An LLM, if added later, will only ever *suggest* include/exclude/score adjustments that go through the same validation.
