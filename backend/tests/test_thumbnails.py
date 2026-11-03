"""Thumbnail Maker tests: timeline-aware frames, storage/versions, director, export
validation, provider contract tests (fake servers), and the API workflow."""
from __future__ import annotations

import base64
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from app import thumb_providers as tp
from app.config import Settings
from app.media import build_asset
from app.projects import ProjectStore
from app.schema import Project
from app.storage import new_id
from app.thumb_analysis import (coverage_similarity, fingerprint, get_frame, render_frame, staleness,
                                summarize, timeline_coverage)
from app.thumb_api import validate_thumbnail
from app.thumb_director import build_concepts, build_design, headlines, needs_context, refine
from app.thumb_models import Concept, Design, ThumbContext
from app.thumb_store import AssetError, ThumbStore, decode_image


def color_clip(path: Path, color: str, d=6, size="640x360"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=30:d={d}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture()
def proj(tmp_path):
    s = Settings(workspace=tmp_path)
    store = ProjectStore(tmp_path / "projects")
    p = store.create("t")
    orig = store.dir(p.id) / "media" / "original"
    red = build_asset(s, "a" * 32, color_clip(orig / ("a" * 32 + ".mp4"), "red"), "red.mp4")
    blue = build_asset(s, "b" * 32, color_clip(orig / ("b" * 32 + ".mp4"), "blue"), "blue.mp4")
    d = p.model_dump(mode="json")
    d["media"] = [red.model_dump(mode="json"), blue.model_dump(mode="json")]
    v1, v2 = d["timeline"]["tracks"][0], d["timeline"]["tracks"][1]
    v1["clips"] = [{"id": "1" * 32, "media_id": "a" * 32, "start": 0, "source_in": 2, "source_out": 4},
                   {"id": "2" * 32, "media_id": "b" * 32, "start": 2, "source_in": 0, "source_out": 3}]
    v2["clips"] = [{"id": "3" * 32, "media_id": "b" * 32, "start": 0.5, "source_in": 0, "source_out": 1,
                    "transform": {"scale": 0.25, "x": 400, "y": -200}}]
    return s, store, Project.model_validate(d), store.dir(p.id)


def color_at(img, x, y):
    b, g, r = (int(v) for v in img[y, x])
    return "red" if r > 200 and b < 60 else "blue" if b > 200 and r < 60 else (r, g, b)


# ---------------------------------------------------------------- timeline awareness
def test_frames_follow_the_final_edit(proj):
    s, _, p, pdir = proj
    a = render_frame(s, p, pdir, 0.2)    # V1 red only
    b = render_frame(s, p, pdir, 1.0)    # red base + blue picture-in-picture top-right
    c = render_frame(s, p, pdir, 3.0)    # second clip (blue)
    assert a.shape == (720, 1280, 3)
    assert color_at(a, 640, 360) == "red" and color_at(a, 1040, 160) == "red"
    assert color_at(b, 640, 360) == "red" and color_at(b, 1040, 160) == "blue"
    assert color_at(c, 640, 360) == "blue"


def test_hidden_track_is_ignored(proj):
    s, _, p, pdir = proj
    p.timeline.tracks[1].hidden = True
    assert color_at(render_frame(s, p, pdir, 1.0), 1040, 160) == "red"


def test_vertical_output_keeps_aspect(proj):
    s, _, p, pdir = proj
    p.output.width, p.output.height = 1080, 1920
    img = render_frame(s, p, pdir, 0.2)
    assert img.shape[1] < img.shape[0]


def test_frames_are_cached(proj):
    s, _, p, pdir = proj
    st = ThumbStore(pdir)
    a = get_frame(s, p, pdir, st, 1.0)
    b = get_frame(s, p, pdir, st, 1.0)
    assert a["id"] == b["id"]
    assert len(st.list_assets("frame")) == 1


def test_fingerprint_coverage_and_staleness(proj):
    _, _, p, _ = proj
    fp, cov = fingerprint(p), timeline_coverage(p)
    assert staleness(p, fp, cov)["state"] == "current"
    p.timeline.tracks[0].clips[1].source_out = 2.9  # tiny trim
    st = staleness(p, fp, cov)
    assert st["state"] == "minor"
    p.timeline.tracks[0].clips = p.timeline.tracks[0].clips[:1]
    p.timeline.tracks[1].clips = []
    assert staleness(p, fp, cov)["state"] == "changed"
    assert coverage_similarity([("m", 0, 10)], [("m", 5, 15)]) == pytest.approx(5 / 15)


def test_summary_is_honest_about_unknowns(proj):
    s, _, p, pdir = proj
    r = summarize(s, p, pdir, ThumbStore(pdir))
    assert r["final_duration"] == 5.0 and r["confidence"] == "low"
    assert any("transcript" in u for u in r["unknowns"])
    assert all(m["frame_asset"] for m in r["moments"])
    assert all(0 <= m["time"] < 5 for m in r["moments"])


def test_empty_timeline_refused(proj):
    s, _, p, pdir = proj
    for t in p.timeline.tracks:
        t.clips = []
    with pytest.raises(ValueError, match="empty"):
        summarize(s, p, pdir, ThumbStore(pdir))


# ---------------------------------------------------------------- storage
def _design(**kw) -> Design:
    return Design.model_validate({"id": new_id(), "name": "D", "layers": [
        {"type": "text", "id": new_id(), "x": 10, "y": 10, "w": 300, "h": 120, "text": "HELLO"}], **kw})


def test_versions_are_immutable_and_restorable(tmp_path):
    st = ThumbStore(tmp_path)
    d = _design()
    st.create(d)
    v1 = st.save_version(d.id, "first")
    d2 = d.model_copy(deep=True)
    d2.layers[0].text = "CHANGED"
    st.save_draft(d2)
    doc = st.get(d.id)
    assert doc["draft"]["layers"][0]["text"] == "CHANGED"
    assert doc["versions"][0]["design"]["layers"][0]["text"] == "HELLO"  # draft save never touches versions
    st.rename_version(d.id, v1["id"], "renamed")
    st.restore_version(d.id, v1["id"])
    doc = st.get(d.id)
    assert doc["draft"]["layers"][0]["text"] == "HELLO" and doc["versions"][0]["label"] == "renamed"
    dup = st.duplicate(d.id)
    assert dup["draft"]["id"] != d.id and len(st.list()) == 2
    st.delete(d.id)
    assert len(st.list()) == 1


def test_design_validation():
    with pytest.raises(Exception):
        Design.model_validate({"id": new_id(), "width": 1920, "height": 1080})
    with pytest.raises(Exception):
        _design().model_validate({"id": new_id(), "layers": [
            {"type": "text", "id": "x" * 32, "x": 0, "y": 0, "w": 1, "h": 1, "text": "a"}]})
    with pytest.raises(Exception):  # unknown font
        Design.model_validate({"id": new_id(), "layers": [
            {"type": "text", "id": new_id(), "x": 0, "y": 0, "w": 1, "h": 1, "text": "a", "font_family": "Evil"}]})


def test_asset_decoding_rejects_junk():
    with pytest.raises(AssetError):
        decode_image(b"<svg onload=alert(1)>")
    with pytest.raises(AssetError):
        decode_image(b"\x89PNG\r\n\x1a\n" + b"garbage")
    ok, buf = cv2.imencode(".jpg", np.zeros((20, 30, 3), np.uint8))
    assert decode_image(buf.tobytes()).shape == (20, 30, 3)


# ---------------------------------------------------------------- export validation
def _encode(w, h, ext, noise=False, q=90):
    img = (np.random.default_rng(0).integers(0, 255, (h, w, 3)).astype(np.uint8) if noise
           else np.full((h, w, 3), 80, np.uint8))
    ok, buf = cv2.imencode("." + ext, img, [cv2.IMWRITE_JPEG_QUALITY, q] if ext == "jpg" else [])
    return buf.tobytes()


def test_export_validation_rules():
    assert validate_thumbnail(_encode(1280, 720, "jpg"), "jpg")["ok"]
    assert validate_thumbnail(_encode(1280, 720, "png"), "png")["ok"]
    bad = validate_thumbnail(_encode(1280, 960, "jpg"), "jpg")
    assert not bad["ok"] and not next(c for c in bad["checks"] if c["check"] == "aspect ratio 16:9")["ok"]
    big = validate_thumbnail(_encode(1280, 720, "png", noise=True), "png")  # random noise PNG ≈ 2.7 MB
    assert not next(c for c in big["checks"] if c["check"] == "file size")["ok"]
    assert not validate_thumbnail(_encode(1280, 720, "png"), "jpg")["ok"]  # mislabelled format
    assert not validate_thumbnail(b"not an image", "png")["ok"]


# ---------------------------------------------------------------- director
ANALYSIS = {"signals": {"energy": "high", "motion": "high", "cuts_per_minute": 14, "faces_ratio": None},
            "transcript": {"available": False, "keywords": []},
            "moments": [{"frame_asset": "c" * 32, "time": 1.0, "dominant_colors": ["#aa2211"]},
                        {"frame_asset": "d" * 32, "time": 9.0, "dominant_colors": []}]}


def test_asks_for_context_when_it_cannot_know():
    assert needs_context(ThumbContext(), ANALYSIS) is not None
    assert needs_context(ThumbContext(about="speedrunning a horror game"), ANALYSIS) is None


@pytest.mark.parametrize("genre", ["horror", "gaming", "funny", "educational", "commentary", "vlog", ""])
@pytest.mark.parametrize("provider", [True, False])
def test_three_distinct_valid_concepts(genre, provider):
    ctx = ThumbContext(about="exploring an abandoned hospital at night", genre=genre, title="Night at the Hospital")
    cs = build_concepts(ctx, ANALYSIS, has_image_provider=provider)
    assert len(cs) == 3 and len({c.direction for c in cs}) == 3
    assert any(c.workflow == "footage_composite" for c in cs), "one concept must use real footage"
    for c in cs:
        Concept.model_validate(c.model_dump())
        if c.workflow != "footage_composite":
            assert "No text" in c.image_prompt and "non-identifiable" in c.image_prompt
            assert c.departs_from_footage and c.review_note
            if not provider:
                assert "Needs an image provider" in c.workflow_reason
        d = build_design(c, background_asset=c.reference_frames[0] if c.reference_frames else "e" * 32,
                         frame_assets=["c" * 32, "d" * 32], genre=genre or "cinematic")
        Design.model_validate(d.model_dump())
    assert build_concepts(ctx, ANALYSIS, has_image_provider=True, seed=1)[0].direction != cs[0].direction or genre == ""


def test_headlines_are_short_grounded_and_not_the_title():
    ctx = ThumbContext(title="I Survived 100 Days in Hardcore Minecraft", about="surviving hardcore minecraft")
    hs = headlines(ctx, ANALYSIS, "gaming")
    assert hs and all(len(h["text"].split()) <= 4 for h in hs)
    assert all(h["text"] != ctx.title.upper() for h in hs)
    assert all(h["basis"] for h in hs)
    assert any("generic" in h["basis"] for h in hs)  # generic framing is labelled as such


def test_refine_respects_locks_and_limits():
    c = build_concepts(ThumbContext(about="x", genre="horror"), ANALYSIS, has_image_provider=True)[0]
    d = build_design(c, background_asset="e" * 32, frame_assets=[], genre="horror")
    text = next(l for l in d.layers if l.type == "text")
    text.locked = True
    r = refine(d, "remove the text and make it more dramatic", can_regenerate=False, can_reference=False)
    assert any(l["type"] == "text" for l in r["design"]["layers"]), "locked text must survive"
    assert any("Locked layers" in n for n in r["notes"])
    assert r["regenerate"] is None and any("needs an image provider" in n for n in r["notes"])
    r2 = refine(d, "make the subject bigger", True, True)
    img = next(l for l in r2["design"]["layers"] if l["type"] == "image")
    assert img["w"] > 1280
    assert refine(d, "xyzzy", True, True)["notes"][0].startswith("I didn't recognise")
    r3 = refine(d, "change the background", True, True)
    assert r3["regenerate"] and r3["regenerate"]["reference_current"]


# ---------------------------------------------------------------- provider contract tests
class Fake(BaseHTTPRequestHandler):
    log = []
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        Fake.log.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if Fake.mode == "401":
            return self._send(401, {"error": {"message": "bad key"}})
        if Fake.mode == "429":
            return self._send(429, {"error": {"message": "slow down"}})
        if Fake.mode == "slow":
            time.sleep(3)
        png = base64.b64encode(cv2.imencode(".png", np.full((64, 96, 3), 200, np.uint8))[1].tobytes()).decode()
        if self.path.startswith("/sdapi/v1/"):
            return self._send(200, {"images": [png]})
        if self.path.endswith("/images/generations") or self.path.endswith("/images/edits"):
            return self._send(200, {"data": [{"b64_json": png}]})
        if self.path.endswith("/chat/completions"):
            return self._send(200, {"choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}]})
        self._send(404, {})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def fake():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Fake.log, Fake.mode = [], "ok"
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_sdwebui_contract(fake):
    p = tp.SDWebUI(fake, 20)
    assert not p.external
    out = p.generate("a castle", "text", [])
    assert decode_image(out).shape[:2] == (64, 96)
    req = json.loads(Fake.log[-1]["body"])
    assert Fake.log[-1]["path"] == "/sdapi/v1/txt2img" and req["negative_prompt"] == "text" and req["width"] == 1344
    p.generate("a castle", "", [b"\x89PNGref"])
    assert Fake.log[-1]["path"] == "/sdapi/v1/img2img"
    assert json.loads(Fake.log[-1]["body"])["init_images"]


def test_openai_images_contract(fake):
    p = tp.OpenAIImages("sk-test", fake + "/v1", "gpt-image-1", "medium")
    decode_image(p.generate("a castle", "text", []))
    last = Fake.log[-1]
    assert last["path"] == "/v1/images/generations" and last["headers"]["Authorization"] == "Bearer sk-test"
    body = json.loads(last["body"])
    assert body["model"] == "gpt-image-1" and "Avoid: text" in body["prompt"]
    decode_image(p.generate("a castle", "", [b"\x89PNGref1", b"\x89PNGref2"]))
    last = Fake.log[-1]
    assert last["path"] == "/v1/images/edits" and b'name="image[]"' in last["body"] and b"ref1" in last["body"]


@pytest.mark.parametrize("mode,msg", [("401", "API key"), ("429", "Rate limit")])
def test_provider_errors_are_friendly(fake, mode, msg):
    Fake.mode = mode
    with pytest.raises(tp.ProviderError, match=msg):
        tp.SDWebUI(fake, 20).generate("x", "", [])


def test_provider_unreachable_and_cancel(fake):
    with pytest.raises(tp.ProviderError, match="Couldn't reach"):
        tp.SDWebUI("http://127.0.0.1:9", 20).generate("x", "", [])
    from app import ffmpeg as ff
    Fake.mode = "slow"
    ev = threading.Event()
    threading.Timer(0.3, ev.set).start()
    t0 = time.time()
    with pytest.raises(ff.Cancelled):
        tp.SDWebUI(fake, 20).generate("x", "", [], cancel=ev)
    assert time.time() - t0 < 2


def test_text_model_contract(fake):
    tm = tp.TextModel(fake + "/v1", "llama3.1", "", vision=False)
    assert tm.chat_json("sys", "user") == {"ok": True}
    body = json.loads(Fake.log[-1]["body"])
    assert body["model"] == "llama3.1" and body["messages"][0]["role"] == "system"
    assert "Authorization" not in Fake.log[-1]["headers"]
    with pytest.raises(tp.ProviderError, match="images"):
        tm.chat_json("s", "u", images=[b"x"])


def test_free_local_defaults(monkeypatch):
    for k in ("CLIPFORGE_IMAGE_PROVIDER", "CLIPFORGE_SDWEBUI_URL", "CLIPFORGE_LLM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-used-automatically")
    assert tp.image_provider() is None and tp.text_model() is None
    monkeypatch.setenv("CLIPFORGE_SDWEBUI_URL", "http://127.0.0.1:7860")
    assert tp.image_provider().id == "sdwebui"


# ---------------------------------------------------------------- API workflow
def test_api_thumbnail_workflow(server, tmp_path, fake, monkeypatch):
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "thumbs"})
    pid = p["id"]
    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid)], check=True)
    _, up, _ = c.upload(pid, vid)
    mid = up["media"]["id"]
    st, r, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/analyze")
    assert st == 400 and "empty" in r["error"]
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    p["timeline"]["tracks"][0]["clips"] = [{"id": new_id(), "media_id": mid, "start": 0, "source_in": 1, "source_out": 5}]
    c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                    "timeline": p["timeline"], "output": p["output"]})
    st, r, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/concepts", {})
    assert st == 409  # analyse first
    _, job, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/analyze")
    assert c.wait_job(job["id"])["status"] == "succeeded"
    _, status, _ = c.req("GET", f"/api/projects/{pid}/thumbnails")
    assert status["analysis"]["moments"] and status["image_provider"] is None
    _, r, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/concepts", {"context": {}})
    assert r.get("needs_context")
    ctx = {"about": "testing a colourful test pattern", "genre": "educational"}
    _, r, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/concepts", {"context": ctx})
    concepts = r["concepts"]
    assert len(concepts) == 3
    st, r, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/generate", {"concept": concepts[0]})
    assert st == 409 and "Stable Diffusion" in r["error"]
    foot = next(x for x in concepts if x["workflow"] == "footage_composite")
    st, doc, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/designs",
                       {"concept": foot, "workflow": "footage_composite", "name": "Mine"})
    assert st == 201
    d = doc["draft"]
    assert d["timeline_fingerprint"] and any(l["type"] == "image" for l in d["layers"])
    assert not d["concept"]["departs_from_footage"]
    ai_c = next(x for x in concepts if x["workflow"] != "footage_composite")
    _, doc_f, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/designs",
                        {"concept": ai_c, "workflow": "footage_composite"})
    assert not doc_f["draft"]["concept"]["departs_from_footage"], "footage builds are never flagged as AI art"
    d["layers"].append({"type": "text", "id": new_id(), "x": 100, "y": 100, "w": 400, "h": 120, "text": "EDITED"})
    st, _, _ = c.req("PUT", f"/api/projects/{pid}/thumbnails/designs/{d['id']}", d)
    assert st == 200
    st, v, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/designs/{d['id']}/versions", {"label": "v1"})
    assert st == 201
    st, ex, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/designs/{d['id']}/export?format=jpg",
                      raw=_encode(1280, 720, "jpg"))
    assert st == 201 and ex["validation"]["ok"]
    st, bad, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/designs/{d['id']}/export?format=jpg",
                       raw=_encode(1000, 720, "jpg"))
    assert st == 422
    st, re_doc, _ = c.req("GET", f"/api/projects/{pid}/thumbnails/designs/{d['id']}")
    assert re_doc["draft"]["layers"][-1]["text"] == "EDITED" and re_doc["versions"][0]["label"] == "v1"
    assert re_doc["staleness"]["state"] == "current"
    # edit the video → design flagged as stale
    _, p, _ = c.req("GET", f"/api/projects/{pid}")
    p["timeline"]["tracks"][0]["clips"][0]["source_in"] = 4.5
    c.req("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                    "timeline": p["timeline"], "output": p["output"]})
    _, re_doc, _ = c.req("GET", f"/api/projects/{pid}/thumbnails/designs/{d['id']}")
    assert re_doc["staleness"]["state"] == "changed"
    # security: traversal and junk uploads
    assert c.req("GET", f"/api/projects/{pid}/thumbnails/assets/../../project.json")[0] == 404
    assert c.req("GET", f"/api/projects/{pid}/thumbnails/exports/..%2F..%2Fproject.json")[0] == 404
    assert c.req("POST", f"/api/projects/{pid}/thumbnails/assets", raw=b"<svg/>")[0] == 415

    # local Stable Diffusion (fake server) → AI artwork design
    monkeypatch.setenv("CLIPFORGE_SDWEBUI_URL", fake)
    ai = next(x for x in concepts if x["workflow"] != "footage_composite")
    st, job, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/generate", {"concept": ai})
    assert st == 202
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded", j
    st, doc2, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/designs",
                        {"concept": ai, "workflow": ai["workflow"], "art_asset": j["result"]["asset_id"]})
    assert st == 201 and doc2["draft"]["generations"][0]["provider"] == "sdwebui"
    assert any(l.get("name") == "AI artwork" for l in doc2["draft"]["layers"])
    # an external provider requires explicit consent
    monkeypatch.setattr(tp, "_is_local", lambda u: False)
    st, r, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/generate", {"concept": ai})
    assert st == 428
    st, _, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/generate", {"concept": ai, "consent_external": True})
    assert st == 202
