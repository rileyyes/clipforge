"""Phase 16: hook checker, B-roll from your own clips, offline voiceover."""
from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from app import brollclips, hook, voiceover as VO
from app.schema import Marker, Project
from app.storage import new_id

PIPER_DIR = os.environ.get("RJCLIP_TEST_PIPER_DIR")   # folder with piper_linux_x86_64.tar.gz and a voice (see CI)


def _project(tmp_path: Path, media: dict[str, dict], v1: list[tuple], extra_video: list[tuple] = ()) -> tuple[Project, Path]:
    """media: id -> {duration, rms (list), motion (list), words}; v1: (media, start, in, out)."""
    pdir = tmp_path / "p"
    (pdir / "analysis").mkdir(parents=True)
    ms = []
    for mid, a in media.items():
        (pdir / "analysis" / f"{mid}.json").write_text(json.dumps({"version": 1, "media_id": mid, "duration": a["duration"], "hop": 0.05,
            "rms_db": a.get("rms", []), "motion": a.get("motion", []), "cuts": [], "words": a.get("words")}))
        ms.append({"id": mid, "original_name": f"{mid[:4]}.mp4", "stored_name": f"{mid}.mp4", "kind": "video", "duration": a["duration"],
                   "size_bytes": 1, "container": "mp4", "has_video": True, "has_audio": True, "imported_at": "2026-01-01T00:00:00Z",
                   "width": 320, "height": 180, "fps": 30.0})
    clip = lambda m, s, a, b, link=None: {"id": new_id(), "media_id": m, "start": s, "source_in": a, "source_out": b, "link_id": link}  # noqa: E731
    vids, auds = [], []
    for m, s, a, b in v1:
        link = new_id()
        vids.append(clip(m, s, a, b, link))
        auds.append(clip(m, s, a, b, link))
    tracks = [{"id": new_id(), "kind": "video", "name": "V1", "clips": vids},
              {"id": new_id(), "kind": "video", "name": "V2", "clips": [clip(m, s, a, b) for m, s, a, b in extra_video]},
              {"id": new_id(), "kind": "audio", "name": "A1", "clips": auds}]
    p = Project.model_validate({"id": new_id(), "name": "t", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
                                "media": ms, "timeline": {"tracks": tracks}})
    return p, pdir


def W(text, s, e):
    return {"text": " " + text, "start": s, "end": e, "p": 0.9}


# ---------------------------------------------------------------- hook checker
def _talk(start_at: float, n: int = 120, gap: float = 0.4):
    words = ["you", "won't", "believe", "this", "boss", "fight", "today."]
    return [W(words[i % len(words)], start_at + i * gap, start_at + i * gap + 0.3) for i in range(n)]


def test_weak_start_is_found_and_fixable(tmp_path):
    A = new_id()
    hop_n = int(60 / 0.05)
    rms = [-60.0] * int(3.5 / 0.05) + [-22.0] * (hop_n - int(3.5 / 0.05))
    for k in range(int(30 / 0.05), int(33 / 0.05)):          # a big moment at 30-33 s
        rms[k] = -6.0
    p, pdir = _project(tmp_path, {A: {"duration": 60, "rms": rms, "motion": [0.2] * hop_n, "words": _talk(3.6, 120)}}, [(A, 0, 0, 60)])
    r = hook.check(p, pdir)
    assert r["score"] < 60, r
    assert r["metrics"]["talk_starts_after"] == pytest.approx(3.6, abs=0.01)
    assert r["tips"][0]["id"] in ("start_delay", "energy")
    trim = next(a for a in r["actions"] if a["id"] == "trim_start")
    assert trim["cut"] == [0.0, pytest.approx(3.4, abs=0.01)]
    tz = next(a for a in r["actions"] if a["id"] == "teaser")["range"]
    assert 27 <= tz[0] <= 31 and tz[1] - tz[0] >= 3.9, tz


def test_strong_start_scores_well(tmp_path):
    A = new_id()
    n = int(60 / 0.05)
    rms = [-14.0] * int(10 / 0.05) + [-22.0] * (n - int(10 / 0.05))
    motion = [0.6] * int(10 / 0.05) + [0.2] * (n - int(10 / 0.05))
    p, pdir = _project(tmp_path, {A: {"duration": 60, "rms": rms, "motion": motion, "words": _talk(0.2, 140)}}, [(A, 0, 0, 60)])
    r = hook.check(p, pdir)
    assert r["score"] >= 75 and r["verdict"] == "Strong start.", r
    assert not any(a["id"] == "trim_start" for a in r["actions"])


