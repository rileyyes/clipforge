"""Phase 10: filler words + retakes (shared vectors with the Editor)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import cleanup as C

VECTORS = json.loads((Path(__file__).parent / "data" / "cleanup_vectors.json").read_text())


@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_vectors(case):
    assert C.find(case["words"]) == case["expect"]


def test_cuts_stay_between_neighbours():
    for case in VECTORS:
        w = case["words"]
        for c in C.find(w):
            if c["first"] > 0:
                assert c["start"] >= w[c["first"] - 1]["end"] - 1e-9 or c["kind"] == "retake"
            if c["last"] + 1 < len(w):
                assert c["end"] <= w[c["last"] + 1]["start"] + 1e-9


def test_subtract_segments():
    segs = [{"source_in": 0, "source_out": 10, "beat": 1}, {"source_in": 20, "source_out": 25, "beat": 2}]
    out = C.subtract(segs, [(2, 3), (9.95, 21), (24, 24.1)])
    assert [(s["source_in"], s["source_out"], s["beat"]) for s in out] == [(0, 2, 1), (3, 9.95, 1), (21, 24, 2), (24.1, 25, 2)]
