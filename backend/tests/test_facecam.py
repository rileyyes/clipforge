"""Phase 9: face cam — layout, following cuts, shapes, hide/full ranges, rendering."""
from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app import facecam as FC
from app import render as R
from app.media import build_asset
from app.projects import ProjectStore
from app.config import Settings
from app.render import render_project
from app.schema import SCHEMA_VERSION, FaceCam, Project
from app.storage import new_id

from test_audio_transitions import Ctx

W, H = 640, 360
COLOURS = {"red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0)}


def _cam_video(path: Path):
    """8 s: red, green, blue, yellow — 2 s each. The colour tells the cam time."""
    ins = []
    for c in COLOURS:
        ins += ["-f", "lavfi", "-i", f"color={c}:s=320x240:r=30:d=2"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-f", "lavfi", "-i", "sine=f=300:d=8",
                    "-filter_complex", "[0][1][2][3]concat=n=4:v=1:a=0[v]", "-map", "[v]", "-map", "4:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def _main_video(path: Path, d=10):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=gray:s={W}x{H}:r=30:d={d}",
                    "-f", "lavfi", "-i", f"sine=f=440:d={d}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def make(tmp_path, main_clips, cam=None, cam_file=None, **fc):
    s = Settings(workspace=tmp_path)
    st = ProjectStore(tmp_path / "projects")
    p = st.create("fc")
    pdir = st.dir(p.id)
    orig = pdir / "media" / "original"
    mid, cid = new_id(), new_id()
    main = build_asset(s, mid, _main_video(orig / f"{mid}.mp4"), "game.mp4")
    camf = cam_file(orig / f"{cid}.mp4") if cam_file else _cam_video(orig / f"{cid}.mp4")
    cam_a = build_asset(s, cid, camf, "cam.mp4")
    d = p.model_dump(mode="json")
    d["media"] = [main.model_dump(mode="json"), cam_a.model_dump(mode="json")]
    d["output"] = {"width": W, "height": H, "fps": 30, "fit_mode": "fit"}
    d["audio"] = {"normalize": False, "ducking": "off"}
    d["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, **c} for c in main_clips]
    d["facecam"] = {"media_id": cid, "main_media_id": mid, **fc}
    return s, Project.model_validate(d), pdir


def frame(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)


def near(px, rgb, tol=50):
    return all(abs(int(a) - b) <= tol for a, b in zip(px, rgb))


def render(s, p, pdir, name="o", **kw):
    r = render_project(Ctx(), dataclasses.replace(s, **kw) if kw else s, p, pdir, name, "high", "libx264")
    assert r["validation"]["ok"], r["validation"]
    return pdir / "exports" / r["file"], r


# ---------------------------------------------------------------- layout
@pytest.mark.parametrize("corner", ["top_left", "top_right", "bottom_left", "bottom_right"])
def test_corner_boxes_keep_the_same_gap_on_both_edges(corner):
    fc = FaceCam(media_id="a" * 32, main_media_id="b" * 32, corner=corner, size=0.25, margin=0.03, shape="rect")
    b = FC.layout_box(fc, 1920, 1080, 4 / 3)
    x, y, w, h = FC.box_px(b, 1920, 1080)
    assert abs(w - 480) <= 2 and abs(h - 360) <= 2
    gap = 0.03 * 1920
    gx = x if "left" in corner else 1920 - x - w
    gy = y if "top" in corner else 1080 - y - h
    assert abs(gx - gap) <= 2 and abs(gy - gap) <= 2


def test_circle_is_square_and_huge_cams_stay_on_screen():
    fc = FaceCam(media_id="a" * 32, main_media_id="b" * 32, shape="circle", size=0.2)
    _, _, w, h = FC.box_px(FC.layout_box(fc, 1080, 1920, 16 / 9), 1080, 1920)
    assert w == h
    big = FaceCam(media_id="a" * 32, main_media_id="b" * 32, shape="rect", size=0.9)
    b = FC.layout_box(big, 1920, 1080, 9 / 16)  # tall phone cam in a wide video
    assert b.y >= 0 and b.y + b.h <= 1.0001 and b.x + b.w <= 1.0001


# ---------------------------------------------------------------- following cuts
def test_parts_follow_cuts_offset_hidden_and_full(tmp_path):
    clips = [dict(start=0, source_in=1, source_out=4), dict(start=3, source_in=6, source_out=9)]
    s, p, pdir = make(tmp_path, clips, offset=-0.5, hidden=[{"start": 2, "end": 2.5}],
                      full=[{"start": 7, "end": 8}])
    parts = FC.cam_parts(p)
    got = [(round(x.clip.start, 3), round(x.clip.source_in, 3), round(x.clip.source_out, 3), x.full,
            x.fade_in > 0, x.fade_out > 0) for x in parts]
    assert got == [
        (0.0, 0.5, 1.5, False, False, True),    # main 1-2, fades out before the hidden bit
        (1.5, 2.0, 3.5, False, True, False),    # main 2.5-4, fades back in
        (3.0, 5.5, 6.5, False, False, False),   # second clip: main 6-7
        (4.0, 6.5, 7.5, True, False, False),    # main 7-8 fills the screen
        (5.0, 7.5, round(p.media[1].duration, 3), False, False, False),  # main 8-8.5: cam ends at 8 s
    ]


def test_no_cam_where_it_doesnt_exist_and_when_disabled(tmp_path):
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=3)], offset=-2)
    assert [(x.clip.source_in, x.clip.start) for x in FC.cam_parts(p)] == [(0.0, 2.0)]
    d = p.model_dump(mode="json")
    d["facecam"]["enabled"] = False
    assert FC.cam_parts(Project.model_validate(d)) == []


