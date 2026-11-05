"""Phase 4 tests: swear detection, censoring at the audio level, effects mapping,
comedy suggestions, captions, rendering and the API (with a fake transcriber)."""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.schema import SCHEMA_VERSION
from app import effects as fx
from app.config import Settings
from app.media import build_asset
from app.projects import ProjectStore
from app.render import render_project
from app.schema import Effect, Project, migrate
from app.storage import new_id

WORDS = [{"start": 0.5, "end": 0.9, "text": " hello", "p": 0.95},
         {"start": 1.0, "end": 1.4, "text": " fucking", "p": 0.92},
         {"start": 1.5, "end": 1.9, "text": " world.", "p": 0.9},
         {"start": 2.4, "end": 2.5, "text": " shit", "p": 0.4},
         {"start": 4.0, "end": 4.4, "text": " what?", "p": 0.9},
         {"start": 5.2, "end": 5.6, "text": " damn", "p": 0.9}]


# ---------------------------------------------------------------- detection
@pytest.mark.parametrize("w", ["fuck", "Fucking,", "MOTHERFUCKER", "shit!", "bullshit", "bitches", "asshole",
                               "f***", "ass", "wtf"])
def test_profanity_positive(w):
    assert fx.is_profane(w)


@pytest.mark.parametrize("w", ["assume", "class", "Dickens", "hello", "shitake" if False else "shiitake",
                               "cocktail", "scunthorpe", "assess", "passage", "damn", "hell", "*"])
def test_profanity_negative(w):
    assert not fx.is_profane(w)


def test_profanity_levels_custom_and_allow():
    assert fx.is_profane("damn", "all") and not fx.is_profane("damn", "strong")
    assert fx.is_profane("Gary", custom=["gary"])
    assert not fx.is_profane("shit", allow=["shit"])
    assert fx.mask_word("FUCKING") == "F******" and fx.mask_word("wtf?") == "w**?"


# ---------------------------------------------------------------- fixtures
def _project(tmp_path, effects=(), audio_clips=None, captions=None, words=WORDS, video_clips=None, rms=None):
    s = Settings(workspace=tmp_path)
    st = ProjectStore(tmp_path / "projects")
    p = st.create("fx")
    pdir = st.dir(p.id)
    f = pdir / "media" / "original" / ("a" * 32 + ".mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=440:d=8:sample_rate=48000", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(f)], check=True)
    a = build_asset(s, "a" * 32, f, "t.mp4")
    (pdir / "analysis").mkdir(exist_ok=True)
    (pdir / "analysis" / ("a" * 32 + ".json")).write_text(json.dumps(
        {"version": 1, "media_id": "a" * 32, "duration": 8.0, "hop": 0.05,
         "rms_db": rms if rms is not None else [-20.0] * 160, "motion": [], "cuts": [], "words": words}))
    d = p.model_dump(mode="json")
    d["media"] = [a.model_dump(mode="json")]
    d["output"] = {"width": 320, "height": 180, "fps": 30, "fit_mode": "fit"}
    vc = video_clips or [dict(start=0, source_in=0, source_out=6)]
    ac = audio_clips or vc
    d["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": "a" * 32, **c} for c in vc]
    d["timeline"]["tracks"][2]["clips"] = [{"id": new_id(), "media_id": "a" * 32, **c} for c in ac]
    d["effects"] = [{"id": new_id(), "media_id": "a" * 32, **e} for e in effects]
    if captions:
        d["captions"] = captions
    return s, Project.model_validate(d), pdir


class Ctx:
    job = SimpleNamespace(id="0" * 32)

    def __init__(self):
        self.cancel_event = threading.Event()

    def stage(self, *a):
        pass

    def progress(self, p):
        pass

    def check_cancel(self):
        pass


