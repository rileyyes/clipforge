"""Phase 15: pop-up words + shapes (titles), freeze frame, reverse, green screen."""
from __future__ import annotations

import subprocess
from urllib.parse import quote

import numpy as np
import pytest
from pydantic import ValidationError

from app import titles
from app.schema import Clip, Title
from app.storage import new_id


def frame_at(path, t, w=64, h=36):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-s", f"{w}x{h}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(int)


# ---------------------------------------------------------------- titles: pop-up words and shapes
def test_free_titles_validate_and_render_to_ass():
    base = dict(id=new_id(), start=1, duration=3, text="NO WAY", x=0.3, y=0.7, rotation=25)
    for tpl in ("pop_text", "arrow", "circle", "box"):
        for anim in ("none", "pop", "typewriter", "slide_up", "bounce"):
            Title(**base, template=tpl, anim=anim)
    for bad in ({"x": 1.2}, {"rotation": 400}, {"anim": "spin"}, {"template": "star"}):
        with pytest.raises(ValidationError):
            Title(**{**base, "template": "pop_text", **bad})
    d = Title(**base, template="arrow", anim="bounce").model_dump()
    a = titles.ass([d], 1280, 720, "DejaVu Sans", None)
    assert "\\frz-25.0" in a and "\\p1" in a and "\\move(384,374,384,504" in a     # turned clockwise, dropped in
    tw = titles.ass([Title(**base, template="pop_text", anim="typewriter").model_dump()], 1280, 720, "DejaVu Sans", None)
    assert tw.count("\\alpha&HFF&") == len("NO WAY")
    # old templates are unchanged by the new fields
    old = Title(id=new_id(), start=0, duration=3, template="lower_third", text="Riley").model_dump()
    assert "\\frz" not in titles.ass([old], 1280, 720, "DejaVu Sans", None)


def test_shapes_render_where_they_are_placed(tmp_path):
    t = Title(id=new_id(), start=0, duration=3, template="circle", text="", x=0.25, y=0.5, accent="#ff0000", anim="none").model_dump()
    (tmp_path / "t.ass").write_text(titles.ass([t], 640, 360, "DejaVu Sans", None), encoding="utf-8")
    out = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=1", "-vf", f"subtitles={tmp_path / 't.ass'},select='gte(t\\,0.5)'",
                    "-frames:v", "1", str(out)], check=True, cwd=tmp_path)
    img = frame_at(out, 0, 640, 360)
    red = (img[:, :, 0] > 180) & (img[:, :, 1] < 80)
    ys, xs = np.nonzero(red)
    assert abs(xs.mean() - 160) < 6 and abs(ys.mean() - 180) < 6    # a ring centred at (25 %, 50 %)
    assert not red[180, 160]                                        # hollow


# ---------------------------------------------------------------- freeze + reverse
def _upload_ramp(c, tmp_path, secs=8):
    """A video that gets brighter every second, with sound."""
    v = tmp_path / "ramp.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=160x90:r=25:d={secs},format=yuv420p,geq=lum='T*28':cb=128:cr=128",
                    "-f", "lavfi", "-i", f"sine=f=300:d={secs}", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
                    "yuv420p", "-c:a", "aac", str(v)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "derive"})
    st, r, _ = c.upload(p["id"], v)
    c.wait_job(r["job_id"])
    return p["id"], r["media"], v


def _file(c, pid, m):
    return c.settings.projects_dir / pid / "media" / "original" / m["stored_name"]


def test_freeze_frame(server, tmp_path):
    c = server
    pid, m, v = _upload_ramp(c, tmp_path)
    st, r, _ = c.req("POST", f"/api/projects/{pid}/media/{m['id']}/derive", {"kind": "freeze", "t": 4.0, "seconds": 2.5})
    assert st == 201, r
    f = r["media"]
    assert abs(f["duration"] - 2.5) < 0.1 and f["has_video"] and not f["has_audio"] and f["original_name"].startswith("Freeze 0:04.0")
    c.wait_job(r["job_id"])
    out = _file(c, pid, f)
    first, last, src = frame_at(out, 0.1).mean(), frame_at(out, 2.3).mean(), frame_at(v, 4.0).mean()
    assert abs(first - last) < 1.5 and abs(first - src) < 4, (first, last, src)
    assert c.req("POST", f"/api/projects/{pid}/media/{m['id']}/derive", {"kind": "freeze", "t": 99})[0] == 422
    assert c.req("POST", f"/api/projects/{pid}/media/{m['id']}/derive", {"kind": "freeze", "t": 1, "seconds": 30})[0] == 422
    assert c.req("POST", f"/api/projects/{pid}/media/{m['id']}/derive", {"kind": "melt"})[0] == 422


