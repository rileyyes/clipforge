"""Browser end-to-end test of Phase 11 polish.

At 1280×720 (a common laptop): nothing on the Editor or AI Auto Editor runs off the
screen -> titles and blurs show on the timeline lane; click opens the Text tab with it
selected, dragging moves it, dragging the edge resizes it -> transitions preview in the
monitor (outgoing picture on top, fading) -> ? opens the shortcut sheet; J/K/L ->
safe-area guides (landscape and Shorts) -> ripple delete moves a title along -> undo.
Fails on console/page errors.

Run:  python scripts/e2e_phase11.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p11-"))
PORT = 8805
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def setup():
    v = TMP / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=20", "-f", "lavfi",
                    "-i", "sine=f=300:d=20", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(v)], check=True)
    p = api("POST", "/api/projects", {"name": "Polish"})
    r = api("POST", f"/api/projects/{p['id']}/media?filename=v.mp4", raw=v.read_bytes())
    mid = r["media"]["id"]
    p = api("GET", f"/api/projects/{p['id']}")
    l1, l2 = os.urandom(16).hex(), os.urandom(16).hex()
    mk = lambda s, a, b, link, **kw: {"id": os.urandom(16).hex(), "media_id": mid, "start": s, "source_in": a, "source_out": b, "link_id": link, **kw}  # noqa: E731
    p["timeline"]["tracks"][0]["clips"] = [mk(0, 0, 6, l1), mk(6, 8, 14, l2, transition_in={"kind": "crossfade", "duration": 1.0})]
    p["timeline"]["tracks"][2]["clips"] = [mk(0, 0, 6, l1), mk(6, 8, 14, l2)]
    p["timeline"]["titles"] = [{"id": "a" * 32, "start": 8, "duration": 2, "template": "lower_third", "text": "Hello"}]
    p["timeline"]["blurs"] = [{"id": "b" * 32, "start": 1, "duration": 2, "keys": [{"t": 1, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]}]
    api("PUT", f"/api/projects/{p['id']}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                                   "output": {"width": 1280, "height": 720, "fps": 30, "fit_mode": "fit"}})
    return p["id"]


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=20000)  # noqa: E731

        # ---- fits a 1280×720 screen
        # checked twice: as drawn here, and with wider text (other machines'
        # fonts can be a few % wider, which once pushed the Editor off-screen)
        for url, wide in [(u, w) for w in (False, True) for u in (f"/#/editor/{pid}", f"/#/auto/{pid}")]:
            await pg.goto(B + url)
            if wide:
                await pg.evaluate("""() => { const st = document.createElement('style'); st.id = 'e2e-wide';
                    st.textContent = '* { letter-spacing: 0.6px !important }'; document.head.appendChild(st) }""")
            await pg.wait_for_timeout(1500)
            over = await pg.evaluate("""() => [...document.querySelectorAll('.editor, .main > *')].map(e => e.scrollWidth - e.clientWidth)
                .concat([document.documentElement.scrollWidth - window.innerWidth])""")
            print(url, "wide text" if wide else "", "overflow px:", over)
            if max(over) > 1:  # name the culprits so a CI failure is easy to fix
                print(await pg.evaluate("""() => { const W = innerWidth; return [...document.querySelectorAll('.editor *, .main *')]
                    .filter(e => e.getBoundingClientRect().right > W + 1 || e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX === 'visible')
                    .slice(0, 12).map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right) + ' sw' + e.scrollWidth + ' cw' + e.clientWidth) }"""))
            assert max(over) <= 1, (url, wide, over)
            await pg.evaluate("() => document.getElementById('e2e-wide')?.remove()")
        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        exp = await pg.get_by_role("button", name="Export").bounding_box()
        assert exp["x"] + exp["width"] <= 1280
        tabs = pg.get_by_role("tab")
        n = await tabs.count()
        assert n == 9, n  # every side tab fits, including the AI tab (Phase 16)
        last = await tabs.nth(n - 1).bounding_box()
        assert last["x"] + last["width"] <= 1281

        # ---- overlay lane: click selects, drag moves, edge resizes
        lane = pg.get_by_test_id("overlay-lane")
        await lane.wait_for()
        title = pg.get_by_test_id("ov-title")
        await title.click()
        await pg.get_by_label("Title text").wait_for()
        assert await pg.get_by_label("Title text").input_value() == "Hello"
        await pg.get_by_role("button", name="Snap", exact=True).click()       # snapping off: exact moves
        box = await title.bounding_box()
        pps = box["width"] / 2.0
        await pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await pg.mouse.down()
        await pg.mouse.move(box["x"] + box["width"] / 2 + pps * 1.0, box["y"] + box["height"] / 2, steps=8)
        await pg.mouse.up()
        await pg.wait_for_timeout(300)
        box = await title.bounding_box()
        await pg.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2)
        await pg.mouse.down()
        await pg.mouse.move(box["x"] + box["width"] - 2 + pps * 1.0, box["y"] + box["height"] / 2, steps=8)
        await pg.mouse.up()
        await pg.get_by_text("All changes saved").wait_for(timeout=15000)
        t = api("GET", f"/api/projects/{pid}")["timeline"]["titles"][0]
        print("title after drag/resize:", t["start"], t["duration"])
        assert abs(t["start"] - 9.0) < 0.15 and abs(t["duration"] - 3.0) < 0.15

        # ---- transition preview: mid-crossfade both pictures show
        await pg.locator(".monitor").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Home")
        for _ in range(6 * 30 - 6):            # 5.8 s: inside the 5.5–6.5 s crossfade
            await pg.keyboard.press("ArrowRight")
        await pg.wait_for_timeout(400)
        out = pg.get_by_test_id("transition-out").first  # V1
        st = await out.evaluate("e => [getComputedStyle(e).visibility, +getComputedStyle(e).opacity]")
        print("transition preview (visibility, opacity of the outgoing clip):", st)
        assert st[0] == "visible" and 0.4 < st[1] < 0.9
        for _ in range(30):
            await pg.keyboard.press("ArrowRight")
        await pg.wait_for_timeout(300)
        assert await out.evaluate("e => getComputedStyle(e).visibility") == "hidden"

        # ---- shortcuts, J/K/L, guides
        await pg.keyboard.press("?")
        await pg.get_by_test_id("shortcuts").wait_for()
        await pg.keyboard.press("Escape")
        await pg.get_by_test_id("shortcuts").wait_for(state="hidden")
        tc = pg.locator(".transport .tc")
        before = await tc.inner_text()
        await pg.keyboard.press("j")
        after = await tc.inner_text()
        print("J:", before, "->", after)
        assert after < before
        await pg.keyboard.press("l")
        await pg.wait_for_timeout(700)
        await pg.keyboard.press("k")
        t1 = await tc.inner_text()
        await pg.wait_for_timeout(500)
        assert await tc.inner_text() == t1 and t1 > after
        await pg.get_by_role("button", name="Safe-area guides").click()
        await pg.get_by_test_id("safe-guides").wait_for()
        await pg.screenshot(path=str(TMP / "editor_1280.png"))

        # ---- ripple delete moves the title along; undo puts it back
        await pg.locator(".clip.video").first.click()
        await pg.keyboard.press("Shift+Delete")
        await pg.wait_for_timeout(300)
        await pg.get_by_text("All changes saved").wait_for(timeout=15000)
        t = api("GET", f"/api/projects/{pid}")["timeline"]["titles"][0]
        print("title after ripple delete:", t["start"])
        assert abs(t["start"] - 3.0) < 0.15
        await pg.keyboard.press("Control+z")
        await pg.get_by_text("All changes saved").wait_for(timeout=15000)
        await pg.wait_for_timeout(1000)
        t = api("GET", f"/api/projects/{pid}")["timeline"]["titles"][0]
        assert abs(t["start"] - 9.0) < 0.15
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
