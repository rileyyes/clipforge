# Testing

All test media is **synthetic** (FFmpeg `lavfi` test patterns and sine tones). No copyrighted content.

## Running

```bash
cd backend  && python -m pytest            # unit + integration (real server, real FFmpeg)
cd frontend && npm test                    # timeline editing engine
cd frontend && npm run typecheck           # strict TypeScript on the engine
python scripts/e2e_browser.py              # headless Chromium end-to-end (needs Playwright + built frontend)
```

## Current results (2026-11-05, Phase 11) — full suite (`scripts/verify_all.sh`) run 3× in a row locally and green in CI on Ubuntu + Windows

| Suite | Tests | Result |
|---|---|---|
| Backend unit (`tests/test_unit.py`) | 29 | ✅ |
| Backend integration (`tests/test_api.py`) | 17 | ✅ |
| Auto Editor (`tests/test_autoedit.py`) | 30 (incl. 400 random recordings) | ✅ |
| Effects (`tests/test_effects.py`) | 49 (incl. audio-level censor verification by FFT, frame diffs for every visual effect, fake-transcriber API flow) | ✅ |
| Audio & transitions (`tests/test_audio_transitions.py`) | 12 (pixel-measured crossfade/dip/fades, ducking measured in the 220 Hz band, noise floor, −14/−16 LUFS) | ✅ |
| Look & animation (`tests/test_look.py`) | 51 (keyframe maths vs FFmpeg expressions, pixel-measured rotation, crop, opacity, colour/looks, volume keyframes, all 21 transitions) | ✅ |
| Render cache & previews (`tests/test_perf.py`) | 6 (full reuse, only changed clip re-renders, off switch, eviction, proxy + 100 peaks/s waveform) | ✅ |
| Block rendering (`tests/test_blocks.py`) | 6 (block windows; block render vs one-pass render **frame by frame** with zoom, shake, flash, pop-up, keyframed overlay, wipe and captions across 1 s block edges; audio matches; exact frame counts at 25/30 fps over 0.4 s blocks; a small edit re-encodes one block and the copied blocks are bit-identical; a caption word change only touches nearby blocks) | ✅ |
| Phase 11 engine (`ops.test.ts`, `keyframes.test.ts`) | ripple delete moves titles/blurs (and not without ripple); transition timing (centred on the cut, both pictures' source times); every one of the 30 transitions' preview starts on the old picture and ends on the new | ✅ |
| Browser E2E: Phase 11 | at 1280×720: no horizontal overflow on the Editor and AI Auto Editor, Export button and all 8 tabs on screen → click/drag/resize a title on the lane → mid-crossfade preview shows both pictures → ? sheet → J/K/L → guides → ripple delete moves the title → undo | ✅ no console errors |
| Fillers & retakes (`tests/test_cleanup.py`, `cleanup.test.ts`) | 8 + shared vectors run by Python and TypeScript (fillers, retakes incl. one with an "uh" inside, no false retakes on "yes yes yes", too far apart, punctuation/case; cuts never reach into neighbouring words; segment subtraction) + the AI finishing touch end to end (2 fillers + 1 retake removed, length checked) | ✅ |
| Edit by transcript (`ops.test.ts`, `cleanup.test.ts`, fuzz) | cutRanges: picture + sound cut together, pieces relinked, overlapping ranges merged, music trimmed with a fade, locked tracks refused; editWords maps words through cuts and speed; fuzz + cross-check include cutRanges, titles, blurs and beat snaps | ✅ |
| Titles (`tests/test_titles.py`) | 7 (lower third slides in and shows text, big title / banner / subscribe draw where they should, chapter card dims, block render = one-pass, editing one title re-encodes only its blocks, validation) | ✅ |
| Privacy blur (`tests/test_blur.py`) | 8 (blur / pixelate / black only inside the box and only while on, oval leaves the corners, moving keys + block render = one-pass, 240-key expressions evaluate correctly, tracking follows a moving square within 2% of the frame, API: tracking across two pieces with a cut (re-found after the cut), faces) | ✅ |
| Beat detection (`tests/test_beats.py`, `ops.test.ts`) | 6 (90/120/128/150 BPM found within 1.5 BPM and beats within about a frame, silence, API + cache) + snap cuts to beats (roll edits, linked sound, nothing else moves, no-footage case) + fit music | ✅ |
| Browser E2E: Phase 10 | transcript (written directly) → remove 2 fillers → 1 retake → cut a word → lower third (preview) → draw a blur on the preview → follow it → find the beat (119.7 BPM) → snap cuts → reload → export shows the title | ✅ no console errors |
| Face cam (`tests/test_facecam.py`) | 20 (corner maths, tall cams stay on screen, following cuts with offset/hidden/full ranges, renders checked by pixel: follows the cuts (colour-coded cam), circle + border + shadow, hide fades + full screen, block render = one-pass render, background removal on a real photo of a person (background replaced, person kept, mask reused), off by default, stacked Shorts, API flow incl. sync job, delete guard, null removes; layout vectors shared with the Editor) | ✅ |
| Sync by sound & crop to face (`tests/test_sync.py`) | 9 (offsets +2.37/−1.23/0/+11.5 s found within 3 ms with a duller, quieter, noisy second mic; unrelated audio = low confidence; real AAC files; face crop finds the face; no face = no crop) | ✅ |
| New transitions (`tests/test_transitions9.py`) | 18 (all 9 render and land on both clips; whip moves sideways, flash goes white, shake moves, light leak is warm top-right, glitch mixes bands, spin rotates and ends upright on the right frames, zoom blur zooms) | ✅ |
| Smoother jump cuts (`tests/test_jumpcuts.py`, `jumpcuts.test.ts`) | shared vectors run by both Python and TypeScript (punch alternates, splits/gaps/other files skipped, too-short pieces skipped, idempotent, fully reversible, your own crops/transitions kept) + the AI finishing touch end to end | ✅ |
| Browser E2E: face cam | add → lined up by sound (−1.000 s) → top-left circle (preview checked: position, size, round) → crop to face → background removal prepared → hide 2–3 s (preview hides it) → jump-cut punch-in → undo/redo → reload → export shows the cam (and not while hidden) | ✅ no console errors |
| Phase 8 creator tools | Shorts 10 (moment picking, face + motion tracking, steady camera path, vertical render that follows the subject), language/AI 9, Publish 7 (chapter rules, tags limits, API), YouTube 5 (client file checks, one-time sign-in state + PKCE, resumable upload surviving partial writes and a 503, scheduling forces private, quota message, full API flow; all against a fake Google), library suggestions 4, cut-out 4 | ✅ |
| My library (`tests/test_library.py`) | 14 (mic-style WebM/Ogg/MP3/WAV import, silence trim, −1 dBFS levelling, 30 s cap, bad/silent files, images re-encoded/downscaled, custom bleeps & sound effects verified by FFT, library deletion vs. project copies, duplicate keeps assets, API + path safety) | ✅ |
| OpenAPI (`tests/test_openapi.py`) | 2 (every route documented, bodies resolved, CSRF header on every write, script-free docs page) | ✅ |
| Version history & one-click extras (`tests/test_history.py`) | 9 (snapshots, throttled checkpoints, pruning, legacy import, compare maths, restore/undo-restore/conflict, deleted-media guard, one-click extras with and without a transcript, idempotent re-run, render) | ✅ |
| Thumbnail Maker (`tests/test_thumbnails.py`) | 36 (incl. provider contract tests vs fake servers) | ✅ |
| Frontend thumbnail model (`thumbs/model.test.ts`) | 5 | ✅ |
| Frontend engine unit (`ops.test.ts`) | 20 | ✅ |
| Frontend keyframes (`keyframes.test.ts`) | 4 (same vectors as the backend, split/trim keep keyframes on the footage) | ✅ |
| Frontend engine fuzz (`fuzz.test.ts`) | 10 × 1,500 random edits by default, now including keyframes, crop, colour, rotation/opacity and all transitions. Run at **200 × 1,500** after Phase 6 (earlier: 1,000 × 1,500 = 1.5 M edits) | ✅ |
| Engine → backend cross-check (`scripts/crosscheck.py`) | 200 random timelines / 12,331 clips (3,532 keyframed, 6,297 cropped + coloured) accepted. Earlier: 1,000 / 79,920 | ✅ |
| Renderer stress (`scripts/render_stress.py 3`) | 3 fuzz timelines with Phase 6 features, 54–79 clips, 2–4 min (earlier: 112–138 clips, 10–29 min) | ✅ all validated |
| Browser E2E: manual editor | full flow | ✅ no console errors |
| Browser E2E: AI auto editor | full flow incl. finishing touches (applied/skipped report) | ✅ no console errors |
| Browser E2E: advanced editor | rotation + crop + B&W + 2-keyframe zoom (preview checked) + volume keyframes + wipe → meters move → light preview proxy → reopen → export frame is rotated & grey → 2nd export fully cached | ✅ no console errors |
| Browser E2E: my library | fake mic → record → save → use as bleep → find swears → import image → add both at playhead → export: the swear is replaced by *your* recording (FFT), the image is in the frame → shared with a new project | ✅ no console errors |
| **CI (GitHub Actions)** | every push: backend on **Ubuntu + Windows**, frontend (incl. a typecheck of the whole UI with React types), cross-check, all browser E2E flows, Windows launcher from scratch, **Windows portable package built and run from a clean PATH** (import → export → cached re-export), pip-audit + npm audit | ✅ all green |
| Smoke test (`scripts/smoke_export.py`) | against a running server: import, export, validation, re-export with every block cached. In `verify_all.sh` and in CI on the portable package | ✅ |
| Benchmark (`scripts/benchmark.py`) | 2-hour source → 30-min 1080p edit, see docs/BENCHMARKS.md | ✅ validated |
| Browser E2E: version history | save version → delete clip → compare → restore → undo the restore → reload | ✅ no console errors |
| Browser E2E: effects | transcript → bleeps → auto comedy edits → pop-up → captions → undo/redo → export → reopen | ✅ no console errors |
| Browser E2E: audio | crossfade + fades + music role + noise/enhance/ducking → export with loudness check → reopen | ✅ no console errors |
| Browser E2E: thumbnail maker | analyse → concepts → studio → version → export → reopen | ✅ no console errors |

Run everything: `scripts/verify_all.sh`.

### Bugs found by this testing (all fixed)

| Found by | Bug |
|---|---|
| screenshots at 1280×720 | The Editor ran ~60 px off the screen (the timeline toolbar couldn't shrink): Export button and side tabs cut off. The AI Auto Editor's two columns overlapped |
| e2e (Phase 11) | Transition preview layers broke the stacking of upper tracks (V1 could cover V2); fixed with per-track layers, face cam on top |
| fuzz | Cutting stretches out of a music track holding both linked and free clips made clips overlap; picture linked to sound on a music track went out of sync |
| fuzz | Snapping two neighbouring cuts to beats could shrink the clip between them to nothing |
| blur API test | After a cut the followed object jumped and tracking lost it (it only searched nearby); it now searches the whole frame after each cut |
| beat tests | Beats landed on the hi-hats between kicks, then 80 ms early (frames timed at the window start) |
| title/blur tests | Missing `json`/`subprocess` imports in two new endpoints (500 errors) |
| transition tests | New transitions came out noisy or solid green: FFmpeg runs custom transition expressions on several threads that share their variables, and `a0()` reads plane 0 only. Now single-threaded with per-plane sampling |
| transition tests | Spin: the incoming clip started on the wrong frame and stayed rotated |
| face cam tests | A very tall (phone) face cam could reach past the top edge |
| browser E2E | Face cam panel couldn't scroll (it slid under the timeline); preview circle was oval when the monitor's shape differed from the video's; the side tabs no longer fit |
| block-render tests | FFmpeg's accurate seek kept one frame too many when several inputs feed a `concat` filter (picture one frame late inside a block). Now: coarse seek with timestamps kept, exact trim in the graph |
| block-render tests | The concat demuxer can't seek accurately at all (blocks came out empty). Now each segment is its own input |
| CI (Ubuntu + Windows) | OpenCV 5.x wheels have no Haar face detector, so Shorts and thumbnail face finding crashed. Pinned OpenCV < 5, and both now fall back to motion if a build lacks it |
| CI UI typecheck | Two type errors the bundler doesn't check (a union type missing `created`, CSS import declaration) |
| CI portable job | Windows PowerShell 5.1 treated pip/npm notices on stderr as fatal; the pinned FFmpeg file name had moved |
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
| fuzz cross-check | The editor accepted unsorted, duplicate or out-of-range keyframes (and out-of-range crop/colour) that the server rejects. The engine now applies the same rules |
| render stress | Soft audio with sharp peaks finished 2–5 dB under the loudness target (FFmpeg's loudnorm silently gives up). A limiter pass now closes the gap |
| browser E2E | Monitor layers lost their position (`inset` overrode `left/top`) |
| Windows CI | JSON written as UTF-8 was read with the Windows code page: names with curly quotes/accents/emoji (e.g. a saved version) silently vanished. All file IO is now UTF-8 |
| Windows CI | FFmpeg's `anlmdn` denoiser crashed (0xC0000374) at "strong". The mix retries with `afftdn` + gate (same hiss reduction on the test) |
| Windows CI | Saving `project.json` failed ("Access is denied") while a background job had it open, so an upload errored. Replaces now retry briefly; the backup step no longer leaves a moment with no project file (all OSes) |
| Windows CI | Launcher: the first run opened an interactive Python prompt (argument splatting in PowerShell 5.1), picked a too-new Python 3.15, and needed a cmdlet that isn't always available. All fixed; CI now runs the `.bat` from scratch |
| library work | Duplicating a project dropped its pop-up images, sounds and transcripts |
| user report | "Find & bleep swears" was greyed out with no reason (no transcript yet), and stayed greyed out after adding clips because the transcript status went stale. It now explains what's needed, has a **Transcribe now** button, and refreshes |
| user report | A failed transcription (e.g. the one-time speech-model download failing) was hidden: the panel just went back to "Transcribe speech". Failures now show with the reason, Details and Retry, and model loading is its own labelled step instead of looking stuck at 0% |
| user report | After installing speech-to-text, "Analyse recording" failed when the transcriber couldn't load (e.g. model download). Transcription is now optional inside analysis: the AI edit still works from sound + picture and shows the reason |
| user report | Every transcription failed with `open() got an unexpected keyword argument 'metadata_errors'`: PyAV 19 (Sept 2026) dropped an argument faster-whisper 1.2.x still passes. ClipForge now decodes the audio with its own FFmpeg and gives Whisper raw samples in 20-minute chunks, with exact time offsets (tested), and `av<19` is pinned |

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
