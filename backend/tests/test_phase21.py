"""Phase 21: auto multicam, motion graphics, auto colour, edit-by-typing (local AI part)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app import colorfix as CF
from app import multicam as MC
from app import titles
from app.schema import ColorAdjust, Multicam, Project, SCHEMA_VERSION, Title, migrate
from app.storage import new_id

from .test_audio_transitions import _project, _render
from .test_phase15 import frame_at

HOP = MC.HOP
DATA = Path(__file__).parent / "data"


def T(**kw) -> dict:
    base = {"id": new_id(), "start": 0.0, "duration": 4.0, "template": "chart", "text": "", "subtext": "", "color": "#ffffff",
            "accent": "#ff5a3c", "align": "left", "size": 1.0}
    return {**base, **kw}


# ---------------------------------------------------------------- multicam: choosing cameras
def _speech(n_s: float, parts: list[tuple[float, float, float]]) -> np.ndarray:
    """A mic's loudness (dB per HOP): quiet room, louder where (start, end, dB)."""
    rng = np.random.default_rng(3)
    db = np.full(int(n_s / HOP), -70.0) + rng.normal(0, 1, int(n_s / HOP))
    for a, b, lvl in parts:
        db[int(a / HOP):int(b / HOP)] = lvl + rng.normal(0, 1.5, int(b / HOP) - int(a / HOP))
    return db


def _two_people():
    # A talks 0-10 and 25-40; B talks 10-25 and 52-60; both at once 40-45; nobody 45-52.
    # Each voice leaks into the other mic ~20 dB lower; A says "yeah" (0.3 s) at 15.
    a = _speech(60, [(0, 10, -20), (10, 25, -34), (15, 15.3, -20), (25, 40, -20), (40, 45, -20)])
    b = _speech(60, [(0, 10, -40), (10, 25, -14), (25, 40, -40), (40, 45, -14), (52, 60, -14)])
    return a, b


def test_multicam_follows_who_is_talking():
    a, b = _two_people()
    sw = MC.plan(np.maximum(a, b), [(a, 0.0, 0), (b, 0.0, 1)], mode="speaker", n_angles=3, wide=2)
    got = [(round(s.t), s.angle) for s in sw]
    assert got == [(0, 0), (10, 1), (25, 0), (40, 2), (52, 1)], got           # the "yeah" doesn't cut away
    assert MC.summary(sw, 60, 3) == pytest.approx([25 / 60, 23 / 60, 12 / 60], abs=0.01)
    # without a wide camera it stays on the last person through overlaps and pauses
    sw = MC.plan(np.maximum(a, b), [(a, 0.0, 0), (b, 0.0, 1)], mode="speaker", n_angles=2)
    assert [s.angle for s in sw] == [0, 1, 0, 1]
    assert all(y.t - x.t >= 2.0 - 1e-9 for x, y in zip(sw, sw[1:]))           # shortest shot


def test_multicam_lines_mics_up_by_offset():
    a, b = _two_people()
    late = np.concatenate([np.full(int(3 / HOP), -70.0), b])                 # B's mic started 3 s later
    sw = MC.plan(np.maximum(a, b), [(a, 0.0, 0), (late, 3.0, 1)], mode="speaker", n_angles=2)
    assert [(round(s.t), s.angle) for s in sw][:3] == [(0, 0), (10, 1), (25, 0)]


def test_multicam_min_shot_and_quick_back_and_forth():
    # rapid back-and-forth every 0.8 s: no flicker, every shot at least min_shot long
    parts_a = [(i * 1.6, i * 1.6 + 0.8, -20) for i in range(20)]
    parts_b = [(i * 1.6 + 0.8, i * 1.6 + 1.6, -20) for i in range(20)]
    a, b = _speech(32, parts_a), _speech(32, parts_b)
    sw = MC.plan(np.maximum(a, b), [(a, 0.0, 0), (b, 0.0, 1)], mode="speaker", n_angles=2, min_shot=3.0)
    assert all(y.t - x.t >= 3.0 - 1e-9 for x, y in zip(sw, sw[1:])), sw
    assert all(x.angle != y.angle for x, y in zip(sw, sw[1:]))


