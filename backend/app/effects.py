"""Phase 4 effects: swear censoring, comedic pop-ups, sound effects and captions.

Design notes
* Every effect is anchored to a moment in a SOURCE file (media_id + source_time),
  so it follows the clip through trims/moves and silently drops out if that
  moment is cut. ``map_to_timeline`` does the projection at render time.
* Censoring is done at the audio level: the original speech under a bleep is
  silenced (not just covered), then the bleep sound is mixed in on its own track.
* All sounds are synthesised here from maths (no samples) — no licensing issues.
* Pop-up text is rendered to PNG with Pillow using a real installed font; images
  come only from files the user adds. Nothing random is inserted automatically.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from .analysis import load_analysis
from .schema import Clip, Effect, Project
from .storage import new_id

# ---------------------------------------------------------------- profanity
# Long, distinctive roots match as prefixes ("fucking", "shitty"); short words
# only match exactly so "assume", "class", "dickens" are never flagged.
PREFIX_ROOTS = ("fuck", "motherfuck", "shit", "bullshit", "bitch", "bastard", "asshole", "dumbass",
                "jackass", "dipshit", "goddamn", "dickhead", "fuk", "sht")
EXACT_STRONG = {"ass", "asses", "dick", "dicks", "cock", "cocks", "cunt", "cunts", "piss", "pissed",
                "prick", "twat", "wanker", "bollocks", "slut", "whore", "fck", "fcking", "wtf", "stfu"}
EXACT_MILD = {"damn", "dammit", "damnit", "hell", "crap", "crappy", "sucks", "bloody", "frick", "freaking"}


def normalize(word: str) -> str:
    return re.sub(r"[^a-z*]", "", word.lower())


def is_profane(word: str, level: str = "strong", custom: Iterable[str] = (),
               allow: Iterable[str] = ()) -> bool:
    w = normalize(word)
    if not w or w in {normalize(a) for a in allow}:
        return False
    if w in {normalize(c) for c in custom if c.strip()}:
        return True
    if "*" in w and len(w) >= 3:  # transcriber already starred it ("f***")
        return True
    if any(w.startswith(r) for r in PREFIX_ROOTS) or w in EXACT_STRONG:
        return True
    return level == "all" and w in EXACT_MILD


def mask_word(word: str) -> str:
    letters = [i for i, ch in enumerate(word) if ch.isalpha() or ch == "*"]
    if len(letters) <= 1:
        return "*" * len(word)
    out = list(word)
    for i in letters[1:]:
        out[i] = "*"
    return "".join(out)


# ---------------------------------------------------------------- mapping
@dataclass
class Window:
    start: float  # timeline seconds
    end: float
    effect: Effect
    clip: Clip


def _clip_end(c: Clip) -> float:
    return c.start + (c.source_out - c.source_in) / c.speed


def map_to_timeline(project: Project, effect: Effect, kind: str) -> list[Window]:
    """Timeline windows where this effect's source moment is visible (kind='video')
    or audible (kind='audio'). Empty if that moment was cut from the edit."""
    tracks = [t for t in project.timeline.tracks if t.kind == kind and
              not (t.hidden if kind == "video" else t.muted)]
    s0, s1 = effect.source_time, effect.source_time + effect.duration
    out: list[Window] = []
    for t in tracks:
        for c in t.clips:
            if c.media_id != effect.media_id:
                continue
            a, b = max(s0, c.source_in), min(s1, c.source_out)
            if b - a <= 0.005:
                continue
            ws = c.start + (a - c.source_in) / c.speed
            out.append(Window(round(ws, 4), round(ws + (b - a) / c.speed, 4), effect, c))
    # identical windows from linked/duplicate tracks count once
    uniq: dict[tuple, Window] = {}
    for w in out:
        uniq.setdefault((round(w.start, 3), round(w.end, 3)), w)
    return sorted(uniq.values(), key=lambda w: w.start)


def timeline_to_source(project: Project, t: float) -> Optional[tuple[str, float, Clip]]:
    vids = [x for x in project.timeline.tracks if x.kind == "video" and not x.hidden]
    auds = [x for x in project.timeline.tracks if x.kind == "audio" and not x.muted]
    for track in reversed(vids):
        for c in track.clips:
            if c.start <= t < _clip_end(c):
                return c.media_id, c.source_in + (t - c.start) * c.speed, c
    for track in auds:
        for c in track.clips:
            if c.start <= t < _clip_end(c):
                return c.media_id, c.source_in + (t - c.start) * c.speed, c
    return None


def mutes_for_clip(project: Project, clip: Clip) -> list[tuple[float, float]]:
    """Censor windows inside one audio clip, relative to the clip's source in-point."""
    out = []
    for e in project.effects:
        if e.kind != "censor" or not e.enabled or e.media_id != clip.media_id:
            continue
        a, b = max(e.source_time, clip.source_in), min(e.source_time + e.duration, clip.source_out)
        if b > a:
            out.append((round(a - clip.source_in, 4), round(b - clip.source_in, 4)))
    return out


