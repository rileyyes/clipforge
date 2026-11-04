"""Phase 8.1: Shorts — best moments, vertical 9:16, keeps the subject in frame."""
from __future__ import annotations

import os
import stat
import subprocess

import numpy as np
import pytest

from app import shorts as SH


def _analysis(dur=120.0, loud=(60, 75)):
    rms = []
    for i in range(int(dur / 0.05)):
        t = i * 0.05
        v = -22.0 if (t % 6) < 4.5 else -60.0
        if loud[0] <= t < loud[1] and (t % 6) < 4.5:
            v = -6.0 + 4 * np.sin(t * 7)  # big reactions
        rms.append(float(v))
    return {"duration": dur, "hop": 0.05, "rms_db": rms, "motion": [], "cuts": [], "words": None}


def test_suggestions_are_sized_non_overlapping_and_find_the_reactions():
    s = SH.suggest(_analysis(), count=4, min_s=15, max_s=40)
    assert 1 <= len(s) <= 4
    for x in s:
        assert 15 <= x["duration"] <= 40.01 and x["reasons"]
    for a in s:
        for b in s:
            if a is not b:
                assert a["end"] <= b["start"] or b["end"] <= a["start"]
    best = s[0]
    assert best["start"] < 75 and best["end"] > 60, best  # the reaction stretch wins
    assert s == sorted(s, key=lambda x: -x["score"])


def test_hook_and_title_from_transcript():
    a = _analysis()
    a["words"] = [{"start": 60.2 + i * 0.4, "end": 60.5 + i * 0.4, "text": " " + w, "p": 0.9}
                  for i, w in enumerate("you will not believe what just happened. so then".split())]
    best = SH.suggest(a, count=1)[0]
    assert best["hook"].startswith("you will not believe") and best["title"] == "You will not believe what just happened"


def test_vertical_geometry():
    scale, pw = SH.vertical_geometry(1920, 1080)
    assert scale == pytest.approx(1920 / 607.5, abs=1e-3) and pw == pytest.approx(3413.3, abs=1)
    assert SH.vertical_geometry(1080, 1920) == (1.0, 1080.0)  # already vertical: nothing to do


def S(t, cx, kind="face"):
    return SH.Sample(t, cx, kind)


def test_camera_holds_inside_the_deadzone_and_moves_when_you_leave_it():
    samples = [S(t / 2, 0.30 + 0.005 * (t % 3)) for t in range(20)] + [S(10 + t / 2, 0.70) for t in range(20)]
    path = SH.camera_path(samples)
    assert len(path) == 2 and path[0][1] == pytest.approx(0.30, abs=0.02) and path[1][1] == pytest.approx(0.70)
    assert 10 <= path[1][0] <= 11


def test_camera_ignores_one_off_false_detections_and_clamps_to_the_frame():
    samples = [S(t / 2, 0.5) for t in range(20)]
    samples[7] = S(3.5, 0.95)  # a false face on the edge for one sample
    assert len(SH.camera_path(samples)) == 1
    edge = SH.camera_path([S(t / 2, 0.01) for t in range(6)])
    assert edge[0][1] == pytest.approx(0.3164 / 2)  # never pans past the picture


def test_motion_is_ignored_when_faces_are_found_and_gaps_hold_position():
    samples = []
    for t in range(30):
        samples.append(S(t / 2, 0.4, "face") if t % 3 else S(t / 2, 0.9, "motion"))
    samples += [S(15 + t / 2, None, "none") for t in range(10)]
    path = SH.camera_path(samples)
    assert len(path) == 1 and path[0][1] == pytest.approx(0.4)


def test_keyframes_ease_hold_then_move_and_stay_in_limits():
    path = [(0.0, 0.3), (5.0, 0.7), (9.0, 0.5)]
    k = SH.keyframes_for(path, 3413, 1080)
    lim = (3413 - 1080) / 2
    assert all(abs(x["v"]) <= lim + 1e-6 for x in k)
    assert [round(x["t"], 1) for x in k] == [0.0, 4.4, 5.0, 8.4, 9.0]
    assert k[0]["v"] == pytest.approx(0.2 * 3413, abs=1) and k[1]["v"] == k[0]["v"]  # hold before the move
    assert all(b["t"] - a["t"] >= 0.001 for a, b in zip(k, k[1:]))
    many = SH.keyframes_for([(i * 1.0, 0.3 if i % 2 else 0.7) for i in range(200)], 3413, 1080)
    assert len(many) <= 64


