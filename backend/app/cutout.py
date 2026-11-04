"""Quick subject cut-out for thumbnails (free, local, no AI model download).

OpenCV's GrabCut separates the subject from the background, seeded from where the face
is (head + shoulders below it) or, without a face, from the middle of the frame. The
largest region is kept, holes are closed and the edge is softened. Good for a bold
"you on top of the background" thumbnail; edges around hair can be rough, and the UI
says so.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

WORK = 640


def _face(gray: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    from .shorts import _detector
    det = _detector()
    if det is None:
        return None
    faces = det(gray)
    return max(faces, key=lambda f: f[2] * f[3]) if faces else None


def cut_out(img: np.ndarray, iterations: int = 5) -> tuple[np.ndarray, dict]:
    """BGRA image cropped to the subject, and info about how it was found."""
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    h, w = img.shape[:2]
    k = min(1.0, WORK / max(h, w))
    small = cv2.resize(img, (max(8, int(w * k)), max(8, int(h * k))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    face = _face(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
    if face is not None:
        fx, fy, fw, fh = face
        x0, x1 = max(1, int(fx - 1.1 * fw)), min(sw - 2, int(fx + 2.1 * fw))
        y0, y1 = max(1, int(fy - 0.7 * fh)), sh - 2
    else:
        x0, x1, y0, y1 = int(sw * 0.12), int(sw * 0.88), int(sh * 0.06), sh - 2
    rect = (x0, y0, max(4, x1 - x0), max(4, y1 - y0))
    mask = np.zeros((sh, sw), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    if face is not None:  # the face itself is certainly the subject
        mask[:] = cv2.GC_BGD
        mask[y0:y1, x0:x1] = cv2.GC_PR_FGD
        mask[fy + fh // 5: fy + fh * 4 // 5, fx + fw // 5: fx + fw * 4 // 5] = cv2.GC_FGD
        cv2.grabCut(small, mask, None, bgd, fgd, iterations, cv2.GC_INIT_WITH_MASK)
    else:
        cv2.grabCut(small, mask, rect, bgd, fgd, iterations, cv2.GC_INIT_WITH_RECT)
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    # keep the biggest piece, close small holes
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if n <= 1:
        raise ValueError("Couldn't find a subject to cut out in this image.")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    fg = np.where(labels == biggest, 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    if fg.mean() < 255 * 0.01:
        raise ValueError("Couldn't find a subject to cut out in this image.")
    alpha = cv2.resize(fg, (w, h), interpolation=cv2.INTER_LINEAR)
    alpha = cv2.GaussianBlur(alpha, (0, 0), max(1.0, 1.2 / k))  # soft edge
    ys, xs = np.nonzero(alpha > 8)
    pad = int(0.02 * max(h, w))
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
    out = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    out[:, :, 3] = alpha
    info = {"method": "face" if face is not None else "centre", "coverage": round(float((alpha > 127).mean()), 3)}
    return out[y0:y1, x0:x1].copy(), info
