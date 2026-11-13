"""Phase 18: who's talking (for name tags) and the funny-moment finder.

Both work from each recording's loudness (20 values a second), computed once and cached in
<project>/analysis/<media>.rms.json (or taken from the Auto Editor's analysis if it ran).

* Talking: louder than that recording's own quiet level by a margin, with short pauses
  bridged and tiny blips dropped. It's a loudness gate, not speech recognition: on a mic
  that also picks up game sound, the game counts as talking.
* Funny moments: stretches where people get much louder than their usual talking level —
  laughing, yelling, screaming. Several mics getting loud together score higher. It can't
  tell a laugh from a shout; it finds the loud reactions and you pick the funny ones.
  Each moment starts a few seconds earlier, because the joke comes before the reaction.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from .analysis import HOP, audio_loudness, load_analysis
from .config import Settings
from .schema import MediaAsset, Project
from .storage import replace_retry

RMS_VERSION = 1


def loudness(settings: Settings, project_dir: Path, asset: MediaAsset) -> np.ndarray:
    """dBFS every HOP seconds for the whole file (cached)."""
    a = load_analysis(project_dir, asset.id)
    if a and a.get("rms_db"):
        return np.asarray(a["rms_db"], dtype=np.float64)
    p = project_dir / "analysis" / f"{asset.id}.rms.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("version") == RMS_VERSION:
                return np.asarray(d["rms_db"], dtype=np.float64)
        except (OSError, ValueError):
            pass
    src = project_dir / "media" / "original" / asset.stored_name
    db = audio_loudness(settings, src, asset.duration)
    p.parent.mkdir(exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": RMS_VERSION, "hop": HOP, "rms_db": db}), encoding="utf-8")
    replace_retry(tmp, p)
    return np.asarray(db, dtype=np.float64)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index runs where mask is true."""
    if not len(mask):
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def talk_intervals(db: np.ndarray, bridge: float = 0.35, min_len: float = 0.15) -> list[list[float]]:
    """Source-time [start, end] stretches where this recording is talking."""
    if len(db) == 0:
        return []
    if not (db > -80).any():
        return []
    floor = float(np.percentile(db, 15))     # pauses (or digital silence) between words
    loud = float(np.percentile(db, 95))
    thr = max(-50.0, floor + max(8.0, (loud - floor) * 0.3))
    on = db > thr
    runs = _runs(on)
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and (a - merged[-1][1]) * HOP <= bridge:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [[round(a * HOP, 3), round(b * HOP, 3)] for a, b in merged if (b - a) * HOP >= min_len]


def _speech_level(db: np.ndarray) -> Optional[float]:
    """Typical talking loudness of a recording: the median of its talking parts."""
    iv = talk_intervals(db)
    if not iv:
        return None
    idx = np.concatenate([np.arange(int(a / HOP), int(b / HOP)) for a, b in iv])
    idx = idx[idx < len(db)]
    return float(np.median(db[idx])) if len(idx) else None


def funny_moments(project: Project, settings: Settings, project_dir: Path, *, lead: float = 4.0,
                  tail: float = 1.5, max_moments: int = 30, min_gap: float = 2.0) -> list[dict]:
    """Loud-reaction moments in the edit (timeline seconds), best first then by time."""
    media = project.media_by_id()
    D = project.timeline.duration
    n = int(np.ceil(D / HOP)) + 1
    if n <= 1:
        return []
    score = np.zeros(n)
    heard = np.zeros(n)
    for tr in project.timeline.tracks:
        if tr.kind != "audio" or tr.muted or tr.role == "music":
            continue
        for c in tr.clips:
            asset = media.get(c.media_id)
            if not asset or not asset.has_audio:
                continue
            db = loudness(settings, project_dir, asset)
            lvl = _speech_level(db)
            if lvl is None:
                continue
            excess = np.clip(db - lvl - 6.0, 0, 24)       # dB above this person's usual talking
            i0, i1 = int(c.source_in / HOP), int(c.source_out / HOP)
            seg = excess[i0:i1]
            if c.speed != 1:
                seg = seg[(np.arange(int(len(seg) / c.speed)) * c.speed).astype(int)]
            t0 = int(round(c.start / HOP))
            m = min(len(seg), n - t0)
            if m > 0:
                score[t0:t0 + m] += seg[:m]
                heard[t0:t0 + m] += (seg[:m] > 0)
    if not score.any():
        return []
    win = max(1, int(0.75 / HOP))
    smooth = np.convolve(score, np.ones(win) / win, mode="same")
    together = np.convolve(heard, np.ones(win) / win, mode="same")
    hot = smooth > 2.0
    moments = []
    for a, b in _runs(hot):
        if (b - a) * HOP < 0.4:
            continue
        peak = float(smooth[a:b].max())
        strength = peak * (b - a) * HOP * (1 + 0.5 * max(0.0, float(together[a:b].max()) - 1))
        moments.append({"react_start": a * HOP, "react_end": b * HOP, "strength": strength,
                        "people": int(round(float(together[a:b].max())))})
    # join reactions that are close, then turn each into a clip with the build-up before it
    moments.sort(key=lambda m: m["react_start"])
    joined: list[dict] = []
    for m in moments:
        if joined and m["react_start"] - joined[-1]["react_end"] < min_gap:
            j = joined[-1]
            j["react_end"] = max(j["react_end"], m["react_end"])
            j["strength"] += m["strength"]
            j["people"] = max(j["people"], m["people"])
        else:
            joined.append(dict(m))
    if not joined:
        return []
    top = max(m["strength"] for m in joined)
    best = sorted(joined, key=lambda m: -m["strength"])[:max_moments]
    out = []
    for m in sorted(best, key=lambda m: m["react_start"]):
        start = max(0.0, m["react_start"] - lead)
        end = min(D, m["react_end"] + tail)
        out.append({"start": round(start, 2), "end": round(end, 2), "reaction": round(m["react_start"], 2),
                    "score": int(round(100 * m["strength"] / top)), "people": m["people"]})
    return out


def talk_for_media(settings: Settings, project_dir: Path, asset: MediaAsset) -> list[list[float]]:
    if not asset.has_audio:
        return []
    return talk_intervals(loudness(settings, project_dir, asset))


def track_talk(project: Project, settings: Settings, project_dir: Path, track) -> list[tuple[float, float]]:
    """Timeline stretches where an audio track is talking (its clips' talking, mapped)."""
    media = project.media_by_id()
    out: list[tuple[float, float]] = []
    for c in sorted(track.clips, key=lambda c: c.start):
        asset = media.get(c.media_id)
        if not asset:
            continue
        for a, b in talk_for_media(settings, project_dir, asset):
            a, b = max(a, c.source_in), min(b, c.source_out)
            if b - a > 0.05:
                out.append((c.start + (a - c.source_in) / c.speed, c.start + (b - c.source_in) / c.speed))
    return out
