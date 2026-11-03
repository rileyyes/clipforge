"""Renderer stress test: export timelines produced by the random edit fuzzer
(many clips, speed changes, overlays, gaps, hidden/muted tracks) using real
synthetic media, and require every export to pass validation.

Run after `npm test` in frontend/:  python scripts/render_stress.py [count]
"""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402
from app.media import build_asset  # noqa: E402
from app.projects import ProjectStore  # noqa: E402
from app.render import render_project  # noqa: E402
from app.schema import OutputSettings, Project  # noqa: E402


class Ctx:
    def __init__(self):
        self.job = SimpleNamespace(id="0" * 32)
        self.cancel_event = threading.Event()
        self.last = 0.0

    def stage(self, *a):
        pass

    def progress(self, p):
        assert p is None or p >= self.last - 1e-9, "progress went backwards"
        self.last = p or self.last

    def check_cancel(self):
        pass


def gen(path: Path, dur: float, video: bool, audio: bool):
    a = ["ffmpeg", "-v", "error", "-y"]
    if video:
        a += ["-f", "lavfi", "-i", f"testsrc2=s=480x270:r=30:d={dur}"]
    if audio:
        a += ["-f", "lavfi", "-i", f"sine=f=330:d={dur}"]
    if video:
        a += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    a += ["-c:a", "aac"] if audio and video else []
    subprocess.run(a + [str(path)], check=True)


def main(count: int):
    data = json.loads((ROOT / "frontend/.test-build/fuzz_timelines.json").read_text())
    tmp = Path(tempfile.mkdtemp(prefix="cf-stress-"))
    settings = Settings(workspace=tmp)
    store = ProjectStore(tmp / "projects")
    # rank sample timelines by number of clips; render the busiest ones
    def score(t):  # prefer timelines rich in transitions/fades but not hours long
        clips = [c for x in t["tracks"] for c in x["clips"]]
        dur = max([c["start"] + (c["source_out"] - c["source_in"]) / c["speed"] for c in clips] or [0])
        fx = sum(1 for c in clips if c.get("transition_in") or c.get("fade_in") or c.get("fade_out"))
        return (-(fx * 3 + len(clips)) if dur < 400 else 1e9)
    tls = sorted(data["timelines"], key=score)[:count]
    failures = 0
    for i, tl in enumerate(tls):
        p = store.create(f"stress {i}")
        orig = store.dir(p.id) / "media" / "original"
        media = []
        for m in data["media"]:
            f = orig / (m["id"] + Path(m["stored_name"]).suffix)
            gen(f, m["duration"] + 0.05, m["has_video"], m["has_audio"])
            a = build_asset(settings, m["id"], f, m["original_name"])
            media.append(a.model_dump(mode="json"))
        for t in tl["tracks"]:
            t["locked"] = False
        proj = Project.model_validate({"id": p.id, "name": p.name, "media": media, "timeline": tl,
                                       "output": OutputSettings(width=640, height=360, fps=30).model_dump()})
        clips = sum(len(t["clips"]) for t in tl["tracks"])
        t0 = time.time()
        res = render_project(Ctx(), settings, proj, store.dir(p.id), "stress", "draft", "libx264")
        rep = res["validation"]
        bad = [c for c in rep["checks"] if not c["ok"]]
        failures += bool(bad)
        print(f"timeline {i}: {clips} clips, {proj.timeline.duration:.1f}s -> "
              f"{'OK' if not bad else 'FAIL ' + str(bad)} ({time.time() - t0:.0f}s)")
    shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        sys.exit(f"{failures} render(s) failed validation")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
