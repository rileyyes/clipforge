"""Titles: text graphics placed on the timeline (lower thirds, big titles, banners…).

Each template is drawn by libass (FFmpeg's subtitle renderer) as ASS events: vector
shapes for the bars/boxes and text on top, with built-in in/out animation. Sizes scale
with the output height, so a design looks the same at 720p, 1080p or 9:16. The Editor's
preview draws the same templates with CSS (frontend/src/components/TitlesPreview.tsx).
"""
from __future__ import annotations

from typing import Optional

TEMPLATES = ("lower_third", "big_title", "top_banner", "subscribe", "chapter", "pop_text", "arrow", "circle", "box")
SHAPES = ("arrow", "circle", "box")
K = 0.5523  # bezier circle constant
IN, OUT = 0.4, 0.3  # seconds of in / out animation


def _c(hex_: str, alpha: int = 0) -> str:
    """#rrggbb -> ASS &HAABBGGRR"""
    r, g, b = hex_[1:3], hex_[3:5], hex_[5:7]
    return f"&H{alpha:02X}{b}{g}{r}&".upper()


def _t(sec: float) -> str:
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(s: str) -> str:
    return (s or "").replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _rect(w: float, h: float) -> str:
    return f"m 0 0 l {w:.0f} 0 {w:.0f} {h:.0f} 0 {h:.0f}"


def _rounded(w: float, h: float, r: float) -> str:
    r = min(r, w / 2, h / 2)
    k = r * 0.45  # bezier handle
    return (f"m {r:.0f} 0 l {w - r:.0f} 0 b {w - k:.0f} 0 {w:.0f} {k:.0f} {w:.0f} {r:.0f} "
            f"l {w:.0f} {h - r:.0f} b {w:.0f} {h - k:.0f} {w - k:.0f} {h:.0f} {w - r:.0f} {h:.0f} "
            f"l {r:.0f} {h:.0f} b {k:.0f} {h:.0f} 0 {h - k:.0f} 0 {h - r:.0f} "
            f"l 0 {r:.0f} b 0 {k:.0f} {k:.0f} 0 {r:.0f} 0")


class Measure:
    """Text width in pixels with the real font (falls back to an estimate)."""

    def __init__(self, font_path: Optional[str]):
        self.path = font_path
        self.cache: dict = {}

    def width(self, text: str, size: int) -> float:
        if not text:
            return 0.0
        if self.path:
            try:
                from PIL import ImageFont
                f = self.cache.get(size) or ImageFont.truetype(self.path, size)
                self.cache[size] = f
                return float(f.getlength(text))
            except Exception:  # noqa: BLE001
                pass
        return len(text) * size * 0.56


