"""Browser end-to-end test of version history (Phase 5).

Project with 3 clips -> Editor -> History -> Save version "Three clips" -> delete a clip ->
Compare (shows the cut footage) -> Restore "Three clips" -> 3 clips again, undo cleared ->
"Before restore" version listed -> restore that one back -> reload persists. Fails on any
console/page error.

Run:  python scripts/e2e_history.py      (needs Playwright + built frontend)
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

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="clipforge-e2e-hist-"))
PORT = 8796
B = f"http://127.0.0.1:{PORT}"
SRC = TMP / "clip.mp4"


def api(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hd = {"X-ClipForge": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(B + path, data=data, method=method, headers=hd)) as r:
        return json.loads(r.read() or b"{}")


def setup() -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=f=300:d=12", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(SRC)], check=True)
    p = api("POST", "/api/projects", {"name": "History test"})
    pid = p["id"]
    mid = api("POST", f"/api/projects/{pid}/media?filename=clip.mp4", raw=SRC.read_bytes())["media"]["id"]
    p = api("GET", f"/api/projects/{pid}")
    v, a = [], []
    for i, (s, e) in enumerate([(0, 3), (4, 7), (8, 11)]):
        link = uuid.uuid4().hex
        v.append({"id": uuid.uuid4().hex, "media_id": mid, "start": i * 3, "source_in": s, "source_out": e, "link_id": link})
        a.append({"id": uuid.uuid4().hex, "media_id": mid, "start": i * 3, "source_in": s, "source_out": e, "link_id": link})
    p["timeline"]["tracks"][0]["clips"] = v
    p["timeline"]["tracks"][2]["clips"] = a
    api("PUT", f"/api/projects/{pid}/timeline", {"base_edit_revision": p["edit_revision"],
                                                  "timeline": p["timeline"], "output": p["output"]})
    return pid


async def main(pid: str):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1500, "height": 950})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(f"{B}/#/editor/{pid}")
        await pg.locator(".clip").first.wait_for()
        assert await pg.locator(".clip").count() == 6
        await pg.get_by_role("tab", name="History").click()
        panel = pg.get_by_test_id("history-panel")
        await panel.get_by_test_id("version").first.wait_for()  # the first save made an autosave checkpoint
        await panel.get_by_role("button", name="Save this version").click()
        await pg.get_by_label("Name", exact=True).fill("Three clips")
        await pg.get_by_role("button", name="Save", exact=True).click()
        await panel.get_by_text("Three clips").wait_for()
        # delete the middle clip (its linked audio goes with it)
        await pg.locator(".clip").nth(1).click()
        await pg.keyboard.press("Delete")
        assert await pg.locator(".clip").count() == 4
        # compare right away: the panel must save the pending edit before comparing
        # compare the saved version with the current edit
        row = panel.get_by_test_id("version").filter(has_text="Three clips")
        await row.get_by_role("button", name="Compare").click()
        cmpv = pg.get_by_test_id("compare-view")
        await cmpv.get_by_test_id("cmp-source").wait_for(timeout=10000)
        await pg.screenshot(path=str(TMP / "compare.png"))
        text = await cmpv.inner_text()
        print("compare:", " | ".join(text.splitlines()[:14]))
        assert "−3.0s cut" in text, text
        await pg.screenshot(path=str(TMP / "compare.png"))
        await cmpv.get_by_role("button", name="Close").click()
        # restore
        await panel.get_by_test_id("version").filter(has_text="Three clips").get_by_role("button", name="Restore").click()
        await pg.get_by_text("Restored “Three clips”").wait_for()
        assert await pg.locator(".clip").count() == 6
        assert await pg.get_by_title("Undo (Ctrl+Z)").is_disabled()  # undo history belongs to the old state
        before = panel.get_by_test_id("version").filter(has_text="Before restoring")
        await before.wait_for()
        await pg.screenshot(path=str(TMP / "history.png"))
        # undo the restore by restoring the automatic "before restore" version
        await before.get_by_role("button", name="Restore").click()
        for _ in range(50):
            if await pg.locator(".clip").count() == 4:
                break
            await pg.wait_for_timeout(100)
        await pg.reload()
        await pg.locator(".clip").first.wait_for()
        assert await pg.locator(".clip").count() == 4
        print("clips after reload:", await pg.locator(".clip").count(), "· versions:",
              len(api("GET", f"/api/projects/{pid}/history")["versions"]))
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
        asyncio.run(main(setup()))
        print("OK — screenshots in", TMP)
    finally:
        srv.terminate()