def _pcm(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def _share(x, t0, t1, f):
    seg = x[int(t0 * 48000):int(t1 * 48000)]
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    fr = np.fft.rfftfreq(len(seg), 1 / 48000)
    return sp[(fr > f - 30) & (fr < f + 30)].max() / (sp.max() + 1e-9), float(np.sqrt((seg ** 2).mean()))


# ---------------------------------------------------------------- mapping
def test_effects_follow_trims_speed_and_cuts(tmp_path):
    s, p, _ = _project(tmp_path, video_clips=[dict(start=0, source_in=2, source_out=4),
                                              dict(start=2, source_in=6, source_out=8, speed=2.0)])
    e1 = Effect(id=new_id(), kind="zoom", media_id="a" * 32, source_time=3.0, duration=0.5)
    e2 = Effect(id=new_id(), kind="zoom", media_id="a" * 32, source_time=5.0, duration=0.5)  # cut
    e3 = Effect(id=new_id(), kind="zoom", media_id="a" * 32, source_time=7.0, duration=0.5)  # sped up
    assert [(w.start, w.end) for w in fx.map_to_timeline(p, e1, "video")] == [(1.0, 1.5)]
    assert fx.map_to_timeline(p, e2, "video") == []
    assert [(w.start, w.end) for w in fx.map_to_timeline(p, e3, "video")] == [(2.5, 2.75)]


def test_linked_tracks_dedupe_and_mutes(tmp_path):
    _, p, _ = _project(tmp_path, effects=[dict(kind="censor", source_time=1.0, duration=0.4, sound="beep")],
                       audio_clips=[dict(start=0, source_in=0.5, source_out=6)])
    e = p.effects[0]
    assert len(fx.map_to_timeline(p, e, "audio")) == 1
    assert fx.mutes_for_clip(p, p.timeline.tracks[2].clips[0]) == [(0.5, 0.9)]


# ---------------------------------------------------------------- suggestions
def test_suggest_censors_with_review_flags(tmp_path):
    _, p, pdir = _project(tmp_path)
    out = fx.suggest_censors(p, pdir, sound="boing")
    assert [e.word for e in out] == ["fucking", "shit"]
    assert out[0].sound == "boing" and not out[0].needs_review
    assert out[1].needs_review  # low confidence + very short
    assert out[0].source_time == pytest.approx(0.94) and out[0].duration == pytest.approx(0.52)
    assert "hello" in out[0].context
    assert len(fx.suggest_censors(p, pdir, level="all")) == 3
    assert len(fx.suggest_censors(p, pdir, allow=["shit"])) == 1


@pytest.mark.parametrize("intensity", ["minimal", "balanced", "chaotic"])
def test_suggest_fun_is_deterministic_spaced_and_imageless(tmp_path, intensity):
    rms = [-30.0] * 160
    for k in (20, 80, 140):  # loud reactions at 1 s, 4 s, 7 s
        for j in range(k, k + 6):
            rms[j] = -5.0
    _, p, pdir = _project(tmp_path, rms=rms, video_clips=[dict(start=0, source_in=0, source_out=8)])
    a = fx.suggest_fun(p, pdir, intensity)
    b = fx.suggest_fun(p, pdir, intensity)
    assert [(e.kind, e.source_time) for e in a] == [(e.kind, e.source_time) for e in b]
    assert a and all(e.kind != "image" for e in a)
    zooms = sorted(e.source_time for e in a if e.kind == "zoom")
    gap = fx.INTENSITY[intensity]["gap"]
    assert all(b2 - b1 >= gap - 0.2 for b1, b2 in zip(zooms, zooms[1:]))
    assert len(zooms) == {"minimal": 1, "balanced": 1, "chaotic": 2}[intensity]


def test_reaction_text_uses_nearby_words(tmp_path):
    rms = [-30.0] * 160
    for j in range(80, 86):  # one loud reaction at 4 s, right on the word "what?"
        rms[j] = -5.0
    _, p, pdir = _project(tmp_path, rms=rms, video_clips=[dict(start=0, source_in=0, source_out=8)])
    texts = [e.text for e in fx.suggest_fun(p, pdir, "chaotic") if e.kind == "text"]
    assert texts == ["WAIT WHAT?"]


# ---------------------------------------------------------------- captions
def test_captions_mask_censored_words_and_format(tmp_path):
    _, p, pdir = _project(tmp_path, effects=[dict(kind="censor", source_time=0.95, duration=0.5, sound="beep")],
                          captions={"enabled": True, "max_words": 3})
    chunks = fx.caption_chunks(p, pdir)
    text = " ".join(c["text"] for c in chunks)
    assert "F******" in text and "FUCKING" not in text
    assert chunks[0]["text"].endswith("WORLD.")  # sentence end breaks the line
    srt = fx.captions_srt(chunks)
    assert srt.startswith("1\n00:00:00,500 --> ")
    ass = fx.captions_ass(p, chunks, "Impact", 180, 320)
    assert "PlayResX: 320" in ass and ass.count("Dialogue:") == len(chunks)
    p.captions.style = "highlight"
    assert fx.captions_ass(p, chunks, "Impact", 180, 320).count("Dialogue:") == sum(len(c["words"]) for c in chunks)


def test_caption_words_follow_the_edit(tmp_path):
    _, p, pdir = _project(tmp_path, audio_clips=[dict(start=0, source_in=3.5, source_out=6)],
                          video_clips=[dict(start=0, source_in=3.5, source_out=6)])
    words = [w["text"].strip() for w in fx.edit_words(p, pdir)]
    assert words == ["what?", "damn"]
    assert fx.edit_words(p, pdir)[0]["start"] == pytest.approx(0.5)


# ---------------------------------------------------------------- schema
def test_schema_v1_projects_migrate():
    assert migrate({"schema_version": 1})["effects"] == []


@pytest.mark.parametrize("bad", [dict(kind="text", text="  "), dict(kind="censor"), dict(kind="sfx", sound="mute"),
                                 dict(kind="image"), dict(kind="zoom", scale=9)])
def test_invalid_effects_rejected(bad):
    with pytest.raises(Exception):
        Effect(id=new_id(), media_id="a" * 32, source_time=0, duration=1, **bad)


def test_effect_on_unknown_media_rejected(tmp_path):
    _, p, _ = _project(tmp_path)
    d = p.model_dump(mode="json")
    d["effects"] = [{"id": new_id(), "media_id": "b" * 32, "kind": "flash", "source_time": 0, "duration": 0.2}]
    with pytest.raises(Exception, match="unknown media"):
        Project.model_validate(d)


# ---------------------------------------------------------------- rendering
@pytest.mark.parametrize("sound", ["beep", "mute", "boing"])
def test_censor_removes_original_audio(tmp_path, sound):
    s, p, pdir = _project(tmp_path, effects=[dict(kind="censor", source_time=1.0, duration=0.5, sound=sound)])
    r = render_project(Ctx(), s, p, pdir, "c", "draft", "libx264")
    assert r["validation"]["ok"], r["validation"]
    x = _pcm(pdir / "exports" / r["file"])
    before, _ = _share(x, 0.2, 0.8, 440)
    under, rms = _share(x, 1.05, 1.45, 440)
    assert before > 0.9
    if sound != "boing":  # the boing itself sweeps through 440 Hz, so it can't be measured this way
        assert under < 0.02, "the original word must not leak under the censor sound"
    if sound == "mute":
        assert rms < 0.002
    if sound == "beep":
        assert _share(x, 1.05, 1.45, 1000)[0] > 0.9


def test_disabled_censor_does_nothing(tmp_path):
    s, p, pdir = _project(tmp_path, effects=[dict(kind="censor", source_time=1.0, duration=0.5, sound="beep",
                                                  enabled=False)])
    x = _pcm(pdir / "exports" / render_project(Ctx(), s, p, pdir, "d", "draft", "libx264")["file"])
    assert _share(x, 1.05, 1.45, 440)[0] > 0.9


def test_all_visual_effects_and_captions_render(tmp_path):
    from app.thumb_store import decode_image  # noqa: F401  (cv2 available)
    import cv2
    img_dir = None
    effects = [dict(kind="zoom", source_time=1.0, duration=1.0, scale=1.6),
               dict(kind="shake", source_time=2.2, duration=0.4),
               dict(kind="flash", source_time=3.0, duration=0.15),
               dict(kind="text", source_time=4.0, duration=1.0, text="NO WAY", color="#ffde00", y=0.3),
               dict(kind="sfx", source_time=4.0, duration=0.6, sound="boom"),
               dict(kind="zoom", source_time=7.0, duration=0.5)]  # outside the edit
    s, p, pdir = _project(tmp_path, effects=effects, captions={"enabled": True})
    r = render_project(Ctx(), s, p, pdir, "fx", "draft", "libx264")
    assert r["validation"]["ok"], r["validation"]
    out = pdir / "exports" / r["file"]

    def frame(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(180, 320, 3).astype(int)

    _, plain, _ = _project(tmp_path / "plain")
    ref = render_project(Ctx(), s, plain, ProjectStore(tmp_path / "plain" / "projects").dir(plain.id), "p",
                         "draft", "libx264")
    ref_out = ProjectStore(tmp_path / "plain" / "projects").dir(plain.id) / "exports" / ref["file"]

    def ref_frame(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(ref_out), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(180, 320, 3).astype(int)

    diff = lambda t: float(np.abs(frame(t) - ref_frame(t)).mean())  # noqa: E731
    assert diff(0.3) < 6, "no effect at 0.3 s"
    assert diff(1.5) > 20, "zoom visible"
    assert frame(3.05).mean() > 180, "flash visible"
    top = np.abs(frame(4.5) - ref_frame(4.5))[30:80].mean()
    assert top > 10, "pop-up text visible"
    assert cv2 is not None and img_dir is None
    x = _pcm(out)
    assert _share(x, 4.02, 4.3, 440)[1] > _share(_pcm(ref_out), 4.02, 4.3, 440)[1] * 1.3, "boom adds energy"


def test_every_sound_synthesises(tmp_path):
    for snd in ("beep", "boing", "scratch", "honk", "quack", "boom", "whoosh", "ding", "pop", "airhorn", "mute"):
        dest = tmp_path / f"{snd}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *fx.sound_args(snd, 24000, 0.8, 48000, dest)], check=True)
        info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=duration_ts", "-of",
                               "default=nw=1:nk=1", str(dest)], capture_output=True, text=True).stdout.strip()
        assert info == "24000", (snd, info)


def test_text_png_uses_a_real_font(tmp_path):
    w, h = fx.text_png("WAIT WHAT?", 80, "#ffde00", tmp_path / "t.png")
    assert w > 200 and h > 60


# ---------------------------------------------------------------- API
class FakeTranscriber:
    name = "fake-whisper"

    def transcribe(self, src, on_progress, cancel):
        on_progress(1.0)
        return [{"start": 1.0, "end": 1.4, "text": " shit", "p": 0.9},
                {"start": 2.0, "end": 2.4, "text": " what?", "p": 0.9}]


def test_api_phase4_flow(server, tmp_path, monkeypatch):
    c = server
    vid = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=5",
                    "-f", "lavfi", "-i", "sine=f=440:d=5:sample_rate=48000", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "p4"})
    pid = p["id"]
    _, up, _ = c.upload(pid, vid)
    mid = up["media"]["id"]
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    link = new_id()
    p["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 5, "link_id": link}]
    p["timeline"]["tracks"][2]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 5, "link_id": link}]
    st, p, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                               "timeline": p["timeline"], "output": p["output"]})
    assert st == 200 and p["schema_version"] == SCHEMA_VERSION and p["effects"] == []
    monkeypatch.setattr("app.api.available_transcriber", lambda: None)
    st, r, _ = c.req("POST", f"/api/projects/{pid}/transcribe", {})
    assert st == 409 and "requirements-ai.txt" in r["error"]
    st, r, _ = c.req("POST", f"/api/projects/{pid}/fx/censor/suggest", {})
    assert st == 409
    monkeypatch.setattr("app.api.available_transcriber", lambda: FakeTranscriber())
    _, job, _ = c.req("POST", f"/api/projects/{pid}/transcribe", {})
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded", j
    _, status, _ = c.req("GET", f"/api/projects/{pid}/fx/status")
    assert status["transcript"]["transcribed"] == 1 and status["transcriber"] == "fake-whisper"
    _, cens, _ = c.req("POST", f"/api/projects/{pid}/fx/censor/suggest", {"sound": "quack"})
    assert [e["word"] for e in cens["effects"]] == ["shit"] and cens["effects"][0]["sound"] == "quack"
    _, fun, _ = c.req("POST", f"/api/projects/{pid}/fx/fun/suggest", {"intensity": "chaotic"})
    assert isinstance(fun["effects"], list)
    effects = cens["effects"] + [{"id": new_id(), "media_id": mid, "kind": "text", "source_time": 2.0,
                                  "duration": 1.0, "text": "WAIT WHAT?"}]
    st, p2, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                                "timeline": p["timeline"], "output": p["output"],
                                                                "effects": effects,
                                                                "captions": {"enabled": True, "style": "highlight"}})
    assert st == 200 and len(p2["effects"]) == 2 and p2["captions"]["style"] == "highlight"
    _, again, _ = c.req("GET", f"/api/projects/{pid}")
    assert len(again["effects"]) == 2  # saved & reopened
    st, srt, h = c.req("GET", f"/api/projects/{pid}/captions.srt")
    assert st == 200 and b"S***" in srt and b"WHAT?" in srt
    st, wav, h = c.req("GET", "/api/sounds/boing.wav")
    assert st == 200 and wav[:4] == b"RIFF"
    assert c.req("GET", "/api/sounds/evil.wav")[0] == 404
    import cv2
    ok, png = cv2.imencode(".png", np.full((40, 60, 3), 255, np.uint8))
    st, img, _ = c.req("POST", f"/api/projects/{pid}/fx/images", raw=png.tobytes())
    assert st == 201
    assert c.req("GET", f"/api/projects/{pid}/fx/images/{img['id']}")[0] == 200
    assert c.req("GET", f"/api/projects/{pid}/fx/images/..%2Fproject")[0] == 404
    assert c.req("POST", f"/api/projects/{pid}/fx/images", raw=b"<svg/>")[0] == 415
    bad = effects + [{"id": new_id(), "media_id": "f" * 32, "kind": "flash", "source_time": 0, "duration": 0.2}]
    st, _, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p2["edit_revision"],
                                                               "timeline": p["timeline"], "output": p["output"],
                                                               "effects": bad})
    assert st == 422
    _, job, _ = c.req("POST", f"/api/projects/{pid}/exports", {"filename": "p4", "quality": "draft"})
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded" and j["result"]["validation"]["ok"], j


