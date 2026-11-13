"""Phase 18: fonts and text styles, counter tools (counter, callout cards, tally, narration
ducking), reaction & group tools (funny moments, name tags, bass boost) and new looks/templates."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app import effects as fx
from app import fontlib, overlays, reactions, titles
from app.analysis import HOP
from app.look import LOOK_FILTERS
from app.schema import Counter, Effect, Project, Title, migrate
from app.storage import new_id

from .test_audio_transitions import _project, _render
from .test_phase15 import frame_at


def _ass_frame(tmp_path: Path, ass_text: str, fonts: dict, t: float = 1.0, w=640, h=360) -> np.ndarray:
    """Draw an ASS file on black with libass (fonts copied next to it, like the render does)."""
    for fid, (_, path) in fonts.items():
        dst = tmp_path / Path(path).name
        if not dst.exists():
            dst.write_bytes(Path(path).read_bytes())
    (tmp_path / "t.ass").write_text(ass_text, encoding="utf-8")
    out = tmp_path / f"f{abs(hash(ass_text)) % 10**8}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={t + 0.5}",
                    "-vf", f"ass=t.ass:fontsdir=.,select='gte(t\\,{t})'", "-frames:v", "1", str(out)], check=True, cwd=tmp_path)
    return frame_at(out, 0, w, h)


# ---------------------------------------------------------------- fonts
def test_builtin_fonts_ship_with_their_licences():
    fonts = fontlib.list_fonts(Path("/nonexistent-ws"))
    built = [f for f in fonts if f["source"] == "builtin"]
    assert len(built) >= 20
    from PIL import ImageFont
    for f in built:
        p, fam = fontlib.resolve(Path("/nonexistent-ws"), f["id"])
        assert p.is_file() and fam == f["family"]
        assert ImageFont.truetype(str(p), 20).getname()[0] == fam          # the family libass will match
        lic = (fontlib.BUILTIN_DIR / "licenses" / f"{f['id']}.txt").read_text(encoding="utf-8")
        assert "SIL Open Font License" in lic or "Apache License" in lic, f["id"]
    assert {"Bold", "Horror", "Fun", "Retro & gaming", "Handwritten", "Stickers", "Clean"} <= {f["category"] for f in built}


def _a_font_file() -> bytes:
    """A real .ttf that isn't one of the built-in families (DejaVu, from the system or matplotlib)."""
    from app.effects import find_font
    f = find_font()
    if not f or not f.lower().endswith(".ttf"):
        pytest.skip("no system .ttf font")
    return Path(f).read_bytes()


def test_add_your_own_font_checks_the_file(tmp_path):
    ws = tmp_path
    data = _a_font_file()
    f = fontlib.add(ws, data, "My Font.ttf")
    assert f["id"].startswith("u-") and f["source"] == "yours" and f["name"] == "My Font"
    p, fam = fontlib.resolve(ws, f["id"])
    assert p.read_bytes() == data and fam == f["family"]
    assert any(x["id"] == f["id"] for x in fontlib.list_fonts(ws))
    with pytest.raises(ValueError, match="already have"):
        fontlib.add(ws, data, "again.ttf")
    for bad, msg in ((b"wOFF" + data[4:], "Web fonts"), (b"ttcf" + data[4:], "collections"), (b"hello world", "isn't a .ttf"),
                     (b"\x00\x01\x00\x00" + b"x" * 200, "couldn't read")):
        with pytest.raises(ValueError, match=msg):
            fontlib.add(ws, bad, "x.ttf")
    assert fontlib.delete(ws, f["id"]) and fontlib.resolve(ws, f["id"]) is None
    assert not fontlib.delete(ws, "anton")                     # built-ins can't be deleted
    assert fontlib.resolve(ws, "../etc/passwd") is None


