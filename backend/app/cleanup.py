"""Filler words and retakes, found in a transcript.

* fillers: "um", "uh", "er", "hmm"… (ClipForge asks the transcriber to write them down;
  how many it catches depends on the speech)
* retakes: you start a sentence, stop, and say it again. Found when the same 3–5 words
  (ignoring fillers) come again within 15 seconds; the first, abandoned try is removed
  and the later one kept.

Words are dicts with text/start/end (any time base). Returns cuts in the same time base.
The Editor has the same rules in frontend/src/timeline/cleanup.ts; both are checked
against tests/data/cleanup_vectors.json.
"""
from __future__ import annotations

import re

FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "hm", "mm", "mhm"}
RETAKE_WINDOW_S = 15.0
RETAKE_MAX_WORDS = 30


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", text.lower())


def find(words: list[dict]) -> list[dict]:
    """[{kind: "filler"|"retake", start, end, text, first, last}] sorted by start; first/last
    are indexes of the words removed."""
    toks = [norm(w["text"]) for w in words]
    cuts: list[dict] = []
    for i, t in enumerate(toks):
        if t in FILLERS:
            prev_end = words[i - 1]["end"] if i else None
            nxt = words[i + 1]["start"] if i + 1 < len(words) else None
            a = words[i]["start"] - 0.05
            if prev_end is not None:
                a = max(a, prev_end + 0.02)
            b = max(words[i]["end"], nxt - 0.06) if nxt is not None else words[i]["end"] + 0.05
            cuts.append({"kind": "filler", "start": round(min(a, words[i]["start"]), 3), "end": round(b, 3),
                         "text": words[i]["text"].strip(), "first": i, "last": i})
    real = [i for i, t in enumerate(toks) if t and t not in FILLERS]
    k = 0
    while k < len(real):
        found = None
        for n in (5, 4, 3):
            if k + n > len(real):
                continue
            seq = [toks[real[x]] for x in range(k, k + n)]
            for m in range(k + n, min(len(real) - n + 1, k + RETAKE_MAX_WORDS)):
                if words[real[m]]["start"] - words[real[k]]["start"] > RETAKE_WINDOW_S:
                    break
                if [toks[real[x]] for x in range(m, m + n)] == seq:
                    found = m
                    break
            if found is not None:
                break
        if found is None:
            k += 1
            continue
        i, j = real[k], real[found]
        cuts.append({"kind": "retake", "start": round(words[i]["start"] - 0.02, 3), "end": round(words[j]["start"] - 0.05, 3),
                     "text": " ".join(w["text"].strip() for w in words[i:j]), "first": i, "last": j - 1})
        k = found
    # a filler inside a retake is already gone
    cuts = [c for c in cuts if not (c["kind"] == "filler" and any(
        r["kind"] == "retake" and r["first"] <= c["first"] <= r["last"] for r in cuts))]
    return sorted(cuts, key=lambda c: c["start"])


def subtract(segments: list[dict], cuts: list[tuple[float, float]], min_len: float = 0.15) -> list[dict]:
    """Remove source-time stretches from source segments [{source_in, source_out, ...}]."""
    out = []
    for s in segments:
        pieces = [(s["source_in"], s["source_out"])]
        for a, b in cuts:
            nxt = []
            for x, y in pieces:
                if b <= x or a >= y:
                    nxt.append((x, y))
                    continue
                if a > x:
                    nxt.append((x, a))
                if b < y:
                    nxt.append((b, y))
            pieces = nxt
        out += [{**s, "source_in": round(x, 3), "source_out": round(y, 3)} for x, y in pieces if y - x >= min_len]
    return out
