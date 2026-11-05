"""Face cam background removal: a per-frame "person mask" for a webcam recording.

Model: PP-HumanSeg (2023), from the OpenCV model zoo (Apache-2.0, ~6 MB, bundled in
``app/models``; see models/NOTICE.md). It runs with OpenCV's own DNN module, on the
CPU, about 10–15 ms per frame — no extra download or GPU needed.

The mask is computed once per face cam recording at 30 fps and 192×192 (the model's
size), lightly smoothed over time to stop flicker, and stored as a small greyscale
video next to the media (``media/matte/<id>.mp4``). Exports reuse it; it's scaled to
the cam picture and turned into transparency during rendering.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import ffmpeg as ff
from .config import Settings
from .schema import MediaAsset

MODEL = Path(__file__).parent / "models" / "human_segmentation_pphumanseg_2023mar.onnx"
SIZE = 192
FPS = 30
BATCH = 8
SMOOTH = 0.35  # weight of the previous frame's mask (temporal smoothing)
_lock = threading.Lock()


def available() -> bool:
    try:
        import cv2
        return MODEL.is_file() and hasattr(cv2, "dnn")
    except ImportError:
        return False


class Segmenter:
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.net = cv2.dnn.readNet(str(MODEL))

    def __call__(self, frames: np.ndarray) -> np.ndarray:
        """frames: N×192×192×3 RGB uint8 → N×192×192 person probability (0..1)."""
        x = (frames.astype(np.float32) / 255.0 - 0.5) / 0.5
        self.net.setInput(np.ascontiguousarray(x.transpose(0, 3, 1, 2)))
        return self.net.forward()[:, 1]


def person_mask(img_bgr: np.ndarray) -> np.ndarray:
    """Mask for one picture (any size), 0..1 float at the picture's size."""
    import cv2
    h, w = img_bgr.shape[:2]
    small = cv2.cvtColor(cv2.resize(img_bgr, (SIZE, SIZE), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    return cv2.resize(Segmenter()(small[None])[0], (w, h), interpolation=cv2.INTER_LINEAR)


def matte_path(project_dir: Path, asset: MediaAsset) -> Path:
    return project_dir / "media" / "matte" / f"{asset.id}.mp4"


def ensure(settings: Settings, project_dir: Path, asset: MediaAsset,
           cancel_event: Optional[threading.Event] = None,
           on_progress: Optional[Callable[[float], None]] = None) -> Path:
    """Return the matte video, making it first if needed (one at a time)."""
    dest = matte_path(project_dir, asset)
    with _lock:
        if dest.is_file():
            return dest
        if not available():
            raise RuntimeError("Background removal isn't available: the bundled model or OpenCV's DNN module is missing.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.stem + ".partial.mp4")
        src = project_dir / "media" / "original" / asset.stored_name
        seg = Segmenter()
        frame_bytes = SIZE * SIZE * 3
        total = max(1, int(asset.duration * FPS))
        dec = subprocess.Popen(
            [settings.ffmpeg_bin, "-v", "error", *ff.untrusted_input_args(src), "-an", "-sn",
             "-vf", f"fps={FPS},scale={SIZE}:{SIZE}:flags=area,format=rgb24", "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        enc = subprocess.Popen(
            [settings.ffmpeg_bin, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
             "-s", f"{SIZE}x{SIZE}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "10", "-pix_fmt", "yuv420p", str(tmp)],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        done, prev = 0, None
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ff.Cancelled("cancelled")
                raw = dec.stdout.read(frame_bytes * BATCH)
                n = len(raw) // frame_bytes
                if n == 0:
                    break
                frames = np.frombuffer(raw[:n * frame_bytes], np.uint8).reshape(n, SIZE, SIZE, 3)
                masks = seg(frames)
                out = np.empty((n, SIZE, SIZE), np.uint8)
                for i in range(n):
                    m = masks[i] if prev is None else (1 - SMOOTH) * masks[i] + SMOOTH * prev
                    prev = m
                    out[i] = np.clip(m * 255 + 0.5, 0, 255).astype(np.uint8)
                enc.stdin.write(out.tobytes())
                done += n
                if on_progress:
                    on_progress(min(1.0, done / total))
            enc.stdin.close()
            if enc.wait(timeout=600) != 0 or dec.wait(timeout=60) != 0 or done == 0:
                raise RuntimeError("Couldn't make the face cam cut-out (the video couldn't be read).")
            ff_ok = tmp.is_file() and tmp.stat().st_size > 0
            if not ff_ok:
                raise RuntimeError("Couldn't make the face cam cut-out.")
            tmp.replace(dest)
            return dest
        except BaseException:
            for p in (dec, enc):
                if p.poll() is None:
                    p.kill()
            tmp.unlink(missing_ok=True)
            raise
        finally:
            for p in (dec, enc):
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
