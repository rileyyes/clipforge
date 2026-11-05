"""Phase 9: line up a face cam with the game by sound; crop to the face."""
from __future__ import annotations

import subprocess

import numpy as np
import pytest

from app import sync as S

RATE = S.RATE


def _speechy(seconds, seed):
    """Bursts of filtered noise with pauses, like talking."""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(seconds * RATE))
    t = 0.3
    while t < seconds - 1:
        d = rng.uniform(0.08, 0.6)
        n = int(d * RATE)
        burst = rng.normal(0, 1, n) * np.hanning(n) * rng.uniform(0.2, 1.0)
        i = int(t * RATE)
        x[i:i + n] += burst
        t += d + rng.uniform(0.05, 0.9)
    return x


def _as_cam(main, shift, seconds, seed):
    """What the webcam mic hears: same voice `shift` seconds later in its own file, quieter,
    duller (low-pass), with its own room noise; possibly a different length."""
    rng = np.random.default_rng(seed)
    cam = np.zeros(int(seconds * RATE))
    s = int(round(shift * RATE))
    src0, dst0 = max(0, -s), max(0, s)
    n = min(len(main) - src0, len(cam) - dst0)
    cam[dst0:dst0 + n] = main[src0:src0 + n] * 0.4
    cam = np.convolve(cam, np.ones(6) / 6, mode="same")
    return cam + rng.normal(0, 0.01, len(cam))


@pytest.mark.parametrize("shift", [2.37, -1.234, 0.0, 11.5])
def test_finds_the_offset_to_a_millisecond_or_two(shift):
    main = _speechy(60, 1)
    cam = _as_cam(main, shift, 50, 2)
    r = S.find_offset(main, cam)
    # cam(t + offset) == main(t)  ->  offset == shift
    assert abs(r.offset - shift) < 0.003, r
    assert r.confidence >= 0.5, r


def test_unrelated_audio_has_low_confidence():
    r = S.find_offset(_speechy(60, 1), _speechy(60, 99))
    assert r.confidence < 0.5, r


def test_too_short_or_silent():
    assert S.find_offset(np.zeros(100), np.zeros(100)).confidence == 0
    assert S.find_offset(np.zeros(RATE * 5), np.zeros(RATE * 5)).confidence < 0.5


def test_sync_real_files(tmp_path):
    main = _speechy(40, 3)
    cam = _as_cam(main, 1.5, 35, 4)

    def write(x, name, video):
        raw = tmp_path / f"{name}.f32"
        (x / (np.abs(x).max() + 1e-9) * 0.8).astype(np.float32).tofile(raw)
        out = tmp_path / f"{name}.mp4"
        vid = ["-f", "lavfi", "-i", f"color=gray:s=160x120:r=30:d={len(x) / RATE}"] if video else []
        subprocess.run(["ffmpeg", "-v", "error", "-y", *vid, "-f", "f32le", "-ar", str(RATE), "-ac", "1",
                        "-i", str(raw), "-c:a", "aac", "-b:a", "128k", *(["-c:v", "libx264"] if video else []),
                        "-shortest", str(out)], check=True)
        return out
    r = S.sync_files("ffmpeg", write(main, "game", True), write(cam, "cam", True))
    assert abs(r.offset - 1.5) < 0.03 and r.confidence >= 0.5, r   # AAC priming may add ~20 ms


def test_face_crop_finds_the_face(tmp_path):
    from pathlib import Path
    person = Path(__file__).parent / "data" / "person.jpg"
    v = tmp_path / "cam.mp4"
    # a 16:9 webcam frame with the person on the right
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-t", "3", "-i", str(person),
                    "-vf", "scale=360:360,pad=640:360:260:0:color=gray,format=yuv420p", "-c:v", "libx264", str(v)],
                   check=True)
    crop, info = S.face_crop("ffmpeg", v, 3.0, 640, 360, aspect=1.0)
    assert info["faces_seen"] >= 4
    cw, ch = 1 - crop.left - crop.right, 1 - crop.top - crop.bottom
    assert abs(cw * 640 - ch * 360) < 4          # square in pixels
    assert cw < 0.8                              # actually cropped in
    face_x = (260 + 360 * 0.47) / 640           # the astronaut's face is ~47% across her picture
    assert crop.left < face_x < 1 - crop.right


def test_no_face_no_crop(tmp_path):
    v = tmp_path / "wall.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=320x240:r=30:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(v)], check=True)
    assert S.face_crop("ffmpeg", v, 2.0, 320, 240) is None
