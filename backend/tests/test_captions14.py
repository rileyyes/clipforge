"""Phase 14: the preview's captions match the export's (shared vectors) and fixed words."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).parent / "data"


def test_caption_vectors_still_match_the_backend(tmp_path):
    """Regenerating the shared vectors from today's backend gives the same file."""
    before = (DATA / "caption_vectors.json").read_text(encoding="utf-8")
    try:
        subprocess.run([sys.executable, str(DATA / "make_caption_vectors.py")], cwd=Path(__file__).parents[1], check=True,
                       capture_output=True)
        after = (DATA / "caption_vectors.json").read_text(encoding="utf-8")
        a, b = json.loads(before), json.loads(after)
        assert [c["expect"] for c in a] == [c["expect"] for c in b]
    finally:
        (DATA / "caption_vectors.json").write_text(before, encoding="utf-8")


def test_mask_word():
    from app.effects import mask_word
    assert mask_word("shit") == "s***" and mask_word("don't") == "d**'*" and mask_word("a") == "*" and mask_word("CAFÉ") == "C***"


def _project_with_transcript(c, tmp_path):
    from app.storage import new_id
    v = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=25:d=6", "-f", "lavfi",
                    "-i", "sine=f=220:d=6", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(v)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "Captions"})
    pid = p["id"]
    st, r, _ = c.upload(pid, v)
    mid = r["media"]["id"]
    c.wait_job(r["job_id"])
    words = [{"text": " Welcome", "start": 0.2, "end": 0.6, "p": 0.9}, {"text": " to", "start": 0.65, "end": 0.75, "p": 0.9},
             {"text": " click", "start": 0.8, "end": 1.1, "p": 0.4}, {"text": " forge.", "start": 1.15, "end": 1.5, "p": 0.5}]
    (c.settings.projects_dir / pid / "analysis").mkdir(exist_ok=True)
    (c.settings.projects_dir / pid / "analysis" / f"{mid}.json").write_text(json.dumps(
        {"version": 1, "media_id": mid, "duration": 6.0, "hop": 0.05, "rms_db": [], "motion": [], "cuts": [], "words": words}))
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    link = new_id()
    for ti in (0, 2):
        p["timeline"]["tracks"][ti]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 6, "link_id": link}]
    st, _r, _ = c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                                              "output": p["output"], "captions": {"enabled": True}})
    assert st == 200
    return pid, mid


def test_fix_a_misheard_word(server, tmp_path):
    c = server
    pid, mid = _project_with_transcript(c, tmp_path)
    st, r, _ = c.req("POST", f"/api/projects/{pid}/words/fix", {"media_id": mid, "start": 0.8, "text": " ClipForge "})
    assert st == 200 and r["word"]["text"] == " ClipForge" and r["word"]["old"] == " click"
    _, w, _ = c.req("GET", f"/api/projects/{pid}/words")
    assert [x["text"] for x in w["media"][mid]] == [" Welcome", " to", " ClipForge", " forge."]
    assert w["media"][mid][2]["fixed"] is True and "fixed" not in w["media"][mid][0]
    assert w["media"][mid][2]["start"] == 0.8 and w["media"][mid][2]["end"] == 1.1      # timing unchanged
    st, srt, _ = c.req("GET", f"/api/projects/{pid}/captions.srt")
    assert st == 200 and b"CLIPFORGE FORGE." in srt and b"CLICK" not in srt
    # a tiny rounding difference in the start time still finds the word
    assert c.req("POST", f"/api/projects/{pid}/words/fix", {"media_id": mid, "start": 1.1505, "text": "Forge."})[0] == 200


def test_fix_word_refusals(server, tmp_path):
    from app.storage import new_id
    c = server
    pid, mid = _project_with_transcript(c, tmp_path)
    fix = lambda body: c.req("POST", f"/api/projects/{pid}/words/fix", body)  # noqa: E731
    assert fix({"media_id": mid, "start": 3.0, "text": "x"})[0] == 404                       # no word there
    assert fix({"media_id": new_id(), "start": 0.2, "text": "x"})[0] == 404                  # unknown media
    for bad in ("", "   ", "two\nlines", "x" * 61, "tab\there"):
        assert fix({"media_id": mid, "start": 0.2, "text": bad})[0] == 422, bad
    assert fix({"media_id": mid, "start": 0.2, "text": "ok", "extra": 1})[0] == 422
    assert fix({"media_id": "../etc", "start": 0.2, "text": "ok"})[0] == 422
    # nothing changed
    _, w, _ = c.req("GET", f"/api/projects/{pid}/words")
    assert w["media"][mid][0]["text"] == " Welcome"
