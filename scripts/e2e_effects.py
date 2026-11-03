"""Browser end-to-end test of Phase 4 (effects) without a real transcriber.

A word-timed transcript is written into the project's analysis (as the free
faster-whisper transcriber would), then in the browser: Editor -> Effects tab ->
Find & bleep swears -> Auto-place comedy edits -> add pop-up text at the playhead
-> enable captions -> undo/redo -> export (validated) -> reload -> effects persist.

Run:  python scripts/e2e_effects.py     (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="clipforge-e2e-fx-"))
WS = TMP / "ws"
PORT = 8794
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"X-ClipForge": "1"}
    if body is not None:
        h["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=h)) as r:
        return json.loads(r.read() or b"null")


def setup() -> str:
    vid = TMP / "talk.mp4"
    audio = ("aevalsrc='0.15*sin(2*PI*190*t)*(0.6+0.4*abs(sin(2*PI*4*t)))+0.6*between(t,5,5.6)*sin(2*PI*300*t)'"
             ":s=48000:d=10")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=10",
                    "-f", "lavfi", "-i", audio, "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)
    p = api("POST", "/api/projects", {"name": "Effects test"})
    m = api("POST", f"/api/projects/{p['id']}/media?filename=talk.mp4", raw=vid.read_bytes())["media"]
    job = api("POST", f"/api/projects/{p['id']}/autoedit/analyze", {"media_id": m["id"]})
    for _ in range(100):
        if api("GET", f"/api/jobs/{job['id']}")["status"] == "succeeded":
            break
        time.sleep(0.3)
    # add a transcript the way faster-whisper would
    af = WS / "projects" / p["id"] / "analysis" / f"{m['id']}.json"
    a = json.loads(af.read_text())
    a["words"] = [{"start": 1.0, "end": 1.3, "text": " oh", "p": 0.9}, {"start": 1.4, "end": 1.8, "text": " shit", "p": 0.93},
                  {"start": 2.0, "end": 2.4, "text": " what", "p": 0.9}, {"start": 2.5, "end": 2.9, "text": " was", "p": 0.9},
                  {"start": 3.0, "end": 3.4, "text": " that?", "p": 0.9}]
    a["transcriber"] = "test"
    af.write_text(json.dumps(a))
    p = api("GET", f"/api/projects/{p['id']}")
    link = uuid.uuid4().hex
    p["timeline"]["tracks"][0]["clips"] = [{"id": uuid.uuid4().hex, "media_id": m["id"], "start": 0, "source_in": 0, "source_out": 10, "link_id": link}]
    p["timeline"]["tracks"][2]["clips"] = [{"id": uuid.uuid4().hex, "media_id": m["id"], "start": 0, "source_in": 0, "source_out": 10, "link_id": link}]
    api("PUT", f"/api/projects/{p['id']}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"], "output": p["output"]})
    return p["id"]


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1500, "height": 950})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(f"{B}/#/editor/{pid}")
        await pg.get_by_role("button", name="Effects").click()
        await pg.get_by_text("1 of 1 clip source(s) transcribed").wait_for(timeout=10000)
        await pg.get_by_role("button", name="Find & bleep swears").click()
        await pg.get_by_text("“shit”").wait_for(timeout=5000)
        await pg.get_by_role("button", name="Auto-place").click()
        await pg.wait_for_timeout(800)
        auto = await pg.locator("text=Zoom").count()
        print("auto-placed zoom effects:", auto)
        # add a pop-up at 6 s
        r = await pg.locator(".ruler").bounding_box()
        pps = await pg.evaluate("()=>parseFloat(document.querySelector('.clip.video').style.width)/10")
        await pg.mouse.click(r["x"] + 6 * pps, r["y"] + 10)
        await pg.get_by_role("button", name="Pop-up text", exact=True).click()
        n_before = await pg.locator("input[maxlength='40']").count()
        assert n_before >= 1
        await pg.locator("input[maxlength='40']").last.fill("E2E POP")
        await pg.get_by_label("Burn animated captions into the export").check()
        await pg.keyboard.press("Escape")
        await pg.locator(".tl-body").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Control+z")
        await pg.wait_for_timeout(200)
        assert not await pg.get_by_label("Burn animated captions into the export").is_checked(), "undo captions"
        await pg.keyboard.press("Control+Shift+z")
        await pg.wait_for_timeout(200)
        assert await pg.get_by_label("Burn animated captions into the export").is_checked(), "redo captions"
        await pg.get_by_text("All changes saved").wait_for(timeout=10000)
        markers = await pg.locator(".ruler div[title]").count()
        print("timeline markers:", markers)
        assert markers >= 2
        await pg.screenshot(path=str(TMP / "effects.png"))
        await pg.get_by_role("button", name="Export").first.click()
        await pg.wait_for_url("**/#/export/*")
        await pg.locator("select").first.select_option("720")
        await pg.get_by_role("button", name="Export video").click()
        for _ in range(240):
            await pg.wait_for_timeout(1000)
            if await pg.locator(".checks").count():
                break
        checks = await pg.locator(".checks").first.inner_text()
        assert "✗" not in checks, checks
        print("export validated:", checks.count("✓"), "checks")
        await pg.goto(f"{B}/#/editor/{pid}")
        await pg.get_by_role("button", name="Effects").click()
        await pg.get_by_text("“shit”").wait_for(timeout=10000)
        assert await pg.locator("input[value='E2E POP']").count() == 1
        print("effects persisted after reopen")
        assert not errs, errs
        await b.close()
    proj = WS / "projects" / pid / "exports"
    mp4 = next(proj.glob("*.mp4"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "6.4", "-i", str(mp4), "-frames:v", "1", str(TMP / "pop.png")])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2.6", "-i", str(mp4), "-frames:v", "1", str(TMP / "caption.png")])


if __name__ == "__main__":
    env = {**os.environ, "CLIPFORGE_WORKSPACE": str(WS), "CLIPFORGE_PORT": str(PORT)}
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
