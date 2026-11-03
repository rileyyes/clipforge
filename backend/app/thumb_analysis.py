"""Timeline-aware video understanding for the Thumbnail Maker.

Works on the *final edit*, not the raw sources:

* ``timeline_coverage`` / ``fingerprint`` describe exactly which source ranges
  survive in the edit (trims, order, speed, hidden tracks).
* ``render_frame`` composites a single frame at a timeline time the same way the
  exporter does (all visible video layers, fit/fill, scale, position), using input
  seeking — so no long render is needed to look at the final video.
* ``summarize`` picks representative moments (analysis peaks, scene changes,
  clip middles), extracts frames once (cached), measures them (sharpness,
  brightness, colourfulness, faces) and reports what is known — and what is NOT
  known — with a confidence level.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from . import ffmpeg as ff
from .analysis import load_analysis
from .config import Settings
from .schema import Clip, Project, Track
from .thumb_store import ThumbStore

FRAME_W = 1280
STOPWORDS = set("""a an the and or but if then so to of in on at for with by from up down out over under
is are was were be been being am i you he she it we they me him her us them my your his its our their this
that these those there here what which who whom whose when where why how all any both each few more most
other some such no nor not only own same than too very can will just don should now um uh like yeah okay
ok oh gonna wanna got get going know think really right well do did does doing have has had having
let lets thing things stuff one two going see said say""".split())


def _clip_end(c: Clip) -> float:
    return c.start + (c.source_out - c.source_in) / c.speed


def visible_video_tracks(project: Project) -> list[Track]:
    return [t for t in project.timeline.tracks if t.kind == "video" and not t.hidden]


def timeline_coverage(project: Project) -> list[tuple[str, float, float]]:
    """Source ranges that appear in the final edit (video if any, else audio)."""
    tracks = visible_video_tracks(project) or [t for t in project.timeline.tracks
                                               if t.kind == "audio" and not t.muted]
    cov = [(c.media_id, round(c.source_in, 2), round(c.source_out, 2)) for t in tracks for c in t.clips]
    return sorted(cov)


def fingerprint(project: Project) -> str:
    parts = []
    for t in project.timeline.tracks:
        if (t.kind == "video" and t.hidden) or (t.kind == "audio" and t.muted):
            continue
        for c in sorted(t.clips, key=lambda c: c.start):
            parts.append([t.kind, c.media_id, round(c.start, 2), round(c.source_in, 2), round(c.source_out, 2),
                          c.speed, round(c.transform.scale, 3), round(c.transform.x), round(c.transform.y)])
    parts.append([project.output.width, project.output.height, project.output.fit_mode])
    return hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:20]


def coverage_similarity(a: list, b: list) -> float:
    """Overlap of two coverages (0..1, Jaccard over seconds per media)."""
    def to_map(cov):
        m: dict[str, list[tuple[float, float]]] = {}
        for mid, s, e in cov:
            m.setdefault(mid, []).append((float(s), float(e)))
        return m

    def length(iv):
        iv = sorted(iv)
        tot, cur = 0.0, None
        for s, e in iv:
            if cur is None or s > cur[1]:
                if cur:
                    tot += cur[1] - cur[0]
                cur = [s, e]
            else:
                cur[1] = max(cur[1], e)
        return tot + (cur[1] - cur[0] if cur else 0)

    def inter(x, y):
        tot = 0.0
        for s1, e1 in x:
            for s2, e2 in y:
                tot += max(0.0, min(e1, e2) - max(s1, s2))
        return tot

    ma, mb = to_map(a), to_map(b)
    if not ma and not mb:
        return 1.0
    i = sum(inter(ma.get(k, []), mb.get(k, [])) for k in set(ma) | set(mb))
    u = sum(length(v) for v in ma.values()) + sum(length(v) for v in mb.values()) - i
    return i / u if u > 0 else 1.0


def staleness(project: Project, design_fp: str, design_cov: list) -> dict:
    fp = fingerprint(project)
    if not design_fp or design_fp == fp:
        return {"state": "current", "similarity": 1.0, "message": ""}
    sim = coverage_similarity(timeline_coverage(project), design_cov)
    if sim < 0.7:
        return {"state": "changed", "similarity": round(sim, 2),
                "message": "The edited video has changed significantly since this thumbnail was made "
                           f"(only {sim:.0%} of the footage is the same). It may no longer represent the video."}
    return {"state": "minor", "similarity": round(sim, 2),
            "message": "The edit changed slightly since this thumbnail was made."}


# ---------------------------------------------------------------- frames
def layers_at(project: Project, t: float) -> list[Clip]:
    out = []
    for track in visible_video_tracks(project):
        c = next((c for c in track.clips if c.start - 1e-6 <= t < _clip_end(c) - 1e-6), None)
        if c:
            out.append(c)
    return out


def frame_key(project: Project, t: float) -> str:
    parts = [[c.media_id, round(c.source_in + (t - c.start) * c.speed, 2), c.transform.scale,
              c.transform.x, c.transform.y] for c in layers_at(project, t)]
    parts.append([project.output.width, project.output.height, project.output.fit_mode])
    return hashlib.sha1(json.dumps(parts).encode()).hexdigest()


def render_frame(settings: Settings, project: Project, project_dir: Path, t: float) -> np.ndarray:
    """Composite the final edit's picture at timeline time ``t`` (BGR array)."""
    layers = layers_at(project, t)
    if not layers:
        raise ValueError(f"no visible video at {t:.2f}s in the edit")
    W, H = project.output.width, project.output.height
    s = min(1.0, FRAME_W / W)
    W2, H2 = int(W * s) // 2 * 2, int(H * s) // 2 * 2
    media = project.media_by_id()
    args = ["-f", "lavfi", "-i", f"color=c=black:s={W2}x{H2}:d=1"]
    graph, last = [], "0:v"
    for i, c in enumerate(layers, start=1):
        src = project_dir / "media" / "original" / media[c.media_id].stored_name
        st = c.source_in + (t - c.start) * c.speed
        args += ff.untrusted_input_args(src, seek=max(0.0, st))
        fit = (f"scale={W2}:{H2}:force_original_aspect_ratio=increase,crop={W2}:{H2}"
               if project.output.fit_mode == "fill" and i == 1 else
               f"scale={W2}:{H2}:force_original_aspect_ratio=decrease")
        if abs(c.transform.scale - 1) > 1e-6:
            fit += f",scale=trunc(iw*{c.transform.scale:.4f}/2)*2:trunc(ih*{c.transform.scale:.4f}/2)*2"
        graph.append(f"[{i}:v]{fit},setsar=1[l{i}]")
        graph.append(f"[{last}][l{i}]overlay=x=(W-w)/2+({c.transform.x * s:.1f}):"
                     f"y=(H-h)/2+({c.transform.y * s:.1f})[o{i}]")
        last = f"o{i}"
    cmd = [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-v", "error", *args,
           "-filter_complex", ";".join(graph), "-map", f"[{last}]", "-frames:v", "1",
           "-f", "image2pipe", "-vcodec", "png", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    if proc.returncode != 0 or not proc.stdout:
        raise ff.FFmpegError("frame extraction failed", proc.stderr.decode(errors="replace"))
    img = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ff.FFmpegError("frame extraction produced no image")
    return img


def get_frame(settings: Settings, project: Project, project_dir: Path, store: ThumbStore,
              t: float) -> dict:
    key = frame_key(project, t)
    hit = store.cached_frame(key)
    if hit:
        return hit
    img = render_frame(settings, project, project_dir, t)
    meta = store.add_asset(img, "frame", {"timeline_time": round(t, 3), "frame_key": key,
                                          "label": "Frame from your edit"})
    meta.update(frame_stats(img))
    from .storage import atomic_write_json
    atomic_write_json(store.root / "assets" / f"{meta['id']}.json", meta, keep_backup=False)
    store.remember_frame(key, meta["id"])
    return meta


_face = None


def frame_stats(img: np.ndarray) -> dict:
    global _face
    small = cv2.resize(img, (640, int(640 * img.shape[0] / img.shape[1])), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    b, g, r = [small[:, :, i].astype(np.float32) for i in range(3)]
    rg, yb = np.abs(r - g), np.abs(0.5 * (r + g) - b)
    colorful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    if _face is None:
        _face = False
        try:
            path = Path(getattr(cv2, "data", None).haarcascades) / "haarcascade_frontalface_default.xml"
            if path.exists():
                clf = cv2.CascadeClassifier(str(path))
                _face = clf if not clf.empty() else False
        except Exception:  # noqa: BLE001 - optional capability
            _face = False
    faces = (_face.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(40, 40))
             if _face is not False else None)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hues = hsv[:, :, 0][hsv[:, :, 1] > 80]
    dom = []
    if hues.size:
        hist = np.bincount((hues // 15).astype(int), minlength=12)
        for k in hist.argsort()[::-1][:2]:
            if hist[k] > hues.size * 0.12:
                h = int(k * 15 + 7)
                c = cv2.cvtColor(np.uint8([[[h, 200, 220]]]), cv2.COLOR_HSV2BGR)[0, 0]
                dom.append("#%02x%02x%02x" % (c[2], c[1], c[0]))
    return {"sharpness": round(sharp, 1), "brightness": round(float(gray.mean()), 1),
            "colorfulness": round(colorful, 1), "faces": None if faces is None else int(len(faces)),
            "face_boxes": [] if faces is None else [[int(v) for v in f] for f in faces[:4]],
            "dominant_colors": dom}


# ---------------------------------------------------------------- summary
def _map_source_peaks(project_dir: Path, c: Clip) -> list[tuple[float, str, float]]:
    """(timeline time, reason, strength 0..1) from cached auto-edit analysis."""
    a = load_analysis(project_dir, c.media_id)
    if not a:
        return []
    hop = a["hop"]
    out = []
    i0, i1 = int(c.source_in / hop), max(int(c.source_in / hop) + 1, int(c.source_out / hop))
    for key, reason in (("rms_db", "loudest moment"), ("motion", "most on-screen movement")):
        arr = np.asarray(a.get(key) or [], dtype=np.float32)[i0:i1]
        if arr.size > 3:
            k = int(np.argmax(arr))
            full = np.asarray(a[key], dtype=np.float32)
            strength = float((full < arr[k]).mean()) if full.size else 0.5
            out.append((c.start + (k * hop) / c.speed, reason, strength))
    for cut in a.get("cuts") or []:
        if c.source_in <= cut < c.source_out - 0.6:
            out.append((c.start + (cut - c.source_in) / c.speed + 0.4, "new scene", 0.55))
    return out


def edit_words(project: Project, project_dir: Path) -> list[str]:
    """Transcript words in final-edit order (only words that survive the edit)."""
    tracks = [t for t in project.timeline.tracks if t.kind == "audio" and not t.muted] or \
        visible_video_tracks(project)
    clips = sorted((c for t in tracks[:1] for c in t.clips), key=lambda c: c.start)
    words: list[str] = []
    cache: dict[str, Optional[dict]] = {}
    for c in clips:
        if c.media_id not in cache:
            cache[c.media_id] = load_analysis(project_dir, c.media_id)
        a = cache[c.media_id]
        for w in (a or {}).get("words") or []:
            if c.source_in <= w["start"] < c.source_out:
                words.append(w["text"])
    return words


def keywords(words: list[str], n: int = 8) -> list[str]:
    toks = [re.sub(r"[^a-z0-9']", "", w.lower()) for w in words]
    toks = [t for t in toks if len(t) > 2 and t not in STOPWORDS and not t.isdigit()]
    return [w for w, _ in Counter(toks).most_common(n)]


def summarize(settings: Settings, project: Project, project_dir: Path, store: ThumbStore,
              on_progress: Callable[[float], None] = lambda f: None, n_frames: int = 8,
              cancel=None) -> dict:
    D = project.timeline.duration
    if D <= 0:
        raise ValueError("The timeline is empty — edit the video first (or use the AI Auto Editor).")
    vtracks = visible_video_tracks(project)
    has_picture = any(t.clips for t in vtracks)
    media = project.media_by_id()

    # candidate moments in the FINAL edit
    cands: list[tuple[float, str, float]] = []
    for t in vtracks:
        for c in t.clips:
            d = _clip_end(c) - c.start
            for f in (0.3, 0.5, 0.75):
                cands.append((c.start + d * f, "representative shot", 0.35))
            cands += _map_source_peaks(project_dir, c)
    cands = [(min(max(t, 0.0), D - 0.05), r, s) for t, r, s in cands]
    cands.sort(key=lambda x: (-x[2], x[0]))
    chosen: list[tuple[float, str, float]] = []
    spacing = max(1.0, D / (n_frames * 1.6))
    for cand in cands:
        if all(abs(cand[0] - c[0]) >= spacing for c in chosen):
            chosen.append(cand)
        if len(chosen) >= n_frames:
            break
    chosen.sort(key=lambda x: x[0])

    moments = []
    for i, (t, reason, strength) in enumerate(chosen):
        if cancel is not None and cancel.is_set():
            raise ff.Cancelled("cancelled")
        if has_picture and layers_at(project, t):
            meta = get_frame(settings, project, project_dir, store, t)
            stats = {k: meta.get(k) for k in ("sharpness", "brightness", "colorfulness", "faces",
                                              "dominant_colors", "face_boxes")}
            if stats["sharpness"] is None:
                stats = frame_stats(cv2.imread(str(store.asset_path(meta["id"]))))
            q = (min(1.0, (stats["sharpness"] or 0) / 300) * 0.4 + min(1.0, (stats["colorfulness"] or 0) / 60) * 0.3
                 + (0.3 if 40 < (stats["brightness"] or 0) < 210 else 0.0))
            moments.append({"time": round(t, 2), "reason": reason, "strength": round(strength, 2),
                            "frame_asset": meta["id"], "quality": round(q, 2), **stats})
        else:
            moments.append({"time": round(t, 2), "reason": reason, "strength": round(strength, 2),
                            "frame_asset": None, "quality": 0})
        on_progress((i + 1) / max(1, len(chosen)))
    # best frames first for the UI
    ranked = sorted(moments, key=lambda m: -(m["strength"] * 0.6 + m["quality"] * 0.4))

    # signals from the auto-edit analysis, restricted to what survives in the edit
    loud, motion, cuts_in_edit = [], [], 0
    for t in (vtracks or [x for x in project.timeline.tracks if x.kind == "audio"]):
        for c in t.clips:
            a = load_analysis(project_dir, c.media_id)
            if not a:
                continue
            hop = a["hop"]
            sl = slice(int(c.source_in / hop), int(c.source_out / hop))
            loud += list(np.asarray(a.get("rms_db") or [], dtype=np.float32)[sl])
            motion += list(np.asarray(a.get("motion") or [], dtype=np.float32)[sl])
            cuts_in_edit += sum(1 for x in (a.get("cuts") or []) if c.source_in <= x < c.source_out)
    clip_count = sum(len(t.clips) for t in vtracks) or sum(len(t.clips) for t in project.timeline.tracks)
    pace = (clip_count + cuts_in_edit) / max(D / 60, 1e-6)
    energy = None
    if loud:
        la = np.asarray(loud)
        spikes = float((la > np.percentile(la, 90) + 3).mean())
        energy = "high" if la.std() > 9 or spikes > 0.04 else "medium" if la.std() > 5 else "low"
    mot = None
    if motion:
        m = float(np.mean(motion))
        mot = "high" if m > 12 else "medium" if m > 4 else "low"
    face_known = [m for m in moments if m.get("faces") is not None]
    face_ratio = (sum(1 for m in face_known if m["faces"] > 0) / len(face_known)) if face_known else None

    words = edit_words(project, project_dir)
    kw = keywords(words)
    fmt_guess, fmt_basis = None, ""
    if has_picture and moments:
        if face_ratio is None:
            pass
        elif face_ratio >= 0.5 and mot in (None, "low", "medium"):
            fmt_guess, fmt_basis = "on-camera / talking-head", f"faces in {face_ratio:.0%} of sampled frames"
        elif face_ratio < 0.2 and mot == "high":
            fmt_guess, fmt_basis = "action-heavy footage (e.g. gameplay or sports)", "high motion, few faces"
        elif face_ratio < 0.2 and mot == "low":
            fmt_guess, fmt_basis = "screen recording, slides or b-roll", "low motion, no faces"
    unknowns = []
    if face_ratio is None and has_picture:
        unknowns.append("whether people appear on screen (face detector not available in this OpenCV build)")
    if not words:
        unknowns.append("topic and spoken content (no transcript available)")
    unknowns.append("genre and story (signal analysis can't tell what happens)")
    confidence = "medium" if words else "low"
    sources = Counter()
    for t in vtracks or project.timeline.tracks:
        for c in t.clips:
            sources[media[c.media_id].original_name] += (c.source_out - c.source_in) / c.speed
    return {
        "fingerprint": fingerprint(project),
        "coverage": timeline_coverage(project),
        "edit_revision": project.edit_revision,
        "final_duration": round(D, 2),
        "clip_count": clip_count,
        "sources": [{"name": k, "seconds": round(v, 1)} for k, v in sources.most_common()],
        "signals": {"energy": energy, "motion": mot, "cuts_per_minute": round(pace, 1),
                    "faces_ratio": None if face_ratio is None else round(face_ratio, 2),
                    "colorfulness": round(float(np.mean([m.get("colorfulness") or 0 for m in moments])), 1) if moments else None,
                    "analysis_available": bool(loud or motion)},
        "format_guess": fmt_guess, "format_basis": fmt_basis,
        "transcript": {"available": bool(words), "words": len(words), "excerpt": " ".join(words[:70]),
                       "keywords": kw},
        "moments": ranked,
        "confidence": confidence,
        "unknowns": unknowns,
        "vision": None,
    }


__all__ = ["summarize", "render_frame", "get_frame", "fingerprint", "timeline_coverage", "staleness",
           "coverage_similarity", "layers_at", "keywords", "edit_words", "frame_stats"]
_ = math
