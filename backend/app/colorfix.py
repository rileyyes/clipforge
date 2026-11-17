"""Phase 21: automatic colour — fix exposure and white balance, or make one camera match another.

How it works (no AI model, nothing to download):

1. A few frames are taken from across the recording (small, 96×54) and put side by side.
2. The picture is measured: how dark the darkest bits and how bright the brightest bits are
   (2nd / 98th percentile of brightness), the middle brightness (median), the colour cast
   (red vs blue in the greyish parts — things that should be neutral) and how colourful it is.
3. The clip's colour settings (brightness, contrast, gamma, warmth, saturation — the same
   sliders as Clip → Colour) are searched so the *measured result* hits the target. Every
   candidate is rendered with the real export filters (look.color_filters), so what's
   measured is what the export will show.

Targets for "fix": a natural spread (shadows near black, highlights near white without
clipping), a middle brightness around 45 %, and no colour cast. For "match", the targets are
the other camera's measurements (after its own colour settings).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from . import ffmpeg as ff
from .look import color_filters
from .schema import ColorAdjust

SW, SH = 96, 54          # sample frame size
N_FRAMES = 8


@dataclass
class Stats:
    lo: float            # 2nd percentile of brightness (0..1)
    hi: float            # 98th percentile
    mid: float           # median brightness
    cast: float          # red minus blue, mostly of the greyish pixels (0 = neutral, > 0 = warm, < 0 = cool)
    sat: float           # mean saturation (0..1)

    def as_dict(self) -> dict:
        return {k: round(float(v), 4) for k, v in self.__dict__.items()}


def sample(ffmpeg_bin: str, src: Path, ranges: list[tuple[float, float]], work: Path) -> Optional[Path]:
    """N_FRAMES small frames from across the given source ranges, side by side in one PNG."""
    total = sum(max(0.0, b - a) for a, b in ranges)
    if total <= 0:
        return None
    times, acc = [], 0.0
    targets = [total * (i + 0.5) / N_FRAMES for i in range(N_FRAMES)]
    for a, b in ranges:
        d = max(0.0, b - a)
        for tt in targets:
            if acc <= tt < acc + d:
                times.append(a + (tt - acc))
        acc += d
    frames = []
    for t in times:
        raw = subprocess.run([ffmpeg_bin, "-v", "error", "-ss", f"{max(0.0, t):.3f}", *ff.untrusted_input_args(src),
                              "-frames:v", "1", "-vf", f"scale={SW}:{SH}:flags=area,format=rgb24", "-f", "rawvideo", "-"],
                             capture_output=True, timeout=120).stdout
        if len(raw) == SW * SH * 3:
            frames.append(np.frombuffer(raw, np.uint8).reshape(SH, SW, 3))
    if not frames:
        return None
    mosaic = np.concatenate(frames, axis=1)
    work.mkdir(parents=True, exist_ok=True)
    raw_path = work / "colorfix_sample.rgb"
    raw_path.write_bytes(mosaic.tobytes())
    out = work / "colorfix_sample.png"
    subprocess.run([ffmpeg_bin, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{mosaic.shape[1]}x{SH}",
                    "-i", str(raw_path), str(out)], check=True, timeout=60)
    raw_path.unlink(missing_ok=True)
    return out


def render(ffmpeg_bin: str, png: Path, c: ColorAdjust) -> np.ndarray:
    """The sample after the export's colour filters (float RGB 0..1)."""
    chain = color_filters(c.model_copy(update={"look": "none"}))
    vf = ",".join(["format=yuv420p", *chain, "format=rgb24"]) if chain else "format=rgb24"
    raw = subprocess.run([ffmpeg_bin, "-v", "error", "-i", str(png), "-vf", vf, "-f", "rawvideo", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    w = len(raw) // (SH * 3)
    return np.frombuffer(raw, np.uint8).reshape(SH, w, 3).astype(np.float64) / 255


def measure(rgb: np.ndarray) -> Stats:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    mx, mn = rgb.max(axis=-1), rgb.min(axis=-1)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    # grey-world (on average a scene is neutral), leaving out near-black and blown-out pixels
    w = ((y > 0.08) & (y < 0.95)).astype(np.float64)
    cast = float(((r - b) * w).sum() / w.sum()) if w.sum() > 1 else 0.0
    return Stats(float(np.percentile(y, 2)), float(np.percentile(y, 98)), float(np.median(y)), cast, float(sat.mean()))


TARGET = Stats(lo=0.04, hi=0.94, mid=0.45, cast=0.0, sat=0.0)


def _err(s: Stats, t: Stats, match: bool) -> float:
    e = 4 * (s.cast - t.cast) ** 2 + (s.mid - t.mid) ** 2 + 0.5 * (s.lo - t.lo) ** 2 + 0.5 * (s.hi - t.hi) ** 2
    if match:
        e += 0.5 * (s.sat - t.sat) ** 2
    return e


def solve(ffmpeg_bin: str, png: Path, target: Stats, match: bool, start: Optional[ColorAdjust] = None) -> tuple[ColorAdjust, Stats, Stats]:
    """Search the colour sliders so the measured picture hits the target.
    Returns (settings, measured before, measured after)."""
    base = (start or ColorAdjust()).model_copy(update={"look": "none"})
    before = measure(render(ffmpeg_bin, png, ColorAdjust()))
    if not match:
        # grey-world can't tell a colour cast from a scene that really is mostly one colour
        # (a sunset, a green field): take away most of a clear cast, leave a slight one alone
        target = Stats(target.lo, target.hi, target.mid, before.cast * 0.25 if abs(before.cast) > 0.015 else before.cast, target.sat)
    cur = base.model_copy(update={"brightness": 0.0, "contrast": 1.0, "gamma": 1.0, "temperature": 0.0, "saturation": 1.0})
    cache: dict[tuple, Stats] = {}

    def score(c: ColorAdjust) -> tuple[float, Stats]:
        key = (round(c.brightness, 3), round(c.contrast, 3), round(c.gamma, 3), round(c.temperature, 3), round(c.saturation, 3))
        if key not in cache:
            cache[key] = measure(render(ffmpeg_bin, png, c))
        return _err(cache[key], target, match), cache[key]

    def cast_err(c: ColorAdjust) -> float:
        return abs(score(c)[1].cast - target.cast) + 0.004 * abs(c.temperature)

    for _round in range(2):
        # 1. white balance, judged on the cast alone (warming also darkens a little, which step 2 makes up for)
        tv = min(np.linspace(-1.0, 1.0, 21), key=lambda v: cast_err(cur.model_copy(update={"temperature": round(float(v), 3)})))
        tv = min((tv - 0.05, tv, tv + 0.05), key=lambda v: cast_err(cur.model_copy(update={"temperature": round(float(v), 3)})) if -1 <= v <= 1 else 9)
        cur = cur.model_copy(update={"temperature": round(float(tv), 3)})
        # 2. contrast + brightness from the spread (eq: out = (in - 0.5) * contrast + 0.5 + brightness),
        #    then gamma for the middle, then a small brightness touch-up
        plain = cur.model_copy(update={"brightness": 0.0, "contrast": 1.0, "gamma": 1.0})
        s0 = score(plain)[1]
        c = float(np.clip((target.hi - target.lo) / max(0.05, s0.hi - s0.lo), 0.75, 1.8))
        # centre the range (if the contrast had to be limited, both ends miss by the same amount)
        bri = float(np.clip((target.lo + target.hi) / 2 - (((s0.lo + s0.hi) / 2 - 0.5) * c + 0.5), -0.3, 0.3))
        cur = plain.model_copy(update={"contrast": round(c, 3), "brightness": round(bri, 3)})
        cur = min((cur.model_copy(update={"gamma": round(float(g), 3)}) for g in np.linspace(0.7, 1.5, 17)), key=lambda x: score(x)[0])
        for d in (-0.06, -0.03, 0.03, 0.06):
            cand = cur.model_copy(update={"brightness": round(float(np.clip(cur.brightness + d, -0.3, 0.3)), 3)})
            if score(cand)[0] < score(cur)[0]:
                cur = cand
        # 3. saturation (match only: as colourful as the other camera)
        if not match:
            break
        cur = min((cur.model_copy(update={"saturation": round(float(v), 3)}) for v in np.linspace(0.6, 1.8, 25)),
                  key=lambda x: abs(score(x)[1].sat - target.sat) + 2 * abs(score(x)[1].cast - target.cast))
    after = score(cur)[1]
    # never make it worse than leaving it alone
    if _err(after, target, match) >= _err(before, target, match):
        return ColorAdjust(look=(start.look if start else "none")), before, before
    return cur.model_copy(update={"look": start.look if start else "none"}), before, after


def target_of(ffmpeg_bin: str, png: Path, c: ColorAdjust) -> Stats:
    """What the reference camera looks like with its own colour settings."""
    return measure(render(ffmpeg_bin, png, c))
