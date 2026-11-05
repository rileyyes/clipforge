"""Phase 10: beat detection."""
from __future__ import annotations

import subprocess

import numpy as np
import pytest

from app import beats as BT


def song(bpm, seconds=30, offset=0.31, seed=0, swing_noise=0.0):
    """Kick + hat pattern with bass and noise (like a simple track)."""
    rng = np.random.default_rng(seed)
    sr = BT.SR
    x = rng.normal(0, 0.02, int(seconds * sr))
    t = np.arange(len(x)) / sr
    x += 0.15 * np.sin(2 * np.pi * 55 * t)
    period = 60 / bpm
    beats = np.arange(offset, seconds - 0.2, period)
    for i, b in enumerate(beats):
        b += rng.normal(0, swing_noise)
        k = int(b * sr)
        n = int(0.12 * sr)
        env = np.exp(-np.arange(n) / (0.03 * sr))
        kick = np.sin(2 * np.pi * (120 - 60 * np.arange(n) / n) * np.arange(n) / sr) * env
        x[k:k + n] += (1.0 if i % 2 == 0 else 0.7) * kick[: len(x[k:k + n])]
        h = int((b + period / 2) * sr)
        hn = int(0.03 * sr)
        x[h:h + hn] += rng.normal(0, 0.25, len(x[h:h + hn])) * np.exp(-np.arange(len(x[h:h + hn])) / (0.008 * sr))
    return x, beats


@pytest.mark.parametrize("bpm", [90, 120, 128, 150])
def test_finds_tempo_and_beats(bpm):
    x, truth = song(bpm)
    r = BT.detect(x)
    assert abs(r["bpm"] - bpm) < 1.5, r["bpm"]
    got = np.array(r["beats"])
    # every true beat (after the first 2 s) has a detected beat within about a frame (30 fps)
    errs = [np.abs(got - b).min() for b in truth if 2 < b < 28]
    assert np.median(errs) < 0.03 and np.percentile(errs, 90) < 0.04, (np.median(errs), np.percentile(errs, 90))
    assert len(got) <= len(truth) + 2


def test_silence_and_short():
    assert BT.detect(np.zeros(1000)) == {"bpm": 0.0, "beats": []}
    r = BT.detect(np.random.default_rng(0).normal(0, 0.01, BT.SR * 10))  # just hiss: no steady beat claimed
    assert isinstance(r["beats"], list)


def test_api_beats(server, tmp_path):
    from test_api import new_project
    x, _ = song(124, 20)
    raw = tmp_path / "s.f32"
    (x / np.abs(x).max() * 0.8).astype(np.float32).tofile(raw)
    mp3 = tmp_path / "song.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(BT.SR), "-ac", "1", "-i", str(raw),
                    "-c:a", "aac", "-b:a", "160k", str(mp3)], check=True)
    p = new_project(server)
    _, r, _ = server.upload(p["id"], mp3)
    mid = r["media"]["id"]
    st, res, _ = server.req("POST", f"/api/projects/{p['id']}/beats", {"media_id": mid})
    assert st == 200, res
    assert abs(res["bpm"] - 124) < 1.5 and len(res["beats"]) > 30
    st2, res2, _ = server.req("POST", f"/api/projects/{p['id']}/beats", {"media_id": mid})
    assert res2 == res  # cached
