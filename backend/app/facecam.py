"""Face cam: a webcam recording laid over the main recording, following every cut.

The face cam isn't a timeline clip. Wherever the main recording appears on the bottom
video track, the matching moment of the cam (cam time = main time + offset) is placed
on top. So cuts made by hand or by the AI apply to the cam automatically, and moving a
clip moves its cam with it.

Rendering: each visible stretch becomes a "virtual" overlay clip. Its segment is an
RGBA picture: the cam scaled to cover its box, cut to the chosen shape (and, if asked,
to the person — see ``matte.py``), on a backdrop with border and shadow, with alpha
fades where it hides/shows. The final encode overlays it like any other upper track.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Optional

from . import ffmpeg as ff
from .schema import CamBox, Clip, Crop, FaceCam, MediaAsset, OutputSettings, Project, Transform, MIN_CLIP_DURATION

HIDE_FADE = 0.25  # seconds: the cam fades out/in around hidden stretches
SHADOW = 0.012    # shadow spread, fraction of frame width


@dataclass
class CamPart:
    clip: Clip            # virtual overlay clip (cam media, cam source times)
    full: bool = False    # fills the screen (big-reaction moment)
    fade_in: float = 0.0  # alpha fades (only next to hidden stretches)
    fade_out: float = 0.0


# ---------------------------------------------------------------- layout
def cam_aspect(fc: FaceCam, cam: MediaAsset, full: bool = False) -> float:
    w, h = (cam.width or 16), (cam.height or 9)
    if full:
        return w / h
    c = fc.crop
    return (w * (1 - c.left - c.right)) / max(1e-6, h * (1 - c.top - c.bottom))


def layout_box(fc: FaceCam, out_w: int, out_h: int, aspect: float) -> CamBox:
    """The cam's box for a corner preset (or the custom box), in frame fractions."""
    if fc.corner == "custom":
        return fc.box
    mx = fc.margin
    my = min(0.2, fc.margin * out_w / out_h)  # same gap in pixels on both edges
    bw_px = fc.size * out_w
    bh_px = bw_px if fc.shape == "circle" else bw_px / max(aspect, 1e-6)
    room = out_h * (1 - 2 * my)
    if bh_px > room:  # very tall cam in a wide frame: shrink it to stay on screen
        k = room / bh_px
        bw_px, bh_px = bw_px * k, bh_px * k
    w, h = bw_px / out_w, bh_px / out_h
    x = mx if fc.corner.endswith("left") else 1 - mx - w
    y = my if fc.corner.startswith("top") else 1 - my - h
    return CamBox(x=round(x, 5), y=round(y, 5), w=round(w, 5), h=round(h, 5))


def box_px(box: CamBox, W: int, H: int) -> tuple[int, int, int, int]:
    """Even-sized pixel box (x, y, w, h)."""
    w = max(16, int(round(box.w * W / 2)) * 2)
    h = max(16, int(round(box.h * H / 2)) * 2)
    return int(round(box.x * W)), int(round(box.y * H)), w, h


# ---------------------------------------------------------------- which parts show
def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _subtract(a: float, b: float, holes: list[tuple[float, float]]) -> list[tuple[float, float, bool, bool]]:
    """Pieces of [a, b) outside ``holes``; flags: piece starts / ends at a hole."""
    pieces, cur, cur_hole = [], a, False
    for ha, hb in holes:
        if hb <= cur or ha >= b:
            continue
        if ha > cur:
            pieces.append((cur, ha, cur_hole, True))
        cur, cur_hole = max(cur, hb), True
    if cur < b:
        pieces.append((cur, b, cur_hole, False))
    return pieces


