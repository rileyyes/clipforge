"""Browser end-to-end smoke test of the first milestone.

Starts the app on a throwaway workspace, then in headless Chromium:
import video (dashboard) -> import second video -> add both to timeline -> split ->
ripple delete -> drag-trim -> undo/redo -> play -> autosave -> reload -> export -> validate.

Requires: Python Playwright + Chromium, FFmpeg, a built frontend (cd frontend && node build.mjs).
Run:  python scripts/e2e_browser.py
"""
import asyncio, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-"))
OUT = TMP / "screens"; OUT.mkdir()
SAMPLE, PORTRAIT = TMP / "sample.mp4", TMP / "portrait.mp4"
PORT = 8791
B = f"http://127.0.0.1:{PORT}"

def gen(path, size, rate, dur, freq):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r={rate}:d={dur}",
                    "-f", "lavfi", "-i", f"sine=f={freq}:d={dur}", "-shortest", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)

async def main():
    async with async_playwright() as pw:
        b=await pw.chromium.launch()
        pg=await b.new_page(viewport={"width":1500,"height":900})
        errs=[]
        pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(B+"/#/dashboard"); await pg.wait_for_timeout(800)
        await pg.screenshot(path=str(OUT/"s1_dashboard.png"))
        # Import video via dashboard
        async with pg.expect_file_chooser() as fc:
            await pg.get_by_text("Import video").click()
        await (await fc.value).set_files(str(SAMPLE))
        await pg.wait_for_url("**/#/editor/*", timeout=20000)
        await pg.wait_for_timeout(2500)
        # import second file via library
        async with pg.expect_file_chooser() as fc:
            await pg.locator(".pane-head button", has_text="Import").click()
        await (await fc.value).set_files(str(PORTRAIT))
        await pg.wait_for_timeout(3000)
        # add both to timeline
        await pg.locator(".media-item").nth(0).dblclick(); await pg.wait_for_timeout(300)
        await pg.locator(".media-item").nth(1).dblclick(); await pg.wait_for_timeout(600)
        n=await pg.locator(".clip").count(); print("clips after add",n)
        # click on ruler at ~4s to set playhead, then split
        pps=await pg.evaluate("""()=>{const c=document.querySelector('.clip.video');return parseFloat(c.style.width)/12}""")
        r=await pg.locator(".ruler").bounding_box()
        await pg.mouse.click(r["x"]+4*pps, r["y"]+10)
        await pg.keyboard.press("s"); await pg.wait_for_timeout(300)
        print("clips after split",await pg.locator(".clip").count())
        # select second piece (4..12) and delete with ripple
        clips=pg.locator(".lane").nth(0).locator(".clip")
        box=await clips.nth(1).bounding_box()
        await pg.mouse.click(box["x"]+box["width"]/2, box["y"]+box["height"]/2)
        await pg.keyboard.press("Shift+Delete"); await pg.wait_for_timeout(300)
        print("clips after ripple delete",await pg.locator(".clip").count())
        # drag-trim end of first clip from 4s to 3s
        box=await clips.nth(0).bounding_box()
        await pg.mouse.move(box["x"]+box["width"]-3, box["y"]+20); await pg.mouse.down()
        await pg.mouse.move(box["x"]+box["width"]-3-pps, box["y"]+20, steps=6); await pg.mouse.up()
        await pg.wait_for_timeout(300)
        # undo then redo
        await pg.keyboard.press("Control+z"); await pg.wait_for_timeout(200)
        await pg.keyboard.press("Control+Shift+z"); await pg.wait_for_timeout(200)
        # play 1.5s
        await pg.mouse.click(r["x"]+1, r["y"]+10)
        await pg.keyboard.press("Space"); await pg.wait_for_timeout(1500); await pg.keyboard.press("Space")
        tc=await pg.locator(".tc").inner_text(); print("timecode after play",tc)
        await pg.wait_for_timeout(1500)
        print("save state:", await pg.locator(".save-state").inner_text())
        await pg.screenshot(path=str(OUT/"s2_editor.png"))
        # reopen: reload page
        await pg.reload(); await pg.wait_for_timeout(1500)
        print("clips after reload",await pg.locator(".clip").count())
        await pg.locator(".lane").nth(0).locator(".clip").nth(0).click()
        await pg.wait_for_timeout(200)
        await pg.screenshot(path=str(OUT/"s3_reload.png"))
        # export
        await pg.get_by_role("button", name="Export").first.click()
        await pg.wait_for_url("**/#/export/*"); await pg.wait_for_timeout(800)
        await pg.locator("select").first.select_option("720")
        await pg.get_by_role("button", name="Export video").click()
        for i in range(120):
            await pg.wait_for_timeout(1000)
            if await pg.locator(".checks").count(): break
        await pg.wait_for_timeout(500)
        await pg.screenshot(path=str(OUT/"s4_export.png"), full_page=True)
        print("export checks:", await pg.locator(".checks").first.inner_text() if await pg.locator(".checks").count() else "none")
        print("ERRORS:", errs[:10])
        assert not errs, errs
        assert await pg.locator(".checks").count(), "export did not validate"
        await b.close()

if __name__ == "__main__":
    gen(SAMPLE, "1280x720", 30, 12, 440)
    gen(PORTRAIT, "720x1280", 25, 6, 660)
    env = {**os.environ, "RJCLIP_WORKSPACE": str(TMP / "ws"), "RJCLIP_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT / "backend", env=env)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(B + "/api/health"); break
            except Exception:
                time.sleep(0.2)
        asyncio.run(main())
        print("screenshots in", OUT)
    finally:
        srv.terminate()
