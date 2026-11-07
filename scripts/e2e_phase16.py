"""Browser end-to-end test of Phase 16 (smarter AI help).

At 1280×720: AI tab -> Check my hook (weak start) -> "Cut the first … s of quiet" ->
check again -> add the teaser -> Find B-roll (a word said in another recording) -> Add ->
Voiceover (only when a local Piper copy is given: RJCLIP_TEST_PIPER_DIR) -> Music tab ->
Match songs to the video (calm part gets the calm song) -> Use these songs -> export.
The side panel must fit. Fails on page errors.

Run:  python scripts/e2e_phase16.py      (needs Playwright + built frontend)
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
TMP = Path(tempfile.mkdtemp(prefix="rjclip-e2e-p16-"))
PORT = 8810
B = f"http://127.0.0.1:{PORT}"
PIPER = os.environ.get("RJCLIP_TEST_PIPER_DIR")


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
    main, other = TMP / "main.mp4", TMP / "castle tour.mp4"
    calm, hype = TMP / "calm song.wav", TMP / "hype song.wav"
    ff("-f", "lavfi", "-i", "color=c=0x303030:s=640x360:r=30:d=60", "-f", "lavfi", "-i", "sine=f=220:d=60", "-shortest",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(main))
    ff("-f", "lavfi", "-i", "color=c=0x2060c0:s=640x360:r=30:d=12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(other))
    ff("-f", "lavfi", "-i", "sine=f=330:d=25,volume=0.12", str(calm))
    ff("-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*60*t)*exp(-25*mod(t\\,0.4))+0.3*(random(0)-0.5)*exp(-60*mod(t+0.2\\,0.4))':d=25", str(hype))
    p = api("POST", "/api/projects", {"name": "Smarter"})
    pid = p["id"]
    up = lambda f: api("POST", f"/api/projects/{pid}/media?filename={urllib.request.quote(f.name)}", raw=f.read_bytes())["media"]["id"]  # noqa: E731
    mid, oid = up(main), up(other)
    up(calm), up(hype)
    adir = TMP / "ws" / "projects" / pid / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    hop = 0.05
    n = int(60 / hop)
    # quiet for 3.5 s, then talking; calm 0-30 s, lively 30-60 s with a big moment at 40 s
    rms = [-60.0] * int(3.5 / hop) + [-28.0] * (int(30 / hop) - int(3.5 / hop)) + [-14.0] * (n - int(30 / hop))
    for k in range(int(40 / hop), int(43 / hop)):
        rms[k] = -4.0
    motion = [0.05] * int(30 / hop) + [0.8] * (n - int(30 / hop))
    talk = ["so", "today", "we", "explore", "the", "castle", "and", "it", "is", "huge."]
    words = [{"text": " " + talk[i % len(talk)], "start": 3.6 + i * 0.45, "end": 3.6 + i * 0.45 + 0.3, "p": 0.9} for i in range(110)]
    (adir / f"{mid}.json").write_text(json.dumps({"version": 1, "media_id": mid, "duration": 60, "hop": hop, "rms_db": rms,
                                                  "motion": motion, "cuts": [], "words": words}))
    (adir / f"{oid}.json").write_text(json.dumps({"version": 1, "media_id": oid, "duration": 12, "hop": hop, "rms_db": [-30.0] * 240,
                                                  "motion": [0.3] * 240, "cuts": [], "words": [
        {"text": " look", "start": 1.0, "end": 1.3, "p": 0.9}, {"text": " at", "start": 1.4, "end": 1.5, "p": 0.9},
        {"text": " this", "start": 1.6, "end": 1.8, "p": 0.9}, {"text": " castle", "start": 5.0, "end": 5.5, "p": 0.9}]}))
    p = api("GET", f"/api/projects/{pid}")
    link = os.urandom(16).hex()
    for ti in (0, 2):
        p["timeline"]["tracks"][ti]["clips"] = [{"id": os.urandom(16).hex(), "media_id": mid, "start": 0, "source_in": 0, "source_out": 60, "link_id": link}]
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                               "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"}})
    return pid, mid, oid


def tl(pid):
    return api("GET", f"/api/projects/{pid}")["timeline"]


async def main(pid, mid, oid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=60000)  # noqa: E731

        async def until(fn, what, timeout=30):
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

        v1 = lambda: sorted(tl(pid)["tracks"][0]["clips"], key=lambda c: c["start"])  # noqa: E731
        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()
        await pg.get_by_role("tab", name="AI", exact=True).click()
        panel = pg.get_by_test_id("smart-panel")
        await panel.wait_for()

        # ---- hook: weak start -> cut the quiet start
        await panel.get_by_role("button", name="Check my hook").click()
        res = pg.get_by_test_id("hook-result")
        await res.wait_for()
        score1 = int(await res.locator(".hook-score").inner_text())
        print("hook score before:", score1, "|", (await res.inner_text()).replace("\n", " | ")[:220])
        assert score1 < 60
        await res.get_by_role("button", name="Cut the first").click()
        await toast("check the hook again")
        await until(lambda: abs(v1()[0]["source_in"] - 3.4) < 0.05, "quiet start not cut")
        await pg.wait_for_function("() => /All changes saved/.test(document.body.innerText)", timeout=15000)
        await pg.wait_for_timeout(600)
        await panel.get_by_role("button", name="Check my hook").click()
        await res.wait_for()
        score2 = int(await res.locator(".hook-score").inner_text())
        print("hook score after cutting the quiet start:", score2)
        assert score2 > score1
        # ---- teaser
        await res.get_by_role("button", name="as a teaser").click()
        await until(lambda: 35 <= v1()[0]["source_in"] <= 42 and len(v1()) == 2, "teaser not added")
        print("teaser:", {k: round(v1()[0][k], 2) for k in ("start", "source_in", "source_out")})
        assert not await overflow(), await overflow()

        # ---- B-roll from the other recording
        await pg.wait_for_function("() => /All changes saved/.test(document.body.innerText)", timeout=15000)
        await pg.wait_for_timeout(600)
        await panel.get_by_role("button", name="Find B-roll").click()
        row = pg.get_by_test_id("broll-row").first
        await row.wait_for()
        print("B-roll:", await row.inner_text())
        assert "castle" in (await row.inner_text()).lower()
        await row.get_by_role("button", name="Add").click()
        await until(lambda: any(c["media_id"] == oid for t in tl(pid)["tracks"] if t["kind"] == "video" for c in t["clips"]), "B-roll not added")

        # ---- voiceover (needs a local Piper copy)
        if PIPER:
            await panel.get_by_role("button", name="Download the voice").click()
            await pg.get_by_label("Voiceover text").wait_for(timeout=180000)
            await pg.get_by_label("Voiceover text").fill("Welcome to the castle. It is huge.")
            await panel.get_by_role("button", name="Add voiceover").click()
            await toast("Voiceover added")
            await until(lambda: any(c.get("label") == "Voiceover" for t in tl(pid)["tracks"] for c in t["clips"]), "voiceover not on the timeline")
            print("voiceover added")
        else:
            print("voiceover: skipped (set RJCLIP_TEST_PIPER_DIR)")
        await pg.screenshot(path=str(TMP / "ai_tab.png"))
        assert not await overflow(), await overflow()

        # ---- music matched to the video
        await pg.get_by_role("tab", name="Music", exact=True).click()
        await pg.get_by_role("button", name="Match songs to the video").click()
        plan = pg.get_by_test_id("music-plan")
        await plan.wait_for(timeout=120000)
        rows = (await plan.inner_text()).replace("\n", " | ")
        print("music plan:", rows[:300])
        assert "calm song" in rows and "hype song" in rows
        await plan.get_by_role("button", name="Use these songs").click()
        await toast("song part")
        await until(lambda: len({c["media_id"] for t in tl(pid)["tracks"] if t.get("role") == "music" for c in t["clips"]}) == 2, "songs not added")
        assert not await overflow(), await overflow()
        await pg.screenshot(path=str(TMP / "music_plan.png"))
        assert not errs, errs
        await b.close()

    j = api("POST", f"/api/projects/{pid}/exports", {"filename": "smart", "quality": "draft"})
    for _ in range(1200):
        j = api("GET", f"/api/jobs/{j['id']}")
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    assert j["status"] == "succeeded", j.get("error_detail")
    print("export ok:", j["result"]["file"])


if __name__ == "__main__":
    env = {**os.environ, "RJCLIP_WORKSPACE": str(TMP / "ws"), "RJCLIP_PORT": str(PORT), "RJCLIP_TRANSCRIBER": "off"}
    if PIPER:
        d = Path(PIPER)
        voice = next(d.glob("**/*.onnx"))
        env.update(RJCLIP_PIPER_URL=(d / "piper_linux_x86_64.tar.gz").as_uri(), RJCLIP_VOICE_URL=voice.parent.as_uri() + "/",
                   RJCLIP_VOICE_NAME=voice.name[: -len(".onnx")])
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
