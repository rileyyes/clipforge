"""Performance benchmark: a long recording through the whole app, measured.

Makes a synthetic talking-head-like recording (720p30 with moving picture, speech-like
audio with pauses and loud reactions), then via the real HTTP API:
import -> background preparation -> analysis -> AI plan (cut to a target) -> apply ->
export. Reports wall time and peak memory of the server and its FFmpeg children
(sampled every 0.2 s), and writes JSON next to the results table in docs/BENCHMARKS.md.

    python scripts/benchmark.py              # 120-minute source -> 30-minute edit
    python scripts/benchmark.py --minutes 10 --target 3 --export-height 720

Needs psutil (pip install psutil). Uses a temporary workspace; nothing else is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PORT = 8811
B = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None, raw_file: Path | None = None, timeout=600):
    hd = {"X-ClipForge": "1"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hd["Content-Type"] = "application/json"
    if raw_file is not None:
        data = raw_file.open("rb")
        hd["Content-Length"] = str(raw_file.stat().st_size)
    req = urllib.request.Request(B + path, data=data, method=method, headers=hd)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


class MemSampler(threading.Thread):
    """Peak RSS of the server process + all its children (FFmpeg)."""

    def __init__(self, pid: int):
        super().__init__(daemon=True)
        self.proc = psutil.Process(pid)
        self.peak_total = self.peak_server = 0
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                server = self.proc.memory_info().rss
                kids = sum(c.memory_info().rss for c in self.proc.children(recursive=True) if c.is_running())
            except psutil.Error:
                server = kids = 0
            self.peak_server = max(self.peak_server, server)
            self.peak_total = max(self.peak_total, server + kids)
            time.sleep(0.2)

    def reset(self):
        try:
            self.peak_server = self.peak_total = self.proc.memory_info().rss
        except psutil.Error:
            self.peak_total = self.peak_server = 0


def make_source(path: Path, minutes: float):
    d = minutes * 60
    # speech-ish: 190 Hz voice with syllable modulation, 5 s talk / 2 s pause, a loud reaction every 47 s
    audio = (f"aevalsrc='(0.12*lt(mod(t,7),5)*(0.6+0.4*abs(sin(2*PI*4*t)))*sin(2*PI*190*t))"
             f"+0.5*between(mod(t,47),20,21.5)*sin(2*PI*310*t)+0.003*(random(0)*2-1)':s=48000:d={d}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={d}",
                    "-f", "lavfi", "-i", audio, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34",
                    "-g", "300", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-shortest", str(path)],
                   check=True)


def wait(jid: str, poll=1.0) -> dict:
    while True:
        j = api("GET", f"/api/jobs/{jid}")
        if j["status"] not in ("queued", "running"):
            if j["status"] != "succeeded":
                raise RuntimeError(f"job {j['kind']} {j['status']}: {j.get('error')}")
            return j
        time.sleep(poll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=120)
    ap.add_argument("--target", type=float, default=30, help="edit length in minutes")
    ap.add_argument("--export-height", type=int, default=1080, choices=[720, 1080])
    ap.add_argument("--out", default=str(ROOT / "docs" / "benchmark-results.json"))
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="cf-bench-"))
    src = tmp / "long.mp4"
    print(f"making a {a.minutes:g}-minute 720p source…", flush=True)
    t = time.time()
    make_source(src, a.minutes)
    print(f"  {src.stat().st_size / 1e6:.0f} MB in {time.time() - t:.0f} s", flush=True)

    env = {**os.environ, "CLIPFORGE_WORKSPACE": str(tmp / "ws"), "CLIPFORGE_PORT": str(PORT),
           "CLIPFORGE_TRANSCRIBER": "off", "CLIPFORGE_MAX_UPLOAD_MB": str(100 * 1024)}
    srv = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT / "backend", env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results: dict = {"source_minutes": a.minutes, "target_minutes": a.target, "export_height": a.export_height,
                     "machine": {"cpus": os.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
                                 "os": platform.platform(), "python": platform.python_version()},
                     "date": time.strftime("%Y-%m-%d"), "steps": {}}
    mem = MemSampler(srv.pid)
    mem.start()

    def step(name, fn):
        mem.reset()
        t0 = time.time()
        out = fn()
        secs = time.time() - t0
        results["steps"][name] = {"seconds": round(secs, 1), "peak_mb_server": round(mem.peak_server / 2**20),
                                  "peak_mb_total": round(mem.peak_total / 2**20)}
        print(f"  {name:<28} {secs:8.1f} s   peak {mem.peak_total / 2**20:6.0f} MB (server {mem.peak_server / 2**20:.0f})",
              flush=True)
        return out

    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(B + "/api/health")
                break
            except Exception:
                time.sleep(0.2)
        pid = api("POST", "/api/projects", {"name": "benchmark"})["id"]
        up = step("import (upload + probe)", lambda: api("POST", f"/api/projects/{pid}/media?filename=long.mp4",
                                                         raw_file=src, timeout=3600))
        mid = up["media"]["id"]
        step("prepare (thumbs + waveform)", lambda: wait(up["job_id"]))
        step("analysis", lambda: wait(api("POST", f"/api/projects/{pid}/autoedit/analyze",
                                          {"media_id": mid, "transcribe": False})["id"], poll=2))
        settings = {"target_mode": "duration", "target_seconds": a.target * 60, "style": "balanced"}
        plan = step("AI plan", lambda: api("POST", f"/api/projects/{pid}/autoedit/plan", {"media_id": mid, "settings": settings}))
        results["plan"] = {"segments": len(plan["segments"]), "output_seconds": plan["output_duration"]}
        step("apply to timeline", lambda: api("POST", f"/api/projects/{pid}/autoedit/apply",
                                              {"media_id": mid, "settings": settings,
                                               "expected_output": plan["output_duration"]}))
        w = 1920 if a.export_height == 1080 else 1280
        body = {"filename": "bench", "quality": "standard",
                "output": {"width": w, "height": a.export_height, "fps": 30, "fit_mode": "fit"}}
        ex = step("export", lambda: wait(api("POST", f"/api/projects/{pid}/exports", body)["id"], poll=3))
        results["export_validation_ok"] = ex["result"]["validation"]["ok"]
        ex2 = step("re-export (render cache)", lambda: wait(api("POST", f"/api/projects/{pid}/exports",
                                                                {**body, "filename": "bench2"})["id"], poll=3))
        results["re_export_cache"] = ex2["result"]["validation"].get("cache")
        results["speed"] = {"analysis_x_realtime": round(a.minutes * 60 / results["steps"]["analysis"]["seconds"], 1),
                            "export_x_realtime": round(plan["output_duration"] / results["steps"]["export"]["seconds"], 2)}
    finally:
        mem.stop.set()
        srv.terminate()
    Path(a.out).write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
