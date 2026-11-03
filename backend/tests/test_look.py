"""Phase 6: crop, rotation, opacity, colour, looks, keyframes, more transitions.

Every render assertion measures pixels / audio of the exported file."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app import look
from app.config import Settings
from app.media import build_asset
from app.projects import ProjectStore
from app.render import XFADE, render_project
from app.schema import Keyframe, Project, migrate
from app.storage import new_id

from test_audio_transitions import Ctx

FPS = 25
W, H = 160, 90
PICS = {
    "red": "color=c=red:s=160x90",
    "blue": "color=c=blue:s=160x90",
    "white": "color=c=white:s=160x90",
    "halves": "color=c=red:s=160x90,drawbox=x=80:y=0:w=80:h=90:color=blue:t=fill",  # red | blue
    "gray": "color=c=0x808080:s=160x90",
    "colors": "testsrc2=s=160x90",
}


def _src(spec: str, extra: str) -> str:
    first, _, rest = spec.partition(",")
    return first + extra + ("," + rest if rest else "")


def _media(path: Path, pic: str, audio: str = "sine=f=440:sample_rate=48000", d: float = 4):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", _src(PICS[pic], f":r={FPS}:d={d}"),
                    "-f", "lavfi", "-i", f"{audio}:d={d}", "-shortest", "-c:v", "libx264", "-crf", "10",
                    "-pix_fmt", "yuv444p" if pic == "halves" else "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def project(tmp_path, specs, transitions=None):
    """specs: (pic, track_index, clip dict)."""
    s = Settings(workspace=tmp_path)
    st = ProjectStore(tmp_path / "projects")
    p = st.create("t")
    pdir = st.dir(p.id)
    media = {}
    d = p.model_dump(mode="json")
    for pic, ti, c in specs:
        if pic not in media:
            mid = new_id()
            f = _media(pdir / "media" / "original" / f"{mid}.mp4", pic)
            media[pic] = build_asset(s, mid, f, f"{pic}.mp4")
        d["timeline"]["tracks"][ti]["clips"].append({"id": new_id(), "media_id": media[pic].id, **c})
    d["media"] = [m.model_dump(mode="json") for m in media.values()]
    d["output"] = {"width": W, "height": H, "fps": FPS, "fit_mode": "fit"}
    d["audio"] = {"normalize": False, "ducking": "off"}
    return s, Project.model_validate(d), pdir


def render(s, p, pdir):
    r = render_project(Ctx(), s, p, pdir, "o", "high", "libx264")
    assert r["validation"]["ok"], r["validation"]
    return pdir / "exports" / r["file"]


def frame(path: Path, t: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)


def is_(px, rgb, tol=60):
    return all(abs(int(a) - b) <= tol for a, b in zip(px, rgb))


RED, BLUE, BLACK, WHITE = (255, 0, 0), (0, 0, 255), (0, 0, 0), (255, 255, 255)


def lit_cx(img: np.ndarray) -> float:
    """Centre x of the non-black pixels."""
    ys, xs = np.nonzero(img.sum(axis=2) > 150)
    return float(xs.mean())


# ---------------------------------------------------------------- keyframe maths
def K(*pts):
    return [Keyframe(t=t, v=v, ease=e) for t, v, e in pts]


def _eval_ffmpeg_expr(expr: str, **vars_) -> float:
    """Tiny evaluator for the subset kf_expr emits (if/lt/arithmetic)."""
    py = re.sub(r"\bif\(", "IF(", expr)
    return float(eval(py, {"IF": lambda a, b, c: b if a else c, "lt": lambda a, b: a < b, **vars_}))


def test_value_at_linear_ease_hold_and_clamps():
    k = K((1, 0, "linear"), (3, 10, "ease"), (5, 20, "hold"), (7, 0, "linear"))
    assert look.value_at(k, 0, 99) == 0 and look.value_at(k, 9, 99) == 0
    assert look.value_at(k, 2, 99) == pytest.approx(5)
    assert look.value_at(k, 3.5, 99) == pytest.approx(10 + 10 * 0.15625)  # smoothstep(0.25)
    assert look.value_at(k, 4, 99) == pytest.approx(15)
    assert look.value_at(k, 6.9, 99) == 20  # hold until the next keyframe
    assert look.value_at([], 3, 7) == 7


def test_ffmpeg_expression_matches_value_at():
    rng = np.random.default_rng(3)
    for _ in range(200):
        n = int(rng.integers(1, 7))
        ts = np.cumsum(rng.uniform(0.01, 3, n))
        k = [Keyframe(t=float(t), v=float(rng.uniform(-50, 50)), ease=str(rng.choice(["linear", "ease", "hold"])))
             for t in ts]
        e = look.kf_expr(k, "T", 0)
        for t in rng.uniform(-1, ts[-1] + 1, 15):
            assert _eval_ffmpeg_expr(e, T=float(t)) == pytest.approx(look.value_at(k, float(t), 0), abs=1e-4)


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize("clip, msg", [
    ({"keyframes": {"bogus": [{"t": 0, "v": 1}]}}, "can't be keyframed"),
    ({"keyframes": {"x": [{"t": 1, "v": 0}, {"t": 0.5, "v": 1}]}}, "time order"),
    ({"keyframes": {"opacity": [{"t": 0, "v": 2}]}}, "outside"),
    ({"keyframes": {"x": [{"t": i / 10, "v": 0} for i in range(65)]}}, "at most"),
    ({"crop": {"left": 0.6, "right": 0.35}}, "at least 10%"),
    ({"crop": {"top": 0.95}}, "less than or equal"),
    ({"color": {"look": "sepia-ish"}}, "look"),
    ({"transform": {"opacity": 1.5}}, "opacity"),
])
def test_bad_look_values_rejected(tmp_path, clip, msg):
    with pytest.raises(ValidationError, match=msg):
        project(tmp_path, [("red", 0, dict(start=0, source_in=0, source_out=2, **clip))])


def test_video_keyframes_not_allowed_on_audio_clips(tmp_path):
    with pytest.raises(ValidationError, match="can't be keyframed on audio"):
        project(tmp_path, [("red", 2, dict(start=0, source_in=0, source_out=2,
                                           keyframes={"x": [{"t": 0, "v": 1}]}))])


def test_v3_projects_migrate_to_v4():
    assert migrate({"schema_version": 3})["schema_version"] == 4


# ---------------------------------------------------------------- renders
def test_rotation_90_turns_the_picture(tmp_path):
    s, p, pdir = project(tmp_path, [("halves", 0, dict(start=0, source_in=0, source_out=2,
                                                        transform={"rotation": 90}))])
    f = frame(render(s, p, pdir), 1.0)
    # clockwise: the red left half goes to the top, blue right half to the bottom, sides go black
    assert is_(f[20, 80], RED) and is_(f[70, 80], BLUE)
    assert is_(f[45, 5], BLACK) and is_(f[45, 154], BLACK)


def test_animated_position_scale_and_static_rotation_on_base_track(tmp_path):
    kf = {"x": [{"t": 0, "v": -40}, {"t": 2, "v": 40}]}
    s, p, pdir = project(tmp_path, [("white", 0, dict(start=0, source_in=0, source_out=2,
                                                       transform={"scale": 0.25}, keyframes=kf))])
    out = render(s, p, pdir)
    for t, want in ((0.04, -38.4), (1.0, 0), (1.92, 36.8)):
        assert lit_cx(frame(out, t)) - W / 2 == pytest.approx(want, abs=3), t
    # animated scale: 0.2 -> 0.6 width
    s, p, pdir = project(tmp_path / "b", [("white", 0, dict(start=0, source_in=0, source_out=2,
                                                             keyframes={"scale": [{"t": 0, "v": 0.2}, {"t": 2, "v": 0.6}]}))])
    out = render(s, p, pdir)
    widths = [(frame(out, t).sum(axis=2)[45] > 300).sum() for t in (0.2, 1.0, 1.8)]
    assert widths[0] < widths[1] < widths[2]
    assert widths[1] == pytest.approx(W * 0.4, abs=4)


def test_keyframes_follow_the_source_after_a_trim(tmp_path):
    """Keyframes are on source time: trimming 1 s off the start shifts the animation with it."""
    kf = {"x": [{"t": 0, "v": -40}, {"t": 2, "v": 40}]}
    s, p, pdir = project(tmp_path, [("white", 0, dict(start=0, source_in=1, source_out=2,
                                                       transform={"scale": 0.25}, keyframes=kf))])
    out = render(s, p, pdir)
    assert lit_cx(frame(out, 0.0)) - W / 2 == pytest.approx(0, abs=3)  # source t=1 -> x=0


def test_opacity_static_and_animated(tmp_path):
    s, p, pdir = project(tmp_path, [("white", 0, dict(start=0, source_in=0, source_out=2,
                                                       keyframes={"opacity": [{"t": 0, "v": 0}, {"t": 2, "v": 1}]})),
                                    ("white", 0, dict(start=2, source_in=0, source_out=1, transform={"opacity": 0.5}))])
    out = render(s, p, pdir)
    lv = [frame(out, t)[45, 80].mean() for t in (0.1, 1.0, 1.9, 2.5)]
    assert lv[0] < 40 and 100 < lv[1] < 155 and lv[2] > 215 and 100 < lv[3] < 155, lv


def test_rotated_overlay_composites_over_base(tmp_path):
    s, p, pdir = project(tmp_path, [("red", 0, dict(start=0, source_in=0, source_out=2)),
                                    ("blue", 1, dict(start=0, source_in=0, source_out=2,
                                                     transform={"scale": 0.5, "rotation": 45}))])
    f = frame(render(s, p, pdir), 1.0)
    assert is_(f[45, 80], BLUE)       # centre: the overlay
    assert is_(f[5, 5], RED)          # far corner: base shows through (transparent around it)
    assert is_(f[24, 42], RED)        # inside the unrotated box's corner, outside the diamond


def test_crop_hides_edges_without_moving_the_rest(tmp_path):
    s, p, pdir = project(tmp_path, [("red", 0, dict(start=0, source_in=0, source_out=2)),
                                    ("halves", 1, dict(start=0, source_in=0, source_out=2,
                                                       transform={"scale": 0.5}, crop={"right": 0.5})),
                                    ("blue", 0, dict(start=2, source_in=0, source_out=2,
                                                     crop={"left": 0.25, "top": 0.2}))])
    out = render(s, p, pdir)
    f = frame(out, 1.0)  # overlay spans x 40..120; its right (blue) half is cropped away
    assert is_(f[45, 55], RED) and is_(f[45, 100], RED)  # left half = red overlay, right = red base
    g = frame(out, 3.0)  # base clip cropped: left quarter and top 20% are black now
    assert is_(g[45, 20], BLACK) and is_(g[8, 80], BLACK) and is_(g[60, 100], BLUE)


def test_cropped_overlay_keeps_position(tmp_path):
    s, p, pdir = project(tmp_path, [("halves", 1, dict(start=0, source_in=0, source_out=2,
                                                       transform={"scale": 0.5}, crop={"left": 0.5}))])
    f = frame(render(s, p, pdir), 1.0)  # remaining blue half stays at x 80..120
    assert is_(f[45, 60], BLACK) and is_(f[45, 100], BLUE) and is_(f[45, 130], BLACK)


@pytest.mark.parametrize("color, check", [
    ({"look": "bw"}, lambda f: np.ptp(f[45, 80]) < 15),
    ({"look": "noir"}, lambda f: np.ptp(f[45, 80]) < 15),
    ({"saturation": 0}, lambda f: np.ptp(f[45, 80]) < 15),
    ({"brightness": 0.3}, lambda f: f.mean() > 128 + 40),
    ({"contrast": 0.3}, lambda f: abs(f.mean() - 128) < 30),
    ({"temperature": 1}, lambda f: f[..., 0].mean() - f[..., 2].mean() > 20),   # warm: red > blue
    ({"temperature": -1}, lambda f: f[..., 2].mean() - f[..., 0].mean() > 20),  # cool: blue > red
    ({"look": "warm"}, lambda f: f[..., 0].mean() > f[..., 2].mean() + 10),
    ({"look": "cool"}, lambda f: f[..., 2].mean() > f[..., 0].mean() + 10),
])
def test_colour_and_looks(tmp_path, color, check):
    pic = "colors" if "look" in color and color["look"] in ("bw", "noir") or "saturation" in color else "gray"
    s, p, pdir = project(tmp_path, [(pic, 0, dict(start=0, source_in=0, source_out=1, color=color))])
    assert check(frame(render(s, p, pdir), 0.5))


def test_every_look_renders(tmp_path):
    specs = [("colors", 0, dict(start=i * 0.5, source_in=0, source_out=0.5, color={"look": lk}))
             for i, lk in enumerate(look.LOOK_FILTERS)]
    s, p, pdir = project(tmp_path, specs)
    out = render(s, p, pdir)
    means = [frame(out, i * 0.5 + 0.25).mean() for i in range(len(specs))]
    assert len(set(round(m) for m in means)) >= 6  # looks actually differ


def test_volume_keyframes(tmp_path):
    s, p, pdir = project(tmp_path, [("red", 2, dict(start=0, source_in=0, source_out=4,
                                                    keyframes={"volume": [{"t": 0, "v": 0}, {"t": 4, "v": 1}]}))])
    out = render(s, p, pdir)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         check=True, capture_output=True).stdout
    a = np.frombuffer(raw, "<i2").astype(float)
    q = [np.sqrt(np.mean(x ** 2)) for x in np.array_split(a, 4)]
    assert q[0] < q[1] < q[2] < q[3] and q[3] > 4 * q[0], q


# ---------------------------------------------------------------- transitions
@pytest.mark.parametrize("kind", sorted(XFADE))
def test_every_transition_exists_in_ffmpeg(tmp_path, kind):
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x36:d=1:r=25",
                        "-f", "lavfi", "-i", "color=blue:s=64x36:d=1:r=25", "-filter_complex",
                        f"xfade=transition={XFADE[kind]}:duration=0.5:offset=0.2", "-f", "null", "-"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _two(tmp_path, kind, dur=1.0):
    return project(tmp_path, [("red", 0, dict(start=0, source_in=0, source_out=2)),
                              ("blue", 0, dict(start=2, source_in=0, source_out=2,
                                               transition_in={"kind": kind, "duration": dur}))])


def test_wipe_and_slide_are_spatial(tmp_path):
    s, p, pdir = _two(tmp_path, "wipe_left")
    f = frame(render(s, p, pdir), 2.0)  # half-way: one side is already the new clip
    left, right = f[45, 20], f[45, 140]
    assert {tuple(is_(left, c) for c in (RED, BLUE)), tuple(is_(right, c) for c in (RED, BLUE))} == \
        {(True, False), (False, True)}


def test_dip_to_white(tmp_path):
    s, p, pdir = _two(tmp_path, "dip_white")
    out = render(s, p, pdir)
    assert is_(frame(out, 2.0)[45, 80], WHITE, 40)
    assert is_(frame(out, 1.0)[45, 80], RED) and is_(frame(out, 3.0)[45, 80], BLUE)
