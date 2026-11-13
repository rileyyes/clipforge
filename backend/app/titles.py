"""Titles: text graphics placed on the timeline (lower thirds, big titles, banners…).

Each template is drawn by libass (FFmpeg's subtitle renderer) as ASS events: vector
shapes for the bars/boxes and text on top, with built-in in/out animation. Sizes scale
with the output height, so a design looks the same at 720p, 1080p or 9:16. The Editor's
preview draws the same templates with CSS (frontend/src/components/TitlesPreview.tsx).
"""
from __future__ import annotations

import re
from typing import Optional

TEMPLATES = ("lower_third", "big_title", "top_banner", "subscribe", "chapter", "pop_text", "arrow", "circle", "box",
             "count_card", "tally", "number_card", "sticker", "ticker", "stamp", "route", "highlight")
SHAPES = ("arrow", "circle", "box")
FREE = ("pop_text", "sticker", "ticker", *SHAPES)   # placed anywhere (x, y), rotated, animated
STICKER_FONT = "emoji"                         # fontlib id of the sticker font (Noto Emoji)
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
    elif t["template"] in FREE:
        out += _free(t, W, H, k, a, b)
    elif t["template"] == "stamp":
        out += _stamp(t, W, H, k, span)
    elif t["template"] == "route":
        out += _route(t, W, H, k, a, b)
    elif t["template"] == "highlight":
        out += _highlight(t, W, H, k, span)
    elif t["template"] == "count_card":
        out += _count_card(t, W, H, k, m, span, fad)
    elif t["template"] == "tally":
        out += _tally(t, W, H, k, m, span)
    elif t["template"] == "number_card":
        fs, ts, ss = int(300 * k), int(78 * k), int(42 * k)
        cy = H * 0.42
        line(0, f"\\an7\\pos(0,0)\\fad({ms(0.2)},{ms(OUT)})\\p1\\c{_c('#000000')}\\alpha&H70&\\bord0\\shad0", _rect(W, H))
        pop = f"\\fscx40\\fscy40\\t(0,{ms(IN * 0.6)},\\fscx112\\fscy112)\\t({ms(IN * 0.6)},{ms(IN)},\\fscx100\\fscy100)"
        line(1, f"\\an5\\pos({W / 2:.0f},{cy:.0f}){fad}{pop}\\fs{fs}\\b1\\c{_c(acc)}\\3c{_c('#000000')}\\bord{10 * k:.1f}\\shad{6 * k:.1f}",
             f"#{int(t.get('number', 1))}")
        if text:
            line(1, f"\\an8\\move({W / 2:.0f},{cy + fs * 0.55 + H * 0.05:.0f},{W / 2:.0f},{cy + fs * 0.55:.0f},{ms(0.15)},{ms(IN + 0.15)})"
                    f"{fad}\\fs{ts}\\b1\\c{_c(col)}\\3c{_c('#000000')}\\bord{5 * k:.1f}\\shad{3 * k:.1f}", text)
        if sub:
            line(1, f"\\an8\\pos({W / 2:.0f},{cy + fs * 0.55 + ts * 1.3:.0f}){fad}\\fs{ss}\\b0\\c{_c(col)}\\alpha&H30&"
                    f"\\3c{_c('#000000')}\\bord{3 * k:.1f}", sub)
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
    if t["template"] == "sticker":
        # the sticker font is line art: an outline in its own colour makes the lines bold
        fs = int(240 * k)
        pos, _ = _anim("pop" if kind == "typewriter" else kind, x, y, H)
        out.append(f"Dialogue: 1,{span},T,,0,0,0,,{{\\an5{pos}{fad}{frz}\\fs{fs}\\b0\\c{_c(col)}\\3c{_c(col)}"
                   f"\\bord{max(1.0, 2.5 * k):.1f}\\shad{5 * k:.1f}\\4c{_c('#000000', 0x60)}}}{_esc(t.get('text', ''))}")
        return out
    if t["template"] == "ticker":
        return _ticker(t, W, H, k, a, b, x, y, frz)
    if t["template"] == "pop_text" and kind == "words":
        fs = int(96 * k)
        out.append(f"Dialogue: 1,{span},T,,0,0,0,,{{\\an5\\pos({x:.0f},{y:.0f}){fad}{frz}\\fs{fs}\\b1\\c{_c(col)}\\3c{_c('#000000')}"
                   f"\\bord{max(2.0, 7 * k):.1f}\\shad{3 * k:.1f}}}{word_by_word(t.get('text', ''), b - a)}")
        return out
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