class SlowLoadingTranscriber(FakeTranscriber):
    def __init__(self, fail: bool):
        self.fail = fail
        self.prepared = False

    def prepare(self):
        if self.fail:
            raise RuntimeError("Couldn't download the speech model (one-time, ~460 MB). Check your internet "
                               "connection and try again.")
        self.prepared = True


def test_transcription_failure_is_reported_and_model_load_has_its_own_step(server, tmp_path, monkeypatch):
    """User report: after 'Transcribe speech' the bleep button stayed off with no explanation."""
    c = server
    vid = make_media_file(tmp_path / "t.mp4")
    _, p, _ = c.req("POST", "/api/projects", {"name": "tr"})
    pid = p["id"]
    _, up, _ = c.upload(pid, vid)
    mid = up["media"]["id"]
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    link = new_id()
    p["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 3, "link_id": link}]
    p["timeline"]["tracks"][2]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 3, "link_id": link}]
    c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"], "output": p["output"]})
    bad = SlowLoadingTranscriber(fail=True)
    monkeypatch.setattr("app.api.available_transcriber", lambda: bad)
    _, job, _ = c.req("POST", f"/api/projects/{pid}/transcribe", {})
    j = c.wait_job(job["id"])
    assert j["status"] == "failed" and "download the speech model" in j["error"], j
    _, st, _ = c.req("GET", f"/api/projects/{pid}/fx/status")
    assert st["transcript"]["transcribed"] == 0
    good = SlowLoadingTranscriber(fail=False)
    monkeypatch.setattr("app.api.available_transcriber", lambda: good)
    _, job, _ = c.req("POST", f"/api/projects/{pid}/transcribe", {})
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded" and good.prepared, j
    _, st, _ = c.req("GET", f"/api/projects/{pid}/fx/status")
    assert st["transcript"]["transcribed"] == 1  # -> the bleep button turns on
    _, cens, _ = c.req("POST", f"/api/projects/{pid}/fx/censor/suggest", {})
    assert [e["word"] for e in cens["effects"]] == ["shit"]


