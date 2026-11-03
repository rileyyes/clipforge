"""Safe FFmpeg / FFprobe invocation.

* Always argument lists — never a shell, so filenames can't inject commands.
* Untrusted inputs are opened with a protocol whitelist (local files only) and a
  demuxer whitelist, so crafted playlists can't reach other files or the network.
* Every call has a timeout; long jobs can be cancelled and report *measured*
  progress parsed from ``-progress`` output.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional

from .storage import SAFE_INPUT_FORMATS


class FFmpegError(RuntimeError):
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr[-4000:]


MISSING_FFMPEG = ("FFmpeg isn't installed or isn't on your PATH. On Windows run "
                  "`winget install Gyan.FFmpeg`, then close and reopen the terminal and restart ClipForge.")


def tools_available(ffmpeg_bin: str, ffprobe_bin: str) -> bool:
    import shutil
    return bool((shutil.which(ffmpeg_bin) or Path(ffmpeg_bin).is_file())
                and (shutil.which(ffprobe_bin) or Path(ffprobe_bin).is_file()))


class Cancelled(RuntimeError):
    pass


def untrusted_input_args(path: Path, seek: Optional[float] = None,
                         duration: Optional[float] = None) -> list[str]:
    args = ["-protocol_whitelist", "file", "-format_whitelist", SAFE_INPUT_FORMATS]
    if seek is not None and seek > 0:
        args += ["-ss", f"{seek:.6f}"]
    if duration is not None:
        args += ["-t", f"{duration:.6f}"]
    return args + ["-i", str(path)]


def _parse_rate(rate: Optional[str]) -> Optional[float]:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        val = float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return None
    return val if 0 < val < 1000 else None


@dataclass
class ProbeResult:
    container: str
    duration: float
    has_video: bool
    has_audio: bool
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    variable_frame_rate: bool
    video_codec: Optional[str]
    audio_codec: Optional[str]
    sample_rate: Optional[int]
    channels: Optional[int]
    rotation: int


def probe(ffprobe_bin: str, path: Path, timeout: int = 60) -> ProbeResult:
    cmd = [
        ffprobe_bin, "-v", "error",
        "-protocol_whitelist", "file", "-format_whitelist", SAFE_INPUT_FORMATS,
        "-print_format", "json", "-show_format", "-show_streams", str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError("media probe timed out") from exc
    except OSError as exc:  # ffprobe missing / not on PATH
        raise FFmpegError(MISSING_FFMPEG) from exc
    if proc.returncode != 0:
        raise FFmpegError("file is not a readable media file", proc.stderr)
    try:
        info = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError("probe returned invalid data") from exc

    streams = info.get("streams", [])
    fmt = info.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None and a is None:
        raise FFmpegError("file has no audio or video streams")

    durations = [fmt.get("duration")] + [s.get("duration") for s in (v, a) if s]
    duration = 0.0
    for d in durations:
        try:
            duration = max(duration, float(d))
        except (TypeError, ValueError):
            continue
    if duration <= 0:
        raise FFmpegError("could not determine media duration")

    fps = vfr = None
    rotation = 0
    if v is not None:
        r = _parse_rate(v.get("r_frame_rate"))
        avg = _parse_rate(v.get("avg_frame_rate"))
        fps = avg or r
        vfr = bool(r and avg and abs(r - avg) / r > 0.01)
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rotation = int(sd["rotation"])
                except (TypeError, ValueError):
                    pass
    width = int(v["width"]) if v and v.get("width") else None
    height = int(v["height"]) if v and v.get("height") else None
    if rotation in (90, -90, 270, -270) and width and height:
        width, height = height, width  # ffmpeg autorotates on decode
    return ProbeResult(
        container=str(fmt.get("format_name", "")),
        duration=round(duration, 6),
        has_video=v is not None,
        has_audio=a is not None,
        width=width,
        height=height,
        fps=round(fps, 4) if fps else None,
        variable_frame_rate=bool(vfr),
        video_codec=v.get("codec_name") if v else None,
        audio_codec=a.get("codec_name") if a else None,
        sample_rate=int(a["sample_rate"]) if a and a.get("sample_rate") else None,
        channels=int(a["channels"]) if a and a.get("channels") else None,
        rotation=rotation,
    )


ProgressFn = Callable[[float], None]


def run_ffmpeg(
    ffmpeg_bin: str,
    args: list[str],
    *,
    expected_duration: Optional[float] = None,
    on_progress: Optional[ProgressFn] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: Optional[float] = None,
) -> None:
    """Run ffmpeg with measured progress (fraction of expected output time)."""
    cmd = [ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-v", "error",
           "-progress", "pipe:1", "-nostats"] + args
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1)
    except OSError as exc:
        raise FFmpegError(MISSING_FFMPEG) from exc
    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_chunks.append(line)
            if len(stderr_chunks) > 400:
                del stderr_chunks[:200]

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()
    started = time.monotonic()
    killed_reason: Optional[str] = None
    assert proc.stdout is not None

    def _watchdog() -> None:
        nonlocal killed_reason
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                killed_reason = "cancelled"
            elif timeout and time.monotonic() - started > timeout:
                killed_reason = "timeout"
            if killed_reason:
                proc.kill()
                return
            time.sleep(0.2)

    w = threading.Thread(target=_watchdog, daemon=True)
    w.start()
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and on_progress and expected_duration:
            try:
                secs = int(value) / 1_000_000
            except ValueError:
                continue
            if secs >= 0:
                on_progress(min(1.0, secs / expected_duration))
    proc.wait()
    t.join(timeout=2)
    if killed_reason == "cancelled":
        raise Cancelled("cancelled by user")
    if killed_reason == "timeout":
        raise FFmpegError("processing timed out")
    if proc.returncode != 0:
        err = "".join(stderr_chunks)
        raise FFmpegError(f"ffmpeg failed (exit {proc.returncode})", err)
    if on_progress:
        on_progress(1.0)


def ffmpeg_version(ffmpeg_bin: str) -> str:
    try:
        out = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True,
                             timeout=10).stdout
        return out.splitlines()[0] if out else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "not found"


_encoder_cache: dict[str, str] = {}


def pick_h264_encoder(ffmpeg_bin: str, preference: str = "auto") -> str:
    """Return a *working* H.264 encoder. Hardware encoders are only chosen after a
    real one-frame test encode succeeds; otherwise fall back to libx264."""
    if preference != "auto":
        return preference
    if "auto" in _encoder_cache:
        return _encoder_cache["auto"]
    chosen = "libx264"
    for enc in ("h264_nvenc", "h264_qsv", "h264_videotoolbox"):
        try:
            r = subprocess.run(
                [ffmpeg_bin, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=256x144:d=0.1", "-frames:v", "1", "-c:v", enc,
                 "-f", "null", "-"],
                capture_output=True, timeout=15,
            )
            if r.returncode == 0:
                chosen = enc
                break
        except (OSError, subprocess.TimeoutExpired):
            continue
    _encoder_cache["auto"] = chosen
    return chosen