def test_reverse(server, tmp_path):
    c = server
    pid, m, v = _upload_ramp(c, tmp_path)
    st, r, _ = c.req("POST", f"/api/projects/{pid}/media/{m['id']}/derive", {"kind": "reverse", "start": 1.0, "end": 6.0})
    assert st == 201, r
    rv = r["media"]
    assert abs(rv["duration"] - 5.0) < 0.15 and rv["has_audio"] and rv["original_name"].startswith("Reversed 0:01.0-0:06.0")
    out = _file(c, pid, rv)
    lum = [frame_at(out, t).mean() for t in (0.1, 1.9, 2.1, 3.0, 4.8)]
    assert lum == sorted(lum, reverse=True), lum                     # gets darker: time runs backwards, across the 2 s pieces
    assert abs(lum[0] - frame_at(v, 5.9).mean()) < 6 and abs(lum[-1] - frame_at(v, 1.2).mean()) < 6
    for bad in ({"start": 1, "end": 1.1}, {"start": 0, "end": 70}, {"start": 5, "end": 20}):
        assert c.req("POST", f"/api/projects/{pid}/media/{m['id']}/derive", {"kind": "reverse", **bad})[0] == 422, bad


# ---------------------------------------------------------------- green screen
def test_chroma_schema():
    clip = dict(id=new_id(), media_id=new_id(), start=0, source_in=0, source_out=2)
    Clip(**clip, chroma={"color": "#00ff00"})
    for bad in ({"color": "green"}, {"similarity": 0}, {"blend": 0.9}, {"extra": 1}):
        with pytest.raises(ValidationError):
            Clip(**clip, chroma={"color": "#00ff00", **bad})


def test_green_screen_export(server, tmp_path):
    c = server
    bg, fg = tmp_path / "bg.mp4", tmp_path / "fg.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x2040ff:s=320x180:r=25:d=3", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(bg)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x00ff00:s=320x180:r=25:d=3,drawbox=x=120:y=60:w=80:h=60:c=red:t=fill",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(fg)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "green"})
    pid = p["id"]
    ids = []
    for f in (bg, fg):
        st, r, _ = c.upload(pid, f)
        c.wait_job(r["job_id"])
        ids.append(r["media"]["id"])
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    clip = lambda m, **kw: {"id": new_id(), "media_id": m, "start": 0, "source_in": 0, "source_out": 3, **kw}  # noqa: E731
    p["timeline"]["tracks"][0]["clips"] = [clip(ids[0])]
    p["timeline"]["tracks"][1]["clips"] = [clip(ids[1], chroma={"color": "#00ff00", "similarity": 0.3, "blend": 0.05})]
    st, r, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                                             "output": {"width": 320, "height": 180, "fps": 25, "fit_mode": "fit"}})
    assert st == 200, r
    st, job, _ = c.req("POST", f"/api/projects/{pid}/exports", {"filename": "gs", "quality": "draft"})
    j = c.wait_job(job["id"], timeout=300)
    assert j["status"] == "succeeded", j.get("error_detail")
    out = c.settings.projects_dir / pid / "exports" / j["result"]["file"]
    img = frame_at(out, 1.0, 320, 180)
    corner, centre = img[20, 20], img[90, 160]
    assert corner[2] > 180 and corner[1] < 120, corner             # the blue background shows through the green
    assert centre[0] > 180 and centre[1] < 90, centre              # the red box stays


