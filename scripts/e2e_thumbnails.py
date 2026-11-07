"""Browser end-to-end test of the Thumbnail Maker (free/local mode, no AI provider).

Edited project -> Thumbnails -> Analyse edit -> describe video -> 3 concepts ->
Build from my footage -> add & edit text -> refine ("more dramatic") -> undo ->
save version -> export JPEG (validated) -> reload -> reopen design, edits intact.

Run:  python scripts/e2e_thumbnails.py     (needs Playwright + built frontend)
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-thumb-"))
PORT = 8793
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"X-RJClip": "1"}
    if body is not None:
        h["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=h)) as r:
        return json.loads(r.read() or b"null")


def setup_project() -> str:
    vid = TMP / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=12",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(vid)], check=True)
    p = api("POST", "/api/projects", {"name": "Thumb test"})
    m = api("POST", f"/api/projects/{p['id']}/media?filename=clip.mp4", raw=vid.read_bytes())["media"]
    p = api("GET", f"/api/projects/{p['id']}")
    p["timeline"]["tracks"][0]["clips"] = [
        {"id": uuid.uuid4().hex, "media_id": m["id"], "start": 0, "source_in": 2, "source_out": 6},
        {"id": uuid.uuid4().hex, "media_id": m["id"], "start": 4, "source_in": 8, "source_out": 11}]
    api("PUT", f"/api/projects/{p['id']}/timeline", {"base_edit_revision": p["edit_revision"],
                                                      "timeline": p["timeline"], "output": p["output"]})
    return p["id"]


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1500, "height": 1000})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept("First version") if d.type == "prompt" else d.accept()))
        await pg.goto(f"{B}/#/thumbs/{pid}")
        await pg.get_by_role("button", name="Analyse edit").click()
        await pg.get_by_text("Not known from analysis").wait_for(timeout=60000)
        frames = await pg.locator("img[title]").count()
        print("frames from edit:", frames)
        assert frames >= 3
        await pg.get_by_label("What is the video about?").fill("a colourful test pattern explained")
        await pg.get_by_label("Genre").select_option("educational")
        await pg.get_by_role("button", name="Get 3 concepts").click()
        await pg.get_by_text("3 · Pick a concept").wait_for(timeout=10000)
        cards = await pg.get_by_role("button", name="Build from my footage").count()
        print("concepts:", cards)
        assert cards == 3
        await pg.screenshot(path=str(TMP / "concepts.png"), full_page=True)
        await pg.get_by_role("button", name="Build from my footage").first.click()
        await pg.get_by_text("Draft saved").wait_for(timeout=10000)
        await pg.get_by_role("button", name="+ Text").click()
        await pg.locator("textarea").fill("E2E TEXT")
        await pg.wait_for_timeout(300)
        await pg.get_by_placeholder("e.g. more dramatic").fill("make it more dramatic")
        await pg.get_by_role("button", name="Apply").click()
        await pg.get_by_text("✓ adjusted image").wait_for(timeout=5000)
        assert await pg.get_by_text("Vignette", exact=True).count() == 1
        await pg.keyboard.press("Control+z")  # undo the refinement
        await pg.wait_for_timeout(300)
        assert await pg.get_by_text("Vignette", exact=True).count() == 0, "undo should remove the vignette"
        await pg.get_by_text("Draft saved").wait_for(timeout=10000)
        # cut the subject out of the footage frame -> a new transparent layer
        layers = pg.locator(".card", has=pg.get_by_role("heading", name="Layers")).locator("div.row")
        for i in range(1, await layers.count()):
            await layers.nth(i).click()
            if await pg.get_by_role("button", name="Cut out subject").count():
                break
        n_before = await layers.count()
        await pg.get_by_role("button", name="Cut out subject").click()
        for _ in range(100):
            if await layers.count() > n_before:
                break
            await pg.wait_for_timeout(100)
        assert await layers.count() == n_before + 1 and await pg.get_by_text("Cut-out", exact=True).count() >= 1
        print("cut-out layer added")
        await pg.get_by_text("Draft saved").wait_for(timeout=10000)
        await pg.get_by_role("button", name="Save version").click()
        await pg.get_by_text("First version").wait_for(timeout=5000)
        await pg.get_by_role("button", name="Export 1280×720").click()
        await pg.locator(".checks").wait_for(timeout=15000)
        checks = await pg.locator(".checks").inner_text()
        assert "✗" not in checks, checks
        print("export checks passed:", checks.count("✓"))
        await pg.screenshot(path=str(TMP / "studio.png"), full_page=True)
        # reopen after a full reload
        await pg.reload()
        await pg.locator(".proj-card").first.wait_for(timeout=10000)
        await pg.locator(".proj-card").first.click()
        await pg.get_by_text("Text: E2E TEXT").wait_for(timeout=5000)
        print("reopened with edits intact")
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    env = {**os.environ, "RJCLIP_WORKSPACE": str(TMP / "ws"), "RJCLIP_PORT": str(PORT)}
    for k in ("RJCLIP_SDWEBUI_URL", "RJCLIP_IMAGE_PROVIDER", "RJCLIP_LLM_BASE_URL"):
        env.pop(k, None)
    srv = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT / "backend", env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(B + "/api/health")
                break
            except Exception:
                time.sleep(0.2)
        asyncio.run(main(setup_project()))
        print("OK — screenshots in", TMP)
    finally:
        srv.terminate()
