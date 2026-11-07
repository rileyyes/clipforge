"""Browser end-to-end test of Phase 15 (pro look).

At 1280×720: Settings → Brand kit (logo, intro, corner) -> Editor → Text → Apply my brand
kit (logo watermark + intro at the start) -> add an Arrow and drag it on the preview ->
Clip tab: green screen on the V2 clip, picture-in-picture layout, freeze frame, slow-mo
ramp, reverse -> export: logo top-left, green keyed out, intro first. The side panel must
fit. Fails on page errors.

Run:  python scripts/e2e_phase15.py      (needs Playwright + built frontend)
"""
import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p15-"))
PORT = 8809
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


def setup():
    main, cam, intro = TMP / "main.mp4", TMP / "cam.mp4", TMP / "intro.mp4"
    ff("-f", "lavfi", "-i", "color=c=0x303030:s=640x360:r=30:d=30", "-f", "lavfi", "-i", "sine=f=220:d=30", "-shortest",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(main))
    ff("-f", "lavfi", "-i", "color=c=0x00ff00:s=640x360:r=30:d=10,drawbox=x=270:y=130:w=100:h=100:c=red:t=fill",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(cam))
    ff("-f", "lavfi", "-i", "color=c=purple:s=640x360:r=30:d=2", "-f", "lavfi", "-i", "sine=f=500:d=2", "-shortest",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(intro))
    buf = io.BytesIO()
    Image.new("RGBA", (200, 200), (255, 220, 0, 255)).save(buf, "PNG")
    (TMP / "logo.png").write_bytes(buf.getvalue())
    p = api("POST", "/api/projects", {"name": "Pro look"})
    pid = p["id"]
    m1 = api("POST", f"/api/projects/{pid}/media?filename=main.mp4", raw=main.read_bytes())["media"]["id"]
    m2 = api("POST", f"/api/projects/{pid}/media?filename=cam.mp4", raw=cam.read_bytes())["media"]["id"]
    p = api("GET", f"/api/projects/{pid}")
    link = os.urandom(16).hex()
    mk = lambda m, a, b, l=None: {"id": os.urandom(16).hex(), "media_id": m, "start": a, "source_in": a, "source_out": b, "link_id": l}  # noqa: E731
    p["timeline"]["tracks"][0]["clips"] = [mk(m1, 0, 30, link)]
    p["timeline"]["tracks"][2]["clips"] = [mk(m1, 0, 30, link)]
    p["timeline"]["tracks"][1]["clips"] = [mk(m2, 0, 8)]
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                               "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"}})
    return pid


