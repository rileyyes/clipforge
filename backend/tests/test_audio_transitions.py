"""Phase 4 (part 2): transitions, fades, music ducking, noise reduction and loudness.
Every assertion measures the exported file (pixels / audio), not just settings."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.schema import SCHEMA_VERSION
from app.config import Settings
from app.media import build_asset
from app.projects import ProjectStore
from app.render import measure_lufs, plan_render, render_project
from app.schema import Project, migrate
from app.storage import new_id

FPS = 25


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


def _media(path: Path, color: str, audio: str, d: float = 6):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r={FPS}:d={d}",
                    "-f", "lavfi", "-i", f"{audio}:d={d}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", str(path)], check=True)
    return path


def _project(tmp_path, specs, audio=None, effects=()):
    """specs: list of (media_key, track_index, clip dict). media keys: red/blue/voice/music/noisy"""
    s = Settings(workspace=tmp_path)
    st = ProjectStore(tmp_path / "projects")
    p = st.create("t")
    pdir = st.dir(p.id)
    orig = pdir / "media" / "original"
    defs = {"red": ("red", "sine=f=440:sample_rate=48000"),
            "blue": ("blue", "sine=f=660:sample_rate=48000"),
            # dialogue: tone only during 0-2 s and 4-6 s
            "voice": ("gray", "aevalsrc='0.3*sin(2*PI*440*t)*(lt(t,2)+gte(t,4))':s=48000"),
            "music": ("black", "aevalsrc='0.2*sin(2*PI*220*t)':s=48000"),
            # soft speech with sharp clicks: loudnorm alone undershoots by ~5 dB
            "peaky": ("gray", "aevalsrc='0.02*sin(2*PI*300*t)+0.95*lt(mod(t,0.5),0.002)*sin(2*PI*3000*t)':s=48000"),
            "noisy": ("gray", "aevalsrc='0.3*sin(2*PI*440*t)*lt(t,3)+0.02*(random(0)*2-1)':s=48000")}
    media = {}
    for key in {k for k, _, _ in specs}:
        mid = new_id()
        color, a = defs[key]
        f = _media(orig / f"{mid}.mp4", color, a)
        media[key] = build_asset(s, mid, f, f"{key}.mp4")
    d = p.model_dump(mode="json")
    d["media"] = [m.model_dump(mode="json") for m in media.values()]
    d["output"] = {"width": 160, "height": 90, "fps": FPS, "fit_mode": "fit"}
    for key, ti, c in specs:
        d["timeline"]["tracks"][ti]["clips"].append({"id": new_id(), "media_id": media[key].id, **c})
    if audio is not None:
        d["audio"] = audio
    d["effects"] = list(effects)
    return s, Project.model_validate(d), pdir, media


def _render(s, p, pdir, name="o"):
    r = render_project(Ctx(), s, p, pdir, name, "draft", "libx264")
    assert r["validation"]["ok"], r["validation"]
    return pdir / "exports" / r["file"], r


def r_len(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                 "default=nw=1:nk=1", str(path)], capture_output=True, text=True).stdout)


def _frame(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(90, 160, 3).astype(float).mean(axis=(0, 1))


def _pcm(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def _band_rms(x, t0, t1, f):
    seg = x[int(t0 * 48000):int(t1 * 48000)]
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) / len(seg)
    fr = np.fft.rfftfreq(len(seg), 1 / 48000)
    return float(sp[(fr > f - 15) & (fr < f + 15)].max())


# ---------------------------------------------------------------- transitions & fades
def test_crossfade_blends_and_keeps_length(tmp_path):
    link = new_id()
    s, p, pdir, _ = _project(tmp_path, [
        ("red", 0, dict(start=0, source_in=0, source_out=2)),
        ("blue", 0, dict(start=2, source_in=1, source_out=3, link_id=link,
                         transition_in={"kind": "crossfade", "duration": 1.0})),
        ("red", 2, dict(start=0, source_in=0, source_out=2)),
        ("blue", 2, dict(start=2, source_in=1, source_out=3, link_id=link))], audio={"normalize": False})
    out, r = _render(s, p, pdir)
    assert r["validation"]["duration"] == pytest.approx(4.0, abs=0.05)
    early, mid, late = _frame(out, 1.0), _frame(out, 2.0), _frame(out, 3.2)
    assert early[0] > 200 and early[2] < 40       # red before the transition
    assert late[2] > 200 and late[0] < 40         # blue after
    assert 60 < mid[0] < 200 and 60 < mid[2] < 200  # both blended in the middle
    x = _pcm(out)
    # audio crossfades too: 440 Hz (red clip) and 660 Hz (blue clip) both present mid-transition
    full = _band_rms(x, 0.6, 1.4, 440)
    assert _band_rms(x, 1.9, 2.1, 440) > full * 0.2 and _band_rms(x, 1.9, 2.1, 660) > full * 0.2
    assert _band_rms(x, 3.2, 3.6, 440) < full * 0.05


def test_dip_to_black_goes_black(tmp_path):
    s, p, pdir, _ = _project(tmp_path, [
        ("red", 0, dict(start=0, source_in=0, source_out=2)),
        ("blue", 0, dict(start=2, source_in=0, source_out=2, transition_in={"kind": "dip_black", "duration": 1.0}))],
        audio={"normalize": False})
    out, _ = _render(s, p, pdir)
    assert _frame(out, 2.0).max() < 12, "middle of a dip-to-black is black"
    assert r_len(out) == pytest.approx(4.0, abs=0.05), "a dip doesn't change the length"
    assert _frame(out, 1.2)[0] > 120 and _frame(out, 2.8)[2] > 120


def test_transition_without_neighbour_fades_from_black(tmp_path):
    s, p, pdir, _ = _project(tmp_path, [
        ("blue", 0, dict(start=0, source_in=0, source_out=3, transition_in={"kind": "crossfade", "duration": 1.0}))],
        audio={"normalize": False})
    out, _ = _render(s, p, pdir)
    assert _frame(out, 0.02).max() < 30 and _frame(out, 1.5)[2] > 200


def test_clip_fades(tmp_path):
    s, p, pdir, _ = _project(tmp_path, [
        ("blue", 0, dict(start=0, source_in=0, source_out=3, fade_in=0.8, fade_out=0.8)),
        ("red", 2, dict(start=0, source_in=0, source_out=3, fade_in=0.8, fade_out=0.8))], audio={"normalize": False})
    out, _ = _render(s, p, pdir)
    assert _frame(out, 0.02).max() < 30 and _frame(out, 1.5)[2] > 200 and _frame(out, 2.96).max() < 40
    x = _pcm(out)
    mid = np.abs(x[int(1.4 * 48000):int(1.6 * 48000)]).max()
    assert np.abs(x[:240]).max() < mid * 0.1 and mid > 0.08  # starts silent, full level mid-clip


def test_transition_planning_shares_time_and_validation():
    from app.schema import Clip, Transition  # noqa: F401
    with pytest.raises(Exception, match="longer than the clip"):
        Project.model_validate({"id": "a" * 32, "name": "x", "media": [
            {"id": "b" * 32, "original_name": "m", "stored_name": "m.mp4", "kind": "video", "duration": 10,
             "size_bytes": 1, "has_video": True, "has_audio": True}],
            "timeline": {"tracks": [{"id": "c" * 32, "kind": "video", "name": "V1", "clips": [
                {"id": "d" * 32, "media_id": "b" * 32, "start": 0, "source_in": 0, "source_out": 1,
                 "transition_in": {"kind": "crossfade", "duration": 3}}]}]}})


def test_transition_plan_frame_counts(tmp_path):
    s, p, pdir, _ = _project(tmp_path, [
        ("red", 0, dict(start=0, source_in=0, source_out=2)),
        ("blue", 0, dict(start=2, source_in=0, source_out=2, transition_in={"kind": "crossfade", "duration": 0.8}))])
    plan = plan_render(p, p.output)
    assert [x.kind for x in plan.base] == ["clip", "transition", "clip"]
    assert [x.count for x in plan.base] == [40, 20, 40]
    assert sum(x.count for x in plan.base) == plan.total_frames == 100


# ---------------------------------------------------------------- audio processing
def test_music_ducks_under_dialogue(tmp_path):
    def run(ducking):
        s, p, pdir, _ = _project(tmp_path / ducking, [
            ("voice", 0, dict(start=0, source_in=0, source_out=6)),
            ("voice", 2, dict(start=0, source_in=0, source_out=6)),
            ("music", 3, dict(start=0, source_in=0, source_out=6))],
            audio={"normalize": False, "ducking": ducking})
        assert p.timeline.tracks[3].role == "music"
        return _pcm(_render(s, p, pdir)[0])
    off, on = run("off"), run("strong")
    talking_on, quiet_on = _band_rms(on, 0.5, 1.8, 220), _band_rms(on, 2.6, 3.8, 220)
    talking_off = _band_rms(off, 0.5, 1.8, 220)
    assert talking_on < talking_off * 0.6, "music is ducked while someone talks"
    assert quiet_on > talking_on * 1.5, "music comes back up in the pause"
    assert _band_rms(on, 0.5, 1.8, 440) == pytest.approx(_band_rms(off, 0.5, 1.8, 440), rel=0.15), "voice untouched"


def test_noise_reduction_lowers_hiss(tmp_path):
    def noise_floor(nr):
        s, p, pdir, _ = _project(tmp_path / nr, [("noisy", 0, dict(start=0, source_in=0, source_out=6)),
                                                 ("noisy", 2, dict(start=0, source_in=0, source_out=6))],
                                 audio={"normalize": False, "noise_reduction": nr})
        x = _pcm(_render(s, p, pdir)[0])
        return float(np.sqrt((x[int(4 * 48000):int(5.8 * 48000)] ** 2).mean()))
    assert noise_floor("strong") < noise_floor("off") * 0.5


@pytest.mark.parametrize("target", [-14, -16])
def test_loudness_normalised_and_validated(tmp_path, target):
    s, p, pdir, _ = _project(tmp_path, [("voice", 0, dict(start=0, source_in=0, source_out=6)),
                                        ("voice", 2, dict(start=0, source_in=0, source_out=6))],
                             audio={"normalize": True, "target_lufs": target})
    out, r = _render(s, p, pdir)
    assert abs(measure_lufs(s, out) - target) <= 1.0
    chk = next(c for c in r["validation"]["checks"] if c["check"] == "loudness")
    assert chk["ok"] and r["validation"]["loudness"]["normalized"] if "loudness" in r["validation"] else chk["ok"]


def test_peaky_quiet_audio_still_reaches_target(tmp_path):
    """Found by render stress test: soft audio with sharp peaks ended 2–5 dB short."""
    s, p, pdir, _ = _project(tmp_path, [("peaky", 0, dict(start=0, source_in=0, source_out=6)),
                                        ("peaky", 2, dict(start=0, source_in=0, source_out=6))],
                             audio={"normalize": True, "target_lufs": -14})
    out, r = _render(s, p, pdir)
    assert abs(measure_lufs(s, out) - (-14)) <= 0.6
    assert r["validation"]["ok"] and r["validation"]["loudness"].get("limiter_gain_db", 0) > 2
    x = _pcm(out)
    assert np.abs(x).max() <= 10 ** (-1.0 / 20)  # peaks stay under the ceiling


def test_silent_project_skips_normalisation(tmp_path):
    s, p, pdir, _ = _project(tmp_path, [("red", 0, dict(start=0, source_in=0, source_out=2))],
                             audio={"normalize": True})
    out, r = _render(s, p, pdir)  # no audio tracks at all -> still a valid export
    assert r["validation"]["ok"]


def test_old_projects_keep_their_sound():
    d = migrate({"schema_version": 2, "effects": [], "captions": {}})
    assert d["audio"] == {"normalize": False, "ducking": "off"} and d["schema_version"] == SCHEMA_VERSION


def test_noise_reduction_survives_a_crashing_denoiser(tmp_path, monkeypatch):
    """Windows CI: anlmdn at 'strong' crashed FFmpeg (0xC0000374). The mix must fall back
    to the FFT denoiser, still reduce the hiss, and say so in the report."""
    import app.render as R
    monkeypatch.setattr(R, "NR", {**R.NR, "strong": 0})  # anlmdn=s=0 is rejected by FFmpeg -> same path
    def floor(nr):
        s, p, pdir, _ = _project(tmp_path / nr, [("noisy", 0, dict(start=0, source_in=0, source_out=6)),
                                                 ("noisy", 2, dict(start=0, source_in=0, source_out=6))],
                                 audio={"normalize": False, "noise_reduction": nr})
        out, r = _render(s, p, pdir)
        x = _pcm(out)
        return float(np.sqrt((x[int(4 * 48000):int(5.8 * 48000)] ** 2).mean())), r
    off, _ = floor("off")
    strong, r = floor("strong")
    assert r["validation"]["ok"] and r["validation"]["loudness"]["noise_reduction_fallback"] == "afftdn"
    assert strong < off * 0.6, (strong, off)