def test_fonts_and_text_styles_api(server):
    c = server
    st, r, _ = c.req("GET", "/api/fonts")
    assert st == 200 and any(f["id"] == "creepster" for f in r["fonts"])
    import urllib.request
    with urllib.request.urlopen(c.base + "/api/fonts/creepster/file") as resp:     # browsers load it with no header
        assert resp.headers["Content-Type"].startswith("font/") and resp.read()[:4] == b"\x00\x01\x00\x00"
    data = _a_font_file()
    st, r, _ = c.req("POST", "/api/fonts?filename=Mine.ttf", raw=data)
    assert st == 200, r
    fid = r["font"]["id"]
    st, r, _ = c.req("POST", "/api/fonts?filename=bad.woff", raw=b"wOFF" + data[4:])
    assert st == 415 and "Web fonts" in r["error"]
    st, r, _ = c.req("DELETE", f"/api/fonts/{fid}")
    assert st == 200 and not any(f["id"] == fid for f in r["fonts"])
    st, r, _ = c.req("DELETE", "/api/fonts/anton")
    assert st == 404
    st, r, _ = c.req("GET", "/api/text-styles")
    assert st == 200 and r == {"styles": []}
    s = {"name": "Horror red", "font": "creepster", "color": "#e3242b", "accent": "#000000", "stroke": 6, "stroke_color": "#000000",
         "shadow": None, "glow": 10, "glow_color": "#ff0000"}
    st, r, _ = c.req("PUT", "/api/text-styles", {"styles": [s]})
    assert st == 200
    st, r, _ = c.req("GET", "/api/text-styles")
    assert r["styles"][0]["name"] == "Horror red" and r["styles"][0]["glow"] == 10
    st, r, _ = c.req("PUT", "/api/text-styles", {"styles": [{**s, "color": "red"}]})
    assert st == 422


def test_text_style_and_font_change_the_picture(tmp_path):
    base = Title(id=new_id(), start=0, duration=3, template="pop_text", text="WOW", x=0.5, y=0.5, anim="none").model_dump()
    plain = titles.ass([base], 640, 360, "DejaVu Sans", None)
    assert "\\fn" not in plain and "\\blur" not in plain                    # nothing set = the template's look
    fonts = fontlib.stage(tmp_path, tmp_path, {"anton", "emoji"})
    styled = {**base, "font": "anton", "stroke": 10, "stroke_color": "#ff0000", "glow": 16, "glow_color": "#00ff00"}
    a = titles.ass([styled], 640, 360, "DejaVu Sans", None, fonts=fonts)
    assert "\\fnAnton\\" in a and "\\b1" not in a.split("[Events]")[1]      # the real font, not fake-bolded
    img = _ass_frame(tmp_path, a, fonts)
    red = (img[:, :, 0] > 150) & (img[:, :, 1] < 90) & (img[:, :, 2] < 90)
    green = (img[:, :, 1] > 90) & (img[:, :, 0] < 90)
    assert red.sum() > 200 and green.sum() > 200                            # red outline, green glow around it
    img_plain = _ass_frame(tmp_path, plain, {})
    white = lambda im: ((im > 200).all(axis=2)).sum()  # noqa: E731
    assert white(img) > 100 and abs(white(img) - white(img_plain)) > 30     # a different font draws differently


def test_sticker_uses_the_emoji_font(tmp_path):
    fonts = fontlib.stage(tmp_path, tmp_path, {"emoji"})
    st = Title(id=new_id(), start=0, duration=3, template="sticker", text="💀", color="#ffde00", x=0.5, y=0.5, anim="none").model_dump()
    a = titles.ass([st], 640, 360, "DejaVu Sans", None, fonts=fonts)
    assert "\\fnNoto Emoji" in a
    img = _ass_frame(tmp_path, a, fonts)
    yellow = (img[:, :, 0] > 180) & (img[:, :, 1] > 160) & (img[:, :, 2] < 90)
    ys, xs = np.nonzero(yellow)
    assert yellow.sum() > 500 and abs(xs.mean() - 320) < 30 and abs(ys.mean() - 180) < 30   # a real glyph, centred