def word_by_word(text: str, dur: float) -> str:
    """Each word pops in after the one before (Phase 19): over at most 1.2 s or 60 % of the title."""
    words = (text or "").split()
    if not words:
        return ""
    step = min(0.35, min(1.2, dur * 0.6) / len(words))
    out = []
    for i, w in enumerate(words):
        t0 = int(i * step * 1000)
        out.append(f"{{\\alpha&HFF&\\fscx55\\fscy55\\t({t0},{t0 + 1},\\alpha&H00&)\\t({t0},{t0 + 140},\\fscx112\\fscy112)"
                   f"\\t({t0 + 140},{t0 + 220},\\fscx100\\fscy100)}}{_esc(w)}" + (" " if i < len(words) - 1 else ""))
    return "".join(out)


# ---------------------------------------------------------------- Phase 19: ticker (timers, money)
def ticker_value(tt: float, t: dict) -> float:
    """The ticker's value tt seconds into the title. Time counts evenly; money and numbers
    roll fast then settle (ease-out). It reaches the end value before the fade-out starts.
    Same rule in the Editor preview (frontend/src/timeline/phase19.ts tickerValue)."""
    frm, to = float(t.get("count_from", 60)), float(t.get("count_to", 0))
    run = max(0.05, float(t["duration"]) - OUT)
    p = min(1.0, max(0.0, tt / run))
    if t.get("format", "time") != "time":
        p = 1 - (1 - p) ** 3
    return frm + (to - frm) * p


def ticker_text(v: float, t: dict) -> str:
    fmt = t.get("format", "time")
    down = float(t.get("count_to", 0)) < float(t.get("count_from", 60))
    if fmt == "time":
        import math
        s = math.ceil(v - 1e-9) if down else math.floor(v + 1e-9)
        sign, s = ("-" if s < 0 else ""), abs(int(s))
        h, m, sec = s // 3600, s // 60 % 60, s % 60
        return f"{sign}{h}:{m:02d}:{sec:02d}" if h else f"{sign}{m}:{sec:02d}"
    n = int(round(v))
    body = f"{abs(n):,}"
    return ("-" if n < 0 else "") + ("$" if fmt == "money" else "") + body


def ticker_steps(t: dict) -> list[tuple[float, str]]:
    """(seconds into the title, text) each time the shown text changes."""
    dur = float(t["duration"])
    step = max(1 / 15, dur / 3000)
    out: list[tuple[float, str]] = []
    n = int(dur / step) + 1
    for i in range(n + 1):
        tt = min(dur, i * step)
        txt = ticker_text(ticker_value(tt, t), t)
        if not out or out[-1][1] != txt:
            out.append((tt, txt))
    # the exact end value, the moment the count finishes
    end = ticker_text(float(t.get("count_to", 0)), t)
    if out[-1][1] != end:
        out.append((min(dur, max(0.05, dur - OUT)), end))
    return out


