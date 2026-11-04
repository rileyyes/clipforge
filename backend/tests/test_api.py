"""Integration tests against a real server, real FFmpeg and synthetic media."""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid

import pytest

from app.jobs import JobManager
from app.storage import atomic_write_json


def nid() -> str:
    return uuid.uuid4().hex


def new_project(c, name="Test"):
    st, p, _ = c.req("POST", "/api/projects", {"name": name})
    assert st == 201
    return p


def save(c, p, out=None):
    return c.req("PUT", f"/api/projects/{p['id']}/timeline", {
        "base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
        "output": out or p["output"]})


def clip(mid, start, a, b, **kw):
    return {"id": nid(), "media_id": mid, "start": start, "source_in": a, "source_out": b, **kw}


def ffprobe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                          "-show_format", str(path)], capture_output=True, text=True).stdout
    return json.loads(out)


# ---------------------------------------------------------------- import
def test_import_probe_and_derived_assets(server, media_dir):
    p = new_project(server)
    st, r, _ = server.upload(p["id"], media_dir / "av.mp4")
    assert st == 201
    m = r["media"]
    assert m["has_video"] and m["has_audio"] and m["width"] == 640 and m["fps"] == 30
    assert abs(m["duration"] - 4.0) < 0.1
    job = server.wait_job(r["job_id"])
    assert job["status"] == "succeeded", job
    assert job["result"]["thumbnail"] and job["result"]["waveform"]
    st, wf, _ = server.req("GET", f"/api/projects/{p['id']}/media/{m['id']}/waveform")
    assert st == 200 and wf["peaks_per_second"] == 100 and len(wf["peaks"]) == pytest.approx(400, abs=5)  # 4 s
    # original stored read-only
    pdir = server.settings.projects_dir / p["id"] / "media" / "original"
    f = next(pdir.iterdir())
    assert not os.access(f, os.W_OK) or os.geteuid() == 0


def test_mkv_gets_browser_proxy_and_vfr_flag(server, media_dir):
    p = new_project(server)
    st, r, _ = server.upload(p["id"], media_dir / "vfr.mkv")
    assert st == 201
    job = server.wait_job(r["job_id"])
    assert job["status"] == "succeeded"
    assert job["result"].get("proxy"), "mkv should get an mp4 proxy"
    st, _, headers = server.req("GET", f"/api/projects/{p['id']}/media/{r['media']['id']}/stream",
                                headers={"Range": "bytes=0-99"})
    assert st == 206 and headers.get("content-length") == "100"


def test_audio_only_and_video_only_import(server, media_dir):
    p = new_project(server)
    st, a, _ = server.upload(p["id"], media_dir / "audio_only.wav")
    assert st == 201 and a["media"]["kind"] == "audio" and not a["media"]["has_video"]
    st, v, _ = server.upload(p["id"], media_dir / "video_only.mp4")
    assert st == 201 and not v["media"]["has_audio"]


def test_rejects_corrupt_wrong_type_and_duplicate(server, media_dir):
    p = new_project(server)
    st, r, _ = server.upload(p["id"], media_dir / "corrupt.mp4")
    assert st == 415 and "Could not import" in r["error"]
    st, _, _ = server.req("POST", f"/api/projects/{p['id']}/media?filename=run.sh", raw=b"#!/bin/sh")
    assert st == 415
    st, _, _ = server.req("POST", f"/api/projects/{p['id']}/media?filename=list.m3u8", raw=b"#EXTM3U")
    assert st == 415
    assert server.upload(p["id"], media_dir / "av.mp4")[0] == 201
    st, r, _ = server.upload(p["id"], media_dir / "av.mp4", name="copy.mp4")
    assert st == 200 and r["duplicate"] is True
    # nothing left behind from rejected uploads
    orig = server.settings.projects_dir / p["id"] / "media" / "original"
    assert len(list(orig.iterdir())) == 1


def test_upload_size_limit(server):
    p = new_project(server)
    big = b"\0" * (server.settings.max_upload_bytes + 1)
    st, r, _ = server.req("POST", f"/api/projects/{p['id']}/media?filename=big.mp4", raw=big)
    # server answers 413 from Content-Length before reading the body; it may close the
    # socket while the client is still sending (status 0 = connection closed early)
    assert st in (413, 0)
    orig = server.settings.projects_dir / p["id"] / "media" / "original"
    assert not list(orig.iterdir())