# ---------------------------------------------------------------- suggestions
def edit_words(project: Project, project_dir: Path) -> list[dict]:
    """Transcript words that survive in the final edit, in timeline order:
    [{text, start, end (timeline s), media_id, src_start, src_end, p}]"""
    tracks = [t for t in project.timeline.tracks if t.kind == "audio" and not t.muted]
    cache: dict[str, Optional[dict]] = {}
    seen: set[tuple] = set()
    out = []
    for t in tracks:
        for c in sorted(t.clips, key=lambda c: c.start):
            if c.media_id not in cache:
                cache[c.media_id] = load_analysis(project_dir, c.media_id)
            for w in (cache[c.media_id] or {}).get("words") or []:
                if not (c.source_in <= w["start"] < c.source_out):
                    continue
                key = (c.media_id, w["start"])
                if key in seen:
                    continue
                seen.add(key)
                ts = c.start + (w["start"] - c.source_in) / c.speed
                te = c.start + (min(w["end"], c.source_out) - c.source_in) / c.speed
                out.append({"text": w["text"], "start": round(ts, 3), "end": round(max(te, ts + 0.05), 3),
                            "media_id": c.media_id, "src_start": w["start"], "src_end": w["end"],
                            "p": w.get("p", 1.0)})
    out.sort(key=lambda w: w["start"])
    return out


def transcript_status(project: Project, project_dir: Path) -> dict:
    ids = {c.media_id for t in project.timeline.tracks if t.kind == "audio" for c in t.clips}
    have = [m for m in ids if (load_analysis(project_dir, m) or {}).get("words") is not None]
    return {"media_in_edit": len(ids), "transcribed": len(have), "missing": sorted(ids - set(have))}


def suggest_censors(project: Project, project_dir: Path, *, sound: str = "beep", level: str = "strong",
                    custom: Iterable[str] = (), allow: Iterable[str] = (), padding: float = 0.06,
                    sound_asset: Optional[str] = None) -> list[Effect]:
    words = []
    for mid in {c.media_id for t in project.timeline.tracks for c in t.clips}:
        a = load_analysis(project_dir, mid)
        ws = (a or {}).get("words") or []
        words += [(mid, i, ws) for i in range(len(ws))]
    media = project.media_by_id()
    out = []
    for mid, i, ws in words:
        w = ws[i]
        if not is_profane(w["text"], level, custom, allow):
            continue
        start = max(0.0, w["start"] - padding)
        end = min(media[mid].duration, w["end"] + padding)
        dur = max(0.08, end - start)
        p = float(w.get("p", 1.0))
        ctx = " ".join(x["text"].strip() for x in ws[max(0, i - 4): i + 5])
        review = p < 0.6 or (w["end"] - w["start"]) < 0.12
        out.append(Effect(id=new_id(), kind="censor", media_id=mid, source_time=round(start, 3),
                          duration=round(min(dur, 30), 3), origin="auto", sound=sound, volume=0.7,
                          sound_asset=sound_asset if sound == "custom" else None,
                          word=w["text"].strip()[:60], context=ctx[:160], confidence=round(p, 3),
                          needs_review=review))
    return out


REACTION_TEXT = {"question": ["WAIT WHAT?", "HUH?!", "WHAT?!"], "no": ["NOPE", "NO NO NO"],
                 "laugh": ["LOL", "HAHA"], "default": ["BRUH", "NO WAY", "OH NO", "OMG", "WHAT?!"]}
INTENSITY = {"minimal": dict(gap=45.0, zoom=1.15, text_every=3, sfx=False),
             "balanced": dict(gap=15.0, zoom=1.22, text_every=2, sfx=True),
             "chaotic": dict(gap=6.0, zoom=1.35, text_every=1, sfx=True)}


