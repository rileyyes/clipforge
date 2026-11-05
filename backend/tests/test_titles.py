"""Phase 10: titles (lower third, big title, top banner, subscribe, chapter card)."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from app import render as R
from app.render import render_project
from app.schema import Project
from app.storage import new_id

from test_audio_transitions import Ctx
from test_facecam import make, frame, near, render as frender, W, H

ACCENT = (255, 90, 60)


def proj(tmp_path, titles):
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=6)])
    d = p.model_dump(mode="json")
    d["facecam"] = None
    d["timeline"]["titles"] = [{"id": new_id(), **t} for t in titles]
    return s, Project.model_validate(d), pdir


def share(img, rgb, tol=50):
    return float(np.mean(np.all(np.abs(img - np.array(rgb)) <= tol, axis=2)))


def test_lower_third_slides_in_and_shows_text(tmp_path):
    s, p, pdir = proj(tmp_path, [dict(start=1, duration=3, template="lower_third", text="RileyPlays", subtext="New video every Friday")])
    out, _ = frender(s, p, pdir)
    before, during, after = frame(out, 0.5), frame(out, 2.5), frame(out, 4.6)
    zone = (slice(int(H * 0.6), int(H * 0.92)), slice(0, int(W * 0.5)))
    assert share(before[zone], ACCENT) < 0.001 and share(after[zone], ACCENT) < 0.001
    assert share(during[zone], ACCENT, 40) > 0.001                 # the accent bar (thin at 360p)
    assert share(during[zone], (255, 255, 255), 40) > 0.004         # white text
    assert share(during[zone], (128, 128, 128), 6) < 0.9            # darkened box behind it
    mid_slide = frame(out, 1.12)                                    # still sliding in from the left
    cols = np.where(np.all(np.abs(mid_slide[zone] - np.array(ACCENT)) <= 40, axis=2).any(axis=0))[0]
    cols_d = np.where(np.all(np.abs(during[zone] - np.array(ACCENT)) <= 40, axis=2).any(axis=0))[0]
    assert len(cols_d) and (not len(cols) or cols.min() < cols_d.min())


@pytest.mark.parametrize("tpl,zone,rgb", [
    ("big_title", (slice(int(H * 0.35), int(H * 0.55)), slice(int(W * 0.25), int(W * 0.75))), (255, 255, 255)),
    ("top_banner", (slice(0, int(H * 0.08)), slice(0, W)), ACCENT),
    ("subscribe", (slice(int(H * 0.55), int(H * 0.82)), slice(int(W * 0.55), W)), ACCENT),
])
def test_templates_draw_where_they_should(tmp_path, tpl, zone, rgb):
    s, p, pdir = proj(tmp_path, [dict(start=0.5, duration=3, template=tpl, text="HELLO THERE", align="right")])
    out, _ = frender(s, p, pdir)
    assert share(frame(out, 2.0)[zone], rgb, 45) > 0.03, tpl
    assert share(frame(out, 4.5)[zone], rgb, 45) < 0.002


def test_chapter_card_dims_the_picture(tmp_path):
    s, p, pdir = proj(tmp_path, [dict(start=1, duration=2, template="chapter", text="The boss fight", subtext="Part 2")])
    out, _ = frender(s, p, pdir)
    assert frame(out, 2.0)[20:60, 20:60].mean() < 100 < frame(out, 0.5)[20:60, 20:60].mean()


def test_titles_with_block_rendering_match_one_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "BLOCK_S", 1.0)
    s, p, pdir = proj(tmp_path, [dict(start=0.6, duration=2.0, template="lower_third", text="Across blocks"),
                                 dict(start=3.5, duration=2, template="big_title", text="BOOM", subtext="wow")])
    a, ra = frender(s, p, pdir, "a")
    b, _ = frender(s, p, pdir, "b", block_render=False)
    for t in (0.7, 1.0, 1.5, 2.5, 3.6, 4.0, 5.4):
        assert np.abs(frame(a, t) - frame(b, t)).mean() < 2.0, t
    # changing one title re-encodes only its blocks
    d = p.model_dump(mode="json")
    d["timeline"]["titles"][1]["text"] = "BANG"
    _, rc = frender(s, Project.model_validate(d), pdir, "c")
    assert 2 <= rc["validation"]["blocks"]["reused"] < rc["validation"]["blocks"]["count"]


def test_validation():
    with pytest.raises(ValueError):
        Project.model_validate({"id": "a" * 32, "name": "x", "timeline": {"tracks": [], "titles": [
            {"id": "b" * 32, "start": 0, "duration": 0.1}]}})
    with pytest.raises(ValueError):
        Project.model_validate({"id": "a" * 32, "name": "x", "timeline": {"tracks": [], "titles": [
            {"id": "b" * 32, "start": 0, "template": "spinning_cube"}]}})
