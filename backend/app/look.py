"""Clip look & animation: colour correction, looks, crop, keyframes, rotation/opacity.

Keyframes are anchored to SOURCE time (seconds of the media file), like effects, so
trimming, splitting or changing speed never shifts an animation off its picture.
Interpolation (shared exactly with the editor preview, see timeline/keyframes.ts):

* before the first keyframe → its value; after the last → its value
* ``linear`` → straight line to the next keyframe
* ``ease``   → smoothstep (slow-fast-slow) to the next keyframe
* ``hold``   → stays until the next keyframe, then jumps
"""
from __future__ import annotations

from typing import Optional, Sequence

from .schema import Clip, ColorAdjust, Keyframe

# ---------------------------------------------------------------- keyframes


def value_at(kfs: Sequence[Keyframe], t: float, default: float) -> float:
    if not kfs:
        return default
    if t <= kfs[0].t:
        return kfs[0].v
    for a, b in zip(kfs, kfs[1:]):
        if t < b.t:
            p = (t - a.t) / (b.t - a.t)
            if a.ease == "hold":
                return a.v
            if a.ease == "ease":
                p = p * p * (3 - 2 * p)
            return a.v + (b.v - a.v) * p
    return kfs[-1].v


def _num(x: float) -> str:
    return str(int(x)) if x == int(x) else format(x, ".12g")


def kf_expr(kfs: Sequence[Keyframe], src: str, default: float) -> str:
    """FFmpeg expression for the keyframed value at source time ``src`` (an expression).

    Built as nested if() over segments; the source time is evaluated once per piece
    (FFmpeg expressions can't hold variables across the whole if-tree reliably)."""
    if not kfs:
        return _num(default)
    S = f"({src})"
    expr = _num(kfs[-1].v)
    for a, b in reversed(list(zip(kfs, kfs[1:]))):
        dv, dt = b.v - a.v, b.t - a.t
        p = f"(({S}-{_num(a.t)})/{_num(dt)})"
        if a.ease == "hold" or abs(dv) < 1e-12:
            piece = _num(a.v)
        elif a.ease == "ease":
            piece = f"({_num(a.v)}+{_num(dv)}*{p}*{p}*(3-2*{p}))"
        else:
            piece = f"({_num(a.v)}+{_num(dv)}*{p})"
        expr = f"if(lt({S},{_num(b.t)}),{piece},{expr})"
    return f"if(lt({S},{_num(kfs[0].t)}),{_num(kfs[0].v)},{expr})"


def animated(clip: Clip, prop: str) -> bool:
    k = clip.keyframes.get(prop) or []
    return len(k) > 1 and any(abs(x.v - k[0].v) > 1e-9 for x in k)


def prop_expr(clip: Clip, prop: str, src: str) -> str:
    """Expression (or constant) for a transform property, keyframes winning over the static value."""
    static = getattr(clip.transform, prop) if prop != "volume" else clip.volume
    kfs = clip.keyframes.get(prop) or []
    if not kfs:
        return _num(static)
    if not animated(clip, prop):
        return _num(kfs[0].v)
    return kf_expr(kfs, src, static)


def static_value(clip: Clip, prop: str) -> float:
    """Value when not animated (single keyframe counts as a fixed value)."""
    kfs = clip.keyframes.get(prop) or []
    if kfs:
        return kfs[0].v
    return getattr(clip.transform, prop) if prop != "volume" else clip.volume


