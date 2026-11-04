"""Smoke test against a RUNNING ClipForge: import a clip, edit, export twice.

Used by CI to check the Windows portable package works on a clean machine, and handy
for checking any install by hand:

    python scripts/smoke_export.py --base http://127.0.0.1:8765 --ffmpeg path/to/ffmpeg

Standard library only. Makes its own 48-second test video with the given FFmpeg, creates
a project called "Smoke test", exports it (draft quality), checks the validation report,
then exports again and checks the second export reused the cached blocks. Exit code 0 =
everything worked.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()

    def req(method, path, body=None, raw=None):
        hd = {"X-ClipForge": "1"}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            hd["Content-Type"] = "application/json"
        r = urllib.request.Request(a.base + path, data=data, method=method, headers=hd)
        try:
            with urllib.request.urlopen(r, timeout=300) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def wait(jid):
        end = time.time() + a.timeout
        while time.time() < end:
            _, j = req("GET", f"/api/jobs/{jid}")
            if j["status"] not in ("queued", "running"):
                return j
            time.sleep(0.5)
        raise SystemExit(f"job {jid} timed out")

    def step(msg):
        print(f"[smoke] {msg}", flush=True)

    st, sysinfo = req("GET", "/api/system")
    assert st == 200, sysinfo
    step(f"ffmpeg: {sysinfo['ffmpeg']} | encoder: {sysinfo['h264_encoder']} | workspace: {sysinfo['workspace']}")
    assert sysinfo["ffmpeg"] and "unknown" not in str(sysinfo["ffmpeg"]).lower(), "FFmpeg not found by ClipForge"

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "smoke.mp4"
        subprocess.run([a.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=48",
                        "-f", "lavfi", "-i", "sine=f=440:d=48:sample_rate=48000", "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
        st, p = req("POST", "/api/projects", {"name": "Smoke test"})
        assert st == 201, p
        st, r = req("POST", f"/api/projects/{p['id']}/media?filename=smoke.mp4", raw=src.read_bytes())
    assert st == 201, r
    mid = r["media"]["id"]
    step("imported test clip")
    _, p = req("GET", f"/api/projects/{p['id']}")
    link = uuid.uuid4().hex

    def clip(start, a_, b_):
        return {"id": uuid.uuid4().hex, "media_id": mid, "start": start, "source_in": a_, "source_out": b_,
                "link_id": link}
    v1, _v2, a1, _a2 = p["timeline"]["tracks"]
    v1["clips"] = [clip(0, 1, 46)]
    a1["clips"] = [clip(0, 1, 46)]
    st, r = req("PUT", f"/api/projects/{p['id']}/timeline", {
        "base_edit_revision": p["edit_revision"], "timeline": p["timeline"],
        "output": {"width": 640, "height": 360, "fps": 30, "fit_mode": "fit"}})
    assert st == 200, r

    reports = []
    for name in ("smoke1", "smoke2"):
        t0 = time.time()
        st, job = req("POST", f"/api/projects/{p['id']}/exports", {"filename": name, "quality": "draft"})
        assert st == 202, job
        job = wait(job["id"])
        assert job["status"] == "succeeded", job.get("error_detail") or job
        rep = job["result"]["validation"]
        bad = [c for c in rep["checks"] if not c["ok"]]
        assert rep["ok"], bad
        reports.append(rep)
        step(f"export {name}: ok in {time.time() - t0:.1f} s, blocks {rep.get('blocks')}, cache {rep.get('cache')}")
    blocks = reports[1].get("blocks")
    if blocks:  # libx264 path: the unchanged re-export copies every block
        assert blocks["reused"] == blocks["count"], blocks
    req("DELETE", f"/api/projects/{p['id']}")
    step("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