def _ticker(t: dict, W: int, H: int, k: float, a: float, b: float, x: float, y: float, frz: str) -> list[str]:
    col, acc = t.get("color", "#ffffff"), t.get("accent", "#ff3b30")
    fs, fl = int(110 * k), int(40 * k)
    down = float(t.get("count_to", 0)) < float(t.get("count_from", 60))
    fad_in = "\\fad(150,0)"
    out = []
    if t.get("text"):
        out.append(f"Dialogue: 1,{_t(a)},{_t(b)},T,,0,0,0,,{{\\an2\\pos({x:.0f},{y - fs * 0.55:.0f})\\fad(150,{int(OUT * 1000)}){frz}"
                   f"\\fs{fl}\\b1\\c{_c(acc)}\\3c{_c('#000000')}\\bord{max(1.5, 4 * k):.1f}\\shad0}}{_esc(t['text'])}")
    steps = ticker_steps(t)
    for i, (t0, txt) in enumerate(steps):
        s0, s1 = a + t0, (a + steps[i + 1][0]) if i + 1 < len(steps) else b
        if s1 - s0 < 0.005:
            continue
        last = i == len(steps) - 1
        # a countdown's last ten seconds turn the accent colour
        hot = t.get("format", "time") == "time" and down and _secs(txt) <= 10
        fade = (fad_in if i == 0 else "") + (f"\\fad(0,{int(OUT * 1000)})" if last and i else "")
        if last and i == 0:
            fade = f"\\fad(150,{int(OUT * 1000)})"
        out.append(f"Dialogue: 1,{_t(s0)},{_t(s1)},T,,0,0,0,,{{\\an5\\pos({x:.0f},{y:.0f}){fade}{frz}\\fs{fs}\\b1"
                   f"\\c{_c(acc if hot else col)}\\3c{_c('#000000')}\\bord{max(2.0, 8 * k):.1f}\\shad{4 * k:.1f}}}{txt}")
    return out


def _secs(txt: str) -> float:
    try:
        parts = [int(p) for p in txt.lstrip("-").split(":")]
    except ValueError:
        return 1e9
    v = 0
    for p_ in parts:
        v = v * 60 + p_
    return v


# ---------------------------------------------------------------- Phase 19: stamp, route, highlight
def _stamp(t: dict, W: int, H: int, k: float, span: str) -> list[str]:
    """Location / time stamp (DAY 1 — 6:00 AM, Tokyo), typed out at the top left."""
    col, acc = t.get("color", "#ffffff"), t.get("accent", "#ffde00")
    fs, ss = int(72 * k), int(38 * k)
    x, y = W * 0.05, H * 0.08
    dur = float(t["duration"])
    text, sub = t.get("text", ""), t.get("subtext") or ""
    fad = f"\\fad(0,{int(OUT * 1000)})"
    out = [f"Dialogue: 0,{span},T,,0,0,0,,{{\\an7\\pos({x:.0f},{y:.0f})\\fad(120,{int(OUT * 1000)})\\p1\\c{_c(acc)}\\bord0\\shad0}}"
           f"{_rect(8 * k, fs * 1.15 + (ss * 1.3 if sub else 0))}",
           f"Dialogue: 1,{span},T,,0,0,0,,{{\\an7\\pos({x + 24 * k:.0f},{y:.0f}){fad}\\fs{fs}\\b1\\c{_c(col)}\\3c{_c('#000000')}"
           f"\\bord{3 * k:.1f}\\shad{3 * k:.1f}}}{typewriter(text, min(dur, 1.6))}"]
    if sub:
        delay = int(min(0.8, min(1.6, dur) * 0.5) * 1000)
        body = "".join(f"{{\\alpha&HFF&\\t({delay + int(i * 35)},{delay + int(i * 35) + 1},\\alpha&H00&)}}{_esc(ch)}" for i, ch in enumerate(sub))
        out.append(f"Dialogue: 1,{span},T,,0,0,0,,{{\\an7\\pos({x + 24 * k:.0f},{y + fs * 1.15:.0f}){fad}\\fs{ss}\\b0\\c{_c(col)}"
                   f"\\3c{_c('#000000')}\\bord{2 * k:.1f}\\shad{2 * k:.1f}}}{body}")
    return out