def test_validation(tmp_path):
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=3)])
    d = p.model_dump(mode="json")
    d["facecam"]["media_id"] = d["facecam"]["main_media_id"]
    with pytest.raises(ValueError, match="different recording"):
        Project.model_validate(d)
    d["facecam"]["media_id"] = "f" * 32
    with pytest.raises(ValueError, match="unknown media"):
        Project.model_validate(d)


# ---------------------------------------------------------------- render
def test_render_corner_cam_follows_the_cuts(tmp_path):
    # timeline 0-2 = main 4-6, timeline 2-4 = main 0-2. Offset +1: cam time = main + 1
    clips = [dict(start=0, source_in=4, source_out=6), dict(start=2, source_in=0, source_out=2)]
    s, p, pdir = make(tmp_path, clips, offset=1, corner="bottom_right", size=0.3, shape="rect",
                      border=0, shadow=False)
    out, _ = render(s, p, pdir)
    x, y, w, h = FC.box_px(FC.layout_box(p.facecam, W, H, 320 / 240), W, H)
    cx, cy = x + w // 2, y + h // 2
    f = frame(out, 0.5)             # main 4.5 -> cam 5.5 = blue
    assert near(f[cy, cx], COLOURS["blue"]) and near(f[30, 30], (128, 128, 128))
    f = frame(out, 1.6)             # main 5.6 -> cam 6.6 = yellow
    assert near(f[cy, cx], COLOURS["yellow"])
    f = frame(out, 2.5)             # main 0.5 -> cam 1.5 = red
    assert near(f[cy, cx], COLOURS["red"])
    f = frame(out, 3.5)             # main 1.5 -> cam 2.5 = green
    assert near(f[cy, cx], COLOURS["green"])
    assert near(f[y - 4, cx], (128, 128, 128)) and near(f[cy, x - 4], (128, 128, 128))  # just outside


