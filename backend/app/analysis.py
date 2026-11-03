"""Media analysis for the AI Auto Editor (signal-based, runs locally, no paid APIs).

Everything streams through FFmpeg in small chunks, so a 2-hour recording uses a
few MB of RAM. Results are cached as JSON per media file.

Signals (all on a fixed time grid, HOP seconds per value):
* ``rms_db``   loudness of the mono mix in dBFS (speech, reactions, dead air)
* ``motion``   mean absolute luma difference between low-res frames (on-screen action)
* ``cuts``     timestamps of hard scene/shot changes

Transcription is a pluggable provider (see ``transcription.py``); the decision
engine works with or without it.
"""
from __future__ import annotations

from .storage import replace_retry

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import ffmpeg as ff
from .config import Settings
from .schema import MediaAsset

ANALYSIS_VERSION = 1
HOP = 0.05  # seconds per analysis value (20 / s)
AUDIO_RATE = 16000
VIDEO_FPS = 4  # frames per second sampled for motion / cuts
VW, VH = 64, 36


def _stream(cmd: list[str], chunk: int, cancel: Optional[threading.Event]):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise ff.Cancelled("cancelled")
            data = proc.stdout.read(chunk)
            if not data:
                break
            yield data
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        proc.wait()
        if proc.returncode not in (0, -9) and not (cancel and cancel.is_set()):
            raise ff.FFmpegError("analysis decode failed", err)


def audio_loudness(settings: Settings, src: Path, duration: float,
                   on_progress: Callable[[float], None] = lambda f: None,
                   cancel: Optional[threading.Event] = None) -> list[float]:
    """Per-HOP RMS loudness (dBFS, floor -90)."""
    hop_n = int(AUDIO_RATE * HOP)
    cmd = [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-v", "error",
           *ff.untrusted_input_args(src), "-vn", "-ac", "1", "-ar", str(AUDIO_RATE),
           "-f", "s16le", "pipe:1"]
    out: list[float] = []
    buf = b""
    expected = max(1, int(duration / HOP))
    for data in _stream(cmd, hop_n * 2 * 200, cancel):
        buf += data
        usable = len(buf) - len(buf) % (hop_n * 2)
        if usable:
            x = np.frombuffer(buf[:usable], dtype="<i2").astype(np.float32).reshape(-1, hop_n) / 32768.0
            rms = np.sqrt(np.mean(x * x, axis=1))
            out.extend(np.maximum(20 * np.log10(np.maximum(rms, 1e-12)), -90.0).round(2).tolist())
            buf = buf[usable:]
            on_progress(min(1.0, len(out) / expected))
    return out


def video_motion(settings: Settings, src: Path, duration: float,
                 on_progress: Callable[[float], None] = lambda f: None,
                 cancel: Optional[threading.Event] = None) -> tuple[list[float], list[float]]:
    """Motion per HOP (interpolated from VIDEO_FPS samples) and hard-cut timestamps."""
    frame = VW * VH
    cmd = [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-v", "error",
           *ff.untrusted_input_args(src), "-an",
           "-vf", f"fps={VIDEO_FPS},scale={VW}:{VH}:flags=area,format=gray",
           "-f", "rawvideo", "pipe:1"]
    diffs: list[float] = []
    prev: Optional[np.ndarray] = None
    buf = b""
    expected = max(1, int(duration * VIDEO_FPS))
    for data in _stream(cmd, frame * 64, cancel):
        buf += data
        n = len(buf) // frame
        if not n:
            continue
        frames = np.frombuffer(buf[: n * frame], dtype=np.uint8).reshape(n, frame).astype(np.int16)
        buf = buf[n * frame:]
        if prev is not None:
            frames = np.vstack([prev[None, :], frames])
            d = np.abs(np.diff(frames, axis=0)).mean(axis=1)
        else:
            d = np.concatenate([[0.0], np.abs(np.diff(frames, axis=0)).mean(axis=1)])
        prev = frames[-1]
        diffs.extend(d.round(3).tolist())
        on_progress(min(1.0, len(diffs) / expected))
    arr = np.array(diffs, dtype=np.float32)
    cuts: list[float] = []
    if len(arr) > 2:
        # a cut is a spike far above the local motion level
        thr = max(25.0, float(np.median(arr) + 6 * (np.percentile(arr, 75) - np.median(arr) + 1)))
        for i in np.nonzero(arr > thr)[0]:
            t = round(float(i) / VIDEO_FPS, 3)
            if not cuts or t - cuts[-1] > 0.5:
                cuts.append(t)
    # resample motion to the HOP grid
    n_hop = max(1, int(round(duration / HOP)))
    if len(arr):
        src_t = np.arange(len(arr)) / VIDEO_FPS
        motion = np.interp(np.arange(n_hop) * HOP, src_t, arr).round(3).tolist()
    else:
        motion = [0.0] * n_hop
    return motion, cuts


