"""Phase 8.7: block rendering (final video encoded in cached blocks, joined by copy).

A block render must match a one-pass render frame for frame, including effects,
overlays, transitions and captions that straddle block boundaries."""
from __future__ import annotations

import dataclasses
import json
import subprocess
from fractions import Fraction

import numpy as np
import pytest

from app import render as R
from app.storage import new_id
from app.render import block_windows, render_project
from app.schema import Project

from test_audio_transitions import Ctx
from test_effects import _project

W, H = 320, 180


def _frames(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.int16)


def _pcm(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "48000", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float64)


def _busy(tmp_path):
    """Everything that crosses a 1 s block boundary at 30 fps."""
    effects = [dict(kind="zoom", source_time=0.8, duration=0.6, scale=1.5),       # 0.8-1.4
               dict(kind="shake", source_time=1.9, duration=0.3),                 # 1.9-2.2
               dict(kind="flash", source_time=2.95, duration=0.15),               # 2.95-3.1
               dict(kind="text", source_time=3.7, duration=0.8, text="WOW", color="#ffde00", y=0.3),
               dict(kind="censor", source_time=2.0, duration=0.4, sound="beep")]
    vc = [dict(start=0, source_in=0, source_out=3.5),
          dict(start=3.5, source_in=4, source_out=6.3, transition_in={"kind": "wipe_left", "duration": 0.6})]
    ac = [{k: v for k, v in c.items() if k != "transition_in"} for c in vc]
    s, p, pdir = _project(tmp_path, effects=effects, captions={"enabled": True, "style": "highlight"},
                          video_clips=vc, audio_clips=ac)
    d = p.model_dump(mode="json")
    mid = d["media"][0]["id"]
    d["timeline"]["tracks"][1]["clips"] = [{
        "id": new_id(), "media_id": mid, "start": 1.5, "source_in": 0, "source_out": 2.2,
        "transform": {"scale": 0.35},
        "keyframes": {"x": [{"t": 0, "v": -100}, {"t": 2.2, "v": 100}]}}]
    return s, Project.model_validate(d), pdir


def test_block_windows():
    f30 = Fraction(30)
    assert block_windows(90, f30, 1) == [(0, 30), (30, 60), (60, 90)]
    assert block_windows(95, f30, 1) == [(0, 30), (30, 60), (60, 95)]   # tiny tail folded in
    assert block_windows(105, f30, 1) == [(0, 30), (30, 60), (60, 90), (90, 105)]
    assert block_windows(10, f30, 1) == [(0, 10)]
    w = block_windows(54000, Fraction(30000, 1001))
    assert w[0] == (0, 599) and w[-1][1] == 54000 and all(a < b for a, b in w)
    assert all(w[i][1] == w[i + 1][0] for i in range(len(w) - 1))


def test_block_render_matches_one_pass_render(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "BLOCK_S", 1.0)
    s, p, pdir = _busy(tmp_path)
    blk = render_project(Ctx(), s, p, pdir, "blocks", "high", "libx264")
    one = render_project(Ctx(), dataclasses.replace(s, block_render=False), p, pdir, "one", "high", "libx264")
    assert blk["validation"]["ok"], blk["validation"]
    assert one["validation"]["ok"], one["validation"]
    assert blk["validation"]["blocks"]["count"] == 6 and "blocks" not in one["validation"]
    a = _frames(pdir / "exports" / blk["file"])
    b = _frames(pdir / "exports" / one["file"])
    assert a.shape == b.shape and a.shape[0] == 174  # 3.5 + 2.9 - 0.6 s overlap = 5.8 s at 30 fps
    per_frame = np.abs(a - b).mean(axis=(1, 2, 3))
    # only encoder noise: a frame shifted by one would differ by >10 on testsrc2
    assert per_frame.max() < 2.5, (int(per_frame.argmax()), float(per_frame.max()))
    # and the effects really are in there (not both renders missing them)
    plain = a[45] - a[15]
    assert np.abs(plain).mean() > 5
    pa, pb = _pcm(pdir / "exports" / blk["file"]), _pcm(pdir / "exports" / one["file"])
    n = min(len(pa), len(pb))
    assert abs(len(pa) - len(pb)) < 1200
    assert np.abs(pa[:n] - pb[:n]).mean() < 0.02 * np.abs(pb[:n]).mean() + 1


def test_reexport_after_small_edit_reencodes_one_block(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "BLOCK_S", 1.0)
    s, p, pdir = _busy(tmp_path)
    r1 = render_project(Ctx(), s, p, pdir, "a", "draft", "libx264")
    assert r1["validation"]["blocks"]["reused"] == 0
    r2 = render_project(Ctx(), s, p, pdir, "b", "draft", "libx264")
    assert r2["validation"]["blocks"]["reused"] == 6 and r2["validation"]["cache"]["rendered"] == 0
    d = p.model_dump(mode="json")
    d["effects"].append({"id": new_id(), "media_id": d["media"][0]["id"], "kind": "flash",
                         "source_time": 5.0, "duration": 0.1})  # timeline 4.5 s (block 4)
    r3 = render_project(Ctx(), s, Project.model_validate(d), pdir, "c", "draft", "libx264")
    assert r3["validation"]["ok"]
    assert r3["validation"]["blocks"]["reused"] == 5
    f3 = _frames(pdir / "exports" / r3["file"])
    f2 = _frames(pdir / "exports" / r2["file"])
    assert f3[136].mean() > f2[136].mean() + 40  # the new flash
    assert np.abs(f3[:120] - f2[:120]).max() == 0   # copied blocks are bit-identical


def test_caption_word_change_only_touches_nearby_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "BLOCK_S", 1.0)
    s, p, pdir = _busy(tmp_path)
    render_project(Ctx(), s, p, pdir, "a", "draft", "libx264")
    f = next((pdir / "analysis").glob("*.json"))
    data = json.loads(f.read_text())
    assert data["words"][-1]["text"] == " damn"   # source 5.2 s -> timeline 4.1 s (block 4)
    data["words"][-1]["text"] = " dang"
    f.write_text(json.dumps(data))
    r = render_project(Ctx(), s, p, pdir, "b", "draft", "libx264")
    assert r["validation"]["ok"]
    assert 3 <= r["validation"]["blocks"]["reused"] <= 5  # blocks 0-2 copied, the caption's block redone


@pytest.mark.parametrize("fps", [30, 25])
def test_long_ish_timeline_frame_exact(tmp_path, monkeypatch, fps):
    """Many short blocks over a plain clip: no dropped or doubled frame at any boundary."""
    monkeypatch.setattr(R, "BLOCK_S", 0.4)
    s, p, pdir = _project(tmp_path, video_clips=[dict(start=0, source_in=0.5, source_out=7.5)])
    d = p.model_dump(mode="json")
    d["output"]["fps"] = fps
    p = Project.model_validate(d)
    r = render_project(Ctx(), s, p, pdir, "x", "high", "libx264")
    one = render_project(Ctx(), dataclasses.replace(s, block_render=False), p, pdir, "y", "high", "libx264")
    a, b = _frames(pdir / "exports" / r["file"]), _frames(pdir / "exports" / one["file"])
    assert a.shape == b.shape and a.shape[0] == 7 * fps
    assert np.abs(a - b).mean(axis=(1, 2, 3)).max() < 2.5
