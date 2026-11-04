"""Where to drop your own sounds and images ("memes / B-roll") in the final edit.

Each library item has keywords: its name's words plus any you add (e.g. a "bruh" sound
tagged "fail, oops, no way"). Suggestions come from two places:

* **Words**: when you *say* one of an item's keywords (in the final edit's transcript),
  suggest the item right there ("you said 'creeper'").
* **Reactions**: big loud reactions get a reaction-type item ("reaction", "funny", "laugh",
  "wow", "bruh"…) or, failing that, any short sound.

Suggestions are spaced at least 4 s apart, each item is used at most 3 times, and the
best 20 are returned. Nothing is added until you click Add. Deterministic.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from . import effects as fx
from .schema import Project

REACTION_WORDS = {"reaction", "react", "funny", "laugh", "laughing", "lol", "wow", "omg", "bruh", "fail", "oops",
                  "wtf", "huh", "what", "shock", "shocked", "surprise", "airhorn", "boom", "meme", "sad", "cry",
                  "clap", "win", "epic", "no", "nope", "yes", "hype", "scream"}
STOP = {"the", "a", "an", "my", "and", "of", "sound", "image", "img", "pic", "photo", "recording", "clip",
        "final", "copy", "new", "file", "audio", "video", "untitled"}


def _stem(w: str) -> str:
    w = w.lower().strip("'")
    for suf in ("ing", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def keywords(item: dict) -> set[str]:
    words = re.findall(r"[a-zA-Z']{2,}", item.get("name", "")) + [t for tag in item.get("tags") or []
                                                                  for t in re.findall(r"[a-zA-Z']{2,}", tag)]
    return {_stem(w) for w in words if w.lower() not in STOP and not w.isdigit()}


def suggest(project: Project, project_dir: Path, items: Sequence[dict], limit: int = 20,
            gap: float = 4.0, per_item: int = 3) -> list[dict]:
    words = fx.edit_words(project, project_dir)
    D = project.timeline.duration
    kw = {it["id"]: keywords(it) for it in items}
    cands: list[dict] = []
    for w in words:
        tok = _stem(re.sub(r"[^\w']", "", w["text"]))
        if len(tok) < 3:
            continue
        for it in items:
            if tok in kw[it["id"]]:
                said = w["text"].strip(" .,!?")
                said = fx.mask_word(said) if fx.is_profane(said, "all") else said
                cands.append({"t": round(w["start"], 2), "item": it, "why": f"you said “{said}”",
                              "score": 2.0 + (0.5 if it["kind"] == "image" else 0)})
    reaction_items = [it for it in items if kw[it["id"]] & {_stem(r) for r in REACTION_WORDS}]
    short_sounds = [it for it in items if it["kind"] == "sound" and (it.get("duration") or 9) <= 4]
    pool = reaction_items or short_sounds
    if pool:
        for k, (t, strength, _db) in enumerate(sorted(fx.reaction_moments(project, project_dir), key=lambda c: -c[1])[:15]):
            it = pool[k % len(pool)]
            cands.append({"t": round(max(0.0, t - 0.1), 2), "item": it, "why": "big reaction", "score": 1.0 + strength})
    cands.sort(key=lambda c: (-c["score"], c["t"]))
    chosen: list[dict] = []
    used: dict[str, int] = {}
    for c in cands:
        if not (0.2 <= c["t"] <= max(0.2, D - 0.5)):
            continue
        if any(abs(c["t"] - o["t"]) < gap for o in chosen) or used.get(c["item"]["id"], 0) >= per_item:
            continue
        chosen.append(c)
        used[c["item"]["id"]] = used.get(c["item"]["id"], 0) + 1
        if len(chosen) >= limit:
            break
    chosen.sort(key=lambda c: c["t"])
    return [{"t": c["t"], "kind": c["item"]["kind"], "item_id": c["item"]["id"], "name": c["item"]["name"],
             "duration": c["item"].get("duration"), "why": c["why"]} for c in chosen]