def cam_parts(project: Project, new_id=lambda: hashlib.sha1(b"x").hexdigest()[:32]) -> list[CamPart]:
    fc = project.facecam
    if fc is None or not fc.enabled:
        return []
    media = project.media_by_id()
    cam, main = media.get(fc.media_id), media.get(fc.main_media_id)
    if cam is None or main is None or not cam.has_video:
        return []
    tracks = [t for t in project.timeline.tracks if t.kind == "video" and not t.hidden]
    if not tracks:
        return []
    hidden = _merge([(r.start, r.end) for r in fc.hidden])
    full = _merge([(r.start, r.end) for r in fc.full])
    parts: list[CamPart] = []
    n = 0
    for c in sorted(tracks[0].clips, key=lambda c: c.start):
        if c.media_id != fc.main_media_id:
            continue
        a = max(c.source_in, -fc.offset)                     # cam must exist at main time t:
        b = min(c.source_out, cam.duration - fc.offset)      # 0 <= t + offset <= cam length
        if b - a < MIN_CLIP_DURATION * c.speed:
            continue
        for pa, pb, after_hole, before_hole in _subtract(a, b, hidden):
            # split at full-screen ranges
            cuts = sorted({pa, pb, *[x for r in full for x in r if pa < x < pb]})
            for i, (sa, sb) in enumerate(zip(cuts, cuts[1:])):
                if sb - sa < MIN_CLIP_DURATION * c.speed:
                    continue
                mid = (sa + sb) / 2
                is_full = any(ra <= mid < rb for ra, rb in full)
                n += 1
                clip = Clip(id=f"{n:08d}" + "c" * 24, media_id=fc.media_id,
                            start=c.start + (sa - c.source_in) / c.speed,
                            source_in=sa + fc.offset, source_out=sb + fc.offset, speed=c.speed)
                d = (sb - sa) / c.speed
                parts.append(CamPart(clip, is_full,
                                     min(HIDE_FADE, d / 3) if (i == 0 and after_hole) else 0.0,
                                     min(HIDE_FADE, d / 3) if (i == len(cuts) - 2 and before_hole) else 0.0))
    return parts


def place(part: CamPart, fc: FaceCam, cam: MediaAsset, out: OutputSettings) -> tuple[CamBox, int]:
    """(box, padding px for border + shadow) and sets the virtual clip's centre offset."""
    W, H = out.width, out.height
    if part.full:
        box, pad = CamBox(x=0, y=0, w=1, h=1), 0
    else:
        box = layout_box(fc, W, H, cam_aspect(fc, cam))
        pad = (_border_px(fc, W) + (int(round(SHADOW * W)) if _shadow(fc) else 0))
    x, y, w, h = box_px(box, W, H)
    part.clip = part.clip.model_copy(update={"transform": Transform(x=x + w / 2 - W / 2, y=y + h / 2 - H / 2)})
    return box, pad


def _border_px(fc: FaceCam, W: int) -> int:
    return 0 if fc.remove_bg or fc.border <= 0 else max(1, int(round(fc.border * W)))


def _shadow(fc: FaceCam) -> bool:
    return fc.shadow and not fc.remove_bg