def events(t: dict, W: int, H: int, m: Measure) -> list[str]:
    """ASS Dialogue lines for one title (timeline times)."""
    k = H / 1080 * t.get("size", 1.0)
    a, b = t["start"], t["start"] + t["duration"]
    text, sub = _esc(t.get("text", "")), _esc(t.get("subtext") or "")
    col, acc = t.get("color", "#ffffff"), t.get("accent", "#ff5a3c")
    align = t.get("align", "left")
    span = f"{_t(a)},{_t(b)}"
    ms = lambda s: int(s * 1000)  # noqa: E731
    fad = f"\\fad({ms(0.15)},{ms(OUT)})"
    out: list[str] = []

    def line(layer: int, tags: str, body: str) -> None:
        out.append(f"Dialogue: {layer},{span},T,,0,0,0,,{{{tags}}}{body}")

    if t["template"] == "lower_third":
        fs, ss = int(54 * k), int(34 * k)
        pad = 28 * k
        w = max(m.width(text, fs), m.width(sub, ss)) + 2 * pad
        h = fs * 1.25 + (ss * 1.3 if sub else 0) + pad
        y = H - H * 0.1 - h
        if align == "right":
            x1, x0 = W - W * 0.05 - w, W + 10
        elif align == "center":
            x1, x0 = (W - w) / 2, (W - w) / 2
        else:
            x1, x0 = W * 0.05, -w - 10
        mv = lambda dx, dy: f"\\move({x0 + dx:.0f},{y + dy:.0f},{x1 + dx:.0f},{y + dy:.0f},0,{ms(IN)})"  # noqa: E731
        line(0, f"\\an7{mv(0, 0)}{fad}\\p1\\c{_c('#000000')}\\alpha&H60&\\bord0\\shad0", _rounded(w, h, 10 * k))
        line(1, f"\\an7{mv(0, 0)}{fad}\\p1\\c{_c(acc)}\\bord0\\shad0", _rect(10 * k, h))
        line(2, f"\\an7{mv(pad, pad * 0.45)}{fad}\\fs{fs}\\b1\\c{_c(col)}\\bord0\\shad0", text)
        if sub:
            line(2, f"\\an7{mv(pad, pad * 0.45 + fs * 1.25)}{fad}\\fs{ss}\\b0\\c{_c(col)}\\alpha&H30&\\bord0\\shad0", sub)
    elif t["template"] == "big_title":
        fs, ss = int(110 * k), int(46 * k)
        cy = H * 0.45
        pop = f"\\fscx70\\fscy70\\t(0,{ms(IN * 0.6)},\\fscx106\\fscy106)\\t({ms(IN * 0.6)},{ms(IN)},\\fscx100\\fscy100)"
        line(1, f"\\an5\\pos({W / 2:.0f},{cy:.0f}){fad}{pop}\\fs{fs}\\b1\\c{_c(col)}\\3c{_c('#000000')}\\bord{6 * k:.1f}\\shad{4 * k:.1f}", text)
        if sub:
            line(1, f"\\an8\\pos({W / 2:.0f},{cy + fs * 0.7:.0f}){fad}\\fs{ss}\\b1\\c{_c(acc)}\\3c{_c('#000000')}\\bord{4 * k:.1f}\\shad{3 * k:.1f}", sub)
    elif t["template"] == "top_banner":
        fs = int(52 * k)
        h = fs * 1.9
        line(0, f"\\an7\\move(0,{-h:.0f},0,0,0,{ms(IN)}){fad}\\p1\\c{_c(acc)}\\bord0\\shad{4 * k:.1f}", _rect(W, h))
        an, x = {"left": (4, W * 0.05), "right": (6, W * 0.95), "center": (5, W / 2)}[align if align in ("left", "right") else "center"]
        line(1, f"\\an{an}\\move({x:.0f},{-h / 2:.0f},{x:.0f},{h / 2:.0f},0,{ms(IN)}){fad}\\fs{fs}\\b1\\c{_c(col)}\\bord0\\shad0",
             text + (f"  {{\\b0\\alpha&H40&}}{sub}" if sub else ""))
    elif t["template"] == "subscribe":
        fs = int(52 * k)
        label = text or "SUBSCRIBE"
        pad = 34 * k
        w, h = m.width(label, fs) + 2 * pad, fs * 1.8
        x = {"left": W * 0.05, "center": (W - w) / 2}.get(align, W * 0.95 - w)
        y = H * 0.8 - h
        pop = f"\\fscx40\\fscy40\\t(0,{ms(IN * 0.6)},\\fscx110\\fscy110)\\t({ms(IN * 0.6)},{ms(IN)},\\fscx100\\fscy100)"
        line(0, f"\\an5\\pos({x + w / 2:.0f},{y + h / 2:.0f}){fad}{pop}\\p1\\c{_c(acc)}\\bord0\\shad{4 * k:.1f}",
             _rounded(w, h, h * 0.25))
        line(1, f"\\an5\\pos({x + w / 2:.0f},{y + h / 2:.0f}){fad}{pop}\\fs{fs}\\b1\\c{_c(col)}\\bord0\\shad0", label)
        if sub:
            line(1, f"\\an8\\pos({x + w / 2:.0f},{y + h + 10 * k:.0f}){fad}\\fs{int(fs * 0.6)}\\c{_c('#ffffff')}\\bord{3 * k:.1f}", sub)
    elif t["template"] in ("pop_text", *SHAPES):
        out += _free(t, W, H, k, a, b)
    elif t["template"] == "chapter":
        fs, ss = int(96 * k), int(40 * k)
        line(0, f"\\an7\\pos(0,0)\\fad({ms(IN)},{ms(OUT)})\\p1\\c{_c('#000000')}\\alpha&H50&\\bord0\\shad0", _rect(W, H))
        line(1, f"\\an5\\pos({W / 2:.0f},{H * 0.5:.0f})\\fad({ms(IN)},{ms(OUT)})\\fs{fs}\\b1\\c{_c(col)}\\bord0\\shad{3 * k:.1f}", text)
        line(1, f"\\an7\\pos({(W - 160 * k) / 2:.0f},{H * 0.5 + fs * 0.65:.0f})\\fad({ms(IN)},{ms(OUT)})\\p1\\c{_c(acc)}\\bord0\\shad0",
             _rect(160 * k, 8 * k))
        if sub:
            line(1, f"\\an2\\pos({W / 2:.0f},{H * 0.5 - fs * 0.6:.0f})\\fad({ms(IN)},{ms(OUT)})\\fs{ss}\\b1\\c{_c(acc)}\\bord0\\shad0",
                 sub.upper())
    return out


