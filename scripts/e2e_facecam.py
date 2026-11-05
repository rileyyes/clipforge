"""Browser end-to-end test of the face cam + smoother jump cuts (Phase 9).

A game recording (two pieces with a bit cut out = a jump cut) and a separately
recorded webcam video (a person, its mic 1 s behind) -> Editor -> Face cam tab ->
Add face cam (lines up by sound automatically) -> top-left circle -> crop to face ->
remove background (prepared in the background) -> hide a stretch -> preview layer
checked -> Smooth jump cuts (zoom punch-in) -> undo/redo -> reload keeps it all ->
export validates and shows the cam where it should be. Fails on console/page errors.

Run:  python scripts/e2e_facecam.py      (needs Playwright + built frontend)
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

import numpy as np
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="clipforge-e2e-cam-"))
PORT = 8803
B = f"http://127.0.0.1:{PORT}"
PERSON = ROOT / "backend" / "tests" / "data" / "person.jpg"
RATE = 8000


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-ClipForge": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def wait_job(jid, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        j = api("GET", f"/api/jobs/{jid}")
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.3)
    raise TimeoutError(jid)


def talk(seconds, seed):
    rng = np.random.default_rng(seed)
    x = np.zeros(int(seconds * RATE))
    t = 0.3
    while t < seconds - 1:
        d = rng.uniform(0.08, 0.6)
        n = int(d * RATE)
        x[int(t * RATE):int(t * RATE) + n] += rng.normal(0, 1, n) * np.hanning(n) * rng.uniform(0.2, 1)
        t += d + rng.uniform(0.05, 0.9)
    return x / np.abs(x).max() * 0.7


def setup() -> tuple[str, str, str]:
    d = 24
    voice = talk(d + 2, 7)
    game_a, cam_a = TMP / "game.f32", TMP / "cam.f32"
    voice[:d * RATE].astype(np.float32).tofile(game_a)
    # the webcam started 1 s later, so its copy of the voice is 1 s earlier in its file
    (np.convolve(voice[RATE:(d + 1) * RATE], np.ones(5) / 5, "same") * 0.5).astype(np.float32).tofile(cam_a)
    game, cam = TMP / "game.mp4", TMP / "webcam.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={d}",
                    "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", str(game_a), "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(game)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-t", str(d), "-i", str(PERSON),
                    "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", str(cam_a), "-shortest",
                    "-vf", "scale=360:360,pad=640:480:260:60:color=0x406080,format=yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(cam)], check=True)
    p = api("POST", "/api/projects", {"name": "Let's play"})
    g = api("POST", f"/api/projects/{p['id']}/media?filename=game.mp4", raw=game.read_bytes())
    c = api("POST", f"/api/projects/{p['id']}/media?filename=webcam.mp4", raw=cam.read_bytes())
    for r in (g, c):
        if r.get("job_id"):
            wait_job(r["job_id"])
    p = api("GET", f"/api/projects/{p['id']}")
    mid = g["media"]["id"]
    link1, link2 = "1" * 32, "2" * 32
    clips = lambda: [  # noqa: E731
        {"id": os.urandom(16).hex(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 8, "link_id": link1},
        {"id": os.urandom(16).hex(), "media_id": mid, "start": 8, "source_in": 10, "source_out": 20, "link_id": link2}]
    v, a = clips(), clips()
    p["timeline"]["tracks"][0]["clips"] = v
    p["timeline"]["tracks"][2]["clips"] = a
    api("PUT", f"/api/projects/{p['id']}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                                   "output": {"width": 1280, "height": 720, "fps": 30, "fit_mode": "fit"}})
    return p["id"], mid, c["media"]["id"]


async def main(pid, game_id, cam_id):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.get_by_role("tab", name="Face cam").click()
        await pg.get_by_label("Face cam video").select_option(cam_id)
        await pg.get_by_role("button", name="Add face cam").click()
        panel = pg.get_by_test_id("facecam-panel")
        await panel.wait_for()
        await panel.get_by_text("started recording after", exact=False).wait_for(timeout=60000)
        offset = float(await pg.get_by_label("Face cam offset").input_value())
        print("lined up by sound: offset", offset)
        assert abs(offset - (-1.0)) < 0.05, offset

        await panel.get_by_role("button", name="↖ Top left").click()
        await panel.get_by_role("button", name="Circle").click()
        await pg.get_by_label("Face cam size").fill("0.3")
        await panel.get_by_role("button", name="Crop to my face").click()
        await pg.get_by_text("Cropped around your face").wait_for(timeout=60000)
        await pg.get_by_label("Remove background").check()
        await panel.get_by_text("Ready for export").wait_for(timeout=180000)

        # preview: nothing in the first second (the webcam started 1 s after the game) ...
        await pg.locator(".monitor").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Home")
        await pg.wait_for_timeout(300)
        layer = pg.get_by_test_id("facecam-layer")
        assert await layer.evaluate("e => getComputedStyle(e).visibility") == "hidden"
        # ... then a circle in the top-left of the monitor
        for _ in range(45):
            await pg.keyboard.press("ArrowRight")
        await pg.wait_for_timeout(500)
        screen = await pg.locator(".screen").bounding_box()
        box = await layer.bounding_box()
        radius = await layer.evaluate("e => getComputedStyle(e).borderTopLeftRadius")
        vis = await layer.evaluate("e => getComputedStyle(e).visibility")
        print("preview layer:", {k: round(v) for k, v in box.items()}, "screen:", {k: round(v) for k, v in screen.items()}, radius, vis)
        assert vis == "visible" and radius == "50%"
        assert box["x"] < screen["x"] + screen["width"] * 0.1 and box["y"] < screen["y"] + screen["height"] * 0.15
        assert abs(box["width"] - box["height"]) < 2 and abs(box["width"] / screen["width"] - 0.3) < 0.02

        # hide a stretch: 2 s -> 3 s (30 frames each)
        for _ in range(15):
            await pg.keyboard.press("ArrowRight")
        await panel.get_by_role("button", name="Hide from here").click()
        for _ in range(30):
            await pg.keyboard.press("ArrowRight")
        await panel.get_by_role("button", name="…hide until here").click()
        await panel.get_by_text("Hidden").wait_for()
        await pg.keyboard.press("ArrowLeft")
        await pg.wait_for_timeout(300)
        assert await layer.evaluate("e => getComputedStyle(e).visibility") == "hidden"

        # jump cut: 0-8 then 10-20 of the same recording
        await pg.get_by_label("Smooth jump cuts").select_option("punch")
        await pg.get_by_text("1 jump cut smoothed with zoom punch-ins").wait_for()
        await pg.keyboard.press("Control+z")
        await pg.get_by_text("Undo: Smooth jump cuts").wait_for()
        await pg.keyboard.press("Control+Shift+z")
        await pg.get_by_text("Redo: Smooth jump cuts").wait_for()
        await pg.get_by_text("All changes saved").wait_for(timeout=15000)
        await pg.screenshot(path=str(TMP / "editor_facecam.png"))

        # reload: everything is still there
        await pg.reload()
        await pg.locator(".clip.video").first.wait_for()
        await pg.get_by_role("tab", name="Face cam").click()
        await pg.get_by_test_id("facecam-panel").get_by_text("Hidden").wait_for()
        p = api("GET", f"/api/projects/{pid}")
        fc = p["facecam"]
        print("saved:", {k: fc[k] for k in ("corner", "shape", "size", "remove_bg", "offset")}, "hidden", fc["hidden"], "crop", fc["crop"])
        assert fc["corner"] == "top_left" and fc["shape"] == "circle" and fc["remove_bg"] and abs(fc["size"] - 0.3) < 1e-6
        assert len(fc["hidden"]) == 1 and abs(fc["hidden"][0]["start"] - 2) < 0.05 and abs(fc["hidden"][0]["end"] - 3) < 0.05
        assert fc["crop"]["left"] > 0.1
        assert p["timeline"]["tracks"][0]["clips"][1]["crop"]["left"] > 0.05  # the punch-in

        job = api("POST", f"/api/projects/{pid}/exports", {"filename": "cam", "quality": "draft"})
        j = wait_job(job["id"], 600)
        assert j["status"] == "succeeded" and j["result"]["validation"]["ok"], j
        out = TMP / "ws" / "projects" / pid / "exports" / j["result"]["file"]
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(out), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        f = np.frombuffer(raw, np.uint8).reshape(720, 1280, 3).astype(int)
        hid = subprocess.run(["ffmpeg", "-v", "error", "-ss", "2.5", "-i", str(out), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        h = np.frombuffer(hid, np.uint8).reshape(720, 1280, 3).astype(int)
        # top-left cam area: the person's orange suit / skin vs the test pattern when hidden
        region = (slice(40, 400), slice(40, 400))
        diff = np.abs(f[region] - h[region]).mean()
        print("export validated; cam area differs from the hidden moment by", round(float(diff), 1))
        assert diff > 15
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