def sample_times(clip: Clip, prop: str, seek: float, seconds: float, fps: float) -> list[tuple[float, float]]:
    """(segment time, value) at every frame where the value changes — for sendcmd."""
    kfs = clip.keyframes.get(prop) or []
    out: list[tuple[float, float]] = []
    n = int(seconds * fps) + 2
    step = max(1, n // 3000)  # cap the command list on very long clips
    last: Optional[float] = None
    for i in range(0, n, step):
        t = i / fps
        v = round(value_at(kfs, seek + t * clip.speed, clip.transform.opacity), 4)
        if v != last:
            out.append((t, v))
            last = v
    return out


# ---------------------------------------------------------------- colour

LOOK_FILTERS = {
    "none": [],
    "warm": ["colortemperature=temperature=4800", "eq=saturation=1.08"],
    "cool": ["colortemperature=temperature=9000"],
    "bw": ["hue=s=0"],
    "vintage": ["curves=preset=vintage"],
    "vivid": ["eq=saturation=1.35:contrast=1.08"],
    "faded": ["curves=all='0/0.08 1/0.92'", "eq=saturation=0.8"],
    "cinematic": ["colorbalance=rs=-0.05:bs=0.07:rh=0.07:bh=-0.06", "eq=contrast=1.08"],
    "noir": ["hue=s=0", "eq=contrast=1.35"],
    # Phase 18
    "horror": ["eq=saturation=0.45:contrast=1.25:brightness=-0.04", "colorbalance=gs=0.06:bs=-0.03:gm=0.04",
               "vignette=angle=PI/3.5"],
    "vhs": ["rgbashift=rh=3:bh=-3", "eq=saturation=1.25:contrast=0.92", "gblur=sigma=0.7",
            "noise=alls=14:allf=t", "drawgrid=w=iw:h=4:t=1:c=black@0.22"],
    "film": ["colortemperature=temperature=5600", "eq=contrast=1.06:saturation=0.9", "noise=alls=10:allf=t",
             "vignette=angle=PI/4.5"],
    "vignette": ["vignette=angle=PI/4"],
    "letterbox": ["drawbox=x=0:y=0:w=iw:h=ih*0.11:color=black:t=fill",
                  "drawbox=x=0:y=ih-ih*0.11:w=iw:h=ih*0.11:color=black:t=fill"],
}


def color_filters(c: ColorAdjust) -> list[str]:
    out: list[str] = []
    if (abs(c.brightness) > 1e-4 or abs(c.contrast - 1) > 1e-4 or abs(c.saturation - 1) > 1e-4
            or abs(c.gamma - 1) > 1e-4):
        out.append(f"eq=brightness={c.brightness:.3f}:contrast={c.contrast:.3f}:"
                   f"saturation={c.saturation:.3f}:gamma={c.gamma:.3f}")
    if abs(c.temperature) > 1e-4:
        # colortemperature: lower Kelvin = warmer picture. ±1 → 3500 K / 10000 K
        k = 6500 - 3000 * c.temperature if c.temperature > 0 else 6500 - 3500 * c.temperature
        out.append(f"colortemperature=temperature={k:.0f}")
    out += LOOK_FILTERS[c.look]
    return out


# ---------------------------------------------------------------- crop

def crop_filters(clip: Clip, keep_size: bool) -> list[str]:
    """Remove the edges. With ``keep_size`` the frame is padded back to its original size
    with transparency so the visible part stays exactly where it was."""
    c = clip.crop
    if not c.active:
        return []
    fw, fh = 1 - c.left - c.right, 1 - c.top - c.bottom
    f = [f"crop=w=trunc(iw*{fw:.5f}/2)*2:h=trunc(ih*{fh:.5f}/2)*2:x=iw*{c.left:.5f}:y=ih*{c.top:.5f}"]
    if keep_size:
        f.append(f"pad=w=trunc(iw/{fw:.5f}/2)*2:h=trunc(ih/{fh:.5f}/2)*2:"
                 f"x=iw/{fw:.5f}*{c.left:.5f}:y=ih/{fh:.5f}*{c.top:.5f}:color=black@0")
    return f


def crop_shift(clip: Clip, axis: str) -> str:
    """Overlay x/y correction (uses the cropped overlay size w/h) that keeps the visible
    part where it was when the picture isn't padded back."""
    c = clip.crop
    if not c.active:
        return "0"
    if axis == "x":
        return f"(w/{1 - c.left - c.right:.5f}*{(c.left - c.right) / 2:.5f})"
    return f"(h/{1 - c.top - c.bottom:.5f}*{(c.top - c.bottom) / 2:.5f})"


# ---------------------------------------------------------------- transform warp

def needs_warp(clip: Clip) -> bool:
    """Rotation, animated scale, any opacity or a green screen need the alpha + perspective path."""
    return (clip.chroma is not None or any(animated(clip, p) for p in ("scale", "rotation", "opacity"))
            or abs(static_value(clip, "rotation")) > 1e-6 or static_value(clip, "opacity") < 0.999)


def perspective_filter(clip: Clip, W: int, H: int, m: int, seek: str, fps: float) -> str:
    """Warp a (W+2m)x(H+2m) transparent canvas holding the fitted clip: scale, rotate
    about the centre and move, by mapping its four corners (``sense=destination``).
    Time comes from the frame number (perspective has no ``t``)."""
    src = f"({seek}+in/{fps:.6f}*{clip.speed:.6f})"
    s = prop_expr(clip, "scale", src)
    r = prop_expr(clip, "rotation", src)
    x = prop_expr(clip, "x", src)
    y = prop_expr(clip, "y", src)
    cx, cy, hw, hh = W / 2 + m, H / 2 + m, W / 2 + m, H / 2 + m
    co, si = f"cos(({r})*PI/180)", f"sin(({r})*PI/180)"
    pts = []
    for dx, dy in ((-hw, -hh), (hw, -hh), (-hw, hh), (hw, hh)):
        px = f"{cx}+({x})+({s})*({dx}*{co}-({dy})*{si})"
        py = f"{cy}+({y})+({s})*({dx}*{si}+({dy})*{co})"
        pts += [px, py]
    names = ["x0", "y0", "x1", "y1", "x2", "y2", "x3", "y3"]
    args = ":".join(f"{n}='{v}'" for n, v in zip(names, pts))
    ev = "frame" if any(animated(clip, p) for p in ("scale", "rotation", "x", "y")) else "init"
    return f"perspective={args}:sense=destination:eval={ev}:interpolation=linear"


def opacity_filters(clip: Clip, seek: float, seconds: float, fps: float) -> list[str]:
    if animated(clip, "opacity"):
        pts = sample_times(clip, "opacity", seek, seconds, fps)
        cmds = ";".join(f"{t:.4f} colorchannelmixer aa {v}" for t, v in pts[1:])
        first = f"colorchannelmixer=aa={pts[0][1]}"
        return ([f"sendcmd=c='{cmds}'"] if cmds else []) + [first]
    op = static_value(clip, "opacity")
    return [f"colorchannelmixer=aa={op:.4f}"] if op < 0.999 else []
