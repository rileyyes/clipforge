"""Backend cross-check: every timeline produced by the frontend fuzz test must pass
the server's schema + semantic validation (the server is the authority on saves).

Run after `npm test` in frontend/:  python scripts/crosscheck.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.schema import Project  # noqa: E402

data = json.loads((ROOT / "frontend/.test-build/fuzz_timelines.json").read_text())
ok = 0
for i, tl in enumerate(data["timelines"]):
    Project.model_validate({"id": "f" * 32, "name": f"fuzz {i}", "media": data["media"], "timeline": tl})
    ok += 1
clips = sum(len(t["clips"]) for tl in data["timelines"] for t in tl["tracks"])
print(f"crosscheck: {ok} engine-produced timelines ({clips} clips) accepted by the backend")