def suggest_fun(project: Project, project_dir: Path, intensity: str = "balanced") -> list[Effect]:
    """Place punch-ins, shakes, pop-up text and SFX on the loudest reactions in
    the FINAL edit, spaced by intensity. Deterministic; never inserts images."""
    cfg = INTENSITY[intensity]
    D = project.timeline.duration
    cands: list[tuple[float, float, float]] = []  # (timeline t, strength 0..1, loud db)
    for track in [t for t in project.timeline.tracks if t.kind == "audio" and not t.muted]:
        for c in track.clips:
            a = load_analysis(project_dir, c.media_id)
            rms = np.asarray((a or {}).get("rms_db") or [], dtype=np.float32)
            if rms.size < 10:
                continue
            hop = a["hop"]
            # "loud" = well above the typical level; capped so that frequent reactions
            # (which raise the 90th percentile themselves) still count
            p90 = min(float(np.percentile(rms, 90)), float(np.median(rms)) + 12)
            seg = rms[int(c.source_in / hop): int(c.source_out / hop)]
            if seg.size < 5:
                continue
            # local maxima above the recording's 90th percentile + 3 dB
            thr = p90 + 3
            k = 0
            while k < seg.size:
                if seg[k] > thr:
                    j = k
                    while j < seg.size and seg[j] > thr - 4:
                        j += 1
                    peak = k + int(np.argmax(seg[k:j]))
                    src_t = c.source_in + peak * hop
                    tl = c.start + (src_t - c.source_in) / c.speed
                    strength = float((rms < seg[peak]).mean())
                    cands.append((tl, strength, float(seg[peak])))
                    k = j + int(1.0 / hop)
                else:
                    k += 1
    cands.sort(key=lambda x: (-x[1], x[0]))
    censored = [(w.start, w.end) for e in project.effects if e.kind == "censor" and e.enabled
                for w in map_to_timeline(project, e, "audio")]
    chosen: list[tuple[float, float, float]] = []
    for cnd in cands:
        if all(abs(cnd[0] - c[0]) >= cfg["gap"] for c in chosen) and 0.3 < cnd[0] < D - 0.5:
            chosen.append(cnd)
    chosen.sort(key=lambda x: x[0])
    words = edit_words(project, project_dir)
    effects: list[Effect] = []
    for n, (t, strength, _db) in enumerate(chosen):
        hit = timeline_to_source(project, t - 0.05)
        if hit is None:
            continue
        mid, src, clip = hit
        near = " ".join(w["text"].lower() for w in words if abs(w["start"] - t) < 1.5)
        dur_zoom = 0.9 if strength > 0.97 else 1.4
        effects.append(Effect(id=new_id(), kind="zoom", media_id=mid, source_time=round(max(0, src - 0.05), 3),
                              duration=dur_zoom, origin="auto", scale=cfg["zoom"] + (0.08 if strength > 0.985 else 0)))
        if strength > 0.985 and intensity != "minimal":
            effects.append(Effect(id=new_id(), kind="shake", media_id=mid, source_time=round(max(0, src), 3),
                                  duration=0.5, origin="auto", intensity=0.6))
        if n % cfg["text_every"] == 0 and not any(
                x.kind == "text" and abs(x.source_time - src) < 1.6 and x.media_id == mid for x in effects):
            bucket = ("question" if re.search(r"\b(what|why|how|huh)\b", near) else
                      "no" if re.search(r"\b(no|nope|nah)\b", near) else
                      "laugh" if re.search(r"\b(haha|lol|lmao)\b", near) else "default")
            pool = REACTION_TEXT[bucket]
            effects.append(Effect(id=new_id(), kind="text", media_id=mid, source_time=round(max(0, src - 0.05), 3),
                                  duration=1.3, origin="auto", text=pool[n % len(pool)],
                                  x=0.5 if n % 3 == 0 else (0.28 if n % 3 == 1 else 0.72), y=0.22, size=0.13,
                                  color="#ffde00" if n % 2 else "#ffffff"))
        if cfg["sfx"] and not any(a - 0.3 < t < b + 0.3 for a, b in censored):
            effects.append(Effect(id=new_id(), kind="sfx", media_id=mid, source_time=round(max(0, src - 0.05), 3),
                                  duration=0.6, origin="auto", sound="boom" if strength > 0.985 else "pop",
                                  volume=0.6))
    return effects