def _anim(kind: str, x: float, y: float, H: float, n_chars: int = 0) -> tuple[str, str]:
    """(position + transform tags, per-text prefix) for a free-placed title's in-animation."""
    ms = lambda s: int(s * 1000)  # noqa: E731
    pos = f"\\pos({x:.0f},{y:.0f})"
    if kind == "pop":
        return pos + f"\\fscx40\\fscy40\\t(0,{ms(IN * 0.6)},\\fscx112\\fscy112)\\t({ms(IN * 0.6)},{ms(IN)},\\fscx100\\fscy100)", ""
    if kind == "slide_up":
        return f"\\move({x:.0f},{y + H * 0.08:.0f},{x:.0f},{y:.0f},0,{ms(IN)})", ""
    if kind == "bounce":
        return (f"\\move({x:.0f},{y - H * 0.18:.0f},{x:.0f},{y:.0f},0,250)"
                "\\t(250,330,\\fscx118\\fscy84)\\t(330,430,\\fscx94\\fscy108)\\t(430,520,\\fscx100\\fscy100)"), ""
    return pos, ""


def typewriter(text: str, dur: float) -> str:
    """Reveal one character at a time (ASS alpha per character), over at most 0.8 s or half the title."""
    chars = list(text)
    if not chars:
        return ""
    step = min(0.06, min(0.8, dur * 0.5) / len(chars))
    out = []
    for i, ch in enumerate(chars):
        t0 = int(i * step * 1000)
        out.append(f"{{\\alpha&HFF&\\t({t0},{t0 + 1},\\alpha&H00&)}}{_esc(ch)}")
    return "".join(out)


def _circle(r: float) -> str:
    c = K * r
    return (f"m {r:.1f} 0 b {r + c:.1f} 0 {2 * r:.1f} {r - c:.1f} {2 * r:.1f} {r:.1f} "
            f"b {2 * r:.1f} {r + c:.1f} {r + c:.1f} {2 * r:.1f} {r:.1f} {2 * r:.1f} "
            f"b {r - c:.1f} {2 * r:.1f} 0 {r + c:.1f} 0 {r:.1f} b 0 {r - c:.1f} {r - c:.1f} 0 {r:.1f} 0")


def _arrow(L: float, T: float) -> str:
    """Arrow pointing right, L long, shaft T thick, head 2.6·T wide."""
    hw, hl = T * 1.3, T * 2.2
    return (f"m 0 {hw - T / 2:.1f} l {L - hl:.1f} {hw - T / 2:.1f} l {L - hl:.1f} 0 l {L:.1f} {hw:.1f} "
            f"l {L - hl:.1f} {2 * hw:.1f} l {L - hl:.1f} {hw + T / 2:.1f} l 0 {hw + T / 2:.1f}")