def test_concat_playlist_disguised_as_mp4_cannot_read_files(server, tmp_path):
    """A crafted file must not make FFmpeg open other local files."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    evil = tmp_path / "evil.mp4"
    evil.write_text(f"ffconcat version 1.0\nfile '{secret}'\n")
    p = new_project(server)
    st, r, _ = server.upload(p["id"], evil)
    assert st == 415


# ---------------------------------------------------------------- security
def test_csrf_and_origin_protection(server):
    st, _, _ = server.req("POST", "/api/projects", {"name": "x"}, csrf=False)
    assert st == 403
    st, _, _ = server.req("POST", "/api/projects", {"name": "x"}, headers={"Origin": "https://evil.example"})
    assert st == 403
    st, _, h = server.req("GET", "/api/health")
    assert st == 200 and "default-src 'self'" in h.get("content-security-policy", "")
    st, _, _ = server.req("GET", "/api/health", headers={"Host": "evil.example"})
    assert st == 400  # DNS-rebinding protection


def test_traversal_and_bad_ids(server):
    p = new_project(server)
    for path in (f"/api/projects/{p['id']}/exports/..%2Fproject.json",
                 f"/api/projects/{p['id']}/exports/project.json",
                 "/api/projects/../../etc/passwd",
                 "/api/projects/not-an-id",
                 f"/api/projects/{p['id']}/media/zzz/stream"):
        st, _, _ = server.req("GET", path)
        assert st == 404, path


# ---------------------------------------------------------------- projects
def test_save_validation_conflict_and_reopen(server, media_dir):
    p = new_project(server)
    _, r, _ = server.upload(p["id"], media_dir / "av.mp4")
    mid = r["media"]["id"]
    _, p, _ = server.req("GET", f"/api/projects/{p['id']}")
    p["timeline"]["tracks"][0]["clips"] = [clip(mid, 0, 0, 2), clip(mid, 1, 0, 2)]  # overlap
    st, e, _ = save(server, p)
    assert st == 422 and "overlap" in e["error"]
    p["timeline"]["tracks"][0]["clips"] = [clip(mid, 0, 0, 2)]
    st, saved, _ = save(server, p)
    assert st == 200 and saved["edit_revision"] == p["edit_revision"] + 1
    st, _, _ = save(server, p)  # stale base revision
    assert st == 409
    server.wait_job(r["job_id"])
    _, reopened, _ = server.req("GET", f"/api/projects/{p['id']}")
    assert reopened["timeline"]["tracks"][0]["clips"][0]["source_out"] == 2
    assert reopened["media"][0]["thumbnail"]  # background job's update merged, not lost


def test_rename_duplicate_delete(server, media_dir):
    p = new_project(server, "Original")
    server.upload(p["id"], media_dir / "av.mp4")
    st, r, _ = server.req("POST", f"/api/projects/{p['id']}/rename", {"name": "Renamed"})
    assert r["name"] == "Renamed"
    st, d, _ = server.req("POST", f"/api/projects/{p['id']}/duplicate")
    assert st == 201 and d["name"] == "Renamed (copy)" and len(d["media"]) == 1
    time.sleep(1.0)  # let derive jobs settle
    st, _, _ = server.req("DELETE", f"/api/projects/{p['id']}")
    assert st == 204
    _, lst, _ = server.req("GET", "/api/projects")
    assert [x["id"] for x in lst["projects"]] == [d["id"]]


def test_media_in_use_cannot_be_deleted(server, media_dir):
    p = new_project(server)
    _, r, _ = server.upload(p["id"], media_dir / "av.mp4")
    mid = r["media"]["id"]
    _, p, _ = server.req("GET", f"/api/projects/{p['id']}")
    p["timeline"]["tracks"][0]["clips"] = [clip(mid, 0, 0, 1)]
    save(server, p)
    st, _, _ = server.req("DELETE", f"/api/projects/{p['id']}/media/{mid}")
    assert st == 409


# ---------------------------------------------------------------- rendering
def test_render_mixed_sources_speed_overlay_and_validation(server, media_dir):
    p = new_project(server)
    ids = {}
    for f in ("av.mp4", "vertical.mov", "audio_only.wav", "video_only.mp4"):
        _, r, _ = server.upload(p["id"], media_dir / f)
        ids[f] = r["media"]["id"]
    _, p, _ = server.req("GET", f"/api/projects/{p['id']}")
    v1, v2, a1, a2 = p["timeline"]["tracks"]
    link = nid()
    v1["clips"] = [clip(ids["av.mp4"], 0, 0.5, 2.5, link_id=link),
                   clip(ids["vertical.mov"], 2.5, 0, 2),          # different size + fps
                   clip(ids["video_only.mp4"], 5, 0, 2, speed=2)]  # gap 4.5-5, then 1 s
    v2["clips"] = [clip(ids["av.mp4"], 1, 0, 1, transform={"scale": 0.25, "x": 200, "y": -100})]
    a1["clips"] = [clip(ids["av.mp4"], 0, 0.5, 2.5, link_id=link, volume=0.5)]
    a2["clips"] = [clip(ids["audio_only.wav"], 0, 0, 4, speed=1.5)]
    st, _, _ = save(server, p, {"width": 640, "height": 360, "fps": 25, "fit_mode": "fit"})
    assert st == 200
    st, job, _ = server.req("POST", f"/api/projects/{p['id']}/exports",
                            {"filename": "out", "quality": "draft"})
    assert st == 202
    job = server.wait_job(job["id"], timeout=300)
    assert job["status"] == "succeeded", job.get("error_detail")
    rep = job["result"]["validation"]
    assert rep["ok"], rep
    path = server.settings.projects_dir / p["id"] / "exports" / job["result"]["file"]
    info = ffprobe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (640, 360)
    assert abs(float(info["format"]["duration"]) - 6.0) < 0.1
    # exactly frame-accurate
    assert int(v["nb_frames"]) == 150
    # work dir cleaned up
    assert not any((server.settings.projects_dir / p["id"] / "work").iterdir())


def test_letterbox_vs_fill(server, media_dir):
    """Vertical source in 16:9 output: 'fit' must keep black bars, 'fill' must not."""
    p = new_project(server)
    _, r, _ = server.upload(p["id"], media_dir / "vertical.mov")
    mid = r["media"]["id"]
    _, p, _ = server.req("GET", f"/api/projects/{p['id']}")
    edge_luma = {}
    for mode in ("fit", "fill"):
        _, p, _ = server.req("GET", f"/api/projects/{p['id']}")
        p["timeline"]["tracks"][0]["clips"] = [clip(mid, 0, 0, 1)]
        assert save(server, p, {"width": 320, "height": 180, "fps": 25, "fit_mode": mode})[0] == 200
        _, job, _ = server.req("POST", f"/api/projects/{p['id']}/exports", {"filename": mode, "quality": "draft"})
        job = server.wait_job(job["id"])
        assert job["status"] == "succeeded"
        out = server.settings.projects_dir / p["id"] / "exports" / job["result"]["file"]
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-frames:v", "1", "-vf",
                              "crop=10:180:0:0,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True).stdout
        edge_luma[mode] = sum(raw) / len(raw)
    assert edge_luma["fit"] < 25      # black letterbox bar
    assert edge_luma["fill"] > 40     # picture reaches the edge


def test_cancel_render_and_retry(server, media_dir, tmp_path):
    from conftest import make_media
    long = make_media(tmp_path / "long.mp4", video="testsrc2=s=1280x720:r=30", duration=40)
    p = new_project(server)
    _, r, _ = server.upload(p["id"], long)
    mid = r["media"]["id"]
    _, p, _ = server.req("GET", f"/api/projects/{p['id']}")
    p["timeline"]["tracks"][0]["clips"] = [clip(mid, 0, 0, 40)]
    save(server, p, {"width": 1920, "height": 1080, "fps": 30, "fit_mode": "fit"})
    server.wait_job(r["job_id"])
    _, job, _ = server.req("POST", f"/api/projects/{p['id']}/exports", {"filename": "c", "quality": "high"})
    for _ in range(100):
        _, j, _ = server.req("GET", f"/api/jobs/{job['id']}")
        if j["status"] == "running" and (j["progress"] or 0) > 0:
            break
        time.sleep(0.1)
    server.req("POST", f"/api/jobs/{job['id']}/cancel")
    j = server.wait_job(job["id"])
    assert j["status"] == "cancelled"
    exports = server.settings.projects_dir / p["id"] / "exports"
    assert not list(exports.glob("*.mp4")), "no partial output left behind"
    st, retry, _ = server.req("POST", f"/api/jobs/{job['id']}/retry")
    assert st == 202
    server.req("POST", f"/api/jobs/{retry['id']}/cancel")
    server.wait_job(retry["id"])


def test_progress_is_measured_and_monotonic(server, media_dir):
    p = new_project(server)
    _, r, _ = server.upload(p["id"], media_dir / "av.mp4")
    _, p, _ = server.req("GET", f"/api/projects/{p['id']}")
    p["timeline"]["tracks"][0]["clips"] = [clip(r["media"]["id"], 0, 0, 4)]
    save(server, p)
    _, job, _ = server.req("POST", f"/api/projects/{p['id']}/exports", {"filename": "p", "quality": "draft"})
    seen = []
    while True:
        _, j, _ = server.req("GET", f"/api/jobs/{job['id']}")
        if j["progress"] is not None:
            seen.append(j["progress"])
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert j["status"] == "succeeded"
    assert seen == sorted(seen) and seen[-1] == 1.0


def test_empty_timeline_export_refused(server):
    p = new_project(server)
    st, r, _ = server.req("POST", f"/api/projects/{p['id']}/exports", {"filename": "x"})
    assert st == 400 and "empty" in r["error"]


def test_interrupted_jobs_recovered_on_restart(tmp_path):
    d = tmp_path / "jobs"
    d.mkdir()
    jid = nid()
    atomic_write_json(d / f"{jid}.json", {"id": jid, "kind": "render", "status": "running"},
                      keep_backup=False)
    m = JobManager(d)
    j = m.get(jid)
    assert j.status == "interrupted" and "stopped" in j.error
    m.shutdown()


def test_missing_ffmpeg_gives_clear_message(server, media_dir, monkeypatch):
    from app import ffmpeg as ff
    monkeypatch.setattr(ff, "tools_available", lambda a, b: False)
    p = new_project(server)
    st, r, _ = server.upload(p["id"], media_dir / "av.mp4")
    assert st == 503 and "FFmpeg wasn't found" in r["error"]


def test_probe_reports_missing_binary(tmp_path):
    from app import ffmpeg as ff
    with pytest.raises(ff.FFmpegError, match="FFmpeg wasn't found"):
        ff.probe("definitely-not-ffprobe-xyz", tmp_path / "x.mp4")


def test_delete_media_while_windows_holds_the_file(server, media_dir, monkeypatch):
    """Windows CI: removing media right after import failed (500): a background job still
    had the file open, and Windows can't delete open files. Now: wait/retry, and if the
    file stays locked, remove it from the project and delete the file at the next cleanup."""
    import pathlib
    p = new_project(server)
    _, r, _ = server.upload(p["id"], media_dir / "av.mp4")
    mid, stored = r["media"]["id"], r["media"]["stored_name"]
    real = pathlib.Path.unlink
    calls = {"n": 0}

    def locked(self, *a, **k):
        if self.name == stored:
            calls["n"] += 1
            raise PermissionError(13, "The process cannot access the file because it is being used")
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "unlink", locked)
    st, _, _ = server.req("DELETE", f"/api/projects/{p['id']}/media/{mid}")
    assert st == 204 and calls["n"] >= 2  # retried, then deferred
    assert server.req("GET", f"/api/projects/{p['id']}")[1]["media"] == []
    orig = server.settings.projects_dir / p["id"] / "media" / "original" / stored
    assert orig.exists()
    monkeypatch.setattr(pathlib.Path, "unlink", real)  # the lock is gone later
    assert server.req("POST", "/api/maintenance/cleanup")[0] == 200
    assert not orig.exists() and not (orig.parent.parent / ".delete-later").exists()
