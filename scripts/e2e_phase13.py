"""Browser end-to-end test of Phase 13: change an effect's time by typing it.

An auto-placed pop-up text at 0:04.00 -> FX tab -> type 20.8 into its time box ->
it moves (onto the second clip) and the preview jumps there -> +0.1s / −0.1s ->
"To playhead" -> nonsense and a time with no footage are refused and the box goes back
-> Esc cancels -> undo -> the export renders it at the new time. Fails on page errors.

Run:  python scripts/e2e_phase13.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p13-"))
PORT = 8807
B = f"http://127.0.0.1:{PORT}"
FX = "e" * 32


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def setup():
    v = TMP / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=40", "-f", "lavfi",
                    "-i", "sine=f=300:d=40", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(v)], check=True)
    p = api("POST", "/api/projects", {"name": "Effect times"})
    pid = p["id"]
    mid = api("POST", f"/api/projects/{pid}/media?filename=v.mp4", raw=v.read_bytes())["media"]["id"]
    p = api("GET", f"/api/projects/{pid}")
    l1, l2 = os.urandom(16).hex(), os.urandom(16).hex()
    mk = lambda s, a, b, link: {"id": os.urandom(16).hex(), "media_id": mid, "start": s, "source_in": a, "source_out": b, "link_id": link}  # noqa: E731
    # two pieces: 0-15 (source 0-15) and 15-30 (source 25-40)
    p["timeline"]["tracks"][0]["clips"] = [mk(0, 0, 15, l1), mk(15, 25, 40, l2)]
    p["timeline"]["tracks"][2]["clips"] = [mk(0, 0, 15, l1), mk(15, 25, 40, l2)]
    fx = {"id": FX, "kind": "text", "media_id": mid, "source_time": 4.0, "duration": 1.3, "origin": "auto",
          "text": "NO WAY", "y": 0.22, "size": 0.13, "color": "#ffde00"}
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                               "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"}, "effects": [fx]})
    return pid


def fx_source(pid):
    return next(e for e in api("GET", f"/api/projects/{pid}")["effects"] if e["id"] == FX)["source_time"]


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=15000)  # noqa: E731

        async def saved_source(expect, eps=0.02):
            """Wait until autosave has stored the effect at this source time."""
            end = time.time() + 15
            while time.time() < end:
                s = fx_source(pid)
                if abs(s - expect) < eps:
                    return s
                await pg.wait_for_timeout(200)
            raise AssertionError(f"effect source time {fx_source(pid)} != {expect}")

        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.get_by_role("tab", name="Effects").click()
        box = pg.get_by_label("Effect time")
        await box.wait_for()
        assert await box.input_value() == "0:04.00", await box.input_value()
        tc = pg.locator(".transport .tc")

        # type a new time: 20.8 s in the edit = 30.8 s in the recording (second piece)
        await box.click()
        await box.fill("20.8")
        await box.press("Enter")
        print("after typing 20.8:", await box.input_value(), "| playhead", await tc.inner_text())
        assert await box.input_value() == "0:20.80"
        assert (await tc.inner_text()).startswith("0:20.8")
        await saved_source(30.8)

        # nudges and "to playhead"
        await pg.get_by_role("button", name="+0.1s").click()
        assert await box.input_value() == "0:20.90"
        await pg.get_by_role("button", name="−0.1s").click()
        await pg.get_by_role("button", name="−0.1s").click()
        assert await box.input_value() == "0:20.70"
        await saved_source(30.7)
        await pg.locator(".monitor").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Home")
        for _ in range(15):
            await pg.keyboard.press("ArrowRight")                        # 0.5 s
        await pg.get_by_role("button", name="To playhead").click()
        print("after 'To playhead':", await box.input_value())
        assert await box.input_value() == "0:00.50"
        await saved_source(0.5)

        # refused: not a time, and a time with no footage; Esc cancels
        await box.fill("soon")
        await box.press("Enter")
        assert await box.input_value() == "0:00.50"
        await box.fill("45")
        await box.press("Enter")
        await toast("no footage at 45")
        assert await box.input_value() == "0:00.50"
        await box.fill("12")
        await box.press("Escape")
        assert await box.input_value() == "0:00.50"
        await pg.screenshot(path=str(TMP / "effect_time.png"))
        # nothing in the side panel sticks out past its right edge (1280-wide screen)
        out = await pg.evaluate("""() => { const col = document.querySelector('.ed-mid').lastElementChild.getBoundingClientRect();
            return [...document.querySelectorAll('.ed-mid > :last-child *')].filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden'
              && e.getBoundingClientRect().right > col.right + 1).map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right - col.right)).slice(0, 10) }""")
        print("side panel overflow:", out)
        assert not out, out

        # undo puts it back to 20.7
        await pg.locator(".monitor").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Control+z")
        assert await box.input_value() == "0:20.70"
        await saved_source(30.7)
        assert not errs, errs
        await b.close()

    # the export draws the yellow text at 20.7 s (and not at the old 4 s)
    j = api("POST", f"/api/projects/{pid}/exports", {"filename": "fx", "quality": "draft"})
    for _ in range(600):
        j = api("GET", f"/api/jobs/{j['id']}")
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    assert j["status"] == "succeeded", j.get("error_detail")
    out = TMP / "ws" / "projects" / pid / "exports" / j["result"]["file"]

    def yellow_at(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        px = [raw[i:i + 3] for i in range(0, len(raw), 3)]
        return sum(1 for p in px if p[0] > 200 and p[1] > 180 and p[2] < 90) / len(px)
    at_new, at_old = yellow_at(21.2), yellow_at(4.5)
    print(f"yellow text share: at 21.2 s {at_new:.4f}, at 4.5 s {at_old:.4f}")
    assert at_new > 0.002 and at_old < 0.0005


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