def test_circle_border_and_shadow(tmp_path):
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=2)], corner="top_left", size=0.3,
                      shape="circle", border=0.006, border_color="#ffffff", shadow=True)
    out, _ = render(s, p, pdir)
    x, y, w, h = FC.box_px(FC.layout_box(p.facecam, W, H, 1), W, H)
    f = frame(out, 1.0)
    assert near(f[y + h // 2, x + w // 2], COLOURS["red"])          # centre: the cam
    assert near(f[y + 3, x + 3], (128, 128, 128), 40)               # box corner: outside the circle
    b = int(round(0.006 * W))
    assert f[y + h // 2, x - b // 2 - 1].mean() > 200               # left edge: white border
    below = f[y + h + b + 3, x + w // 2]
    assert below.mean() < 120                                       # shadow under it


def test_hidden_and_full_screen_ranges(tmp_path):
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=6)], corner="bottom_left",
                      shape="rect", border=0, shadow=False,
                      hidden=[{"start": 1.5, "end": 3}], full=[{"start": 4, "end": 5}])
    out, _ = render(s, p, pdir)
    x, y, w, h = FC.box_px(FC.layout_box(p.facecam, W, H, 320 / 240), W, H)
    cx, cy = x + w // 2, y + h // 2
    assert near(frame(out, 0.8)[cy, cx], COLOURS["red"])
    assert near(frame(out, 2.2)[cy, cx], (128, 128, 128))           # hidden
    r, g, _ = frame(out, 1.4)[cy, cx]                               # fading out: partly see-through
    assert 140 < r < 245 and 20 < g < 120, (r, g)
    full = frame(out, 4.5)                                          # cam time 4.5 = blue, everywhere
    assert near(full[20, 20], COLOURS["blue"]) and near(full[H // 2, W // 2], COLOURS["blue"])
    after = frame(out, 5.5)                                         # back in the corner (cam 5.5 = blue)
    assert near(after[cy, cx], COLOURS["blue"]) and near(after[20, 20], (128, 128, 128))


def test_block_render_with_face_cam_matches_one_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "BLOCK_S", 1.0)
    clips = [dict(start=0, source_in=0.5, source_out=3), dict(start=2.5, source_in=4, source_out=6.5)]
    s, p, pdir = make(tmp_path, clips, shape="rounded", hidden=[{"start": 1.8, "end": 2.3}])
    a, _ = render(s, p, pdir, "a")
    b, _ = render(s, p, pdir, "b", block_render=False)

    def all_frames(path):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             check=True, capture_output=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.int16)
    fa, fb = all_frames(a), all_frames(b)
    assert fa.shape == fb.shape
    assert np.abs(fa - fb).mean(axis=(1, 2, 3)).max() < 2.0


def test_project_without_face_cam_renders_as_before(tmp_path):
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=1)])
    d = p.model_dump(mode="json")
    d["facecam"] = None
    out, _ = render(s, Project.model_validate(d), pdir)
    assert near(frame(out, 0.5)[H - 40, W - 60], (128, 128, 128))


def test_old_projects_migrate(tmp_path):
    from app.schema import migrate
    d = {"schema_version": 4, "id": "a" * 32, "name": "x"}
    assert migrate(d)["schema_version"] == SCHEMA_VERSION
    assert json.loads(json.dumps(Project.model_validate(migrate(d)).model_dump(mode="json")))["facecam"] is None


# ---------------------------------------------------------------- background removal
ASTRONAUT = None
try:
    import skimage  # only for its bundled sample photo of a person
    ASTRONAUT = Path(skimage.__file__).parent / "data" / "astronaut.png"
except ImportError:  # pragma: no cover
    pass
PERSON = Path(__file__).parent / "data" / "person.jpg"


def _person_video(path: Path):
    src = PERSON if PERSON.exists() else ASTRONAUT
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-t", "3", "-i", str(src),
                    "-vf", "scale=480:480,format=yuv420p", "-c:v", "libx264", str(path)], check=True)
    return path


def test_person_mask_on_a_real_photo():
    import cv2
    from app import matte
    img = cv2.imread(str(PERSON))
    m = matte.person_mask(img)
    h, w = m.shape
    assert m[int(h * 0.3), int(w * 0.45)] > 0.8      # face
    assert m[int(h * 0.05), int(w * 0.05)] < 0.2     # flag in the corner (background)
    assert 0.2 < (m > 0.5).mean() < 0.8


