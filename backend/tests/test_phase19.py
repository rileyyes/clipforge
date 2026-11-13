"""Phase 19: tools from how well-edited videos keep people watching — ticker (timers, money),
time & place stamp, route on a map, highlighter, word-by-word titles, key words in captions,
riser/impact sounds, the pacing checker's motion endpoint."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app import effects as fx
from app import titles
from app.schema import CaptionSettings, Project, Title
from app.storage import new_id

from .test_audio_transitions import _project, _render
from .test_phase15 import frame_at

DATA = Path(__file__).parent / "data"


def _frame(tmp_path: Path, items: list[dict], t: float, w=640, h=360) -> np.ndarray:
    (tmp_path / "t.ass").write_text(titles.ass(items, w, h, "DejaVu Sans", None), encoding="utf-8")
    out = tmp_path / f"f{t}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x305070:s={w}x{h}:d={t + 0.5}",
                    "-vf", f"ass=t.ass,select='gte(t\\,{t})'", "-frames:v", "1", str(out)], check=True, cwd=tmp_path)
    return frame_at(out, 0, w, h)


def T(**kw) -> dict:
    return Title(id=new_id(), start=0, **kw).model_dump()


# ---------------------------------------------------------------- ticker
def test_ticker_vectors_are_current():
    """The preview's copy of the rule (phase19.ts) is checked against this file: it must match the backend."""
    for c in json.loads((DATA / "ticker_vectors.json").read_text()):
        steps = titles.ticker_steps(c["title"])
        for tt, want in c["samples"]:
            assert [x for s0, x in steps if s0 <= tt + 1e-9][-1] == want, (c["title"], tt)


@pytest.mark.parametrize("fmt,frm,to,dur,first,last", [
    ("time", 10, 0, 10.3, "0:10", "0:00"), ("time", 0, 75, 2, "0:00", "1:15"), ("time", 7200, 7199, 2, "2:00:00", "1:59:59"),
    ("money", 0, 10000, 3, "$0", "$10,000"), ("number", 1500, -20, 2, "1,500", "-20"), ("money", -5, -5, 1, "-$5", "-$5"),
])
def test_ticker_counts(fmt, frm, to, dur, first, last):
    t = T(template="ticker", duration=dur, count_from=frm, count_to=to, format=fmt)
    steps = titles.ticker_steps(t)
    assert steps[0] == (0.0, first) and steps[-1][1] == last
    step = max(1 / 15, dur / 3000)
    assert steps[-1][0] <= dur - titles.OUT + step + 1e-6                # reaches the end by the fade (sampled every step)
    assert all(steps[i][1] != steps[i + 1][1] for i in range(len(steps) - 1))
    if fmt == "time" and to < frm and abs((frm - to) - (dur - titles.OUT)) < 0.01:
        # a real-time countdown changes once a second
        assert [round(s, 2) for s, _ in steps[:4]] == [0.0, 1.0, 2.0, 3.0]


def test_ticker_events_and_hot_countdown():
    a = titles.ass([T(template="ticker", duration=12.3, count_from=12, count_to=0, text="TIME LEFT", accent="#ff0000")], 1280, 720, "DejaVu Sans", None)
    ev = a.split("[Events]")[1]
    assert "TIME LEFT" in ev and ev.count("}0:1") == 3                    # 0:12 0:11 0:10
    red = "&H000000FF&"
    for line in ev.splitlines():
        if line.endswith("}0:11"):
            assert red not in line.split("\\3c")[0]
        if line.endswith("}0:09"):
            assert f"\\c{red}" in line                                     # last ten seconds in the accent colour


def test_ticker_draws_where_it_is(tmp_path):
    img = _frame(tmp_path, [T(template="ticker", duration=3, count_from=0, count_to=500, format="money", x=0.75, y=0.5, anim="none",
                              color="#ffff00")], 2.0)
    yellow = (img[:, :, 0] > 200) & (img[:, :, 1] > 200) & (img[:, :, 2] < 80)
    ys, xs = np.nonzero(yellow)
    assert yellow.sum() > 300 and abs(xs.mean() - 480) < 40 and abs(ys.mean() - 180) < 25


