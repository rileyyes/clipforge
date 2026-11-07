"""Hook checker (Phase 16): how strong are the first seconds of the edit?

Viewers decide in the first few seconds. This looks at the start of the FINAL edit (the
timeline, not the raw recordings) and scores it 0–100 from things that can be measured:

* how long until you start talking (dead air at the start),
* how loud / lively the start is compared with the rest of the video,
* how much is said in the first seconds,
* how much the picture moves,
* how long a branded intro runs before the video starts,
* whether the first sentence is a "hook" (a question, "you", "how", "never", "best"…).

It also finds the most exciting few seconds later in the video, which can be copied to the
start as a teaser. Everything is local and rule-based: the reasons are shown, so the score
can be checked.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np

from .analysis import load_analysis
from .effects import edit_words
from .schema import Project

STEP = 0.1
HOOK_WORDS = {"you", "your", "how", "why", "what", "never", "best", "worst", "insane", "crazy", "secret", "watch",
              "today", "finally", "first", "biggest", "won", "lost", "broke", "impossible", "wait"}
LAUGH = re.compile(r"\b(ha(ha)+|lol|lmao|omg|no way|what)\b", re.I)


def _duration(p: Project) -> float:
    return max([c.start + (c.source_out - c.source_in) / c.speed for t in p.timeline.tracks for c in t.clips] or [0.0])


def edit_curves(p: Project, project_dir: Path, D: float) -> tuple[np.ndarray, np.ndarray]:
    """Loudness (dB) and motion (0..1 per recording) along the edit, every STEP seconds."""
    n = max(1, int(np.ceil(D / STEP)))
    loud = np.full(n, -90.0, dtype=np.float32)
    motion = np.zeros(n, dtype=np.float32)
    cache: dict[str, Optional[dict]] = {}
    for tr in p.timeline.tracks:
        if tr.muted and tr.kind == "audio" or tr.hidden and tr.kind == "video" or tr.role == "music":
            continue
        for c in tr.clips:
            a = cache.setdefault(c.media_id, load_analysis(project_dir, c.media_id))
            if not a:
                continue
            hop = a.get("hop", 0.05)
            arr = np.asarray(a.get("rms_db" if tr.kind == "audio" else "motion") or [], dtype=np.float32)
            if arr.size < 2:
                continue
            if tr.kind == "video":
                arr = np.clip(arr / max(1e-6, float(np.percentile(arr, 95))), 0, 1)
            i0 = int(c.start / STEP)
            i1 = min(n, int((c.start + (c.source_out - c.source_in) / c.speed) / STEP))
            for i in range(i0, i1):
                src = c.source_in + (i * STEP - c.start) * c.speed
                j = min(arr.size - 1, max(0, int(src / hop)))
                if tr.kind == "audio":
                    loud[i] = max(loud[i], arr[j])
                else:
                    motion[i] = max(motion[i], arr[j])
    return loud, motion


def check(p: Project, project_dir: Path) -> dict:
    D = _duration(p)
    if D < 3:
        return {"score": None, "verdict": "The edit is too short to judge.", "tips": [], "teaser": None, "metrics": {}}
    H = min(10.0, max(3.0, D * 0.3))
    words = edit_words(p, project_dir)
    loud, motion = edit_curves(p, project_dir, D)
    nH = int(H / STEP)
    have_audio = bool((loud > -89).any())
    v1 = next((t for t in p.timeline.tracks if t.kind == "video"), None)
    first = min(v1.clips, key=lambda c: c.start) if v1 and v1.clips else None
    intro_len = (first.source_out - first.source_in) / first.speed if first and (first.label or "").lower() == "intro" else 0.0
    body = intro_len  # where the video itself starts
    m: dict[str, float] = {}
    parts: list[tuple[str, float, float, str]] = []   # (id, part 0..1, weight, tip if weak)

    # 1. how long until you talk (after any intro)
    first_word = next((w["start"] for w in words if w["start"] >= body - 0.05), None)
    if first_word is not None:
        delay = first_word - body
        m["talk_starts_after"] = round(delay, 2)
        parts.append(("start_delay", float(np.clip(1 - (delay - 0.5) / 2.5, 0, 1)), 0.25,
                      f"You start talking {delay:.1f} s in. Cut the quiet start so the video begins on your first word."))
    elif have_audio:
        speech = np.nonzero(loud[int(body / STEP):] > max(-40.0, float(np.median(loud)) - 6))[0]
        delay = float(speech[0] * STEP) if speech.size else H
        m["sound_starts_after"] = round(delay, 2)
        parts.append(("start_delay", float(np.clip(1 - (delay - 0.5) / 2.5, 0, 1)), 0.25,
                      f"Nothing much is heard for the first {delay:.1f} s. Start where the action starts."))
    # 2. energy of the start vs the whole video
    if have_audio:
        a0, med = float(np.mean(loud[:nH])), float(np.median(loud[loud > -89]))
        m["start_loudness_vs_typical_db"] = round(a0 - med, 1)
        parts.append(("energy", float(np.clip((a0 - med + 6) / 8, 0, 1)), 0.2,
                      "The start is quieter than the rest of the video. Open on a louder, livelier moment (try the teaser below)."))
    # 3. talking in the first seconds
    if words:
        w0 = sum(1 for w in words if w["start"] < H) / H
        wall = len(words) / D
        m["words_per_s_start"], m["words_per_s_overall"] = round(w0, 2), round(wall, 2)
        parts.append(("talk", float(np.clip(w0 / max(0.5, wall * 0.9), 0, 1)), 0.15,
                      "You say less at the start than usual. Get to the point in the first sentence."))
    # 4. movement
    if motion.any():
        mm0, mall = float(np.mean(motion[:nH])), float(np.mean(motion)) or 1e-6
        m["start_motion_vs_overall"] = round(mm0 / mall, 2)
        parts.append(("motion", float(np.clip(mm0 / mall, 0, 1)), 0.1,
                      "The picture barely moves at the start. Open with action, or add a zoom or pop-up text."))
    # 5. intro length
    if intro_len:
        m["intro_s"] = round(intro_len, 2)
        parts.append(("intro", float(np.clip(1 - (intro_len - 3) / 5, 0, 1)), 0.15,
                      f"Your intro runs {intro_len:.1f} s before the video starts. Keep it under 3 s, or move it after a teaser."))
    # 6. hook line
    if words:
        sent = []
        for w in words:
            sent.append(w["text"].strip())
            if w["text"].strip()[-1:] in ".?!" or len(sent) >= 20:
                break
        line = " ".join(sent)
        toks = {re.sub(r"[^a-z']", "", t.lower()) for t in sent}
        hooky = line.endswith("?") or bool(toks & HOOK_WORDS)
        m["first_sentence"] = line[:160]
        parts.append(("hook_line", 1.0 if hooky else 0.4, 0.15,
                      "Your first sentence doesn't hook: try a question, a bold claim, or tell viewers what they'll get."))

    if not parts:
        return {"score": None, "verdict": "Analyse or transcribe the recordings first (AI Auto Editor → Analyse), then check again.",
                "tips": [], "teaser": None, "metrics": m}
    wsum = sum(w for _, _, w, _ in parts)
    score = int(round(100 * sum(pt * w for _, pt, w, _ in parts) / wsum))
    tips = [{"id": i, "text": tip, "weak": round(1 - pt, 2)} for i, pt, _, tip in sorted(parts, key=lambda x: x[1]) if pt < 0.7]
    verdict = ("Strong start." if score >= 75 else "Okay start — a couple of fixes would help." if score >= 50
               else "Weak start: viewers may leave early.")

    # teaser: the liveliest 4 s after the first H seconds
    teaser = None
    L = 4.0
    nL = int(L / STEP)
    if D > H + L + 1 and (have_audio or motion.any()):
        lz = (loud - float(np.median(loud))) / (float(np.std(loud)) or 1.0) if have_audio else np.zeros_like(loud)
        lz = np.where(loud > -89, lz, -3)
        energy = lz + 1.5 * motion
        for w in words:
            if LAUGH.search(w["text"]):
                k = int(w["start"] / STEP)
                if 0 <= k < energy.size:
                    energy[k] += 2.0
        csum = np.concatenate([[0.0], np.cumsum(energy)])
        lo = max(nH, int(body / STEP) + nH)
        scores = [(csum[i + nL] - csum[i], i) for i in range(lo, energy.size - nL)]
        if scores:
            best, i = max(scores)
            a = i * STEP
            # start and end on word gaps where possible, so no word is cut in half
            for w in words:
                if w["start"] < a < w["end"]:
                    a = w["start"]
            b = a + L
            for w in words:
                if w["start"] < b < w["end"]:
                    b = w["end"]
            teaser = {"start": round(a, 2), "end": round(b, 2)}
    actions = []
    if "talk_starts_after" in m and m["talk_starts_after"] > 0.8:
        actions.append({"id": "trim_start", "label": f"Cut the first {m['talk_starts_after'] - 0.2:.1f} s of quiet",
                        "cut": [round(body, 2), round(body + m["talk_starts_after"] - 0.2, 2)]})
    if teaser:
        actions.append({"id": "teaser", "label": f"Copy the moment at {teaser['start']:.0f} s to the start as a teaser",
                        "range": [teaser["start"], teaser["end"]]})
    return {"score": score, "verdict": verdict, "tips": tips, "teaser": teaser, "actions": actions, "metrics": m,
            "window_s": round(H, 1)}


# ---------------------------------------------------------------- music to match the video (Phase 16)
def sections(p: Project, project_dir: Path, min_len: float = 25.0) -> list[dict]:
    """Parts of the edit with their energy (0..1, relative to this video): from the user's
    markers when there are some, else ~30-second pieces merged while they feel the same."""
    D = _duration(p)
    if D < 1:
        return []
    loud, motion = edit_curves(p, project_dir, D)
    has = loud > -89
    lz = np.where(has, (loud - float(np.median(loud[has]))) / (float(np.std(loud[has])) or 1.0) if has.any() else 0.0, -2.0)
    energy = lz + 1.5 * motion
    marks = sorted(m.t for m in p.timeline.markers if 1.0 < m.t < D - 1.0)
    if marks:
        cuts = [0.0, *marks, D]
    else:
        n = max(1, int(round(D / 30.0)))
        cuts = [D * i / n for i in range(n + 1)]
    raw = []
    for a, b in zip(cuts, cuts[1:]):
        seg = energy[int(a / STEP):max(int(a / STEP) + 1, int(b / STEP))]
        raw.append({"start": round(a, 2), "end": round(b, 2), "e": float(np.mean(seg)) if seg.size else 0.0})
    es = np.array([r["e"] for r in raw])
    lo, hi = float(es.min()), float(es.max())
    for r in raw:
        r["energy"] = round((r["e"] - lo) / (hi - lo), 3) if hi - lo > 0.15 else 0.5
        r["label"] = "calm" if r["energy"] < 0.34 else "medium" if r["energy"] < 0.67 else "hype"
        del r["e"]
    if marks:
        return raw
    merged: list[dict] = []
    for r in raw:  # neighbours that feel the same (or too short) become one part
        if merged and (merged[-1]["label"] == r["label"] or r["end"] - r["start"] < min_len):
            m = merged[-1]
            w0, w1 = m["end"] - m["start"], r["end"] - r["start"]
            m["energy"] = round((m["energy"] * w0 + r["energy"] * w1) / (w0 + w1), 3)
            m["end"] = r["end"]
        else:
            merged.append(dict(r))
    return merged


def music_plan(secs: list[dict], songs: list[dict]) -> list[dict]:
    """Calmer parts get calmer songs: songs are ranked by energy and each part takes the song
    at its own rank. Neighbouring parts with the same song become one stretch."""
    if not secs or not songs:
        return []
    ranked = sorted(songs, key=lambda s: s["energy"])
    plan: list[dict] = []
    for s in secs:
        song = ranked[min(len(ranked) - 1, int(round(s["energy"] * (len(ranked) - 1))))]
        if plan and plan[-1]["media_id"] == song["media_id"]:
            plan[-1]["end"] = s["end"]
        else:
            plan.append({"start": s["start"], "end": s["end"], "media_id": song["media_id"]})
    return plan
