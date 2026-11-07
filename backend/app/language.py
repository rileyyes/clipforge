"""What the words say: transcript features for picking moments, plus optional local AI.

Deterministic features (no AI needed), computed from Whisper word timestamps:

* **laughs**      laughter in the transcript ("haha", "lol", "(laughs)", "[Laughter]"…)
* **punchlines**  a setup (a question or a finished sentence) followed within ~3 s by a
                  payoff: laughter, an exclamation/interjection, or a loud reaction spike
* **exclaim**     exclamations and interjections ("wait", "no way", "bro", "what?!")
* **questions**   questions asked (set-ups, curiosity)
* **story**       storytelling markers ("so then", "turns out", "suddenly", "because")

All are rates per minute of the moment. They feed the style weights in ``autoedit``.

Optional: a local LLM (free Ollama, auto-detected on 127.0.0.1:11434, or
``RJCLIP_LLM_BASE_URL``) rates transcript chunks for how funny / interesting they are.
Its scores become one more feature ("ai") with its one-line reason shown to you.
Nothing is sent anywhere unless such a server is configured; a non-local URL is flagged.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from typing import Iterable, Optional, Sequence

import numpy as np

LAUGH_RE = re.compile(r"^(?:[\(\[]\s*)?(?:ha(?:ha)+h?|he(?:he)+|lo+l|lmf?ao+|rofl|laugh(?:s|ing|ter)?|"
                      r"chuckles?|giggles?)(?:\s*[\)\]])?$", re.I)
INTERJECTIONS = {
    "wait", "what", "whoa", "woah", "wow", "omg", "bro", "bruh", "dude", "yo", "nah", "nope", "yes", "yeah",
    "oh", "ah", "ahh", "ow", "ouch", "damn", "dang", "holy", "jeez", "gosh", "huh", "hey", "stop", "no",
}
PHRASES = ["no way", "oh my god", "oh my gosh", "are you kidding", "you're kidding", "what the", "let's go",
           "lets go", "i can't", "shut up", "come on", "are you serious", "get out", "oh no"]
STORY = ["so then", "and then", "turns out", "it turns out", "suddenly", "all of a sudden", "because",
         "the thing is", "long story", "one day", "that's when", "next thing", "eventually", "finally",
         "at first", "remember when", "back when", "anyway", "so basically"]
PAYOFF_S = 3.0


def _norm(t: str) -> str:
    return re.sub(r"[^\w' ]+", "", t.lower()).strip()


def _sentences(words: Sequence[dict], gap: float = 0.8) -> list[list[dict]]:
    """Split words into sentences at end punctuation or a pause."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        t = w["text"].strip()
        nxt = words[i + 1]["start"] if i + 1 < len(words) else None
        if t.endswith((".", "?", "!", "…")) or (nxt is not None and nxt - w["end"] > gap):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def word_events(words: Sequence[dict], rms_db: Sequence[float] = (), hop: float = 0.05) -> dict[str, list[float]]:
    """Times (source seconds) of each kind of language event, for the whole recording."""
    ev: dict[str, list[float]] = {"laughs": [], "exclaim": [], "questions": [], "story": [], "punchlines": []}
    if not words:
        return ev
    rms = np.asarray(rms_db, dtype=np.float32)
    spike_thr = float(np.percentile(rms, 95)) if rms.size > 20 else None
    toks = [_norm(w["text"]) for w in words]
    sents = _sentences(words)
    short = {id(w) for s in sents if len(s) <= 2 for w in s}  # standalone reactions ("Wait!", "No way")
    for w, raw, tok in zip(words, (w["text"].strip() for w in words), toks):
        if LAUGH_RE.match(raw.strip(".,!?")) or LAUGH_RE.match(tok):
            ev["laughs"].append(w["start"])
        elif raw.endswith("!") or (tok in INTERJECTIONS and (raw.endswith("?!") or id(w) in short)):
            ev["exclaim"].append(w["start"])
        if raw.endswith("?"):
            ev["questions"].append(w["end"])
    text = " ".join(toks)
    # map phrase hits back to word times via a running character offset
    starts, pos = [], 0
    for tok in toks:
        starts.append(pos)
        pos += len(tok) + 1
    def time_at(char: int) -> float:
        i = int(np.searchsorted(np.asarray(starts), char, side="right")) - 1
        return float(words[max(0, i)]["start"])
    for ph in PHRASES:
        for m in re.finditer(r"\b" + re.escape(ph) + r"\b", text):
            ev["exclaim"].append(time_at(m.start()))
    for ph in STORY:
        for m in re.finditer(r"\b" + re.escape(ph) + r"\b", text):
            ev["story"].append(time_at(m.start()))
    # punchlines: setup sentence end -> payoff soon after
    payoffs = sorted(ev["laughs"] + ev["exclaim"])
    for s in sents:
        end = s[-1]["end"]
        if len(s) < 3:  # a setup is a real sentence, not a one-word reaction
            continue
        hit = any(end < t <= end + PAYOFF_S for t in payoffs)
        if not hit and spike_thr is not None and rms.size:
            a, b = int(end / hop), int((end + PAYOFF_S) / hop)
            seg = rms[a:b]
            hit = bool(seg.size and float(seg.max()) >= spike_thr + 2)
        if hit:
            ev["punchlines"].append(end)
    for k in ev:
        ev[k] = sorted(set(round(t, 3) for t in ev[k]))
    return ev


