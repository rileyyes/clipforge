"""Phase 5: version history (snapshots, checkpoints, restore, compare) and the
one-click AI edit extras."""
from __future__ import annotations

import json
import time

import pytest

from app import history as H
from app.storage import new_id

from test_effects import FakeTranscriber


def _doc(clips, effects=(), captions=None, audio=None):
    """clips: [(media_id, start, source_in, source_out)] on V1."""
    return {"timeline": {"tracks": [
        {"id": "v1", "kind": "video", "clips": [
            {"id": new_id(), "media_id": m, "start": s, "source_in": a, "source_out": b} for m, s, a, b in clips]},
        {"id": "a1", "kind": "audio", "clips": []}]},
        "effects": list(effects), "captions": captions or {"enabled": False},
        "audio": audio or {"normalize": True}, "output": {"width": 1920}}


def _project(doc, rev=1):
    return {**doc, "edit_revision": rev, "media": [{"id": "m1", "original_name": "talk.mp4", "duration": 60}]}


# ---------------------------------------------------------------- unit
def test_snapshot_list_get_rename_delete(tmp_path):
    hs = H.HistoryStore(tmp_path)
    m = hs.snapshot(_project(_doc([("m1", 0, 0, 10)])), "First cut")
    assert m.clips == 1 and m.duration == 10 and m.media_names == ["talk.mp4"]
    assert [v["label"] for v in hs.list()] == ["First cut"]
    assert "doc" not in hs.list()[0] and hs.get(m.id)["doc"]["timeline"]
    assert hs.rename(m.id, "  Final  ")["label"] == "Final"
    assert hs.rename(m.id, "")["label"] == "Final"  # blank keeps the old name
    hs.delete(m.id)
    assert hs.list() == []
    with pytest.raises(H.HistoryNotFound):
        hs.get(m.id)
    with pytest.raises(Exception):
        hs.get("../../project")


def test_auto_checkpoints_are_throttled_and_skip_unchanged(tmp_path, monkeypatch):
    hs = H.HistoryStore(tmp_path)
    assert hs.maybe_checkpoint(_project(_doc([]))) is None  # nothing worth saving yet
    p = _project(_doc([("m1", 0, 0, 10)]))
    assert hs.maybe_checkpoint(p) is not None
    p2 = _project(_doc([("m1", 0, 0, 8)]))
    assert hs.maybe_checkpoint(p2) is None  # too soon
    real = time.time
    monkeypatch.setattr(H.time, "time", lambda: real() + H.AUTO_EVERY_S + 5)
    assert hs.maybe_checkpoint(p2) is not None
    monkeypatch.setattr(H.time, "time", lambda: real() + 2 * H.AUTO_EVERY_S + 10)
    assert hs.maybe_checkpoint(p2) is None  # unchanged since the last checkpoint


def test_prune_keeps_manual_and_newest_automatic(tmp_path):
    hs = H.HistoryStore(tmp_path)
    keep = hs.snapshot(_project(_doc([("m1", 0, 0, 1)])), "Mine")
    for i in range(H.AUTO_KEEP + 5):
        hs.snapshot(_project(_doc([("m1", 0, 0, 1 + i)])), f"auto {i}", "auto")
    vs = hs.list()
    assert sum(v["origin"] == "auto" for v in vs) == H.AUTO_KEEP
    assert any(v["id"] == keep.id for v in vs)
    assert "auto 0" not in {v["label"] for v in vs}


def test_legacy_ai_backups_are_imported_once(tmp_path):
    (tmp_path / "history").mkdir()
    tl = _doc([("m1", 0, 0, 5)])["timeline"]
    (tmp_path / "history" / "timeline-1700000000000.json").write_text(json.dumps(tl))
    (tmp_path / "history" / "timeline-garbage.json").write_text("{")
    hs = H.HistoryStore(tmp_path)
    vs = hs.list()
    assert len(vs) == 1 and vs[0]["origin"] == "before_ai" and vs[0]["created_at"].startswith("2023-11-14")
    assert H.HistoryStore(tmp_path).list() == vs  # not imported twice
    assert hs.get(vs[0]["id"])["doc"]["effects"] is None  # restore keeps current effects


def test_compare_reports_kept_removed_added_and_settings():
    a = _doc([("m1", 0, 0, 10), ("m1", 10, 20, 30)],
             effects=[{"id": "e1", "kind": "censor", "media_id": "m1"}, {"id": "e2", "kind": "zoom", "media_id": "m1"}])
    b = _doc([("m1", 0, 0, 5), ("m1", 5, 25, 40)],
             effects=[{"id": "e2", "kind": "zoom", "media_id": "m1", "zoom": 1.5},
                      {"id": "e3", "kind": "text", "media_id": "m1"}],
             captions={"enabled": True})
    r = H.compare(a, b, {"m1": {"original_name": "talk.mp4", "duration": 60}})
    s = r["sources"][0]
    assert s["name"] == "talk.mp4"
    assert s["removed"] == [(5, 10), (20, 25)] and s["removed_s"] == 10
    assert s["added"] == [(30, 40)] and s["added_s"] == 10
    assert r["a"]["duration"] == 20 and r["b"]["duration"] == 20
    assert r["effects"] == {"added": {"text": 1}, "removed": {"censor": 1}, "changed": 1}
    assert r["settings"] == [{"group": "captions", "setting": "enabled", "a": False, "b": True}]
    assert not r["identical"] and H.compare(a, a, {})["identical"]


