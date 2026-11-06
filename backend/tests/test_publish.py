"""Phase 8.3: chapters, titles, description, tags from the final edit."""
from __future__ import annotations

import json
import subprocess

import pytest

from app import publish as PB
from app.storage import new_id

TOPICS = [
    "minecraft creeper exploded my diamond house minecraft creeper sword armor diamond",
    "pasta recipe tomato sauce garlic basil pasta boil water tomato garlic recipe",
    "car engine oil change wrench engine tires garage car oil wrench tires",
]


def transcript(seconds_per_topic=70, extra=""):
    words, t = [], 0.0
    for k, topic in enumerate(TOPICS):
        toks = topic.split()
        end = (k + 1) * seconds_per_topic
        i = 0
        while t < end - 0.5:
            w = toks[i % len(toks)]
            i += 1
            if i % 9 == 0:
                w += "."
            words.append({"start": round(t, 2), "end": round(t + 0.3, 2), "text": " " + w, "p": 0.9})
            t += 0.5 if i % 9 else 1.6  # pause after each sentence
    if extra:
        for j, w in enumerate(extra.split()):
            words.append({"start": t + j * 0.4, "end": t + j * 0.4 + 0.3, "text": " " + w, "p": 0.9})
    return words, (len(TOPICS) * seconds_per_topic)


def test_chapters_find_the_topics_and_follow_youtube_rules():
    words, dur = transcript()
    ch = PB.chapters(words, dur)
    assert len(ch) >= 3 and ch[0]["t"] == 0
    assert PB.validate_chapters(ch, dur) == []
    # boundaries land near the real topic changes (70 s, 140 s)
    starts = [c["t"] for c in ch[1:]]
    assert any(abs(s - 70) <= 12 for s in starts) and any(abs(s - 140) <= 12 for s in starts), ch
    names = " ".join(c["title"].lower() for c in ch)
    assert "pasta" in names or "tomato" in names or "garlic" in names
    assert "engine" in names or "oil" in names or "car" in names or "wrench" in names


def test_chapter_rules():
    assert PB.validate_chapters([{"t": 5, "title": "a"}, {"t": 20, "title": "b"}], 100) == [
        "The first chapter must start at 0:00.", "YouTube needs at least 3 chapters."]
    assert "shorter than 10 seconds" in PB.validate_chapters(
        [{"t": 0, "title": "a"}, {"t": 5, "title": "b"}, {"t": 30, "title": "c"}], 60)[0]
    assert PB.chapters(transcript()[0][:30], 40) == []  # too short for chapters


def test_titles_tags_description_and_no_swears():
    words, dur = transcript(extra="this is so fucking cool! what just happened? you shit")
    r = PB.suggest(words, dur + 10, "my_minecraft_video.mp4")
    blob = json.dumps(r).lower()
    assert "fuck" not in blob and "shit" not in blob
    assert "What just happened?" in r["titles"] and "My minecraft video" in r["titles"]
    assert all(len(t) <= 100 for t in r["titles"])
    assert sum(len(t) + (3 if " " in t else 1) for t in r["tags"]) <= 500 and "minecraft" in r["tags"]
    assert "Chapters\n0:00 " in r["description"] and r["hashtags"][0].startswith("#")
    assert PB.fmt_ts(3725) == "1:02:05" and PB.fmt_ts(65) == "1:05"


def test_no_transcript_is_honest():
    r = PB.suggest([], 300, "Gaming night")
    assert r["chapters"] == [] and r["titles"] == ["Gaming night"] and "Transcribe" in r["warnings"][0]


class FakeModel:
    model = "fake"

    def chat_json(self, system, user, cancel=None):
        n = user.count("Chapter ")
        return {"titles": ["Creeper Blew Up My House!", "Damn fucking creepers", "Best pasta ever"],
                "description": "I lose my house, cook pasta, then fix my car.",
                "chapter_titles": [f"Part {i}" for i in range(1, n + 1)], "tags": ["minecraft", "creeper", "shit"]}


