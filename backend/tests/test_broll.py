"""Phase 8.5: suggestions for where to drop your own library sounds & images."""
from __future__ import annotations

from app import broll

from test_effects import _project


def W(*items):
    return [{"start": s, "end": s + 0.3, "text": " " + t, "p": 0.9} for s, t in items]


ITEMS = [
    {"id": "a" * 32, "kind": "image", "name": "Creeper face", "tags": []},
    {"id": "b" * 32, "kind": "sound", "name": "My bruh", "tags": ["fail", "oops"], "duration": 1.2},
    {"id": "c" * 32, "kind": "sound", "name": "long song", "tags": [], "duration": 25},
    {"id": "d" * 32, "kind": "image", "name": "pizza.png", "tags": ["food"]},
]


def test_keywords_from_name_and_tags():
    assert broll.keywords(ITEMS[0]) == {"creeper", "face"}
    assert broll.keywords(ITEMS[1]) == {"bruh", "fail", "oop"}
    assert broll.keywords({"name": "Recording 12:30", "tags": []}) == set()


def test_words_and_reactions_become_suggestions(tmp_path):
    words = W((0.5, "a"), (1.0, "creepers!"), (1.6, "everywhere."), (3.0, "creeper"), (6.3, "want"), (6.6, "pizza"),
              (6.9, "now"))
    rms = [-20.0] * 160
    for i in range(96, 104):  # loud reaction at 4.8-5.2 s
        rms[i] = 0.0
    s, p, pdir = _project(tmp_path, words=words, rms=rms, video_clips=[dict(start=0, source_in=0, source_out=7.5)])
    out = broll.suggest(p, pdir, ITEMS, gap=1.5)
    by = [(o["t"], o["name"], o["why"]) for o in out]
    assert (1.0, "Creeper face", "you said “creepers”") in by
    assert any(o["name"] == "pizza.png" and o["why"] == "you said “pizza”" for o in out)
    assert any(o["name"] == "My bruh" and o["why"] == "big reaction" for o in out)  # tagged 'fail' -> reaction item
    assert all(b["t"] - a["t"] >= 1.5 for a, b in zip(out, out[1:]))  # spaced out
    assert len(broll.suggest(p, pdir, ITEMS)) < len(out)  # the default 4 s spacing keeps fewer
    assert "long song" not in {o["name"] for o in out}  # 25 s isn't a reaction sound
    assert out == sorted(out, key=lambda o: o["t"])


def test_per_item_cap_and_cut_words_ignored(tmp_path):
    words = W(*[(i * 0.5, "creeper") for i in range(14)])  # 0-6.5 s, all inside the 0-6 s clip except the last
    s, p, pdir = _project(tmp_path, words=words, rms=[-20.0] * 160, video_clips=[dict(start=0, source_in=0, source_out=6)])
    out = broll.suggest(p, pdir, ITEMS[:1], gap=0.1)
    assert len(out) == 3 and all(o["t"] < 6 for o in out)


def test_api_broll(server, tmp_path):
    _, p, _ = server.req("POST", "/api/projects", {"name": "b"})
    st, r, _ = server.req("POST", f"/api/projects/{p['id']}/fx/broll/suggest")
    assert st == 200 and r["suggestions"] == [] and "empty" in r["note"]
    import cv2
    import numpy as np
    ok, png = cv2.imencode(".png", np.full((20, 20, 3), 9, np.uint8))
    _, img, _ = server.req("POST", "/api/library/images?name=Creeper", raw=png.tobytes())
    st, it, _ = server.req("PUT", f"/api/library/images/{img['id']}", {"tags": ["Explosion!", "boom", "boom", "  "]})
    assert st == 200 and it["tags"] == ["explosion", "boom"] and it["name"] == "Creeper"
    st, r, _ = server.req("POST", f"/api/projects/{p['id']}/fx/broll/suggest")
    assert st == 200 and r["suggestions"] == []  # nothing said yet