def moving_square(path, d=20.0):
    """Dark picture with a bright square sliding left -> right (a 'subject' with no face)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x202020:s=640x360:r=25:d={d}",
                    "-f", "lavfi", "-i", f"aevalsrc='0.25*sin(2*PI*220*t)*lt(mod(t,5),4)':s=48000:d={d}",
                    "-f", "lavfi", "-i", f"color=c=white:s=80x80:r=25:d={d}",
                    "-filter_complex", f"[0:v][2:v]overlay=x='40+520*t/{d}':y=140:shortest=1[v]",
                    "-map", "[v]", "-map", "1:a", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return path


def test_tracks_a_moving_subject_without_a_face(tmp_path):
    src = moving_square(tmp_path / "m.mp4")
    samples = SH.sample_track("ffmpeg", src, 0, 20, 640, 360)
    xs = [s.cx for s in samples if s.cx is not None]
    assert len(samples) >= 38 and all(s.kind in ("motion", "none", "face") for s in samples)
    assert xs[0] < 0.3 and xs[-1] > 0.7  # follows it across


def test_face_model_loads():
    det = SH._detector()
    assert det is not None and det(np.zeros((180, 320), np.uint8)) == []


# ---------------------------------------------------------------- API + render
def _frame(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=270:480",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(480, 270)


def test_api_make_a_short_that_follows_the_subject(server, tmp_path):
    c = server
    src = moving_square(tmp_path / "sq.mp4")
    _, p, _ = c.req("POST", "/api/projects", {"name": "Gaming"})
    pid = p["id"]
    up = c.upload(pid, src)[1]
    mid = up["media"]["id"]
    c.wait_job(up["job_id"])
    assert c.req("POST", f"/api/projects/{pid}/shorts/suggest", {"media_id": mid})[0] == 409  # analyse first
    _, job, _ = c.req("POST", f"/api/projects/{pid}/autoedit/analyze", {"media_id": mid, "transcribe": False})
    assert c.wait_job(job["id"])["status"] == "succeeded"
    st, sug, _ = c.req("POST", f"/api/projects/{pid}/shorts/suggest", {"media_id": mid, "min_seconds": 5, "max_seconds": 15})
    assert st == 200 and sug["suggestions"] and all(5 <= x["duration"] <= 15.01 for x in sug["suggestions"])
    assert c.req("POST", f"/api/projects/{pid}/shorts", {"media_id": mid, "start": 5, "end": 6})[0] == 422
    assert c.req("POST", f"/api/projects/{pid}/shorts", {"media_id": mid, "start": 0, "end": 999})[0] == 422
    st, job, _ = c.req("POST", f"/api/projects/{pid}/shorts", {"media_id": mid, "start": 0, "end": 20})
    assert st == 202
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded", j
    res = j["result"]
    assert res["name"] == "Gaming — Short 1" and res["follow"]["moves"] >= 2 and res["follow"]["motion"] > 20
    _, short, _ = c.req("GET", f"/api/projects/{res['project_id']}")
    assert (short["output"]["width"], short["output"]["height"]) == (1080, 1920)
    clip = short["timeline"]["tracks"][0]["clips"][0]
    assert clip["transform"]["scale"] > 3 and len(clip["keyframes"]["x"]) >= 3
    assert short["timeline"]["tracks"][2]["clips"][0]["link_id"] == clip["link_id"]
    # media shared, not copied
    so = c.settings.projects_dir / pid / "media" / "original" / up["media"]["stored_name"]
    sh = c.settings.projects_dir / res["project_id"] / "media" / "original" / up["media"]["stored_name"]
    if os.name != "nt":
        assert os.stat(so).st_ino == os.stat(sh).st_ino
    # export and check the square stays near the middle as it crosses the original frame
    _, ej, _ = c.req("POST", f"/api/projects/{res['project_id']}/exports",
                     {"filename": "short", "quality": "draft", "output": {**short["output"], "width": 540, "height": 960}})
    ej = c.wait_job(ej["id"], timeout=400)
    assert ej["status"] == "succeeded" and ej["result"]["validation"]["ok"], ej
    out = c.settings.projects_dir / res["project_id"] / "exports" / ej["result"]["file"]
    for t in (2.0, 10.0, 18.0):
        f = _frame(out, t)
        cols = np.flatnonzero(f.max(axis=0) > 200)
        assert cols.size, t
        centre = (cols[0] + cols[-1]) / 2 / 270
        assert 0.15 < centre < 0.85, (t, centre)  # in the vertical frame, not lost off-screen
    # without following, the square leaves the frame
    st, job, _ = c.req("POST", f"/api/projects/{pid}/shorts", {"media_id": mid, "start": 0, "end": 20, "follow": False,
                                                               "title": "static"})
    r2 = c.wait_job(job["id"])["result"]
    assert r2["name"] == "Gaming — Short: static" and r2["follow"]["moves"] == 0
    # deleting a Short never touches the source project's files
    assert c.req("DELETE", f"/api/projects/{res['project_id']}")[0] in (200, 204)
    assert so.is_file()
    if os.name != "nt":
        assert not (os.stat(so).st_mode & stat.S_IWUSR)  # still read-only
