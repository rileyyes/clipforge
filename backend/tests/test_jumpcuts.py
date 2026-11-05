"""Phase 9: smoother jump cuts. Shared vectors with the Editor's TypeScript version."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import jumpcuts as J
from app.schema import Timeline

VECTORS = json.loads((Path(__file__).parent / "data" / "jumpcut_vectors.json").read_text())


def _summary(tl: dict) -> list:
    v = next(t for t in tl["tracks"] if t["kind"] == "video")
    return [[(c.get("crop") or {}).get("left", 0) > 0, (c.get("transition_in") or {}).get("kind")]
            for c in sorted(v["clips"], key=lambda c: c["start"])]


@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_vectors(case):
    tl = case["timeline"]
    for mode, expect in case["expect"].items():
        out, n = J.smooth(tl, mode)
        Timeline.model_validate(out)
        assert _summary(out) == expect["summary"], (mode, _summary(out))
        assert n == expect["count"]
        again, _ = J.smooth(out, mode)          # idempotent
        assert _summary(again) == expect["summary"]
        off, _ = J.smooth(out, "off")           # fully reversible
        assert _summary(off) == _summary(J.smooth(tl, "off")[0])


def test_users_own_crop_and_transitions_are_kept():
    tl = VECTORS[0]["timeline"]
    v = next(t for t in tl["tracks"] if t["kind"] == "video")
    v["clips"][1]["crop"] = {"left": 0.2, "right": 0, "top": 0, "bottom": 0}
    v["clips"][2]["transition_in"] = {"kind": "spin", "duration": 0.5}
    out, _ = J.smooth(tl, "punch")
    out, _ = J.smooth(out, "blend")
    out, _ = J.smooth(out, "off")
    vo = next(t for t in out["tracks"] if t["kind"] == "video")
    assert vo["clips"][1]["crop"]["left"] == 0.2
    assert vo["clips"][2]["transition_in"]["kind"] == "spin"
