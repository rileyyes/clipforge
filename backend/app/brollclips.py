"""B-roll from your own recordings (Phase 16).

When you say something in the edit ("…then the dragon showed up"), find a moment in your
OTHER recordings in this project where the same word comes up, and suggest showing a few
seconds of it over the main video right there. Matching is by words in the transcripts
(rarer words count more), so both recordings need transcribing. Local and rule-based.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from .analysis import load_analysis
from .effects import edit_words
from .schema import Project

STOP = set("""a about after again all also am an and any are as at be because been before being but by can could did do does
doing don dont down during each few for from further get got had has have having he her here hers him his how i if in into
is it its itself just like me more most my no nor not now of off on once only or other our out over own really right same
say said see she should so some such than that the their them then there these they thing things this those through to too
under until up very was we were what when where which while who why will with would yeah yes you your okay ok gonna wanna
going know think mean actually little lot well um uh oh hey guys""".split())
CLIP = 3.0          # seconds of B-roll per suggestion
SPACING = 6.0       # at least this far apart
MAX = 10


def norm(w: str) -> str:
    """Plain word form for matching: castles/castle, dragons/dragon, parties/party, boxes/box."""
    t = re.sub(r"[^a-z0-9']", "", w.lower()).strip("'")
    if t.endswith("'s"):
        t = t[:-2]
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("es") and t[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def suggest(p: Project, project_dir: Path) -> dict:
    words = edit_words(p, project_dir)
    if not words:
        return {"suggestions": [], "note": "Transcribe the main recording first (FX tab → 1 · Transcript)."}
    v1 = next((t for t in p.timeline.tracks if t.kind == "video"), None)
    main_ids = {c.media_id for c in (v1.clips if v1 else [])}
    media = {m.id: m for m in p.media}
    others: dict[str, list[dict]] = {}
    for m in p.media:
        if m.id in main_ids or not m.has_video:
            continue
        a = load_analysis(project_dir, m.id)
        if a and a.get("words"):
            others[m.id] = a["words"]
    if not others:
        no_t = [m.original_name for m in p.media if m.id not in main_ids and m.has_video]
        return {"suggestions": [], "note": ("Import your other recordings and transcribe them too (Media panel, then FX → Transcript)."
                                            if not no_t else f"Transcribe your other recordings first: {', '.join(no_t[:3])}.")}
    # how rare each word is across everything (rarer = a better match)
    df = Counter()
    docs = [[norm(w["text"]) for w in words]] + [[norm(w["text"]) for w in ws] for ws in others.values()]
    for d in docs:
        df.update(set(d))
    idf = {k: math.log((1 + len(docs)) / (1 + v)) + 1 for k, v in df.items()}
    index: dict[str, list[tuple[str, dict]]] = {}
    for mid, ws in others.items():
        for w in ws:
            k = norm(w["text"])
            if len(k) >= 4 and k not in STOP:
                index.setdefault(k, []).append((mid, w))
    # existing overlays: don't suggest on top of them
    busy = [(c.start, c.start + (c.source_out - c.source_in) / c.speed) for t in p.timeline.tracks
            if t.kind == "video" and t is not v1 for c in t.clips]
    cands = []
    for w in words:
        k = norm(w["text"])
        if len(k) < 4 or k in STOP or k not in index:
            continue
        mid, hit = max(index[k], key=lambda x: x[1].get("p", 0.5))
        m = media[mid]
        src = max(0.0, hit["start"] - 0.4)
        dur = min(CLIP, max(0.0, m.duration - src))
        if dur < 1.0:
            continue
        cands.append({"t": round(w["start"], 3), "duration": round(dur, 3), "media_id": mid, "source_in": round(src, 3),
                      "word": w["text"].strip(" .,!?"), "score": round(idf.get(k, 1.0), 3),
                      "media_name": m.original_name})
    out: list[dict] = []
    used_words: set[str] = set()                 # each thing you mention once (its first mention)
    used_moments: set[tuple[str, int]] = set()   # and each moment of a recording once
    for c in sorted(cands, key=lambda c: -c["score"]):
        if len(out) >= MAX:
            break
        key, moment = norm(c["word"]), (c["media_id"], int(c["source_in"] // CLIP))
        if key in used_words or moment in used_moments:
            continue
        if any(abs(c["t"] - o["t"]) < SPACING for o in out):
            continue
        if any(a < c["t"] + c["duration"] and c["t"] < b for a, b in busy):
            continue
        used_words.add(key)
        used_moments.add(moment)
        out.append(c)
    out.sort(key=lambda c: c["t"])
    note = None if out else "No words in this edit match your other recordings yet."
    return {"suggestions": out, "note": note}
