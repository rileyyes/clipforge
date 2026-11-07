"""Browser end-to-end test of Phase 17 (polish).

At 1280×720:
- Settings → "Show the tour again" → the editor opens with the tour; every step's card is
  fully on screen, and the highlighted part is really there; keys don't reach the editor
  behind it; "Start editing" ends it and it doesn't come back on reload; Esc skips it.
- Drag a clip later on the timeline: the title, marker and blur on it move with it; the
  ones on the clip that stayed don't. Ctrl+Z puts everything back.
Fails on console/page errors.

Run:  python scripts/e2e_phase17.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p17-"))
PORT = 8811
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def make(path, d, color):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=30:d={d}", "-f", "lavfi",
                    "-i", f"sine=f=300:d={d}", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return path


def hexid():
    return os.urandom(16).hex()


def setup():
    v = make(TMP / "main.mp4", 20, "gray")
    p = api("POST", "/api/projects", {"name": "Polish"})
    pid = p["id"]
    mid = api("POST", f"/api/projects/{pid}/media?filename=main.mp4", raw=v.read_bytes())["media"]["id"]
    p = api("GET", f"/api/projects/{pid}")
    links = [hexid(), hexid()]
    mk = lambda s, a, b, link: {"id": hexid(), "media_id": mid, "start": s, "source_in": a, "source_out": b, "link_id": link}  # noqa: E731
    t = p["timeline"]
    t["tracks"][0]["clips"] = [mk(0, 0, 4, links[0]), mk(4, 8, 12, links[1])]
    t["tracks"][2]["clips"] = [mk(0, 0, 4, links[0]), mk(4, 8, 12, links[1])]
    t["titles"] = [{"id": hexid(), "start": 1, "template": "lower_third", "text": "On A"},
                   {"id": hexid(), "start": 5, "template": "lower_third", "text": "On B"}]
    t["markers"] = [{"id": hexid(), "t": 2, "label": "A"}, {"id": hexid(), "t": 6, "label": "B"}]
    t["blurs"] = [{"id": hexid(), "start": 5.5, "duration": 1, "keys": [{"t": 5.5, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]}]
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": t,
                                               "output": {"width": 1280, "height": 720, "fps": 30, "fit_mode": "fit"}})
    return pid


def tl(pid):
    return api("GET", f"/api/projects/{pid}")["timeline"]


def overlays(t):
    return ([x["start"] for x in t["titles"]], [m["t"] for m in t["markers"]], [b["start"] for b in t["blurs"]],
            [k["t"] for b in t["blurs"] for k in b["keys"]])


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=20000)  # noqa: E731

        async def saved():
            await pg.wait_for_timeout(150)
            await pg.wait_for_function("() => /All changes saved/.test(document.body.innerText) && !/Unsaved|Saving/.test(document.querySelector('.ed-top')?.innerText || '')", timeout=15000)

        # ---- an automated browser doesn't get the tour by itself
        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.wait_for_timeout(500)
        assert await pg.get_by_test_id("tour").count() == 0

        # ---- Settings → Show the tour again → editor shows it
        await pg.goto(B + "/#/settings")
        await pg.get_by_role("button", name="Show the tour again").click()
        await toast("The tour starts next time")
        await pg.goto(B + f"/#/editor/{pid}")
        tour = pg.get_by_test_id("tour")
        await tour.wait_for()
        card = pg.get_by_role("dialog")
        steps = int((await card.locator(".tour-count").inner_text()).split("/")[1])
        print("tour steps:", steps)
        assert steps >= 5
        for k in ("s", "Delete", "m"):            # editor shortcuts must not reach the editor behind the tour
            await pg.keyboard.press(k)
        assert (await card.locator(".tour-count").inner_text()).startswith("1 /")
        for i in range(steps):
            await pg.wait_for_timeout(300)        # the highlight glides into place
            cb = await card.bounding_box()
            assert cb["x"] >= 0 and cb["y"] >= 0 and cb["x"] + cb["width"] <= 1280 and cb["y"] + cb["height"] <= 720, (i, cb)
            hole = pg.locator(".tour-hole")
            title = await card.locator("h3").inner_text()
            if await hole.count():
                hb = await hole.bounding_box()
                assert hb["width"] > 20 and hb["height"] > 20, (i, hb)
                assert hb["x"] >= 0 and hb["y"] >= 0 and hb["x"] + hb["width"] <= 1280 and hb["y"] + hb["height"] <= 720, (i, hb)
                small = hb["width"] * hb["height"] < 0.5 * 1280 * 720
                overlap = not (cb["x"] >= hb["x"] + hb["width"] or cb["x"] + cb["width"] <= hb["x"]
                               or cb["y"] >= hb["y"] + hb["height"] or cb["y"] + cb["height"] <= hb["y"])
                assert not (small and overlap), (title, cb, hb)
                print(f"  {i + 1}. {title}: card {[round(v) for v in cb.values()]}, highlight {[round(v) for v in hb.values()]}")
            else:
                print(f"  {i + 1}. {title}: centred")
            await pg.screenshot(path=str(TMP / f"tour_{i + 1}.png"))
            if i == 1:                             # Back works
                await card.get_by_role("button", name="Back").click()
                assert (await card.locator(".tour-count").inner_text()).startswith("1 /")
                await card.get_by_role("button", name="Next").click()
            await card.get_by_role("button", name="Start editing" if i == steps - 1 else "Next").click()
        await tour.wait_for(state="detached")
        t0 = tl(pid)
        assert len(t0["tracks"][0]["clips"]) == 2 and len(t0["markers"]) == 2, "a key reached the editor during the tour"
        await pg.reload()
        await pg.locator(".clip.video").first.wait_for()
        await pg.wait_for_timeout(500)
        assert await pg.get_by_test_id("tour").count() == 0, "tour came back after finishing it"
        # Esc skips it
        await pg.goto(B + "/#/settings")
        await pg.get_by_role("button", name="Show the tour again").click()
        await pg.goto(B + f"/#/editor/{pid}")
        await tour.wait_for()
        await pg.keyboard.press("Escape")
        await tour.wait_for(state="detached")

        # ---- dragging clip B later carries its title, marker and blur
        await pg.locator(".clip.video").first.wait_for()
        await pg.get_by_role("button", name="Snap", exact=True).click()       # snapping off: exact moves
        v = pg.locator(".clip.video")
        c1 = await v.nth(0).bounding_box()
        pps = c1["width"] / 4.0
        box = await v.nth(1).bounding_box()
        await pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await pg.mouse.down()
        await pg.mouse.move(box["x"] + box["width"] / 2 + pps * 3, box["y"] + box["height"] / 2, steps=12)
        await pg.mouse.up()
        await saved()
        t = tl(pid)
        starts = [c["start"] for c in t["tracks"][0]["clips"]]
        ti, mk, bl, keys = overlays(t)
        print("after dragging clip B by 3 s: clips", starts, "titles", ti, "markers", mk, "blur", bl, keys)
        d = starts[1] - 4
        assert abs(d - 3) < 0.1, starts
        assert ti[0] == 1 and abs(ti[1] - (5 + d)) < 1e-3, ti
        assert mk[0] == 2 and abs(mk[1] - (6 + d)) < 1e-3, mk
        assert abs(bl[0] - (5.5 + d)) < 1e-3 and abs(keys[0] - (5.5 + d)) < 1e-3, (bl, keys)
        # the overlay lane shows the title at its new place
        await pg.get_by_test_id("ov-title").nth(1).wait_for()
        await pg.screenshot(path=str(TMP / "moved.png"))

        # ---- one undo puts the clip and everything on it back
        await pg.locator(".timeline").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Control+z")
        await saved()
        ti, mk, bl, keys = overlays(tl(pid))
        print("after undo: titles", ti, "markers", mk, "blur", bl)
        assert ti == [1, 5] and mk == [2, 6] and bl == [5.5], (ti, mk, bl)

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
