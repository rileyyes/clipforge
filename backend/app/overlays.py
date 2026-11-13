"""Phase 18 overlays drawn by libass above every title: counters (KILLS 7) and name tags
(who's talking). They go in the titles ASS file as extra events.

The Editor's preview draws the same things in CSS (frontend/src/components/OverlaysPreview.tsx)
with the same sizes, positions and timing.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import effects as fx
from .schema import Counter, Project
from .titles import Measure, _c, _esc, _rounded, _t

LAYER = 9000          # above every title (titles use 3 layers per title, at most 500 titles)
POP = 0.25            # seconds a new count takes to settle


def counter_ticks(project: Project) -> dict[str, list[float]]:
    """Timeline times each counter goes up (a count effect counts every time its moment plays)."""
    ids = {c.id for c in project.timeline.counters}
    out: dict[str, list[float]] = {i: [] for i in ids}
    for e in project.effects:
        if e.kind != "count" or not e.enabled or e.counter not in ids:
            continue
        wins = fx.map_to_timeline(project, e, "video") or fx.map_to_timeline(project, e, "audio")
        out[e.counter] += [w.start for w in wins]
    return {k: sorted(v) for k, v in out.items()}


def counter_layout(c: Counter, H: int, measure: Measure, biggest: int) -> dict:
    """Box size (px) for a counter; wide enough for its biggest number so it doesn't jump."""
    k = H / 1080 * c.size
    fl, fn, pad = int(30 * k), int(86 * k), 18 * k
    w = max(measure.width(c.label.upper(), fl), measure.width(str(biggest), fn), 70 * k) + 2 * pad
    h = pad * 0.8 + (fl * 1.2 if c.label else 0) + fn * 1.05 + pad * 0.5
    return {"k": k, "fl": fl, "fn": fn, "pad": pad, "w": w, "h": h}


def counter_events(c: Counter, ticks: list[float], W: int, H: int, D: float,
                   family: Optional[str], measure: Measure, layer: int) -> list[tuple[float, float, str]]:
    a0 = max(0.0, c.start)
    a1 = min(D, c.end) if c.end is not None else D
    if a1 - a0 < 0.05:
        return []
    ticks = [t for t in ticks if t < a1]
    L = counter_layout(c, H, measure, c.start_value + len(ticks))
    k, fl, fn, pad, w, h = L["k"], L["fl"], L["fn"], L["pad"], L["w"], L["h"]
    cx, cy = c.x * W, c.y * H
    x0, y0 = cx - w / 2, cy - h / 2
    fnt = f"\\fn{family}\\b0" if family else "\\b1"
    out: list[tuple[float, float, str]] = []

    def ev(a: float, b: float, lay: int, tags: str, body: str) -> None:
        out.append((a, b, f"Dialogue: {layer + lay},{_t(a)},{_t(b)},T,,0,0,0,,{{{tags}}}{body}"))
    fade = "\\fad(200,0)" if a0 > 0 else ""
    ev(a0, a1, 0, f"\\an7\\pos({x0:.0f},{y0:.0f}){fade}\\p1\\c{_c('#000000')}\\alpha&H48&\\3c{_c(c.accent)}"
                  f"\\bord{max(1.5, 4 * k):.1f}\\shad0", _rounded(w, h, 12 * k))
    if c.label:
        ev(a0, a1, 1, f"\\an8\\pos({cx:.0f},{y0 + pad * 0.8:.0f}){fade}\\fs{fl}{fnt}\\c{_c(c.color)}\\alpha&H20&\\bord0\\shad0",
           _esc(c.label.upper()))
    ny = y0 + pad * 0.8 + (fl * 1.2 if c.label else 0) + fn * 0.525
    # one event per value; each new value pops in and flashes the accent colour
    bounds = [a0] + [t for t in ticks if t >= a0] + [a1]
    value = c.start_value + sum(1 for t in ticks if t < a0)
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if i > 0:
            value += 1
        if b - a < 0.005:
            continue
        pop = (f"\\fscx160\\fscy160\\c{_c(c.accent)}\\t(0,{int(POP * 1000)},\\fscx100\\fscy100)"
               f"\\t(0,{int(POP * 2000)},\\c{_c(c.color)})") if i > 0 else f"\\c{_c(c.color)}{fade}"
        ev(a, b, 2, f"\\an5\\pos({cx:.0f},{ny:.0f}){pop}\\fs{fn}{fnt}\\3c{_c('#000000')}\\bord{3 * k:.1f}\\shad0", str(value))
    return out