def _disc(cx: float, cy: float, r: float) -> str:
    c = K * r
    return (f"m {cx:.1f} {cy - r:.1f} b {cx + c:.1f} {cy - r:.1f} {cx + r:.1f} {cy - c:.1f} {cx + r:.1f} {cy:.1f} "
            f"b {cx + r:.1f} {cy + c:.1f} {cx + c:.1f} {cy + r:.1f} {cx:.1f} {cy + r:.1f} "
            f"b {cx - c:.1f} {cy + r:.1f} {cx - r:.1f} {cy + c:.1f} {cx - r:.1f} {cy:.1f} "
            f"b {cx - r:.1f} {cy - c:.1f} {cx - c:.1f} {cy - r:.1f} {cx:.1f} {cy - r:.1f}")


def _quad(x0: float, y0: float, x1: float, y1: float, half: float) -> str:
    import math
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L * half, dx / L * half
    q = [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]
    # same turning direction as _disc, so overlaps add up instead of cutting holes at the joints
    if sum(q[i][0] * q[(i + 1) % 4][1] - q[(i + 1) % 4][0] * q[i][1] for i in range(4)) < 0:
        q.reverse()
    return "m " + " l ".join(f"{x:.1f} {y:.1f}" for x, y in q[:1]) + " l " + " ".join(f"{x:.1f} {y:.1f}" for x, y in q[1:])


def route_path(pts: list[tuple[float, float]], f: float, half: float) -> tuple[str, tuple[float, float]]:
    """Drawing of the route's first fraction f (by length), with round joins; and the tip."""
    import math
    lens = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
    total = sum(lens) or 1.0
    want = total * max(0.0, min(1.0, f))
    parts = [_disc(pts[0][0], pts[0][1], half)]
    tip = pts[0]
    for i, L in enumerate(lens):
        if want <= 0:
            break
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        u = 1.0 if want >= L else want / L
        tip = (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)
        parts += [_quad(x0, y0, tip[0], tip[1], half), _disc(tip[0], tip[1], half)]
        want -= L
    return " ".join(parts), tip


ROUTE_STEPS = 30


def route_draw_time(dur: float) -> float:
    return min(2.0, max(0.3, dur * 0.5))


def _route(t: dict, W: int, H: int, k: float, a: float, b: float) -> list[str]:
    """A line drawn along points (a route on a map, a path to follow), then a pin at its end."""
    pts = [(x * W, y * H) for x, y in (t.get("points") or [])]
    acc, col = t.get("accent", "#ff3b30"), t.get("color", "#ffffff")
    half = max(2.0, 7 * k)
    out: list[str] = []
    if len(pts) < 2:
        return out
    draw = route_draw_time(b - a)
    # a white line under the coloured one (outlining each piece would show seams at the corners)
    edge = max(1.0, 3 * k)
    under = f"\\an7\\pos(0,0)\\p1\\c{_c('#ffffff')}\\bord0\\shad{2 * k:.1f}"
    over = f"\\an7\\pos(0,0)\\p1\\c{_c(acc)}\\bord0\\shad0"
    for i in range(1, ROUTE_STEPS + 1):
        s0 = a + draw * (i - 1) / ROUTE_STEPS
        s1 = a + draw * i / ROUTE_STEPS if i < ROUTE_STEPS else b
        fade = f"\\fad(0,{int(OUT * 1000)})" if i == ROUTE_STEPS else ""
        out.append(f"Dialogue: 0,{_t(s0)},{_t(s1)},T,,0,0,0,,{{{under}{fade}}}{route_path(pts, i / ROUTE_STEPS, half + edge)[0]}")
        out.append(f"Dialogue: 1,{_t(s0)},{_t(s1)},T,,0,0,0,,{{{over}{fade}}}{route_path(pts, i / ROUTE_STEPS, half)[0]}")
    ex, ey = pts[-1]
    r = 16 * k
    pop = f"\\fscx40\\fscy40\\t(0,180,\\fscx115\\fscy115)\\t(180,280,\\fscx100\\fscy100)"
    out.append(f"Dialogue: 2,{_t(a + draw)},{_t(b)},T,,0,0,0,,{{\\an5\\pos({ex:.0f},{ey:.0f}){pop}\\fad(0,{int(OUT * 1000)})"
               f"\\p1\\c{_c(acc)}\\3c{_c('#ffffff')}\\bord{max(1.5, 5 * k):.1f}\\shad{3 * k:.1f}}}{_circle(r)}")
    if t.get("text"):
        fs = int(46 * k)
        out.append(f"Dialogue: 2,{_t(a + draw)},{_t(b)},T,,0,0,0,,{{\\an2\\pos({ex:.0f},{ey - r * 1.6:.0f})\\fad(150,{int(OUT * 1000)})"
                   f"\\fs{fs}\\b1\\c{_c(col)}\\3c{_c('#000000')}\\bord{max(2.0, 5 * k):.1f}\\shad{2 * k:.1f}}}{_esc(t['text'])}")
    return out


