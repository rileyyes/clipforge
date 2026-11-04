"""AI Auto Editor decision engine.

Pipeline (deterministic — same analysis + settings → same edit):

1. **Sound regions**: frames louder than an adaptive threshold (between the noise
   floor and typical speech level). Gaps shorter than the preset's minimum
   silence are kept (natural pauses are never all removed).
2. **Pacing**: each region is padded by the preset's retained pause, so breaths
   and rhythm survive. Silence removal can be turned off.
3. **Beats**: regions separated by short gaps are grouped into "beats" (a
   sentence/exchange/moment), split at the longest internal pause if too long.
   Beats are the unit of selection, so cuts land at natural boundaries and never
   mid-word (a beat only ends in silence, or on a word boundary with a transcript).
4. **Scoring**: per-beat features (loudness, reaction spikes, talking density,
   on-screen motion, scene cuts, speech rate with transcript) → percentile-ranked →
   weighted by the chosen style. Every score comes with human-readable reasons.
5. **Duration planning**: pick highest-scoring beats that fit the target, honour
   forced include/exclude, keep the opening hook if asked, then add *setup* beats
   that directly precede chosen ones (context) while room remains. Output is in
   chronological order.
6. **Validation**: the edit decision list (EDL) is checked (sorted, inside the
   media, non-overlapping, minimum length) before it can touch a timeline.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, Field

from . import language
from .schema import MIN_CLIP_DURATION

SilencePreset = Literal["off", "conservative", "balanced", "aggressive"]
Style = Literal["balanced", "excitement", "information", "reactions", "action", "humor", "story"]

SILENCE = {  # min silence to cut (s), pause kept on each side (s), merge-into-beat gap (s)
    "off": None,
    "conservative": dict(min_silence=1.2, keep=0.35, beat_gap=2.5),
    "balanced": dict(min_silence=0.7, keep=0.22, beat_gap=1.8),
    "aggressive": dict(min_silence=0.4, keep=0.12, beat_gap=1.2),
}

# feature weights per style
# Language features (laughs, punchlines, exclaim, questions, story; see language.py) only
# exist with a transcript, and "ai" only with the optional local AI rating. Missing
# features simply drop out of a beat's weighted average.
STYLES: dict[str, dict[str, float]] = {
    "balanced": dict(loudness=1, reactions=1, density=1, motion=1, cuts=0.5, speech_rate=0.5,
                     laughs=0.7, punchlines=0.7, exclaim=0.5, questions=0.3, story=0.3, ai=2.0),
    "excitement": dict(loudness=1.5, reactions=2, density=0.3, motion=1.2, cuts=0.6, speech_rate=0.6,
                       laughs=0.6, punchlines=0.8, exclaim=1.5, questions=0.2, story=0.1, ai=1.5),
    "information": dict(loudness=0.5, reactions=0.3, density=2.5, motion=0.3, cuts=0.2, speech_rate=1.5,
                        laughs=0.1, punchlines=0.2, exclaim=0.1, questions=1.0, story=0.8, ai=2.5),
    "reactions": dict(loudness=1, reactions=3, density=0.4, motion=0.6, cuts=0.3, speech_rate=0.3,
                      laughs=1.5, punchlines=1.0, exclaim=2.0, questions=0.2, story=0.1, ai=1.5),
    "action": dict(loudness=0.6, reactions=0.6, density=0.3, motion=2.5, cuts=1.5, speech_rate=0.2,
                   laughs=0.2, punchlines=0.2, exclaim=0.5, questions=0.1, story=0.1, ai=1.0),
    # humor/story genuinely need language understanding; without a transcript they
    # fall back to the closest signals and say so in the warnings.
    "humor": dict(loudness=0.8, reactions=2.0, density=0.6, motion=0.4, cuts=0.3, speech_rate=0.8,
                  laughs=3.0, punchlines=3.0, exclaim=1.0, questions=0.5, story=0.3, ai=3.0),
    "story": dict(loudness=0.6, reactions=0.6, density=2.0, motion=0.4, cuts=0.3, speech_rate=1.0,
                  laughs=0.5, punchlines=1.0, exclaim=0.3, questions=1.0, story=3.0, ai=3.0),
}

MAX_BEAT = 45.0
MIN_BEAT = 1.0


class AutoEditSettings(BaseModel):
    target_mode: Literal["original", "duration", "percent"] = "duration"
    target_seconds: float = Field(default=600, gt=0, le=24 * 3600)
    target_percent: float = Field(default=50, gt=0, le=100)
    style: Style = "balanced"
    silence: SilencePreset = "balanced"
    keep_opening: bool = True
    context: bool = True  # add setup beats before chosen moments
    include: list[int] = Field(default_factory=list, max_length=20000)
    exclude: list[int] = Field(default_factory=list, max_length=20000)


@dataclass
class Beat:
    id: int
    start: float
    end: float
    regions: list[tuple[float, float]]
    features: dict[str, float] = field(default_factory=dict)
    ranks: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    ai_why: Optional[str] = None
    selected: bool = False
    why: str = ""

    @property
    def kept(self) -> float:
        return sum(b - a for a, b in self.regions)


# ---------------------------------------------------------------- regions & beats
def sound_regions(rms_db: list[float], hop: float, duration: float,
                  preset: Optional[dict]) -> tuple[list[tuple[float, float]], dict]:
    a = np.asarray(rms_db, dtype=np.float32)
    if a.size == 0:
        return [(0.0, duration)], {"threshold_db": None, "noise_db": None, "speech_db": None}
    noise = float(np.percentile(a, 10))
    speech = float(np.percentile(a, 90))
    thr = noise + 0.3 * (speech - noise)
    if speech - noise < 6:  # flat audio (music, constant noise, silence): no reliable pauses
        thr = noise - 1
    thr = min(thr, -18.0)
    info = {"threshold_db": round(thr, 1), "noise_db": round(noise, 1), "speech_db": round(speech, 1)}
    if preset is None:
        return [(0.0, duration)], info
    on = a > thr
    regions: list[list[float]] = []
    i, n = 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            regions.append([i * hop, min(duration, j * hop)])
            i = j
        else:
            i += 1
    # bridge gaps shorter than the minimum silence (natural pauses stay)
    merged: list[list[float]] = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < preset["min_silence"]:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    merged = [r for r in merged if r[1] - r[0] >= 0.15]  # drop clicks
    keep = preset["keep"]
    padded: list[tuple[float, float]] = []
    for st, en in merged:
        s2, e2 = round(max(0.0, st - keep), 3), round(min(duration, en + keep), 3)
        if padded and s2 <= padded[-1][1]:
            padded[-1] = (padded[-1][0], max(padded[-1][1], e2))
        else:
            padded.append((s2, e2))
    return padded, info


def snap_to_words(regions: list[tuple[float, float]], words: Optional[list[dict]],
                  duration: float) -> list[tuple[float, float]]:
    """Never cut through a word: extend region edges to cover any word they intersect."""
    if not words:
        return regions
    out = []
    for s, e in regions:
        for w in words:
            if w["start"] < s < w["end"]:
                s = max(0.0, w["start"] - 0.05)
            if w["start"] < e < w["end"]:
                e = min(duration, w["end"] + 0.05)
        out.append((round(s, 3), round(e, 3)))
    # re-merge anything that now touches
    merged: list[tuple[float, float]] = []
    for s, e in out:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def make_beats(regions: list[tuple[float, float]], beat_gap: float, max_beat: float = MAX_BEAT,
               rms: Optional[np.ndarray] = None, hop: float = 0.05) -> list[Beat]:
    """Group regions into beats. Groups longer than ``max_beat`` are split at their
    longest pause. A single continuous region is only split when it exceeds the
    hard MAX_BEAT cap, and then at its quietest moment — never at an arbitrary time."""
    def quiet_split(s: float, e: float) -> list[tuple[float, float]]:
        if e - s <= MAX_BEAT:
            return [(s, e)]
        lo, hi = s + (e - s) * 0.25, s + (e - s) * 0.75
        if rms is not None and rms.size:
            seg = rms[int(lo / hop): int(hi / hop)]
            cut = lo + float(np.argmin(seg)) * hop if seg.size else (s + e) / 2
        else:
            cut = (s + e) / 2
        cut = round(cut, 3)
        return quiet_split(s, cut) + quiet_split(cut, e)

    pieces = [p for r in regions for p in quiet_split(*r)]
    groups: list[list[tuple[float, float]]] = []
    for r in pieces:
        gap = r[0] - groups[-1][-1][1] if groups else None
        # gap == 0 only between the halves of a quiet split: those become separate beats
        if gap is not None and 0 < gap <= beat_gap:
            groups[-1].append(r)
        else:
            groups.append([r])

    def split(g: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
        if g[-1][1] - g[0][0] <= max_beat or len(g) == 1:
            return [g]
        gaps = [g[k + 1][0] - g[k][1] for k in range(len(g) - 1)]
        k = int(np.argmax(gaps))
        return split(g[: k + 1]) + split(g[k + 1:])

    out: list[Beat] = []
    for g in groups:
        for part in split(g):
            out.append(Beat(id=len(out), start=part[0][0], end=part[-1][1], regions=part))
    return out


# ---------------------------------------------------------------- scoring
def _slice(arr: np.ndarray, s: float, e: float, hop: float) -> np.ndarray:
    return arr[int(s / hop): max(int(s / hop) + 1, int(math.ceil(e / hop)))]


def tie_aware_ranks(v: np.ndarray) -> np.ndarray:
    """Percentile rank in [0, 1]; equal values share their average rank (so position
    in the recording never breaks ties)."""
    order = v.argsort(kind="stable")
    pos = np.empty(len(v), dtype=np.float64)
    pos[order] = np.arange(len(v))
    for u in np.unique(v):
        m = v == u
        pos[m] = pos[m].mean()
    return pos / (len(v) - 1)


def score_beats(beats: list[Beat], analysis: dict, style: str, thr_info: dict) -> None:
    hop = analysis["hop"]
    rms = np.asarray(analysis.get("rms_db") or [], dtype=np.float32)
    motion = np.asarray(analysis.get("motion") or [], dtype=np.float32)
    cuts = np.asarray(analysis.get("cuts") or [], dtype=np.float32)
    words = analysis.get("words")
    events = language.word_events(words, analysis.get("rms_db") or [], hop) if words else None
    ratings = analysis.get("ai_ratings") or []
    speech_db = thr_info.get("speech_db")
    thr = thr_info.get("threshold_db")
    for b in beats:
        span = max(b.end - b.start, 1e-6)
        r = np.concatenate([_slice(rms, s, e, hop) for s, e in b.regions]) if rms.size else np.array([])
        f: dict[str, float] = {}
        if r.size:
            voiced = r[r > thr] if thr is not None else r
            f["loudness"] = float(np.mean(voiced)) if voiced.size else -90.0
            spike = (speech_db if speech_db is not None else float(np.max(rms))) + 4
            f["reactions"] = float(np.sum(r > spike)) * hop / span * 60  # loud seconds per minute
            f["density"] = float(voiced.size * hop / span)
        m = _slice(motion, b.start, b.end, hop) if motion.size else np.array([])
        if m.size:
            f["motion"] = float(np.mean(m))
            f["cuts"] = float(np.sum((cuts >= b.start) & (cuts < b.end))) / span * 60
        ai_why = None
        if words:
            n = sum(1 for w in words if b.start <= w["start"] < b.end)
            f["speech_rate"] = n / span * 60
            f.update(language.beat_features(events, b.start, b.end))
        if ratings:
            hit = language.ai_feature(ratings, b.start, b.end)
            if hit is not None:
                f["ai"], ai_why = hit
        b.features = {k: round(v, 3) for k, v in f.items()}
        b.ai_why = ai_why
    # percentile ranks across beats (robust to scale); single beat → 0.5
    keys = sorted({k for b in beats for k in b.features})
    weights = STYLES[style]
    for k in keys:
        vals = np.array([b.features.get(k, np.nan) for b in beats], dtype=np.float64)
        ok = ~np.isnan(vals)
        if ok.sum() <= 1:
            for b in beats:
                if k in b.features:
                    b.ranks[k] = 0.5
            continue
        ranks = tie_aware_ranks(vals[ok])
        for b, rk in zip([b for b, o in zip(beats, ok) if o], ranks):
            b.ranks[k] = round(float(rk), 3)
    for b in beats:
        if "ai" in b.features:  # an absolute 0-10 judgement: use it as is, not its rank
            b.ranks["ai"] = round(min(1.0, max(0.0, b.features["ai"] / 10)), 3)
        num = sum(weights.get(k, 0) * v for k, v in b.ranks.items())
        den = sum(weights.get(k, 0) for k in b.ranks) or 1
        # very short beats rarely stand alone well
        brevity = min(1.0, 0.6 + 0.4 * b.kept / 6.0)
        b.score = round(100 * num / den * brevity, 1)
        b.reasons = explain(b, weights)
        if b.ai_why and b.features.get("ai", 0) >= 6:
            b.reasons = [f"AI: {b.ai_why} ({b.features['ai']:.0f}/10)"] + b.reasons[:1]


LABELS = {
    "loudness": ("energetic, loud delivery", "quiet section"),
    "reactions": ("big reactions / loud spikes", "no strong reactions"),
    "density": ("continuous talking, little dead air", "lots of pauses"),
    "motion": ("lots of on-screen movement", "static picture"),
    "cuts": ("fast visual changes", "no scene changes"),
    "speech_rate": ("fast, dense speech", "slow speech"),
    "laughs": ("laughter", "no laughs"),
    "punchlines": ("punchline: setup then payoff", "no payoff moments"),
    "exclaim": ("exclamations & reactions in the words", "calm wording"),
    "questions": ("questions / set-ups", "no questions"),
    "story": ("storytelling", "no story markers"),
    "ai": ("AI rates it highly", "AI rates it low"),
}


def explain(b: Beat, weights: dict[str, float]) -> list[str]:
    contrib = sorted(((weights.get(k, 0) * (v - 0.5), k, v) for k, v in b.ranks.items() if k != "ai"),
                     reverse=True)
    out = []
    for c, k, v in contrib[:2]:
        if v >= 0.7 and c > 0:
            out.append(f"{LABELS[k][0]} (top {max(1, round((1 - v) * 100))}%)")
    for c, k, v in contrib[::-1][:1]:
        if v <= 0.25 and c < 0:
            out.append(f"{LABELS[k][1]}")
    return out or ["average across signals"]


# ---------------------------------------------------------------- planning
def plan(analysis: dict, s: AutoEditSettings) -> dict:
    duration = float(analysis["duration"])
    preset = SILENCE[s.silence]
    regions, thr_info = sound_regions(analysis.get("rms_db") or [], analysis["hop"], duration, preset)
    regions = snap_to_words(regions, analysis.get("words"), duration)
    if not analysis.get("rms_db"):
        # no audio: there are no words to protect, so split at scene cuts, then into
        # even windows, giving the planner pieces it can actually choose between
        bounds = [0.0] + [c for c in (analysis.get("cuts") or []) if 0 < c < duration] + [duration]
        regions = []
        for a, b in zip(bounds, bounds[1:]):
            n = max(1, math.ceil((b - a) / 5.0))
            regions += [(round(a + (b - a) * k / n, 3), round(a + (b - a) * (k + 1) / n, 3)) for k in range(n)]
    usable_est = sum(e - a for a, e in regions)
    if s.target_mode == "original":
        target = usable_est
    elif s.target_mode == "percent":
        target = duration * s.target_percent / 100
    else:
        target = s.target_seconds
    # moment size adapts to the target: a 60 s short needs finer pieces than a 30 min cut.
    # Splits only ever happen at pauses, never inside a sound region (except one
    # continuous region longer than the limit, which is split evenly).
    max_beat = max(4.0, min(MAX_BEAT, target / 4))
    beats = make_beats(regions, preset["beat_gap"] if preset else 2.0, max_beat,
                       np.asarray(analysis.get("rms_db") or [], dtype=np.float32), analysis["hop"])
    score_beats(beats, analysis, s.style, thr_info)
    warnings: list[str] = []
    if s.style in ("humor", "story") and not analysis.get("words"):
        warnings.append(f"'{s.style}' works best with a transcript; without one it's approximated "
                        "from reactions and talking density.")
    if not analysis.get("rms_db"):
        warnings.append("This media has no audio, so pauses can't be detected; selection uses motion only.")

    usable = sum(b.kept for b in beats)
    if s.target_mode == "original":
        target = usable

    include, exclude = set(s.include), set(s.exclude)
    chosen: set[int] = set()
    total = 0.0

    def take(b: Beat, why: str) -> None:
        nonlocal total
        chosen.add(b.id)
        b.why = why
        total += b.kept

    for b in beats:
        if b.id in include and b.id not in exclude:
            take(b, "included by you")
    if s.keep_opening and beats and beats[0].id not in exclude and beats[0].id not in chosen:
        if total + beats[0].kept <= target * 1.02:
            take(beats[0], "opening hook")
    slack = 1.02
    ranked = sorted((b for b in beats if b.id not in chosen and b.id not in exclude),
                    key=lambda b: (-b.score, b.start))
    for b in ranked:
        if b.kept < MIN_BEAT:
            continue
        if total + b.kept <= target * slack:
            take(b, "high score")
    if s.context:
        # add the beat right before a chosen one (setup → payoff) while room remains
        changed = True
        while changed:
            changed = False
            for b in beats:
                if b.id in chosen or b.id in exclude:
                    continue
                nxt = beats[b.id + 1] if b.id + 1 < len(beats) else None
                if nxt and nxt.id in chosen and nxt.start - b.end < 3.0 and total + b.kept <= target * slack:
                    take(b, f"setup for #{nxt.id + 1}")
                    changed = True
    for b in beats:
        b.selected = b.id in chosen
        if not b.selected:
            b.why = ("excluded by you" if b.id in exclude else
                     "too short to stand alone" if b.kept < MIN_BEAT else
                     "didn't fit the target length" if total + b.kept > target * slack else
                     "lower score than chosen moments")

    segments = []
    for b in sorted((b for b in beats if b.selected), key=lambda b: b.start):
        for a, e in b.regions:
            if segments and a - segments[-1]["source_out"] < 0.02 and segments[-1]["beat"] == b.id:
                segments[-1]["source_out"] = e
            elif e - a >= MIN_CLIP_DURATION:
                segments.append({"source_in": a, "source_out": e, "beat": b.id})
    validate_edl(segments, duration)
    out_dur = round(sum(x["source_out"] - x["source_in"] for x in segments), 3)

    if s.target_mode != "original" and target > usable + 1:
        warnings.append(f"The target ({fmt(target)}) is longer than the usable content after removing "
                        f"dead air ({fmt(usable)}). The edit will be {fmt(out_dur)}.")
    elif s.target_mode != "original" and out_dur < target * 0.85 and usable > target:
        warnings.append(f"Could only reach {fmt(out_dur)} of {fmt(target)} without cutting moments "
                        "mid-sentence. Include more moments by hand or raise the target.")
    if s.target_mode != "original" and usable > 0 and target / usable < 0.08:
        warnings.append(f"Keeping only {target / usable:.0%} of the usable content is very aggressive; "
                        "expect a highlight reel rather than a coherent story.")
    if not beats:
        warnings.append("No sound was detected above the noise floor, so nothing could be selected.")

    return {
        "source_duration": duration,
        "usable_duration": round(usable, 3),
        "target_duration": round(target, 3),
        "output_duration": out_dur,
        "dead_air_removed": round(duration - usable, 3),
        "levels": thr_info,
        "beats": [_beat_json(b) for b in beats],
        "segments": segments,
        "warnings": warnings,
        "settings": s.model_dump(),
        "transcript": bool(analysis.get("words")),
    }


def _beat_json(b: Beat) -> dict:
    return {"id": b.id, "start": round(b.start, 3), "end": round(b.end, 3), "kept": round(b.kept, 3),
            "score": b.score, "reasons": b.reasons, "selected": b.selected, "why": b.why,
            "features": b.features}


def fmt(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


class EDLError(ValueError):
    pass


def validate_edl(segments: list[dict], duration: float) -> None:
    prev = -1.0
    for seg in segments:
        a, b = seg["source_in"], seg["source_out"]
        if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
            raise EDLError("segment times must be numbers")
        if math.isnan(a) or math.isnan(b) or a < 0 or b > duration + 0.01:
            raise EDLError(f"segment {a}-{b} is outside the media (0-{duration})")
        if b - a < MIN_CLIP_DURATION - 1e-9:
            raise EDLError(f"segment {a}-{b} is too short")
        if a < prev - 1e-6:
            raise EDLError("segments overlap or are out of order")
        prev = b


def edl_to_timeline(project: dict, media: dict, segments: list[dict], new_id) -> dict:
    """Replace the project's timeline with the EDL as linked V1/A1 clips."""
    tracks = project["timeline"]["tracks"]
    v = next((t for t in tracks if t["kind"] == "video"), None)
    a = next((t for t in tracks if t["kind"] == "audio"), None)
    for t in tracks:
        t["clips"] = []
        t["locked"] = False
    t0 = 0.0
    for seg in segments:
        link = new_id() if (media["has_video"] and media["has_audio"]) else None
        dur = round(seg["source_out"] - seg["source_in"], 6)
        base = {"media_id": media["id"], "start": round(t0, 6), "source_in": seg["source_in"],
                "source_out": seg["source_out"], "speed": 1.0, "volume": 1.0, "link_id": link,
                "label": None, "transform": {"x": 0, "y": 0, "scale": 1, "rotation": 0}}
        if media["has_video"] and v is not None:
            v["clips"].append({**base, "id": new_id()})
        if media["has_audio"] and a is not None:
            a["clips"].append({**base, "id": new_id()})
        t0 += dur
    return project


__all__ = ["AutoEditSettings", "plan", "validate_edl", "edl_to_timeline", "EDLError", "asdict"]
