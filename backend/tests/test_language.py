"""Phase 8.2: the AI editor reads what's said (laughs, punchlines, stories) + optional local AI."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import language as L
from app.autoedit import AutoEditSettings, plan


def W(*items):
    """(start, text) pairs -> words lasting 0.3 s."""
    return [{"start": s, "end": s + 0.3, "text": " " + t, "p": 0.9} for s, t in items]


def test_laughs_exclaims_questions_story():
    words = W((1, "So"), (1.4, "then"), (1.8, "he"), (2.2, "fell."), (2.6, "Hahaha"), (5, "Wait!"),
              (8, "No"), (8.4, "way."), (11, "Is"), (11.4, "that"), (11.8, "true?"),
              (14, "Turns"), (14.4, "out"), (14.8, "yes."), (20, "no"), (20.4, "I"), (20.8, "said"), (21.2, "no."))
    ev = L.word_events(words)
    assert ev["laughs"] == [2.6]
    assert 5 in ev["exclaim"] and 8 in ev["exclaim"]
    assert 20 not in ev["exclaim"]  # "no" inside a sentence isn't a reaction
    assert ev["questions"] == [12.1]
    assert ev["story"] == [1.0, 14.0]
    assert 2.5 in ev["punchlines"]  # "So then he fell." -> laughter right after
    assert L.beat_features(ev, 0, 6)["laughs"] == pytest.approx(10)  # 1 per 6 s = 10/min


@pytest.mark.parametrize("tok", ["haha", "Hahaha!", "(laughs)", "[Laughter]", "lol", "LMAO", "chuckles"])
def test_laugh_tokens(tok):
    assert L.word_events(W((0, "x"), (1, tok)))["laughs"]


def test_punchline_from_a_loud_reaction_without_words():
    words = W((1, "And"), (1.4, "then"), (1.8, "it"), (2.2, "exploded."))
    rms = [-40.0] * 200
    for i in range(52, 60):  # loud spike 2.6-3.0 s
        rms[i] = -5.0
    assert L.word_events(words, rms, 0.05)["punchlines"] == [2.5]


def _analysis(words, dur=60.0):
    # steady talking: same loudness everywhere, so only the words differ
    rms = []
    for i in range(int(dur / 0.05)):
        t = i * 0.05
        rms.append(-20.0 if (t % 10) < 8 else -60.0)
    return {"duration": dur, "hop": 0.05, "rms_db": rms, "motion": [], "cuts": [], "words": words}


def test_humor_style_prefers_the_punchline():
    filler = [(t + k * 0.5, w) for t in (10.5, 30.5, 50.5) for k, w in enumerate("well I think that we should".split())]
    joke = W((20.5, "Why"), (21, "did"), (21.5, "he"), (22, "do"), (22.5, "that?"), (23, "Hahaha"), (24, "No"), (24.5, "way!"))
    a = _analysis(W(*filler) + joke)
    r = plan(a, AutoEditSettings(target_mode="duration", target_seconds=9, style="humor", keep_opening=False, context=False))
    chosen = [b for b in r["beats"] if b["selected"]]
    assert any(b["start"] <= 23 < b["end"] for b in chosen), chosen
    top = max(r["beats"], key=lambda b: b["score"])
    assert top["start"] <= 23 < top["end"] and any("laugh" in x or "punchline" in x for x in top["reasons"])


def test_chunks_and_ai_feature():
    words = W(*[(i * 0.5, "word.") for i in range(100)])
    cs = L.chunks(words, target=10)
    assert len(cs) >= 4 and all(e > s for s, e, _ in cs)
    ratings = [{"start": 0, "end": 10, "score": 9, "why": "great joke"}, {"start": 10, "end": 20, "score": 1, "why": "filler"}]
    assert L.ai_feature(ratings, 0, 10) == (9.0, "great joke")
    assert L.ai_feature(ratings, 5, 15)[0] == pytest.approx(5.0)
    assert L.ai_feature(ratings, 30, 40) is None


class FakeModel:
    model = "fake"

    def __init__(self, scores):
        self.scores, self.calls = scores, []

    def chat_json(self, system, user, cancel=None):
        self.calls.append(user)
        ids = [int(line.split(":")[0]) for line in user.splitlines()]
        return {"ratings": [{"i": i, "score": self.scores(i), "why": f"chunk {i}"} for i in ids]
                + [{"i": 999, "score": 5}, {"i": ids[0], "score": 42}]}  # junk is ignored


def test_ai_rate_batches_and_ignores_junk():
    words = W(*[(i * 0.5, "word.") for i in range(400)])
    m = FakeModel(lambda i: 9 if i == 3 else 2)
    out = L.ai_rate(m, words, batch=5)
    assert len(m.calls) == (len(L.chunks(words)) + 4) // 5
    assert all(0 <= r["score"] <= 10 for r in out)
    assert [r["why"] for r in out if r["score"] == 9] == ["chunk 3"]


def test_planner_uses_ai_ratings_and_shows_the_reason():
    words = W(*[(t, "talk.") for t in range(0, 60)])
    a = _analysis(words)
    a["ai_ratings"] = [{"start": 30, "end": 38, "score": 9.5, "why": "the big reveal"},
                       {"start": 0, "end": 30, "score": 2, "why": "rambling"}, {"start": 38, "end": 60, "score": 2, "why": "x"}]
    r = plan(a, AutoEditSettings(target_mode="duration", target_seconds=8, style="story", keep_opening=False, context=False))
    top = max(r["beats"], key=lambda b: b["score"])
    assert top["start"] < 38 and top["end"] > 30 and top["reasons"][0].startswith("AI: the big reveal")


# ---------------------------------------------------------------- local AI server contract
class FakeLLM(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):  # Ollama's model list
        self._send({"models": [{"name": "nomic-embed-text"}, {"name": "qwen2.5:7b"}, {"name": "llama3.1:8b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeLLM.requests.append((self.path, body))
        user = body["messages"][1]["content"]
        ids = [int(line.split(":")[0]) for line in user.splitlines()]
        content = json.dumps({"ratings": [{"i": i, "score": 8 if i == 1 else 3, "why": "funny bit" if i == 1 else "meh"}
                                          for i in ids]})
        self._send({"choices": [{"message": {"content": "Sure!\n```json\n" + content + "\n```"}}]})

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def fake_llm():
    srv = HTTPServer(("127.0.0.1", 0), FakeLLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeLLM.requests = []
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_ollama_autodetect_prefers_a_chat_model(fake_llm, monkeypatch):
    L._detect_cache.update(at=0.0, model=None)
    assert L.detect_ollama(fake_llm) == "llama3.1:8b"
    L._detect_cache.update(at=0.0, model=None)
    assert L.detect_ollama("http://127.0.0.1:9") is None  # nothing running: quietly no AI


def test_api_ai_rate_flow(server, fake_llm, monkeypatch, tmp_path):
    import subprocess
    c = server
    monkeypatch.setenv("CLIPFORGE_LLM_BASE_URL", fake_llm + "/v1")
    vid = tmp_path / "t.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=25:d=40", "-f", "lavfi",
                    "-i", "aevalsrc='0.2*sin(2*PI*200*t)*lt(mod(t,10),8)':s=48000:d=40", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)
    _, p, _ = c.req("POST", "/api/projects", {"name": "ai"})
    pid = p["id"]
    mid = c.upload(pid, vid)[1]["media"]["id"]
    _, job, _ = c.req("POST", f"/api/projects/{pid}/autoedit/analyze", {"media_id": mid, "transcribe": False})
    assert c.wait_job(job["id"])["status"] == "succeeded"
    st, r, _ = c.req("POST", f"/api/projects/{pid}/autoedit/ai-rate", {"media_id": mid})
    assert st == 409 and "Transcribe" in r["error"]
    # add a transcript the way Whisper would
    af = c.settings.projects_dir / pid / "analysis" / f"{mid}.json"
    a = json.loads(af.read_bytes())
    a["words"] = [{"start": t * 0.5, "end": t * 0.5 + 0.3, "text": " word." if t % 6 else " Hey!", "p": 0.9} for t in range(70)]
    af.write_text(json.dumps(a), encoding="utf-8")
    _, status, _ = c.req("GET", f"/api/projects/{pid}/autoedit")
    assert status["ai"]["model"] == "llama3.1" and status["ai"]["external"] is False
    st, job, _ = c.req("POST", f"/api/projects/{pid}/autoedit/ai-rate", {"media_id": mid})
    assert st == 202
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded" and j["result"]["rated"] >= 2, j
    path, body = FakeLLM.requests[-1]
    assert path == "/v1/chat/completions" and "funny" in body["messages"][0]["content"]
    m = c.req("GET", f"/api/projects/{pid}/autoedit")[1]["media"][0]
    assert m["ai_rated"] >= 2 and m["ai_model"] == "llama3.1"
    _, pl, _ = c.req("POST", f"/api/projects/{pid}/autoedit/plan",
                     {"media_id": mid, "settings": {"target_mode": "duration", "target_seconds": 10, "style": "humor"}})
    assert any(x.startswith("AI: funny bit") for b in pl["beats"] for x in b["reasons"])
    monkeypatch.setenv("CLIPFORGE_LLM", "off")
    st, r, _ = c.req("POST", f"/api/projects/{pid}/autoedit/ai-rate", {"media_id": mid})
    assert st == 409 and "Ollama" in r["error"]
