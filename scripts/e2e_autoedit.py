"""Browser end-to-end test of the AI Auto Editor.

Dashboard -> Start AI auto edit -> import a synthetic 'talking' recording -> Analyse ->
set a 12 s target -> drop a moment -> play rough cut -> pick finishing touches ->
Send to Manual Editor -> verify clips + the touches that were applied/skipped -> Export -> validation passes. Fails on any console/page error.

Run:  python scripts/e2e_autoedit.py      (needs Playwright + built frontend)
"""
import asyncio
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-auto-"))
PORT = 8792
B = f"http://127.0.0.1:{PORT}"
SRC = TMP / "talk.mp4"


def make_recording():
    # 4 s of 'speech' then 3 s of near-silence, repeated; one loud reaction at 21-23 s
    audio = ("aevalsrc='(0.15*lt(mod(t,7),4)+0.6*between(t,21,23))*sin(2*PI*190*t)*(0.6+0.4*abs(sin(2*PI*4*t)))"
             "+0.002*random(0)':s=48000:d=35")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=35",
                    "-f", "lavfi", "-i", audio, "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(SRC)], check=True)


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1500, "height": 950})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(B + "/#/dashboard")
        await pg.get_by_text("Start AI auto edit").click()
        await pg.wait_for_url("**/#/auto")
        async with pg.expect_file_chooser() as fc:
            await pg.get_by_text("Import a recording").click()
        await (await fc.value).set_files(str(SRC))
        await pg.wait_for_url(re.compile(r".*#/auto/[0-9a-f]{32}$"), timeout=30000)
        await pg.get_by_role("button", name="Analyse recording").click()
        await pg.get_by_text("2 · Settings").wait_for(timeout=120000)
        await pg.get_by_text("Your video").wait_for(timeout=20000)
        # custom duration 0:12
        await pg.get_by_label("Minutes").fill("0")
        await pg.get_by_label("Seconds").fill("12")
        await pg.wait_for_timeout(1200)
        out = await pg.locator("text=Your video >> xpath=following-sibling::div").inner_text()
        print("planned output:", out)
        mm, ss = out.split(":")
        assert int(mm) * 60 + int(ss) <= 13, out
        kept_before = await pg.locator(".chip.ok", has_text="kept").count()
        # drop the first kept moment
        row = pg.locator("div", has=pg.locator(".chip.ok", has_text="kept")).filter(has=pg.get_by_role("button", name="Drop")).last
        await row.get_by_role("button", name="Drop").click()
        await pg.wait_for_timeout(1200)
        assert await pg.get_by_text("excluded by you").count() >= 1
        print("kept moments before/after drop:", kept_before, await pg.locator(".chip.ok", has_text="kept").count())
        await pg.get_by_role("button", name="Play rough cut").click()
        await pg.wait_for_timeout(1500)
        # one-click finishing touches (no transcriber in this test -> bleeps are skipped, honestly)
        extras = pg.get_by_test_id("extras")
        await extras.locator("select").nth(1).select_option("balanced")
        assert await extras.get_by_text("need a transcript").count() == 1
        await pg.screenshot(path=str(TMP / "auto_review.png"), full_page=True)
        await pg.get_by_role("button", name="Send to Manual Editor").click()
        await pg.wait_for_url(re.compile(r".*#/editor/[0-9a-f]{32}$"), timeout=20000)
        await pg.wait_for_timeout(1500)
        clips = await pg.locator(".clip").count()
        print("clips in editor:", clips)
        assert clips >= 2
        toasts = await pg.locator(".toast").all_inner_texts()
        print("finishing touches:", toasts)
        assert any("Audio polish" in t for t in toasts) and any("Bleep swears skipped" in t for t in toasts), toasts
        assert any("Comedy edits" in t for t in toasts), toasts
        await pg.get_by_role("tab", name=re.compile(r"^Effects")).click()
        await pg.get_by_role("tab", name="History").click()
        assert await pg.get_by_test_id("version").count() == 0  # timeline was empty before: nothing to back up
        await pg.screenshot(path=str(TMP / "auto_editor.png"))
        await pg.get_by_role("button", name="Export").first.click()
        await pg.wait_for_url("**/#/export/*")
        await pg.locator("select").first.select_option("720")
        await pg.get_by_role("button", name="Export video").click()
        for _ in range(180):
            await pg.wait_for_timeout(1000)
            if await pg.locator(".checks").count():
                break
        checks = await pg.locator(".checks").first.inner_text()
        assert "✗" not in checks, checks
        print("export validated:", checks.count("✓"), "checks passed")
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    make_recording()
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
        asyncio.run(main())
        print("OK — screenshots in", TMP)
    finally:
        srv.terminate()