def name_tag_events(project: Project, talk_of: Callable, W: int, H: int, D: float,
                    measure: Measure, layer: int) -> list[tuple[float, float, str]]:
    """A voice-chat style list of the tagged audio tracks; whoever is talking lights up."""
    nt = project.timeline.name_tags
    tracks = [t for t in project.timeline.tracks if t.kind == "audio" and not t.muted and t.tag.strip() and t.clips]
    if not nt.enabled or not tracks or D <= 0:
        return []
    k = H / 1080 * nt.size
    fs, pad, dot = int(34 * k), 14 * k, 18 * k
    rh, gap = fs * 1.55, 8 * k
    w = max(measure.width(t.tag.strip(), fs) for t in tracks) + pad * 3 + dot
    mx, my = W * 0.025, H * 0.04
    right, bottom = nt.corner.endswith("r"), nt.corner.startswith("b")
    out: list[tuple[float, float, str]] = []
    n = len(tracks)
    for i, tr in enumerate(tracks):
        row = (n - 1 - i) if bottom else i
        x = W - mx - w if right else mx
        y = (H - my - (row + 1) * rh - row * gap) if bottom else (my + row * (rh + gap))
        name = _esc(tr.tag.strip())

        def ev(a: float, b: float, lay: int, tags: str, body: str) -> None:
            out.append((a, b, f"Dialogue: {layer + lay},{_t(a)},{_t(b)},T,,0,0,0,,{{{tags}}}{body}"))
        if not nt.only_talking:      # the quiet look, always there
            ev(0, D, 0, f"\\an7\\pos({x:.0f},{y:.0f})\\p1\\c{_c('#000000')}\\alpha&H70&\\bord0\\shad0", _rounded(w, rh, rh / 2))
            ev(0, D, 1, f"\\an7\\pos({x + pad:.0f},{y + (rh - dot) / 2:.0f})\\p1\\c{_c('#80848e')}\\bord0\\shad0", _rounded(dot, dot, dot / 2))
            ev(0, D, 1, f"\\an4\\pos({x + pad * 2 + dot:.0f},{y + rh / 2:.0f})\\fs{fs}\\b1\\c{_c('#ffffff')}\\alpha&H50&\\bord0\\shad0", name)
        for a, b in talk_of(tr):
            a, b = max(0.0, a), min(D, b)
            if b - a < 0.05:
                continue
            ev(a, b, 2, f"\\an7\\pos({x:.0f},{y:.0f})\\p1\\c{_c(tr.tag_color)}\\alpha&H10&\\bord0\\shad{2 * k:.1f}", _rounded(w, rh, rh / 2))
            ev(a, b, 3, f"\\an7\\pos({x + pad:.0f},{y + (rh - dot) / 2:.0f})\\p1\\c{_c('#3ba55d')}\\3c{_c('#ffffff')}"
                        f"\\bord{max(1.0, 2 * k):.1f}\\shad0", _rounded(dot, dot, dot / 2))
            ev(a, b, 3, f"\\an4\\pos({x + pad * 2 + dot:.0f},{y + rh / 2:.0f})\\fs{fs}\\b1\\c{_c('#ffffff')}\\bord0\\shad{1.5 * k:.1f}", name)
    return out


def events(project: Project, W: int, H: int, D: float, fonts: dict, default_measure: Measure,
           talk_of: Callable) -> list[tuple[float, float, str]]:
    """All overlay events (start, end, ASS line), timeline seconds."""
    out: list[tuple[float, float, str]] = []
    ticks = counter_ticks(project)
    for i, c in enumerate(project.timeline.counters):
        fam, path = fonts.get(c.font, (None, None)) if c.font else (None, None)
        m = Measure(path) if fam else default_measure
        out += counter_events(c, ticks.get(c.id, []), W, H, D, fam, m, LAYER + i * 4)
    out += name_tag_events(project, talk_of, W, H, D, default_measure, LAYER + 40)
    return out


def font_ids(project: Project) -> set[Optional[str]]:
    """Every font the titles, counters and captions use (to stage for libass)."""
    ids: set[Optional[str]] = {t.font for t in project.timeline.titles}
    ids |= {c.font for c in project.timeline.counters}
    ids.add(project.captions.font)
    if any(t.template == "sticker" for t in project.timeline.titles):
        ids.add("emoji")
    return ids