def test_hook_without_analysis_or_too_short(tmp_path):
    A = new_id()
    p, pdir = _project(tmp_path, {A: {"duration": 2}}, [(A, 0, 0, 2)])
    assert hook.check(p, pdir)["score"] is None
    p, pdir = _project(tmp_path / "b", {A: {"duration": 30}}, [(A, 0, 0, 30)])
    assert "Analyse" in hook.check(p, pdir)["verdict"]


# ---------------------------------------------------------------- B-roll from your own clips
def test_broll_from_other_recordings(tmp_path):
    A, B, C = new_id(), new_id(), new_id()
    main = [W("today", 1, 1.4), W("the", 1.5, 1.6), W("dragon", 1.7, 2.1), W("attacked", 2.2, 2.6), W("us", 2.7, 2.8),
            W("so", 12, 12.2), W("we", 12.3, 12.4), W("built", 12.5, 12.8), W("castles", 12.9, 13.4)]
    other = [W("look", 5, 5.3), W("at", 5.4, 5.5), W("this", 5.6, 5.8), W("dragon", 20.0, 20.4), W("flying", 20.5, 20.9),
             W("castle", 40, 40.4)]
    p, pdir = _project(tmp_path, {A: {"duration": 30, "words": main}, B: {"duration": 60, "words": other},
                                  C: {"duration": 10, "words": None}}, [(A, 0, 0, 30)])
    r = brollclips.suggest(p, pdir)
    s = r["suggestions"]
    assert [(x["word"], x["media_id"]) for x in s] == [("dragon", B), ("castles", B)], s
    assert s[0]["t"] == 1.7 and s[0]["source_in"] == pytest.approx(19.6) and s[0]["duration"] == 3.0
    assert s[1]["source_in"] == pytest.approx(39.6)


def test_broll_notes(tmp_path):
    A, B = new_id(), new_id()
    p, pdir = _project(tmp_path, {A: {"duration": 30, "words": None}}, [(A, 0, 0, 30)])
    assert "Transcribe the main" in brollclips.suggest(p, pdir)["note"]
    p, pdir = _project(tmp_path / "2", {A: {"duration": 30, "words": [W("dragon", 1, 2)]}, B: {"duration": 9}}, [(A, 0, 0, 30)])
    assert "Transcribe your other" in brollclips.suggest(p, pdir)["note"]
    # an overlay already there: no suggestion on top of it
    p, pdir = _project(tmp_path / "3", {A: {"duration": 30, "words": [W("dragon", 1, 2)]}, B: {"duration": 9, "words": [W("dragon", 3, 4)]}},
                       [(A, 0, 0, 30)], extra_video=[(B, 0, 0, 5)])
    assert brollclips.suggest(p, pdir)["suggestions"] == []


# ---------------------------------------------------------------- voiceover
def test_voice_status_and_refusals(server, tmp_path):
    c = server
    st, s, _ = c.req("GET", "/api/voice")
    assert st == 200 and s["ready"] is False and s["credit"].startswith("Voice: Piper") and "Voice 1" in s["speakers"]
    _, p, _ = c.req("POST", "/api/projects", {"name": "vo"})
    assert c.req("POST", f"/api/projects/{p['id']}/voiceover", {"text": "hello"})[0] == 409
    assert c.req("POST", f"/api/projects/{p['id']}/voiceover", {"text": "x" * 2001})[0] == 422
    assert c.req("POST", f"/api/projects/{p['id']}/voiceover", {"text": "hi", "speed": 5})[0] == 422


