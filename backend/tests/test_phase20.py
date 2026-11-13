"""Phase 20: sound mixer (track volume, solo, effects level) and blend modes."""
from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app import look
from app.render import BLEND_FFMPEG, blend_chain, plan_render
from app.schema import SCHEMA_VERSION, Clip, Effect, Project, Track, migrate
from app.storage import new_id

from .test_audio_transitions import _project, _render
from .test_phase15 import frame_at
from .test_phase18 import _level

SIX = {"start": 0, "source_in": 0, "source_out": 6}


# ---------------------------------------------------------------- schema
def test_mixer_and_blend_fields_validate():
    t = Track(id=new_id(), kind="audio", name="A1")
    assert t.volume == 1.0 and t.solo is False
    Track(id=new_id(), kind="audio", name="A1", volume=2.0)
    with pytest.raises(ValidationError):
        Track(id=new_id(), kind="audio", name="A1", volume=2.5)
    with pytest.raises(ValidationError):
        Track(id=new_id(), kind="audio", name="A1", volume=-0.1)
    c = Clip(id=new_id(), media_id=new_id(), start=0, source_in=0, source_out=1)
    assert c.blend == "normal" and not look.needs_warp(c)
    assert look.needs_warp(c.model_copy(update={"blend": "screen"}))
    with pytest.raises(ValidationError):
        Clip(id=new_id(), media_id=new_id(), start=0, source_in=0, source_out=1, blend="dissolve")


def test_old_projects_upgrade_to_v9():
    assert SCHEMA_VERSION == 9
    d = migrate({"schema_version": 8, "id": new_id(), "name": "x"})
    assert d["schema_version"] == 9


def test_every_blend_mode_has_an_ffmpeg_name():
    from app.schema import BLEND_MODES
    assert set(BLEND_MODES) - {"normal"} == set(BLEND_FFMPEG)
    g = blend_chain("v0", "o1", "screen", "v1", "b1")
    assert g[-1].endswith("[v1]") and "all_mode=screen" in ";".join(g)


# ---------------------------------------------------------------- mixer: render
def _mix_project(tmp_path, **audio):
    # A1 = the "movie" (440 Hz), A2 = music (220 Hz)
    s, p, pdir, media = _project(tmp_path, [("red", 0, SIX), ("red", 2, SIX), ("music", 3, SIX)],
                                 audio={"normalize": False, "ducking": "off", **audio})
    d = p.model_dump(mode="json")
    d["timeline"]["tracks"][3]["role"] = "music"
    return s, d, pdir, media


def test_track_volume_sets_the_balance(tmp_path):
    s, d, pdir, _ = _mix_project(tmp_path)
    out0, _ = _render(s, Project.model_validate(d), pdir, "even")
    d["timeline"]["tracks"][3]["volume"] = 0.25          # music down to 25 %
    d["timeline"]["tracks"][2]["volume"] = 1.5           # movie up
    out1, _ = _render(s, Project.model_validate(d), pdir, "mixed")
    mus0, mus1 = _level(out0, 1, 5, 220), _level(out1, 1, 5, 220)
    mov0, mov1 = _level(out0, 1, 5, 440), _level(out1, 1, 5, 440)
    assert 0.2 < mus1 / mus0 < 0.3, (mus0, mus1)
    assert 1.4 < mov1 / mov0 < 1.6, (mov0, mov1)


def test_solo_and_zero_volume(tmp_path):
    s, d, pdir, _ = _mix_project(tmp_path)
    d["timeline"]["tracks"][3]["solo"] = True             # only the music
    p = Project.model_validate(d)
    plan = plan_render(p, p.output)
    assert plan.audio_roles == ["music"] and plan.audio_volumes == [1.0]
    out, _ = _render(s, p, pdir, "solo")
    assert _level(out, 1, 5, 440) < _level(out, 1, 5, 220) * 0.02
    d["timeline"]["tracks"][3]["solo"] = False
    d["timeline"]["tracks"][3]["volume"] = 0              # music off = left out of the mix entirely
    p = Project.model_validate(d)
    assert plan_render(p, p.output).audio_roles == ["dialogue"]


