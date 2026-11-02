# Testing

All test media is **synthetic** (FFmpeg `lavfi` test patterns and sine tones). No copyrighted content.

## Running

```bash
cd backend  && python -m pytest            # unit + integration (real server, real FFmpeg)
cd frontend && npm test                    # timeline editing engine
cd frontend && npm run typecheck           # strict TypeScript on the engine
python scripts/e2e_browser.py              # headless Chromium end-to-end (needs Playwright + built frontend)
```

## Current results (2026-11-02)

| Suite | Tests | Result |
|---|---|---|
| Backend unit (`tests/test_unit.py`) | 29 | ✅ pass |
| Backend integration (`tests/test_api.py`) | 17 | ✅ pass (~75 s) |
| Frontend engine (`src/timeline/ops.test.ts`) | 20 | ✅ pass |
| Browser E2E (`scripts/e2e_browser.py`) | 1 flow | ✅ pass, no console errors |

## What's covered

**Unit**: path traversal (incl. symlink escape), id validation, extension allow-list, filename sanitising, atomic write + `.bak` recovery, schema rules (overlap, source bounds, track kind, rotation guard, even dimensions, unknown fields, newer-schema refusal), speed-aware duration, **frame/sample quantisation without drift over 300 clips**, gaps, hidden/muted tracks, empty-timeline guard, NTSC rates, atempo chains.

**Integration**: import + probe + thumbnail + waveform; MKV proxy + VFR flag + HTTP range; audio-only and video-only media; corrupt file, wrong type, playlist disguised as MP4 (security), duplicate detection, upload size limit; CSRF header, foreign Origin, Host-header (DNS rebinding), traversal URLs; save validation, edit-revision conflict, background-job merge, reopen; rename/duplicate/delete; in-use media protection; **mixed-source render** (different sizes, fps, speed 1.5×/2×, overlay, gap, two audio tracks) with exact frame count and validation; letterbox vs crop pixel check; **cancel mid-render with no partial output** and retry; monotonic measured progress; interrupted-job recovery on restart.

**Frontend engine**: add/link, overlap rejection, split (incl. speed), trim clamping (media bounds, neighbours, minimum length), linked trim, move/clamp/cross-track, ripple vs plain delete, duplicate, locked tracks, speed overlap guard, track add/remove, snapping, top-layer lookup, undo/redo.

**E2E**: dashboard import → editor → second import → add to timeline → split (S) → ripple delete → drag-trim → undo/redo → play → autosave → reload → export 720p → validation shown.

## Not yet covered (planned)

- React component tests (Testing Library) once npm installs are available
- Fixtures: multiple speakers, profanity, loud background noise, overlapping speech (with Phase 3/4 features)
- Benchmark suite: 2-hour synthetic source, memory and time per stage
- Interrupted render *process kill* (restart recovery is tested at the job-store level)