def test_archives_cannot_escape(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as t:
        data = b"x"
        ti = tarfile.TarInfo("../../evil.txt")
        ti.size = 1
        t.addfile(ti, io.BytesIO(data))
    with pytest.raises(VO.VoiceError):
        VO._safe_extract(bad, tmp_path / "out")
    badz = tmp_path / "bad.zip"
    with zipfile.ZipFile(badz, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(VO.VoiceError):
        VO._safe_extract(badz, tmp_path / "out2")
    assert not (tmp_path / "evil.txt").exists()
    with pytest.raises(VO.VoiceError):
        VO._download("http://example.com/x", tmp_path / "x", None, lambda f: None)


@pytest.mark.skipif(not PIPER_DIR, reason="set RJCLIP_TEST_PIPER_DIR to a folder with Piper + a voice to run the real voice test")
def test_real_voiceover(server, tmp_path, monkeypatch):
    c = server
    d = Path(PIPER_DIR)
    voice = next(d.glob("**/*.onnx"))
    monkeypatch.setenv("RJCLIP_PIPER_URL", (d / "piper_linux_x86_64.tar.gz").as_uri())
    monkeypatch.setenv("RJCLIP_VOICE_URL", voice.parent.as_uri() + "/")
    monkeypatch.setenv("RJCLIP_VOICE_NAME", voice.name[: -len(".onnx")])
    st, r, _ = c.req("POST", "/api/voice/setup")
    assert st == 202, r
    j = c.wait_job(r["job_id"], timeout=300)
    assert j["status"] == "succeeded", j.get("error")
    assert c.req("GET", "/api/voice")[1]["ready"] is True
    _, p, _ = c.req("POST", "/api/projects", {"name": "vo"})
    st, r, _ = c.req("POST", f"/api/projects/{p['id']}/voiceover", {"text": "Welcome back. Today we build a castle.", "speaker": "Voice 2", "speed": 1.2})
    assert st == 202
    j = c.wait_job(r["job_id"], timeout=300)
    assert j["status"] == "succeeded", j.get("error")
    m = j["result"]["media"]
    assert m["kind"] == "audio" and 1.0 < m["duration"] < 6 and m["original_name"].startswith("Voiceover - Welcome back.")
    _, p2, _ = c.req("GET", f"/api/projects/{p['id']}")
    assert any(x["id"] == m["id"] for x in p2["media"])
    # it really is speech-like: loud enough and not silence
    wav = c.settings.projects_dir / p["id"] / "media" / "original" / m["stored_name"]
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(wav), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    mean = float(vol.split("mean_volume:")[1].split("dB")[0])
    assert mean > -40, mean


# ---------------------------------------------------------------- music matched to the video
def test_sections_and_plan(tmp_path):
    A = new_id()
    n = int(120 / 0.05)
    # 0-60 s calm talking, 60-120 s loud action
    rms = [-30.0] * (n // 2) + [-10.0] * (n // 2)
    motion = [0.05] * (n // 2) + [0.9] * (n // 2)
    p, pdir = _project(tmp_path, {A: {"duration": 120, "rms": rms, "motion": motion}}, [(A, 0, 0, 120)])
    secs = hook.sections(p, pdir)
    assert [s["label"] for s in secs] == ["calm", "hype"] and secs[0]["end"] == pytest.approx(60, abs=0.5), secs
    songs = [{"media_id": "chill", "energy": 0.2}, {"media_id": "mid", "energy": 0.5}, {"media_id": "banger", "energy": 0.9}]
    plan = hook.music_plan(secs, songs)
    assert [(x["media_id"], x["start"], x["end"]) for x in plan] == [("chill", 0, secs[0]["end"]), ("banger", secs[1]["start"], 120)]
    assert hook.music_plan(secs, [songs[1]]) == [{"start": 0, "end": 120, "media_id": "mid"}]   # one song: the whole video
    # markers decide the parts when there are some
    p2 = p.model_copy(update={"timeline": p.timeline.model_copy(update={"markers": [Marker(id=new_id(), t=40), Marker(id=new_id(), t=90)]})})
    assert [(s["start"], s["end"]) for s in hook.sections(p2, pdir)] == [(0, 40), (40, 90), (90, 120)]


def test_song_energy():
    import numpy as np
    from app import beats as BT
    sr = BT.SR
    t = np.arange(20 * sr) / sr
    calm = 0.1 * np.sin(2 * np.pi * 220 * t)
    kick = np.sin(2 * np.pi * 60 * t) * np.exp(-25 * np.mod(t, 0.4)) * 0.9 + 0.3 * np.random.default_rng(1).normal(size=t.size) * np.exp(-60 * np.mod(t + 0.2, 0.4))
    a, b = BT.detect(calm), BT.detect(kick)
    assert a["label"] == "calm" and b["energy"] > a["energy"] + 0.2, (a["energy"], b["energy"])


def test_broll_suggests_each_thing_once(tmp_path):
    A, B = new_id(), new_id()
    main = [W("castle", 1 + 8 * i, 1.5 + 8 * i) for i in range(5)] + [W("dragons", 50, 50.5)]
    other = [W("castle", 5, 5.4), W("dragon", 9, 9.4)]
    p, pdir = _project(tmp_path, {A: {"duration": 60, "words": main}, B: {"duration": 20, "words": other}}, [(A, 0, 0, 60)])
    s = brollclips.suggest(p, pdir)["suggestions"]
    assert [(x["word"], x["t"]) for x in s] == [("castle", 1), ("dragons", 50)], s
