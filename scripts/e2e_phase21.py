"""Browser end-to-end test of Phase 21 (multicam, motion graphics, auto colour, edit by typing).

At 1280×720:
- AI tab → "Tell RJClip what to do": "add a bar chart at 0:01; add a marker "Intro" at 0:00" is one
  undo step that adds both; "go to 0:05" moves the playhead; something it doesn't know shows an
  error (no local AI here). Pressing / jumps to the box.
- AI tab → Multicam: a main camera (grey) and camera B (red, started 2 s late), each person with
  their own mic. Line up & switch → the edit on V1 cuts to camera B while B talks; the preview
  shows B's picture there; the sound stays the main recording's. A shot can be changed by hand.
  Match colours to Cam 1 changes camera B's colour. Back to one camera undoes it all.
- Clip tab → Colour → Auto fix on the darkened main camera brightens it.
- Text tab → Bar chart, Percent ring, List reveal, Progress bar, End screen: previews show
  (the ring's number rolls up to the end value; the progress bar fills).
- Export: camera B's moments are red, the others grey; the chart is drawn.
- Nothing sticks out of the side panel; no console errors.

Run:  python scripts/e2e_phase21.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p21-"))
WS = TMP / "ws"
PORT = 8823
B = f"http://127.0.0.1:{PORT}"
SECS = 36

KNOCKS = "+".join(f"between(t,{a},{a + 0.08})" for a in (1.3, 5.9, 11.7, 14.2, 17.3, 23.6, 25.9, 31.4, 33.1))
ROOM = ("(0.9*(" + KNOCKS + ")*sin(2*PI*900*t)+0.02*sin(2*PI*137*t)*(0.5+0.5*sin(2*PI*3*t))"
        "+0.3*(lt(t,8)+between(t,20,28))*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*5*t))"
        "+0.3*(between(t,8,20)+between(t,28,36))*sin(2*PI*330*t)*(0.6+0.4*sin(2*PI*7*t)))")
MIC_A = ("(0.6*(" + KNOCKS + ")*sin(2*PI*900*t)+0.01*sin(2*PI*137*t)+0.5*(lt(t,8)+between(t,20,28))*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*5*t))"
         "+0.04*(between(t,8,20)+between(t,28,36))*sin(2*PI*330*t))")
MIC_B = ("(0.6*(" + KNOCKS + ")*sin(2*PI*900*t)+0.01*sin(2*PI*137*t)+0.04*(lt(t,8)+between(t,20,28))*sin(2*PI*220*t)"
         "+0.5*(between(t,8,20)+between(t,28,36))*sin(2*PI*330*t)*(0.6+0.4*sin(2*PI*7*t)))")


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def wait_job(jid):
    for _ in range(1500):
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
    # the main camera is a bit dark (for Auto fix); camera B started 2 s late
    main = make("main.mp4", ["-f", "lavfi", "-i", f"color=c=0x707070:s=320x180:r=25:d={SECS}", "-f", "lavfi", "-i", f"aevalsrc='{ROOM}':s=48000:d={SECS}",
                             "-vf", "eq=brightness=-0.15", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", str(SECS)])
    camb = make("camb.mp4", ["-f", "lavfi", "-i", f"color=c=0xd02020:s=320x180:r=25:d={SECS - 2}", "-f", "lavfi", "-i", f"aevalsrc='{ROOM}':s=48000:d={SECS}",
                             "-af", "atrim=start=2,asetpts=PTS-STARTPTS", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", str(SECS - 2)])
    mic_a = make("mic_a.wav", ["-f", "lavfi", "-i", f"aevalsrc='{MIC_A}':s=48000:d={SECS}"])
    mic_b = make("mic_b.wav", ["-f", "lavfi", "-i", f"aevalsrc='{MIC_B}':s=48000:d={SECS}"])
    pid = api("POST", "/api/projects", {"name": "Podcast"})["id"]
    ids = {n: upload(pid, f) for n, f in (("main", main), ("camb", camb), ("mic_a", mic_a), ("mic_b", mic_b))}
    p = api("GET", f"/api/projects/{pid}")
    t = p["timeline"]
    link = hexid()
    t["tracks"][0]["clips"] = [{"id": hexid(), "media_id": ids["main"], "start": 0, "source_in": 0, "source_out": SECS, "link_id": link}]
    t["tracks"][2]["clips"] = [{"id": hexid(), "media_id": ids["main"], "start": 0, "source_in": 0, "source_out": SECS, "link_id": link}]
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": t,
                                               "output": {"width": 640, "height": 360, "fps": 25, "fit_mode": "fit"}})
    return pid, ids


def project(pid):
    return api("GET", f"/api/projects/{pid}")


def pixel(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-s", "64x36", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(36, 64, 3).astype(int)


async def main(pid, ids):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text and "409" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=30000)  # noqa: E731

        async def saved():
            await pg.wait_for_timeout(150)
            await pg.wait_for_function("() => /All changes saved/.test(document.body.innerText) && !/Unsaved|Saving/.test(document.querySelector('.ed-top')?.innerText || '')", timeout=15000)

        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.locator("button[title='Fit timeline']").click()
        clip0 = await pg.locator(".clip.video").first.bounding_box()
        x0, pps = clip0["x"], clip0["width"] / SECS

        async def seek(t):
            r = await pg.locator(".ruler").bounding_box()
            await pg.mouse.click(x0 + t * pps, r["y"] + r["height"] / 2)
            await pg.wait_for_timeout(250)

        async def no_overflow(where):
            wide = await pg.evaluate("""() => [...document.querySelectorAll('.pane-body')].filter(p => p.offsetParent).flatMap(p => {
                const r = p.getBoundingClientRect(); return [...p.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
                return b.width > 0 && b.height > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).map(e => e.outerHTML.slice(0, 120)); }).slice(0, 5)""")
            assert not wide, (where, wide)

        def v1():
            return project(pid)["timeline"]["tracks"][0]["clips"]

        # ---- edit by typing (/ jumps to the box)
        await pg.locator(".timeline").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("/")
        box = pg.get_by_label("Command")
        await pg.wait_for_function("() => document.activeElement?.id === 'rj-command'", timeout=5000)
        await box.fill('add a bar chart at 0:01; add a marker "Intro" at 0:00')
        await box.press("Enter")
        await saved()
        pr = project(pid)
        assert [t["template"] for t in pr["timeline"]["titles"]] == ["chart"] and pr["timeline"]["markers"][0]["label"] == "Intro", pr["timeline"]
        log = pg.get_by_test_id("command-log")
        assert "Added bar chart" in await log.inner_text()
        await box.press("Escape")                               # (leave the box: Ctrl+Z there edits the text)
        await pg.keyboard.press("Control+z")                    # one undo step takes both back
        await saved()
        pr = project(pid)
        assert not pr["timeline"]["titles"] and not pr["timeline"]["markers"], pr["timeline"]
        await box.fill("go to 0:05")
        await box.press("Enter")
        await log.get_by_text("Went to 0:05").wait_for()
        await box.fill("make it look awesome")
        await box.press("Enter")
        await log.get_by_text("I don't know").wait_for()
        await pg.get_by_test_id("command-examples").wait_for()
        await no_overflow("AI tab: command box")

        # ---- multicam
        mcp = pg.get_by_test_id("multicam")
        await mcp.get_by_label("Camera 1", exact=True).select_option(ids["main"])
        await mcp.get_by_label("Camera 2", exact=True).select_option(ids["camb"])
        await mcp.get_by_label("Name of camera 1").fill("Alex")
        await mcp.get_by_label("Name of camera 2").fill("Sam")
        await mcp.get_by_label("Mic of camera 1").select_option(ids["mic_a"])
        await mcp.get_by_label("Mic of camera 2").select_option(ids["mic_b"])
        await mcp.get_by_role("button", name="Line up & switch").click()
        await toast("Multicam:")
        await saved()
        clips = v1()
        shots = [(round(c["start"]), "B" if c["media_id"] == ids["camb"] else "A") for c in clips]
        print("multicam shots:", shots)
        assert shots == [(0, "A"), (8, "B"), (20, "A"), (28, "B")], shots
        b8 = clips[1]
        assert abs(b8["source_in"] - 6.0) < 0.05, b8                                 # camera B time = main time - 2
        a1 = project(pid)["timeline"]["tracks"][2]["clips"]
        assert all(c["media_id"] == ids["main"] for c in a1) and abs(sum(c["source_out"] - c["source_in"] for c in a1) - SECS) < 0.01
        assert "Cam 1 · Alex" in await mcp.get_by_test_id("multicam-share").inner_text()
        await seek(12)
        await pg.wait_for_timeout(600)
        src = await pg.locator("video[data-layer='V1']").first.evaluate("v => v.currentSrc || v.src")
        assert ids["camb"] in src, src                                               # the preview plays camera B here
        await pg.screenshot(path=str(TMP / "multicam.png"))
        # change a shot by hand
        await pg.locator(".clip.video").nth(1).click()
        await mcp.get_by_test_id("multicam-pick").get_by_role("button", name="Cam 1 · Alex").click()
        await saved()
        assert v1()[1]["media_id"] == ids["main"]
        await pg.keyboard.press("Control+z")
        await saved()
        assert v1()[1]["media_id"] == ids["camb"]
        # colours
        await mcp.get_by_role("button", name="Match colours to Cam 1").click()
        await toast("Matched")
        await saved()
        colb = [c for c in v1() if c["media_id"] == ids["camb"]][0]["color"]
        print("camera B colour:", colb)
        assert colb != {"brightness": 0, "contrast": 1, "saturation": 1, "gamma": 1, "temperature": 0, "look": "none"}
        await no_overflow("AI tab: multicam")

        # ---- auto fix on the main camera (Clip tab)
        await pg.locator(".clip.video").first.click()
        await pg.get_by_role("tab", name="Clip", exact=True).click()
        await pg.get_by_test_id("auto-color").get_by_role("button", name="Auto fix").click()
        await toast("Colour fixed")
        await saved()
        cola = [c for c in v1() if c["media_id"] == ids["main"]]
        assert all(c["color"]["brightness"] > 0.05 for c in cola), [c["color"] for c in cola]
        await no_overflow("Clip tab")

        # ---- motion graphics
        await pg.get_by_role("tab", name="Text", exact=True).click()
        panel = pg.get_by_test_id("titles-panel")
        await seek(2)
        await panel.get_by_role("button", name="Bar chart").click()
        await saved()
        await panel.get_by_label("Item 1 name").fill("Alex")
        await panel.get_by_label("Item 1 value").fill("42")
        await saved()
        ch = [x for x in project(pid)["timeline"]["titles"] if x["template"] == "chart"][0]
        assert ch["items"][0] == {"label": "Alex", "value": 42}, ch["items"]
        await seek(4)
        assert "Alex" in await pg.locator("[data-template=chart]").inner_text()
        await seek(10)
        await panel.get_by_role("button", name="Percent ring").click()
        await saved()
        await seek(13)
        assert await pg.get_by_test_id("ring-value").inner_text() == "87%"
        await seek(15)
        await panel.get_by_role("button", name="List reveal").click()
        await panel.get_by_role("button", name="Progress bar").click()
        await panel.get_by_role("button", name="End screen").click()
        await saved()
        tt = {x["template"]: x for x in project(pid)["timeline"]["titles"]}
        assert tt["progress"]["start"] == 0 and abs(tt["progress"]["duration"] - SECS) < 0.01
        assert abs(tt["end_screen"]["start"] - (SECS - 20)) < 0.01
        await seek(18)
        w = await pg.get_by_test_id("progress-fill").evaluate("e => e.getBoundingClientRect().width")
        assert w > 0
        await pg.screenshot(path=str(TMP / "motion.png"))
        await no_overflow("Text tab")

        assert not errs, errs
        await b.close()

    # ---- export
    j = wait_job(api("POST", f"/api/projects/{pid}/exports", {"filename": "phase21", "quality": "draft"})["id"])
    assert j["status"] == "succeeded", j.get("error_detail")
    out = WS / "projects" / pid / "exports" / j["result"]["file"]
    a, bb = pixel(out, 6.5)[30, 5], pixel(out, 9.0)[30, 5]
    print("export pixels: cam A", a, "| cam B", bb)
    assert bb[0] > bb[1] + 60 and abs(int(a[0]) - int(a[1])) < 25, (a, bb)
    f = pixel(out, 4.0)
    assert (np.abs(f - [255, 90, 60]).sum(axis=2) < 90).any()                       # a chart bar


if __name__ == "__main__":
    env = {**os.environ, "RJCLIP_WORKSPACE": str(WS), "RJCLIP_PORT": str(PORT), "RJCLIP_TRANSCRIBER": "off", "RJCLIP_LLM": "off"}
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