# ---------------------------------------------------------------- sound synthesis
def synth_expr(sound: str, dur: float) -> str:
    D = max(dur, 0.05)
    exprs = {
        "beep": "0.45*sin(2*PI*1000*t)",
        "mute": "0",
        "boing": f"0.55*sin(2*PI*(180*t+30*(1-cos(2*PI*6*t))*exp(-2.5*t)))*exp(-1.8*t/{D})",
        "scratch": "0.5*(random(0)*2-1)*abs(sin(2*PI*7*t))*sin(2*PI*(400+1200*abs(sin(2*PI*5*t)))*t)",
        "honk": "0.22*(sgn(sin(2*PI*370*t))+sgn(sin(2*PI*466*t)))",
        "quack": "0.35*(2*(t*230-floor(t*230))-1)*abs(sin(2*PI*4*t))*(1+0.5*sin(2*PI*900*t))",
        "boom": "0.9*sin(2*PI*(55*t+12*(1-exp(-9*t))))*exp(-3.5*t)",
        "whoosh": f"0.45*(random(0)*2-1)*sin(PI*t/{D})",
        "ding": "0.45*sin(2*PI*1320*t)*exp(-5*t)+0.2*sin(2*PI*2640*t)*exp(-7*t)",
        "pop": "0.8*sin(2*PI*(700*t-300*t*t))*exp(-28*t)",
        "airhorn": "0.16*(sgn(sin(2*PI*440*t))+sgn(sin(2*PI*554*t))+sgn(sin(2*PI*659*t)))",
    }
    return exprs[sound]


def sound_input_args(sound: str, samples: int, volume: float, rate: int) -> list[str]:
    """FFmpeg input + filter args producing exactly ``samples`` stereo samples."""
    dur = samples / rate
    fade = min(0.008, dur / 4)
    return ["-f", "lavfi", "-i", f"aevalsrc={synth_expr(sound, dur)}:s={rate}:d={dur + 0.05:.4f}",
            "-af", f"afade=t=in:d={fade:.4f},afade=t=out:st={max(0.0, dur - fade):.4f}:d={fade:.4f},"
                   f"volume={volume:.3f},aformat=sample_fmts=s16:channel_layouts=stereo,apad,"
                   f"atrim=end_sample={samples}",
            "-ac", "2"]


def sound_args(sound: str, samples: int, volume: float, rate: int, dest: Path,
               file: Optional[Path] = None) -> list[str]:
    """``file``: a custom sound (WAV made by the library) — played from its start,
    cut to the window with a short fade so it never clicks."""
    if file is None:
        return sound_input_args(sound, samples, volume, rate) + ["-c:a", "pcm_s16le", str(dest)]
    dur = samples / rate
    fade = min(0.01, dur / 4)
    return ["-i", str(file), "-af",
            f"aresample={rate},aformat=sample_fmts=s16:channel_layouts=stereo,atrim=end_sample={samples},"
            f"afade=t=out:st={max(0.0, dur - fade):.4f}:d={fade:.4f},volume={volume:.3f},apad,"
            f"atrim=end_sample={samples}", "-ac", "2", "-c:a", "pcm_s16le", str(dest)]


