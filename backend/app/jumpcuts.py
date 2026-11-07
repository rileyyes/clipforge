"""Smoother jump cuts: where talking was cut out of one continuous shot, the picture
jumps. Three ways to hide that, applied to every jump cut on the bottom video track:

* "punch": alternate between the normal framing and a slight zoom-in (~12%), so each
  cut looks like a different camera angle (what most YouTubers do by hand)
* "blend": a 0.12 s crossfade (the linked audio crossfades too)
* "whip": a 0.25 s whip pan, alternating left/right

The same rules are implemented in the Editor (frontend/src/timeline/ops.ts,
smoothJumpCuts) and both are checked against tests/data/jumpcut_vectors.json.
Only changes RJClip made itself are undone when switching mode or turning it off.
"""
from __future__ import annotations

from typing import Literal

Mode = Literal["off", "punch", "blend", "whip"]
PUNCH = 0.055                      # crop from each side -> 1 / (1 - 2 * 0.055) = 1.12x zoom
BLEND = ("crossfade", 0.12)
WHIP = (("whip_left", "whip_right"), 0.25)
GAP = 0.02                         # clips this close on the timeline are "back to back"
JUMP = 0.04                        # at least this much footage removed between them


def _dur(c: dict) -> float:
    return (c["source_out"] - c["source_in"]) / c.get("speed", 1)


def _is_punch(crop: dict | None) -> bool:
    c = crop or {}
    return all(abs(c.get(k, 0) - PUNCH) < 1e-6 for k in ("left", "right", "top", "bottom"))


def _is_plain(crop: dict | None) -> bool:
    c = crop or {}
    return all(abs(c.get(k, 0)) < 1e-6 for k in ("left", "right", "top", "bottom"))


def _ours(tr: dict | None) -> bool:
    if not tr:
        return False
    return ((tr["kind"] == BLEND[0] and abs(tr["duration"] - BLEND[1]) < 1e-6)
            or (tr["kind"] in WHIP[0] and abs(tr["duration"] - WHIP[1]) < 1e-6))


def jump_pairs(clips: list[dict]) -> list[tuple[int, int]]:
    """Indexes (into the start-sorted list) of back-to-back clips of the same footage
    with a stretch cut out between them."""
    out = []
    for i in range(len(clips) - 1):
        a, b = clips[i], clips[i + 1]
        if (a["media_id"] == b["media_id"] and abs(b["start"] - (a["start"] + _dur(a))) < GAP
                and b["source_in"] - a["source_out"] > JUMP):
            out.append((i, i + 1))
    return out


def smooth(timeline: dict, mode: Mode) -> tuple[dict, int]:
    """Returns (new timeline, number of jump cuts smoothed)."""
    tracks = [dict(t, clips=[dict(c) for c in t["clips"]]) for t in timeline["tracks"]]
    video = next((t for t in tracks if t["kind"] == "video"), None)
    if video is None or video.get("locked"):
        return {**timeline, "tracks": tracks}, 0
    clips = sorted(video["clips"], key=lambda c: c["start"])
    # undo our own earlier changes first (modes don't stack)
    for c in clips:
        if _is_punch(c.get("crop")):
            c["crop"] = {"left": 0, "right": 0, "top": 0, "bottom": 0}
        if _ours(c.get("transition_in")):
            c["transition_in"] = None
    pairs = jump_pairs(clips)
    n = 0
    if mode == "punch":
        in_run: dict[int, int] = {}
        for i, j in pairs:
            in_run.setdefault(i, 0)
            in_run[j] = in_run[i] + 1
        for idx, pos in in_run.items():
            c = clips[idx]
            if pos % 2 == 1 and _is_plain(c.get("crop")):
                c["crop"] = {"left": PUNCH, "right": PUNCH, "top": PUNCH, "bottom": PUNCH}
                n += 1
    elif mode in ("blend", "whip"):
        k = 0
        for i, j in pairs:
            a, b = clips[i], clips[j]
            d = BLEND[1] if mode == "blend" else WHIP[1]
            if b.get("transition_in") or min(_dur(a), _dur(b)) * 0.9 < d:
                continue
            kind = BLEND[0] if mode == "blend" else WHIP[0][k % 2]
            b["transition_in"] = {"kind": kind, "duration": d}
            k += 1
            n += 1
    video["clips"] = clips
    return {**timeline, "tracks": tracks}, n
