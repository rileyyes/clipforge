"""Browser end-to-end test of Phase 20 (sound mixer and blend modes).

At 1280×720:
- Music tab → Sound mixer: one row per sound track. Turning the music track down to 30 %
  plays it quieter in the preview right away and is saved; Solo on the music track silences
  the movie sound in the preview (and the row shows it); Reset puts it back. The sound
  effects level is saved.
- Clip tab → Blend: on the base track the control explains it needs an upper track; on V2,
  Screen makes the preview layer blend (CSS mix-blend-mode) and is saved.
- Export: the music is quieter by the mixer's amount, and the picture at the blended moment
  is the Screen of the two (gray + red → light red), not plain red.
- Nothing sticks out of the side panel; no console errors.

Run:  python scripts/e2e_phase20.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p20-"))
WS = TMP / "ws"
PORT = 8822
B = f"http://127.0.0.1:{PORT}"
SECS = 12


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def wait_job(jid):
    for _ in range(900):
        j = api("GET", f"/api/jobs/{jid}")
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.2)
    raise TimeoutError(jid)


def hexid():
    return os.urandom(16).hex()


def make(name, args):
    f = TMP / name
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, str(f)], check=True)
    return f


def upload(pid, f):
    r = api("POST", f"/api/projects/{pid}/media?filename={f.name}", raw=f.read_bytes())
    assert wait_job(r["job_id"])["status"] == "succeeded"
    return r["media"]["id"]


def setup():
    movie = make("movie.mp4", ["-f", "lavfi", "-i", f"color=c=gray:s=320x180:r=30:d={SECS}", "-f", "lavfi", "-i", f"sine=f=440:d={SECS}",
                              "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"])
    leak = make("leak.mp4", ["-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=4", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"])
    song = make("song.wav", ["-f", "lavfi", "-i", f"sine=f=220:d={SECS}", "-ar", "48000"])
    pid = api("POST", "/api/projects", {"name": "Mixer"})["id"]
    mid, lid, sid = upload(pid, movie), upload(pid, leak), upload(pid, song)
    p = api("GET", f"/api/projects/{pid}")
    t = p["timeline"]
    link = hexid()
    t["tracks"][0]["clips"] = [{"id": hexid(), "media_id": mid, "start": 0, "source_in": 0, "source_out": SECS, "link_id": link}]
    t["tracks"][1]["clips"] = [{"id": hexid(), "media_id": lid, "start": 4, "source_in": 0, "source_out": 4}]
    t["tracks"][2]["clips"] = [{"id": hexid(), "media_id": mid, "start": 0, "source_in": 0, "source_out": SECS, "link_id": link}]
    t["tracks"][3]["clips"] = [{"id": hexid(), "media_id": sid, "start": 0, "source_in": 0, "source_out": SECS}]
    t["tracks"][3]["role"] = "music"
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": t,
                                               "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"}})
    return pid


def project(pid):
    return api("GET", f"/api/projects/{pid}")


def level(path, a, b, f):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)[int(a * 8000):int(b * 8000)]
    spec = np.abs(np.fft.rfft(x)) / len(x)
    fr = np.fft.rfftfreq(len(x), 1 / 8000)
    return float(spec[(fr > f - 15) & (fr < f + 15)].max())


def pixel(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-s", "64x36", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(36, 64, 3)[18, 32].astype(int)


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))

        async def saved():
            await pg.wait_for_timeout(150)
            await pg.wait_for_function("() => /All changes saved/.test(document.body.innerText) && !/Unsaved|Saving/.test(document.querySelector('.ed-top')?.innerText || '')", timeout=15000)

        async def seek(t):
            c = await pg.locator(".clip.video").first.bounding_box()
            r = await pg.locator(".ruler").bounding_box()
            await pg.mouse.click(c["x"] + t * c["width"] / SECS, r["y"] + r["height"] / 2)
            await pg.wait_for_timeout(250)

        async def set_range(loc, v):
            await loc.evaluate("""(el, v) => { const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                s.call(el, String(v)); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }""", v)

        async def gain(track):
            return await pg.locator(f"audio[data-track='{track}']").get_attribute("data-gain")

        async def no_overflow(where):
            wide = await pg.evaluate("""() => [...document.querySelectorAll('.pane-body')].filter(p => p.offsetParent).flatMap(p => {
                const r = p.getBoundingClientRect(); return [...p.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
                return b.width > 0 && b.height > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).map(e => e.outerHTML.slice(0, 120)); }).slice(0, 5)""")
            assert not wide, (where, wide)

        def tracks():
            return {t["name"]: t for t in project(pid)["timeline"]["tracks"]}

        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.locator("button[title='Fit timeline']").click()
        await seek(2)

        # ---- the mixer
        await pg.get_by_role("tab", name="Music", exact=True).click()
        mx = pg.get_by_test_id("mixer")
        await mx.wait_for()
        names = [await r.get_attribute("data-track") for r in await mx.get_by_test_id("mixer-row").all()]
        print("mixer rows:", names)
        assert "A1" in names and "A2" in names, names
        assert await gain("A1") == "1" and await gain("A2") == "1", (await gain("A1"), await gain("A2"))
        await set_range(mx.get_by_label("Volume of A2"), 0.3)
        await saved()
        assert abs(tracks()["A2"]["volume"] - 0.3) < 1e-6, tracks()["A2"]
        await pg.wait_for_function("() => document.querySelector(\"audio[data-track='A2']\")?.dataset.gain === '0.3'", timeout=5000)
        row = mx.locator("[data-testid=mixer-row][data-track='A2']")
        assert "30% · −10 dB" in await row.inner_text(), await row.inner_text()
        # solo the music: the movie sound goes quiet
        await mx.get_by_role("button", name="Solo A2").click()
        await saved()
        assert tracks()["A2"]["solo"] is True
        await pg.wait_for_function("() => document.querySelector(\"audio[data-track='A1']\")?.dataset.gain === '0'", timeout=5000)
        assert await mx.locator("[data-testid=mixer-row][data-track='A1']").get_attribute("data-heard") == "0"
        await mx.get_by_text("Solo is on").wait_for()
        await pg.screenshot(path=str(TMP / "mixer_solo.png"))
        await mx.get_by_role("button", name="Solo A2").click()
        await saved()
        await pg.wait_for_function("() => document.querySelector(\"audio[data-track='A1']\")?.dataset.gain === '1'", timeout=5000)
        # effects level
        await set_range(mx.get_by_label("Volume of sound effects"), 0.5)
        await saved()
        assert abs(project(pid)["audio"]["fx_volume"] - 0.5) < 1e-6
        # reset then put the music back down for the export
        await mx.get_by_role("button", name="Reset").click()
        await saved()
        assert tracks()["A2"]["volume"] == 1 and not tracks()["A2"]["solo"]
        await set_range(mx.get_by_label("Volume of A2"), 0.3)
        await saved()
        await no_overflow("Music tab")

        # ---- blend modes
        await pg.locator(".clip.video").first.click()
        await pg.get_by_role("tab", name="Clip", exact=True).click()
        sel = pg.get_by_label("Blend mode")
        assert await sel.is_disabled()
        assert "V2 or higher" in await pg.get_by_test_id("blend").inner_text()
        await pg.locator(".clip.video").nth(1).click()
        assert not await sel.is_disabled()
        await sel.select_option("screen")
        await saved()
        v2 = [t for t in project(pid)["timeline"]["tracks"] if t["name"] == "V2"][0]
        assert v2["clips"][0]["blend"] == "screen", v2["clips"][0]
        assert "light leaks" in await pg.get_by_test_id("blend").inner_text()
        await seek(6)
        layer = pg.locator("video[data-layer='V2']")
        assert await layer.get_attribute("data-blend") == "screen"
        assert await layer.evaluate("e => getComputedStyle(e).mixBlendMode") == "screen"
        assert await pg.locator("video[data-layer='V1']").evaluate("e => getComputedStyle(e).mixBlendMode") == "normal"
        await pg.screenshot(path=str(TMP / "blend.png"))
        await no_overflow("Clip tab")

        assert not errs, errs
        await b.close()

    # ---- export: same mix and blend
    plain = json.loads(json.dumps(project(pid)))
    j = wait_job(api("POST", f"/api/projects/{pid}/exports", {"filename": "phase20", "quality": "draft"})["id"])
    assert j["status"] == "succeeded", j.get("error_detail")
    out = WS / "projects" / pid / "exports" / j["result"]["file"]
    px_blend, px_base = pixel(out, 6.0), pixel(out, 2.0)
    print("export pixels: base", px_base, "| blended", px_blend)
    assert px_blend[0] > 240 and 100 < px_blend[1] < 160 and 100 < px_blend[2] < 160, px_blend    # screen(gray, red)
    assert abs(px_base - 128).max() < 12, px_base
    music, movie = level(out, 1, 3, 220), level(out, 1, 3, 440)
    # the same export with the mixer at 100 % for comparison
    t = plain["timeline"]
    for tr in t["tracks"]:
        if tr["name"] == "A2":
            tr["volume"] = 1
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": plain["edit_revision"], "timeline": t, "output": plain["output"]})
    j = wait_job(api("POST", f"/api/projects/{pid}/exports", {"filename": "phase20_even", "quality": "draft"})["id"])
    assert j["status"] == "succeeded", j.get("error_detail")
    out2 = WS / "projects" / pid / "exports" / j["result"]["file"]
    music2, movie2 = level(out2, 1, 3, 220), level(out2, 1, 3, 440)
    ratio = (music / movie) / (music2 / movie2)
    print(f"music vs movie with the mixer at 30 %: {ratio:.2f}x of the even mix")
    assert 0.2 < ratio < 0.4, ratio


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
