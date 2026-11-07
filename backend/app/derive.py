"""Freeze frames and reversed clips, made as new media files (Phase 15).

They become ordinary media items, so the preview plays them and every edit (trim,
split, move, export) works on them with no special cases:

* freeze: one frame of a recording held for N seconds (no sound).
* reverse: a range of a recording played backwards (sound too). FFmpeg's reverse filter
  keeps every frame in memory, so the range is reversed in 2-second pieces that are then
  joined last-to-first, which keeps memory small (about 2 s of frames at a time).
"""
from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from . import ffmpeg as ff

FREEZE_MAX = 10.0
REVERSE_MAX = 60.0
CHUNK = 2.0


def _enc(fps: float) -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", f"{fps:.6f}"]


def freeze(ffmpeg_bin: str, src: Path, t: float, seconds: float, fps: float, dest: Path) -> None:
    """Hold the frame at `t` (seconds into src) for `seconds`."""
    seconds = min(FREEZE_MAX, max(0.2, seconds))
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "f.png"
        ff.run_ffmpeg(ffmpeg_bin, [*ff.untrusted_input_args(src, seek=max(0.0, t)), "-frames:v", "1", "-an", str(png)])
        if not png.exists():
            raise ff.FFmpegError("Couldn't grab that frame (is the time past the end?)")
        ff.run_ffmpeg(ffmpeg_bin, ["-loop", "1", "-framerate", f"{fps:.6f}", "-i", str(png), "-t", f"{seconds:.3f}",
                                   "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1", *_enc(fps), "-an", str(dest)])


def reverse(ffmpeg_bin: str, src: Path, start: float, end: float, fps: float, has_audio: bool, dest: Path,
            cancel=None, on_progress=None) -> None:
    """src[start:end] played backwards (picture and sound)."""
    end = min(end, start + REVERSE_MAX)
    n = max(1, math.ceil((end - start) / CHUNK - 1e-9))
    with tempfile.TemporaryDirectory() as td:
        parts = []
        for i in range(n):
            a = start + i * CHUNK
            d = min(CHUNK, end - a)
            if d <= 0.01:
                break
            part = Path(td) / f"p{i:03d}.mp4"
            audio = ["-af", "areverse", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"] if has_audio else ["-an"]
            ff.run_ffmpeg(ffmpeg_bin, [*ff.untrusted_input_args(src, seek=a, duration=d), "-vf", f"fps={fps:.6f},reverse",
                                       *audio, *_enc(fps), str(part)], cancel_event=cancel)
            parts.append(part)
            if on_progress:
                on_progress((i + 1) / n)
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in reversed(parts)), encoding="utf-8")
        ff.run_ffmpeg(ffmpeg_bin, ["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(dest)],
                      cwd=Path(td))


def output_fps(media_fps: Optional[float]) -> float:
    return media_fps if media_fps and 1 <= media_fps <= 240 else 30.0


__all__ = ["freeze", "reverse", "FREEZE_MAX", "REVERSE_MAX", "output_fps", "shutil"]