def test_remove_background_renders_only_the_person(tmp_path):
    import cv2
    from app import matte
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=3)], cam_file=_person_video,
                      corner="bottom_right", size=0.4, shape="rect", remove_bg=True)
    out, r = render(s, p, pdir)
    assert matte.matte_path(pdir, p.media[1]).is_file()
    x, y, w, h = FC.box_px(FC.layout_box(p.facecam, W, H, 1.0), W, H)
    f = frame(out, 1.5)
    mask = cv2.resize(matte.person_mask(cv2.imread(str(PERSON))), (w, h))
    fg = np.argwhere(mask > 0.95)
    bg = np.argwhere(mask < 0.02)
    assert len(fg) > 500 and len(bg) > 500
    rng = np.random.default_rng(1)
    on_bg = [f[y + a, x + b] for a, b in bg[rng.choice(len(bg), 60)]]
    on_fg = [f[y + a, x + b] for a, b in fg[rng.choice(len(fg), 60)]]
    grey = sum(near(px, (128, 128, 128), 20) for px in on_bg) / len(on_bg)
    kept = sum(not near(px, (128, 128, 128), 20) for px in on_fg) / len(on_fg)
    assert grey > 0.9, grey      # background replaced by the game picture
    assert kept > 0.8, kept      # the person is still there
    # second export reuses the cut-out (no model run)
    mtime = matte.matte_path(pdir, p.media[1]).stat().st_mtime_ns
    render(s, p, pdir, "again")
    assert matte.matte_path(pdir, p.media[1]).stat().st_mtime_ns == mtime


def test_remove_background_is_off_by_default(tmp_path):
    from app import matte
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=1)])
    assert p.facecam.remove_bg is False
    render(s, p, pdir)
    assert not matte.matte_path(pdir, p.media[1]).exists()


