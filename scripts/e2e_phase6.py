"""Browser end-to-end test of Phase 6 (advanced editor).

Two clips -> rotation, crop, Black & white look, a 2-keyframe slow zoom (marks on the
timeline, preview follows), volume keyframes on the audio, a wipe transition -> the
monitor preview reflects it -> audio meters move while playing -> light preview makes a
proxy -> export validates and the exported frame really is rotated + grey -> reopen keeps
everything -> the second export reuses the render cache. Fails on console/page errors.

Run:  python scripts/e2e_phase6.py      (needs Playwright + built frontend)
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

import numpy as np
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="clipforge-e2e-p6-"))
PORT = 8797
B = f"http://127.0.0.1:{PORT}"
SRC = TMP / "clip.mp4"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-ClipForge": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def setup() -> tuple[str, str]:
    # colourful picture + a loud tone so meters have something to show
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=440:d=8:sample_rate=48000", "-af", "volume=0.6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(SRC)], check=True)
    p = api("POST", "/api/projects", {"name": "Phase 6 test"})
    pid = p["id"]
    mid = api("POST", f"/api/projects/{pid}/media?filename=clip.mp4", raw=SRC.read_bytes())["media"]["id"]
    p = api("GET", f"/api/projects/{pid}")
    v, a = [], []
    for i, (s, e) in enumerate([(0, 4), (4, 8)]):
        link = uuid.uuid4().hex
        v.append({"id": uuid.uuid4().hex, "media_id": mid, "start": i * 4, "source_in": s, "source_out": e, "link_id": link})
        a.append({"id": uuid.uuid4().hex, "media_id": mid, "start": i * 4, "source_in": s, "source_out": e, "link_id": link})
    p["timeline"]["tracks"][0]["clips"] = v
    p["timeline"]["tracks"][2]["clips"] = a
    p["output"].update(width=640, height=360, fps=30)
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                  "timeline": p["timeline"], "output": p["output"]})
    return pid, mid


async def set_range(loc, value):
    await loc.fill(str(value))


async def keys(pg, key, n=1):
    """Playhead keys only work when no slider/select has focus (like in real use)."""
    await pg.evaluate("document.activeElement && document.activeElement.blur()")
    for _ in range(n):
        await pg.keyboard.press(key)


async def wait_saved(pg):
    await pg.wait_for_timeout(300)
    await pg.get_by_text("All changes saved").wait_for(timeout=10000)


async def export(pg, pid, name):
    job = api("POST", f"/api/projects/{pid}/exports", {"filename": name, "quality": "draft",
                                                         "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"}})
    for _ in range(600):
        j = api("GET", f"/api/jobs/{job['id']}")
        if j["status"] not in ("queued", "running"):
            return j
        await asyncio.sleep(0.25)
    raise TimeoutError


def frame_at(path: Path, t: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(360, 640, 3).astype(int)


async def main(pid: str, mid: str):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        pg = await b.new_page(viewport={"width": 1500, "height": 1000})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(f"{B}/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        # ---- first video clip: rotation, crop, look
        await pg.locator(".clip.video").first.click()
        tf = pg.get_by_test_id("transform")
        await set_range(tf.get_by_label("Rotation"), 90)
        await set_range(pg.get_by_test_id("crop").get_by_label("Left"), 0.1)
        await pg.get_by_label("Look").select_option("bw")
        # ---- slow zoom: keyframe at 0.5 s (100%) and 3.5 s (150%)
        await keys(pg, "Home")
        await keys(pg, "ArrowRight", 15)
        scale = pg.get_by_test_id("kf-scale")
        await scale.get_by_role("button", name="◆").click()
        await keys(pg, "ArrowRight", 90)
        await set_range(scale.get_by_label("Scale"), 1.5)
        await wait_saved(pg)
        assert await pg.locator(".clip.video").first.locator(".kf-mark").count() == 2
        assert "2 keyframes" in await scale.inner_text()
        # preview follows the animation: at 2 s the scale is ~125%
        await keys(pg, "Home")
        await keys(pg, "ArrowRight", 60)
        await pg.wait_for_timeout(300)
        style = await pg.locator("video[data-layer='V1']").get_attribute("style")
        print("V1 preview style:", style[:200])
        assert "rotate(90deg)" in style and "scale(1.25)" in style and "grayscale(1)" in style and "inset(" in style, style
        # ---- audio clip: duck the volume with two keyframes
        await pg.locator(".clip.audio").first.click()
        vol = pg.get_by_test_id("kf-volume")
        await vol.get_by_role("button", name="◆").click()
        await keys(pg, "ArrowRight", 30)
        await set_range(vol.get_by_label("Volume"), 0.3)
        assert "2 keyframes" in await vol.inner_text()
        # ---- wipe transition into the second clip
        await pg.locator(".clip.video").nth(1).click()
        await pg.get_by_label("Transition in").select_option("wipe_left")
        await wait_saved(pg)
        assert await pg.locator(".clip.video").nth(1).get_attribute("title")
        # ---- meters move while playing
        await keys(pg, "Home")
        await pg.get_by_title("Play / pause (Space)").click()
        await pg.wait_for_timeout(1500)
        h = await pg.locator(".meter-bar").first.evaluate("e => parseFloat(e.style.height)")
        await pg.get_by_title("Play / pause (Space)").click()
        print("meter height while playing: %.0f%%" % h)
        assert h > 30, h
        await pg.screenshot(path=str(TMP / "editor.png"))
        # ---- light preview makes a proxy for the file
        await pg.get_by_role("button", name="Light preview").click()
        for _ in range(200):
            if api("GET", f"/api/projects/{pid}")["media"][0].get("proxy"):
                break
            await asyncio.sleep(0.2)
        assert api("GET", f"/api/projects/{pid}")["media"][0].get("proxy"), "no proxy made"
        await pg.reload()
        await pg.locator(".clip.video").first.wait_for()
        await pg.wait_for_timeout(800)
        src = await pg.locator("video[data-layer='V1']").evaluate("e => e.currentSrc")
        assert src.endswith("?proxy=1"), src
        # ---- reopen keeps everything
        p = api("GET", f"/api/projects/{pid}")
        c0 = p["timeline"]["tracks"][0]["clips"][0]
        assert c0["transform"]["rotation"] == 90 and c0["crop"]["left"] == 0.1 and c0["color"]["look"] == "bw"
        assert [k["v"] for k in c0["keyframes"]["scale"]] == [1, 1.5]
        assert p["timeline"]["tracks"][0]["clips"][1]["transition_in"]["kind"] == "wipe_left"
        assert len(p["timeline"]["tracks"][2]["clips"][0]["keyframes"]["volume"]) == 2
        # ---- export twice: validated, rotated + grey, and the second one reuses the cache
        j = await export(pg, pid, "p6")
        assert j["status"] == "succeeded" and j["result"]["validation"]["ok"], j
        out = Path(TMP / "ws/projects" / pid / "exports" / j["result"]["file"])
        f = frame_at(out, 0.5)
        grey = np.abs(f[..., 0] - f[..., 1]).mean() + np.abs(f[..., 1] - f[..., 2]).mean()
        # rotated 90° on a 16:9 canvas: the picture becomes a tall shape with black on both sides
        side = f[:, :100].mean(), f[:, 270:370].mean()
        print(f"export frame: colour spread {grey:.1f}, left-edge brightness {side[0]:.1f}, centre {side[1]:.1f}")
        assert grey < 6 and side[0] < 8 and side[1] > 40
        j2 = await export(pg, pid, "p6-again")
        cache = j2["result"]["validation"]["cache"]
        print("second export cache:", cache)
        assert j2["status"] == "succeeded" and cache["reused"] > 0 and cache["rendered"] == 0, cache
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    env = {**os.environ, "CLIPFORGE_WORKSPACE": str(TMP / "ws"), "CLIPFORGE_PORT": str(PORT)}
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
