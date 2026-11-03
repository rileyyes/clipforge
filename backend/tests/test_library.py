"""My library: your own recorded/imported sounds and images, used in edits."""
from __future__ import annotations

import subprocess

import numpy as np
import pytest

from app.config import Settings
from app.library import Library, LibraryError, wav_duration
from app.render import render_project
from app.storage import new_id

from test_effects import Ctx, _pcm, _project, _share


def _recording(path, *, lead=0.8, tone=1.2, tail=0.7, freq=1500, amp=0.25):
    """A mic-recording-like file: silence, a tone, silence (Opus in WebM like Chrome's MediaRecorder)."""
    d = lead + tone + tail
    fmt = path.suffix[1:]
    codec = {"webm": ["-c:a", "libopus"], "ogg": ["-c:a", "libvorbis"], "mp3": ["-c:a", "libmp3lame"],
             "wav": ["-c:a", "pcm_s16le"]}[fmt]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{amp}*sin(2*PI*{freq}*t)*between(t,{lead},{lead + tone})':s=48000:d={d}",
                    *codec, str(path)], check=True)
    return path.read_bytes()


def _peak_db(path):
    x = _pcm(path)
    return 20 * np.log10(np.abs(x).max() + 1e-12)


@pytest.fixture()
def lib(tmp_path):
    return Library(Settings(workspace=tmp_path / "ws"))


def test_recorded_sound_is_trimmed_and_levelled(lib, tmp_path):
    item = lib.add_sound(_recording(tmp_path / "r.webm"), "my laugh.webm", recorded=True)
    assert item.name == "my laugh" and item.source == "recorded"
    f = lib.file("sound", item.id)
    assert 1.1 < item.duration < 1.45 and abs(wav_duration(f) - item.duration) < 0.01  # silence gone
    assert -1.6 < _peak_db(f) < -0.4  # quiet mic level raised to -1 dBFS
    assert [s["id"] for s in lib.list()["sounds"]] == [item.id]


@pytest.mark.parametrize("fmt", ["ogg", "mp3", "wav"])
def test_imported_sound_formats(lib, tmp_path, fmt):
    item = lib.add_sound(_recording(tmp_path / f"x.{fmt}", lead=0, tail=0), f"x.{fmt}", recorded=False)
    assert item.source == "imported" and item.duration > 1.0


def test_long_sounds_are_capped_at_30s(lib, tmp_path):
    item = lib.add_sound(_recording(tmp_path / "l.ogg", lead=0, tone=40, tail=0), "long", False)
    assert 29.9 <= item.duration <= 30.01


def test_silent_and_garbage_uploads_rejected(lib, tmp_path):
    with pytest.raises(LibraryError, match="no audible sound"):
        lib.add_sound(_recording(tmp_path / "s.webm", amp=0), "silence", True)
    with pytest.raises(LibraryError, match="readable"):
        lib.add_sound(b"<html>not audio</html>" * 50, "evil", False)
    with pytest.raises(LibraryError):
        lib.add_sound(b"", "empty", False)
    assert lib.list()["sounds"] == []


def test_images_are_reencoded_and_downscaled(lib, tmp_path):
    import cv2
    ok, png = cv2.imencode(".jpg", np.full((3000, 1500, 3), 200, np.uint8))
    item = lib.add_image(png.tobytes(), "Reaction face.jpg")
    assert item.name == "Reaction face" and (item.width, item.height) == (1000, 2000)
    assert lib.file("image", item.id).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(LibraryError):
        lib.add_image(b"<svg onload=alert(1)>", "x.svg")


def test_rename_delete_and_paths(lib, tmp_path):
    item = lib.add_sound(_recording(tmp_path / "r.webm"), "a", True)
    assert lib.rename("sound", item.id, "  Bruh  ").name == "Bruh"
    with pytest.raises(Exception):
        lib.file("sound", "../../etc/passwd")
    lib.delete("sound", item.id)
    assert lib.list()["sounds"] == []
    with pytest.raises(KeyError):
        lib.delete("sound", item.id)


# ---------------------------------------------------------------- in edits
def _with_custom(tmp_path, kind, source_time, duration, lib_root=None, copy=True):
    s, p, pdir = _project(tmp_path)
    lib = Library(s)
    item = lib.add_sound(_recording(tmp_path / "mine.webm", lead=0.3, tone=2.5, tail=0.2), "mine", True)
    if copy:
        lib.copy_into_project("sound", item.id, pdir)
    d = p.model_dump(mode="json")
    d["effects"] = [{"id": new_id(), "media_id": "a" * 32, "kind": kind, "source_time": source_time,
                     "duration": duration, "sound": "custom", "sound_asset": item.id, "volume": 1.0}]
    return s, type(p).model_validate(d), pdir, lib, item


def test_custom_bleep_replaces_the_word(tmp_path):
    s, p, pdir, _lib, _item = _with_custom(tmp_path, "censor", 1.0, 0.5)
    r = render_project(Ctx(), s, p, pdir, "c", "draft", "libx264")
    assert r["validation"]["ok"], r["validation"]
    x = _pcm(pdir / "exports" / r["file"])
    assert _share(x, 1.05, 1.45, 440)[0] < 0.02           # original word gone
    assert _share(x, 1.05, 1.45, 1500)[0] > 0.9           # your sound instead
    assert _share(x, 2.0, 2.5, 1500)[0] < 0.05            # cut to the word: doesn't run on
    assert _share(x, 0.2, 0.8, 440)[0] > 0.9