# ---------------------------------------------------------------- graphics
FONT_CANDIDATES = [
    "C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/Library/Fonts/Impact.ttf", "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def find_font() -> Optional[str]:
    env = os.environ.get("CLIPFORGE_FONT")
    if env and Path(env).is_file():
        return env
    return next((f for f in FONT_CANDIDATES if Path(f).is_file()), None)


def text_png(text: str, px: int, color: str, dest: Path) -> tuple[int, int]:
    """Bold outlined pop-up text as a transparent PNG; returns its size."""
    from PIL import Image, ImageDraw, ImageFont
    font_path = find_font()
    font = ImageFont.truetype(font_path, px) if font_path else ImageFont.load_default(size=px)
    stroke = max(2, px // 12)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font, stroke_width=stroke)
    pad = stroke + px // 6
    w, h = r - l + pad * 2, b - t + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # soft drop shadow, then outlined text
    d.text((pad - l + px // 18, pad - t + px // 14), text, font=font, fill=(0, 0, 0, 140),
           stroke_width=stroke, stroke_fill=(0, 0, 0, 140))
    d.text((pad - l, pad - t), text, font=font, fill=color, stroke_width=stroke, stroke_fill="#000000")
    img.save(dest)
    return w, h


def image_png(src: Path, width: int, dest: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGBA")
        h = max(2, int(im.height * width / im.width))
        im.resize((width, h), Image.LANCZOS).save(dest)
        return width, h


# ---------------------------------------------------------------- captions (ASS)
def _ass_color(hex_: str, alpha: int = 0) -> str:
    r, g, b = hex_[1:3], hex_[3:5], hex_[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def caption_chunks(project: Project, project_dir: Path) -> list[dict]:
    """Group final-edit words into short caption lines; censored words are masked."""
    cs = project.captions
    words = edit_words(project, project_dir)
    censor = [(w.start, w.end) for e in project.effects if e.kind == "censor" and e.enabled
              for w in map_to_timeline(project, e, "audio")]
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        if any(a - 0.02 <= mid <= b + 0.02 for a, b in censor):
            w["text"] = mask_word(w["text"].strip())
    chunks: list[dict] = []
    cur: list[dict] = []
    for w in words:
        txt = w["text"].strip()
        if not txt:
            continue
        brk = cur and (len(cur) >= cs.max_words or w["start"] - cur[-1]["end"] > 0.6
                       or cur[-1]["text"].strip()[-1:] in ".?!")
        if brk:
            chunks.append({"words": cur})
            cur = []
        cur.append({**w, "text": txt.upper() if cs.uppercase else txt})
    if cur:
        chunks.append({"words": cur})
    for i, c in enumerate(chunks):
        c["start"] = c["words"][0]["start"]
        end = c["words"][-1]["end"] + 0.25
        if i + 1 < len(chunks):
            end = min(end, chunks[i + 1]["words"][0]["start"])
        c["end"] = max(end, c["start"] + 0.3)
        c["text"] = " ".join(w["text"] for w in c["words"])
    return chunks


def captions_ass(project: Project, chunks: list[dict], font_family: str, H: int, W: int) -> str:
    cs = project.captions
    size = int(H * cs.size)
    align = {"bottom": 2, "middle": 5, "top": 8}[cs.position]
    margin = int(H * (0.08 if cs.position != "middle" else 0))
    border, outline, back = (3, max(2, size // 10), "&H90000000") if cs.style == "clean" else (1, max(3, size // 9), "&H64000000")
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,{font_family},{size},{_ass_color(cs.color)},{_ass_color(cs.highlight)},&H00000000,{back},"
            f"-1,0,0,0,100,100,0,0,{border},{outline},{0 if cs.style == 'clean' else 2},{align},{int(W*0.06)},{int(W*0.06)},{margin},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    esc = lambda s: s.replace("\\", "").replace("{", "(").replace("}", ")")  # noqa: E731
    for c in chunks:
        if cs.style == "highlight":
            for i, w in enumerate(c["words"]):
                st = w["start"] if i else c["start"]
                en = c["words"][i + 1]["start"] if i + 1 < len(c["words"]) else c["end"]
                parts = [(f"{{\\c{_ass_color(cs.highlight)}}}{esc(x['text'])}{{\\c{_ass_color(cs.color)}}}" if j == i
                          else esc(x["text"])) for j, x in enumerate(c["words"])]
                lines.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(max(en, st + 0.05))},Cap,,0,0,0,,{' '.join(parts)}")
        elif cs.style == "bold_pop":
            pop = "{\\fad(40,60)\\fscx80\\fscy80\\t(0,90,\\fscx112\\fscy112)\\t(90,170,\\fscx100\\fscy100)}"
            lines.append(f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Cap,,0,0,0,,{pop}{esc(c['text'])}")
        else:
            lines.append(f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Cap,,0,0,0,,{{\\fad(60,60)}}{esc(c['text'])}")
    return head + "\n".join(lines) + "\n"


def captions_srt(chunks: list[dict]) -> str:
    def ts(t: float) -> str:
        ms = int(round(max(0.0, t) * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n" for i, c in enumerate(chunks, 1))


def prepare_caption_font(work: Path) -> Optional[str]:
    """Copy a real font into the work dir so libass can use it on any OS; return its family."""
    f = find_font()
    if not f:
        return None
    dst = work / ("capfont" + Path(f).suffix.lower())
    shutil.copyfile(f, dst)
    try:
        from PIL import ImageFont
        return ImageFont.truetype(str(dst), 20).getname()[0]
    except Exception:  # noqa: BLE001
        return None