def test_count_cards_are_numbered_and_the_tally_lists_them():
    mk = lambda s, name, how: Title(id=new_id(), start=s, duration=3, template="count_card", text=name, subtext=how).model_dump()  # noqa: E731
    cards = [mk(10, "Steve", "Machete"), mk(2, "Ann", "Axe"), mk(20, "Late", "")]
    tally = Title(id=new_id(), start=15, duration=6, template="tally", text="FINAL COUNT").model_dump()
    a = titles.ass(cards + [tally], 1280, 720, "DejaVu Sans", None)
    assert a.index("}#1\n") < a.index("}Ann")
    ev = a.split("[Events]")[1]
    assert ev.count("}#") == 3 and "}#2\n" in ev and "}#3\n" in ev and "KILL" not in ev
    tl = [ln for ln in ev.splitlines() if "0:00:15.00" in ln]
    body = "\n".join(tl)
    assert "1. Ann" in body and "2. Steve" in body and "Late" not in body     # only the cards before it
    assert "}2\n" in body + "\n" or "}2" in body                              # the total
    # in a render block that doesn't contain the earlier cards, numbering stays the same
    part = titles.ass([cards[0]], 1280, 720, "DejaVu Sans", None, all_titles=cards)
    assert "}#2\n" in part


def test_old_callout_name_still_opens():
    t = Title.model_validate({"id": new_id(), "start": 0, "template": "death_card", "text": "x"})
    assert t.template == "count_card"


def test_number_card_and_new_templates_validate():
    for tpl in ("count_card", "tally", "number_card", "sticker"):
        Title(id=new_id(), start=0, template=tpl, text="x")
    with pytest.raises(ValidationError):
        Title(id=new_id(), start=0, template="number_card", number=1000)
    with pytest.raises(ValidationError):
        Title(id=new_id(), start=0, font="../x")
    a = titles.ass([Title(id=new_id(), start=0, template="number_card", number=7, text="Best trap").model_dump()], 1280, 720, "DejaVu Sans", None)
    assert "}#7" in a and "Best trap" in a


# ---------------------------------------------------------------- counters
def _counter_project(tmp_path):
    s, p, pdir, media = _project(tmp_path, [("blue", 0, {"start": 0, "source_in": 0, "source_out": 6}),
                                            ("blue", 2, {"start": 0, "source_in": 0, "source_out": 6})])
    mid = media["blue"].id
    ctr = Counter(id=new_id(), label="Goals", x=0.5, y=0.5, accent="#ff0000", size=2.0)
    effs = [Effect(id=new_id(), kind="count", media_id=mid, source_time=t, duration=0.5, counter=ctr.id, sound="boom")
            for t in (1.0, 3.0)]
    d = p.model_dump(mode="json")
    d["timeline"]["counters"] = [ctr.model_dump(mode="json")]
    d["effects"] = [e.model_dump(mode="json") for e in effs]
    return s, Project.model_validate(d), pdir, ctr


def test_counter_counts_each_tick_and_skips_cut_ones(tmp_path):
    s, p, pdir, ctr = _counter_project(tmp_path)
    assert overlays.counter_ticks(p) == {ctr.id: [1.0, 3.0]}
    evs = overlays.counter_events(ctr, [1.0, 3.0], 1280, 720, 6.0, None, titles.Measure(None), 9000)
    nums = [(a, b, ln.rsplit("}", 1)[1]) for a, b, ln in evs if "\\an5" in ln]
    assert nums == [(0.0, 1.0, "0"), (1.0, 3.0, "1"), (3.0, 6.0, "2")]
    assert sum("\\fscx160" in ln for _, _, ln in evs) == 2                # each new number pops
    # cut the moment of the second count out of the edit: it doesn't count
    d = p.model_dump(mode="json")
    for tr in d["timeline"]["tracks"]:
        for c in tr["clips"]:
            c["source_out"] = 2.5
    assert overlays.counter_ticks(Project.model_validate(d))[ctr.id] == [1.0]
    with pytest.raises(ValidationError):
        Effect(id=new_id(), kind="count", media_id=new_id(), source_time=0, duration=0.5)    # which counter?
    d = p.model_dump(mode="json")
    d["timeline"]["counters"] *= 2
    with pytest.raises(ValidationError, match="duplicate counter"):
        Project.model_validate(d)