def test_multicam_pace_cuts_between_sentences():
    db = _speech(60, [(i * 3.0, i * 3.0 + 2.5, -20) for i in range(20)])     # sentences with 0.5 s gaps
    sw = MC.plan(db, [], mode="pace", n_angles=3, pace=6)
    gaps = [y.t - x.t for x, y in zip(sw, sw[1:])]
    assert sw[0].t == 0 and len(sw) >= 7 and all(2.5 <= g <= 9.5 for g in gaps), gaps
    for s in sw[1:]:
        assert (s.t % 3.0) >= 2.45 or (s.t % 3.0) < 0.05, s                 # in a gap between sentences
    assert all(x.angle != y.angle for x, y in zip(sw, sw[1:]))
    assert set(s.angle for s in sw) == {0, 1, 2}
    assert MC.plan(db, [], mode="pace", n_angles=1, pace=6) == [MC.Switch(0.0, 0)]


def test_multicam_schema_rules():
    m, c = new_id(), new_id()
    ok = {"main_media_id": m, "angles": [{"media_id": m}, {"media_id": c, "offset": 1.5}], "switches": [{"t": 0, "angle": 0}, {"t": 3, "angle": 1}]}
    Multicam.model_validate(ok)
    for bad in ({**ok, "angles": [{"media_id": c}, {"media_id": m}]},                         # angle 0 must be the main one
                {**ok, "switches": [{"t": 3, "angle": 1}, {"t": 0, "angle": 0}]},            # out of order
                {**ok, "switches": [{"t": 0, "angle": 2}]},                                  # no such camera
                {**ok, "wide": 3},
                {**ok, "angles": [{"media_id": m}]}):                                        # one camera
        with pytest.raises(ValidationError):
            Multicam.model_validate(bad)
    assert SCHEMA_VERSION == 10 and migrate({"schema_version": 9, "id": new_id(), "name": "x"})["schema_version"] == 10


def _cam(path: Path, colour: str, secs: float, expr: str, delay: float = 0.0):
    """A 'camera': a coloured picture with the room sound (expr), starting ``delay`` s late."""
    a = f"aevalsrc='{expr}':s=48000:d={secs + 2}"
    af = f"atrim=start={delay},asetpts=PTS-STARTPTS" if delay else "anull"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={colour}:s=160x90:r=25:d={secs}",
                    "-f", "lavfi", "-i", a, "-af", af, "-t", str(secs), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)


# two people in a room: A talks 0-8 and 20-28, B 8-20 and 28-36 (each mic hears the other quietly);
# a few knocks at irregular times make the sound easy to line up
KNOCKS = "+".join(f"between(t,{a},{a + 0.08})" for a in (1.3, 5.9, 11.7, 14.2, 17.3, 23.6, 25.9, 31.4, 33.1))
ROOM = ("(0.9*(" + KNOCKS + ")*sin(2*PI*900*t)+0.02*sin(2*PI*137*t)*(0.5+0.5*sin(2*PI*3*t))+0.3*(lt(t,8)+between(t,20,28))*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*5*t))"
        "+0.3*(between(t,8,20)+between(t,28,36))*sin(2*PI*330*t)*(0.6+0.4*sin(2*PI*7*t)))")
MIC_A = ("(0.6*(" + KNOCKS + ")*sin(2*PI*900*t)+0.01*sin(2*PI*137*t)+0.5*(lt(t,8)+between(t,20,28))*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*5*t))"
         "+0.04*(between(t,8,20)+between(t,28,36))*sin(2*PI*330*t))")
MIC_B = ("(0.6*(" + KNOCKS + ")*sin(2*PI*900*t)+0.01*sin(2*PI*137*t)+0.04*(lt(t,8)+between(t,20,28))*sin(2*PI*220*t)"
         "+0.5*(between(t,8,20)+between(t,28,36))*sin(2*PI*330*t)*(0.6+0.4*sin(2*PI*7*t)))")


