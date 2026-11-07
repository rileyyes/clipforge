"""Speech-to-text provider interface.

The Auto Editor works without a transcriber (signal-based mode). When the optional
``faster-whisper`` package is installed, word-level timestamps are added and the
decision engine uses them to snap cuts to word boundaries and score talking density.

    pip install faster-whisper          # MIT, runs on CPU; GPU optional

Status: decoding/chunking is tested with a stand-in model; faster-whisper itself
couldn't be installed in the build environment, so the model call is tested by
users. It is reported as "experimental" in the UI.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Optional, Protocol


class Transcriber(Protocol):
    name: str

    def transcribe(self, src: Path, on_progress: Callable[[float], None],
                   cancel: Optional[threading.Event]) -> list[dict]:
        """Return [{"start": s, "end": s, "text": str, "p": prob}] in source time."""
        ...


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(self, model_size: str = "small"):
        self.model_size = model_size
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # type: ignore
            device = os.environ.get("RJCLIP_WHISPER_DEVICE", "cpu")
            try:
                self._model = WhisperModel(self.model_size, device=device,
                                           compute_type="int8" if device == "cpu" else "float16")
            except Exception as exc:  # noqa: BLE001 - turn library errors into something actionable
                msg = str(exc)
                if any(k in msg.lower() for k in ("connection", "resolve", "timed out", "huggingface", "offline", "ssl")):
                    raise RuntimeError("Couldn't download the speech model (one-time, ~480 MB). Check your internet "
                                       f"connection and try again. Details: {msg}") from exc
                raise RuntimeError(f"The speech model failed to load on {device}: {msg}") from exc
        return self._model

    def prepare(self) -> None:
        self._load()

    def transcribe(self, src, on_progress, cancel):
        """Audio is decoded by RJClip's own FFmpeg and handed to Whisper as samples,
        in chunks (bounded memory for long recordings). faster-whisper's built-in decoder
        (PyAV) is not used: PyAV 19 removed an argument faster-whisper 1.2.x still passes,
        which broke every transcription with "unexpected keyword argument 'metadata_errors'"."""
        from . import ffmpeg as ff
        model = self._load()
        words: list[dict] = []
        total = max(media_duration(src), 1e-6)
        for offset, audio in decode_chunks(src, CHUNK_S, cancel):
            # Whisper tends to leave out "um"/"uh"; a prompt written with them nudges it to keep
            # them, so filler-word removal has something to find (results vary by voice)
            segments, _info = model.transcribe(audio, word_timestamps=True, vad_filter=True,
                                               initial_prompt=FILLER_PROMPT)
            for seg in segments:
                if cancel is not None and cancel.is_set():
                    raise ff.Cancelled("cancelled")
                for w in seg.words or []:
                    words.append({"start": round(offset + float(w.start), 3), "end": round(offset + float(w.end), 3),
                                  "text": str(w.word).strip(), "p": round(float(w.probability), 3)})
                on_progress(min(1.0, (offset + float(seg.end)) / total))
            on_progress(min(1.0, (offset + len(audio) / SAMPLE_RATE) / total))
        return words


SAMPLE_RATE = 16000  # what Whisper expects
CHUNK_S = 20 * 60    # 20 min ≈ 77 MB of float32 samples per chunk
FILLER_PROMPT = "Umm, so, uh, let me think. Hmm, okay, um, like this."


def _ffmpeg_bins() -> tuple[str, str]:
    from .config import find_tool
    return (os.environ.get("RJCLIP_FFMPEG") or find_tool("ffmpeg"),
            os.environ.get("RJCLIP_FFPROBE") or find_tool("ffprobe"))


def media_duration(src: Path) -> float:
    import subprocess
    _ff, probe = _ffmpeg_bins()
    try:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def decode_chunks(src: Path, chunk_s: float, cancel: Optional[threading.Event]):
    """Yield (offset seconds, mono 16 kHz float32 samples) chunk by chunk, streaming
    from one FFmpeg process (never the whole recording in memory)."""
    import subprocess

    import numpy as np

    from . import ffmpeg as ff
    ffmpeg, _probe = _ffmpeg_bins()
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", *ff.untrusted_input_args(Path(src)),
           "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    need = int(chunk_s * SAMPLE_RATE) * 4
    offset = 0.0
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise ff.Cancelled("cancelled")
            buf = bytearray()
            while len(buf) < need:
                part = proc.stdout.read(min(1 << 20, need - len(buf)))
                if not part:
                    break
                buf += part
            usable = len(buf) - len(buf) % 4
            if usable >= 4 * SAMPLE_RATE // 10:  # ignore a trailing sliver < 0.1 s
                audio = np.frombuffer(bytes(buf[:usable]), dtype=np.float32)
                yield offset, audio
                offset += len(audio) / SAMPLE_RATE
            if len(buf) < need:
                break
        proc.wait(timeout=60)
        if proc.returncode not in (0, None) and offset == 0:
            err = proc.stderr.read().decode(errors="replace")[-400:]
            raise RuntimeError(f"Couldn't read the audio for transcription: {err.strip() or 'ffmpeg failed'}")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.stderr.close()


def available_transcriber() -> Optional[Transcriber]:
    if os.environ.get("RJCLIP_TRANSCRIBER", "auto") == "off":
        return None
    try:
        import faster_whisper  # type: ignore  # noqa: F401
    except ImportError:
        return None
    return FasterWhisperTranscriber(os.environ.get("RJCLIP_WHISPER_MODEL", "small"))
