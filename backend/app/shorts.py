"""YouTube Shorts maker: best moments -> vertical 9:16 projects that keep you in frame.

1. **Suggest**: the AI editor's scored moments (sound, picture and, with a transcript,
   laughs/punchlines/stories, plus optional local-AI ratings) are grouped into
   windows of 15-60 s that start and end at pauses. Windows are scored on their
   average, their best moment and their opening (the hook); the best non-overlapping
   ones are suggested, each with its reasons and opening line.
2. **Follow**: frames are sampled twice a second. The largest face is found (OpenCV's
   frontal-face model), falling back to where things move; then the path is cleaned
   (outliers dropped, gaps held) and turned into a calm "camera operator" move. The
   frame only pans when you leave the middle of the shot, with eased moves.
3. **Make**: a new project ("<name> — Short 1") at 1080x1920 that shares the original
   media files (hard links, no extra disk space), with the clip zoomed to fill the frame,
   position keyframes for the follow, your bleeps/effects and captions on.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

from . import autoedit as AE
from . import language
from .ffmpeg import Cancelled, untrusted_input_args

SAMPLE_FPS = 2.0
TRACK_W = 320
MODEL = Path(__file__).parent / "models" / "haarcascade_frontalface_default.xml"


# ---------------------------------------------------------------- suggest
def scored_beats(analysis: dict, style: str = "balanced") -> list:
    duration = float(analysis["duration"])
    preset = AE.SILENCE["balanced"]
    rms = np.asarray(analysis.get("rms_db") or [], dtype=np.float32)
    regions, thr = AE.sound_regions(analysis.get("rms_db") or [], analysis["hop"], duration, preset)
    regions = AE.snap_to_words(regions, analysis.get("words"), duration)
    if not analysis.get("rms_db"):
        regions = [(float(a), float(min(duration, a + 5))) for a in np.arange(0, duration, 5)]
    beats = AE.make_beats(regions, preset["beat_gap"], 12.0, rms, analysis["hop"])
    AE.score_beats(beats, analysis, style, thr)
    return beats


def suggest(analysis: dict, count: int = 3, min_s: float = 15, max_s: float = 60,
            style: str = "balanced") -> list[dict]:
    duration = float(analysis["duration"])
    min_s = min(min_s, max(3.0, duration * 0.9))
    beats = scored_beats(analysis, style)
    words = analysis.get("words") or []
    cands = []
    for i in range(len(beats)):
        for j in range(i, len(beats)):
            start, end = max(0.0, beats[i].start - 0.15), min(duration, beats[j].end + 0.3)
            if end - start > max_s:
                break
            if end - start < min_s:
                continue
            seg = beats[i:j + 1]
            kept = sum(b.kept for b in seg) or 1e-6
            mean = sum(b.score * b.kept for b in seg) / kept
            dead = 1 - kept / (end - start)  # long silences inside make a weak short
            score = 0.5 * mean + 0.3 * max(b.score for b in seg) + 0.2 * seg[0].score - 30 * max(0.0, dead - 0.25)
            cands.append((score, start, end, i, j))
    cands.sort(key=lambda c: (-c[0], c[1]))
    out: list[dict] = []
    for score, start, end, i, j in cands:
        if any(not (end <= o["start"] or start >= o["end"]) for o in out):
            continue
        top = max(beats[i:j + 1], key=lambda b: b.score)
        hook = language.transcript_text(words, start, min(end, start + 8), 140) if words else ""
        out.append({"start": round(start, 2), "end": round(end, 2), "duration": round(end - start, 2),
                    "score": round(max(0.0, score), 1), "reasons": top.reasons[:2], "hook": hook,
                    "title": _title(hook)})
        if len(out) >= count:
            break
    return sorted(out, key=lambda o: -o["score"])


def _title(hook: str) -> str:
    h = hook.strip()
    if not h:
        return ""
    first = h.split(".")[0].split("?")[0].split("!")[0].strip()
    t = (first or h)[:60].strip()
    return t[0].upper() + t[1:] if t else ""


# ---------------------------------------------------------------- follow
@dataclass
class Sample:
    t: float               # source seconds
    cx: Optional[float]    # subject centre x, 0..1 of the frame width (None: not found)
    kind: str              # "face" | "motion" | "none"


def _detector():
    import cv2
    if not hasattr(cv2, "CascadeClassifier"):  # some OpenCV builds leave out the Haar detector
        return None
    clf = cv2.CascadeClassifier(str(MODEL))
    if clf.empty():
        return None

    def detect(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
        return [tuple(int(v) for v in f) for f in clf.detectMultiScale(gray, 1.1, 5, minSize=(24, 24))]
    return detect


def sample_track(ffmpeg: str, src: Path, start: float, end: float, src_w: int, src_h: int,
                 detect: Optional[Callable] = None, on_progress=None, cancel=None) -> list[Sample]:
    """Where the subject is, twice a second: largest face (kept consistent), else motion."""
    w = TRACK_W
    h = max(2, int(round(src_h * w / max(1, src_w) / 2)) * 2)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
           *untrusted_input_args(src, seek=start, duration=max(0.1, end - start)),
           "-an", "-vf", f"fps={SAMPLE_FPS},scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    detect = detect if detect is not None else _detector()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    out: list[Sample] = []
    prev = None
    last_face: Optional[tuple] = None
    n_total = max(1, int((end - start) * SAMPLE_FPS))
    try:
        k = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled("cancelled")
            buf = proc.stdout.read(w * h)
            if len(buf) < w * h:
                break
            g = np.frombuffer(buf, np.uint8).reshape(h, w)
            t = start + k / SAMPLE_FPS
            cx, kind = None, "none"
            faces = detect(g) if detect else []
            if faces:
                if last_face is not None:  # stay with the same person if they're still there
                    lx = last_face[0] + last_face[2] / 2
                    faces = sorted(faces, key=lambda f: abs(f[0] + f[2] / 2 - lx) - 0.5 * f[2])
                else:
                    faces = sorted(faces, key=lambda f: -f[2] * f[3])
                f = faces[0]
                last_face = f
                cx, kind = (f[0] + f[2] / 2) / w, "face"
            elif prev is not None:
                diff = np.abs(g.astype(np.int16) - prev.astype(np.int16)) > 25
                if diff.mean() > 0.002:
                    cols = diff.sum(axis=0).astype(np.float64)
                    cx, kind = float((cols * np.arange(w)).sum() / cols.sum() + 0.5) / w, "motion"
            out.append(Sample(round(float(t), 3), None if cx is None else round(float(cx), 4), kind))
            prev = g
            k += 1
            if on_progress:
                on_progress(min(1.0, k / n_total))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.wait()
    return out


def camera_path(samples: Sequence[Sample], deadzone: float = 0.12, view: float = 0.3164) -> list[tuple[float, float]]:
    """(t, centre x 0..1) of a calm virtual camera that keeps the subject in view.

    ``view`` is the visible width as a fraction of the source (9:16 window of a 16:9
    frame = 0.3164). Faces count more than motion; single-sample jumps are ignored;
    the camera re-centres only when the subject leaves the middle ``deadzone``."""
    if not samples:
        return []
    xs = np.array([np.nan if s.cx is None else s.cx for s in samples], dtype=np.float64)
    ts = np.array([s.t for s in samples])
    faces = np.array([s.kind == "face" for s in samples])
    # when faces exist, motion samples in between are noise (hands, background)
    if faces.mean() > 0.3:
        xs[~faces] = np.nan
    # median filter (5) to drop one-off false detections
    sm = xs.copy()
    for i in range(len(xs)):
        win = xs[max(0, i - 2): i + 3]
        win = win[~np.isnan(win)]
        sm[i] = np.median(win) if win.size else np.nan
    # fill gaps: hold the last known position (start: first known, else centre)
    known = ~np.isnan(sm)
    if not known.any():
        return [(float(ts[0]), 0.5)]
    first = sm[known][0]
    filled, cur = [], first
    for v in sm:
        cur = cur if np.isnan(v) else v
        filled.append(cur)
    half = view / 2
    lo, hi = half, 1 - half
    cam = float(min(hi, max(lo, filled[0])))
    path = [(float(ts[0]), cam)]
    for t, x in zip(ts[1:], filled[1:]):
        if abs(x - cam) > deadzone * view:
            cam = float(min(hi, max(lo, x)))
            if abs(cam - path[-1][1]) > 0.01:
                path.append((float(t), cam))
    return path


def keyframes_for(path: list[tuple[float, float]], picture_w: float, canvas_w: float, move_s: float = 0.6) -> list[dict]:
    """Camera path -> transform-x keyframes (source time). Each re-centre is an eased
    move of ``move_s`` that ends where the subject is."""
    if not path:
        return []
    lim = max(0.0, (picture_w - canvas_w) / 2)

    def x_of(c: float) -> float:
        return float(round(max(-lim, min(lim, -(c - 0.5) * picture_w)), 1))
    kfs = [{"t": round(path[0][0], 3), "v": x_of(path[0][1]), "ease": "ease"}]
    for t, c in path[1:]:
        t0 = max(kfs[-1]["t"] + 0.01, t - move_s)
        kfs.append({"t": round(t0, 3), "v": kfs[-1]["v"], "ease": "ease"})  # hold, then ease to the new spot
        kfs.append({"t": round(max(t0 + 0.01, t), 3), "v": x_of(c), "ease": "ease"})
    # drop no-op holds and keep within the 64-keyframe limit by thinning the middle
    clean = [kfs[0]]
    for k in kfs[1:]:
        if k["t"] - clean[-1]["t"] >= 0.002:
            clean.append(k)
    while len(clean) > 64:
        clean = clean[:1] + clean[1:-1:2] + clean[-1:]
    return clean


# ---------------------------------------------------------------- make
def vertical_geometry(src_w: int, src_h: int, W: int = 1080, H: int = 1920) -> tuple[float, float]:
    """(clip scale, picture width on the canvas) so a fitted landscape picture fills 9:16."""
    fit = min(W / src_w, H / src_h)
    fitted_w, fitted_h = src_w * fit, src_h * fit
    scale = max(1.0, H / fitted_h, W / fitted_w)
    return round(min(scale, 10.0), 4), fitted_w * min(scale, 10.0)


STACK_CAM = 0.4  # stacked layout: the face cam takes the top 40%, the video the rest


def stacked_geometry(src_w: int, src_h: int, W: int = 1080, H: int = 1920) -> tuple[float, float]:
    """(clip scale, y offset px) so the main picture fills the area under the face cam."""
    fit = min(W / src_w, H / src_h)
    fw, fh = src_w * fit, src_h * fit
    area = H * (1 - STACK_CAM)
    scale = max(area / fh, W / fw)
    return round(min(scale, 10.0), 4), round(H * STACK_CAM + area / 2 - H / 2, 2)


def short_facecam(source: dict, media_id: str, layout: str) -> dict | None:
    """The face cam for a Short: kept in its corner, stacked on top, or left out."""
    fc = source.get("facecam")
    if not fc or layout == "none" or fc.get("main_media_id") != media_id:
        return None
    if layout == "stacked":
        return {**fc, "enabled": True, "corner": "custom", "shape": "rect", "border": 0, "shadow": False,
                "box": {"x": 0, "y": 0, "w": 1, "h": STACK_CAM}}
    return dict(fc)


def build_short_project(source: dict, media: dict, start: float, end: float, x_keyframes: list[dict],
                        scale: float, title: str, captions: bool, new_id, layout: str = "corner") -> dict:
    """The new project document (pure; ids from ``new_id``). ``layout``: what happens to
    the source's face cam (if it follows this recording): "corner", "stacked" or "none"."""
    from .schema import SCHEMA_VERSION
    link = new_id()
    facecam = short_facecam(source, media["id"], layout)
    y = 0.0
    if facecam is not None and layout == "stacked" and media.get("width") and media.get("height"):
        scale, y = stacked_geometry(media["width"], media["height"])
        x_keyframes = []
    clip = {"id": new_id(), "media_id": media["id"], "start": 0, "source_in": round(start, 3),
            "source_out": round(min(end, media["duration"]), 3), "link_id": link,
            "transform": {"x": x_keyframes[0]["v"] if x_keyframes else 0, "y": y, "scale": scale, "rotation": 0, "opacity": 1},
            "keyframes": {"x": x_keyframes} if len(x_keyframes) > 1 else {}}
    tracks = [{"id": new_id(), "kind": "video", "name": "V1", "clips": [clip]},
              {"id": new_id(), "kind": "video", "name": "V2", "clips": []},
              {"id": new_id(), "kind": "audio", "name": "A1", "role": "dialogue",
               "clips": [{**{k: v for k, v in clip.items() if k not in ("transform", "keyframes")}, "id": new_id()}]
               if media.get("has_audio") else []},
              {"id": new_id(), "kind": "audio", "name": "A2", "role": "music", "clips": []}]
    # stacked: captions on the seam between face cam and video, like most vertical clips
    caps = {**(source.get("captions") or {}), "enabled": bool(captions), "position": "middle", "max_words": 3}
    return {
        "schema_version": SCHEMA_VERSION,
        "media": source["media"],
        "timeline": {"tracks": tracks},
        "output": {**source["output"], "width": 1080, "height": 1920, "fit_mode": "fit"},
        "effects": source.get("effects") or [],
        "captions": caps,
        "audio": {**(source.get("audio") or {}), "normalize": True},
        "facecam": facecam,
        "_title": title,
    }
