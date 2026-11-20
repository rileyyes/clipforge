"""Browser end-to-end test of Phase 22 (editor UI: resizable panels, tool search, folding
sections, title gallery, tab bar, track headers, media bin, light theme).

- Dragging the divider between the preview and the tool panel makes the panel wider; the size
  is kept after a reload; double-clicking the divider puts it back. Arrow keys on a focused
  divider move it too.
- The media bin folds to a thin strip (kept after a reload) and opens again.
- The timeline divider makes the timeline taller (kept).
- Ctrl+K → "mixer" → Enter opens the Music tab at the Sound mixer and unfolds it if folded.
- Clicking a section heading folds it (kept after a reload).
- Text tab: a gallery of previews in groups; clicking "Percent ring" adds one.
- Clicking a clip while on another tab puts a dot on the Clip tab (the open tab stays).
- Track headers say Voice / Music and the mixer level.
- The theme button switches to the light theme (kept).
- At 1024×640 nothing sticks out of the panels and the preview stays usable.

Run:  python scripts/e2e_phase22.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p22-"))
WS = TMP / "ws"
PORT = 8824
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def wait_job(jid):
    for _ in range(600):
        j = api("GET", f"/api/jobs/{jid}")
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.2)
    raise TimeoutError(jid)


def setup():
    v, s = TMP / "talk.mp4", TMP / "song.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=20", "-f", "lavfi", "-i", "sine=f=300:d=20",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(v)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=20", str(s)], check=True)
    pid = api("POST", "/api/projects", {"name": "UI"})["id"]
    ids = []
    for f in (v, s):
        r = api("POST", f"/api/projects/{pid}/media?filename={f.name}", raw=f.read_bytes())
        assert wait_job(r["job_id"])["status"] == "succeeded"
        ids.append(r["media"]["id"])
    p = api("GET", f"/api/projects/{pid}")
    t = p["timeline"]
    link = os.urandom(16).hex()
    t["tracks"][0]["clips"] = [{"id": os.urandom(16).hex(), "media_id": ids[0], "start": 0, "source_in": 0, "source_out": 20, "link_id": link}]
    t["tracks"][2]["clips"] = [{"id": os.urandom(16).hex(), "media_id": ids[0], "start": 0, "source_in": 0, "source_out": 20, "link_id": link}]
    t["tracks"][3]["clips"] = [{"id": os.urandom(16).hex(), "media_id": ids[1], "start": 0, "source_in": 0, "source_out": 20}]
    t["tracks"][3]["role"] = "music"
    t["tracks"][3]["volume"] = 0.4
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": t, "output": p["output"]})
    return pid


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1280, "height": 720})
        await ctx.add_init_script("try { if (!sessionStorage.getItem('rj-e2e')) { localStorage.setItem('rj:tour', 'done'); sessionStorage.setItem('rj-e2e', '1'); } } catch {}")
        pg = await ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))

        async def width(sel):
            return await pg.locator(sel).first.evaluate("e => Math.round(e.getBoundingClientRect().width)")

        async def open_editor():
            await pg.goto(B + f"/#/editor/{pid}")
            await pg.locator(".clip.video").first.wait_for()
            await pg.wait_for_timeout(300)

        async def no_overflow(where):
            wide = await pg.evaluate("""() => [...document.querySelectorAll('.pane-body, .transport, .pane-head')].filter(p => p.offsetParent).flatMap(p => {
                const r = p.getBoundingClientRect(); return [...p.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
                return b.width > 0 && b.height > 0 && (b.right > r.right + 1 || b.left < r.left - 1) && !e.closest('.tg-thumb'); }).map(e => e.outerHTML.slice(0, 120)); }).slice(0, 5)""")
            assert not wide, (where, wide)

        await open_editor()
        side0 = await width(".pane.side")
        print("tool panel at 1280x720:", side0)
        assert 270 <= side0 <= 290, side0
        # ---- drag the tool panel wider
        sp = pg.get_by_label("Resize the tool panel")
        bb = await sp.bounding_box()
        await pg.mouse.move(bb["x"] + 3, bb["y"] + 150)
        await pg.mouse.down()
        await pg.mouse.move(bb["x"] - 150, bb["y"] + 150, steps=6)
        await pg.mouse.up()
        side1 = await width(".pane.side")
        assert abs(side1 - (side0 + 153)) <= 6, (side0, side1)
        await open_editor()
        assert abs(await width(".pane.side") - side1) <= 2                   # kept
        await sp.focus()
        await pg.keyboard.press("ArrowLeft")
        assert abs(await width(".pane.side") - (side1 + 16)) <= 2
        await sp.dblclick()
        assert abs(await width(".pane.side") - side0) <= 2                    # back to normal
        # ---- fold the media bin away
        prev0 = await width(".monitor")
        await pg.get_by_label("Hide the media panel").click()
        await pg.get_by_test_id("media-strip").wait_for()
        assert await width(".monitor") > prev0 + 120
        await open_editor()
        await pg.get_by_test_id("media-strip").wait_for()                     # kept
        await pg.get_by_label("Show the media panel").click()
        await pg.get_by_label("Hide the media panel").wait_for()
        # ---- timeline taller
        tl0 = await pg.locator(".editor").evaluate("e => parseInt(getComputedStyle(e).getPropertyValue('--tl-h'))")
        sb = await pg.get_by_label("Resize the timeline").bounding_box()
        await pg.mouse.move(sb["x"] + 300, sb["y"] + 3)
        await pg.mouse.down()
        await pg.mouse.move(sb["x"] + 300, sb["y"] - 60, steps=5)
        await pg.mouse.up()
        tl1 = await pg.locator(".editor").evaluate("e => parseInt(getComputedStyle(e).getPropertyValue('--tl-h'))")
        assert abs(tl1 - (tl0 + 63)) <= 4, (tl0, tl1)

        # ---- track headers
        subs = await pg.get_by_test_id("track-sub").all_inner_texts()
        print("track headers:", subs)
        assert "Voice" in subs[2] and "Music" in subs[3] and "40%" in subs[3], subs

        # ---- fold a section, find it with Ctrl+K
        await pg.get_by_role("tab", name="Music", exact=True).click()
        head = pg.locator(".insp-section h3[role=button]", has_text="Sound mixer")
        await head.click()
        mixer = pg.get_by_test_id("mixer")
        await pg.wait_for_function("() => document.querySelector('[data-testid=mixer]')?.hasAttribute('data-folded')")
        await pg.wait_for_function("() => (localStorage.getItem('cf:folded') || '').includes('sound mixer')")
        assert not await pg.get_by_test_id("mixer-row").first.is_visible()
        await open_editor()
        await pg.get_by_role("tab", name="Music", exact=True).click()
        await pg.wait_for_function("() => document.querySelector('[data-testid=mixer]')?.hasAttribute('data-folded')")   # kept
        await pg.get_by_role("tab", name="Text", exact=True).click()
        await pg.keyboard.press("Control+k")
        box = pg.get_by_role("combobox", name="Find a tool")
        await box.wait_for()
        await box.fill("mixer")
        await pg.get_by_role("option", name="Sound mixer").wait_for()
        await box.press("Enter")
        await pg.wait_for_function("() => document.querySelector('[data-testid=mixer]') && !document.querySelector('[data-testid=mixer]').hasAttribute('data-folded')")
        assert await pg.get_by_role("tab", name="Music", exact=True).get_attribute("aria-selected") == "true"
        assert await pg.get_by_test_id("mixer-row").first.is_visible()
        # an action
        await pg.keyboard.press("Control+k")
        await box.fill("shortcuts")
        await box.press("Enter")
        await pg.get_by_role("heading", name="Keyboard shortcuts").wait_for()
        await pg.get_by_role("button", name="Close").click()
        await pg.keyboard.press("Control+k")
        await box.fill("qqqq")
        await pg.get_by_text("Nothing called").wait_for()
        await pg.keyboard.press("Escape")
        assert not await pg.get_by_test_id("tool-search").count()

        # ---- title gallery
        await pg.get_by_role("tab", name="Text", exact=True).click()
        gal = pg.get_by_test_id("title-gallery")
        groups = await gal.locator(".tg-head").all_inner_texts()
        assert groups == ["Titles", "Arrows & shapes", "Motion graphics", "YouTube"], groups
        assert await gal.locator(".tg-card").count() >= 20
        assert not await gal.locator("[data-testid=title-preview]").count()               # samples aren't mistaken for titles
        await gal.get_by_role("button", name="Percent ring", exact=True).click()
        await pg.wait_for_function("() => document.querySelector('[data-testid=title-preview][data-template=ring]')")
        await pg.screenshot(path=str(TMP / "gallery.png"))

        # ---- picking a clip on another tab: the Clip tab gets a dot (the open tab stays)
        await pg.get_by_role("tab", name="History", exact=True).click()
        await pg.locator(".clip.video").first.click()
        clip_tab = pg.get_by_role("tab", name="Clip", exact=True)
        assert "attn" in (await clip_tab.get_attribute("class")) and await pg.get_by_role("tab", name="History", exact=True).get_attribute("aria-selected") == "true"
        await clip_tab.click()
        assert "attn" not in (await clip_tab.get_attribute("class"))

        # ---- light theme
        await pg.get_by_role("button", name="Switch to the light theme").click()
        assert await pg.evaluate("document.documentElement.dataset.theme") == "light"
        await open_editor()
        assert await pg.evaluate("document.documentElement.dataset.theme") == "light"
        bg = await pg.locator(".pane.side").evaluate("e => getComputedStyle(e).backgroundColor")
        assert bg == "rgb(255, 255, 255)", bg
        await pg.screenshot(path=str(TMP / "light.png"))
        await pg.get_by_role("button", name="Switch to the dark theme").click()
        await no_overflow("1280x720")

        # ---- a small window
        await pg.set_viewport_size({"width": 1024, "height": 640})
        await pg.wait_for_timeout(400)
        mon = await width(".monitor")
        print("preview width at 1024x640:", mon)
        assert mon >= 300, mon
        for tab in ("Clip", "Text", "Music", "AI"):
            await pg.get_by_role("tab", name=tab, exact=True).click()
            await pg.wait_for_timeout(150)
            await no_overflow(f"1024x640 {tab}")
        await pg.screenshot(path=str(TMP / "small.png"))
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    env = {**os.environ, "RJCLIP_WORKSPACE": str(WS), "RJCLIP_PORT": str(PORT), "RJCLIP_TRANSCRIBER": "off"}
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
