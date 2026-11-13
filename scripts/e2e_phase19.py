"""Browser end-to-end test of Phase 19 (tools from how well-edited videos keep people watching).

At 1280×720:
- Text tab: a Timer counts down in real time in the preview (and "Real time" fixes its length
  after changing From); a Money counter lands on $10,000; Time & place types itself out;
  a Route is clicked onto the preview (Enter finishes) and draws itself; a Highlighter box is
  dragged on the preview; pop-up words animate word by word.
- Effects tab: key words in captions stand out; Auto sound design adds whooshes/risers/hits and
  "Remove it" takes them away again.
- Clip tab: Slow push in sets a steady zoom over the clip.
- AI tab: the pacing checker finds still stretches (red on the ruler); "Punch in all of them"
  fixes them.
- Export succeeds with all of it. Nothing sticks out of the side panel; no console errors.

Run:  python scripts/e2e_phase19.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p19-"))
WS = TMP / "ws"
PORT = 8813
B = f"http://127.0.0.1:{PORT}"
SECS = 40


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


def setup():
    v = TMP / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s=640x360:r=30:d={SECS}", "-f", "lavfi",
                    "-i", f"sine=f=300:d={SECS}", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(v)], check=True)
    pid = api("POST", "/api/projects", {"name": "Pacing"})["id"]
    r = api("POST", f"/api/projects/{pid}/media?filename=talk.mp4", raw=v.read_bytes())
    wait_job(r["job_id"])
    mid = r["media"]["id"]
    # a transcript (the speech-to-text model isn't used in tests)
    j = api("POST", f"/api/projects/{pid}/autoedit/analyze", {"media_id": mid})
    assert wait_job(j["id"])["status"] == "succeeded"
    af = WS / "projects" / pid / "analysis" / f"{mid}.json"
    a = json.loads(af.read_text())
    text = "so today we built a huge castle and it cost 10,000 dollars".split()
    a["words"] = [{"start": 1 + i * 0.4, "end": 1.35 + i * 0.4, "text": " " + w, "p": 0.95} for i, w in enumerate(text)]
    a["transcriber"] = "test"
    af.write_text(json.dumps(a))
    p = api("GET", f"/api/projects/{pid}")
    link = hexid()
    t = p["timeline"]
    t["tracks"][0]["clips"] = [{"id": hexid(), "media_id": mid, "start": 0, "source_in": 0, "source_out": SECS, "link_id": link}]
    t["tracks"][2]["clips"] = [{"id": hexid(), "media_id": mid, "start": 0, "source_in": 0, "source_out": SECS, "link_id": link}]
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": t,
                                               "output": {"width": 1280, "height": 720, "fps": 30, "fit_mode": "fit"}})
    return pid


def project(pid):
    return api("GET", f"/api/projects/{pid}")


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept(d.default_value) if d.type == "prompt" else d.accept()))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=20000)  # noqa: E731

        async def saved():
            await pg.wait_for_timeout(150)
            await pg.wait_for_function("() => /All changes saved/.test(document.body.innerText) && !/Unsaved|Saving/.test(document.querySelector('.ed-top')?.innerText || '')", timeout=15000)

        async def seek(t):
            c = await pg.locator(".clip.video").first.bounding_box()
            r = await pg.locator(".ruler").bounding_box()
            await pg.mouse.click(c["x"] + t * c["width"] / SECS, r["y"] + r["height"] / 2)
            await pg.wait_for_timeout(250)

        async def no_overflow(where):
            wide = await pg.evaluate("""() => [...document.querySelectorAll('.pane-body')].filter(p => p.offsetParent).flatMap(p => {
                const r = p.getBoundingClientRect(); return [...p.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
                return b.width > 0 && b.height > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).map(e => e.outerHTML.slice(0, 120)); }).slice(0, 5)""")
            assert not wide, (where, wide)

        def titles_of(tpl):
            return [x for x in project(pid)["timeline"]["titles"] if x["template"] == tpl]

        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.locator("button[title='Fit timeline']").click()
        await pg.get_by_role("tab", name="Text", exact=True).click()
        panel = pg.get_by_test_id("titles-panel")

        # ---- timer: counts down in real time; From → 0:30 + Real time
        await seek(2)
        await panel.get_by_role("button", name="Timer", exact=True).click()
        await saved()
        tm = titles_of("ticker")[0]
        assert tm["format"] == "time" and tm["count_from"] == 10 and abs(tm["duration"] - 10.3) < 1e-6, tm
        val = pg.get_by_test_id("ticker-value")
        await seek(2.2)
        assert await val.inner_text() == "0:10"
        await seek(5.5)
        assert await val.inner_text() == "0:07", await val.inner_text()
        await panel.get_by_label("Count from").fill("0:30")
        await panel.get_by_label("Count from").press("Enter")
        await panel.get_by_role("button", name="Real time").click()
        await saved()
        tm = titles_of("ticker")[0]
        assert tm["count_from"] == 30 and abs(tm["duration"] - 30.3) < 1e-6, tm
        await panel.get_by_text("Runs in real time").wait_for()

        # ---- money counter
        await seek(8)
        await panel.get_by_role("button", name="Money counter").click()
        await saved()
        await seek(10.9)
        vals = [await x.inner_text() for x in await val.all()]
        assert "$10,000" in vals, vals

        # ---- time & place
        await seek(12)
        await panel.get_by_role("button", name="Time & place").click()
        await seek(14)
        assert "DAY 1" in await pg.get_by_test_id("title-preview").filter(has_text="DAY 1").first.inner_text()

        # ---- route: click three points on the preview, Enter finishes
        await seek(16)
        await panel.get_by_role("button", name="Route on a map").click()
        await panel.get_by_role("button", name="Click the route on the preview").click()
        layer = pg.get_by_test_id("pick-layer")
        await layer.wait_for()
        sb = await pg.locator(".screen").bounding_box()
        for fx_, fy in ((0.2, 0.8), (0.5, 0.4), (0.8, 0.6)):
            await pg.mouse.click(sb["x"] + sb["width"] * fx_, sb["y"] + sb["height"] * fy)
        await pg.keyboard.press("Enter")
        await layer.wait_for(state="detached")
        await saved()
        rt = titles_of("route")[0]
        assert len(rt["points"]) == 3 and abs(rt["points"][1][0] - 0.5) < 0.02 and abs(rt["points"][1][1] - 0.4) < 0.02, rt["points"]
        await seek(19)
        assert await pg.locator("[data-template=route] polyline").count() == 2
        await pg.screenshot(path=str(TMP / "route.png"))

        # ---- highlighter: drag a box on the preview
        await seek(22)
        await panel.get_by_role("button", name="Highlighter").click()
        await panel.get_by_role("button", name="Draw the box on the preview").click()
        await pg.get_by_test_id("draw-layer").wait_for()
        await pg.mouse.move(sb["x"] + sb["width"] * 0.2, sb["y"] + sb["height"] * 0.3)
        await pg.mouse.down()
        await pg.mouse.move(sb["x"] + sb["width"] * 0.6, sb["y"] + sb["height"] * 0.4, steps=8)
        await pg.mouse.up()
        await saved()
        hl = titles_of("highlight")[0]
        assert abs(hl["w"] - 0.4) < 0.02 and abs(hl["h"] - 0.1) < 0.02 and abs(hl["x"] - 0.4) < 0.02, hl

        # ---- pop-up words, word by word
        await seek(25)
        await panel.get_by_role("button", name="Pop-up words").click()
        await panel.get_by_label("Title animation").select_option("words")
        await saved()
        assert titles_of("pop_text")[0]["anim"] == "words"
        await no_overflow("Text tab")

        # ---- effects: key words in captions, auto sound design
        await pg.get_by_role("tab", name="Effects").click()
        await pg.get_by_label("Burn animated captions into the export").check()
        await pg.get_by_label("Make key words stand out").check()
        await saved()
        assert project(pid)["captions"]["emphasis"] is True
        await seek(4.0)
        await pg.get_by_test_id("caption-preview").wait_for()
        await seek(30)
        await pg.locator(".timeline").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("m")                                   # a marker: a riser + hit go into it
        await saved()
        n0 = len(project(pid)["effects"])
        await pg.get_by_role("button", name="Auto sound design").click()
        await toast("Sound design:")
        await saved()
        sd = [e for e in project(pid)["effects"] if e.get("context") == "sound design"]
        print("sound design:", sorted(e["sound"] for e in sd))
        assert {"whoosh", "riser", "impact"} == {e["sound"] for e in sd}, sd
        await pg.get_by_role("button", name="Remove it").click()
        await saved()
        assert len(project(pid)["effects"]) == n0
        await no_overflow("Effects tab")

        # ---- clip tab: slow push in
        await pg.locator(".clip.video").first.click()
        await pg.get_by_role("tab", name="Clip", exact=True).click()
        await pg.get_by_test_id("slow-push").get_by_role("button", name="Push in").click()
        await saved()
        kf = project(pid)["timeline"]["tracks"][0]["clips"][0]["keyframes"]["scale"]
        assert [k["v"] for k in kf] == [1, 1.12], kf
        await pg.get_by_test_id("slow-push").get_by_role("button", name="Remove").click()
        await saved()

        # ---- AI tab: pacing checker
        await pg.get_by_role("tab", name="AI", exact=True).click()
        pc = pg.get_by_test_id("pacing")
        await pc.get_by_role("button", name="Lively").click()
        await pc.get_by_test_id("pacing-result").wait_for()
        rows = await pc.get_by_test_id("slow-row").count()
        strips = await pg.get_by_test_id("slow-stretch").count()
        before = await pc.get_by_test_id("pacing-result").inner_text()
        print("pacing:", before, "| rows", rows, "| on the ruler", strips)
        assert rows > 0 and strips == rows
        await pc.get_by_role("button", name="Punch in all of them").click()
        await saved()
        await pg.wait_for_timeout(300)
        after = await pc.inner_text()
        print("after punch-ins:", "nice pacing" in after, "|", (await pc.get_by_test_id("pacing-result").inner_text()) if await pc.get_by_test_id("pacing-result").count() else "")
        assert await pc.get_by_test_id("slow-row").count() < rows
        await no_overflow("AI tab")
        await pg.screenshot(path=str(TMP / "pacing.png"))

        assert not errs, errs
        await b.close()

    j = api("POST", f"/api/projects/{pid}/exports", {"filename": "phase19", "quality": "draft"})
    j = wait_job(j["id"])
    assert j["status"] == "succeeded", j.get("error_detail")
    print("export ok:", j["result"]["file"])


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