def test_counter_export_shows_the_count_and_plays_its_sound(tmp_path):
    s, p, pdir, ctr = _counter_project(tmp_path)
    out, r = _render(s, p, pdir)
    w, h = 160, 90
    before, after = frame_at(out, 0.5, w, h), frame_at(out, 1.1, w, h)
    # red flash on the new number right after the count
    red = lambda im: ((im[:, :, 0] > 150) & (im[:, :, 1] < 100) & (im[:, :, 2] < 120))[25:70, 50:110].sum()  # noqa: E731
    white = lambda im: ((im > 200).all(axis=2))[25:70, 50:110].sum()  # noqa: E731
    assert white(before) > 5                                              # the 0 is there
    assert red(after) > red(before) + 5
    # the boom is in the sound at 1 s and 3 s
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    lo = lambda a, b: float(np.abs(np.fft.rfft(x[int(a * 8000):int(b * 8000)]))[5:60].mean())  # noqa: E731  (< 120 Hz)
    assert lo(1.0, 1.4) > 3 * lo(0.3, 0.7) and lo(3.0, 3.4) > 3 * lo(0.3, 0.7)


# ---------------------------------------------------------------- audio: narration, bass boost
def _level(path, a, b, f):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)[int(a * 8000):int(b * 8000)]
    spec = np.abs(np.fft.rfft(x)) / len(x)
    freqs = np.fft.rfftfreq(len(x), 1 / 8000)
    return float(spec[(freqs > f - 15) & (freqs < f + 15)].max())


def test_narration_ducks_the_recording_under_it(tmp_path):
    spec = [("red", 0, {"start": 0, "source_in": 0, "source_out": 6}),     # 440 Hz all the way: the "movie"
            ("red", 2, {"start": 0, "source_in": 0, "source_out": 6}),
            ("voice", 3, {"start": 0, "source_in": 0, "source_out": 6})]   # 440? no: voice is 440 too — use music
    s, p, pdir, media = _project(tmp_path, [spec[0], spec[1], ("music", 3, {"start": 0, "source_in": 0, "source_out": 6})],
                                 audio={"normalize": False, "ducking": "strong"})
    d = p.model_dump(mode="json")
    d["timeline"]["tracks"][3]["role"] = "narration"                      # 220 Hz "narration" all through
    nar = Project.model_validate(d)
    plain = Project.model_validate({**d, "timeline": {**d["timeline"], "tracks": [
        {**t, "role": "dialogue"} if i == 3 else t for i, t in enumerate(d["timeline"]["tracks"])]}})
    out_n, r = _render(s, nar, pdir, "nar")
    out_p, _ = _render(s, plain, pdir, "plain")
    movie_n, movie_p = _level(out_n, 2, 5, 440), _level(out_p, 2, 5, 440)
    voice_n, voice_p = _level(out_n, 2, 5, 220), _level(out_p, 2, 5, 220)
    assert movie_n < movie_p * 0.6, (movie_n, movie_p)                   # the movie gets quieter under the narration
    assert voice_n > voice_p * 0.8                                       # the narration doesn't


def test_bass_boost_only_where_it_is(tmp_path):
    s, p, pdir, media = _project(tmp_path, [("music", 0, {"start": 0, "source_in": 0, "source_out": 6}),
                                            ("music", 2, {"start": 0, "source_in": 0, "source_out": 6})],
                                 audio={"normalize": False, "ducking": "off"},
                                 effects=[])
    d = p.model_dump(mode="json")
    d["effects"] = [Effect(id=new_id(), kind="bass", media_id=media["music"].id, source_time=2.0, duration=2.0,
                           intensity=1.0).model_dump(mode="json")]
    out, _ = _render(s, Project.model_validate(d), pdir, "bass")
    inside, outside = _level(out, 2.3, 3.7, 220), _level(out, 0.3, 1.7, 220)
    assert inside > outside * 1.6, (inside, outside)
    assert _level(out, 4.3, 5.7, 220) < inside * 0.7                    # back to normal after


# ---------------------------------------------------------------- looks
@pytest.mark.parametrize("look", ["horror", "vhs", "film", "vignette", "letterbox"])
def test_new_looks_render(tmp_path, look):
    out = tmp_path / f"{look}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x808080:s=320x180:d=0.2",
                    "-vf", ",".join(["format=yuv420p", *LOOK_FILTERS[look]]), "-frames:v", "1", str(out)], check=True)
    img = frame_at(out, 0, 320, 180)
    if look == "letterbox":
        assert img[5, 160].max() < 20 and img[175, 160].max() < 20 and img[90, 160].min() > 100
    if look in ("vignette", "horror", "film"):
        assert img[5, 5].mean() < img[90, 160].mean() - 15                 # darker corners


