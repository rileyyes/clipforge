"""Browser end-to-end test of Phase 10: edit by transcript, filler/retake removal,
titles, privacy blur (drawn + followed), music beat sync.

A talking video with a transcript (written directly, so no speech model is needed) and a
120 BPM song on the music track -> Script: remove fillers, retakes, cut a selected word ->
Text: lower third -> Blur: draw one on the preview, follow it -> Beat: find the beat,
snap cuts -> reload keeps it all -> export validates, with the title and the blur in it.
Fails on console/page errors.

Run:  python scripts/e2e_phase10.py      (needs Playwright + built frontend)
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
sys.path[:0] = [str(ROOT / "backend" / "tests"), str(ROOT / "backend")]
TMP = Path(tempfile.mkdtemp(prefix="clipforge-e2e-p10-"))
PORT = 8804
B = f"http://127.0.0.1:{PORT}"
W, H = 1280, 720
SAY = "so um today I want to show today I want to show you uh my new setup and this is really it"


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


def setup():
    from test_beats import song
    d = 14
    vid, mus = TMP / "talk.mp4", TMP / "song.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=30:d={d}",
                    "-f", "lavfi", "-i", f"aevalsrc='0.3*sin(2*PI*180*t)*lt(mod(t,0.4),0.3)':s=48000:d={d}",
                    "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=True)
    x, _ = song(120, 30)
    raw = TMP / "song.f32"
    (x / np.abs(x).max() * 0.8).astype(np.float32).tofile(raw)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", "11025", "-ac", "1", "-i", str(raw),
                    "-c:a", "aac", str(mus)], check=True)
    p = api("POST", "/api/projects", {"name": "Setup tour"})
    pid = p["id"]
    v = api("POST", f"/api/projects/{pid}/media?filename=talk.mp4", raw=vid.read_bytes())
    m = api("POST", f"/api/projects/{pid}/media?filename=song.m4a", raw=mus.read_bytes())
    for r in (v, m):
        if r.get("job_id"):
            wait_job(r["job_id"])
    vid_id, mus_id = v["media"]["id"], m["media"]["id"]
    # transcript, as the speech-to-text would write it
    words, t = [], 1.0
    for w in SAY.split():
        words.append({"start": round(t, 3), "end": round(t + 0.3, 3), "text": w, "p": 0.9})
        t += 0.45
    an = TMP / "ws" / "projects" / pid / "analysis"
    an.mkdir(parents=True, exist_ok=True)
    (an / f"{vid_id}.json").write_text(json.dumps({"version": 1, "media_id": vid_id, "duration": d, "hop": 0.05,
                                                   "rms_db": [-20.0] * int(d / 0.05), "motion": [], "cuts": [], "words": words}))
    p = api("GET", f"/api/projects/{pid}")
    link = os.urandom(16).hex()
    clip = lambda: {"id": os.urandom(16).hex(), "media_id": vid_id, "start": 0, "source_in": 0, "source_out": d, "link_id": link}  # noqa: E731
    p["timeline"]["tracks"][0]["clips"] = [clip()]
    p["timeline"]["tracks"][2]["clips"] = [clip()]
    p["timeline"]["tracks"][3]["clips"] = [{"id": os.urandom(16).hex(), "media_id": mus_id, "start": 0, "source_in": 0, "source_out": 30}]
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
                                               "output": {"width": W, "height": H, "fps": 30, "fit_mode": "fit"}})
    return pid


async def main(pid):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        toast = lambda text: pg.get_by_text(text, exact=False).first.wait_for(timeout=60000)  # noqa: E731
        await pg.goto(B + f"/#/editor/{pid}")
        await pg.locator(".clip.video").first.wait_for()

        # ---- Script: fillers, retakes, cut a word
        await pg.get_by_role("tab", name="Script").click()
        panel = pg.get_by_test_id("script-panel")
        await panel.wait_for()
        n_words = await panel.locator(".script-word").count()
        print("script words:", n_words)
        assert n_words == len(SAY.split())
        await panel.get_by_role("button", name="Remove 2 filler words").click()
        await toast("Removed 2 filler words")
        await panel.get_by_role("button", name="Remove 1 retake").click()
        await toast("Removed 1 retake")
        words = await panel.locator(".script-word").all_inner_texts()
        print("after cleanup:", " ".join(words))
        assert words == "so today I want to show you my new setup and this is really it".split()
        await panel.locator(".script-word", has_text="really").click()
        await panel.get_by_role("button", name="Cut", exact=True).click()
        await toast("Ctrl+Z to undo")
        words = await panel.locator(".script-word").all_inner_texts()
        assert "really" not in words, words
        clips = await pg.locator(".clip.video").count()
        print("video clips after cuts:", clips)
        assert clips == 4

        # ---- Text: lower third
        await pg.get_by_role("tab", name="Text", exact=True).click()
        await pg.keyboard.press("Home")
        await pg.get_by_test_id("titles-panel").get_by_role("button", name="Lower third").click()
        await pg.get_by_label("Title text").fill("RileyPlays")
        for _ in range(30):
            await pg.keyboard.press("ArrowRight")
        prev = pg.get_by_test_id("title-preview")
        await prev.wait_for()
        assert "RileyPlays" in await prev.inner_text()

        # ---- Blur: draw a box on the preview, follow it
        await pg.get_by_role("tab", name="Blur", exact=True).click()
        await pg.get_by_test_id("blur-panel").get_by_role("button", name="Draw a blur").click()
        layer = pg.get_by_test_id("draw-layer")
        box = await layer.bounding_box()
        x0, y0 = box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.2
        await pg.mouse.move(x0, y0)
        await pg.mouse.down()
        await pg.mouse.move(x0 + box["width"] * 0.15, y0 + box["height"] * 0.2, steps=5)
        await pg.mouse.up()
        await toast("Blur added")
        await pg.get_by_test_id("blur-preview").first.wait_for()
        await pg.get_by_test_id("blur-panel").get_by_role("button", name="Follow it").click()
        await toast("Following it now")

        # ---- Beat: find it, snap cuts
        await pg.get_by_role("tab", name="Music", exact=True).click()
        bp = pg.get_by_test_id("beat-panel")
        await bp.get_by_role("button", name="Find the beat").click()
        await bp.get_by_text("BPM").wait_for(timeout=60000)
        bpm = await bp.get_by_text("BPM").inner_text()
        print("song:", bpm)
        assert abs(float(bpm.split()[0]) - 120) < 2
        await bp.get_by_role("button", name="Snap cuts to the beat").click()
        await toast("moved onto the beat")
        await pg.get_by_text("All changes saved").wait_for(timeout=15000)
        await pg.screenshot(path=str(TMP / "editor_p10.png"))

        # ---- reload keeps it all
        await pg.reload()
        await pg.locator(".clip.video").first.wait_for()
        p = api("GET", f"/api/projects/{pid}")
        tl = p["timeline"]
        print("saved: clips", len(tl["tracks"][0]["clips"]), "titles", len(tl["titles"]), "blur keys", len(tl["blurs"][0]["keys"]))
        assert len(tl["tracks"][0]["clips"]) == 4 and tl["titles"][0]["text"] == "RileyPlays" and len(tl["blurs"]) == 1

        # ---- export: valid, with the title and the blur in it
        job = api("POST", f"/api/projects/{pid}/exports", {"filename": "p10", "quality": "draft"})
        j = wait_job(job["id"], 600)
        assert j["status"] == "succeeded" and j["result"]["validation"]["ok"], j
        out = TMP / "ws" / "projects" / pid / "exports" / j["result"]["file"]
        ttl = tl["titles"][0]
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(ttl["start"] + 1.5), "-i", str(out), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        f = np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)
        lower = f[int(H * 0.65):int(H * 0.92), :int(W * 0.5)]
        accent = np.all(np.abs(lower - np.array([255, 90, 60])) < 45, axis=2).mean()
        print("export validated; lower-third accent pixels:", round(float(accent), 4))
        assert accent > 0.001
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
        asyncio.run(main(setup()))
        print("OK — screenshots in", TMP)
    finally:
        srv.terminate()