def test_compare_uses_audio_when_there_is_no_video():
    d = {"timeline": {"tracks": [{"kind": "audio", "clips": [
        {"media_id": "x", "start": 0, "source_in": 2, "source_out": 4}]}]}}
    r = H.compare(d, {"timeline": {"tracks": []}}, {})
    assert r["sources"][0]["removed"] == [(2, 4)] and r["sources"][0]["name"] == "(deleted media)"


# ---------------------------------------------------------------- API
def _setup(c, tmp_path, clips=((0, 0, 5),)):
    from conftest import make_media
    vid = make_media(tmp_path / "talk.mp4", video="testsrc2=s=320x180:r=30", duration=6)
    _, p, _ = c.req("POST", "/api/projects", {"name": "hist"})
    pid = p["id"]
    _, up, _ = c.upload(pid, vid)
    mid = up["media"]["id"]
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    return pid, mid, p


def _save(c, pid, p, mid, ranges, **extra):
    v, a = [], []
    for s, i, o in ranges:
        link = new_id()
        v.append({"id": new_id(), "media_id": mid, "start": s, "source_in": i, "source_out": o, "link_id": link})
        a.append({"id": new_id(), "media_id": mid, "start": s, "source_in": i, "source_out": o, "link_id": link})
    p["timeline"]["tracks"][0]["clips"] = v
    p["timeline"]["tracks"][2]["clips"] = a
    st, out, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                                 "timeline": p["timeline"], "output": p["output"],
                                                                 **extra})
    assert st == 200, out
    return out


def test_api_history_flow(server, tmp_path):
    c = server
    pid, mid, p = _setup(c, tmp_path)
    p = _save(c, pid, p, mid, [(0, 0, 5)])
    H_ = f"/api/projects/{pid}/history"
    _, h, _ = c.req("GET", H_)
    assert [v["origin"] for v in h["versions"]] == ["auto"]  # first save checkpoints
    st, emoji, _ = c.req("POST", H_, {"label": "Final ✅ “best” cut — café"})
    assert st == 201
    assert any(v["label"] == "Final ✅ “best” cut — café" for v in c.req("GET", H_)[1]["versions"])
    assert c.req("DELETE", f"{H_}/{emoji['id']}")[0] == 204
    st, v1, _ = c.req("POST", H_, {"label": "Long version"})
    assert st == 201 and v1["duration"] == 5
    p = _save(c, pid, p, mid, [(0, 1, 3)], captions={"enabled": True})
    _, h, _ = c.req("GET", H_)
    assert len(h["versions"]) == 2  # second save is within 10 minutes: no new checkpoint
    st, cmp_, _ = c.req("GET", f"{H_}/compare?a={v1['id']}&b=current")
    assert st == 200 and cmp_["a_label"] == "Long version" and cmp_["b_label"] == "Current edit"
    assert cmp_["sources"][0]["removed"] == [[0, 1], [3, 5]] and cmp_["b"]["duration"] == 2
    assert {"group": "captions", "setting": "enabled", "a": False, "b": True} in cmp_["settings"]
    assert c.req("GET", f"{H_}/compare?a=..%2F..&b=current")[0] == 404
    assert c.req("GET", f"{H_}/compare?a={'0' * 32}&b=current")[0] == 404
    st, r, _ = c.req("PUT", f"{H_}/{v1['id']}", {"label": "Director's cut"})
    assert st == 200 and r["label"] == "Director's cut"
    assert c.req("PUT", f"{H_}/{v1['id']}", {"label": "x" * 200})[0] == 422
    # restore: current edit is snapshotted first, then replaced
    rev = p["edit_revision"]
    st, restored, _ = c.req("POST", f"{H_}/{v1['id']}/restore")
    assert st == 200 and restored["edit_revision"] == rev + 1
    clips = restored["timeline"]["tracks"][0]["clips"]
    assert [(x["source_in"], x["source_out"]) for x in clips] == [(0, 5)]
    assert restored["captions"]["enabled"] is False
    _, h, _ = c.req("GET", H_)
    before = [v for v in h["versions"] if v["origin"] == "before_restore"]
    assert len(before) == 1 and before[0]["duration"] == 2 and "Director's cut" in before[0]["label"]
    # …so the restore itself can be undone
    st, back, _ = c.req("POST", f"{H_}/{before[0]['id']}/restore")
    assert st == 200 and back["timeline"]["tracks"][0]["clips"][0]["source_in"] == 1
    # stale editors get a conflict after a restore
    st, _, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                               "timeline": p["timeline"], "output": p["output"]})
    assert st == 409
    # delete
    assert c.req("DELETE", f"{H_}/{v1['id']}")[0] == 204
    assert c.req("DELETE", f"{H_}/{v1['id']}")[0] == 404
    assert c.req("POST", f"{H_}/{v1['id']}/restore")[0] == 404
    # CSRF header required for changes
    assert c.req("POST", H_, {"label": "x"}, csrf=False)[0] == 403


