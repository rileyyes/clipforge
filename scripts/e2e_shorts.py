"""Browser end-to-end test of the Shorts maker.

A landscape video with a moving subject -> Shorts page -> Analyse -> suggestions -> title ->
Make Short -> it appears under "Your Shorts" -> Open: a 1080x1920 project with follow
keyframes and the vertical monitor -> export validates. Fails on console/page errors.

Run:  python scripts/e2e_shorts.py      (needs Playwright + built frontend)
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-shorts-"))
PORT = 8802
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def setup() -> str:
    src = TMP / "gaming.mp4"
    d = 40
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={d}",
                    "-f", "lavfi", "-i", f"aevalsrc='(0.15*lt(mod(t,6),4.5)+0.6*between(t,20,24))*sin(2*PI*200*t)':s=48000:d={d}",
                    "-f", "lavfi", "-i", f"color=c=white:s=160x160:r=30:d={d}",
                    "-filter_complex", f"[0:v][2:v]overlay=x='100+1000*t/{d}':y=280[v]", "-map", "[v]", "-map", "1:a",
                    "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    p = api("POST", "/api/projects", {"name": "Gaming session"})
    api("POST", f"/api/projects/{p['id']}/media?filename=gaming.mp4", raw=src.read_bytes())
    return p["id"]


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1500, "height": 1000})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(B + "/#/shorts")
        await pg.get_by_role("button", name="Choose").first.click()
        await pg.get_by_role("button", name="Analyse video").click()
        sug = pg.get_by_test_id("short-suggestion")
        await sug.first.wait_for(timeout=120000)
        n = await sug.count()
        print("suggestions:", n, "| first:", (await sug.first.inner_text()).replace("\n", " ")[:120])
        await pg.get_by_label("Length").select_option("15-30")
        await pg.wait_for_timeout(800)
        await sug.first.wait_for()
        first = sug.first
        await first.get_by_label("Short title").fill("Big reaction")
        await first.get_by_role("button", name="start ▶").click()
        await pg.screenshot(path=str(TMP / "shorts.png"))
        await first.get_by_role("button", name="Make Short").click()
        done = pg.get_by_test_id("short-job").filter(has_text="Short: Big reaction")
        await done.wait_for(timeout=120000)
        print("made:", (await done.inner_text()).replace("\n", " "))
        assert "follows you" in await done.inner_text()
        await done.get_by_role("link", name="Open").click()
        await pg.locator(".clip.video").first.wait_for()
        await pg.wait_for_timeout(800)
        marks = await pg.locator(".clip.video .kf-mark").count()
        info = await pg.locator(".transport").inner_text()
        print("editor:", info.split("\n")[-1], "| keyframe marks:", marks)
        assert "1080×1920" in info and marks >= 2
        await pg.screenshot(path=str(TMP / "short_editor.png"))
        sid = pg.url.rsplit("/", 1)[1]
        job = api("POST", f"/api/projects/{sid}/exports", {"filename": "short", "quality": "draft",
                                                            "output": {"width": 540, "height": 960, "fps": 30, "fit_mode": "fit"}})
        for _ in range(400):
            j = api("GET", f"/api/jobs/{job['id']}")
            if j["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(0.25)
        assert j["status"] == "succeeded" and j["result"]["validation"]["ok"], j
        print("export validated:", sum(c["ok"] for c in j["result"]["validation"]["checks"]), "checks")
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    env = {**os.environ, "RJCLIP_WORKSPACE": str(TMP / "ws"), "RJCLIP_PORT": str(PORT), "RJCLIP_TRANSCRIBER": "off"}
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
