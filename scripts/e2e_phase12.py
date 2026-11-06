"""Browser end-to-end test of Phase 12 (the editing basics that were skipped).

At 1280×720: a media file goes missing -> the Media panel says so -> Find file relinks
it -> select two clips and drag one: both move (with their sound) -> Ctrl+L unlinks
picture and sound, select both and Ctrl+L links them again -> M adds markers, name
them, Shift+← jumps back, drag a marker, Delete removes one -> Ctrl+A selects every
clip -> the Publish page writes chapters from the markers. The timeline toolbar must
fit without scrolling. Fails on console/page errors.

Run:  python scripts/e2e_phase12.py      (needs Playwright + built frontend)
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="clipforge-e2e-p12-"))
PORT = 8806
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-ClipForge": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def make(path, d, color):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=30:d={d}", "-f", "lavfi",
                    "-i", f"sine=f=300:d={d}", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return path


def setup():
    v = make(TMP / "main.mp4", 30, "gray")
    cam = make(TMP / "broll.mp4", 6, "blue")
    p = api("POST", "/api/projects", {"name": "Basics"})
    pid = p["id"]
    mid = api("POST", f"/api/projects/{pid}/media?filename=main.mp4", raw=v.read_bytes())["media"]["id"]
    r2 = api("POST", f"/api/projects/{pid}/media?filename=broll.mp4", raw=cam.read_bytes())
    p = api("GET", f"/api/projects/{pid}")
    links = [os.urandom(16).hex() for _ in range(3)]
    mk = lambda m, s, a, b, link: {"id": os.urandom(16).hex(), "media_id": m, "start": s, "source_in": a, "source_out": b, "link_id": link}  # noqa: E731
    p["timeline"]["tracks"][0]["clips"] = [mk(mid, 0, 0, 4, links[0]), mk(mid, 4, 6, 10, links[1]), mk(mid, 8, 12, 16, links[2])]
    p["timeline"]["tracks"][2]["clips"] = [mk(mid, 0, 0, 4, links[0]), mk(mid, 4, 6, 10, links[1]), mk(mid, 8, 12, 16, links[2])]
    p["timeline"]["tracks"][1]["clips"] = [mk(r2["media"]["id"], 13, 0, 3, None)]
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                               "output": {"width": 1280, "height": 720, "fps": 30, "fit_mode": "fit"}})
    # the b-roll file "goes missing" (e.g. deleted by hand); a renamed copy is somewhere else
    time.sleep(1.5)  # let its preview job finish with the file
    f = TMP / "ws" / "projects" / pid / "media" / "original" / r2["media"]["stored_name"]
    f.chmod(0o600)
    f.unlink()
    shutil.copy(cam, TMP / "broll (found).mp4")
    return pid, r2["media"]["id"]


def tl(pid):
    return api("GET", f"/api/projects/{pid}")["timeline"]


async def main(pid, missing_id):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=20000)  # noqa: E731

        async def saved():
            """Wait until autosave has really sent the latest edit (not an earlier "saved")."""
            await pg.wait_for_timeout(150)
            await pg.wait_for_function("() => /All changes saved/.test(document.body.innerText) && !/Unsaved|Saving/.test(document.querySelector('.ed-top')?.innerText || '')", timeout=15000)

        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()

        # ---- toolbar fits a 1280-wide screen (no sideways scrolling)
        tools = await pg.locator(".tl-tools").evaluate("e => [e.scrollWidth, e.clientWidth]")
        print("toolbar scroll/client width:", tools)
        assert tools[0] <= tools[1] + 1, tools

        # ---- relink the missing file
        await pg.get_by_test_id("missing-note").wait_for()
        async with pg.expect_file_chooser() as fc:
            await pg.get_by_test_id("relink-btn").click()
        await (await fc.value).set_files(str(TMP / "broll (found).mp4"))
        await toast("Relinked")
        await pg.get_by_test_id("missing-note").wait_for(state="hidden", timeout=20000)
        assert api("GET", f"/api/projects/{pid}")["missing_media"] == []

        # ---- multi-clip drag: select clips 2 and 3, drag clip 2 right by 2 s
        await pg.get_by_role("button", name="Snap", exact=True).click()       # snapping off: exact moves
        v = pg.locator(".clip.video")
        c1 = await v.nth(0).bounding_box()
        pps = c1["width"] / 4.0
        await v.nth(1).click()
        await v.nth(2).click(modifiers=["Control"])
        assert await pg.locator(".clip.video.sel").count() == 2
        box = await v.nth(1).bounding_box()
        await pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await pg.mouse.down()
        await pg.mouse.move(box["x"] + box["width"] / 2 + pps * 2, box["y"] + box["height"] / 2, steps=10)
        await pg.mouse.up()
        await saved()
        t = tl(pid)
        vs = [c["start"] for c in t["tracks"][0]["clips"]]
        aus = [c["start"] for c in t["tracks"][2]["clips"]]
        print("after group drag: video", vs, "audio", aus)
        assert abs(vs[0]) < 1e-6 and abs(vs[1] - 6) < 0.1 and abs(vs[2] - 10) < 0.1 and vs == aus

        # ---- unlink (Ctrl+L), then link again
        await v.nth(0).click()
        await pg.keyboard.press("Control+l")
        await toast("Unlinked")
        await saved()
        t = tl(pid)
        assert t["tracks"][0]["clips"][0]["link_id"] is None and t["tracks"][2]["clips"][0]["link_id"] is None
        await pg.locator(".clip.audio").first.click(modifiers=["Control"])
        assert await pg.get_by_role("button", name="Link", exact=True).is_enabled()
        await pg.keyboard.press("Control+l")
        await toast("Linked")
        await saved()
        t = tl(pid)
        L = t["tracks"][0]["clips"][0]["link_id"]
        assert L and L == t["tracks"][2]["clips"][0]["link_id"]

        # ---- markers
        await pg.keyboard.press("Escape")
        await pg.keyboard.press("Home")
        await pg.keyboard.press("m")
        bar = pg.get_by_test_id("marker-bar")
        await bar.wait_for()
        await pg.get_by_label("Marker name").fill("Intro bit")
        await pg.keyboard.press("Enter")
        await pg.get_by_role("button", name="Done").click()
        ruler = await pg.locator(".ruler").bounding_box()
        scroll_left = await pg.locator(".tl-scroll").evaluate("e => e.scrollLeft")
        x6 = ruler["x"] + 6 * pps - scroll_left
        await pg.mouse.click(x6, ruler["y"] + 20)                             # playhead to 6 s
        await pg.keyboard.press("m")
        await pg.get_by_label("Marker name").fill("Boss fight")
        await pg.keyboard.press("Enter")
        await pg.mouse.click(ruler["x"] + 11 * pps - scroll_left, ruler["y"] + 20)
        await pg.keyboard.press("m")                                          # a third one, deleted below
        await saved()
        ms = tl(pid)["markers"]
        print("markers:", [(round(m["t"], 2), m["label"]) for m in ms])
        assert [m["label"] for m in ms] == ["Intro bit", "Boss fight", ""] and abs(ms[1]["t"] - 6) < 0.1
        await pg.keyboard.press("Delete")                                     # removes the selected (third) marker
        await saved()
        assert len(tl(pid)["markers"]) == 2
        await pg.keyboard.press("Shift+ArrowLeft")
        tc = await pg.locator(".transport .tc").inner_text()
        print("Shift+← jumped to", tc)
        assert tc.startswith("0:06")
        await pg.keyboard.press("Escape")
        flag = pg.get_by_test_id("user-marker").nth(1)
        fb = await flag.bounding_box()
        await pg.mouse.move(fb["x"] + 1, fb["y"] + 5)
        await pg.mouse.down()
        await pg.mouse.move(fb["x"] + 1 + pps, fb["y"] + 5, steps=8)
        await pg.mouse.up()
        await saved()
        ms = tl(pid)["markers"]
        print("after dragging the marker:", [(round(m["t"], 2), m["label"]) for m in ms])
        assert abs(ms[1]["t"] - 7) < 0.15 and ms[1]["label"] == "Boss fight"
        await pg.screenshot(path=str(TMP / "editor_markers.png"))

        # ---- Ctrl+A
        await pg.locator(".monitor").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Control+a")
        n = await pg.locator(".clip").count()
        assert await pg.locator(".clip.sel").count() == n and n == 7, n

        # ---- undo goes back through it all
        await pg.keyboard.press("Control+z")                                  # marker move
        await saved()
        await pg.wait_for_timeout(800)
        assert abs(tl(pid)["markers"][1]["t"] - 6) < 0.15

        # ---- Publish: chapters from the markers
        await pg.goto(B + f"/#/publish/{pid}")
        sel = pg.get_by_label("Chapters from")
        await sel.wait_for()
        assert await sel.input_value() == "markers"
        await pg.get_by_role("button", name="Write it for me").click()
        await toast("chapters come from your markers")
        await pg.wait_for_timeout(1500)
        d = api("GET", f"/api/projects/{pid}/publish")["draft"]
        print("chapters:", d["chapters"])
        assert [c["title"] for c in d["chapters"]] == ["Intro bit", "Boss fight"] and d["chapters"][0]["t"] == 0
        await pg.screenshot(path=str(TMP / "publish_markers.png"))
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    env = {**os.environ, "CLIPFORGE_WORKSPACE": str(TMP / "ws"), "CLIPFORGE_PORT": str(PORT), "CLIPFORGE_TRANSCRIBER": "off"}
    srv = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT / "backend", env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(B + "/api/health")
                break
            except Exception:
                time.sleep(0.2)
        asyncio.run(main(*setup()))
        print("OK — screenshots in", TMP)
    finally:
        srv.terminate()