def test_restore_refuses_versions_with_deleted_media(server, tmp_path):
    c = server
    pid, mid, p = _setup(c, tmp_path)
    p = _save(c, pid, p, mid, [(0, 0, 5)])
    _, v, _ = c.req("POST", f"/api/projects/{pid}/history", {"label": "uses talk.mp4"})
    p = _save(c, pid, p, mid, [])
    assert c.req("DELETE", f"/api/projects/{pid}/media/{mid}")[0] in (200, 204)
    st, r, _ = c.req("POST", f"/api/projects/{pid}/history/{v['id']}/restore")
    assert st == 409 and "removed" in r["error"]
    _, cmp_, _ = c.req("GET", f"/api/projects/{pid}/history/compare?a={v['id']}&b=current")
    assert cmp_["sources"][0]["name"] == "(deleted media)"


def test_one_click_extras(server, tmp_path, monkeypatch):
    """AI edit + bleeps + comedy + captions + audio polish in one request."""
    c = server
    from test_autoedit import write_talk_wav
    import subprocess
    wav = write_talk_wav(tmp_path / "talk.wav")
    vid = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=30",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "oneclick"})
    pid = p["id"]
    _, up, _ = c.upload(pid, vid)
    mid = up["media"]["id"]
    _, job, _ = c.req("POST", f"/api/projects/{pid}/autoedit/analyze", {"media_id": mid})
    assert c.wait_job(job["id"])["status"] == "succeeded"
    extras = {"censor": True, "censor_sound": "honk", "fun": "chaotic", "captions": True, "audio_polish": True}
    body = {"media_id": mid, "settings": {"target_mode": "original"}, "extras": extras}
    # without a transcript: bleeps + captions are skipped, honestly reported
    st, r, _ = c.req("POST", f"/api/projects/{pid}/autoedit/apply", body)
    assert st == 200, r
    notes = {n["step"]: n for n in r["extras"]}
    assert not notes["Bleep swears"]["ok"] and "transcript" in notes["Bleep swears"]["detail"]
    assert not notes["Captions"]["ok"] and notes["Audio polish"]["ok"] and notes["Comedy edits"]["ok"]
    assert r["project"]["captions"]["enabled"] is False
    assert r["project"]["audio"]["enhance_voice"] is True
    n_fun = len(r["project"]["effects"])
    # with a transcript every step runs
    monkeypatch.setattr("app.api.available_transcriber", lambda: FakeTranscriber())
    _, job, _ = c.req("POST", f"/api/projects/{pid}/transcribe", {})
    assert c.wait_job(job["id"])["status"] == "succeeded"
    st, r, _ = c.req("POST", f"/api/projects/{pid}/autoedit/apply", body)
    assert st == 200 and all(n["ok"] for n in r["extras"]), r["extras"]
    effs = r["project"]["effects"]
    censors = [e for e in effs if e["kind"] == "censor"]
    assert len(censors) == 1 and censors[0]["sound"] == "honk"
    assert 0 < len(effs) - 1 <= n_fun  # re-running replaced the old auto comedy edits instead of stacking
    assert r["project"]["captions"]["enabled"] is True
    # running again with the same settings is idempotent
    st, r2, _ = c.req("POST", f"/api/projects/{pid}/autoedit/apply", body)
    assert len(r2["project"]["effects"]) == len(effs)
    # the AI edit can be undone from history
    _, h, _ = c.req("GET", f"/api/projects/{pid}/history")
    assert sum(v["origin"] == "before_ai" for v in h["versions"]) == 2
    # and the result renders + validates
    _, ej, _ = c.req("POST", f"/api/projects/{pid}/exports",
                     {"filename": "oneclick", "quality": "draft",
                      "output": {"width": 320, "height": 180, "fps": 30, "fit_mode": "fit"}})
    ej = c.wait_job(ej["id"], timeout=400)
    assert ej["status"] == "succeeded" and ej["result"]["validation"]["ok"], ej
    # bad extras rejected
    bad = {**body, "extras": {"fun": "nuclear"}}
    assert c.req("POST", f"/api/projects/{pid}/autoedit/apply", bad)[0] == 422