def test_multicam_job_lines_up_and_switches(server, tmp_path):
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "podcast"})
    pid = p["id"]
    _cam(tmp_path / "wide.mp4", "gray", 36, ROOM)
    _cam(tmp_path / "camb.mp4", "red", 34, ROOM, delay=2.0)          # started 2 s after the main camera
    ids = {}
    for name in ("wide.mp4", "camb.mp4"):
        st, r, _ = c.upload(pid, tmp_path / name)
        assert c.wait_job(r["job_id"])["status"] == "succeeded"
        ids[name] = r["media"]["id"]
    # separate mics (audio files), lined up with the main camera
    for name, expr in (("mic_a.wav", MIC_A), ("mic_b.wav", MIC_B)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d=36", str(tmp_path / name)], check=True)
        st, r, _ = c.upload(pid, tmp_path / name)
        assert c.wait_job(r["job_id"])["status"] == "succeeded"
        ids[name] = r["media"]["id"]
    body = {"angles": [{"media_id": ids["wide.mp4"], "mic_media_id": ids["mic_a.wav"]},
                       {"media_id": ids["camb.mp4"], "mic_media_id": ids["mic_b.wav"]}], "mode": "speaker", "min_shot": 2}
    st, job, _ = c.req("POST", f"/api/projects/{pid}/multicam", body)
    assert st == 202, job
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded", j.get("error_detail")
    r = j["result"]
    assert r["angles"][1]["offset"] == pytest.approx(-2.0, abs=0.02)          # (synthetic tones: low confidence is fine)
    got = [(round(s["t"]), s["angle"]) for s in r["switches"]]
    assert got == [(0, 0), (8, 1), (20, 0), (28, 1)], got
    # the result is valid as the project's multicam
    _, pr, _ = c.req("GET", f"/api/projects/{pid}")
    pr["timeline"]["multicam"] = {k: r[k] for k in ("main_media_id", "mode", "wide", "min_shot", "pace", "switches")} | {
        "angles": [{k: a[k] for k in ("media_id", "offset", "mic_media_id", "mic_offset")} for a in r["angles"]]}
    st, out, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": pr["edit_revision"], "timeline": pr["timeline"], "output": pr["output"]})
    assert st == 200, out
    # its media can't be deleted while multicam uses it
    st, out, _ = c.req("DELETE", f"/api/projects/{pid}/media/{ids['mic_b.wav']}")
    assert st == 409 and "multicam" in str(out)
    # bad requests
    for bad, code in (({"angles": [body["angles"][0], body["angles"][0]]}, 422),
                      ({"angles": [{"media_id": ids["mic_a.wav"]}, body["angles"][1]]}, 409),     # a sound file isn't a camera
                      ({"angles": body["angles"], "wide": 2}, 422)):
        st, out, _ = c.req("POST", f"/api/projects/{pid}/multicam", bad)
        assert st == code, (bad, out)


def test_multicam_needs_two_mics_to_follow_talking(server, tmp_path):
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "silent cams"})
    pid = p["id"]
    ids = []
    for name, col in (("a.mp4", "gray"), ("b.mp4", "red")):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=160x90:r=25:d=5", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(tmp_path / name)], check=True)
        st, r, _ = c.upload(pid, tmp_path / name)
        c.wait_job(r["job_id"])
        ids.append(r["media"]["id"])
    angles = [{"media_id": ids[0]}, {"media_id": ids[1]}]
    st, out, _ = c.req("POST", f"/api/projects/{pid}/multicam", {"angles": angles})
    assert st == 409 and "no sound" in out["error"]                                     # can't line up without sound
    st, job, _ = c.req("POST", f"/api/projects/{pid}/multicam", {"angles": [angles[0], {**angles[1], "offset": 0}], "mode": "pace", "pace": 2})
    assert st == 202
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded" and len(j["result"]["switches"]) >= 2               # pace mode works without sound