def _highlight(t: dict, W: int, H: int, k: float, span: str) -> list[str]:
    """Highlighter pen sweeping left to right over a box (a quote in a screenshot, a line of text)."""
    w, h = float(t.get("w", 0.4)) * W, float(t.get("h", 0.08)) * H
    x0, y0 = float(t.get("x", 0.5)) * W - w / 2, float(t.get("y", 0.5)) * H - h / 2
    sweep = int(min(0.6, float(t["duration"]) * 0.4) * 1000)
    acc = t.get("accent", "#ffde00")
    clip0 = f"\\clip({x0:.0f},{y0 - 2:.0f},{x0 + 1:.0f},{y0 + h + 2:.0f})"
    clip1 = f"\\clip({x0:.0f},{y0 - 2:.0f},{x0 + w:.0f},{y0 + h + 2:.0f})"
    return [f"Dialogue: 0,{span},T,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\c{_c(acc)}\\alpha&H88&\\bord0\\shad0"
            f"\\fad(0,{int(OUT * 1000)}){clip0}\\t(0,{sweep},{clip1})}}"
            f"m {x0:.0f} {y0:.0f} l {x0 + w:.0f} {y0:.0f} {x0 + w:.0f} {y0 + h:.0f} {x0:.0f} {y0 + h:.0f}"]


def _count_card(t: dict, W: int, H: int, k: float, m: Measure, span: str, fad: str) -> list[str]:
    """A callout: name and detail, with #n (n = its place among the callout cards). Slams in from the left."""
    name, cause = _esc(t.get("text", "")), _esc(t.get("subtext") or "")
    col, acc = t.get("color", "#ffffff"), t.get("accent", "#e3242b")
    label = f"#{t.get('_card_n', 1)}"
    fl, fn, fc = int(30 * k), int(66 * k), int(38 * k)
    pad = 26 * k
    w = max(m.width(label, fl), m.width(name, fn), m.width(cause, fc), 300 * k) + 2 * pad + 12 * k
    h = pad + fl * 1.35 + fn * 1.15 + (fc * 1.3 if cause else 0) + pad * 0.7
    x, y = W * 0.05, H * 0.78 - h
    tx = x + 12 * k + pad

    def mv(px: float, py: float) -> str:
        return f"\\move({px - 60 * k:.0f},{py:.0f},{px:.0f},{py:.0f},0,140)"
    out = [f"Dialogue: 0,{span},T,,0,0,0,,{{\\an7{mv(x, y)}{fad}\\p1\\c{_c('#000000')}\\alpha&H28&\\bord0\\shad{4 * k:.1f}}}{_rounded(w, h, 8 * k)}",
           f"Dialogue: 1,{span},T,,0,0,0,,{{\\an7{mv(x, y)}{fad}\\p1\\c{_c(acc)}\\bord0\\shad0}}{_rect(12 * k, h)}",
           f"Dialogue: 2,{span},T,,0,0,0,,{{\\an7{mv(tx, y + pad * 0.8)}{fad}\\fs{fl}\\b1\\c{_c(acc)}\\bord0\\shad0}}{label}",
           f"Dialogue: 2,{span},T,,0,0,0,,{{\\an7{mv(tx, y + pad * 0.8 + fl * 1.35)}{fad}\\fs{fn}\\b1\\c{_c(col)}\\bord0\\shad0}}{name}"]
    if cause:
        out.append(f"Dialogue: 2,{span},T,,0,0,0,,{{\\an7{mv(tx, y + pad * 0.8 + fl * 1.35 + fn * 1.15)}{fad}\\fs{fc}\\b0"
                   f"\\c{_c(col)}\\alpha&H30&\\bord0\\shad0}}{cause}")
    return out