# ---------------------------------------------------------------- API
def test_api_face_cam_flow(server, tmp_path):
    from test_sync import _speechy, _as_cam
    from test_api import new_project, clip as mkclip
    rate = 8000
    voice = _speechy(20, 5)
    camv = _as_cam(voice, 1.25, 18, 6)

    def mp4(x, name, colour):
        raw = tmp_path / f"{name}.f32"
        (x / (np.abs(x).max() + 1e-9) * 0.8).astype(np.float32).tofile(raw)
        out = tmp_path / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={colour}:s=320x240:r=30:d={len(x) / rate}",
                        "-f", "f32le", "-ar", str(rate), "-ac", "1", "-i", str(raw), "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], check=True)
        return out
    p = new_project(server)
    _, r1, _ = server.upload(p["id"], mp4(voice, "game", "gray"))
    _, r2, _ = server.upload(p["id"], mp4(camv, "cam", "red"))
    main, cam = r1["media"]["id"], r2["media"]["id"]
    for j in (r1.get("job_id"), r2.get("job_id")):
        if j:
            server.wait_job(j)

    # sync by sound
    st, job, _ = server.req("POST", f"/api/projects/{p['id']}/facecam/sync", {"media_id": cam, "main_media_id": main})
    assert st == 202
    job = server.wait_job(job["id"], timeout=120)
    assert job["status"] == "succeeded", job
    assert abs(job["result"]["offset"] - 1.25) < 0.04 and job["result"]["confidence"] >= 0.5, job["result"]

    # no face in a red picture
    st, body, _ = server.req("POST", f"/api/projects/{p['id']}/facecam/face-crop", {"media_id": cam})
    assert st == 422 and "face" in body["error"].lower()

    # save timeline + face cam
    _, p, _ = server.req("GET", f"/api/projects/{p['id']}")
    link = new_id()
    p["timeline"]["tracks"][0]["clips"] = [mkclip(main, 0, 2, 8, link_id=link)]
    p["timeline"]["tracks"][2]["clips"] = [mkclip(main, 0, 2, 8, link_id=link)]
    fc = {"media_id": cam, "main_media_id": main, "offset": job["result"]["offset"], "corner": "top_right",
          "shape": "circle"}
    st, saved, _ = server.req("PUT", f"/api/projects/{p['id']}/timeline", {
        "base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
        "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"}, "facecam": fc})
    assert st == 200, saved
    assert saved["facecam"]["corner"] == "top_right"
    # leaving it out keeps it; null removes it (and validation errors are 422)
    st, saved, _ = server.req("PUT", f"/api/projects/{p['id']}/timeline", {
        "base_edit_revision": saved["edit_revision"], "timeline": saved["timeline"], "output": saved["output"]})
    assert st == 200 and saved["facecam"] is not None
    st, bad, _ = server.req("PUT", f"/api/projects/{p['id']}/timeline", {
        "base_edit_revision": saved["edit_revision"], "timeline": saved["timeline"], "output": saved["output"],
        "facecam": {**fc, "media_id": main}})
    assert st == 422

    # the cam's media can't be deleted while it's in use
    st, body, _ = server.req("DELETE", f"/api/projects/{p['id']}/media/{cam}")
    assert st == 409 and "face cam" in body["error"]

    # export: cam visible in the top-right circle
    st, job, _ = server.req("POST", f"/api/projects/{p['id']}/exports", {"filename": "fc", "quality": "draft"})
    job = server.wait_job(job["id"], timeout=300)
    assert job["status"] == "succeeded" and job["result"]["validation"]["ok"], job
    out = server.settings.projects_dir / p["id"] / "exports" / job["result"]["file"]
    from app.schema import FaceCam as FCm
    x, y, w, h = FC.box_px(FC.layout_box(FCm(**fc), 640, 360, 1), 640, 360)
    f = frame(out, 3.0)
    assert near(f[y + h // 2, x + w // 2], (255, 0, 0)) and near(f[y + 2, x + 2], (128, 128, 128), 40)

    # background removal prepared ahead (no person in red: fine, it still runs)
    st, job, _ = server.req("POST", f"/api/projects/{p['id']}/facecam/matte", {"media_id": cam})
    assert st == 202
    job = server.wait_job(job["id"], timeout=300)
    assert job["status"] == "succeeded", job
    _, pp, _ = server.req("GET", f"/api/projects/{p['id']}")
    assert pp["mattes"] == [cam]

    # remove the face cam -> media can be deleted, matte goes too
    st, saved, _ = server.req("PUT", f"/api/projects/{p['id']}/timeline", {
        "base_edit_revision": pp["edit_revision"], "timeline": pp["timeline"], "output": pp["output"], "facecam": None})
    assert st == 200 and saved["facecam"] is None
    assert server.req("DELETE", f"/api/projects/{p['id']}/media/{cam}")[0] == 204
    assert not (server.settings.projects_dir / p["id"] / "media" / "matte" / f"{cam}.mp4").exists()


def test_layout_vectors_shared_with_the_editor():
    """The Editor's preview (frontend/src/timeline/facecam.ts) is tested against this file too."""
    cases = json.loads((Path(__file__).parent / "data" / "facecam_layout_vectors.json").read_text())
    for c in cases:
        b = FC.layout_box(FaceCam(**c["fc"]), c["W"], c["H"], c["aspect"])
        assert b.model_dump() == c["box"]


# ---------------------------------------------------------------- Shorts
def test_short_with_stacked_face_cam(tmp_path):
    from app import shorts as SH
    s, p, pdir = make(tmp_path, [dict(start=0, source_in=0, source_out=6)], offset=0, corner="bottom_right")
    src = p.model_dump(mode="json")
    main = p.media[0].model_dump(mode="json")
    n = iter(range(1000))
    nid = lambda: f"{next(n):032x}"  # noqa: E731
    doc = SH.build_short_project(src, main, 1, 5, [], 1.0, "", False, nid, "stacked")
    st = ProjectStore(tmp_path / "projects")
    short = st.create_from(p.id, "short", doc)
    assert short.facecam.corner == "custom" and short.facecam.box.h == SH.STACK_CAM
    out, _ = render(s, short, st.dir(short.id))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.5", "-i", str(out), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(1920, 1080, 3).astype(int)
    assert near(f[300, 540], COLOURS["green"]) and near(f[20, 20], COLOURS["green"])  # cam: main 2.5 -> green, full width
    assert near(f[1400, 540], (128, 128, 128)) and near(f[1900, 20], (128, 128, 128))  # game fills the rest
    assert near(f[790, 540], (128, 128, 128))
    # corner layout keeps the cam's corner; "none" drops it; another recording drops it
    assert SH.build_short_project(src, main, 1, 5, [], 1.0, "", False, nid, "corner")["facecam"]["corner"] == "bottom_right"
    assert SH.build_short_project(src, main, 1, 5, [], 1.0, "", False, nid, "none")["facecam"] is None
    cam = p.media[1].model_dump(mode="json")
    assert SH.build_short_project(src, cam, 1, 5, [], 1.0, "", False, nid, "stacked")["facecam"] is None
