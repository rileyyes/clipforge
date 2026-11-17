"""Phase 21: automatic multicam (several cameras filming the same moment).

1. **Line up** every camera (and every separate mic) with the main recording by sound,
   the same way the face cam is lined up (sync.py).
2. **Choose a camera for every moment** of the main recording:

   * ``speaker``: each camera belongs to a person, and that person's mic (the camera's
     own sound, or a separate mic file) tells when they talk. At each moment the person
     who is talking the most *for their own mic* wins (each mic is compared with its own
     normal talking level, so a loud mic doesn't always win and the other person's voice
     leaking into a mic doesn't count). A new person has to talk for a moment before the
     camera follows (no flicker on "yeah" / "mm"), every shot lasts at least ``min_shot``,
     and the cut is placed where they started talking. When several people talk at once
     for a while, or nobody talks for a long time, it goes to the wide camera (if one is
     picked).
   * ``pace``: one person, several cameras (or a game + face): switch camera about every
     ``pace`` seconds, at the quietest moment nearby (between sentences), going round the
     cameras so the same one doesn't come back straight away.

The result is a list of switches in the main recording's own time; the Editor applies it to
the edit on the bottom video track (frontend/src/timeline/phase21.ts, applyMulticam), so
any cuts already made stay as they are. It's a loudness gate, not face or speech
recognition: background sound on a mic counts as talking.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np

from .analysis import HOP
from .reactions import _runs

MAX_ANGLES = 4                 # cameras, the main one included
GAP = -1                       # nobody talking
BOTH = -2                      # several people at once


@dataclass
class Switch:
    t: float                   # main recording time (s)
    angle: int                 # index into the cameras (0 = the main recording)


def talk_mask(db: np.ndarray) -> tuple[np.ndarray, float]:
    """Frames where this mic is talking, and its normal talking level (dB)."""
    if len(db) == 0 or not (db > -80).any():
        return np.zeros(len(db), bool), -120.0
    floor = float(np.percentile(db, 15))
    loud = float(np.percentile(db, 95))
    thr = max(-50.0, floor + max(8.0, (loud - floor) * 0.3))
    on = db > thr
    # bridge short gaps between words (0.35 s) and drop blips (< 0.15 s)
    for a, b in _runs(~on):
        if 0 < a and b < len(on) and (b - a) * HOP <= 0.35:
            on[a:b] = True
    for a, b in _runs(on):
        if (b - a) * HOP < 0.15:
            on[a:b] = False
    level = float(np.median(db[on])) if on.any() else -120.0
    return on, level


def align(db: np.ndarray, offset: float, n: int) -> np.ndarray:
    """A mic's loudness on the main recording's clock (mic time = main time + offset);
    -120 dB where the mic wasn't recording."""
    idx = np.round(np.arange(n) + offset / HOP).astype(int)
    out = np.full(n, -120.0)
    ok = (idx >= 0) & (idx < len(db))
    out[ok] = db[idx[ok]]
    return out


def raw_speaker(dbs: Sequence[np.ndarray], margin: float = 3.0) -> np.ndarray:
    """Who is talking at each frame: a mic index, GAP or BOTH (all mics on the main clock)."""
    n = min(len(d) for d in dbs) if dbs else 0
    rel = np.full((len(dbs), n), -np.inf)
    for i, d in enumerate(dbs):
        on, level = talk_mask(d[:n])
        rel[i, on] = d[:n][on] - level
    out = np.full(n, GAP, dtype=int)
    if n == 0:
        return out
    order = np.argsort(-rel, axis=0)
    best = order[0]
    top = rel[best, np.arange(n)]
    talking = np.isfinite(top)
    out[talking] = best[talking]
    if len(dbs) > 1:
        second = rel[order[1], np.arange(n)]
        with np.errstate(invalid="ignore"):
            both = talking & np.isfinite(second) & (top - second < margin) & (second > -6)
        out[both] = BOTH
    return out


def smooth(raw: np.ndarray, window: float = 0.5) -> np.ndarray:
    """Majority vote over a short window, so a frame or two of noise doesn't break up a run."""
    n = len(raw)
    if n == 0:
        return raw
    half = max(1, round(window / HOP / 2))
    labels = np.unique(raw)
    k = np.ones(2 * half + 1)
    counts = np.stack([np.convolve((raw == lb).astype(float), k, mode="same") for lb in labels])
    # ties keep the frame's own label
    own = np.searchsorted(labels, raw)
    best = counts.argmax(axis=0)
    tie = counts[best, np.arange(n)] == counts[own, np.arange(n)]
    return np.where(tie, raw, labels[best])