def _tally(t: dict, W: int, H: int, k: float, m: Measure, span: str) -> list[str]:
    """End-of-video tally: heading, the total, then every callout card's name (and detail), revealed one by one."""
    info = t.get("_tally") or {"entries": [], "total": 0}
    entries = info["entries"][:36]
    col, acc = t.get("color", "#ffffff"), t.get("accent", "#e3242b")
    heading = _esc(t.get("text") or "FINAL TALLY")
    dur = t["duration"]
    fad = f"\\fad(250,{int(OUT * 1000)})"
    fh, ft, fe = int(64 * k), int(150 * k), int(36 * k)
    out = [f"Dialogue: 0,{span},T,,0,0,0,,{{\\an7\\pos(0,0)\\fad(250,{int(OUT * 1000)})\\p1\\c{_c('#000000')}\\alpha&H18&\\bord0\\shad0}}{_rect(W, H)}",
           f"Dialogue: 1,{span},T,,0,0,0,,{{\\an8\\pos({W / 2:.0f},{H * 0.07:.0f}){fad}\\fs{fh}\\b1\\c{_c(col)}\\bord0\\shad{3 * k:.1f}}}{heading}",
           f"Dialogue: 1,{span},T,,0,0,0,,{{\\an8\\pos({W / 2:.0f},{H * 0.07 + fh * 1.2:.0f}){fad}"
           f"\\fscx40\\fscy40\\t(0,240,\\fscx112\\fscy112)\\t(240,400,\\fscx100\\fscy100)\\fs{ft}\\b1\\c{_c(acc)}"
           f"\\3c{_c('#000000')}\\bord{6 * k:.1f}\\shad{4 * k:.1f}}}{int(info['total'])}"]
    if not entries:
        return out
    n = len(entries)
    cols = 1 if n <= 8 else 2 if n <= 18 else 3
    rows = -(-n // cols)
    top = H * 0.07 + fh * 1.2 + ft * 1.15
    row_h = min(fe * 1.4, (H * 0.95 - top) / rows)
    fs = int(min(fe, row_h / 1.4))
    col_w = W * 0.9 / cols
    step = min(0.25, max(0.05, dur * 0.4 / n))
    for i, (name, cause) in enumerate(entries):
        c, r = divmod(i, rows)
        x = W * 0.05 + c * col_w + (col_w / 2 if cols == 1 else 0)
        an = 8 if cols == 1 else 7
        y = top + r * row_h
        label = f"{i + 1}. {_esc(name)}" + (f"  {{\\alpha&H50&}}— {_esc(cause)}" if cause else "")
        t0 = int((0.45 + i * step) * 1000)
        out.append(f"Dialogue: 1,{span},T,,0,0,0,,{{\\an{an}\\pos({x:.0f},{y:.0f})\\fad(0,{int(OUT * 1000)})\\alpha&HFF&"
                   f"\\t({t0},{t0 + 180},\\alpha&H00&)\\fs{fs}\\b1\\c{_c(col)}\\bord0\\shad{2 * k:.1f}}}{label}")
    return out


_BORD = re.compile(r"\\bord[0-9.]+")
_SHAD = re.compile(r"\\shad[0-9.]+")
_C3 = re.compile(r"\\3c&H[0-9A-Fa-f]+&")


def _restyle(lines: list[str], t: dict, k: float, family: Optional[str]) -> list[str]:
    """Apply the title's font and text style (outline, shadow, glow) to its text lines.
    Shapes (\\p1 drawings) keep their look. Nothing set = the template's own look."""
    stroke, shadow, glow = t.get("stroke"), t.get("shadow"), float(t.get("glow") or 0)
    if family is None and stroke is None and shadow is None and glow <= 0:
        return lines
    out = []
    for ln in lines:
        parts = ln.split(",", 9)
        text = parts[9]
        if not text.startswith("{") or "\\p1" in text[:text.index("}")]:
            out.append(ln)
            continue
        end = text.index("}")
        tags, body = text[1:end], text[end + 1:]
        if family:
            tags = tags.replace("\\b1", "\\b0") + f"\\fn{family}"
        if stroke is not None:
            tags = _C3.sub("", _BORD.sub("", tags)) + f"\\bord{stroke * k:.1f}\\3c{_c(t.get('stroke_color', '#000000'))}"
        if shadow is not None:
            tags = _SHAD.sub("", tags) + f"\\shad{shadow * k:.1f}"
        head = ",".join(parts[:9])
        if glow > 0:
            gt = _SHAD.sub("", _C3.sub("", _BORD.sub("", tags)))
            out.append(f"{head},{{{gt}\\1a&HFF&\\bord{glow * k:.1f}\\blur{glow * k * 0.8:.1f}"
                       f"\\3c{_c(t.get('glow_color', '#ffde00'))}\\shad0}}{body}")
        out.append(f"{head},{{{tags}}}{body}")
    return out


def ass(titles: list[dict], W: int, H: int, family: str, font_path: Optional[str],
        fonts: Optional[dict] = None, extra: Optional[list[str]] = None, stamp: str = "",
        all_titles: Optional[list[dict]] = None) -> str:
    """``fonts``: font id -> (family, file) for the fonts staged in the work folder.
    ``extra``: ready Dialogue lines drawn above every title (counters, name tags).
    ``stamp``: comment lines identifying the font files (so a changed file changes the text)."""
    fonts = fonts or {}
    default_m = Measure(font_path)
    measures: dict[str, Measure] = {}
    # callout cards are numbered in time order; the tally lists the ones before it
    # (numbered among all the project's titles, not just the ones in this render block)
    cards = sorted((x for x in (all_titles or titles) if x["template"] == "count_card"), key=lambda x: x["start"])
    ordered = []
    for x in sorted(titles, key=lambda t: t["start"]):
        if x["template"] == "count_card":
            x = {**x, "_card_n": next((i for i, c in enumerate(cards, 1) if c["id"] == x["id"]), 1)}
        elif x["template"] == "tally" and "_tally" not in x:
            before = [c for c in cards if c["start"] < x["start"]] or cards
            x = {**x, "_tally": {"entries": [(c.get("text", ""), c.get("subtext", "")) for c in before], "total": len(before)}}
        ordered.append(x)
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            f"{stamp}"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: T,{family},48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,0,2,7,0,0,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    for i, t in enumerate(ordered):
        fid = STICKER_FONT if t["template"] == "sticker" else t.get("font")
        fam, path = fonts.get(fid, (None, None)) if fid else (None, None)
        m = measures.setdefault(fid, Measure(path)) if fam else default_m
        k = H / 1080 * t.get("size", 1.0)
        # later titles above earlier ones (5 layers each: glow copies share their text's layer)
        lines += [ln.replace("Dialogue: ", f"Dialogue: {i * 3}+", 1) for ln in _restyle(events(t, W, H, m), t, k, fam)]
    fixed = []
    for ln in lines:  # Layer = base*3 + template layer
        pre, rest = ln.split(",", 1)
        base, lay = pre[len("Dialogue: "):].split("+")
        fixed.append(f"Dialogue: {int(base) + int(lay)},{rest}")
    fixed += list(extra or [])  # their layers are set by the caller (above every title)
    return head + "\n".join(fixed) + "\n"
