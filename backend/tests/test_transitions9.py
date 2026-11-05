"""Phase 9: nine new transition styles (pixel checks on red -> blue)."""
from __future__ import annotations

import numpy as np
import pytest

from app.render import CUSTOM

from test_look import BLUE, RED, WHITE, frame, is_, project, render

NEW = ["whip_left", "whip_right", "spin", "glitch", "rgb_split", "light_leak", "zoom_blur", "flash_cut", "shake_cut"]


def _two(tmp_path, kind, dur=1.0, a="red", b="blue"):
    return project(tmp_path, [(a, 0, dict(start=0, source_in=0, source_out=2)),
                              (b, 0, dict(start=2, source_in=0, source_out=2,
                                          transition_in={"kind": kind, "duration": dur}))])


def share(f, rgb, tol=70):
    return float(np.mean(np.all(np.abs(f - np.array(rgb)) <= tol, axis=2)))


def test_every_new_kind_is_implemented():
    assert set(NEW) - {"spin"} == set(CUSTOM)


@pytest.mark.parametrize("kind", NEW)
def test_new_transition_renders_and_lands_on_both_clips(tmp_path, kind):
    s, p, pdir = _two(tmp_path, kind)
    out = render(s, p, pdir)  # validation (frame count, duration, A/V sync) checked inside
    assert share(frame(out, 1.2), RED) > 0.97
    assert share(frame(out, 2.8), BLUE) > 0.97
    if kind not in ("shake_cut", "zoom_blur"):  # shaking/zooming a solid colour looks the same (own tests)
        mid = frame(out, 2.0)
        assert share(mid, RED) < 0.97 and share(mid, BLUE) < 0.97, kind  # something is happening


def test_whip_is_a_sideways_move(tmp_path):
    s, p, pdir = _two(tmp_path, "whip_left")
    f = frame(render(s, p, pdir), 2.0)
    assert share(f[:, :40], RED) > 0.6 or share(f[:, -40:], BLUE) > 0.6


def test_flash_cut_flashes_white_and_cuts(tmp_path):
    s, p, pdir = _two(tmp_path, "flash_cut")
    out = render(s, p, pdir)
    assert share(frame(out, 2.0), WHITE, 60) > 0.9
    assert share(frame(out, 1.62), RED) > 0.9 and share(frame(out, 2.4), BLUE) > 0.9


def test_shake_cut_is_a_hard_cut_with_movement(tmp_path):
    s, p, pdir = project(tmp_path, [("colors", 0, dict(start=0, source_in=0, source_out=2)),
                                    ("colors", 0, dict(start=2, source_in=2, source_out=4,
                                                       transition_in={"kind": "shake_cut", "duration": 1.0}))])
    out = render(s, p, pdir)
    a, b = frame(out, 1.92), frame(out, 2.0)
    assert np.abs(a - b).mean() > 10  # the picture moves around the cut


def test_light_leak_glows_top_right(tmp_path):
    s, p, pdir = _two(tmp_path, "light_leak", a="gray", b="gray")
    f = frame(render(s, p, pdir), 2.0)
    assert f[15, 130].mean() > f[80, 15].mean() + 40
    assert f[15, 130][0] > f[15, 130][2] + 40  # warm (more red than blue)


def test_glitch_mixes_bands_of_both(tmp_path):
    s, p, pdir = _two(tmp_path, "glitch")
    out = render(s, p, pdir)
    found = False
    for t in (1.8, 1.9, 2.0, 2.1, 2.2):
        f = frame(out, t)
        rows = [share(f[y:y + 1], RED) > 0.8 for y in range(0, 90, 5)] + \
               [share(f[y:y + 1], BLUE) > 0.8 for y in range(0, 90, 5)]
        if share(f, RED) > 0.1 and share(f, BLUE) > 0.1 and any(rows):
            found = True
    assert found


def test_spin_rotates(tmp_path):
    s, p, pdir = _two(tmp_path, "spin")
    f = frame(render(s, p, pdir), 1.85)
    assert f[2, 2].max() < 60 or f[87, 157].max() < 60  # a corner shows the black behind the turning picture


def test_zoom_blur_zooms_into_the_picture(tmp_path):
    s, p, pdir = project(tmp_path, [("colors", 0, dict(start=0, source_in=0, source_out=2)),
                                    ("colors", 0, dict(start=2, source_in=2, source_out=4,
                                                       transition_in={"kind": "zoom_blur", "duration": 1.0}))])
    out = render(s, p, pdir)
    f = frame(out, 1.85)                       # zoomed in ~1.5x
    # the centre of a zoomed picture is a blurry enlargement: much less fine detail than the original
    detail = lambda img: np.abs(np.diff(img.astype(float), axis=1)).mean()  # noqa: E731
    assert detail(f) < detail(frame(out, 1.2)) * 0.8


def test_spin_ends_straight_on_the_right_frames(tmp_path):
    s, p, pdir = project(tmp_path, [("colors", 0, dict(start=0, source_in=0, source_out=2)),
                                    ("colors", 0, dict(start=2, source_in=2, source_out=4,
                                                       transition_in={"kind": "spin", "duration": 1.0}))])
    out = render(s, p, pdir)
    ref, rp, rdir = project(tmp_path / "r", [("colors", 0, dict(start=0, source_in=0, source_out=4))])
    plain = render(ref, rp, rdir)
    # near the end of the transition the new clip is upright and in time with the source
    assert np.abs(frame(out, 2.44) - frame(plain, 2.44)).mean() < 12
    assert np.abs(frame(out, 2.6) - frame(plain, 2.6)).mean() < 4
