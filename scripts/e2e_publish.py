"""Browser end-to-end test of Publish (chapters/title/description/tags + YouTube upload).

Uses a FAKE Google (OAuth + resumable upload) on localhost, so nothing real is touched.
Project with a transcript -> Publish -> "Write it for me" -> chapters/tags appear -> edit the
title -> add the client JSON -> Connect (sign-in tab redirects back) -> connected -> export ->
choose it -> Upload (confirm) -> "Uploaded" shows the youtu.be link; the fake received the
title, chapters in the description, and privacy=private. Fails on console/page errors.

Run:  python scripts/e2e_publish.py      (needs Playwright + built frontend)
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="clipforge-e2e-pub-"))
WS = TMP / "ws"
PORT = 8803
B = f"http://127.0.0.1:{PORT}"
GOT: dict = {}


class FakeGoogle(BaseHTTPRequestHandler):
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

    def do_GET(self):
        if self.path.startswith("/auth?"):  # "sign in" instantly and send the browser back
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            self.send_response(302)
            self.send_header("Location", q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": "c0de", "state": q["state"]}))
            self.end_headers()
            return
        if self.path.startswith("/api/channels"):
            return self._send(200, {"items": [{"id": "UC1", "snippet": {"title": "Riley Plays"}}]})
        self._send(404, {})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path == "/token":
            return self._send(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
        if self.path.startswith("/upload/videos"):
            GOT["meta"] = json.loads(body)
            GOT["size"] = int(self.headers["x-upload-content-length"])
            return self._send(200, {}, {"Location": f"http://127.0.0.1:{self.server.server_address[1]}/session"})
        self._send(200, {})

    def do_PUT(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        GOT["bytes"] = GOT.get("bytes", 0) + len(body)
        return self._send(201, {"id": "abc123", "status": {"privacyStatus": GOT["meta"]["status"]["privacyStatus"]}})


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-ClipForge": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


TOPICS = ["minecraft creeper exploded my diamond house sword armor", "pasta recipe tomato sauce garlic basil boil",
          "car engine oil change wrench tires garage"]


def setup() -> str:
    vid = TMP / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=25:d=200", "-f", "lavfi",
                    "-i", "sine=f=200:d=200", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(vid)], check=True)
    p = api("POST", "/api/projects", {"name": "Weekend vlog"})
    pid = p["id"]
    m = api("POST", f"/api/projects/{pid}/media?filename=v.mp4", raw=vid.read_bytes())["media"]
    job = api("POST", f"/api/projects/{pid}/autoedit/analyze", {"media_id": m["id"], "transcribe": False})
    while api("GET", f"/api/jobs/{job['id']}")["status"] in ("queued", "running"):
        time.sleep(0.3)
    words, t = [], 0.0
    for k, topic in enumerate(TOPICS):
        toks = topic.split()
        i = 0
        while t < (k + 1) * 66:
            w = toks[i % len(toks)] + ("." if i % 8 == 7 else "")
            words.append({"start": round(t, 2), "end": round(t + 0.3, 2), "text": " " + w, "p": 0.9})
            t += 0.5 if i % 8 != 7 else 1.5
            i += 1
    words.append({"start": t, "end": t + 0.4, "text": " What", "p": 0.9})
    words += [{"start": t + 0.5, "end": t + 0.8, "text": " just", "p": 0.9}, {"start": t + 0.9, "end": t + 1.2, "text": " happened?", "p": 0.9}]
    af = WS / "projects" / pid / "analysis" / f"{m['id']}.json"
    a = json.loads(af.read_bytes())
    a["words"] = words
    af.write_text(json.dumps(a), encoding="utf-8")
    p = api("GET", f"/api/projects/{pid}")
    link = uuid.uuid4().hex
    for ti in (0, 2):
        p["timeline"]["tracks"][ti]["clips"] = [{"id": uuid.uuid4().hex, "media_id": m["id"], "start": 0, "source_in": 0, "source_out": 200, "link_id": link}]
    p["output"].update(width=320, height=180)
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"], "output": p["output"]})
    job = api("POST", f"/api/projects/{pid}/exports", {"filename": "final", "quality": "draft", "output": p["output"]})
    while api("GET", f"/api/jobs/{job['id']}")["status"] in ("queued", "running"):
        time.sleep(0.5)
    client = TMP / "client_secret.json"
    client.write_text(json.dumps({"installed": {"client_id": "1-x.apps.googleusercontent.com", "client_secret": "s"}}))
    return pid


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1500, "height": 1100})
        pg = await ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(f"{B}/#/publish/{pid}")
        det = pg.get_by_test_id("details")
        await det.get_by_role("button", name="Write it for me").click()
        await pg.get_by_test_id("chapter").first.wait_for(timeout=15000)
        n_ch = await pg.get_by_test_id("chapter").count()
        desc = await det.get_by_label("Description").input_value()
        print(f"chapters: {n_ch} | title: {await det.get_by_label('Title', exact=True).input_value()!r}")
        assert n_ch >= 3 and "Chapters\n0:00" in desc
        ideas = det.locator("button.btn.xs")
        print("title ideas:", await ideas.all_inner_texts())
        await det.get_by_label("Title", exact=True).fill("What just happened?")
        await det.get_by_label("Add tags").fill("vlog, weekend")
        await det.get_by_label("Add tags").press("Enter")
        await pg.get_by_text("draft saved").wait_for(timeout=10000)
        yt = pg.get_by_test_id("youtube")
        async with pg.expect_file_chooser() as fc:
            await yt.get_by_role("button", name="Choose the client JSON file").click()
        await (await fc.value).set_files(str(TMP / "client_secret.json"))
        async with ctx.expect_page() as popup:
            await yt.get_by_role("button", name="Connect YouTube").click()
        tab = await popup.value
        await tab.wait_for_load_state()
        print("sign-in tab says:", (await tab.inner_text("body")).split("\n")[0])
        await tab.close()
        await yt.get_by_text("Riley Plays").wait_for(timeout=10000)
        opts = await yt.get_by_label("Video to upload").locator("option").all_inner_texts()
        await yt.get_by_label("Video to upload").select_option(index=1)
        print("exports offered:", opts[1:])
        await pg.get_by_text("draft saved").wait_for(timeout=10000)
        await pg.screenshot(path=str(TMP / "publish.png"), full_page=True)
        await yt.get_by_test_id("upload").click()
        await pg.get_by_test_id("uploaded").first.wait_for(timeout=30000)
        row = await pg.get_by_test_id("uploaded").first.inner_text()
        print("uploaded:", row.replace("\n", " "))
        assert "https://youtu.be/abc123" in row and "private" in row
        meta = GOT["meta"]
        assert meta["snippet"]["title"] == "What just happened?" and "vlog" in meta["snippet"]["tags"]
        assert "0:00 " in meta["snippet"]["description"] and meta["status"]["privacyStatus"] == "private"
        assert GOT["bytes"] == GOT["size"] > 1000
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    g = ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
    threading.Thread(target=g.serve_forever, daemon=True).start()
    gb = f"http://127.0.0.1:{g.server_address[1]}"
    env = {**os.environ, "CLIPFORGE_WORKSPACE": str(WS), "CLIPFORGE_PORT": str(PORT), "CLIPFORGE_LLM": "off",
           "CLIPFORGE_GOOGLE_AUTH_URL": gb + "/auth", "CLIPFORGE_GOOGLE_TOKEN_URL": gb + "/token",
           "CLIPFORGE_GOOGLE_REVOKE_URL": gb + "/revoke", "CLIPFORGE_YOUTUBE_API_URL": gb + "/api",
           "CLIPFORGE_YOUTUBE_UPLOAD_URL": gb + "/upload"}
    srv = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT / "backend", env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(B + "/api/health")
                break
            except Exception:
                time.sleep(0.2)
        asyncio.run(main(setup()))
        print("OK — screenshots in", TMP)
    finally:
        srv.terminate()
        g.shutdown()
