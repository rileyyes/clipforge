"""Phase 12: relink a media file that went missing from the project folder."""
from __future__ import annotations

import json
import os
import subprocess

from app.storage import new_id


def make(path, d, color="gray", audio=True, video=True):
    args = ["ffmpeg", "-v", "error", "-y"]
    if video:
        args += ["-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=25:d={d}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=f=300:d={d}"]
    if video:
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac"]
    subprocess.run(args + ["-shortest", str(path)], check=True)
    return path


def remove_original(c, pid, m):
    f = c.settings.projects_dir / pid / "media" / "original" / m["stored_name"]
    f.chmod(0o600)
    f.unlink()


def setup(c, tmp_path, clip_out=6.0):
    vid = make(tmp_path / "rec.mp4", 8)
    _, p, _ = c.req("POST", "/api/projects", {"name": "Relink"})
    pid = p["id"]
    st, r, _ = c.upload(pid, vid)
    assert st == 201
    m = r["media"]
    c.wait_job(r["job_id"])
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    link = new_id()
    p["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": m["id"], "start": 0, "source_in": 1, "source_out": clip_out, "link_id": link}]
    p["timeline"]["tracks"][2]["clips"] = [{"id": new_id(), "media_id": m["id"], "start": 0, "source_in": 1, "source_out": clip_out, "link_id": link}]
    st, _r, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"], "output": p["output"]})
    assert st == 200
    return pid, m, vid


def relink(c, pid, mid, path, name=None):
    from urllib.parse import quote
    return c.req("POST", f"/api/projects/{pid}/media/{mid}/relink?filename={quote(name or path.name)}", raw=path.read_bytes())


def test_relink_same_file_keeps_everything(server, tmp_path):
    c = server
    pid, m, vid = setup(c, tmp_path)
    analysis = c.settings.projects_dir / pid / "analysis" / f"{m['id']}.json"
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(json.dumps({"words": []}), encoding="utf-8")
    # not missing yet: refused
    st, r, _ = relink(c, pid, m["id"], vid)
    assert st == 409 and "isn't missing" in r["error"]
    remove_original(c, pid, m)
    assert c.req("GET", f"/api/projects/{pid}")[1]["missing_media"] == [m["id"]]
    renamed = tmp_path / "renamed copy.mp4"
    renamed.write_bytes(vid.read_bytes())
    st, r, _ = relink(c, pid, m["id"], renamed)
    assert st == 200 and r["same_file"] is True and r["note"] is None
    assert r["media"]["id"] == m["id"] and r["media"]["original_name"] == "renamed copy.mp4"
    c.wait_job(r["job_id"])
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    assert p["missing_media"] == [] and analysis.exists()  # same file: the analysis is kept
    st, _b, _ = c.req("GET", f"/api/projects/{pid}/media/{m['id']}/stream")
    assert st == 200
    if os.name != "nt":
        f = c.settings.projects_dir / pid / "media" / "original" / r["media"]["stored_name"]
        assert not (f.stat().st_mode & 0o222)  # read-only like any import


def test_relink_checks_the_new_file(server, tmp_path):
    c = server
    pid, m, _vid = setup(c, tmp_path, clip_out=7.5)
    remove_original(c, pid, m)
    short = make(tmp_path / "short.mp4", 4)
    st, r, _ = relink(c, pid, m["id"], short)
    assert st == 422 and "too short" in r["error"] and "7.5" in r["error"]
    sound = make(tmp_path / "sound.m4a", 9, video=False)
    st, r, _ = relink(c, pid, m["id"], sound)
    assert st == 422 and "no video" in r["error"]
    assert relink(c, pid, m["id"], short, name="evil.exe")[0] == 415
    assert relink(c, pid, m["id"], short, name="x.mp4")[0] == 422
    # nothing half-done was left behind, and it's still missing
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    assert p["missing_media"] == [m["id"]]
    left = os.listdir(c.settings.projects_dir / pid / "media" / "original")
    assert left == [], left
    # a file that is already another media item of the project is refused
    other = make(tmp_path / "other.mp4", 9, color="blue")
    st, r2, _ = c.upload(pid, other)
    assert st == 201
    st, r, _ = relink(c, pid, m["id"], other)
    assert st == 422 and "already in this project" in r["error"]


def test_relink_different_file_resets_analysis_and_exports(server, tmp_path):
    c = server
    pid, m, _vid = setup(c, tmp_path)
    adir = c.settings.projects_dir / pid / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / f"{m['id']}.json").write_text("{}", encoding="utf-8")
    (adir / f"beats-{m['id']}.json").write_text("{}", encoding="utf-8")
    remove_original(c, pid, m)
    new = make(tmp_path / "re-export.mov", 9, color="green")
    st, r, _ = relink(c, pid, m["id"], new)
    assert st == 200 and r["same_file"] is False and "reset" in r["note"]
    assert r["media"]["stored_name"].endswith(".mov")
    assert not (adir / f"{m['id']}.json").exists() and not (adir / f"beats-{m['id']}.json").exists()
    c.wait_job(r["job_id"])
    st, job, _ = c.req("POST", f"/api/projects/{pid}/exports", {"filename": "out", "quality": "draft"})
    assert st == 202, job
    j = c.wait_job(job["id"], timeout=300)
    assert j["status"] == "succeeded" and j["result"]["validation"]["ok"], j.get("error_detail")


def test_relink_unknown_media_is_404(server):
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "x"})
    assert c.req("POST", f"/api/projects/{p['id']}/media/{new_id()}/relink?filename=a.mp4", raw=b"x")[0] == 404
