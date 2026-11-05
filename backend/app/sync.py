"""Line up two recordings of the same moment by their sound (e.g. a face cam and the game).

Both mics hear the same voice, so the loudness changes line up. We compare the
loudness curves (100 per second) of both recordings with an FFT cross-correlation,
which finds the best shift anywhere in the overlap; then refine to the sample with a
whitened (GCC-PHAT) correlation of the sound itself near that shift, which ignores
differences in mic tone and volume. Confidence compares the best
match with the best match somewhere else: a clear single peak means a real sync.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import ffmpeg as ff

RATE = 8000        # decode rate (Hz)
ENV_HZ = 100       # coarse onset curve rate
MAX_SECONDS = 20 * 60  # compare at most the first 20 minutes of each


@dataclass
class SyncResult:
    offset: float      # cam time = main time + offset
    confidence: float  # 0..1 (≥ 0.5: trustworthy)
    peak_ratio: float


def decode(ffmpeg_bin: str, src: Path, seconds: float = MAX_SECONDS) -> np.ndarray:
    raw = subprocess.run([ffmpeg_bin, "-v", "error", *ff.untrusted_input_args(src, duration=seconds),
                          "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                         capture_output=True, timeout=1800).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def _envelope(x: np.ndarray, hz: int) -> np.ndarray:
    hop = RATE // hz
    n = len(x) // hop
    if n < 2:
        return np.zeros(1)
    e = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-10)
    return np.log(e)


def _norm_env(x: np.ndarray, hz: int) -> np.ndarray:
    e = np.exp(_envelope(x, hz))
    return (e - e.mean()) / (e.std() + 1e-12)


def _xcorr(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """c[k] = sum a[i] b[i+k] for lags k = -(len(a)-1) .. len(b)-1 (index k + len(a) - 1)."""
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.conj(np.fft.rfft(a, n)) * np.fft.rfft(b, n), n)
    return np.concatenate([c[n - len(a) + 1:], c[: len(b)]])


def _gcc_phat(a: np.ndarray, b: np.ndarray, lo: int, hi: int) -> int:
    """Best lag (samples) in [lo, hi] with b[i+lag] ~ a[i]; whitened, so EQ/volume differences don't matter."""
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    X = np.conj(np.fft.rfft(a, n)) * np.fft.rfft(b, n)
    c = np.fft.irfft(X / (np.abs(X) + 1e-12), n)
    lags = np.arange(lo, hi + 1)
    return int(lags[np.argmax(c[lags % n])])


def find_offset(main: np.ndarray, cam: np.ndarray) -> SyncResult:
    """offset such that cam(t + offset) matches main(t)."""
    if len(main) < RATE or len(cam) < RATE or main.std() < 1e-6 or cam.std() < 1e-6:
        return SyncResult(0.0, 0.0, 0.0)
    a, b = _norm_env(main, ENV_HZ), _norm_env(cam, ENV_HZ)
    c = _xcorr(a, b)
    lags = np.arange(-(len(a) - 1), len(b))
    ov = np.minimum(len(b) - np.maximum(lags, 0), len(a) - np.maximum(-lags, 0))
    need = min(len(a), len(b), 10 * ENV_HZ) * 0.5   # at least half the shorter one (max 5 s) must overlap
    valid = ov >= need
    score = np.where(valid, c / np.maximum(ov, 1), -np.inf)
    k = int(np.argmax(score))
    best = float(score[k])
    away = valid & (np.abs(lags - lags[k]) > ENV_HZ // 2)
    second = float(np.max(score[away])) if np.any(away) else 0.0
    ratio = best / second if second > 1e-9 else (99.0 if best > 0 else 0.0)
    coarse = int(lags[k]) * (RATE // ENV_HZ)
    # refine to the sample on (at most) 60 s of overlapping raw audio
    i0 = max(0, -coarse)
    n = min(len(main) - i0, len(cam) - (i0 + coarse), 60 * RATE)
    win = RATE // ENV_HZ * 3
    if n > RATE:
        seg_a = main[i0:i0 + n]
        seg_b = cam[i0 + coarse - win if i0 + coarse - win >= 0 else 0:]
        shift0 = (i0 + coarse - win) if i0 + coarse - win >= 0 else 0
        seg_b = seg_b[:n + 2 * win]
        lag = _gcc_phat(seg_a, seg_b, (i0 + coarse) - shift0 - win, (i0 + coarse) - shift0 + win)
        fine = lag + shift0 - i0
    else:
        fine = coarse
    conf = float(np.clip((min(ratio, 4.0) - 1.2) / 0.8, 0, 1)) if best > 0 else 0.0
    return SyncResult(round(fine / RATE, 4), round(conf, 3), round(min(ratio, 99.0), 3))


def sync_files(ffmpeg_bin: str, main: Path, cam: Path) -> SyncResult:
    return find_offset(decode(ffmpeg_bin, main), decode(ffmpeg_bin, cam))


# ---------------------------------------------------------------- crop to the face
def face_crop(ffmpeg_bin: str, src: Path, duration: float, width: int, height: int,
              aspect: float = 1.0, samples: int = 12):
    """A crop (fractions) around the face, head and shoulders, with the given aspect
    (w/h in pixels). None if no face is seen in most sampled frames."""
    from .schema import Crop
    from .shorts import _detector
    import cv2
    det = _detector()
    if det is None:
        return None
    sw = 480
    sh = max(2, int(round(height * sw / width / 2)) * 2)
    boxes = []
    for i in range(samples):
        t = duration * (i + 0.5) / samples
        raw = subprocess.run([ffmpeg_bin, "-v", "error", *ff.untrusted_input_args(src, seek=t), "-frames:v", "1",
                              "-vf", f"scale={sw}:{sh}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, timeout=120).stdout
        if len(raw) != sw * sh:
            continue
        faces = det(np.frombuffer(raw, np.uint8).reshape(sh, sw))
        if faces:
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            boxes.append((x / sw, y / sh, w / sw, h / sh))
    if len(boxes) < max(2, samples // 3):
        return None
    fx, fy, fw, fh = (float(np.median([b[i] for b in boxes])) for i in range(4))
    cx, cy = fx + fw / 2, fy + fh * 0.62           # a bit below the face centre: shoulders in
    ch = min(1.0, fh * 2.8)                        # head and shoulders
    cw = ch * height * aspect / width
    if cw > 1.0:
        cw, ch = 1.0, width / (height * aspect)
    k = max(1.0, 0.15 / cw, 0.15 / ch)             # a crop must keep ≥ 10% of the picture
    cw, ch = min(1.0, cw * k), min(1.0, ch * k)
    left = float(np.clip(cx - cw / 2, 0, 1 - cw))
    top = float(np.clip(cy - ch / 2, 0, 1 - ch))
    r = lambda v: round(max(0.0, v), 4)  # noqa: E731
    crop = Crop(left=r(left), right=r(1 - left - cw), top=r(top), bottom=r(1 - top - ch))
    return crop, {"faces_seen": len(boxes), "samples": samples}
