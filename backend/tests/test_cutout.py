"""Phase 8.6: thumbnail subject cut-out, library images, face detection."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.cutout import cut_out


def scene(w=800, h=450, seed=1):
    rng = np.random.default_rng(seed)
    img = (rng.integers(0, 60, (h, w, 3))).astype(np.uint8)  # busy dark background
    img[:, :, 1] += 40
    mask = np.zeros((h, w), np.uint8)
    cv2.ellipse(mask, (w // 2, int(h * 0.62)), (int(w * 0.17), int(h * 0.36)), 0, 0, 360, 255, -1)
    img[mask > 0] = (40, 60, 230)  # a bold red "subject" in the middle
    return img, mask


def test_cutout_finds_the_subject():
    img, truth = scene()
    out, info = cut_out(img)
    assert out.shape[2] == 4 and info["method"] in ("centre", "face")
    # put the alpha back on the full canvas to compare with the truth
    full = np.zeros(truth.shape, np.uint8)
    ys, xs = np.nonzero(truth)
    # the cut-out is cropped to the subject (+2% padding): it must contain the whole ellipse
    assert out.shape[0] >= ys.max() - ys.min() and out.shape[1] >= xs.max() - xs.min()
    a = out[:, :, 3] > 127
    area_ratio = a.sum() / (truth > 0).sum()
    assert 0.85 < area_ratio < 1.2, area_ratio
    # the background is transparent (corners of the crop)
    assert out[0, 0, 3] < 30 and out[-1, -1, 3] < 30 or out[0, -1, 3] < 30


def test_cutout_rejects_an_empty_picture():
    flat = np.full((300, 400, 3), 128, np.uint8)
    with pytest.raises(ValueError):
        cut_out(flat)


def test_api_cutout_and_library_image(server):
    c = server
    _, p, _ = c.req("POST", "/api/projects", {"name": "thumb"})
    pid = p["id"]
    img, _ = scene()
    ok, png = cv2.imencode(".png", img)
    st, a, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/assets", raw=png.tobytes())
    assert st == 201
    st, cut, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/assets/{a['id']}/cutout")
    assert st == 201 and cut["kind"] == "cutout" and cut["width"] < img.shape[1]
    st, data, _ = c.req("GET", f"/api/projects/{pid}/thumbnails/assets/{cut['id']}")
    dec = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    assert dec.shape[2] == 4  # transparent background survives storage
    assert c.req("POST", f"/api/projects/{pid}/thumbnails/assets/{'0' * 32}/cutout")[0] == 404
    _, li, _ = c.req("POST", "/api/library/images?name=Me%20shocked", raw=png.tobytes())
    st, m, _ = c.req("POST", f"/api/projects/{pid}/thumbnails/assets/from-library", {"id": li["id"]})
    assert st == 201 and m["label"] == "Me shocked"
    assert c.req("POST", f"/api/projects/{pid}/thumbnails/assets/from-library", {"id": "../x"})[0] == 404
    c.req("PUT", f"/api/projects/{pid}/publish", {"title": "I survived 100 days"})
    assert c.req("GET", f"/api/projects/{pid}/thumbnails")[1]["publish_title"] == "I survived 100 days"


def test_face_detection_is_available_for_thumbnails():
    from app import thumb_analysis as ta
    st = ta.frame_stats(np.zeros((360, 640, 3), np.uint8))
    assert st["faces"] == 0  # None would mean the face model is missing