def tl(pid):
    return api("GET", f"/api/projects/{pid}")["timeline"]


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=30000)  # noqa: E731

        async def until(fn, what, timeout=20):
            end = time.time() + timeout
            while time.time() < end:
                try:
                    if fn():
                        return
                except Exception:
                    pass
                await pg.wait_for_timeout(250)
            raise AssertionError(what)

        async def overflow():
            return await pg.evaluate("""() => { const col = document.querySelector('.ed-mid').lastElementChild.getBoundingClientRect();
                return [...document.querySelectorAll('.ed-mid > :last-child *')].filter(e => e.getClientRects().length
                  && e.getBoundingClientRect().right > col.right + 1).map(e => e.tagName + '.' + e.className).slice(0, 8) }""")

        # ---- brand kit in Settings
        await pg.goto(B + "/#/settings")
        kit = pg.get_by_test_id("brand-kit")
        await kit.wait_for()
        async with pg.expect_file_chooser() as fc:
            await kit.get_by_role("button", name="Upload logo").click()
        await (await fc.value).set_files(str(TMP / "logo.png"))
        await toast("Logo saved")
        async with pg.expect_file_chooser() as fc:
            await kit.get_by_role("button", name="Choose video").first.click()
        await (await fc.value).set_files(str(TMP / "intro.mp4"))
        await toast("Intro saved")
        await pg.get_by_label("Logo corner").select_option("tl")
        await until(lambda: api("GET", "/api/brand")["brand"]["logo_corner"] == "tl", "corner not saved")
        await pg.screenshot(path=str(TMP / "settings_brand.png"))

        # ---- apply it in the Editor
        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.get_by_role("tab", name="Text", exact=True).click()
        await pg.get_by_test_id("brand-apply").get_by_role("button", name="Apply my brand kit").click()
        await toast("Brand kit applied")
        await until(lambda: api("GET", f"/api/projects/{pid}")["watermark"]["corner"] == "tl", "watermark not set")
        await until(lambda: tl(pid)["tracks"][0]["clips"][0]["label"] == "Intro" and tl(pid)["tracks"][0]["clips"][1]["start"] > 1.9,
                    "intro not placed first")
        await pg.get_by_test_id("watermark-preview").wait_for()
        print("brand kit applied; V1 starts:", [round(c["start"], 2) for c in tl(pid)["tracks"][0]["clips"]])

        # ---- an arrow, dragged on the preview
        await pg.keyboard.press("Home")
        for _ in range(90):
            await pg.keyboard.press("ArrowRight")                        # 3.0 s
        await pg.get_by_role("button", name="Arrow").click()
        await until(lambda: any(t["template"] == "arrow" for t in tl(pid).get("titles", [])), "arrow not added")
        arrow = pg.locator("[data-testid=title-preview][data-template=arrow]")
        await pg.wait_for_timeout(800)
        await arrow.wait_for()
        bb = await arrow.bounding_box()
        await pg.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        await pg.mouse.down()
        await pg.mouse.move(bb["x"] + bb["width"] / 2 + 120, bb["y"] + bb["height"] / 2 + 40, steps=8)
        await pg.mouse.up()
        await until(lambda: next(t for t in tl(pid)["titles"] if t["template"] == "arrow")["x"] > 0.5, "arrow not moved")
        print("arrow at", {k: round(next(t for t in tl(pid)["titles"] if t["template"] == "arrow")[k], 3) for k in ("x", "y", "rotation")})
        assert not await overflow(), await overflow()

        # ---- Clip tab: green screen on V2, picture-in-picture
        await pg.get_by_role("tab", name="Clip", exact=True).click()
        await pg.locator(".lane[data-track='V2'] .clip").first.click()
        await pg.get_by_label("Green screen").check()
        await until(lambda: tl(pid)["tracks"][1]["clips"][0].get("chroma"), "green screen not saved")
        await pg.get_by_role("button", name="Picture-in-picture").click()
        await until(lambda: tl(pid)["tracks"][1]["clips"][0]["transform"]["scale"] == 0.3, "layout not applied")
        assert not await overflow(), await overflow()
        await pg.screenshot(path=str(TMP / "editor_pro.png"))

        # ---- freeze frame at 15 s, slow-mo ramp at 22 s, reverse the last piece
        async def to(sec):
            """Click the ruler at `sec` (pixels per second from the intro clip, which is 2 s long)."""
            intro = await pg.locator(".lane[data-track='V1'] .clip").first.bounding_box()
            pps = intro["width"] / 2.0
            ruler = await pg.locator(".ruler").bounding_box()
            await pg.mouse.click(intro["x"] + sec * pps, ruler["y"] + 20)
        main_clips = lambda: [c for c in tl(pid)["tracks"][0]["clips"] if c.get("label") != "Intro"]  # noqa: E731
        await to(15)
        await pg.keyboard.press("Escape")
        await pg.get_by_label("Freeze seconds").fill("1.5")
        await pg.get_by_role("button", name="Freeze frame").click()
        await toast("Froze")
        await until(lambda: len(main_clips()) == 3, "freeze not inserted")
        await to(24)
        await pg.locator(".lane[data-track='V1'] .clip").last.click()
        await to(24)
        await pg.get_by_role("button", name="Slow-mo").click()
        await until(lambda: min(c["speed"] for c in main_clips()) < 0.5, "ramp not applied")
        print("V1 after freeze + ramp:", len(main_clips()), "clips; speeds", sorted({round(c["speed"], 2) for c in main_clips()}))
        await pg.locator(".lane[data-track='V1'] .clip").last.click()
        await pg.get_by_role("button", name="Reverse this clip").click()
        await toast("Reversed")
        await until(lambda: "Reversed" in json.dumps(api("GET", f"/api/projects/{pid}")["media"]), "reverse not made")
        assert not errs, errs
        await b.close()

    # ---- export
    j = api("POST", f"/api/projects/{pid}/exports", {"filename": "pro", "quality": "draft"})
    for _ in range(1200):
        j = api("GET", f"/api/jobs/{j['id']}")
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    assert j["status"] == "succeeded", j.get("error_detail")
    out = TMP / "ws" / "projects" / pid / "exports" / j["result"]["file"]

    def frame(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-s", "640x360", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(360, 640, 3).astype(int)
    intro_px, f5 = frame(1.0)[180, 320], frame(5.0)
    yellow = (f5[:, :, 0] > 200) & (f5[:, :, 1] > 180) & (f5[:, :, 2] < 90)
    ys, xs = np.nonzero(yellow)
    green = ((f5[:, :, 1] > 200) & (f5[:, :, 0] < 80) & (f5[:, :, 2] < 80)).mean()
    print(f"intro pixel {intro_px.tolist()}, logo at x {xs.min()}-{xs.max()} y {ys.min()}-{ys.max()}, green left {green:.4f}")
    assert intro_px[0] > 90 and intro_px[2] > 90 and intro_px[1] < 60                  # purple intro first
    assert xs.max() < 140 and ys.max() < 140                                            # logo top-left
    assert green < 0.002                                                                 # green screen keyed out


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
