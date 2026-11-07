# Benchmarks

Measured with `scripts/benchmark.py` on 2026-11-03. A **120-minute** synthetic 720p30 recording (moving picture; speech-like audio with pauses and loud reactions) goes through the real HTTP API: import → preparation → analysis → AI plan to **30 minutes** → apply → **1080p export** → re-export.

**Machine:** 2 CPU cores, 7.8 GB RAM, Linux, Python 3.13.18, software H.264 (libx264). It's a small cloud VM, so a typical recent laptop with 4–8 cores should be roughly 2–3× faster at exporting. Transcription was off (it's measured separately; see the notes below).

| Step | Time | Peak memory (server + FFmpeg) | Server process alone |
|---|---|---|---|
| import (upload + probe) | 8.0 s (0.1 min) | 142 MB | 83 MB |
| prepare (thumbs + waveform) | 24.1 s (0.4 min) | 166 MB | 94 MB |
| analysis | 180.3 s (3.0 min) | 189 MB | 102 MB |
| AI plan | 0.1 s (0.0 min) | 102 MB | 102 MB |
| apply to timeline | 0.2 s (0.0 min) | 123 MB | 123 MB |
| export | 2,526.4 s (42.1 min) | 471 MB | 122 MB |
| re-export (render cache) | 1,414.9 s (23.6 min) | 462 MB | 104 MB |

- **Analysis:** 39.9× faster than real time. A 2-hour recording takes about 3 minutes and never needs more than ~190 MB, because it streams.
- **AI plan:** 303 cuts, 30.6-minute result, planned in a fraction of a second.
- **Export:** 0.73× real time on 2 cores, with peak memory under 0.5 GB. All validation checks passed: duration, A/V sync, frame count and full decode.
- **Re-export:** all 606 segments came from the render cache (0 rendered again). That saved about 44%. The rest is the final full-length encode, which always runs.

## Faster re-exports (block rendering, Phase 8)

Measured 2026-11-04 on the same 2-core VM: a 10-minute 720p source cut to a **3-minute** 720p edit (30 cuts), run twice, once with block rendering and once with it turned off (`RJCLIP_BLOCK_RENDER=0`, the old one-pass final encode):

| | One-pass final encode (before) | Block rendering (now) |
|---|---|---|
| first export | 144.2 s | 141.3 s |
| re-export, nothing changed | 87.2 s | **42.1 s** (9 of 9 blocks copied) |
| re-export after adding one flash | (≈ 87 s, the full encode runs again) | **51.1 s** (8 of 9 blocks copied) |

- The first export costs the same. Every re-export skips the final encode for everything that didn't change.
- What's left in a re-export is the audio mix (noise removal, ducking, two-pass loudness), copying, and the full-decode validation of the result. Those run every time because they're quick to redo and need the whole timeline.
- The 2-hour table above was measured before block rendering, so its re-export line is the old behaviour.

## Face cam background removal (Phase 9)

Measured 2026-11-05 on the same 2-core VM: preparing background removal for a 60-second 1280×720 webcam video took **26.0 s (0.43× its length)**. It runs once per face cam recording, in the background; exports reuse it. The mask file is tiny (about 70 KB per minute).

## What this means for you

- Memory is not a concern: even the 2-hour run stayed under half a gigabyte.
- Long exports are CPU-bound. On a 4–8-core PC, expect very roughly 15–25 minutes for a 30-minute 1080p video. A working GPU encoder (NVENC, Quick Sync, AMF; detected automatically) is much faster for the final encode.
- Small changes re-export fast: only the clips and 20-second stretches you touched are encoded again (see *Faster re-exports* above). With a GPU encoder the final encode is still one pass, without that cache.

## Transcription (not in the table)

Not measured: faster-whisper can't be installed in the environment these benchmarks ran in. Its speed depends heavily on the CPU (or GPU, with `RJCLIP_WHISPER_DEVICE=cuda`). On a 2-hour recording, expect it to take longer than the sound/picture analysis above, plus a one-time ~480 MB model download. The progress bar shows the real rate on your machine.

## Re-running

```bash
pip install psutil
python scripts/benchmark.py                       # 2 h → 30 min at 1080p (about 1.5 h on 2 cores)
python scripts/benchmark.py --minutes 10 --target 3 --export-height 720   # quick check
```

Raw numbers: [benchmark-results.json](benchmark-results.json).