def test_multicam_export_shows_each_camera(tmp_path):
    # the edit (applied by the Editor) is plain clips of each camera: check that the export shows them
    s, p, pdir, media = _project(tmp_path, [("blue", 0, {"start": 0, "source_in": 0, "source_out": 3}),
                                            ("red", 0, {"start": 3, "source_in": 1, "source_out": 4})])
    d = p.model_dump(mode="json")
    d["timeline"]["multicam"] = {"main_media_id": media["blue"].id, "mode": "pace", "switches": [{"t": 0, "angle": 0}, {"t": 3, "angle": 1}],
                                 "angles": [{"media_id": media["blue"].id}, {"media_id": media["red"].id, "offset": -2}]}
    out, r = _render(s, Project.model_validate(d), pdir, "mc")
    assert r["validation"]["ok"]
    assert frame_at(out, 1.0)[18, 32][2] > 150 and frame_at(out, 4.5)[18, 32][0] > 150


# ---------------------------------------------------------------- motion graphics
def test_motion_vectors_match_the_preview_rules():
    v = json.loads((DATA / "motion_vectors.json").read_text())
    for tt, i, g in v["bar_grow"]:
        assert titles.bar_grow(tt, i) == pytest.approx(g, abs=1e-9)
    for val, fmt, dec, txt in v["fmt_value"]:
        assert titles.fmt_value(val, fmt, dec) == txt
    for vals, d in v["decimals"]:
        assert titles.decimals(vals) == d
    for t, tt, val, frac in v["ring"]:
        assert titles.ring_value(tt, t) == pytest.approx(val, abs=1e-9) and titles.ring_fraction(val, t) == pytest.approx(frac, abs=1e-9)
    for i, n, dur, d in v["list_delay"]:
        assert titles.list_delay(i, n, dur) == pytest.approx(d, abs=1e-9)


def test_motion_graphics_validate():
    Title.model_validate(T(template="chart", items=[{"label": "A", "value": 3}] * 10, format="percent"))
    Title.model_validate(T(template="progress", duration=3600))
    with pytest.raises(ValidationError):
        Title.model_validate(T(template="chart", duration=3600))                    # only a progress bar may be that long
    with pytest.raises(ValidationError):
        Title.model_validate(T(template="chart", items=[{"label": "A", "value": 3}] * 11))
    with pytest.raises(ValidationError):
        Title.model_validate(T(template="list", items=[{"label": "x" * 41, "value": 0}]))


def test_chart_bars_grow_in_order_and_numbers_roll_up():
    t = T(template="chart", start=1, duration=5, format="money", items=[{"label": "A", "value": 100}, {"label": "B", "value": 50.5}])
    ev = titles.events(t, 1920, 1080, titles.Measure(None))
    bars = [e for e in ev if "\\clip(" in e and "\\t(" in e]
    assert len(bars) == 2
    assert "\\t(250,850,0.4," in bars[0] and "\\t(370,970,0.4," in bars[1]       # staggered
    w = [float(e.split("\\clip(")[2].split(",")[2]) - float(e.split("\\clip(")[2].split(",")[0]) for e in bars]
    assert w[1] == pytest.approx((w[0] - 1) * 0.505 + 1, abs=2)                 # B half as long
    texts = [e.rsplit("}", 1)[1] for e in ev if "\\an4" in e]
    assert texts[0] == "$0" and "$100" in texts and "$50.5" in texts            # rolls up to the value
    last = [e for e in ev if "\\an4" in e and e.rsplit("}", 1)[1] == "$100"][0]
    assert ",0:00:06.00," in last                                               # held to the end


