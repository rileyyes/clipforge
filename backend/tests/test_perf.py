"""Phase 6: render cache, preview proxies on demand, detailed waveforms."""
from __future__ import annotations

import os
import time

import pytest

from app import rcache
from app.render import render_project
from app.schema import Project

from test_audio_transitions import Ctx
from test_look import frame, project


def _render(s, p, pdir, name="o"):
    r = render_project(Ctx(), s, p, pdir, name, "draft", "libx264")
    assert r["validation"]["ok"], r["validation"]
    return pdir / "exports" / r["file"], r["validation"]["cache"]


def _specs():
    return [("red", 0, dict(start=0, source_in=0, source_out=2)),
            ("blue", 0, dict(start=2, source_in=0, source_out=2, transition_in={"kind": "wipe_left", "duration": 1})),
            ("red", 2, dict(start=0, source_in=0, source_out=2)),
            ("white", 1, dict(start=0.5, source_in=0, source_out=1, transform={"scale": 0.3, "rotation": 20}))]


def test_second_export_reuses_every_segment(tmp_path):
    s, p, pdir = project(tmp_path, _specs())
    out1, c1 = _render(s, p, pdir, "one")
    t0 = time.time()
    out2, c2 = _render(s, p, pdir, "two")
    assert c1["enabled"] and c1["reused"] == 0 and c1["rendered"] > 4
    assert c2["rendered"] == 0 and c2["reused"] == c1["rendered"]  # incl. transition parts read from work files
    for t in (0.6, 2.0, 3.5):
        assert (abs(frame(out1, t) - frame(out2, t)) <= 2).all()


def test_changed_clip_rerenders_only_itself(tmp_path):
    s, p, pdir = project(tmp_path, _specs())
    _o, c1 = _render(s, p, pdir)
    d = p.model_dump(mode="json")
    d["timeline"]["tracks"][1]["clips"][0]["color"] = {"look": "bw"}  # the overlay only
    _o, c2 = _render(s, Project.model_validate(d), pdir)
    # the overlay segment + the one final-quality block it appears in
    assert c2["rendered"] == 2 and c2["reused"] == c1["rendered"] - 2


def test_cache_can_be_turned_off(tmp_path):
    s, p, pdir = project(tmp_path, _specs()[:1])
    import dataclasses
    s = dataclasses.replace(s, render_cache_bytes=0)
    _o, c = _render(s, p, pdir)
    assert c == {"enabled": False, "reused": 0, "rendered": 0}
    assert not s.cache_dir.exists() or not any(s.cache_dir.iterdir())


def test_eviction_keeps_recent_files(tmp_path):
    root = tmp_path / "c"
    root.mkdir()
    for i in range(10):
        f = root / f"{i}.mp4"
        f.write_bytes(b"x" * 1000)
        os.utime(f, (1000 + i, 1000 + i))
    freed = rcache.evict(root, 5000)
    left = sorted(int(p.stem) for p in root.iterdir())
    assert freed == 6000 and left == [6, 7, 8, 9]  # oldest go first, down to 80% of the limit
    assert rcache.clear(root) == 4000 and not root.exists()


def test_missing_input_disables_caching_for_that_segment(tmp_path):
    c = rcache.RenderCache(tmp_path / "c", 10**9, "ffmpeg")
    work = tmp_path / "w"
    assert c.key(["-i", str(work / "unknown.mp4"), str(work / "x.mp4")], work, "x.mp4") is None
    k1 = c.key(["-i", "a", str(work / "x.mp4")], work, "x.mp4")
    k2 = c.key(["-i", str(work / "x.mp4"), str(work / "y.mp4")], work, "y.mp4")
    assert k1 and k2 and k1 != k2


# ---------------------------------------------------------------- API
def test_previews_proxy_and_waveform_detail(server, tmp_path):
    from conftest import make_media
    c = server
    vid = make_media(tmp_path / "v.mp4", duration=3)
    _, p, _ = c.req("POST", "/api/projects", {"name": "px"})
    pid = p["id"]
    _, up, _ = c.upload(pid, vid)
    mid = up["media"]["id"]
    assert c.wait_job(up["job_id"])["status"] == "succeeded"
    _, m, _ = c.req("GET", f"/api/projects/{pid}")
    assert m["media"][0]["proxy"] is None  # a browser-friendly MP4 needs no proxy by default
    st, wf, _ = c.req("GET", f"/api/projects/{pid}/media/{mid}/waveform")
    assert wf["peaks_per_second"] == 100 and len(wf["peaks"]) == pytest.approx(300, abs=3)
    orig = c.req("GET", f"/api/projects/{pid}/media/{mid}/stream")[1]
    st, job, _ = c.req("POST", f"/api/projects/{pid}/media/{mid}/previews", {"proxy": True})
    assert st == 202 and c.wait_job(job["id"])["status"] == "succeeded"
    _, m, _ = c.req("GET", f"/api/projects/{pid}")
    assert m["media"][0]["proxy"]
    light = c.req("GET", f"/api/projects/{pid}/media/{mid}/stream?proxy=1")[1]
    assert c.req("GET", f"/api/projects/{pid}/media/{mid}/stream")[1] == orig  # original stays the default
    assert light != orig and len(light) > 1000
    assert c.req("POST", f"/api/projects/{pid}/media/{mid}/previews", {"proxy": "yes please"})[0] == 422
    assert c.req("POST", f"/api/projects/{pid}/media/{'0' * 32}/previews", {})[0] == 404
    # an export fills the cache; system shows it and cleanup empties it
    p = m
    link = "a" * 32
    p["timeline"]["tracks"][0]["clips"] = [{"id": "b" * 32, "media_id": mid, "start": 0, "source_in": 0, "source_out": 2, "link_id": link}]
    st, p, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                               "timeline": p["timeline"], "output": p["output"]})
    _, ej, _ = c.req("POST", f"/api/projects/{pid}/exports", {"filename": "x", "quality": "draft",
                                                              "output": {"width": 320, "height": 180, "fps": 30, "fit_mode": "fit"}})
    assert c.wait_job(ej["id"])["status"] == "succeeded"
    _, sysinfo, _ = c.req("GET", "/api/system")
    assert sysinfo["render_cache_bytes"] > 0
    _, r, _ = c.req("POST", "/api/maintenance/cleanup")
    assert r["freed_bytes"] >= sysinfo["render_cache_bytes"]
    assert c.req("GET", "/api/system")[1]["render_cache_bytes"] == 0