# ---------------------------------------------------------------- stamp, route, highlight, words
def test_stamp_types_itself_out():
    a = titles.ass([T(template="stamp", duration=4, text="DAY 1", subtext="Tokyo")], 1280, 720, "DejaVu Sans", None)
    ev = a.split("[Events]")[1]
    assert ev.count("\\alpha&HFF&") == len("DAY 1") + len("Tokyo")       # one character at a time
    assert "\\p1" in ev                                                   # the accent bar


def test_route_draws_on_then_pins(tmp_path):
    pts = [(0.1, 0.8), (0.5, 0.8), (0.5, 0.2)]
    item = T(template="route", duration=4, points=pts, accent="#ff0000", text="HERE")
    early, done = _frame(tmp_path, [item], 0.3), _frame(tmp_path, [item], 3.0)
    red = lambda im: (im[:, :, 0] > 200) & (im[:, :, 1] < 80) & (im[:, :, 2] < 80)  # noqa: E731
    assert 0 < red(early).sum() < red(done).sum() * 0.6                  # still drawing
    ys, xs = np.nonzero(red(early))
    assert xs.max() < 320 and ys.min() > 250                              # only the first leg so far
    ys, xs = np.nonzero(red(done))
    assert ys.min() < 90 and abs(xs[ys < 90].mean() - 320) < 25           # reached the end, pin at (50 %, 20 %)
    white = (done > 230).all(axis=2)
    assert white[:60, 280:360].sum() > 30                                 # the label above the pin
    assert titles.ass([T(template="route", duration=4, points=[(0.5, 0.5)])], 640, 360, "DejaVu Sans", None).count("Dialogue") == 0


def test_route_points_are_checked():
    with pytest.raises(ValidationError):
        Title(id=new_id(), start=0, template="route", points=[(1.2, 0.5)])
    with pytest.raises(ValidationError):
        Title(id=new_id(), start=0, template="route", points=[(0.5, 0.5)] * 21)


def test_highlighter_sweeps_left_to_right(tmp_path):
    item = T(template="highlight", duration=3, x=0.5, y=0.5, w=0.6, h=0.1, accent="#ffff00")
    mid, done = _frame(tmp_path, [item], 0.3), _frame(tmp_path, [item], 1.5)
    hl = lambda im: (im[:, :, 0] > 140) & (im[:, :, 1] > 140) & (im[:, :, 2] < 120)  # noqa: E731
    ys, xs = np.nonzero(hl(done))
    assert abs(xs.min() - 128) < 6 and abs(xs.max() - 512) < 6 and abs(ys.mean() - 180) < 4
    ys2, xs2 = np.nonzero(hl(mid))
    assert abs(xs2.min() - 128) < 6 and 200 < xs2.max() < 450              # half way across


def test_words_pop_in_one_after_another():
    a = titles.ass([T(template="pop_text", anim="words", duration=3, text="THIS CHANGES EVERYTHING")], 1280, 720, "DejaVu Sans", None)
    ev = a.split("[Events]")[1]
    starts = [int(x.split(",")[0]) for x in ev.split("\\t(")[1::3]]
    assert ev.count("\\alpha&HFF&") == 3 and starts == sorted(starts) and starts[0] == 0 and starts[-1] > 0


# ---------------------------------------------------------------- captions: key words
def test_emphasis_vectors_are_current():
    v = json.loads((DATA / "emphasis_vectors.json").read_text(encoding="utf-8"))
    assert v["skip"] == sorted(fx.EMPHASIS_SKIP)
    for c in v["cases"]:
        assert fx.key_word(c["words"]) == c["key"], c["words"]