def test_ring_progress_bar_list_quote_end_screen_draw():
    m = titles.Measure(None)
    ring = titles.events(T(template="ring", count_from=0, count_to=50, format="percent", text="Score"), 1920, 1080, m)
    nums = [e.rsplit("}", 1)[1] for e in ring if "\\an5" in e]
    assert nums[0] == "0%" and nums[-1] == "50%"
    lst = titles.events(T(template="list", duration=6, text="Why", items=[{"label": a, "value": 0} for a in "xyz"]), 1920, 1080, m)
    assert sum(1 for e in lst if "\\move(" in e) == 9                           # badge, number, text for each
    prog = titles.events(T(template="progress", start=0, duration=60, _chapters=[(0, "Intro"), (20, "Main"), (50, "End")]), 1920, 1080, m)
    assert sum(1 for e in prog if e.endswith("Intro") or e.endswith("Main") or e.endswith("End")) == 3
    assert any("\\t(0,60000,\\clip(" in e for e in prog)
    q = titles.events(T(template="quote", text="A long quote that should wrap onto more than one line in the card " * 1, subtext="Me"), 1920, 1080, m)
    assert any(e.endswith("— Me") for e in q) and sum(1 for e in q if "\\an7\\pos(" in e and "\\alpha&HFF&" in e) >= 2
    es = titles.events(T(template="end_screen", duration=20, text="", subtext="SUBSCRIBE"), 1920, 1080, m)
    assert any(e.endswith("WATCH NEXT") for e in es) and len(es) == 6


def test_motion_graphics_export(tmp_path):
    s, p, pdir, media = _project(tmp_path, [("blue", 0, {"start": 0, "source_in": 0, "source_out": 6})])
    d = p.model_dump(mode="json")
    d["timeline"]["markers"] = [{"id": new_id(), "t": 0, "label": "Intro", "color": "#ffb703"},
                                {"id": new_id(), "t": 3, "label": "Part two", "color": "#ffb703"}]
    d["timeline"]["titles"] = [T(template="chart", start=0, duration=3, items=[{"label": "A", "value": 10}, {"label": "B", "value": 5}], x=0.5, y=0.5, w=0.6),
                               T(template="ring", start=3, duration=3, count_from=0, count_to=100, format="percent", x=0.5, y=0.5),
                               T(template="progress", start=0, duration=6, y=0.97)]
    out, r = _render(s, Project.model_validate(d), pdir, "mg")
    assert r["validation"]["ok"]
    f = frame_at(out, 2.0)
    assert (np.abs(f.astype(int) - [255, 90, 60]).sum(axis=2) < 90).any()       # an accent-coloured bar
    # the progress bar is about half full at 3 s (accent on the left half of the bottom row, not the right)
    g = frame_at(out, 3.0)
    row = g[int(g.shape[0] * 0.97)]
    acc = (np.abs(row.astype(int) - [255, 90, 60]).sum(axis=1) < 120)
    w = len(row)
    assert acc[int(w * 0.1):int(w * 0.4)].mean() > 0.8 and acc[int(w * 0.6):int(w * 0.9)].mean() < 0.2