def beat_features(events: dict[str, list[float]], start: float, end: float) -> dict[str, float]:
    """Per-minute rates of each language event inside [start, end)."""
    span = max(end - start, 1e-6)
    out = {}
    for k, ts in events.items():
        n = sum(1 for t in ts if start <= t < end)
        out[k] = n / span * 60
    return out


def transcript_text(words: Sequence[dict], start: float, end: float, limit: int = 600) -> str:
    return " ".join(w["text"].strip() for w in words if start <= w["start"] < end)[:limit]


# ---------------------------------------------------------------- optional local AI
_detect_cache: dict = {"at": 0.0, "model": None}
_detect_lock = threading.Lock()
PREFERRED = ("llama3.1", "llama3.2", "llama3", "qwen2.5", "qwen3", "gemma3", "gemma2", "mistral", "phi4", "phi3")


def detect_ollama(base: str = "http://127.0.0.1:11434", timeout: float = 0.6) -> Optional[str]:
    """Name of an installed Ollama model, if Ollama is running locally (cached 60 s)."""
    with _detect_lock:
        if time.time() - _detect_cache["at"] < 60:
            return _detect_cache["model"]
        model = None
        try:
            with urllib.request.urlopen(base + "/api/tags", timeout=timeout) as r:
                names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
            names = [n for n in names if n and "embed" not in n]
            model = next((n for p in PREFERRED for n in names if n.startswith(p)), names[0] if names else None)
        except (OSError, ValueError):
            model = None
        _detect_cache.update(at=time.time(), model=model)
        return model


def text_model():
    """The configured text model (RJCLIP_LLM_BASE_URL), else a running local Ollama, else None."""
    from .thumb_providers import TextModel, text_model as configured
    if os.environ.get("RJCLIP_LLM", "auto").lower() == "off":
        return None
    m = configured()
    if m is not None:
        return m
    found = detect_ollama()
    if found:
        return TextModel("http://127.0.0.1:11434/v1", os.environ.get("RJCLIP_LLM_MODEL", found), "", False)
    return None


def chunks(words: Sequence[dict], target: float = 15.0) -> list[tuple[float, float, str]]:
    """Transcript split into ~15 s chunks at sentence boundaries (the unit the AI rates)."""
    out: list[tuple[float, float, str]] = []
    cur: list[dict] = []
    for s in _sentences(words):
        cur += s
        if cur[-1]["end"] - cur[0]["start"] >= target:
            out.append((cur[0]["start"], cur[-1]["end"], " ".join(w["text"].strip() for w in cur)))
            cur = []
    if cur:
        out.append((cur[0]["start"], cur[-1]["end"], " ".join(w["text"].strip() for w in cur)))
    return out


RATE_SYSTEM = ("You help a YouTuber edit their video. For each numbered transcript chunk, rate how much it "
               "deserves to stay in a tight, entertaining edit: funny moments, punchlines, surprising or "
               "dramatic moments, key story beats and useful information score high; filler, repetition, "
               "rambling and dead talk score low. Reply ONLY with JSON: "
               '{"ratings": [{"i": <chunk number>, "score": <0-10>, "why": "<max 8 words>"}]}')


def ai_rate(model, words: Sequence[dict], on_progress=None, cancel=None, batch: int = 12) -> list[dict]:
    """[{start, end, score 0-10, why}] for each chunk; chunks the model skips are left out."""
    cs = chunks(words)
    out: list[dict] = []
    for b0 in range(0, len(cs), batch):
        if cancel is not None and cancel.is_set():
            from .ffmpeg import Cancelled
            raise Cancelled("cancelled")
        part = cs[b0:b0 + batch]
        user = "\n".join(f"{b0 + k}: {t[:500]}" for k, (_s, _e, t) in enumerate(part))
        data = model.chat_json(RATE_SYSTEM, user, cancel=cancel)
        for r in data.get("ratings", []) if isinstance(data, dict) else []:
            try:
                i = int(r["i"])
                score = float(r["score"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (b0 <= i < b0 + len(part)) or not (0 <= score <= 10):
                continue
            s, e, _t = cs[i]
            out.append({"start": round(s, 3), "end": round(e, 3), "score": round(score, 1),
                        "why": str(r.get("why", ""))[:80]})
        if on_progress:
            on_progress(min(1.0, (b0 + len(part)) / max(1, len(cs))))
    return out


def ai_feature(ratings: Iterable[dict], start: float, end: float) -> Optional[tuple[float, str]]:
    """Overlap-weighted AI score for [start, end) and the best-matching reason."""
    tot = w_sum = 0.0
    best = (0.0, "")
    for r in ratings:
        ov = min(end, r["end"]) - max(start, r["start"])
        if ov <= 0:
            continue
        tot += r["score"] * ov
        w_sum += ov
        if ov * r["score"] > best[0]:
            best = (ov * r["score"], r.get("why", ""))
    if w_sum <= 0:
        return None
    return tot / w_sum, best[1]
