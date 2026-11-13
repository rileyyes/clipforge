"""Browser end-to-end test: transitions, fades, music track + ducking, loudness.

Two clips on V1/A1 plus a music file on A2. In the browser: set a crossfade on the
second clip, fade the music in/out, toggle the music track role, turn on noise
removal + voice enhancement, export, and require every validation check to pass
(including the -14 LUFS loudness check). Reload: settings persist.

Run:  python scripts/e2e_audio.py     (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-audio-"))
PORT = 8795
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"X-RJClip": "1"}
    if body is not None:
        h["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=h)) as r:
        return json.loads(r.read() or b"null")


def setup() -> str:
    vid, mus = TMP / "talk.mp4", TMP / "music.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8", "-f", "lavfi",
                    "-i", "aevalsrc='0.2*sin(2*PI*190*t)*(0.6+0.4*abs(sin(2*PI*4*t)))*lt(mod(t,4),3)':s=48000:d=8",
                    "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.15*sin(2*PI*220*t)+0.1*sin(2*PI*330*t)':s=48000:d=8", str(mus)], check=True)
    p = api("POST", "/api/projects", {"name": "Audio test"})
    v = api("POST", f"/api/projects/{p['id']}/media?filename=talk.mp4", raw=vid.read_bytes())["media"]
    m = api("POST", f"/api/projects/{p['id']}/media?filename=music.wav", raw=mus.read_bytes())["media"]
    p = api("GET", f"/api/projects/{p['id']}")
    tr = p["timeline"]["tracks"]
    l1, l2 = uuid.uuid4().hex, uuid.uuid4().hex
    tr[0]["clips"] = [{"id": uuid.uuid4().hex, "media_id": v["id"], "start": 0, "source_in": 0, "source_out": 3, "link_id": l1},
                      {"id": uuid.uuid4().hex, "media_id": v["id"], "start": 3, "source_in": 4, "source_out": 7, "link_id": l2}]
    tr[2]["clips"] = [{"id": uuid.uuid4().hex, "media_id": v["id"], "start": 0, "source_in": 0, "source_out": 3, "link_id": l1},
                      {"id": uuid.uuid4().hex, "media_id": v["id"], "start": 3, "source_in": 4, "source_out": 7, "link_id": l2}]
    tr[3]["clips"] = [{"id": uuid.uuid4().hex, "media_id": m["id"], "start": 0, "source_in": 0, "source_out": 6}]
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
        await pg.locator(".clip.video").nth(1).wait_for(timeout=10000)
        # crossfade into the second clip
        box = await pg.locator(".clip.video").nth(1).bounding_box()
        await pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + 30)
        await pg.get_by_label("Transition in").select_option("crossfade")
        await pg.get_by_text("Crossfade in", exact=False).count()
        assert await pg.locator(".clip.video [title='Crossfade in']").count() == 1, "transition badge on the clip"
        # fade the music clip
        music = pg.locator(".lane").nth(3).locator(".clip")
        mb = await music.bounding_box()
        await pg.mouse.click(mb["x"] + mb["width"] / 2, mb["y"] + 20)
        for label, val in (("Fade in", "1"), ("Fade out", "1.5")):
            f = pg.get_by_label(label)
            await f.fill(val)
            await f.press("Enter")
        # A2 starts as a music track in new projects: the button cycles music -> narration -> dialogue -> music
        role = pg.locator(".tl-head").nth(3).locator("button[title^='Music track']")
        assert await role.count() == 1, "A2 is a music track by default"
        await role.click()
        await pg.locator(".tl-head").nth(3).locator("button[title^='Narration track']").click()
        await pg.locator(".tl-head").nth(3).locator("button[title^='Dialogue track']").click()
        await pg.locator(".tl-head").nth(3).locator("button[title^='Music track']").wait_for()
        # audio settings
        await pg.get_by_role("tab", name="Effects").click()
        await pg.get_by_label("Background noise removal").select_option("light")
        await pg.get_by_label("Enhance voice (cut rumble, add clarity, even out levels)").check()
        await pg.get_by_label("Duck music under voice").select_option("strong")
        await pg.get_by_text("All changes saved").wait_for(timeout=10000)
        await pg.screenshot(path=str(TMP / "audio.png"))
        await pg.get_by_role("button", name="Export").first.click()
        await pg.wait_for_url("**/#/export/*")
        await pg.locator("select").first.select_option("720")
        await pg.get_by_role("button", name="Export video").click()
        for _ in range(300):
            await pg.wait_for_timeout(1000)
            if await pg.locator(".checks").count():
                break
        checks = await pg.locator(".checks").first.inner_text()
        assert "✗" not in checks and "loudness" in checks, checks
        print("export checks:", checks.count("✓"), "incl. loudness:", [l for l in checks.splitlines() if "LUFS" in l])
        await pg.goto(f"{B}/#/editor/{pid}")
        await pg.get_by_role("tab", name="Effects").click()
        assert await pg.get_by_label("Duck music under voice").input_value() == "strong"
        assert await pg.locator(".clip.video [title='Crossfade in']").count() == 1
        print("settings persisted after reopen")
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    env = {**os.environ, "RJCLIP_WORKSPACE": str(TMP / "ws"), "RJCLIP_PORT": str(PORT)}
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