@pytest.mark.parametrize("style", ["bold_pop", "clean", "highlight"])
def test_captions_make_the_key_word_stand_out(style, tmp_path):
    words = [{"text": t, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, t in enumerate(["WE", "WON", "$10,000"])]
    chunk = {"start": 0.0, "end": 1.0, "text": "WE WON $10,000", "words": words}
    s, p, pdir, _ = _project(tmp_path, [("red", 0, {"start": 0, "source_in": 0, "source_out": 6})])
    d = p.model_dump(mode="json")
    d["captions"] = {**d["captions"], "enabled": True, "style": style, "emphasis": True, "emphasis_color": "#00ff00"}
    on = fx.captions_ass(Project.model_validate(d), [chunk], "DejaVu Sans", 720, 1280)
    d["captions"]["emphasis"] = False
    off = fx.captions_ass(Project.model_validate(d), [chunk], "DejaVu Sans", 720, 1280)
    green = "&H0000FF00"
    assert green not in off and "$10,000" in off
    for line in [ln for ln in on.splitlines() if ln.startswith("Dialogue")]:
        before = line.split("}$10,000")[0]
        lit = "&H0000DEFF"     # word highlight: while it's being said it has the highlight colour, still bigger
        assert (f"\\c{green}" in before or (style == "highlight" and f"\\c{lit}" in before.rsplit("{", 1)[-1])) \
            and ("\\fscx115" in before or "\\fscx129" in before), line
        assert line.count(green) <= 1


# ---------------------------------------------------------------- sounds, pacing endpoint
def test_riser_and_impact_sounds(tmp_path):
    for name in ("riser", "impact"):
        out = tmp_path / f"{name}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *fx.sound_input_args(name, 48000, 0.8, 48000), "-c:a", "pcm_s16le", str(out)], check=True)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-ac", "1", "-f", "f32le", "-"], capture_output=True, check=True).stdout
        x = np.abs(np.frombuffer(raw, np.float32))
        first, last = x[:12000].mean(), x[-12000:].mean()
        if name == "riser":
            assert last > 4 * first                                       # builds up
        else:
            assert first > 4 * last                                       # hits then dies away
    Project.model_validate  # (the names are valid effect sounds)
    from app.schema import Effect
    Effect(id=new_id(), kind="sfx", media_id=new_id(), source_time=0, duration=1, sound="riser")


def test_pacing_motion_needs_analysis(server, media_dir):
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "pace"})
    st, r, _ = c.upload(p["id"], media_dir / "av.mp4")
    c.wait_job(r["job_id"])
    _, pr, _ = c.req("GET", f"/api/projects/{p['id']}")
    m = r["media"]
    pr["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": m["id"], "start": 0, "source_in": 0, "source_out": 2}]
    c.req("PUT", f"/api/projects/{p['id']}/timeline", {"base_edit_revision": pr["edit_revision"], "timeline": pr["timeline"], "output": pr["output"]})
    st, r, _ = c.req("GET", f"/api/projects/{p['id']}/pacing/motion")
    assert st == 200 and r["motion"] is None                              # not analysed: only the edit's own changes count
    st, job, _ = c.req("POST", f"/api/projects/{p['id']}/autoedit/analyze", {"media_id": m["id"]})
    assert c.wait_job(job["id"])["status"] == "succeeded"
    st, r, _ = c.req("GET", f"/api/projects/{p['id']}/pacing/motion")
    assert st == 200 and len(r["motion"]) == 20 and all(0 <= v <= 1 for v in r["motion"]) and r["step"] == 0.1


def test_phase19_export(tmp_path):
    s, p, pdir, media = _project(tmp_path, [("blue", 0, {"start": 0, "source_in": 0, "source_out": 6}),
                                            ("blue", 2, {"start": 0, "source_in": 0, "source_out": 6})])
    d = p.model_dump(mode="json")
    d["timeline"]["titles"] = [T(template="ticker", duration=4, count_from=0, count_to=99, format="number", x=0.5, y=0.5, anim="none"),
                               T(template="stamp", duration=4, text="DAY 1"),
                               T(template="route", duration=4, points=[(0.1, 0.9), (0.9, 0.1)]),
                               T(template="highlight", duration=4, x=0.5, y=0.8, w=0.5, h=0.1)]
    d["effects"] = [{"id": new_id(), "kind": "sfx", "media_id": media["blue"].id, "source_time": 1.0, "duration": 1.5, "sound": "riser"}]
    out, r = _render(s, Project.model_validate(d), pdir, "p19")
    assert r["validation"]["ok"]
