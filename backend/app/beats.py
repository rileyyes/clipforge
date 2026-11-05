"""Beat detection for your music (no extra packages).

1. onset strength: how much the spectrum gets louder from one moment to the next
   (spectral flux, ~43 values a second), with the low end (kick, bass) weighted up so
   the beat lands on the kick rather than the hi-hat between kicks
2. tempo: the strongest repeat in that curve between 60 and 180 BPM (autocorrelation,
   gently preferring ~120 BPM so a half/double tempo doesn't win by chance)
3. beats: dynamic programming that picks onset peaks spaced about one beat apart
   (Ellis 2007, the method librosa's beat tracker is based on)
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from . import ffmpeg as ff

SR = 11025
HOP = 256
FPS = SR / HOP  # ~43 onset values a second


def decode(ffmpeg_bin: str, src: Path, max_s: float = 15 * 60) -> np.ndarray:
    raw = subprocess.run([ffmpeg_bin, "-v", "error", *ff.untrusted_input_args(src, duration=max_s), "-vn",
                          "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, timeout=900).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


WIN = 1024


def onset_envelope(x: np.ndarray) -> np.ndarray:
    n = WIN
    if len(x) < n * 4:
        return np.zeros(0)
    frames = 1 + (len(x) - n) // HOP
    idx = np.arange(n)[None, :] + HOP * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(n), axis=1))
    logs = np.log1p(1000 * spec)
    d = np.maximum(0, np.diff(logs, axis=0))
    low = int(200 / (SR / n)) + 1          # kick drum and bass (< 200 Hz) carry the beat:
    flux = d.sum(axis=1) / d.shape[1] + 3 * d[:, :low].sum(axis=1) / low  # weigh them more than hats
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # remove slow loudness changes
    flux = np.maximum(flux, 0)
    return flux / (flux.std() + 1e-9)


def tempo(env: np.ndarray, lo: float = 60, hi: float = 180) -> float:
    if len(env) < FPS * 4:
        return 0.0
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lags = np.arange(int(FPS * 60 / hi), int(FPS * 60 / lo) + 1)
    bpm = 60 * FPS / lags
    prior = np.exp(-0.5 * (np.log2(bpm / 120) / 0.9) ** 2)
    score = ac[lags] * prior
    best = int(np.argmax(score))
    # refine with the parabola through the peak
    if 0 < best < len(lags) - 1:
        a, b, c = score[best - 1:best + 2]
        d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0
        return float(60 * FPS / (lags[best] + d))
    return float(bpm[best])


def track(env: np.ndarray, bpm: float, tightness: float = 100) -> np.ndarray:
    """Beat times (seconds)."""
    if bpm <= 0 or not len(env):
        return np.zeros(0)
    period = FPS * 60 / bpm
    n = len(env)
    score = env.copy()
    back = np.full(n, -1)
    lo, hi = int(round(period / 2)), int(round(period * 2))
    window = np.arange(-hi, -lo + 1)
    penalty = -tightness * np.log(-window / period) ** 2
    for t in range(n):
        prev = t + window
        ok = prev >= 0
        if not ok.any():
            continue
        cand = score[prev[ok]] + penalty[ok]
        k = int(np.argmax(cand))
        if cand[k] > 0:
            score[t] = env[t] + cand[k]
            back[t] = prev[ok][k]
    # end on the best-scoring beat in the last period
    t = int(np.argmax(score[max(0, n - int(period) - 1):])) + max(0, n - int(period) - 1)
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    return np.array(beats[::-1]) / FPS


def detect(x: np.ndarray) -> dict:
    env = onset_envelope(x)
    bpm = tempo(env)
    # onset frame i covers samples [i*HOP, i*HOP+WIN): its time is the window's centre
    beats = track(env, bpm) + WIN / 2 / SR
    return {"bpm": round(bpm, 1), "beats": [round(float(b), 3) for b in beats if b >= 0]}