def _free(t: dict, W: int, H: int, k: float, a: float, b: float) -> list[str]:
    """pop_text, arrow, circle, box: placed anywhere (x, y = centre), rotated, animated."""
    span = f"{_t(a)},{_t(b)}"
    x, y = t.get("x", 0.5) * W, t.get("y", 0.5) * H
    rot = -float(t.get("rotation", 0))  # ASS turns anticlockwise; the UI's degrees are clockwise
    kind = t.get("anim", "pop")
    col, acc = t.get("color", "#ffffff"), t.get("accent", "#ff5a3c")
    fad = f"\\fad(120,{int(OUT * 1000)})"
    frz = f"\\frz{rot:.1f}" if abs(rot) > 1e-6 else ""
    out = []
    if t["template"] == "pop_text":
        fs = int(96 * k)
        pos, _ = _anim("none" if kind == "typewriter" else kind, x, y, H)
        body = typewriter(t.get("text", ""), b - a) if kind == "typewriter" else _esc(t.get("text", ""))
        out.append(f"Dialogue: 1,{span},T,,0,0,0,,{{\\an5{pos}{fad}{frz}\\fs{fs}\\b1\\c{_c(col)}\\3c{_c('#000000')}"
                   f"\\bord{max(2.0, 7 * k):.1f}\\shad{3 * k:.1f}}}{body}")
        return out
    pos, _ = _anim(kind if kind != "typewriter" else "pop", x, y, H)
    stroke = max(3.0, 12 * k)
    if t["template"] == "arrow":
        L, T = 260 * k, 34 * k
        out.append(f"Dialogue: 1,{span},T,,0,0,0,,{{\\an5{pos}{fad}{frz}\\p1\\c{_c(acc)}\\3c{_c('#000000')}"
                   f"\\bord{max(1.5, 4 * k):.1f}\\shad{3 * k:.1f}}}{_arrow(L, T)}")
    elif t["template"] == "circle":
        r = 120 * k
        out.append(f"Dialogue: 1,{span},T,,0,0,0,,{{\\an5{pos}{fad}{frz}\\p1\\1a&HFF&\\3c{_c(acc)}"
                   f"\\bord{stroke:.1f}\\shad0}}{_circle(r)}")
    else:  # box
        w, h = 320 * k, 200 * k
        out.append(f"Dialogue: 1,{span},T,,0,0,0,,{{\\an5{pos}{fad}{frz}\\p1\\1a&HFF&\\3c{_c(acc)}"
                   f"\\bord{stroke:.1f}\\shad0}}{_rect(w, h)}")
    if t.get("text"):  # optional label under the shape
        fs = int(48 * k)
        out.append(f"Dialogue: 2,{span},T,,0,0,0,,{{\\an8\\pos({x:.0f},{y + 140 * k:.0f}){fad}\\fs{fs}\\b1\\c{_c(col)}"
                   f"\\3c{_c('#000000')}\\bord{max(2.0, 5 * k):.1f}}}{_esc(t['text'])}")
    return out


def ass(titles: list[dict], W: int, H: int, family: str, font_path: Optional[str]) -> str:
    m = Measure(font_path)
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: T,{family},48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,0,2,7,0,0,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    for i, t in enumerate(sorted(titles, key=lambda t: t["start"])):
        # later titles above earlier ones
        lines += [ln.replace("Dialogue: ", f"Dialogue: {i * 3}+", 1) for ln in events(t, W, H, m)]
    fixed = []
    for ln in lines:  # Layer = base*3 + template layer
        pre, rest = ln.split(",", 1)
        base, lay = pre[len("Dialogue: "):].split("+")
        fixed.append(f"Dialogue: {int(base) + int(lay)},{rest}")
    return head + "\n".join(fixed) + "\n"