# ---------------------------------------------------------------- auto colour
def _clip_file(path: Path, vf: str, secs: float = 3):
    """A fairly neutral scene (the test pattern, toned down), then ``vf`` (the camera's problem)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=25:d={secs}", "-vf", f"eq=saturation=0.35,{vf}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


def test_auto_fix_brightens_a_dark_cool_picture(tmp_path):
    _clip_file(tmp_path / "bad.mp4", "eq=brightness=-0.15:contrast=0.75,colortemperature=temperature=9500")
    png = CF.sample("ffmpeg", tmp_path / "bad.mp4", [(0, 3)], tmp_path / "w")
    c, before, after = CF.solve("ffmpeg", png, CF.TARGET, False)
    assert c.brightness > 0.05 and c.contrast > 1.1 and c.temperature > 0.05, c    # brighter, punchier, warmer
    assert abs(after.mid - 0.45) < abs(before.mid - 0.45) and abs(after.cast) < abs(before.cast)
    assert after.hi - after.lo > before.hi - before.lo


def test_auto_fix_leaves_a_good_picture_alone(tmp_path):
    _clip_file(tmp_path / "ok.mp4", "null")
    png = CF.sample("ffmpeg", tmp_path / "ok.mp4", [(0, 3)], tmp_path / "w")
    c, before, after = CF.solve("ffmpeg", png, CF.TARGET, False)
    assert abs(c.brightness) <= 0.12 and 0.8 <= c.contrast <= 1.25 and abs(c.temperature) <= 0.2, c


def test_match_brings_camera_b_to_camera_a(tmp_path):
    _clip_file(tmp_path / "a.mp4", "null")
    _clip_file(tmp_path / "b.mp4", "eq=brightness=0.1:contrast=0.8:saturation=0.7,colortemperature=temperature=5200")
    ref = CF.sample("ffmpeg", tmp_path / "a.mp4", [(0, 3)], tmp_path / "wa")
    target = CF.target_of("ffmpeg", ref, ColorAdjust())
    png = CF.sample("ffmpeg", tmp_path / "b.mp4", [(0, 3)], tmp_path / "wb")
    c, before, after = CF.solve("ffmpeg", png, target, True)
    assert c.temperature < -0.05 and c.contrast > 1.05, c                           # cooler and punchier, like A
    for k in ("mid", "cast", "sat"):
        assert abs(getattr(after, k) - getattr(target, k)) < abs(getattr(before, k) - getattr(target, k)), k


def test_color_auto_api(server, tmp_path):
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "colour"})
    pid = p["id"]
    _clip_file(tmp_path / "dark.mp4", "eq=brightness=-0.2")
    _clip_file(tmp_path / "ref.mp4", "null")
    ids = []
    for f in ("dark.mp4", "ref.mp4"):
        st, r, _ = c.upload(pid, tmp_path / f)
        c.wait_job(r["job_id"])
        ids.append(r["media"]["id"])
    st, r, _ = c.req("POST", f"/api/projects/{pid}/color/auto", {"media_ids": [ids[0]], "mode": "fix"})
    assert st == 200, r
    res = r["results"][ids[0]]
    assert res["changed"] and res["color"]["brightness"] > 0.05 and res["after"]["mid"] > res["before"]["mid"]
    ColorAdjust.model_validate(res["color"])
    st, r, _ = c.req("POST", f"/api/projects/{pid}/color/auto", {"media_ids": [ids[0]], "mode": "match", "reference_media_id": ids[1]})
    assert st == 200 and r["results"][ids[0]]["changed"]
    for bad in ({"media_ids": [ids[0]], "mode": "match"}, {"media_ids": [ids[0]], "mode": "match", "reference_media_id": ids[0]},
                {"media_ids": [new_id()]}):
        st, r, _ = c.req("POST", f"/api/projects/{pid}/color/auto", bad)
        assert st in (404, 422), (bad, r)


# ---------------------------------------------------------------- edit by typing: local AI
def test_command_ai_without_a_local_ai(server, monkeypatch):
    from app import language
    monkeypatch.setattr(language, "text_model", lambda: None)
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "cmd"})
    st, r, _ = c.req("POST", f"/api/projects/{p['id']}/command/ai", {"text": "make it pop"})
    assert st == 409 and "Ollama" in r["error"]


def test_command_ai_turns_words_into_command_lines(server, monkeypatch):
    from app import language

    class Fake:
        def chat_json(self, system, user, **kw):
            assert "cut M:SS to M:SS" in system and "1:05" in user and "zoom" in user
            return {"lines": ["add a zoom at 1:05", "  ", 42, {"x": 1}, "music to 30%"]}
    monkeypatch.setattr(language, "text_model", lambda: Fake())
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "cmd"})
    st, r, _ = c.req("POST", f"/api/projects/{p['id']}/command/ai", {"text": "zoom in here and turn the music down", "playhead": 65})
    assert st == 200 and r["lines"] == ["add a zoom at 1:05", "42", "music to 30%"]
