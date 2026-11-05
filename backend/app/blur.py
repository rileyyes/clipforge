"""Privacy blur: hide part of the picture, optionally following something that moves.

Rendering: for each blur, a fixed-size patch (the largest box it ever has) is cut out at
a position that follows its keys (piecewise linear, as a balanced tree of if()s so long
tracks stay cheap), blurred / pixelated / blacked out (and cut to an ellipse if asked),
and laid back at the same place while the blur is on. Times are timeline seconds.

Tracking: template matching (OpenCV, no model needed) on frames of the clip(s) under the
blur at 10 fps; the template adapts slowly so gradual changes (turning a head) are kept,
and the result is simplified to a few keys a second.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import ffmpeg as ff

TRACK_FPS = 10
MAX_KEYS = 240


# ---------------------------------------------------------------- render
def _lerp_tree(keys: list[dict], field: str, lo: int, hi: int) -> str:
    if hi - lo <= 1:
        a, b = keys[lo], keys[hi]
        if abs(b["t"] - a["t"]) < 1e-9 or abs(b[field] - a[field]) < 1e-9:
            return f"{a[field]:.2f}"
        return f"({a[field]:.2f}+({b[field] - a[field]:.2f})*(t-{a['t']:.3f})/{b['t'] - a['t']:.3f})"
    mid = (lo + hi) // 2
    return f"if(lt(t,{keys[mid]['t']:.3f}),{_lerp_tree(keys, field, lo, mid)},{_lerp_tree(keys, field, mid, hi)})"


def position_expr(keys: list[dict], field: str) -> str:
    """Piecewise-linear value of keys[field] over t (held before the first / after the last)."""
    if len(keys) == 1:
        return f"{keys[0][field]:.2f}"
    k0, kn = keys[0], keys[-1]
    return (f"if(lt(t,{k0['t']:.3f}),{k0[field]:.2f},if(gte(t,{kn['t']:.3f}),{kn[field]:.2f},"
            f"{_lerp_tree(keys, field, 0, len(keys) - 1)}))")


def filters(blurs: list, W: int, H: int, last: str, g: list[str], work: Path, tag: str) -> str:
    """Append the blur filters to graph ``g``; returns the new last label."""
    for i, b in enumerate(blurs):
        pw = max(8, int(round(max(k.w for k in b.keys) * W / 2)) * 2)
        ph = max(8, int(round(max(k.h for k in b.keys) * H / 2)) * 2)
        pw, ph = min(pw, W), min(ph, H)
        # top-left of the patch: key centre minus half the (fixed) patch size, kept on the frame
        pts = [{"t": k.t, "cx": (k.x + k.w / 2) * W, "cy": (k.y + k.h / 2) * H} for k in b.keys]
        x = f"clip({position_expr(pts, 'cx')}-{pw / 2:.1f},0,{W - pw})"
        y = f"clip({position_expr(pts, 'cy')}-{ph / 2:.1f},0,{H - ph})"
        a, e = b.start, b.start + b.duration
        n = f"b{tag}_{i}"
        g.append(f"[{last}]split[{n}m][{n}s]")
        chain = f"[{n}s]crop={pw}:{ph}:x='{x}':y='{y}'"
        if b.mode == "blur":
            r = int(max(2, min(b.strength * min(pw, ph) / 4, min(pw, ph) / 4 - 1)))
            chain += f",boxblur=luma_radius={r}:luma_power=3:chroma_radius={max(1, r // 2)}:chroma_power=3"
        elif b.mode == "pixelate":
            cells = max(3, int(round(4 + (1 - b.strength) * 20)))  # blocks across the patch
            chain += (f",scale={cells}:{max(2, round(cells * ph / pw))}:flags=area,"
                      f"scale={pw}:{ph}:flags=neighbor")
        else:
            chain += ",lutyuv=y=16:u=128:v=128"
        if b.shape == "ellipse":
            mask = _ellipse(work, pw, ph)
            g.append(f"movie='{mask.name}',loop=loop=-1:size=1,format=gray[{n}k]")
            chain += f",format=yuva420p[{n}c];[{n}c][{n}k]alphamerge"
        g.append(f"{chain}[{n}p]")
        g.append(f"[{n}m][{n}p]overlay=x='{x}':y='{y}':eval=frame:enable='between(t,{a:.3f},{e:.3f})'[{n}o]")
        last = f"{n}o"
    return last


def _ellipse(work: Path, w: int, h: int) -> Path:
    from PIL import Image, ImageDraw
    p = work / f"blurmask_{w}x{h}.png"
    if not p.exists():
        k = 4
        img = Image.new("L", (w * k, h * k), 0)
        ImageDraw.Draw(img).ellipse([0, 0, w * k - 1, h * k - 1], fill=255)
        img.resize((w, h), Image.LANCZOS).save(p)
    return p


# ---------------------------------------------------------------- tracking
def grab(ffmpeg_bin: str, src: Path, start: float, end: float, width: int, src_w: int, src_h: int) -> np.ndarray:
    h = max(2, int(round(src_h * width / src_w / 2)) * 2)
    raw = subprocess.run([ffmpeg_bin, "-v", "error", *ff.untrusted_input_args(src, seek=start, duration=max(0.05, end - start)),
                          "-vf", f"fps={TRACK_FPS},scale={width}:{h}", "-an", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, timeout=1800).stdout
    n = len(raw) // (width * h)
    return np.frombuffer(raw[: n * width * h], np.uint8).reshape(n, h, width)


def track(frames: np.ndarray, box: tuple[float, float, float, float],
          on_progress: Optional[Callable[[float], None]] = None,
          template: Optional[np.ndarray] = None, state: Optional[dict] = None) -> list[tuple[float, float, float, float, float]]:
    """box = (x, y, w, h) fractions in frame 0; returns (x, y, w, h, score) per frame.
    With ``template`` (what was followed before a cut) the first frame is searched whole,
    because after a cut the thing can be anywhere. ``state["template"]`` gets the final
    template, to pass on to the next piece."""
    import cv2
    n, H, W = frames.shape
    bw, bh = max(8, int(box[2] * W)), max(8, int(box[3] * H))
    x, y = int(box[0] * W), int(box[1] * H)
    x, y = min(max(0, x), W - bw), min(max(0, y), H - bh)
    score0 = 1.0
    if template is not None and template.shape == (bh, bw) and template.std() > 1e-3:
        res = cv2.matchTemplate(frames[0].astype(np.float32), template, cv2.TM_CCOEFF_NORMED)
        _, score0, _, loc = cv2.minMaxLoc(res)
        if score0 >= 0.5:
            x, y = loc
    tpl = frames[0][y:y + bh, x:x + bw].astype(np.float32)
    if template is not None and score0 < 0.5:
        tpl = template  # not found after the cut: keep looking for the old picture
    out = [(x / W, y / H, bw / W, bh / H, float(score0))]
    for i in range(1, n):
        mx, my = int(bw * 1.2), int(bh * 1.2)          # search around the last spot
        sx0, sy0 = max(0, x - mx), max(0, y - my)
        sx1, sy1 = min(W, x + bw + mx), min(H, y + bh + my)
        region = frames[i][sy0:sy1, sx0:sx1].astype(np.float32)
        if region.shape[0] < bh or region.shape[1] < bw or tpl.std() < 1e-3:
            out.append((x / W, y / H, bw / W, bh / H, 0.0))
            continue
        res = cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score >= 0.35:
            x, y = sx0 + loc[0], sy0 + loc[1]
            if score >= 0.6:  # adapt slowly to gradual changes
                tpl = 0.85 * tpl + 0.15 * frames[i][y:y + bh, x:x + bw].astype(np.float32)
        out.append((x / W, y / H, bw / W, bh / H, float(score)))
        if on_progress and i % 10 == 0:
            on_progress(i / n)
    if state is not None:
        state["template"] = tpl
    return out


def simplify(points: list[tuple[float, float, float]], tol: float = 0.004) -> list[int]:
    """Indexes of (t, x, y) points to keep (Ramer–Douglas–Peucker on x and y)."""
    if len(points) <= 2:
        return list(range(len(points)))
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ta, xa, ya = points[a]
        tb, xb, yb = points[b]
        worst, wi = 0.0, -1
        for i in range(a + 1, b):
            t, x, y = points[i]
            f = (t - ta) / (tb - ta) if tb > ta else 0
            d = max(abs(x - (xa + (xb - xa) * f)), abs(y - (ya + (yb - ya) * f)))
            if d > worst:
                worst, wi = d, i
        if worst > tol and wi > 0:
            keep.add(wi)
            stack += [(a, wi), (wi, b)]
    return sorted(keep)


# ---------------------------------------------------------------- source <-> output frame
def picture_rect(src_w: int, src_h: int, out_w: int, out_h: int, fit: str = "fit",
                 scale: float = 1.0, dx: float = 0.0, dy: float = 0.0) -> tuple[float, float, float, float]:
    """Where a base-track clip's picture lands in the output (px: left, top, width, height)."""
    k = (max if fit == "fill" else min)(out_w / src_w, out_h / src_h) * scale
    w, h = src_w * k, src_h * k
    return (out_w - w) / 2 + dx, (out_h - h) / 2 + dy, w, h


def to_output(box: tuple[float, float, float, float], rect, out_w: int, out_h: int):
    x, y, w, h = box
    L, T, RW, RH = rect
    return ((L + x * RW) / out_w, (T + y * RH) / out_h, w * RW / out_w, h * RH / out_h)


def to_source(box: tuple[float, float, float, float], rect, out_w: int, out_h: int):
    x, y, w, h = box
    L, T, RW, RH = rect
    return ((x * out_w - L) / RW, (y * out_h - T) / RH, w * out_w / RW, h * out_h / RH)
