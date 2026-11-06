"""Browser end-to-end test of Phase 14: background music + captions.

At 1280×720: Music tab -> import an 8 s song -> From 0:05 To 0:25 -> Add music (it loops
3×) -> ducking -> the captions show in the preview -> Script tab: double-click a
misheard word and fix it -> the preview caption changes -> remove the music, undo ->
export: the song is heard from 5 s to 25 s and not before; the captions file has the
fixed word. The side panel must fit. Fails on page errors.

Run:  python scripts/e2e_phase14.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="clipforge-e2e-p14-"))
PORT = 8808
B = f"http://127.0.0.1:{PORT}"
SONG_HZ, VOICE_HZ = 880, 220


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-ClipForge": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        raw = r.read()
        return json.loads(raw or b"{}") if r.headers.get_content_type() == "application/json" else raw


def setup():
    v = TMP / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=30", "-f", "lavfi",
                    "-i", f"sine=f={VOICE_HZ}:d=30", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(v)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={SONG_HZ}:d=8", "-c:a", "libmp3lame",
                    str(TMP / "my song.mp3")], check=True)
    p = api("POST", "/api/projects", {"name": "Music + captions"})
    pid = p["id"]
    r = api("POST", f"/api/projects/{pid}/media?filename=talk.mp4", raw=v.read_bytes())
    mid = r["media"]["id"]
    words = [{"text": t, "start": s, "end": e, "p": 0.8} for t, s, e in
             ((" Welcome", 0.2, 0.6), (" to", 0.65, 0.75), (" click", 0.8, 1.1), (" forge.", 1.15, 1.5),
              (" Today", 3.0, 3.3), (" we", 3.35, 3.5), (" edit.", 3.55, 3.9))]
    adir = TMP / "ws" / "projects" / pid / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / f"{mid}.json").write_text(json.dumps({"version": 1, "media_id": mid, "duration": 30.0, "hop": 0.05,
                                                  "rms_db": [], "motion": [], "cuts": [], "words": words}))
    p = api("GET", f"/api/projects/{pid}")
    link = os.urandom(16).hex()
    for ti in (0, 2):
        p["timeline"]["tracks"][ti]["clips"] = [{"id": os.urandom(16).hex(), "media_id": mid, "start": 0, "source_in": 0,
                                                 "source_out": 30, "link_id": link}]
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                               "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"},
                                               "captions": {"enabled": True}})
    return pid, mid


async def main(pid, mid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=20000)  # noqa: E731

        async def until(fn, what, timeout=15):
            end = time.time() + timeout
            while time.time() < end:
                if fn():
                    return
                await pg.wait_for_timeout(200)
            raise AssertionError(what)

        music_clips = lambda: [c for t in api("GET", f"/api/projects/{pid}")["timeline"]["tracks"]  # noqa: E731
                               if t.get("role") == "music" for c in t["clips"]]

        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()

        # ---- captions show in the preview
        await pg.keyboard.press("Home")
        for _ in range(12):
            await pg.keyboard.press("ArrowRight")                        # 0.4 s
        cap = pg.get_by_test_id("caption-preview")
        await cap.wait_for(timeout=10000)
        print("caption preview:", await cap.inner_text())
        assert (await cap.inner_text()).strip() == "WELCOME TO CLICK FORGE."

        # ---- Music tab: import a song, put it from 0:05 to 0:25
        await pg.get_by_role("tab", name="Music", exact=True).click()
        sec = pg.get_by_test_id("music-section")
        await sec.wait_for()
        async with pg.expect_file_chooser() as fc:
            await sec.get_by_role("button", name="Import").click()
        await (await fc.value).set_files(str(TMP / "my song.mp3"))
        await toast("Imported")
        await pg.wait_for_function("() => [...document.querySelectorAll('select[aria-label=Song] option')].some(o => o.selected && o.textContent.includes('my song.mp3'))", timeout=15000)
        await pg.get_by_label("Music from").fill("0:05")
        await pg.get_by_label("Music to").fill("0:25")
        await sec.get_by_role("button", name="Add music").click()
        await toast("looped 3×")
        await until(lambda: len(music_clips()) == 3, "music not saved")
        mc = sorted(music_clips(), key=lambda c: c["start"])
        print("music pieces:", [(c["start"], c["source_in"], c["source_out"]) for c in mc])
        d = mc[0]["source_out"]                                         # the song's real length (MP3 adds a little padding)
        assert 7.9 < d < 8.2 and [round(c["start"], 3) for c in mc] == [5, round(5 + d, 3), round(5 + 2 * d, 3)]
        assert round(mc[-1]["start"] + mc[-1]["source_out"] - mc[-1]["source_in"], 3) == 25
        assert await pg.get_by_test_id("music-item").count() == 1
        await pg.get_by_label("Ducking").select_option("medium")
        await until(lambda: api("GET", f"/api/projects/{pid}")["audio"]["ducking"] == "medium", "ducking not saved")

        # side panel fits
        out = await pg.evaluate("""() => { const col = document.querySelector('.ed-mid').lastElementChild.getBoundingClientRect();
            return [...document.querySelectorAll('.ed-mid > :last-child *')].filter(e => e.getClientRects().length
              && e.getBoundingClientRect().right > col.right + 1).map(e => e.tagName + '.' + e.className + ' +' + Math.round(e.getBoundingClientRect().right - col.right) + ' w' + Math.round(e.getBoundingClientRect().width)).slice(0, 8) }""")
        print("side panel overflow:", out)
        await pg.screenshot(path=str(TMP / "music.png"))
        assert not out, out

        # remove it, then undo
        await pg.get_by_role("button", name="Remove music").click()
        await until(lambda: len(music_clips()) == 0, "music not removed")
        await pg.locator(".monitor").click(position={"x": 5, "y": 5})
        await pg.keyboard.press("Control+z")
        await until(lambda: len(music_clips()) == 3, "undo didn't bring the music back")

        # ---- fix a misheard word in the Script tab
        await pg.get_by_role("tab", name="Script", exact=True).click()
        # the action row must keep its height when a word is selected, even with wider fonts
        await pg.evaluate("""() => { const st = document.createElement('style'); st.id = 'e2e-wide';
            st.textContent = '* { letter-spacing: 0.6px !important }'; document.head.appendChild(st) }""")
        row = pg.locator(".script-actions")
        h0 = (await row.bounding_box())["height"]
        await pg.locator(".script-word", has_text="Today").click()
        await pg.locator(".script-word", has_text="Today").click(modifiers=["Shift"])
        await pg.locator(".script-word", has_text="edit.").click(modifiers=["Shift"])
        h1 = (await row.bounding_box())["height"]
        print("Script action row height:", h0, "->", h1, "(wide text)")
        assert h0 == h1
        await pg.keyboard.press("Escape")
        await pg.evaluate("() => document.getElementById('e2e-wide')?.remove()")
        word = pg.locator(".script-word", has_text="click")
        await pg.evaluate("""() => { window.__blurs = []; document.addEventListener('focusout', (e) => window.__blurs.push(
            (e.target?.tagName || '') + '.' + (e.target?.className || '') + ' -> ' + (e.relatedTarget ? e.relatedTarget.tagName + '.' + e.relatedTarget.className : 'nothing')), true) }""")
        await word.dblclick()
        box = pg.get_by_label("Fix word")
        try:
            await box.wait_for(timeout=5000)
        except Exception:
            await pg.screenshot(path=str(TMP / "fix_word_missing.png"))
            print("DIAG fix box missing | words:", await pg.locator(".script-word").all_inner_texts(),
                  "| selected:", await pg.locator(".script-word.sel").all_inner_texts(),
                  "| focus-outs:", await pg.evaluate("window.__blurs"),
                  "| toasts:", await pg.locator(".toast").all_inner_texts())
            raise
        await box.fill("ClipForge")
        await box.press("Enter")
        await toast("Fixed")
        await pg.keyboard.press("Home")
        for _ in range(12):
            await pg.keyboard.press("ArrowRight")
        await pg.wait_for_function("() => document.querySelector('[data-testid=caption-preview]')?.innerText.includes('CLIPFORGE')", timeout=10000)
        print("caption preview after the fix:", await cap.inner_text())
        assert "CLICK" not in await cap.inner_text()
        assert await pg.locator(".script-word", has_text="ClipForge").count() == 1
        await pg.screenshot(path=str(TMP / "captions_fixed.png"))
        assert not errs, errs
        await b.close()

    srt = api("GET", f"/api/projects/{pid}/captions.srt").decode()
    assert "CLIPFORGE" in srt and "CLICK" not in srt, srt

    # ---- export: the song is heard from 5 to 25 s only
    j = api("POST", f"/api/projects/{pid}/exports", {"filename": "music", "quality": "draft"})
    for _ in range(900):
        j = api("GET", f"/api/jobs/{j['id']}")
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    assert j["status"] == "succeeded", j.get("error_detail")
    out = TMP / "ws" / "projects" / pid / "exports" / j["result"]["file"]
    pcm = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                                       capture_output=True, check=True).stdout, np.int16).astype(np.float32)

    def song_level(t0, t1):
        seg = pcm[int(t0 * 8000):int(t1 * 8000)]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        f = np.fft.rfftfreq(len(seg), 1 / 8000)
        band = lambda hz: spec[(f > hz - 15) & (f < hz + 15)].max()  # noqa: E731
        return band(SONG_HZ) / (band(VOICE_HZ) + 1e-9)
    levels = {t: round(float(song_level(t, t + 1.5)), 4) for t in (1, 7, 14.5, 22, 27)}
    print("song vs voice level:", levels)
    assert levels[1] < 0.01 and levels[27] < 0.01                     # no music before 5 s or after 25 s
    assert all(levels[t] > 0.02 for t in (7, 14.5, 22))                # heard throughout, across the loop joins


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
