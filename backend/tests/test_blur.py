"""Phase 10: privacy blur (blur / pixelate / black, rect / ellipse, tracking)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from app import blur as B
from app import render as R
from app.media import build_asset
from app.projects import ProjectStore
from app.config import Settings
from app.schema import Project
from app.storage import new_id

from test_facecam import frame as _frame, render as frender

W, H = 640, 360


def detail(img):
    return float(np.abs(np.diff(img.astype(float), axis=1)).mean())


def proj(tmp_path, blurs, src="testsrc2", d=6):
    s = Settings(workspace=tmp_path)
    st = ProjectStore(tmp_path / "projects")
    p = st.create("blur")
    pdir = st.dir(p.id)
    mid = new_id()
    f = pdir / "media" / "original" / f"{mid}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=s={W}x{H}:r=30:d={d}",
                    "-f", "lavfi", "-i", f"sine=f=440:d={d}", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(f)], check=True)
    a = build_asset(s, mid, f, "v.mp4")
    d_ = p.model_dump(mode="json")
    d_["media"] = [a.model_dump(mode="json")]
    d_["output"] = {"width": W, "height": H, "fps": 30, "fit_mode": "fit"}
    d_["audio"] = {"normalize": False, "ducking": "off"}
    d_["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": d}]
    d_["timeline"]["blurs"] = [{"id": new_id(), **b} for b in blurs]
    return s, Project.model_validate(d_), pdir


def frame(out, t):
    return _frame(out, t)


BOX = {"x": 0.25, "y": 0.25, "w": 0.3, "h": 0.4}


def region(img, k=BOX, inset=6):
    y0, x0 = int(k["y"] * H) + inset, int(k["x"] * W) + inset
    return img[y0:int((k["y"] + k["h"]) * H) - inset, x0:int((k["x"] + k["w"]) * W) - inset]


@pytest.mark.parametrize("mode", ["blur", "pixelate", "black"])
def test_modes_hide_only_the_box_and_only_while_on(tmp_path, mode):
    s, p, pdir = proj(tmp_path, [dict(start=1, duration=2, mode=mode, keys=[{"t": 1, **BOX}])])
    out, _ = frender(s, p, pdir)
    ref, _ = frender(*proj(tmp_path / "ref", []))
    on, plain = frame(out, 2.0), frame(ref, 2.0)
    if mode == "black":
        assert region(on).mean() < 25 and region(plain).mean() > 60
    else:
        assert np.abs(region(on) - region(plain)).mean() > 8          # the box changed
        if mode == "blur":                                            # and its sharp edges are gone
            edge = lambda img: np.abs(np.diff(img.mean(axis=2), axis=1)).max()  # noqa: E731
            assert edge(region(on)) < 0.4 * edge(region(plain))
    outside = (slice(0, 60), slice(0, 120))
    assert np.abs(on[outside] - plain[outside]).mean() < 2            # nothing else did
    assert np.abs(frame(out, 4.0) - frame(ref, 4.0)).mean() < 2       # and only while it's on


def test_ellipse_leaves_the_corners(tmp_path):
    s, p, pdir = proj(tmp_path, [dict(start=0, duration=3, mode="black", shape="ellipse", keys=[{"t": 0, **BOX}])])
    out, _ = frender(s, p, pdir)
    f = frame(out, 1.0)
    cx, cy = int((BOX["x"] + BOX["w"] / 2) * W), int((BOX["y"] + BOX["h"] / 2) * H)
    assert f[cy, cx].max() < 30
    assert f[int(BOX["y"] * H) + 2, int(BOX["x"] * W) + 2].max() > 40   # box corner: not blacked out


def test_moving_keys_and_block_render(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "BLOCK_S", 1.0)
    keys = [{"t": 0.5, "x": 0.0, "y": 0.3, "w": 0.2, "h": 0.3}, {"t": 4.5, "x": 0.8, "y": 0.3, "w": 0.2, "h": 0.3}]
    s, p, pdir = proj(tmp_path, [dict(start=0.5, duration=4, mode="black", keys=keys)])
    a, _ = frender(s, p, pdir, "a")
    b, _ = frender(s, p, pdir, "b", block_render=False)
    for t, xc in ((1.0, 0.1 + 0.8 * 0.5 / 4), (2.5, 0.5), (4.0, 0.1 + 0.8 * 3.5 / 4)):
        fa = frame(a, t)
        assert fa[int(0.45 * H), int(xc * W)].max() < 30, t                 # box is where it should be
        assert np.abs(fa - frame(b, t)).mean() < 1.5                         # blocks = one pass


def test_long_tracks_are_cheap_expressions():
    keys = [{"t": i * 0.1, "cx": i, "cy": 0} for i in range(240)]
    e = B.position_expr(keys, "cx")
    assert e.count("if(") <= 245 and len(e) < 40000
    # evaluate it like FFmpeg would at a few times
    import re
    def ev(t):
        py = re.sub(r"if\(", "_if(", e.replace("lt(t,", "_lt(t,").replace("gte(t,", "_gte(t,"))
        return eval(py, {"_if": lambda c, a, b: a if c else b, "_lt": lambda a, b: a < b, "_gte": lambda a, b: a >= b, "t": t})
    for t in (0.0, 1.05, 12.34, 23.9, 30):
        assert abs(ev(t) - min(239, t * 10)) < 1e-6


def _moving_square(path: Path, d=4):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"cellauto=s={W}x{H}:rate=30:rule=110,format=gray,format=yuv420p",
                    "-f", "lavfi", "-i", f"color=c=white:s=60x60:r=30:d={d}", "-filter_complex",
                    f"[0:v]trim=duration={d},setpts=PTS-STARTPTS,boxblur=2[bg];"
                    f"[1:v]drawbox=x=10:y=10:w=40:h=40:color=red:t=fill[sq];"
                    f"[bg][sq]overlay=x='60+100*t':y='100+20*t'", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)],
                   check=True)


def test_tracking_follows_a_moving_square(tmp_path):
    src = tmp_path / "m.mp4"
    _moving_square(src)
    frames = B.grab("ffmpeg", src, 0, 4, 320, W, H)
    assert 38 <= len(frames) <= 41
    box = (60 / W, 100 / H, 60 / W, 60 / H)
    got = B.track(frames, box)
    for i in (10, 20, 35):
        t = i / B.TRACK_FPS
        ex, ey = (60 + 100 * t) / W, (100 + 20 * t) / H
        x, y, w, h, score = got[i]
        assert abs(x - ex) < 0.02 and abs(y - ey) < 0.03 and score > 0.6, (i, x, ex, y, ey, score)
    keep = B.simplify([(i / 10, g[0], g[1]) for i, g in enumerate(got)])
    assert 2 <= len(keep) <= 8  # a straight line needs few keys


def test_api_track_and_faces(server, tmp_path):
    from test_api import new_project
    src = tmp_path / "m.mp4"
    _moving_square(src, 5)
    p = new_project(server)
    _, r, _ = server.upload(p["id"], src)
    mid = r["media"]["id"]
    if r.get("job_id"):
        server.wait_job(r["job_id"])
    body = {"pieces": [{"media_id": mid, "src_start": 1.0, "src_end": 3.0, "speed": 1, "t_start": 0.0},
                       {"media_id": mid, "src_start": 4.0, "src_end": 5.0, "speed": 1, "t_start": 2.0}],
            "box": {"x": 160 / W, "y": 120 / H, "w": 60 / W, "h": 60 / H}}
    st, job, _ = server.req("POST", f"/api/projects/{p['id']}/blur/track", body)
    assert st == 202, job
    job = server.wait_job(job["id"], timeout=120)
    assert job["status"] == "succeeded", job
    keys = job["result"]["keys"]
    assert keys[0]["t"] == 0 and keys[-1]["t"] >= 2.8 and len(keys) < 60
    at = lambda t: float(np.interp(t, [k["t"] for k in keys], [k["x"] for k in keys]))  # noqa: E731
    assert abs(at(1.5) - (60 + 250) / W) < 0.03               # timeline 1.5 = source 2.5
    assert abs(at(2.5) - (60 + 450) / W) < 0.03               # second piece: timeline 2.5 = source 4.5
    assert job["result"]["lost"] == 0
    # faces: none in this video
    st, res, _ = server.req("POST", f"/api/projects/{p['id']}/blur/faces", {"media_id": mid, "time": 1.0})
    assert st == 200 and res["faces"] == []