def test_ai_polish_replaces_text_but_filters_swears_and_keeps_chapter_times():
    words, dur = transcript()
    base = PB.suggest(words, dur, "x")
    r = PB.ai_polish(FakeModel(), words, base)
    assert r["source"] == "ai" and r["titles"][:2] == ["Creeper Blew Up My House!", "Best pasta ever"]
    assert [c["t"] for c in r["chapters"]] == [c["t"] for c in base["chapters"]]
    assert r["chapters"][1]["title"] == "Part 2"
    assert "shit" not in r["tags"] and r["description"].startswith("I lose my house")


def test_draft_validation():
    with pytest.raises(Exception):
        PB.PublishDraft(tags=["x" * 29] * 20)  # > 500 characters
    with pytest.raises(Exception):
        PB.PublishDraft(title="<script>")
    with pytest.raises(Exception):
        PB.PublishDraft(privacy="everyone")
    assert PB.PublishDraft().privacy == "private"  # never public by default


def test_api_publish_flow(server, tmp_path):
    c = server
    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=25:d=210", "-f", "lavfi",
                    "-i", "sine=f=200:d=210", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(vid)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "Weekend vlog"})
    pid = p["id"]
    mid = c.upload(pid, vid)[1]["media"]["id"]
    _, job, _ = c.req("POST", f"/api/projects/{pid}/autoedit/analyze", {"media_id": mid, "transcribe": False})
    c.wait_job(job["id"])
    af = c.settings.projects_dir / pid / "analysis" / f"{mid}.json"
    a = json.loads(af.read_bytes())
    a["words"] = transcript()[0]
    af.write_text(json.dumps(a), encoding="utf-8")
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    link = new_id()
    # the edit keeps only the first 150 s: the car chapter is mostly cut
    p["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 150, "link_id": link}]
    p["timeline"]["tracks"][2]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 150, "link_id": link}]
    c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"], "output": p["output"]})
    st, r, _ = c.req("POST", f"/api/projects/{pid}/publish/suggest", {})
    assert st == 200 and r["source"] == "rules" and r["chapter_problems"] == [] and len(r["chapters"]) >= 2
    assert r["chapters"][-1]["t"] < 150 and "Weekend vlog" in r["titles"]
    st, r2, _ = c.req("POST", f"/api/projects/{pid}/publish/suggest", {"use_ai": True})
    assert st in (200, 409)  # 409 unless a local AI happens to be running
    _, d, _ = c.req("GET", f"/api/projects/{pid}/publish")
    assert d["draft"]["privacy"] == "private" and d["categories"]["20"] == "Gaming"
    body = {**d["draft"], "title": r["titles"][0], "description": r["description"], "tags": r["tags"][:5],
            "chapters": r["chapters"], "category_id": "20"}
    st, saved, _ = c.req("PUT", f"/api/projects/{pid}/publish", body)
    assert st == 200 and saved["draft"]["category_id"] == "20" and saved["chapter_problems"] == []
    assert c.req("GET", f"/api/projects/{pid}/publish")[1]["draft"]["title"] == r["titles"][0]
    assert c.req("PUT", f"/api/projects/{pid}/publish", {**body, "privacy": "secret"})[0] == 422
    assert c.req("PUT", f"/api/projects/{pid}/publish", {**body, "extra": 1})[0] == 422


