"""Browser end-to-end test of "My sounds & images".

Fake microphone (a 2 kHz tone) -> Effects tab -> Record sound -> Stop -> name it -> Save ->
"Bleep" (use as bleep sound) -> Find & bleep swears -> import an image -> Add it at the
playhead -> add the sound as a sound effect -> export -> the swear is replaced by YOUR
recording (measured by FFT) and the image is in the picture -> the library persists across
projects. Fails on console/page errors.

Run:  python scripts/e2e_library.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-lib-"))
WS = TMP / "ws"
PORT = 8798
B = f"http://127.0.0.1:{PORT}"
MIC = TMP / "mic.wav"
IMG = TMP / "face.png"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def setup() -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=2000:d=30:sample_rate=48000",
                    "-af", "volume=0.3", "-ac", "1", str(MIC)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=magenta:s=200x200:d=1",
                    "-frames:v", "1", str(IMG)], check=True)
    vid = TMP / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=6",
                    "-f", "lavfi", "-i", "sine=f=440:d=6:sample_rate=48000", "-shortest", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)
    p = api("POST", "/api/projects", {"name": "Library test"})
    m = api("POST", f"/api/projects/{p['id']}/media?filename=talk.mp4", raw=vid.read_bytes())["media"]
    job = api("POST", f"/api/projects/{p['id']}/autoedit/analyze", {"media_id": m["id"]})
    for _ in range(100):
        if api("GET", f"/api/jobs/{job['id']}")["status"] == "succeeded":
            break
        time.sleep(0.3)
    af = WS / "projects" / p["id"] / "analysis" / f"{m['id']}.json"
    a = json.loads(af.read_text())
    a["words"] = [{"start": 1.0, "end": 1.3, "text": " oh", "p": 0.9}, {"start": 1.5, "end": 2.0, "text": " shit", "p": 0.93}]
    a["transcriber"] = "test"
    af.write_text(json.dumps(a))
    p = api("GET", f"/api/projects/{p['id']}")
    link = uuid.uuid4().hex
    p["timeline"]["tracks"][0]["clips"] = [{"id": uuid.uuid4().hex, "media_id": m["id"], "start": 0, "source_in": 0, "source_out": 6, "link_id": link}]
    p["timeline"]["tracks"][2]["clips"] = [{"id": uuid.uuid4().hex, "media_id": m["id"], "start": 0, "source_in": 0, "source_out": 6, "link_id": link}]
    p["output"].update(width=640, height=360, fps=30)
    api("PUT", f"/api/projects/{p['id']}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"], "output": p["output"]})
    return p["id"]


def band(x, t0, t1, f):
    seg = x[int(t0 * 48000):int(t1 * 48000)]
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    fr = np.fft.rfftfreq(len(seg), 1 / 48000)
    return sp[(fr > f - 40) & (fr < f + 40)].max() / (sp.max() + 1e-9)


async def main(pid: str):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                                           f"--use-file-for-fake-audio-capture={MIC}"])
        ctx = await b.new_context(viewport={"width": 1500, "height": 1000}, permissions=["microphone"])
        pg = await ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(f"{B}/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.get_by_role("tab", name="Effects").click()
        lib = pg.get_by_test_id("library")
        await lib.scroll_into_view_if_needed()
        # ---- record from the (fake) microphone
        await lib.get_by_test_id("record").click()
        await lib.get_by_test_id("stop").wait_for()
        await pg.wait_for_timeout(1800)
        await lib.get_by_test_id("stop").click()
        take = lib.get_by_test_id("take")
        await take.wait_for()
        await take.get_by_label("Sound name").fill("My bruh")
        await take.get_by_role("button", name="Save").click()
        row = lib.get_by_test_id("lib-sound").filter(has_text="My bruh")
        await row.wait_for(timeout=15000)
        print("library row:", (await row.inner_text()).replace("\n", " "))
        # ---- use it as the bleep sound, then find swears
        await row.get_by_role("button", name="Bleep").click()
        sel = pg.get_by_label("Bleep sound")
        await pg.wait_for_timeout(300)
        print("bleep sound picker:", await sel.evaluate("e => [e.value, e.selectedOptions[0]?.textContent, e.options.length]"))
        assert "★ My bruh" in await sel.evaluate("e => e.selectedOptions[0]?.textContent || ''")
        await pg.get_by_role("button", name="Find & bleep swears").click()
        await pg.get_by_text("1 bleep(s) added").wait_for(timeout=10000)
        # ---- import an image and drop it at the playhead
        async with pg.expect_file_chooser() as fc:
            await lib.get_by_role("button", name="Import image").click()
        await (await fc.value).set_files(str(IMG))
        img = lib.get_by_test_id("lib-image").first
        await img.wait_for(timeout=15000)
        await pg.evaluate("document.activeElement && document.activeElement.blur()")
        await pg.keyboard.press("Home")
        for _ in range(90):
            await pg.keyboard.press("ArrowRight")  # 3.0 s
        await img.get_by_role("button", name="Add").click()
        # ---- and the recording as a sound effect at 4 s
        for _ in range(30):
            await pg.keyboard.press("ArrowRight")
        await row.get_by_role("button", name="Add").click()
        await pg.wait_for_timeout(300)
        # ---- keywords -> suggestion: tag the image with a word that's said in the video
        await img.get_by_role("button", name="#").click()
        await pg.locator(".modal input[type=text]").fill("oh, shit")  # the keywords box
        await pg.get_by_role("button", name="Save", exact=True).click()
        await img.get_by_role("button", name="#").wait_for()
        br = pg.get_by_test_id("broll")
        await br.get_by_role("button", name="Suggest").click()
        sug = br.get_by_test_id("broll-suggestion").first
        await sug.wait_for(timeout=10000)
        print("library suggestion:", (await sug.inner_text()).replace("\n", " "))
        assert "you said" in await sug.inner_text()
        await sug.get_by_role("button", name="Add").click()
        await pg.wait_for_timeout(300)
        await pg.get_by_text("All changes saved").wait_for(timeout=10000)
        await pg.screenshot(path=str(TMP / "library.png"))
        p = api("GET", f"/api/projects/{pid}")
        kinds = sorted((e["kind"], e.get("sound")) for e in p["effects"])
        print("effects:", kinds)
        assert kinds == [("censor", "custom"), ("image", None), ("image", None), ("sfx", "custom")], kinds
        # ---- export and measure
        job = api("POST", f"/api/projects/{pid}/exports", {"filename": "lib", "quality": "draft",
                                                            "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"}})
        for _ in range(400):
            j = api("GET", f"/api/jobs/{job['id']}")
            if j["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(0.25)
        assert j["status"] == "succeeded" and j["result"]["validation"]["ok"], j
        out = WS / "projects" / pid / "exports" / j["result"]["file"]
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                             capture_output=True).stdout
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        at_swear, swear_orig, before = band(x, 1.6, 1.9, 2000), band(x, 1.6, 1.9, 440), band(x, 0.3, 0.9, 440)
        print(f"bleep window: your sound {at_swear:.2f}, original word {swear_orig:.3f}; before it: speech {before:.2f}")
        assert at_swear > 0.9 and swear_orig < 0.05 and before > 0.9
        assert band(x, 4.2, 4.8, 2000) > 0.5  # the sound effect
        fr = subprocess.run(["ffmpeg", "-v", "error", "-ss", "3.3", "-i", str(out), "-frames:v", "1", "-f", "rawvideo",
                             "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        f = np.frombuffer(fr, np.uint8).reshape(360, 640, 3).astype(int)
        magenta = ((f[..., 0] > 180) & (f[..., 1] < 80) & (f[..., 2] > 180)).mean()
        print(f"image pop-up covers {magenta * 100:.1f}% of the frame")
        assert magenta > 0.005
        # ---- the library is shared: a new project sees the same sound
        p2 = api("POST", "/api/projects", {"name": "Another"})
        await pg.goto(f"{B}/#/editor/{p2['id']}")
        await pg.get_by_role("tab", name="Effects").click()
        await pg.get_by_test_id("lib-sound").filter(has_text="My bruh").wait_for()
        assert not errs, errs
        await b.close()


if __name__ == "__main__":
    env = {**os.environ, "RJCLIP_WORKSPACE": str(WS), "RJCLIP_PORT": str(PORT)}
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
