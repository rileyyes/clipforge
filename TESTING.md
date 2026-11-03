# Testing

All test media is **synthetic** (FFmpeg `lavfi` test patterns and sine tones). No copyrighted content.

## Running

```bash
cd backend  && python -m pytest            # unit + integration (real server, real FFmpeg)
cd frontend && npm test                    # timeline editing engine
cd frontend && npm run typecheck           # strict TypeScript on the engine
python scripts/e2e_browser.py              # headless Chromium end-to-end (needs Playwright + built frontend)
```

## Current results (2026-11-03) — full suite run 3× in a row, all green

| Suite | Tests | Result |
|---|---|---|
| Backend unit (`tests/test_unit.py`) | 29 | ✅ |
| Backend integration (`tests/test_api.py`) | 17 | ✅ |
| Auto Editor (`tests/test_autoedit.py`) | 30 (incl. 400 random recordings) | ✅ |
| Effects (`tests/test_effects.py`) | 49 (incl. audio-level censor verification by FFT, frame diffs for every visual effect, fake-transcriber API flow) | ✅ |
| Audio & transitions (`tests/test_audio_transitions.py`) | 12 (pixel-measured crossfade/dip/fades, ducking measured in the 220 Hz band, noise floor, −14/−16 LUFS) | ✅ |
| Version history & one-click extras (`tests/test_history.py`) | 9 (snapshots, throttled checkpoints, pruning, legacy import, compare maths, restore/undo-restore/conflict, deleted-media guard, one-click extras with and without a transcript, idempotent re-run, render) | ✅ |
| Thumbnail Maker (`tests/test_thumbnails.py`) | 36 (incl. provider contract tests vs fake servers) | ✅ |
| Frontend thumbnail model (`thumbs/model.test.ts`) | 5 | ✅ |
| Frontend engine unit (`ops.test.ts`) | 20 | ✅ |
| Frontend engine fuzz (`fuzz.test.ts`) | 10 × 1,500 random edits by default; also run at **1,000 × 1,500 (1.5 M edits)** | ✅ |
| Engine → backend cross-check (`scripts/crosscheck.py`) | 1,000 random timelines / 79,920 clips accepted | ✅ |
| Renderer stress (`scripts/render_stress.py 3`) | 3 fuzz timelines, 112–138 clips, 10–29 min | ✅ all validated |
| Browser E2E: manual editor | full flow | ✅ no console errors |
| Browser E2E: AI auto editor | full flow incl. finishing touches (applied/skipped report) | ✅ no console errors |
| Browser E2E: version history | save version → delete clip → compare → restore → undo the restore → reload | ✅ no console errors |
| Browser E2E: effects | transcript → bleeps → auto comedy edits → pop-up → captions → undo/redo → export → reopen | ✅ no console errors |
| Browser E2E: audio | crossfade + fades + music role + noise/enhance/ducking → export with loudness check → reopen | ✅ no console errors |
| Browser E2E: thumbnail maker | analyse → concepts → studio → version → export → reopen | ✅ no console errors |

Run everything: `scripts/verify_all.sh`.

### Bugs found by this testing (all fixed)

| Found by | Bug |
|---|---|
| fuzz | Ripple delete could shift linked video and audio by different amounts (A/V out of sync) |
| fuzz | Speeding up a very short clip could make it shorter than the minimum (server would reject the save) |
| fuzz | The last video/audio track could be removed |
| fuzz | Float rounding let a trim extend over the next clip (overlap) |
| auto-edit tests | Tied features got different ranks by position, biasing scores |
| auto-edit tests | A loud moment merged into a long beat couldn't be selected for short targets |
| auto-edit tests | Even-splitting a long phrase could cut mid-word |
| auto-edit tests | Video without audio became one giant moment; opening hook could overshoot the target |
| browser E2E | Split ignored the playhead when a newly-added clip was selected |
| integration | MKV files weren't given a browser preview proxy |
| screenshots | Ruler label drift, duration rounding mismatch, wrapping badges |
| test runner | Frontend tests were running stale compiled copies after adding a second test folder |
| screenshots | Footage-built thumbnails were wrongly labelled as AI artwork |
| effects tests | Frequent reactions raised the loudness percentile so none were detected |
| browser E2E | Transcript status hidden when transcripts existed but the transcriber wasn't installed |
| screenshots | New pop-ups could stack on top of a showing one; effects panel controls clipped |
| user report | requirements.txt missed OpenCV; missing FFmpeg gave a vague "Upload failed" |
| transition tests | FFmpeg's "fadeblack" never reaches black — dip to black rebuilt as fade-out/fade-in |
| noise tests | `afftdn` barely reduced broadband hiss — switched to `anlmdn` (−85–95% hiss, voice level unchanged) |
| fuzz cross-check | Editor rounded a max transition length up by 1 µs, which the server rejected |
| history tests | Two versions saved in the same second could sort in the wrong order, which broke checkpoint throttling. Versions now store a precise timestamp |
| browser E2E | Compare with "Current edit" could show the server's stale copy while an edit was still waiting to autosave. Unsaved edits are now saved before comparing |
| screenshots | Long version names pushed the History panel wider than the sidebar |

## What's covered

**Unit**: path traversal (incl. symlink escape), id validation, extension allow-list, filename sanitising, atomic write + `.bak` recovery, schema rules (overlap, source bounds, track kind, rotation guard, even dimensions, unknown fields, newer-schema refusal), speed-aware duration, **frame/sample quantisation without drift over 300 clips**, gaps, hidden/muted tracks, empty-timeline guard, NTSC rates, atempo chains.

**Integration**: import + probe + thumbnail + waveform; MKV proxy + VFR flag + HTTP range; audio-only and video-only media; corrupt file, wrong type, playlist disguised as MP4 (security), duplicate detection, upload size limit; CSRF header, foreign Origin, Host-header (DNS rebinding), traversal URLs; save validation, edit-revision conflict, background-job merge, reopen; rename/duplicate/delete; in-use media protection; **mixed-source render** (different sizes, fps, speed 1.5×/2×, overlay, gap, two audio tracks) with exact frame count and validation; letterbox vs crop pixel check; **cancel mid-render with no partial output** and retry; monotonic measured progress; interrupted-job recovery on restart.

**Auto Editor**: analysis against synthetic recordings with planted pauses, a natural 0.3 s pause, dead air, a loud reaction and colour-cut scene changes (found within 0.3 s); every preset/style/target combination yields a valid EDL; cuts never inside sound; word-boundary snapping; include/exclude/opening; warnings for unrealistic targets; determinism; 2-hour-scale planning < 10 s; no-audio and silent/noise-only media; full API flow analyse → plan → stale-apply refused → apply → render validated.

**Frontend engine**: add/link, overlap rejection, split (incl. speed), trim clamping (media bounds, neighbours, minimum length), linked trim, move/clamp/cross-track, ripple vs plain delete, duplicate, locked tracks, speed overlap guard, track add/remove, snapping, top-layer lookup, undo/redo.

**E2E**: dashboard import → editor → second import → add to timeline → split (S) → ripple delete → drag-trim → undo/redo → play → autosave → reload → export 720p → validation shown.

## Not yet covered (planned)

- React component tests (Testing Library) once npm installs are available
- Fixtures: multiple speakers, profanity, loud background noise, overlapping speech (with Phase 3/4 features)
- Benchmark suite: 2-hour synthetic source, memory and time per stage
- Interrupted render *process kill* (restart recovery is tested at the job-store level)
