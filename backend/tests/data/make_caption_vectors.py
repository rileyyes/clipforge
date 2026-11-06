"""Make backend/tests/data/caption_vectors.json from the backend's caption_chunks.

Run from backend/: python tests/data/make_caption_vectors.py (only when the caption rules change on purpose)."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
from app.schema import Project
from app.projects import ProjectStore
from app.storage import new_id
from app import effects as fx

A, B = "a" * 32, "b" * 32
def W(text, s, e): return {"text": text, "start": s, "end": e, "p": 0.9}
WA = [W(" So", 0.2, 0.4), W(" today", 0.45, 0.8), W(" we're", 0.85, 1.0), W(" going", 1.05, 1.3), W(" to", 1.32, 1.4),
      W(" build", 1.45, 1.8), W(" it.", 1.85, 2.1), W(" What", 2.3, 2.5), W(" the", 2.52, 2.6), W(" shit", 2.62, 2.9),
      W(" is", 2.95, 3.05), W(" that?", 3.1, 3.4), W(" Okay", 4.6, 4.9), W(" café", 5.0, 5.3), W(" don't", 5.4, 5.7),
      W(" stop", 5.75, 6.0), W(" now", 6.05, 6.3), W(" ", 6.4, 6.5), W(" ok!", 6.6, 6.9), W(" yes", 7.0, 7.2)]
WB = [W(" second", 0.1, 0.5), W(" clip", 0.55, 0.9), W(" here", 0.95, 1.3), W(" fast", 1.4, 1.8)]

def clip(m, start, si, so, speed=1.0, link=None):
    return {"id": new_id(), "media_id": m, "start": start, "source_in": si, "source_out": so, "speed": speed, "link_id": link}

def censor(m, t, d): return {"id": new_id(), "kind": "censor", "media_id": m, "source_time": t, "duration": d, "origin": "auto", "word": "shit", "sound": "beep"}

CASES = [
    ("simple sentence, punctuation and pauses", {"max_words": 4, "uppercase": False},
     [clip(A, 0, 0, 8)], [], []),
    ("max 2 words, uppercase", {"max_words": 2, "uppercase": True},
     [clip(A, 0, 0, 8)], [], []),
    ("bleeped word masked", {"max_words": 4, "uppercase": True},
     [clip(A, 0, 0, 8)], [censor(A, 2.6, 0.32)], []),
    ("cut in the middle, second clip at 2x, muted track ignored", {"max_words": 3, "uppercase": False},
     [clip(A, 0, 0, 2.2), clip(B, 2.2, 0, 1.9, 2.0), clip(A, 3.15, 4.5, 7.3)], [censor(A, 5.35, 0.4)], [clip(A, 0, 0, 8)]),
]
out = []
with tempfile.TemporaryDirectory() as td:
    st = ProjectStore(Path(td) / "projects")
    for name, cs, aclips, effs, muted in CASES:
        p = st.create("v")
        pdir = st.dir(p.id)
        (pdir / "analysis").mkdir(exist_ok=True)
        for m, words in ((A, WA), (B, WB)):
            (pdir / "analysis" / f"{m}.json").write_text(json.dumps({"version": 1, "media_id": m, "duration": 8.0, "hop": 0.05,
                                                                       "rms_db": [], "motion": [], "cuts": [], "words": words}))
        d = p.model_dump(mode="json")
        d["timeline"]["tracks"][2]["clips"] = aclips
        if muted:
            d["timeline"]["tracks"].append({"id": new_id(), "kind": "audio", "name": "A9", "muted": True, "hidden": False,
                                            "locked": False, "clips": muted})
        d["effects"] = effs
        d["media"] = [{"id": m, "original_name": f"{m[0]}.mp4", "stored_name": f"{m}.mp4", "kind": "video", "duration": 8.0,
                       "size_bytes": 1, "container": "mp4", "has_video": True, "has_audio": True, "variable_frame_rate": False,
                       "imported_at": "2026-01-01T00:00:00Z", "width": 320, "height": 180, "fps": 30.0} for m in (A, B)]
        d["captions"] = {**d["captions"], **cs, "enabled": True}
        proj = Project.model_validate(d)
        chunks = fx.caption_chunks(proj, pdir)
        out.append({"name": name, "timeline": d["timeline"], "effects": d["effects"], "words": {A: WA, B: WB}, "captions": cs,
                    "expect": [{"start": round(c["start"], 6), "end": round(c["end"], 6), "text": c["text"]} for c in chunks]})
Path("tests/data/caption_vectors.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
for c in out:
    print(c["name"], "->", [x["text"] for x in c["expect"]])