def test_custom_sound_effect_plays_its_natural_length(tmp_path):
    s, p, pdir, _lib, item = _with_custom(tmp_path, "sfx", 2.0, 2.5)
    r = render_project(Ctx(), s, p, pdir, "s", "draft", "libx264")
    x = _pcm(pdir / "exports" / r["file"])
    assert _share(x, 2.2, 4.2, 1500)[0] > 0.5 and _share(x, 2.2, 4.2, 440)[0] > 0.05  # mixed over speech
    assert _share(x, 4.9, 5.5, 1500)[0] < 0.05  # and stops after its length


def test_project_keeps_working_after_library_delete_and_reports_missing(tmp_path):
    s, p, pdir, lib, item = _with_custom(tmp_path, "censor", 1.0, 0.5)
    lib.delete("sound", item.id)  # project has its own copy
    r = render_project(Ctx(), s, p, pdir, "c", "draft", "libx264")
    assert "missing_sounds" not in r["validation"]
    assert _share(_pcm(pdir / "exports" / r["file"]), 1.05, 1.45, 1500)[0] > 0.9
    (pdir / "fx" / "sounds" / f"{item.id}.wav").unlink()  # copy lost too: export still works, says so
    r = render_project(Ctx(), s, p, pdir, "c2", "draft", "libx264")
    assert r["validation"]["ok"] and r["validation"]["missing_sounds"] == 1


def test_custom_sound_requires_an_asset():
    from app.schema import Effect
    with pytest.raises(Exception, match="custom sound needs"):
        Effect(id=new_id(), kind="sfx", media_id="a" * 32, source_time=0, duration=1, sound="custom")


# ---------------------------------------------------------------- API
def test_api_library_flow(server, tmp_path):
    c = server
    rec = _recording(tmp_path / "r.webm")
    st, item, _ = c.req("POST", "/api/library/sounds?name=Bruh&recorded=1", raw=rec)
    assert st == 201 and item["name"] == "Bruh" and item["source"] == "recorded"
    assert c.req("POST", "/api/library/sounds?name=x", raw=rec, csrf=False)[0] == 403
    assert c.req("POST", "/api/library/sounds", raw=b"nope" * 100)[0] == 415
    assert c.req("POST", "/api/library/videos", raw=rec)[0] == 404
    st, wav, h = c.req("GET", f"/api/library/sounds/{item['id']}")
    assert st == 200 and wav[:4] == b"RIFF" and h["content-type"] == "audio/wav"
    assert c.req("GET", "/api/library/sounds/..%2F..%2Fsecret")[0] == 404
    import cv2
    ok, png = cv2.imencode(".png", np.full((50, 80, 3), 30, np.uint8))
    st, img, _ = c.req("POST", "/api/library/images?name=Face", raw=png.tobytes())
    assert st == 201 and img["width"] == 80
    _, lst, _ = c.req("GET", "/api/library")
    assert [x["name"] for x in lst["sounds"]] == ["Bruh"] and [x["name"] for x in lst["images"]] == ["Face"]
    assert c.req("PUT", f"/api/library/sounds/{item['id']}", {"name": "Big bruh"})[1]["name"] == "Big bruh"
    # use in a project
    _, p, _ = c.req("POST", "/api/projects", {"name": "lib"})
    pid = p["id"]
    st, used, _ = c.req("POST", f"/api/projects/{pid}/fx/library", {"kind": "sound", "id": item["id"]})
    assert st == 200 and used["id"] == item["id"]
    assert c.req("GET", f"/api/projects/{pid}/fx/sounds/{item['id']}")[0] == 200
    assert c.req("POST", f"/api/projects/{pid}/fx/library", {"kind": "image", "id": img["id"]})[0] == 200
    assert c.req("GET", f"/api/projects/{pid}/fx/images/{img['id']}")[0] == 200  # usable as a pop-up image
    assert c.req("POST", f"/api/projects/{pid}/fx/library", {"kind": "sound", "id": "0" * 32})[0] == 404
    assert c.req("DELETE", f"/api/library/sounds/{item['id']}")[0] == 204
    assert c.req("GET", f"/api/projects/{pid}/fx/sounds/{item['id']}")[0] == 200  # project copy stays
    _, lst, _ = c.req("GET", "/api/library")
    assert lst["sounds"] == []


def test_duplicated_project_keeps_sounds_images_and_transcript(tmp_path):
    """Found while adding the library: duplicates lost fx assets and transcripts."""
    from app.projects import ProjectStore
    s, p, pdir, lib, item = _with_custom(tmp_path, "censor", 1.0, 0.5)
    st = ProjectStore(s.projects_dir)
    (pdir / "project.json").write_text(p.model_dump_json())
    (pdir / "fx" / ("b" * 32 + ".png")).write_bytes(b"\x89PNG fake")
    dup = st.duplicate(p.id)
    ddir = st.dir(dup.id)
    assert (ddir / "fx" / "sounds" / f"{item.id}.wav").is_file()
    assert (ddir / "fx" / ("b" * 32 + ".png")).is_file()
    assert (ddir / "analysis" / ("a" * 32 + ".json")).is_file()
    r = render_project(Ctx(), s, st.load(dup.id), ddir, "d", "draft", "libx264")
    assert r["validation"]["ok"] and "missing_sounds" not in r["validation"]
