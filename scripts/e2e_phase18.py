"""Browser end-to-end test of Phase 18 (fonts, reaction & group tools, new looks).

At 1280×720:
- Settings: the built-in fonts are listed; add your own .ttf (shows up, can be used); a web
  font file is turned down with a message.
- Text tab: a pop-up title gets the Horror preset (Creepster really loaded and drawn), an
  outline and glow; your own font; an emoji sticker.
- The old counter tools are gone from the app: no counter, callout or tally wording or buttons.
- Name tags on two mics; the tag of whoever is loud lights up in the preview.
- Audio track set to narration (the track button cycles dialogue → music → narration).
- Effects: a combo adds zoom + shake + boom at once; the sound board drops a sound; caption font.
- Clip tab: VHS look shows its overlay in the preview.
- AI tab: the funny-moment finder finds the loud reaction (with the build-up before it);
  "Keep only these" cuts the rest; undo.
- Export succeeds with all of it.
Fails on console/page errors.

Run:  python scripts/e2e_phase18.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p18-"))
PORT = 8812
B = f"http://127.0.0.1:{PORT}"
SECS = 40


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-RJClip": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def voice(path, loud, video=True):
    """Talking (syllable-like) all through, much louder during `loud`."""
    expr = f"(0.08+0.6*between(t,{loud[0]},{loud[1]}))*sin(2*PI*300*t)*(0.5+0.5*sin(2*PI*4*t))"
    args = ["ffmpeg", "-v", "error", "-y"]
    if video:
        args += ["-f", "lavfi", "-i", f"testsrc2=s=640x360:r=30:d={SECS}"]
    args += ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={SECS}"]
    args += (["-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"] if video else []) + ["-c:a", "aac", str(path)]
    subprocess.run(args, check=True)
    return path


def wait_job(jid):
    for _ in range(600):
        j = api("GET", f"/api/jobs/{jid}")
        if j["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
            return j
        time.sleep(0.2)
    raise TimeoutError(jid)


def hexid():
    return os.urandom(16).hex()


def setup():
    me, friend = voice(TMP / "me.mp4", (24, 27)), voice(TMP / "friend.m4a", (24.5, 28), video=False)
    pid = api("POST", "/api/projects", {"name": "Phase 18 test"})["id"]
    ids = []
    for f in (me, friend):
        r = api("POST", f"/api/projects/{pid}/media?filename={f.name}", raw=f.read_bytes())
        wait_job(r["job_id"])
        ids.append(r["media"]["id"])
    p = api("GET", f"/api/projects/{pid}")
    t = p["timeline"]
    link = hexid()
    mk = lambda m, ln=None: {"id": hexid(), "media_id": m, "start": 0, "source_in": 0, "source_out": SECS, "link_id": ln}  # noqa: E731
    t["tracks"][0]["clips"] = [mk(ids[0], link)]
    t["tracks"][2]["clips"] = [mk(ids[0], link)]
    t["tracks"].append({"id": hexid(), "kind": "audio", "name": "A3", "clips": [mk(ids[1])]})
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": t,
                                               "output": {"width": 1280, "height": 720, "fps": 30, "fit_mode": "fit"}})
    return pid


def project(pid):
    return api("GET", f"/api/projects/{pid}")


def a_font_file() -> bytes:
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(cand).is_file():
            return Path(cand).read_bytes()
    import matplotlib  # noqa: F401  (CI: matplotlib ships DejaVu)
    from matplotlib import font_manager
    return Path(font_manager.findfont("DejaVu Serif")).read_bytes()


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text and "415" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept(d.default_value) if d.type == "prompt" else d.accept()))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=20000)  # noqa: E731

        async def saved():
            await pg.wait_for_timeout(150)
            await pg.wait_for_function("() => /All changes saved/.test(document.body.innerText) && !/Unsaved|Saving/.test(document.querySelector('.ed-top')?.innerText || '')", timeout=15000)

        async def no_overflow(where):
            """Nothing in the visible side panel sticks out sideways (it's narrow at 1280 px)."""
            wide = await pg.evaluate("""() => [...document.querySelectorAll('.pane-body')].filter(p => p.offsetParent).flatMap(p => {
                const r = p.getBoundingClientRect(); return [...p.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
                return b.width > 0 && b.height > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).map(e => e.outerHTML.slice(0, 120)); }).slice(0, 5)""")
            assert not wide, (where, wide)

        async def seek(t):
            """Click the ruler at t s (pixels per second from the 40 s main clip, after Fit timeline)."""
            c = await pg.locator(".clip.video").first.bounding_box()
            r = await pg.locator(".ruler").bounding_box()
            await pg.mouse.click(c["x"] + t * c["width"] / SECS, r["y"] + r["height"] / 2)
            await pg.wait_for_timeout(250)

        # ---- Settings: fonts
        await pg.goto(B + "/#/settings")
        card = pg.get_by_test_id("fonts-card")
        await card.get_by_text("Creepster").wait_for()
        font = TMP / "My Serif.ttf"
        font.write_bytes(a_font_file())
        await card.locator("input[type=file]").set_input_files(str(font))
        await card.get_by_test_id("my-font").first.wait_for()
        fonts = api("GET", "/api/fonts")["fonts"]
        mine = next(f for f in fonts if f["source"] == "yours")
        print("my font:", mine["family"], mine["id"])
        bad = TMP / "web.woff"
        bad.write_bytes(b"wOFF" + font.read_bytes()[4:])
        await card.locator("input[type=file]").set_input_files(str(bad))
        await toast("Web fonts")

        # ---- editor, Text tab: pop-up title with the Horror preset
        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.get_by_role("button", name="Fit timeline").click() if await pg.get_by_role("button", name="Fit timeline").count() else \
            await pg.locator("button[title='Fit timeline']").click()
        await pg.get_by_role("tab", name="Text", exact=True).click()
        panel = pg.get_by_test_id("titles-panel")
        await seek(2)
        await panel.get_by_role("button", name="Pop-up words").click()
        style = panel.get_by_test_id("text-style")
        await style.get_by_role("button", name="Horror", exact=True).click()
        await saved()
        t0 = project(pid)["timeline"]["titles"][0]
        assert t0["font"] == "creepster" and t0["glow"] > 0, t0
        await seek(3)
        prev = pg.get_by_test_id("title-preview").first
        await prev.wait_for()
        ff = await prev.locator("span").first.evaluate("e => getComputedStyle(e).fontFamily")
        assert "rjf-creepster" in ff, ff
        assert await pg.evaluate("() => document.fonts.load(\"40px 'rjf-creepster'\").then(f => f.length > 0)"), "Creepster didn't load"
        await style.get_by_label("Outline", exact=True).fill("12")
        await style.get_by_label("Font", exact=True).select_option(mine["id"])
        await saved()
        t0 = project(pid)["timeline"]["titles"][0]
        assert t0["font"] == mine["id"] and t0["stroke"] == 12, t0
        assert await pg.evaluate(f"() => document.fonts.load(\"40px 'rjf-{mine['id']}'\").then(f => f.length > 0)"), "your font didn't load"
        await pg.screenshot(path=str(TMP / "title_style.png"))
        # save it as my style; it shows with a star
        await style.get_by_role("button", name="Save as my style").click()          # the name prompt is accepted as offered
        await style.get_by_role("button", name="★ My style 1").wait_for()
        assert api("GET", "/api/text-styles")["styles"][0]["font"] == mine["id"]

        # sticker
        await seek(6)
        await panel.get_by_role("button", name="Emoji sticker").click()
        await panel.get_by_test_id("sticker-picker").get_by_role("button", name="Sticker 💀").click()
        await saved()
        st = [x for x in project(pid)["timeline"]["titles"] if x["template"] == "sticker"][0]
        assert st["text"] == "💀", st

        # ---- the counter tools were taken out of the app (owner's request): nothing in the
        # Text tab talks about counting, and no counter / callout / tally buttons are offered
        text = (await panel.inner_text()).lower()
        for w in ("kill", "count it", "final count", "tally", "callout", "counter"):
            assert w not in text, (w, text[:400])
        assert await pg.get_by_test_id("counter-tools").count() == 0

        # ---- name tags
        nt = pg.get_by_test_id("name-tags")
        await nt.get_by_label("Name tag for A1").fill("Me")
        await nt.get_by_label("Name tag for A3").fill("Friend")
        await nt.get_by_label("Show name tags").check()
        await saved()
        await seek(25.5)
        tags = pg.get_by_test_id("name-tag")
        await tags.first.wait_for()
        await pg.wait_for_function("() => [...document.querySelectorAll('[data-testid=name-tag]')].some(e => e.dataset.talking === '1')", timeout=15000)
        await pg.screenshot(path=str(TMP / "name_tags.png"))
        # nothing in the Text tab sticks out sideways (the side panel is narrow at 1280 px)
        wide = await pg.evaluate("""() => { const p = document.querySelector('[data-testid=titles-panel]');
            const r = p.getBoundingClientRect(); return [...p.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
            return b.width > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).slice(0, 5).map(e => e.outerHTML.slice(0, 120)); }""")
        assert not wide, wide

        # ---- narration: A2 (music) button → narration
        btn = pg.locator("button[data-role]").nth(1)            # A1, A2 (music), A3
        role = await btn.get_attribute("data-role")
        for _ in range(3):
            if role == "narration":
                break
            await btn.click()
            await pg.wait_for_timeout(150)
            role = await btn.get_attribute("data-role")
        assert role == "narration", role
        await saved()
        assert any(t.get("role") == "narration" for t in project(pid)["timeline"]["tracks"])

        # ---- effects: combo, sound board, caption font
        await pg.get_by_role("tab", name="Effects").click()
        await seek(12)
        n0 = len(project(pid)["effects"])
        await pg.get_by_test_id("combos").get_by_role("button", name="Meme zoom").click()
        await pg.get_by_test_id("sound-board").get_by_role("button", name="airhorn", exact=True).click()
        await pg.get_by_test_id("combos").get_by_role("button", name="Bass boosted").click()
        await saved()
        kinds = [e["kind"] for e in project(pid)["effects"]][n0:]
        assert sorted(kinds) == sorted(["zoom", "shake", "sfx", "sfx", "bass", "zoom", "shake"]), kinds
        await pg.get_by_label("Caption font").select_option("bangers")
        await saved()
        assert project(pid)["captions"]["font"] == "bangers"
        await no_overflow("Effects tab")

        # ---- clip look: VHS
        await pg.locator(".clip.video").first.click()
        await pg.get_by_role("tab", name="Clip", exact=True).click()
        await pg.get_by_label("Look").select_option("vhs")
        await pg.get_by_test_id("look-overlay").wait_for()
        assert await pg.get_by_test_id("look-overlay").get_attribute("data-look") == "vhs"
        await saved()

        # ---- export with all of it (the export page itself is covered by earlier tests)
        j = api("POST", f"/api/projects/{pid}/exports", {"filename": "phase18", "quality": "draft"})
        for _ in range(1200):
            j = api("GET", f"/api/jobs/{j['id']}")
            if j["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(0.5)
        assert j["status"] == "succeeded", j.get("error_detail")
        print("export ok:", j["result"]["file"], "| checks:", all(c["ok"] for c in j["result"]["validation"]["checks"]))
        out = TMP / "ws" / "projects" / pid / "exports" / j["result"]["file"]
        frame = TMP / "export_9_5s.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "9.5", "-i", str(out), "-frames:v", "1", str(frame)], check=True)

        # ---- AI tab: funny moments (back in the editor)
        await pg.get_by_role("tab", name="AI", exact=True).click()
        fm = pg.get_by_test_id("funny-moments")
        await fm.get_by_role("button", name="Find funny moments").click()
        await fm.get_by_test_id("moment").first.wait_for(timeout=60000)
        n = await fm.get_by_test_id("moment").count()
        first = await fm.get_by_test_id("moment").first.inner_text()
        print("funny moments:", n, "| first:", first.replace("\n", " "))
        assert "2 people" in first
        await no_overflow("AI tab")
        dur0 = max(c["start"] + (c["source_out"] - c["source_in"]) for t in project(pid)["timeline"]["tracks"] for c in t["clips"])
        await fm.get_by_role("button", name="Keep only these").click()
        await toast("Highlights cut")
        await saved()
        dur1 = max(c["start"] + (c["source_out"] - c["source_in"]) for t in project(pid)["timeline"]["tracks"] for c in t["clips"])
        print(f"keep only the funny moments: {dur0:.1f} s -> {dur1:.1f} s")
        assert 5 < dur1 < 15 and dur0 == SECS, (dur0, dur1)
        await pg.locator(".timeline").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Control+z")
        await saved()
        assert abs(max(c["start"] + (c["source_out"] - c["source_in"]) for t in project(pid)["timeline"]["tracks"] for c in t["clips"]) - SECS) < 0.01

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
