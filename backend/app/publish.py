"""YouTube metadata from the final edit: chapters, title ideas, description, tags.

Works without any AI (deterministic rules over the transcript of the *final edit*, so
cut parts never show up), and optionally lets a local AI (Ollama, see language.py)
write catchier titles, chapter names and a description from the same material.

* **Chapters**: the edit is split into ~30 s windows of words; topic boundaries go where
  adjacent windows share the fewest distinctive words (TF-IDF cosine), nudged to the
  nearest pause. YouTube's rules are enforced: the first chapter starts at 0:00, there
  are at least 3, and each is at least 10 s long. Names are the chapter's most
  distinctive words.
* **Titles**: the strongest line you say (exclamations and questions in the best
  moments), plus keyword-based ideas; ≤ 100 characters (YouTube's limit).
* **Description**: hook line, what the video covers, the chapter list, hashtags.
* **Tags**: distinctive words and two-word phrases, within YouTube's 500-character limit.

Swear words never appear in generated text.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional, Sequence

from .effects import is_profane

STOP = set("""a about above after again against all am an and any are aren't as at be because been before being
below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each
few for from further get got gonna gotta had hadn't has hasn't have haven't having he he'd he'll he's her here
here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself just
kind know let's like literally look me mean more most mustn't my myself no nor not now of off oh ok okay on once
only or other ought our ours ourselves out over own pretty probably really right same say said see shan't she
she'd she'll she's should shouldn't so some something stuff such than that that's the their theirs them
themselves then there there's these they they'd they'll they're they've thing things think this those through
to too um uh under until up us very was wasn't way we we'd we'll we're we've well were weren't what what's when
when's where where's which while who who's whom why why's will with won't would wouldn't yeah yes you you'd you'll
you're you've your yours yourself yourselves go going gonna want wanna one two also actually basically maybe
lot lots bit even still back thank thanks guys guy hey yo bro dude man""".split())
WORD_RE = re.compile(r"[a-z][a-z'\-]{2,}")


def _tokens(text: str) -> list[str]:
    return [w.strip("'-") for w in WORD_RE.findall(text.lower()) if w.strip("'-") not in STOP]


def fmt_ts(t: float) -> str:
    t = int(round(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _clean(words: Sequence[dict]) -> list[dict]:
    return [w for w in words if not is_profane(w["text"], "all")]


def windows(words: Sequence[dict], duration: float, size: float = 30.0) -> list[tuple[float, float, list[str]]]:
    out = []
    n = max(1, math.ceil(duration / size))
    for i in range(n):
        a, b = i * size, min(duration, (i + 1) * size)
        out.append((a, b, [t for w in words if a <= w["start"] < b for t in _tokens(w["text"])]))
    return out


def _tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    vecs = []
    for d in docs:
        tf = Counter(d)
        vecs.append({t: (c / max(1, len(d))) * math.log((1 + n) / (1 + df[t]) + 1) for t, c in tf.items()})
    return vecs


def _cos(a: dict, b: dict) -> float:
    num = sum(v * b.get(k, 0.0) for k, v in a.items())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def _keywords(tokens: list[str], vec: dict[str, float], k: int = 3) -> list[str]:
    counts = Counter(tokens)
    ranked = sorted(vec, key=lambda t: (-vec[t] * (1 + math.log(counts[t])), t))
    return [t for t in ranked if counts[t] >= 1][:k]


def chapters(words: Sequence[dict], duration: float, max_chapters: Optional[int] = None) -> list[dict]:
    """[{t, title}] obeying YouTube's chapter rules, or [] if the video is too short."""
    words = _clean(words)
    if duration < 60 or len(words) < 20:
        return []
    k = max_chapters or int(min(12, max(3, round(duration / 120))))
    k = min(k, int(duration // 10))
    win = windows(words, duration, size=min(30.0, max(10.0, duration / (k * 3))))
    vecs = _tfidf([w[2] for w in win])
    # dissimilarity between neighbours: boundary candidates at the start of window i
    gaps = [(1 - _cos(vecs[i - 1], vecs[i]), i) for i in range(1, len(win))]
    gaps.sort(reverse=True)
    starts = [0.0]
    for _d, i in gaps:
        t = _snap_to_pause(words, win[i][0])
        if all(abs(t - s) >= max(10.0, duration / (k * 2)) for s in starts) and duration - t >= 10:
            starts.append(t)
        if len(starts) >= k:
            break
    starts.sort()
    if len(starts) < 3:
        return []
    out = []
    seg_tokens = []
    for j, s in enumerate(starts):
        e = starts[j + 1] if j + 1 < len(starts) else duration
        seg_tokens.append([t for w in words if s <= w["start"] < e for t in _tokens(w["text"])])
    seg_vecs = _tfidf(seg_tokens)
    for j, s in enumerate(starts):
        kw = _keywords(seg_tokens[j], seg_vecs[j], 2)
        title = " & ".join(x.capitalize() for x in kw) if kw else f"Part {j + 1}"
        out.append({"t": round(s, 1), "title": "Intro" if j == 0 and not kw else title})
    return out


def _snap_to_pause(words: Sequence[dict], t: float, reach: float = 6.0) -> float:
    """Move a boundary to the start of the word after the longest pause near ``t``."""
    best, best_gap = t, -1.0
    for a, b in zip(words, words[1:]):
        if abs(b["start"] - t) <= reach:
            gap = b["start"] - a["end"]
            if gap > best_gap:
                best, best_gap = b["start"], gap
    return round(max(0.0, best), 1)


def validate_chapters(ch: Sequence[dict], duration: float) -> list[str]:
    """YouTube's rules; returns problems (empty = OK)."""
    probs = []
    if not ch:
        return probs
    if ch[0]["t"] > 0.5:
        probs.append("The first chapter must start at 0:00.")
    if len(ch) < 3:
        probs.append("YouTube needs at least 3 chapters.")
    for a, b in zip(ch, list(ch[1:]) + [{"t": duration}]):
        if b["t"] - a["t"] < 10:
            probs.append(f"Chapter “{a['title']}” is shorter than 10 seconds.")
    return probs


def _sentences(words: Sequence[dict]) -> list[tuple[float, str]]:
    """Sentences split at end punctuation *or* a pause (Whisper doesn't always punctuate)."""
    from .language import _sentences as split
    return [(s[0]["start"], " ".join(w["text"].strip() for w in s)) for s in split(list(words)) if s]


def title_ideas(words: Sequence[dict], project_name: str, keywords: list[str]) -> list[str]:
    words = _clean(words)
    ideas: list[str] = []
    for _t, s in _sentences(words):
        n = len(s.split())
        if 3 <= n <= 12 and s.endswith(("!", "?")):
            s = s.rstrip(".")
            ideas.append(s[:1].upper() + s[1:])
    ideas = sorted(set(ideas), key=lambda x: (not x.endswith("!"), len(x)))[:3]
    if keywords:
        top = [k.capitalize() for k in keywords[:3]]
        ideas.append(f"{top[0]} & {top[1]}" if len(top) > 1 else top[0])
    base = re.sub(r"[_\-]+", " ", re.sub(r"\.[a-z0-9]{2,4}$", "", project_name, flags=re.I)).strip()
    if base and base.lower() not in ("untitled", "auto edit"):
        ideas.append(base[:1].upper() + base[1:])
    seen, out = set(), []
    for i in ideas:
        i = re.sub(r"\s+", " ", i).strip()[:100]
        if i and i.lower() not in seen:
            seen.add(i.lower())
            out.append(i)
    return out[:5]


def tags_for(words: Sequence[dict], limit_chars: int = 480, max_tags: int = 15) -> list[str]:
    words = _clean(words)
    toks = [t for w in words for t in _tokens(w["text"])]
    if not toks:
        return []
    counts = Counter(toks)
    bigrams = Counter(f"{a} {b}" for a, b in zip(toks, toks[1:]) if a != b)
    singles = [t for t, c in counts.most_common(30) if c >= 2]
    pairs = [b for b, c in bigrams.most_common(15) if c >= 2]
    cand = [x for pair in zip(singles, pairs + [None] * len(singles)) for x in pair if x] + pairs[len(singles):]
    out, total, seen = [], 0, set()
    for t in cand:
        if t in seen or len(t) > 30:
            continue
        cost = len(t) + (2 if " " in t else 0) + 1  # YouTube counts quotes around multi-word tags
        if total + cost > limit_chars or len(out) >= max_tags:
            break
        out.append(t)
        seen.add(t)
        total += cost
    return out


def description_for(hook: str, keywords: list[str], ch: Sequence[dict], hashtags: list[str]) -> str:
    parts = []
    if hook:
        parts.append(hook)
    if keywords:
        parts.append("In this video: " + ", ".join(keywords[:6]) + ".")
    if ch:
        parts.append("Chapters\n" + "\n".join(f"{fmt_ts(c['t'])} {c['title']}" for c in ch))
    if hashtags:
        parts.append(" ".join(hashtags))
    return "\n\n".join(parts)[:4900]  # YouTube: 5000 characters max


def suggest(words: Sequence[dict], duration: float, project_name: str) -> dict:
    words = list(words)
    clean = _clean(words)
    toks = [t for w in clean for t in _tokens(w["text"])]
    vec = _tfidf([toks, []])[0] if toks else {}
    keywords = _keywords(toks, vec, 8) if toks else []
    ch = chapters(words, duration)
    titles = title_ideas(words, project_name, keywords)
    hook = next((s for _t, s in _sentences(clean) if 4 <= len(s.split()) <= 25), "")
    hook = hook[:1].upper() + hook[1:]
    hashtags = ["#" + re.sub(r"[^a-z0-9]", "", k) for k in keywords[:3] if re.sub(r"[^a-z0-9]", "", k)]
    warnings = []
    if not words:
        warnings.append("No transcript in this edit, so only a basic title could be suggested. Transcribe it for chapters, a description and tags.")
    elif not ch and duration >= 60:
        warnings.append("Not enough talking to make chapters.")
    elif duration < 60:
        warnings.append("Chapters are only useful on videos longer than a minute.")
    return {"titles": titles, "description": description_for(hook, keywords, ch, hashtags), "chapters": ch,
            "tags": tags_for(words), "hashtags": hashtags, "keywords": keywords, "source": "rules", "warnings": warnings}


# ---------------------------------------------------------------- optional local AI polish
AI_SYSTEM = ("You write YouTube metadata for a creator's video from its transcript. Be specific to what is "
             "actually said, energetic but not clickbait-lies, no swear words, no emojis spam. Reply ONLY with JSON: "
             '{"titles": [5 strings, each under 70 characters], "description": "2-4 sentence description", '
             '"chapter_titles": [one short title (2-5 words) per chapter, same order], "tags": [10-20 short tags]}')


def ai_polish(model, words: Sequence[dict], base: dict, cancel=None) -> dict:
    clean = _clean(words)
    excerpt = []
    ch = base.get("chapters") or [{"t": 0.0, "title": ""}]
    bounds = [c["t"] for c in ch] + [float("inf")]
    for i, c in enumerate(ch):
        text = " ".join(w["text"].strip() for w in clean if bounds[i] <= w["start"] < bounds[i + 1])
        excerpt.append(f"Chapter {i + 1} at {fmt_ts(c['t'])}: {text[:700]}")
    data = model.chat_json(AI_SYSTEM, "\n\n".join(excerpt)[:9000], cancel=cancel)
    out = dict(base, source="ai", warnings=list(base.get("warnings", [])))
    titles = [str(t).strip()[:100] for t in (data.get("titles") or []) if str(t).strip() and not _has_swear(str(t))]
    if titles:
        out["titles"] = titles[:5] + [t for t in base["titles"] if t not in titles][:2]
    names = [str(t).strip()[:60] for t in (data.get("chapter_titles") or [])]
    if base.get("chapters") and len(names) == len(base["chapters"]) and all(names):
        out["chapters"] = [{"t": c["t"], "title": n} for c, n in zip(base["chapters"], names)]
    desc = str(data.get("description") or "").strip()
    if desc and not _has_swear(desc):
        hook_free = desc[:3000]
        out["description"] = description_for(hook_free, [], out["chapters"], base.get("hashtags", []))
    tags = [str(t).strip().lower()[:30] for t in (data.get("tags") or []) if str(t).strip() and not _has_swear(str(t))]
    if tags:
        merged, total = [], 0
        for t in tags + [t for t in base["tags"] if t not in tags]:
            if total + len(t) + 3 > 480:
                break
            merged.append(t)
            total += len(t) + 3
        out["tags"] = merged
    return out


def _has_swear(text: str) -> bool:
    return any(is_profane(w, "strong") for w in re.findall(r"[A-Za-z*']+", text))


# ---------------------------------------------------------------- saved draft (per project)
from pydantic import BaseModel, Field, field_validator  # noqa: E402

CATEGORIES = {"1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals", "17": "Sports",
              "19": "Travel & Events", "20": "Gaming", "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
              "25": "News & Politics", "26": "Howto & Style", "27": "Education", "28": "Science & Technology"}


class Chapter(BaseModel):
    model_config = {"extra": "forbid"}
    t: float = Field(ge=0)
    title: str = Field(min_length=1, max_length=100)


class PublishDraft(BaseModel):
    """What will be sent to YouTube (nothing is sent until you press Upload)."""
    model_config = {"extra": "forbid"}
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=60)
    chapters: list[Chapter] = Field(default_factory=list, max_length=50)
    privacy: str = Field(default="private", pattern="^(private|unlisted|public)$")
    category_id: str = "22"
    made_for_kids: bool = False
    publish_at: Optional[str] = Field(default=None, max_length=40)  # ISO time; needs privacy=private on upload
    export_file: Optional[str] = Field(default=None, max_length=200)
    thumbnail_file: Optional[str] = Field(default=None, max_length=200)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out = [t.strip()[:30] for t in v if t.strip() and "<" not in t and ">" not in t]
        if sum(len(t) + (3 if " " in t else 1) for t in out) > 500:
            raise ValueError("tags are longer than YouTube's 500-character limit")
        return out

    @field_validator("category_id")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError("unknown YouTube category")
        return v

    @field_validator("title", "description")
    @classmethod
    def _no_angle(cls, v: str) -> str:
        if "<" in v or ">" in v:
            raise ValueError("YouTube doesn't allow < or > in titles and descriptions")
        return v