# ---------------------------------------------------------------- Phase 12: chapters from markers
def test_marker_chapters_follow_youtube_rules():
    m = lambda t, label="": {"id": new_id(), "t": t, "label": label}
    ch = PB.marker_chapters([m(95, "Boss fight"), m(30, "Gameplay"), m(30.2, ""), m(299.8, "too late")], 300)
    assert ch == [{"t": 0.0, "title": "Intro"}, {"t": 30.0, "title": "Gameplay"}, {"t": 95.0, "title": "Boss fight"}]
    assert PB.validate_chapters(ch, 300) == []
    # a marker at (nearly) 0 becomes the first chapter; unnamed ones are numbered
    ch = PB.marker_chapters([m(0.3), m(40), m(80, "End")], 120)
    assert ch == [{"t": 0.0, "title": "Intro"}, {"t": 40.0, "title": "Part 2"}, {"t": 80.0, "title": "End"}]
    # too close together: still returned, and the problem is reported
    ch = PB.marker_chapters([m(5, "A"), m(9, "B")], 60)
    assert any("shorter than 10 seconds" in p for p in PB.validate_chapters(ch, 60))
    assert PB.marker_chapters([], 60) == [] and PB.marker_chapters([m(70)], 60) == []


def test_marker_chapters_without_transcript_and_ai_keeps_names():
    markers = [{"id": new_id(), "t": t, "label": l} for t, l in ((0, "Hello"), (20, "Build"), (50, "Fight"))]
    out = PB.suggest([], 90, "My video", markers)
    assert out["chapters_from"] == "markers" and [c["title"] for c in out["chapters"]] == ["Hello", "Build", "Fight"]
    assert "0:00 Hello" in out["description"] and "0:50 Fight" in out["description"]

    class Model:
        model = "fake"
        def chat_json(self, *a, **k):
            return {"titles": ["A great title"], "description": "Nice.", "chapter_titles": ["x", "y", "z"], "tags": ["t"]}
    words, _ = transcript()
    pol = PB.ai_polish(Model(), words, out)
    assert [c["title"] for c in pol["chapters"]] == ["Hello", "Build", "Fight"]


def test_markers_schema_and_migration():
    from app.schema import SCHEMA_VERSION, Marker, migrate
    from pydantic import ValidationError
    assert SCHEMA_VERSION >= 6
    Marker(id=new_id(), t=12.5, label="Intro", color="#00ff00")
    for bad in ({"t": -1}, {"t": 1, "color": "red"}, {"t": 1, "label": "x" * 101}, {"t": 1, "extra": 1}):
        with pytest.raises(ValidationError):
            Marker(id=new_id(), **bad)
    assert migrate({"schema_version": 5})["schema_version"] == SCHEMA_VERSION


def test_api_chapters_from_markers(server, tmp_path):
    c = server
    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=25:d=90", "-f", "lavfi",
                    "-i", "sine=f=200:d=90", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(vid)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "Markers"})
    pid = p["id"]
    mid = c.upload(pid, vid)[1]["media"]["id"]
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    p["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 90}]
    save = lambda: c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"], "output": p["output"]})
    st, _r, _ = save()
    assert st == 200
    st, r, _ = c.req("POST", f"/api/projects/{pid}/publish/suggest", {"chapters": "markers"})
    assert st == 409 and "markers" in r["error"]
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    p["timeline"]["markers"] = [{"id": new_id(), "t": 25, "label": "Part one"}, {"id": new_id(), "t": 60, "label": "Part two", "color": "#4cc9f0"}]
    st, _r, _ = save()
    assert st == 200
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    assert [m["label"] for m in p["timeline"]["markers"]] == ["Part one", "Part two"] and p["timeline"]["markers"][0]["color"] == "#ffb703"
    st, r, _ = c.req("POST", f"/api/projects/{pid}/publish/suggest", {"chapters": "markers"})
    assert st == 200 and r["chapters_from"] == "markers" and r["chapter_problems"] == []
    assert [x["title"] for x in r["chapters"]] == ["Intro", "Part one", "Part two"]
    assert c.req("POST", f"/api/projects/{pid}/publish/suggest", {"chapters": "nope"})[0] == 422
    p["timeline"]["markers"] = [{"id": new_id(), "t": 5, "label": "bad", "color": "javascript:1"}]
    assert save()[0] == 422