# ---------------------------------------------------------------- shapes (PNG)
def _shape_img(w: int, h: int, shape: str, fill, mode: str = "L"):
    from PIL import Image, ImageDraw
    k = 4  # draw big, shrink: smooth edges
    img = Image.new(mode, (w * k, h * k), 0 if mode == "L" else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shape == "circle":
        d.ellipse([0, 0, w * k - 1, h * k - 1], fill=fill)
    elif shape == "rounded":
        d.rounded_rectangle([0, 0, w * k - 1, h * k - 1], radius=int(min(w, h) * 0.12 * k), fill=fill)
    else:
        d.rectangle([0, 0, w * k - 1, h * k - 1], fill=fill)
    return img.resize((w, h), Image.LANCZOS)


def mask_png(work: Path, w: int, h: int, shape: str) -> Path:
    p = work / f"cammask_{shape}_{w}x{h}.png"
    if not p.exists():
        _shape_img(w, h, shape, 255).save(p)
    return p


def backdrop_png(work: Path, fc: FaceCam, w: int, h: int, W: int) -> Optional[Path]:
    """Border + shadow behind the cam, on a canvas padded on every side."""
    from PIL import Image, ImageFilter
    b = _border_px(fc, W)
    s = int(round(SHADOW * W)) if _shadow(fc) else 0
    if not b and not s:
        return None
    pad = b + s
    key = hashlib.sha1(f"{fc.shape}{w}{h}{b}{s}{fc.border_color}".encode()).hexdigest()[:12]
    p = work / f"camback_{key}.png"
    if p.exists():
        return p
    cw, ch = w + 2 * pad, h + 2 * pad
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    if s:
        sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        sh.paste(_shape_img(w + 2 * b, h + 2 * b, fc.shape, (0, 0, 0, 150), "RGBA"),
                 (pad - b, pad - b + max(1, s // 3)))
        canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(max(1, s / 2))))
    if b:
        rgb = tuple(int(fc.border_color[i:i + 2], 16) for i in (1, 3, 5))
        border = _shape_img(w + 2 * b, h + 2 * b, fc.shape, (*rgb, 255), "RGBA")
        layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        layer.paste(border, (pad - b, pad - b))
        canvas = Image.alpha_composite(canvas, layer)
    canvas.save(p)
    return p


# ---------------------------------------------------------------- FFmpeg
def _crop_filter(c: Crop) -> Optional[str]:
    if not c.active:
        return None
    return (f"crop=trunc(iw*{1 - c.left - c.right:.5f}/2)*2:trunc(ih*{1 - c.top - c.bottom:.5f}/2)*2:"
            f"trunc(iw*{c.left:.5f}):trunc(ih*{c.top:.5f})")


def segment_args(src: Path, matte: Optional[Path], seg, part: CamPart, fc: FaceCam, cam: MediaAsset,
                 out: OutputSettings, fps: Fraction, work: Path, dest: Path) -> list[str]:
    """RGBA (FFV1) picture of one visible face cam stretch: cam + shape (+ person cut-out),
    on its border/shadow backdrop, with alpha fades."""
    c = seg.clip
    W, H = out.width, out.height
    box, pad = place(part, fc, cam, out)
    _, _, bw, bh = box_px(box, W, H)
    seek = c.source_in + seg.head * c.speed
    span = c.source_out - seek
    shape = "rect" if part.full else fc.shape
    crop = None if part.full else _crop_filter(fc.crop)
    cover = f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},setsar=1"
    timing = f"setpts=(PTS-STARTPTS)/{c.speed:.6f},fps={fps}"
    inputs = ff.untrusted_input_args(src, seek=seek, duration=max(span, 0.05) + 0.5)
    g = [f"[0:v]{timing},{','.join(x for x in (crop, cover) if x)},format=yuva444p[c]"]
    k = 1
    inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(mask_png(work, bw, bh, shape))]
    g.append(f"[{k}:v]format=gray[sm]")
    mask = "sm"
    k += 1
    if matte is not None and fc.remove_bg and not part.full:
        sw, sh = cam.width or 1280, cam.height or 720
        inputs += ["-ss", f"{seek:.6f}", "-t", f"{max(span, 0.05) + 0.5:.6f}", "-i", str(matte)]
        # soft threshold: model confidence 0.3 → 0, 0.7 → 1 (cleaner edges, less halo)
        g.append(f"[{k}:v]{timing},scale={sw}:{sh},{','.join(x for x in (crop, cover) if x)},format=gray,"
                 f"lut=y='clip((val-77)*255/102\\,0\\,255)'[mm]")
        g.append("[mm][sm]blend=all_mode=multiply[mk]")
        mask = "mk"
        k += 1
    g.append(f"[c][{mask}]alphamerge[ca]")
    last = "ca"
    back = None if part.full else backdrop_png(work, fc, bw, bh, W)
    if back is not None:
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(back)]
        g.append(f"[{k}:v]format=yuva444p[bd]")
        g.append(f"[bd][{last}]overlay=x={pad}:y={pad}:shortest=1:format=yuv444[cb]")
        last = "cb"
    dur = float(seg.count / fps)
    fades = []
    if part.fade_in > 0 and seg.head <= 1e-6:
        fades.append(f"fade=t=in:st=0:d={part.fade_in:.3f}:alpha=1")
    if part.fade_out > 0:
        fades.append(f"fade=t=out:st={max(0.0, dur - part.fade_out):.3f}:d={part.fade_out:.3f}:alpha=1")
    tail = ",".join(["tpad=stop_mode=clone:stop_duration=10", f"trim=end_frame={seg.count}",
                     "setpts=PTS-STARTPTS", *fades, "format=yuva420p"])
    g.append(f"[{last}]{tail}[v]")
    return inputs + ["-filter_complex", ";".join(g), "-map", "[v]", "-an", "-frames:v", str(seg.count),
                     "-r", str(fps), "-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuva420p", str(dest)]