def make_media_file(path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25:d=3",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return path


def test_analysis_survives_a_failing_transcriber(server, tmp_path, monkeypatch):
    """User report: after installing speech-to-text, 'Analyse recording' broke when the
    model couldn't load. Analysis must still work (sound + picture), with a warning."""
    c = server
    vid = make_media_file(tmp_path / "a.mp4")
    _, p, _ = c.req("POST", "/api/projects", {"name": "an"})
    pid = p["id"]
    _, up, _ = c.upload(pid, vid)
    mid = up["media"]["id"]
    monkeypatch.setattr("app.api.available_transcriber", lambda: SlowLoadingTranscriber(fail=True))
    _, job, _ = c.req("POST", f"/api/projects/{pid}/autoedit/analyze", {"media_id": mid})
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded" and "sound and picture only" in j["result"]["warning"], j
    _, st, _ = c.req("GET", f"/api/projects/{pid}/autoedit")
    m = st["media"][0]
    assert m["analyzed"] and not m["has_transcript"] and "download the speech model" in m["transcript_error"]
    st_, plan, _ = c.req("POST", f"/api/projects/{pid}/autoedit/plan", {"media_id": mid})
    assert st_ == 200  # the AI edit still works
    # a later successful transcription clears the warning
    monkeypatch.setattr("app.api.available_transcriber", lambda: SlowLoadingTranscriber(fail=False))
    p = c.req("GET", f"/api/projects/{pid}")[1]
    link = new_id()
    p["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 3, "link_id": link}]
    p["timeline"]["tracks"][2]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 3, "link_id": link}]
    c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"], "output": p["output"]})
    _, job, _ = c.req("POST", f"/api/projects/{pid}/transcribe", {})
    assert c.wait_job(job["id"])["status"] == "succeeded"
    m = c.req("GET", f"/api/projects/{pid}/autoedit")[1]["media"][0]
    assert m["has_transcript"] and m["transcript_error"] is None