def test_effects_level_turns_sound_effects_down(tmp_path):
    s, d, pdir, media = _mix_project(tmp_path)
    d["timeline"]["tracks"][2]["muted"] = True
    d["timeline"]["tracks"][3]["muted"] = True
    d["effects"] = [Effect(id=new_id(), kind="sfx", media_id=media["red"].id, source_time=2.0, duration=1.0,
                           sound="ding", volume=1.0).model_dump(mode="json")]
    loud, _ = _render(s, Project.model_validate(d), pdir, "fx1")
    d["audio"]["fx_volume"] = 0.3
    quiet, _ = _render(s, Project.model_validate(d), pdir, "fx03")
    from .test_audio_transitions import _pcm
    a, b = _pcm(loud)[96000:144000], _pcm(quiet)[96000:144000]
    ra, rb = math.sqrt(float((a ** 2).mean())), math.sqrt(float((b ** 2).mean()))
    assert ra > 0.01 and 0.25 < rb / ra < 0.35, (ra, rb)


# ---------------------------------------------------------------- blend modes: render
def _css(mode: str, b: float, s: float) -> float:
    """The CSS mix-blend-mode formulas the preview uses (b = picture under it, s = layer)."""
    if mode == "screen":
        return 1 - (1 - b) * (1 - s)
    if mode == "multiply":
        return b * s
    if mode == "lighten":
        return max(b, s)
    if mode == "darken":
        return min(b, s)
    if mode == "addition":            # CSS plus-lighter
        return min(1.0, b + s)
    if mode == "difference":
        return abs(b - s)
    if mode == "overlay":             # hard light with the layers swapped
        return 2 * b * s if b <= 0.5 else 1 - 2 * (1 - b) * (1 - s)
    if mode == "softlight":
        if s <= 0.5:
            return b - (1 - 2 * s) * b * (1 - b)
        dd = ((16 * b - 12) * b + 4) * b if b <= 0.25 else math.sqrt(b)
        return b + (2 * s - 1) * (dd - b)
    raise ValueError(mode)


@pytest.mark.parametrize("mode", ["screen", "multiply", "overlay", "lighten", "darken", "addition", "difference", "softlight"])
def test_blend_mode_export_matches_the_preview_formula(tmp_path, mode):
    # gray base under a red layer from 2 s to 4 s
    s, p, pdir, _ = _project(tmp_path, [("voice", 0, SIX), ("red", 1, {"start": 2, "source_in": 0, "source_out": 2})])
    d = p.model_dump(mode="json")
    d["timeline"]["tracks"][1]["clips"][0]["blend"] = mode
    out, _ = _render(s, Project.model_validate(d), pdir, mode)
    before, during, after = frame_at(out, 1.0)[18, 32], frame_at(out, 3.0)[18, 32], frame_at(out, 5.0)[18, 32]
    base = before / 255
    want = [_css(mode, base[i], [1.0, 0.0, 0.0][i]) * 255 for i in range(3)]
    tol = 14 if mode == "softlight" else 10              # FFmpeg's soft light is a close cousin of the CSS one
    assert all(abs(during[i] - want[i]) <= tol for i in range(3)), (mode, before, during, want)
    assert all(abs(after[i] - before[i]) <= 3 for i in range(3)), (after, before)   # gone after the layer


def test_blend_respects_the_layer_opacity(tmp_path):
    s, p, pdir, _ = _project(tmp_path, [("voice", 0, SIX), ("red", 1, {"start": 0, "source_in": 0, "source_out": 6})])
    d = p.model_dump(mode="json")
    c = d["timeline"]["tracks"][1]["clips"][0]
    c["blend"] = "multiply"
    c["transform"]["opacity"] = 0.5
    out, _ = _render(s, Project.model_validate(d), pdir, "half")
    px = frame_at(out, 3.0)[18, 32]
    g = 128 / 255
    want = [0.5 * g + 0.5 * g * x for x in (1.0, 0.0, 0.0)]
    assert all(abs(px[i] - want[i] * 255) <= 10 for i in range(3)), (px, [w * 255 for w in want])
