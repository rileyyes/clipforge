"""Phase 8.4: YouTube upload, contract-tested against a fake Google (OAuth + resumable upload)."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import youtube as YT


class Google(BaseHTTPRequestHandler):
    state: dict = {}

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, headers=None):
        data = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        return self.rfile.read(int(self.headers.get("content-length", 0)))

    def do_GET(self):
        G = Google.state
        if self.path.startswith("/api/channels"):
            if self.headers.get("authorization") != "Bearer " + G.get("access", ""):
                return self._send(401, {"error": {"message": "bad token"}})
            return self._send(200, {"items": [{"id": "UC123", "snippet": {"title": "Riley Plays"}}]})
        self._send(404, {})

    def do_POST(self):
        G = Google.state
        body = self._body()
        if self.path == "/token":
            f = dict(urllib.parse.parse_qsl(body.decode()))
            G.setdefault("token_calls", []).append(f)
            if f["grant_type"] == "authorization_code":
                ok = base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if f["code"] != "good-code" or ok != G["challenge"] or f["client_secret"] != "s3cret":
                    return self._send(400, {"error": "invalid_grant", "error_description": "bad code"})
                G["access"] = "at-1"
                return self._send(200, {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600})
            if f["grant_type"] == "refresh_token":
                if f["refresh_token"] != "rt-1":
                    return self._send(400, {"error": "invalid_grant"})
                G["access"] = "at-2"
                return self._send(200, {"access_token": "at-2", "expires_in": 3600})
        if self.path == "/revoke":
            G["revoked"] = dict(urllib.parse.parse_qsl(body.decode()))
            return self._send(200, {})
        if self.path.startswith("/upload/videos?uploadType=resumable"):
            if self.headers.get("authorization") != "Bearer " + G.get("access", ""):
                return self._send(401, {"error": {"message": "bad token"}})
            if G.get("quota"):
                return self._send(403, {"error": {"message": "quota", "errors": [{"reason": "quotaExceeded"}]}})
            G["meta"] = json.loads(body)
            G["size"] = int(self.headers["x-upload-content-length"])
            G["received"] = bytearray()
            return self._send(200, {}, {"Location": f"http://127.0.0.1:{self.server.server_address[1]}/session/1"})
        if self.path.startswith("/upload/thumbnails/set?videoId=vid123"):
            G["thumb"] = (self.headers.get("content-type"), len(body))
            return self._send(200, {"items": []})
        self._send(404, {})

    def do_PUT(self):
        G = Google.state
        body = self._body()
        rng = self.headers.get("content-range")
        size = G["size"]
        if rng == f"bytes */{size}":  # status query after a failure
            have = len(G["received"])
            if have >= size:
                return self._send(200, {"id": "vid123", "status": {"privacyStatus": G["meta"]["status"]["privacyStatus"]}})
            return self._send(308, None, {"Range": f"bytes=0-{have - 1}"} if have else {})
        start = int(rng.split(" ")[1].split("-")[0])
        G["puts"] = G.get("puts", 0) + 1
        if G["puts"] == 2 and G.get("fail_once"):
            return self._send(503, {"error": {"message": "backend error"}})
        assert start == len(G["received"]), (start, len(G["received"]))
        keep = body if not (G["puts"] == 1 and G.get("partial")) else body[: len(body) // 2 // 1024 * 1024]
        G["received"] += keep
        if len(G["received"]) >= size:
            return self._send(201, {"id": "vid123", "status": {"privacyStatus": G["meta"]["status"]["privacyStatus"]}})
        return self._send(308, None, {"Range": f"bytes=0-{len(G['received']) - 1}"})


@pytest.fixture()
def google(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Google)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    Google.state = {}
    monkeypatch.setenv("RJCLIP_GOOGLE_AUTH_URL", base + "/auth")
    monkeypatch.setenv("RJCLIP_GOOGLE_TOKEN_URL", base + "/token")
    monkeypatch.setenv("RJCLIP_GOOGLE_REVOKE_URL", base + "/revoke")
    monkeypatch.setenv("RJCLIP_YOUTUBE_API_URL", base + "/api")
    monkeypatch.setenv("RJCLIP_YOUTUBE_UPLOAD_URL", base + "/upload")
    yield base
    srv.shutdown()


CLIENT = json.dumps({"installed": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "s3cret",
                                   "redirect_uris": ["http://localhost"]}}).encode()


def connect(yt: YT.YouTube) -> None:
    yt.set_client(CLIENT)
    url = yt.auth_url("http://127.0.0.1:8765/api/youtube/callback")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert q["code_challenge_method"] == "S256" and "youtube.upload" in q["scope"] and q["access_type"] == "offline"
    Google.state["challenge"] = q["code_challenge"]
    yt.finish(q["state"], "good-code")


def test_client_file_checks(tmp_path):
    yt = YT.YouTube(tmp_path)
    with pytest.raises(YT.YouTubeError, match="Desktop app"):
        yt.set_client(json.dumps({"web": {"client_id": "x", "client_secret": "y"}}).encode())
    with pytest.raises(YT.YouTubeError):
        yt.set_client(b"not json")
    assert yt.set_client(CLIENT)["client_id"].startswith("123-abc")
    import os
    if os.name != "nt":
        assert oct(os.stat(yt.client_file).st_mode)[-3:] == "600"


def test_sign_in_state_is_one_time_and_pkce_is_checked(google, tmp_path):
    yt = YT.YouTube(tmp_path)
    connect(yt)
    st = yt.status()
    assert st["connected"] and st["channel"] == {"id": "UC123", "title": "Riley Plays"}
    with pytest.raises(YT.YouTubeError, match="expired or wasn't started"):
        yt.finish("forged-state", "good-code")
    url = yt.auth_url("http://127.0.0.1:8765/api/youtube/callback")
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
    with pytest.raises(YT.YouTubeError, match="bad code"):
        yt.finish(state, "stolen-code")  # (challenge differs too)
    with pytest.raises(YT.YouTubeError):
        yt.finish(state, "good-code")  # state already used


def test_resumable_upload_survives_partial_writes_and_a_503(google, tmp_path, monkeypatch):
    yt = YT.YouTube(tmp_path)
    connect(yt)
    monkeypatch.setattr(YT, "CHUNK", 256 * 1024)
    video = tmp_path / "v.mp4"
    payload = bytes(range(256)) * 4100  # ~1 MB, not a multiple of the chunk size
    video.write_bytes(payload)
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"\xff\xd8" + b"0" * 5000)
    Google.state.update(partial=True, fail_once=True)
    # force a token refresh on the way
    tok = json.loads(yt.token_file.read_bytes())
    tok["expires_at"] = 0
    yt.token_file.write_text(json.dumps(tok))
    meta = YT.metadata({"title": "My video", "description": "Hi", "tags": ["a", "b"], "category_id": "20",
                        "chapters": [{"t": 0, "title": "Intro"}, {"t": 65, "title": "Boss"}, {"t": 130, "title": "End"}],
                        "privacy": "unlisted"})
    progress = []
    r = yt.upload(video, meta, thumb, on_progress=progress.append, sleep=lambda s: None)
    G = Google.state
    assert bytes(G["received"]) == payload  # every byte exactly once, in order
    assert r == {"video_id": "vid123", "url": "https://youtu.be/vid123", "privacy": "unlisted", "thumbnail": "set"}
    assert G["meta"]["snippet"]["description"] == "Hi\n\n0:00 Intro\n1:05 Boss\n2:10 End"
    assert G["meta"]["snippet"]["categoryId"] == "20" and G["meta"]["status"]["privacyStatus"] == "unlisted"
    assert G["thumb"] == ("image/jpeg", 5002) and progress[-1] == 1.0
    assert [c["grant_type"] for c in G["token_calls"]] == ["authorization_code", "refresh_token"]


def test_schedule_forces_private_and_quota_message(google, tmp_path):
    m = YT.metadata({"title": "x", "privacy": "public", "publish_at": "2026-12-01T17:00:00Z"})
    assert m["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "publishAt": "2026-12-01T17:00:00Z"}
    yt = YT.YouTube(tmp_path)
    connect(yt)
    Google.state["quota"] = True
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 1000)
    with pytest.raises(YT.YouTubeError, match="daily upload quota"):
        yt.upload(v, m)


def test_api_youtube_flow(server, google, tmp_path):
    c = server
    assert c.req("GET", "/api/youtube/status")[1] == {"client_configured": False, "connected": False, "channel": None}
    assert c.req("POST", "/api/youtube/connect")[0] == 409
    assert c.req("POST", "/api/youtube/client", raw=b"{}")[0] == 422
    st, r, _ = c.req("POST", "/api/youtube/client", raw=CLIENT)
    assert st == 200 and r["client_configured"]
    st, r, _ = c.req("POST", "/api/youtube/connect")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["url"]).query))
    assert q["redirect_uri"].startswith("http://127.0.0.1:") and q["redirect_uri"].endswith("/api/youtube/callback")
    Google.state["challenge"] = q["code_challenge"]
    st, page, _ = c.req("GET", f"/api/youtube/callback?state=nope&code=good-code")
    assert st == 400 and b"Not connected" in page
    st, page, _ = c.req("GET", f"/api/youtube/callback?state={q['state']}&code=good-code")
    assert st == 200 and b"Riley Plays" in page and b"<script" not in page
    assert c.req("GET", "/api/youtube/status")[1]["connected"] is True
    # a project with an export and a draft
    _, p, _ = c.req("POST", "/api/projects", {"name": "upload"})
    pid = p["id"]
    exports = c.settings.projects_dir / pid / "exports"
    (exports / "final.mp4").write_bytes(b"\x00" * 3000)
    up = f"/api/projects/{pid}/youtube/upload"
    assert c.req("POST", up, {"export_file": "final.mp4"})[0] == 400  # no confirm
    assert c.req("POST", up, {"confirm": True, "export_file": "final.mp4"})[0] == 422  # no title
    c.req("PUT", f"/api/projects/{pid}/publish", {"title": "Hello", "description": "d"})
    assert c.req("POST", up, {"confirm": True, "export_file": "../../secrets/youtube_token.json"})[0] == 404
    assert c.req("POST", up, {"confirm": True, "export_file": "missing.mp4"})[0] == 404
    assert c.req("POST", up, {"confirm": True, "export_file": "final.mp4"}, csrf=False)[0] == 403
    st, job, _ = c.req("POST", up, {"confirm": True, "export_file": "final.mp4"})
    assert st == 202
    j = c.wait_job(job["id"])
    assert j["status"] == "succeeded" and j["result"]["url"] == "https://youtu.be/vid123", j
    assert Google.state["meta"]["status"]["privacyStatus"] == "private"  # the default
    hist = c.req("GET", f"/api/projects/{pid}/youtube/uploads")[1]["uploads"]
    assert hist[0]["video_id"] == "vid123" and hist[0]["title"] == "Hello"
    # tokens never reach the browser
    assert "rt-1" not in json.dumps(c.req("GET", "/api/youtube/status")[1])
    assert c.req("POST", "/api/youtube/disconnect")[1]["connected"] is False
    assert Google.state["revoked"]["token"] == "rt-1"