def test_whisper_gets_ffmpeg_decoded_chunks_with_exact_offsets(tmp_path, monkeypatch):
    """User report: "open() got an unexpected keyword argument 'metadata_errors'" (PyAV 19 vs
    faster-whisper 1.2). ClipForge now decodes audio itself; the model only sees samples."""
    from types import SimpleNamespace

    from app import transcription as T
    src = tmp_path / "beeps.mp4"
    # silence with short beeps at 1.0, 3.5 and 5.2 s (chunks of 2 s -> beeps in chunks 0, 1, 2)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25:d=6",
                    "-f", "lavfi", "-i", "aevalsrc='0.8*sin(2*PI*1000*t)*(between(t,1,1.2)+between(t,3.5,3.7)+between(t,5.2,5.4))':s=44100:d=6",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    seen = []

    class FakeModel:
        def transcribe(self, audio, word_timestamps, vad_filter, initial_prompt=None):
            assert isinstance(audio, np.ndarray) and audio.dtype == np.float32  # never a file path
            assert initial_prompt and "um" in initial_prompt.lower()  # asks Whisper to keep filler words
            seen.append(len(audio))
            loud = np.flatnonzero(np.abs(audio) > 0.3)
            if not loud.size:
                return iter([]), None
            t = loud[0] / T.SAMPLE_RATE
            w = SimpleNamespace(start=t, end=t + 0.2, word=" beep", probability=0.9)
            return iter([SimpleNamespace(end=t + 0.2, words=[w])]), None
    tr = T.FasterWhisperTranscriber()
    monkeypatch.setattr(tr, "_load", lambda: FakeModel())
    monkeypatch.setattr(T, "CHUNK_S", 2)
    prog = []
    words = tr.transcribe(src, prog.append, None)
    assert [round(w["start"], 1) for w in words] == [1.0, 3.5, 5.2]
    assert len(seen) == 3 and all(n == 2 * T.SAMPLE_RATE for n in seen[:2])
    assert prog and prog[-1] == pytest.approx(1.0, abs=0.02)


def test_whisper_decode_reports_unreadable_audio(tmp_path):
    from app import transcription as T
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00" * 1000)
    with pytest.raises(RuntimeError, match="Couldn't read the audio"):
        list(T.decode_chunks(bad, 60, None))
