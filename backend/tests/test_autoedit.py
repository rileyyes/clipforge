"""Auto Editor tests on synthetic recordings with KNOWN structure.

Talk-like audio (modulated tone + noise floor) with silences, a short natural pause,
dead air and a loud reaction at known times; video with hard colour cuts at known
times. Assertions check the engine finds exactly what was planted.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from app.autoedit import AutoEditSettings, EDLError, plan, validate_edl
from app.config import Settings

RATE = 48000
# (start, end, amplitude) of sound; everything else is a quiet noise floor
SCRIPT = [(0, 4, 0.12), (6, 10, 0.12), (10.3, 14, 0.12), (20, 23, 0.8), (24, 30, 0.12)]
SILENCES = [(4, 6), (10, 10.3), (14, 20), (23, 24)]
CUTS = [7.0, 15.0]  # colour changes


def write_talk_wav(path: Path, script=SCRIPT, total=30.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(total * RATE)) / RATE
    x = rng.normal(0, 0.002, t.size)
    for s, e, amp in script:
        m = (t >= s) & (t < e)
        tt = t[m]
        # syllable-like 4 Hz envelope on a 180 Hz voice with harmonics
        env = 0.55 + 0.45 * np.abs(np.sin(2 * np.pi * 4 * tt))
        x[m] += amp * env * (np.sin(2 * np.pi * 180 * tt) + 0.4 * np.sin(2 * np.pi * 540 * tt))
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return path


@pytest.fixture(scope="module")
def talk_video(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("talk")
    wav = write_talk_wav(d / "talk.wav")
    out = d / "talk.mp4"
    # three solid colour shots (0-7 red, 7-15 blue, 15-30 green) with a moving box for motion
    graph = ("color=c=red:s=320x180:r=30:d=7[a];color=c=blue:s=320x180:r=30:d=8[b];"
             "color=c=green:s=320x180:r=30:d=15[c];[a][b][c]concat=n=3:v=1:a=0[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", graph, "-i", str(wav),
                    "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], check=True)
    return out


class Ctx:
    def __init__(self):
        import threading
        from types import SimpleNamespace
        self.job = SimpleNamespace(id="0" * 32)
        self.cancel_event = threading.Event()
        self.prog = []

    def stage(self, *a):
        pass

    def progress(self, p):
        self.prog.append(p)

    def check_cancel(self):
        pass


@pytest.fixture(scope="module")
def analysis(talk_video, tmp_path_factory):
    from app.analysis import analyze_media
    from app.media import build_asset
    d = tmp_path_factory.mktemp("proj")
    (d / "media" / "original").mkdir(parents=True)
    dst = d / "media" / "original" / ("a" * 32 + ".mp4")
    dst.write_bytes(talk_video.read_bytes())
    s = Settings(workspace=d)
    asset = build_asset(s, "a" * 32, dst, "talk.mp4")
    ctx = Ctx()
    analyze_media(ctx, s, d, asset)
    import json
    data = json.loads((d / "analysis" / f"{'a' * 32}.json").read_text())
    data["_progress"] = ctx.prog
    return data


def inside_sound(t: float, slack: float = 0.05) -> bool:
    return any(s + slack < t < e - slack for s, e, _ in SCRIPT)


# ---------------------------------------------------------------- analysis
def test_analysis_shapes_and_progress(analysis):
    assert analysis["hop"] == 0.05
    assert abs(len(analysis["rms_db"]) - 600) <= 2
    assert abs(len(analysis["motion"]) - 600) <= 2
    p = analysis["_progress"]
    assert p == sorted(p) and p[-1] == pytest.approx(1.0, abs=0.02)


def test_scene_cuts_detected_at_known_times(analysis):
    assert len(analysis["cuts"]) == len(CUTS), analysis["cuts"]
    for found, want in zip(analysis["cuts"], CUTS):
        assert abs(found - want) <= 0.3


def test_loudness_separates_sound_from_silence(analysis):
    rms = np.array(analysis["rms_db"])
    talk = rms[int(1 / 0.05):int(3 / 0.05)].mean()
    dead = rms[int(15 / 0.05):int(19 / 0.05)].mean()
    loud = rms[int(20.5 / 0.05):int(22.5 / 0.05)].mean()
    assert dead < talk - 25 and loud > talk + 10


# ---------------------------------------------------------------- planning
def test_original_length_removes_only_dead_air(analysis):
    r = plan(analysis, AutoEditSettings(target_mode="original", silence="balanced"))
    # all sound kept, long silences shortened to the retained pause
    assert all(b["selected"] for b in r["beats"])
    sound = sum(e - s for s, e, _ in SCRIPT)
    assert sound <= r["output_duration"] <= sound + 3.0
    assert r["dead_air_removed"] > 6.0
    # the 0.3 s natural pause inside 6-14 is never cut
    assert not any(10.0 < seg["source_out"] < 10.3 for seg in r["segments"])
    # no cut lands inside sound (never mid-word)
    for seg in r["segments"]:
        assert not inside_sound(seg["source_in"]) and not inside_sound(seg["source_out"]), seg


@pytest.mark.parametrize("preset,expected_cuts", [("conservative", 3), ("balanced", 4), ("aggressive", 4)])  # conservative keeps the 1 s gap
def test_silence_presets_keep_breathing_room(analysis, preset, expected_cuts):
    r = plan(analysis, AutoEditSettings(target_mode="original", silence=preset))
    keep = {"conservative": 0.35, "balanced": 0.22, "aggressive": 0.12}[preset]
    for seg in r["segments"]:
        # every segment starts a little before the sound and ends a little after it
        starts = [s for s, _, _ in SCRIPT if abs(seg["source_in"] - (s - keep)) < 0.12 or seg["source_in"] == 0]
        assert starts, (preset, seg)
    assert len(r["segments"]) == expected_cuts


def test_silence_off_keeps_everything(analysis):
    r = plan(analysis, AutoEditSettings(target_mode="original", silence="off"))
    assert r["output_duration"] == pytest.approx(30.0, abs=0.06)


def test_target_duration_and_reactions_style(analysis):
    r = plan(analysis, AutoEditSettings(target_mode="duration", target_seconds=8, style="reactions",
                                        keep_opening=False, context=False))
    chosen = [b for b in r["beats"] if b["selected"]]
    assert r["output_duration"] <= 8 * 1.02 + 0.01
    assert any(b["start"] <= 20 < b["end"] for b in chosen), "the loud reaction must be chosen"
    loud = next(b for b in r["beats"] if b["start"] <= 20 < b["end"])
    assert loud["score"] == max(b["score"] for b in r["beats"])
    assert any("reactions" in x for x in loud["reasons"])


def test_include_exclude_and_opening(analysis):
    base = plan(analysis, AutoEditSettings(target_mode="duration", target_seconds=6, keep_opening=True))
    assert base["beats"][0]["selected"] and base["beats"][0]["why"] == "opening hook"
    last = base["beats"][-1]["id"]
    r = plan(analysis, AutoEditSettings(target_mode="duration", target_seconds=6,
                                        include=[last], exclude=[0]))
    assert r["beats"][last]["selected"] and r["beats"][last]["why"] == "included by you"
    assert not r["beats"][0]["selected"] and r["beats"][0]["why"] == "excluded by you"


def test_unrealistic_targets_warn(analysis):
    long = plan(analysis, AutoEditSettings(target_mode="duration", target_seconds=3600))
    assert any("longer than the usable content" in w for w in long["warnings"])
    tiny = plan(analysis, AutoEditSettings(target_mode="duration", target_seconds=1))
    assert any("aggressive" in w for w in tiny["warnings"])
    humor = plan(analysis, AutoEditSettings(style="humor"))
    assert any("transcript" in w for w in humor["warnings"])


def test_deterministic(analysis):
    s = AutoEditSettings(target_mode="percent", target_percent=40, style="excitement")
    assert plan(analysis, s) == plan(analysis, s)


@pytest.mark.parametrize("pct", [5, 10, 25, 50, 75, 100])
def test_every_plan_is_a_valid_edl(analysis, pct):
    for style in ("balanced", "excitement", "information", "reactions", "action", "humor", "story"):
        for silence in ("off", "conservative", "balanced", "aggressive"):
            r = plan(analysis, AutoEditSettings(target_mode="percent", target_percent=pct,
                                                style=style, silence=silence))
            validate_edl(r["segments"], 30.0)
            assert r["output_duration"] == pytest.approx(
                sum(x["source_out"] - x["source_in"] for x in r["segments"]), abs=1e-3)
            for b in r["beats"]:
                assert b["reasons"] and 0 <= b["score"] <= 100


def test_word_boundaries_respected_with_transcript(analysis):
    data = dict(analysis)
    # a word that straddles the start of the 6 s talk block
    data["words"] = [{"start": 5.5, "end": 6.4, "text": "so", "p": 0.9},
                     {"start": 6.4, "end": 7.0, "text": "anyway", "p": 0.9}]
    r = plan(data, AutoEditSettings(target_mode="original", silence="aggressive"))
    seg = next(s for s in r["segments"] if 5 < s["source_out"] and s["source_in"] < 7)
    assert seg["source_in"] <= 5.5


@pytest.mark.parametrize("bad", [
    [{"source_in": -1, "source_out": 2}],
    [{"source_in": 0, "source_out": 31}],
    [{"source_in": 2, "source_out": 2.01}],
    [{"source_in": 5, "source_out": 8}, {"source_in": 7, "source_out": 9}],
    [{"source_in": float("nan"), "source_out": 2}],
])
def test_edl_validation_rejects_bad_segments(bad):
    with pytest.raises(EDLError):
        validate_edl(bad, 30.0)


def test_silent_and_noise_only_media(tmp_path):
    flat = {"duration": 10.0, "hop": 0.05, "rms_db": [-90.0] * 200, "motion": [], "cuts": []}
    r = plan(flat, AutoEditSettings())
    validate_edl(r["segments"], 10.0)
    noise = {"duration": 10.0, "hop": 0.05,
             "rms_db": list(np.random.default_rng(1).normal(-40, 1, 200)), "motion": [], "cuts": []}
    r = plan(noise, AutoEditSettings(target_mode="original"))
    validate_edl(r["segments"], 10.0)


def test_two_hour_scale_planning_is_fast():
    """2 h of analysis data (144k values) must plan quickly with bounded output."""
    import time
    rng = np.random.default_rng(7)
    n = int(7200 / 0.05)
    t = np.arange(n) * 0.05
    talk = (np.sin(t / 3.1) + 0.3 * rng.standard_normal(n)) > -0.2
    rms = np.where(talk, -22 + 4 * rng.standard_normal(n), -62 + rng.standard_normal(n))
    data = {"duration": 7200.0, "hop": 0.05, "rms_db": rms.round(2).tolist(),
            "motion": (rng.random(n) * 10).tolist(), "cuts": sorted(rng.random(300) * 7200)}
    t0 = time.time()
    r = plan(data, AutoEditSettings(target_mode="duration", target_seconds=1800))
    assert time.time() - t0 < 10
    validate_edl(r["segments"], 7200.0)
    assert 1500 <= r["output_duration"] <= 1800 * 1.02


def test_tied_features_get_equal_ranks():
    from app.autoedit import tie_aware_ranks
    r = tie_aware_ranks(np.array([0.0, 0.0, 5.0, 0.0]))
    assert r[0] == r[1] == r[3] and r[2] == 1.0


# ---------------------------------------------------------------- full API flow
def test_api_analyze_plan_apply_export(server, talk_video):
    st, p, _ = server.req("POST", "/api/projects", {"name": "auto"})
    pid = p["id"]
    _, up, _ = server.upload(pid, talk_video)
    mid = up["media"]["id"]
    st, r, _ = server.req("POST", f"/api/projects/{pid}/autoedit/plan", {"media_id": mid})
    assert st == 409  # must analyse first
    st, job, _ = server.req("POST", f"/api/projects/{pid}/autoedit/analyze", {"media_id": mid})
    assert st == 202
    j = server.wait_job(job["id"])
    assert j["status"] == "succeeded", j
    _, status, _ = server.req("GET", f"/api/projects/{pid}/autoedit")
    assert status["media"][0]["analyzed"] is True
    settings = {"target_mode": "duration", "target_seconds": 12, "style": "reactions"}
    st, plan_r, _ = server.req("POST", f"/api/projects/{pid}/autoedit/plan", {"media_id": mid, "settings": settings})
    assert st == 200 and plan_r["segments"]
    # stale review is refused
    st, _, _ = server.req("POST", f"/api/projects/{pid}/autoedit/apply",
                          {"media_id": mid, "settings": settings, "expected_output": plan_r["output_duration"] + 5})
    assert st == 409
    st, applied, _ = server.req("POST", f"/api/projects/{pid}/autoedit/apply",
                                {"media_id": mid, "settings": settings, "expected_output": plan_r["output_duration"]})
    assert st == 200, applied
    tl = applied["project"]["timeline"]
    v = [c for t in tl["tracks"] if t["kind"] == "video" for c in t["clips"]]
    a = [c for t in tl["tracks"] if t["kind"] == "audio" for c in t["clips"]]
    assert len(v) == len(a) == len(plan_r["segments"])
    assert all(x["link_id"] == y["link_id"] for x, y in zip(v, a))
    total = sum(c["source_out"] - c["source_in"] for c in v)
    assert total == pytest.approx(plan_r["output_duration"], abs=1e-3)
    # applying again snapshots the previous edit first, so the AI edit can be undone
    st, again, _ = server.req("POST", f"/api/projects/{pid}/autoedit/apply",
                              {"media_id": mid, "settings": settings, "expected_output": plan_r["output_duration"]})
    assert st == 200 and again["extras"] == []
    _, hist, _ = server.req("GET", f"/api/projects/{pid}/history")
    assert [v["origin"] for v in hist["versions"]].count("before_ai") == 1
    # bad settings rejected by validation
    st, _, _ = server.req("POST", f"/api/projects/{pid}/autoedit/plan",
                          {"media_id": mid, "settings": {"target_seconds": -5}})
    assert st == 422
    st, _, _ = server.req("POST", f"/api/projects/{pid}/autoedit/plan", {"media_id": "../../x"})
    assert st == 404
    # and the rough cut renders + validates
    st, ej, _ = server.req("POST", f"/api/projects/{pid}/exports",
                           {"filename": "rough", "quality": "draft",
                            "output": {"width": 320, "height": 180, "fps": 30, "fit_mode": "fit"}})
    ej = server.wait_job(ej["id"])
    assert ej["status"] == "succeeded" and ej["result"]["validation"]["ok"], ej


def test_video_without_audio_still_plans():
    data = {"duration": 20.0, "hop": 0.05, "rms_db": [], "motion": [float(i % 40) for i in range(400)],
            "cuts": [5.0, 12.0]}
    r = plan(data, AutoEditSettings(target_mode="duration", target_seconds=8, style="action"))
    validate_edl(r["segments"], 20.0)
    assert any("no audio" in w for w in r["warnings"])
    assert 0 < r["output_duration"] <= 8 * 1.02


def test_planner_randomized_properties():
    """400 random recordings x random settings: the plan is always a valid EDL,
    never exceeds the target (unless the user forces moments in), never cuts inside
    a sound region, and is deterministic."""
    import random
    styles = ["balanced", "excitement", "information", "reactions", "action", "humor", "story"]
    rnd = random.Random(1234)
    for case in range(400):
        dur = rnd.choice([3.0, 17.3, 60.0, 245.7, 900.0])
        n = int(dur / 0.05)
        rng = np.random.default_rng(case)
        on = rng.random(n) < rnd.random()
        # make runs: smooth the on/off pattern so there are real phrases and pauses
        on = np.convolve(on, np.ones(rnd.choice([1, 5, 20, 60])), "same") > 0.5
        rms = np.where(on, rng.normal(-24, 5, n), rng.normal(-60, 3, n))
        data = {"duration": dur, "hop": 0.05,
                "rms_db": rms.round(2).tolist() if rnd.random() > 0.1 else [],
                "motion": (rng.random(n) * 20).tolist() if rnd.random() > 0.2 else [],
                "cuts": sorted(rng.random(rnd.randint(0, 20)) * dur)}
        beats_guess = rnd.randint(0, 6)
        s = AutoEditSettings(
            target_mode=rnd.choice(["original", "duration", "percent"]),
            target_seconds=rnd.choice([1, 5, 30, 60, 600]), target_percent=rnd.choice([5, 20, 50, 100]),
            style=rnd.choice(styles), silence=rnd.choice(["off", "conservative", "balanced", "aggressive"]),
            keep_opening=rnd.random() < 0.5, context=rnd.random() < 0.5,
            exclude=[rnd.randint(0, 10) for _ in range(beats_guess)])
        r = plan(data, s)
        validate_edl(r["segments"], dur)
        assert plan(data, s) == r, f"case {case}: not deterministic"
        if s.target_mode != "original" and not s.include:
            assert r["output_duration"] <= r["target_duration"] * 1.02 + 1e-6, (case, r["output_duration"], r["target_duration"])
        excluded = set(s.exclude)
        assert not any(b["selected"] and b["id"] in excluded for b in r["beats"])
        if data["rms_db"] and s.silence != "off":
            # cuts only between sound regions: no segment edge strictly inside a voiced run
            thr = r["levels"]["threshold_db"]
            a = np.asarray(data["rms_db"])
            for seg in r["segments"]:
                for edge in (seg["source_in"], seg["source_out"]):
                    i = int(round(edge / 0.05))
                    if 2 <= i < len(a) - 2 and 0 < edge < dur:
                        assert not (a[i - 2:i + 2] > thr).all(), (case, edge)