def speaker_switches(raw: np.ndarray, angle_of: Sequence[int], *, wide: Optional[int] = None,
                     min_shot: float = 2.0, hold: float = 0.6, both_after: float = 1.5,
                     quiet_after: float = 4.0) -> list[Switch]:
    """Turn the frame-by-frame speaker into camera shots (see the module docstring).

    ``angle_of[i]`` is the camera of mic i."""
    n = len(raw)
    if n == 0:
        return [Switch(0.0, 0)]
    need_hold, need_shot = max(1, round(hold / HOP)), max(1, round(min_shot / HOP))
    need_both, need_quiet = max(1, round(both_after / HOP)), max(1, round(quiet_after / HOP))

    def cam(label: int) -> Optional[int]:
        if label >= 0:
            return angle_of[label]
        return wide

    first = next((angle_of[x] for x in raw if x >= 0), 0)
    shots: list[list[int]] = [[0, first]]          # [start frame, camera]
    run_label, run_start = int(raw[0]), 0
    for f in range(1, n + 1):
        label = int(raw[f]) if f < n else None
        if label == run_label:
            continue
        # a run of run_label ended at f; decide whether it earns a shot
        length = f - run_start
        target = None
        if run_label >= 0 and length >= need_hold:
            target = cam(run_label)
        elif run_label == BOTH and length >= need_both:
            target = cam(BOTH)
        elif run_label == GAP and length >= need_quiet:
            target = cam(GAP)
        if target is not None and target != shots[-1][1]:
            at = max(run_start, shots[-1][0] + need_shot)
            if at < f:                              # the run is still going after the minimum shot
                shots.append([at, target])
        if label is not None:
            run_label, run_start = label, f
    # a last shot shorter than the minimum goes back to the one before
    if len(shots) > 1 and n - shots[-1][0] < need_shot:
        shots.pop()
    out: list[Switch] = []
    for start, c in shots:
        if not out or out[-1].angle != c:
            out.append(Switch(round(start * HOP, 3), int(c)))
    out[0] = Switch(0.0, out[0].angle)
    return out


def pace_switches(db: np.ndarray, n_angles: int, pace: float = 5.0, search: float = 1.5) -> list[Switch]:
    """Switch about every ``pace`` seconds at the quietest nearby moment, going round the cameras.
    Deterministic: the gaps vary between 0.75× and 1.25× the pace in a fixed pattern."""
    n = len(db)
    if n == 0 or n_angles < 2:
        return [Switch(0.0, 0)]
    pattern = (1.0, 1.25, 0.8, 1.1, 0.75, 1.2, 0.9)
    out = [Switch(0.0, 0)]
    order = list(range(n_angles))
    t, k, w = 0.0, 0, max(1, round(search / HOP))
    dur = n * HOP
    while True:
        t_next = t + pace * pattern[k % len(pattern)]
        if t_next > dur - pace * 0.5:
            break
        c = round(t_next / HOP)
        lo, hi = max(0, c - w), min(n, c + w + 1)
        # quietest nearby; on a tie, the one closest to the planned time
        q = lo + int(np.argmin(db[lo:hi] + 0.5 * np.abs(np.arange(lo, hi) - c) / w))
        cut = q * HOP
        if cut - t < pace * 0.5:
            cut = t_next
        angle = order[(k + 1) % n_angles]
        out.append(Switch(round(cut, 3), angle))
        t, k = cut, k + 1
    return out


def plan(main_db: np.ndarray, mics: Sequence[tuple[np.ndarray, float, int]], *, mode: str,
         n_angles: int, wide: Optional[int] = None, min_shot: float = 2.0, pace: float = 5.0) -> list[Switch]:
    """``mics``: (loudness, offset to main, camera index) for every mic in ``speaker`` mode."""
    n = len(main_db)
    if mode == "pace":
        return pace_switches(main_db, n_angles, pace)
    dbs = [align(db, off, n) for db, off, _ in mics]
    raw = smooth(raw_speaker(dbs))
    return speaker_switches(raw, [a for _, _, a in mics], wide=wide, min_shot=min_shot)


def summary(switches: Sequence[Switch], duration: float, n_angles: int) -> list[float]:
    """Share of the recording each camera gets (0..1)."""
    share = [0.0] * n_angles
    for i, s in enumerate(switches):
        end = switches[i + 1].t if i + 1 < len(switches) else duration
        if 0 <= s.angle < n_angles:
            share[s.angle] += max(0.0, end - s.t)
    tot = sum(share) or 1.0
    return [round(x / tot, 3) for x in share]


ProgressFn = Callable[[float], None]