# ---------------------------------------------------------------- talking + funny moments
def test_talk_intervals_from_loudness():
    db = np.full(400, -70.0)                                               # 20 s of quiet
    db[40:80] = -20                                                        # 2-4 s talking
    db[82:90] = -20                                                        # a 0.1 s pause: bridged
    db[200:202] = -20                                                      # a 0.1 s blip: dropped
    iv = reactions.talk_intervals(db)
    assert iv == [[2.0, 4.5]]


def _voice_file(path: Path, secs: int, loud_at: list[tuple[float, float]]):
    """'Talking' (syllable-like bursts at a normal level) all through, much louder at loud_at."""
    loud = "+".join(f"between(t,{a},{b})" for a, b in loud_at) or "0"
    expr = f"(0.08+0.6*({loud}))*sin(2*PI*300*t)*(0.5+0.5*sin(2*PI*4*t))"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s=160x90:r=25:d={secs}",
                    "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={secs}", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)


def test_funny_moments_find_the_loud_reactions_with_the_build_up(server, tmp_path):
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "session"})
    pid = p["id"]
    ids = []
    for name, loud in (("me.mp4", [(20, 23), (45, 46)]), ("friend.mp4", [(20.5, 24)])):
        _voice_file(tmp_path / name, 60, loud)
        st, r, _ = c.upload(pid, tmp_path / name)
        c.wait_job(r["job_id"])
        ids.append(r["media"]["id"])
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    tl = p["timeline"]
    clip = lambda m: {"id": new_id(), "media_id": m, "start": 0, "source_in": 0, "source_out": 60}  # noqa: E731
    tl["tracks"][0]["clips"] = [clip(ids[0])]
    tl["tracks"][2]["clips"] = [clip(ids[0])]
    tl["tracks"].append({"id": new_id(), "kind": "audio", "name": "A3", "clips": [clip(ids[1])]})
    st, r, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": tl,
                                                             "output": p["output"]})
    assert st == 200, r
    st, r, _ = c.req("GET", f"/api/projects/{pid}/moments")
    assert st == 200, r
    ms = r["moments"]
    assert len(ms) == 2, ms
    big, small = ms
    assert 15 <= big["start"] <= 17 and 24 <= big["end"] <= 26 and big["score"] == 100 and big["people"] == 2
    assert 40 <= small["start"] <= 42 and small["score"] < big["score"]
    st, r, _ = c.req("GET", f"/api/projects/{pid}/media/{ids[1]}/talk")
    assert st == 200 and r["talk"] and r["talk"][0][0] < 1.0                 # talking from the start


def test_name_tags_light_up_whoever_talks(tmp_path):
    s, p, pdir, media = _project(tmp_path, [("blue", 0, {"start": 0, "source_in": 0, "source_out": 6}),
                                            ("voice", 2, {"start": 0, "source_in": 0, "source_out": 6})])
    d = p.model_dump(mode="json")
    d["timeline"]["tracks"][2]["tag"] = "Riley"
    d["timeline"]["tracks"][2]["tag_color"] = "#ff0000"
    d["timeline"]["name_tags"] = {"enabled": True, "corner": "tl", "size": 2.0, "only_talking": False}
    p = Project.model_validate(d)
    talk = reactions.track_talk(p, s, pdir, p.timeline.tracks[2])
    assert len(talk) == 2 and abs(talk[0][0]) < 0.2 and abs(talk[0][1] - 2) < 0.2 and abs(talk[1][0] - 4) < 0.2
    out, _ = _render(s, p, pdir, "tags")
    red = lambda im: ((im[:, :, 0] > 170) & (im[:, :, 1] < 80))[:25, :60].sum()  # noqa: E731
    assert red(frame_at(out, 1.0, 160, 90)) > 10 and red(frame_at(out, 3.0, 160, 90)) < 3   # lit while talking


# ---------------------------------------------------------------- schema
def test_old_projects_upgrade_to_v7():
    d = migrate({"schema_version": 6, "id": new_id(), "name": "x"})
    p = Project.model_validate(d)
    assert p.schema_version == 7 and p.timeline.counters == [] and not p.timeline.name_tags.enabled
    assert p.captions.font is None
