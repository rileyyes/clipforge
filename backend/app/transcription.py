"""Speech-to-text provider interface.

The Auto Editor works without a transcriber (signal-based mode). When the optional
``faster-whisper`` package is installed, word-level timestamps are added and the
decision engine uses them to snap cuts to word boundaries and score talking density.

    pip install faster-whisper          # MIT, runs on CPU; GPU optional

Status: the FasterWhisper adapter follows the library's documented API but has
NOT been run in this repository's automated tests (the package couldn't be
installed in the build environment). It is reported as "experimental" in the UI.
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
            device = os.environ.get("CLIPFORGE_WHISPER_DEVICE", "cpu")
            try:
                self._model = WhisperModel(self.model_size, device=device,
                                           compute_type="int8" if device == "cpu" else "float16")
            except Exception as exc:  # noqa: BLE001 - turn library errors into something actionable
                msg = str(exc)
                if any(k in msg.lower() for k in ("connection", "resolve", "timed out", "huggingface", "offline", "ssl")):
                    raise RuntimeError("Couldn't download the speech model (one-time, ~460 MB). Check your internet "
                                       f"connection and try again. Details: {msg}") from exc
                raise RuntimeError(f"The speech model failed to load on {device}: {msg}") from exc
        return self._model

    def prepare(self) -> None:
        self._load()

    def transcribe(self, src, on_progress, cancel):
        from . import ffmpeg as ff
        model = self._load()
        segments, info = model.transcribe(str(src), word_timestamps=True, vad_filter=True)
        words: list[dict] = []
        total = max(float(getattr(info, "duration", 0) or 0), 1e-6)
        for seg in segments:
            if cancel is not None and cancel.is_set():
                raise ff.Cancelled("cancelled")
            for w in seg.words or []:
                words.append({"start": round(float(w.start), 3), "end": round(float(w.end), 3),
                              "text": str(w.word).strip(), "p": round(float(w.probability), 3)})
            on_progress(min(1.0, float(seg.end) / total))
        return words


def available_transcriber() -> Optional[Transcriber]:
    if os.environ.get("CLIPFORGE_TRANSCRIBER", "auto") == "off":
        return None
    try:
        import faster_whisper  # type: ignore  # noqa: F401
    except ImportError:
        return None
    return FasterWhisperTranscriber(os.environ.get("CLIPFORGE_WHISPER_MODEL", "small"))