# ---------------------------------------------------------------- brand kit
def _png(color=(255, 0, 0, 255), size=(200, 100)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_brand_kit_settings_and_files(server, tmp_path):
    c = server
    st, b, _ = c.req("GET", "/api/brand")
    assert st == 200 and b["has_logo"] is False and b["brand"]["logo_corner"] == "br"
    st, b, _ = c.req("PUT", "/api/brand", {**b["brand"], "name": "RJ", "logo_corner": "tl", "title_accent": "#00ccff",
                                           "captions": {**b["brand"]["captions"], "style": "highlight"}})
    assert st == 200 and b["brand"]["name"] == "RJ" and b["brand"]["captions"]["style"] == "highlight"
    assert c.req("PUT", "/api/brand", {**b["brand"], "logo_size": 2})[0] == 422
    assert c.req("PUT", "/api/brand", {**b["brand"], "logo": "../../etc/passwd"})[1]["brand"]["logo"] is None   # files only via upload
    # logo: any image becomes a capped PNG; non-images are refused
    st, b, _ = c.req("POST", "/api/brand/files/logo", raw=_png(size=(3000, 1500)))
    assert st == 200 and b["has_logo"] and b["brand"]["logo"].startswith("logo-")
    st, img, _ = c.req("GET", "/api/brand/logo")
    from PIL import Image
    import io
    assert st == 200 and max(Image.open(io.BytesIO(img)).size) == 1024
    assert c.req("POST", "/api/brand/files/logo", raw=b"not an image")[0] == 415
    assert c.req("POST", "/api/brand/files/banner", raw=b"x")[0] == 404
    # intro: must be a video
    v = tmp_path / "intro.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=purple:s=160x90:r=25:d=2", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(v)], check=True)
    st, b, _ = c.req("POST", "/api/brand/files/intro?filename=intro.mp4", raw=v.read_bytes())
    assert st == 200 and b["has_intro"]
    snd = tmp_path / "s.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=1", str(snd)], check=True)
    assert c.req("POST", "/api/brand/files/outro?filename=s.wav", raw=snd.read_bytes())[0] == 415
    files = sorted(f.name for f in (c.settings.workspace / "brand").iterdir())
    assert len(files) == 3 and "brand.json" in files                      # old logo removed, no leftovers
    st, b, _ = c.req("DELETE", "/api/brand/files/intro")
    assert st == 200 and not b["has_intro"]


def test_watermark_and_intro_in_a_project(server, tmp_path):
    c = server
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=320x180:r=25:d=3", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(v)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "branded"})
    pid = p["id"]
    st, r, _ = c.upload(pid, v)
    c.wait_job(r["job_id"])
    mid = r["media"]["id"]
    assert c.req("POST", f"/api/projects/{pid}/brand/watermark", {"on": True})[0] == 409    # no logo yet
    c.req("POST", "/api/brand/files/logo", raw=_png((0, 255, 0, 255), (100, 100)))
    _, b, _ = c.req("GET", "/api/brand")
    c.req("PUT", "/api/brand", {**b["brand"], "logo_corner": "tr", "logo_size": 0.2, "logo_opacity": 1.0})
    st, r, _ = c.req("POST", f"/api/projects/{pid}/brand/watermark", {"on": True})
    assert st == 200 and r["watermark"]["corner"] == "tr"
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    p["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 3}]
    assert c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                                          "output": {"width": 320, "height": 180, "fps": 25, "fit_mode": "fit"}})[0] == 200
    st, job, _ = c.req("POST", f"/api/projects/{pid}/exports", {"filename": "wm", "quality": "draft"})
    j = c.wait_job(job["id"], timeout=300)
    assert j["status"] == "succeeded", j.get("error_detail")
    img = frame_at(c.settings.projects_dir / pid / "exports" / j["result"]["file"], 1.0, 320, 180)
    green = (img[:, :, 1] > 200) & (img[:, :, 0] < 80)
    ys, xs = np.nonzero(green)
    assert xs.min() > 240 and xs.max() < 315 and ys.max() < 80, (xs.min(), xs.max(), ys.max())   # top right, 20 % wide
    # changing the kit later doesn't break the project (its copy of the logo stays)
    c.req("DELETE", "/api/brand/files/logo")
    assert (c.settings.projects_dir / pid / "media" / "brand" / r["watermark"]["file"]).exists()
    st, r, _ = c.req("POST", f"/api/projects/{pid}/brand/watermark", {"on": False})
    assert st == 200 and r["watermark"] is None
    # intro: imported once into the project's media
    intro = tmp_path / "intro.mp4"
    intro.write_bytes(v.read_bytes() + b"")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=purple:s=160x90:r=25:d=2", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(intro)], check=True)
    c.req("POST", "/api/brand/files/intro?filename=intro.mp4", raw=intro.read_bytes())
    st, r1, _ = c.req("POST", f"/api/projects/{pid}/brand/import", {"kind": "intro"})
    assert st == 201 and r1["media"]["original_name"] == "Intro.mp4"
    st, r2, _ = c.req("POST", f"/api/projects/{pid}/brand/import", {"kind": "intro"})
    assert st == 200 and r2["media"]["id"] == r1["media"]["id"]
    assert c.req("POST", f"/api/projects/{pid}/brand/import", {"kind": "outro"})[0] == 409
