"""Media ingest and derived assets (thumbnails, waveforms, browser proxies).

Originals are written once, set read-only, and never modified afterwards.
Long media is processed by streaming through FFmpeg — nothing loads a whole
video into memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from . import ffmpeg as ff
from .config import Settings
from .schema import MediaAsset
from .storage import SAFE_INPUT_FORMATS, safe_join

# Codec/container combos every mainstream browser can play directly.

WAVEFORM_PEAKS_PER_SECOND = 100  # detail for zoomed-in timelines (older media: 20)


def media_dir(project_dir: Path, sub: str) -> Path:
    d = safe_join(project_dir, "media", sub) if sub else safe_join(project_dir, "media")
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def build_asset(settings: Settings, asset_id: str, stored: Path, original_name: str) -> MediaAsset:
    info = ff.probe(settings.ffprobe_bin, stored, timeout=settings.ffprobe_timeout_s)
    return MediaAsset(
        id=asset_id,
        original_name=original_name,
        stored_name=stored.name,
        kind="video" if info.has_video else "audio",
        duration=info.duration,
        size_bytes=stored.stat().st_size,
        container=info.container,
        has_video=info.has_video,
        has_audio=info.has_audio,
        width=info.width,
        height=info.height,
        fps=info.fps,
        variable_frame_rate=info.variable_frame_rate,
        video_codec=info.video_codec,
        audio_codec=info.audio_codec,
        sample_rate=info.sample_rate,
        channels=info.channels,
    )


def needs_proxy(asset: MediaAsset) -> bool:
    """True unless every mainstream browser (incl. Safari) can play the file as-is.

    Decided by real file type + codecs; ffprobe reports MKV as "matroska,webm",
    so the container name alone isn't enough.
    """
    ext = Path(asset.stored_name).suffix.lower()
    if asset.has_video:
        if ext in (".mp4", ".m4v", ".mov"):
            return not (asset.video_codec == "h264" and asset.audio_codec in ("aac", "mp3", None))
        if ext == ".webm":
            return not (asset.video_codec in ("vp8", "vp9", "av1")
                        and asset.audio_codec in ("opus", "vorbis", None))
        return True  # mkv, avi, …
    return ext not in (".mp3", ".wav", ".m4a", ".aac", ".flac")


def make_thumbnail(settings: Settings, asset: MediaAsset, src: Path, out: Path) -> None:
    at = min(max(asset.duration * 0.1, 0.0), max(asset.duration - 0.1, 0.0))
    ff.run_ffmpeg(
        settings.ffmpeg_bin,
        ff.untrusted_input_args(src, seek=at)
        + ["-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", str(out)],
        timeout=120,
    )


def make_waveform(settings: Settings, asset: MediaAsset, src: Path, out: Path,
                  cancel: Optional[threading.Event] = None) -> None:
    """Stream decoded mono audio and keep the peak of each 1/100 s bucket."""
    rate = 8000
    bucket = rate // WAVEFORM_PEAKS_PER_SECOND
    cmd = [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-v", "error",
           *ff.untrusted_input_args(src), "-vn", "-ac", "1", "-ar", str(rate),
           "-f", "s16le", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    peaks: list[int] = []
    leftover = b""
    assert proc.stdout is not None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise ff.Cancelled("cancelled")
            data = proc.stdout.read(bucket * 2 * 400)
            if not data:
                break
            data = leftover + data
            usable = len(data) - (len(data) % (bucket * 2))
            leftover = data[usable:]
            if usable:
                samples = np.frombuffer(data[:usable], dtype="<i2").reshape(-1, bucket)
                p = np.abs(samples.astype(np.int32)).max(axis=1)
                peaks.extend((p * 255 // 32768).astype(int).tolist())
    finally:
        proc.wait()
    if proc.returncode not in (0, None):
        raise ff.FFmpegError("waveform extraction failed")
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps({"peaks_per_second": WAVEFORM_PEAKS_PER_SECOND,
                               "peaks": peaks}), encoding="utf-8")
    os.replace(tmp, out)


def make_proxy(settings: Settings, asset: MediaAsset, src: Path, out: Path,
               on_progress=None, cancel: Optional[threading.Event] = None) -> None:
    """Browser-playable preview copy. Never used for final renders."""
    tmp = out.with_name(out.stem + ".partial.mp4")
    args = ff.untrusted_input_args(src)
    if asset.has_video:
        args += ["-map", "0:v:0", "-vf", "scale=-2:'min(540,ih)'",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
                 "-pix_fmt", "yuv420p", "-g", "30"]
    if asset.has_audio:
        args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    args += ["-movflags", "+faststart", str(tmp)]
    ff.run_ffmpeg(settings.ffmpeg_bin, args, expected_duration=asset.duration,
                  on_progress=on_progress, cancel_event=cancel,
                  timeout=settings.render_timeout_s)
    os.replace(tmp, out)


def mark_read_only(path: Path) -> None:
    try:
        os.chmod(path, 0o400)
    except OSError:
        pass


__all__ = [
    "build_asset", "needs_proxy", "make_thumbnail", "make_waveform", "make_proxy",
    "sha256_file", "media_dir", "mark_read_only", "SAFE_INPUT_FORMATS",
]