def analysis_path(project_dir: Path, media_id: str) -> Path:
    d = project_dir / "analysis"
    d.mkdir(exist_ok=True)
    return d / f"{media_id}.json"


def load_analysis(project_dir: Path, media_id: str) -> Optional[dict]:
    p = analysis_path(project_dir, media_id)
    if not p.exists():
        return None
    data = json.loads(p.read_bytes())
    return data if data.get("version") == ANALYSIS_VERSION else None


def analyze_media(ctx, settings: Settings, project_dir: Path, asset: MediaAsset,
                  transcriber=None) -> dict:
    src = project_dir / "media" / "original" / asset.stored_name
    steps = [s for s, on in (("audio", asset.has_audio), ("video", asset.has_video),
                             ("transcript", bool(asset.has_audio and transcriber))) if on]
    weights = {"audio": 0.4, "video": 0.6, "transcript": 2.0}
    total = sum(weights[s] for s in steps) or 1
    done = 0.0
    result: dict = {"version": ANALYSIS_VERSION, "media_id": asset.id, "duration": asset.duration,
                    "hop": HOP, "rms_db": [], "motion": [], "cuts": [], "words": None,
                    "transcriber": None}
    for i, step in enumerate(steps, 1):
        w = weights[step]
        prog = lambda f, d=done, w=w: ctx.progress((d + f * w) / total)  # noqa: E731
        if step == "audio":
            ctx.stage(i, len(steps), "Analysing audio loudness and pauses")
            result["rms_db"] = audio_loudness(settings, src, asset.duration, prog, ctx.cancel_event)
        elif step == "video":
            ctx.stage(i, len(steps), "Detecting motion and scene cuts")
            result["motion"], result["cuts"] = video_motion(settings, src, asset.duration, prog,
                                                           ctx.cancel_event)
        else:
            # optional: if speech-to-text fails (e.g. the one-time model download), keep the
            # sound/picture analysis — the Auto Editor works without words
            try:
                _prepare(ctx, transcriber, i, len(steps))
                ctx.stage(i, len(steps), f"Transcribing speech ({transcriber.name})")
                result["words"] = transcriber.transcribe(src, prog, ctx.cancel_event)
                result["transcriber"] = transcriber.name
            except ff.Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                if ctx.cancel_event.is_set():
                    raise
                result["words"] = None
                result["transcript_error"] = str(exc)[:500]
        done += w
        ctx.check_cancel()
    out = analysis_path(project_dir, asset.id)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result), encoding="utf-8")
    replace_retry(tmp, out)
    return {"media_id": asset.id, "values": len(result["rms_db"]), "cuts": len(result["cuts"]),
            "words": len(result["words"]) if result["words"] is not None else None,
            **({"warning": "Speech transcription failed, so this analysis uses sound and picture only: "
                           + result["transcript_error"]} if result.get("transcript_error") else {})}


def _prepare(ctx, transcriber, i: int, n: int) -> None:
    """Load the speech model first, under its own label: the first run downloads it and
    would otherwise look stuck at 0%."""
    prep = getattr(transcriber, "prepare", None)
    if prep is not None:
        ctx.stage(i, n, "Loading speech model (the first time this downloads it, ~480 MB — can take a few minutes)")
        prep()


def transcribe_media(ctx, settings: Settings, project_dir: Path, asset: MediaAsset, transcriber) -> dict:
    """Add word timestamps to a media file's analysis (running the signal analysis
    first if it doesn't exist yet)."""
    existing = load_analysis(project_dir, asset.id)
    if existing is None:
        res = analyze_media(ctx, settings, project_dir, asset, transcriber)
        err = (load_analysis(project_dir, asset.id) or {}).get("transcript_error")
        if err:  # transcription was the point of this job: report it as failed
            raise RuntimeError(err)
        return res
    src = project_dir / "media" / "original" / asset.stored_name
    _prepare(ctx, transcriber, 1, 1)
    ctx.stage(1, 1, f"Transcribing speech ({transcriber.name})")
    existing["words"] = transcriber.transcribe(src, ctx.progress, ctx.cancel_event)
    existing["transcriber"] = transcriber.name
    existing.pop("transcript_error", None)
    out = analysis_path(project_dir, asset.id)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing), encoding="utf-8")
    replace_retry(tmp, out)
    return {"media_id": asset.id, "words": len(existing["words"])}
