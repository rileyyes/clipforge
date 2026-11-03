"""Your own sounds and images, shared by all projects ("My library").

    <workspace>/library/sounds/<id>.wav + <id>.json
    <workspace>/library/images/<id>.png + <id>.json

* Sounds come from a mic recording in the browser (WebM/Ogg/MP4) or any audio/video
  file. They're decoded with FFmpeg using the same input allow-lists as media import, and
  stored as 48 kHz stereo WAV: at most 30 s, silence trimmed from recordings, peaks
  levelled to -1 dBFS. Nothing else from the upload is kept.
* Images are decoded and re-encoded as PNG (max 2000 px), so no original file bytes or
  metadata survive.
* When you use an item in a project it is *copied* into that project (``fx/sounds``,
  ``fx``), so projects stay self-contained: deleting from the library never breaks an edit.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .config import Settings
from .ffmpeg import FFmpegError, MISSING_FFMPEG, untrusted_input_args
from .schema import now_iso
from .storage import atomic_write_json, new_id, safe_join, validate_id

MAX_SOUND_S = 30.0
MAX_SOUND_UPLOAD = 50 * 1024 * 1024
MAX_IMAGE_UPLOAD = 15 * 1024 * 1024
MAX_IMAGE_SIDE = 2000
MAX_ITEMS = 500
RATE = 48000


class LibraryError(ValueError):
    pass


class LibraryItem(BaseModel):
    id: str
    kind: Literal["sound", "image"]
    name: str = Field(max_length=60)
    source: Literal["recorded", "imported"] = "imported"
    created_at: str = Field(default_factory=now_iso)
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None


def clean_name(name: str, fallback: str) -> str:
    name = re.sub(r"[\x00-\x1f<>]", "", name or "").strip()
    name = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name)  # drop a file extension
    return (name or fallback)[:60]


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


class Library:
    def __init__(self, settings: Settings):
        self.s = settings
        self.root = settings.workspace / "library"
        for sub in ("sounds", "images"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def _dir(self, kind: str) -> Path:
        return self.root / ("sounds" if kind == "sound" else "images")

    def _ext(self, kind: str) -> str:
        return ".wav" if kind == "sound" else ".png"

    def file(self, kind: str, item_id: str) -> Path:
        p = safe_join(self._dir(kind), validate_id(item_id) + self._ext(kind))
        if not p.is_file():
            raise KeyError(item_id)
        return p

    # ---------------------------------------------------------------- listing
    def list(self) -> dict:
        out: dict[str, list] = {"sounds": [], "images": []}
        for kind, key in (("sound", "sounds"), ("image", "images")):
            for meta in self._dir(kind).glob("*.json"):
                try:
                    item = LibraryItem.model_validate_json(meta.read_text())
                except ValueError:
                    continue
                if (self._dir(kind) / (item.id + self._ext(kind))).is_file():
                    out[key].append(item.model_dump())
            out[key].sort(key=lambda d: d["created_at"], reverse=True)
        return out

    def get(self, kind: str, item_id: str) -> LibraryItem:
        self.file(kind, item_id)
        meta = safe_join(self._dir(kind), validate_id(item_id) + ".json")
        return LibraryItem.model_validate_json(meta.read_text())

    def _count(self) -> int:
        return sum(1 for k in ("sound", "image") for _ in self._dir(k).glob("*.json"))

    def _save_meta(self, item: LibraryItem) -> None:
        atomic_write_json(self._dir(item.kind) / f"{item.id}.json", item.model_dump(), keep_backup=False)

    # ---------------------------------------------------------------- sounds
    def add_sound(self, data: bytes, name: str, recorded: bool) -> LibraryItem:
        if self._count() >= MAX_ITEMS:
            raise LibraryError(f"Your library is full ({MAX_ITEMS} items) — delete some first.")
        if not data:
            raise LibraryError("empty upload")
        sid = new_id()
        tmp_dir = self.s.tmp_dir / f"lib-{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            src = tmp_dir / "upload.bin"
            src.write_bytes(data)
            out = tmp_dir / "sound.wav"
            # trim silence at both ends (recordings start/stop with button clicks and room tone)
            trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
                    "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,")
            self._ffmpeg(untrusted_input_args(src) + [
                "-vn", "-map", "0:a:0", "-af", f"{trim}aformat=channel_layouts=stereo",
                "-t", str(MAX_SOUND_S), "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s16le", str(out)])
            if not out.exists() or wav_duration(out) < 0.05:
                raise LibraryError("That file has no audible sound (it may be silent or too quiet).")
            peak = self._peak_db(out)
            final = self._dir("sound") / f"{sid}.wav"
            gain = -1.0 - peak if peak is not None else 0.0
            if abs(gain) > 0.3:
                self._ffmpeg(["-i", str(out), "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(final)])
            else:
                shutil.copyfile(out, final)
            item = LibraryItem(id=sid, kind="sound", name=clean_name(name, "My sound"),
                               source="recorded" if recorded else "imported", duration=round(wav_duration(final), 3))
            self._save_meta(item)
            return item
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _ffmpeg(self, args: list[str]) -> None:
        try:
            proc = subprocess.run([self.s.ffmpeg_bin, "-hide_banner", "-nostdin", "-v", "error", "-y", *args],
                                  capture_output=True, text=True, timeout=120)
        except OSError as exc:
            raise FFmpegError(MISSING_FFMPEG) from exc
        except subprocess.TimeoutExpired as exc:
            raise LibraryError("Processing the sound took too long.") from exc
        if proc.returncode != 0:
            raise LibraryError("That file isn't a readable audio or video file.")

    def _peak_db(self, wav: Path) -> Optional[float]:
        proc = subprocess.run([self.s.ffmpeg_bin, "-hide_banner", "-nostdin", "-i", str(wav),
                               "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, timeout=60)
        m = re.search(r"max_volume:\s*(-?[\d.]+) dB", proc.stderr)
        return float(m.group(1)) if m else None

    # ---------------------------------------------------------------- images
    def add_image(self, data: bytes, name: str) -> LibraryItem:
        if self._count() >= MAX_ITEMS:
            raise LibraryError(f"Your library is full ({MAX_ITEMS} items) — delete some first.")
        from .thumb_store import AssetError, decode_image  # needs OpenCV
        import cv2
        try:
            img = decode_image(data)
        except AssetError as exc:
            raise LibraryError(str(exc)) from exc
        h, w = img.shape[:2]
        k = min(1.0, MAX_IMAGE_SIDE / max(h, w))
        if k < 1:
            img = cv2.resize(img, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
        iid = new_id()
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise LibraryError("couldn't encode the image")
        (self._dir("image") / f"{iid}.png").write_bytes(buf.tobytes())
        item = LibraryItem(id=iid, kind="image", name=clean_name(name, "My image"),
                           width=int(img.shape[1]), height=int(img.shape[0]))
        self._save_meta(item)
        return item

    # ---------------------------------------------------------------- edit
    def rename(self, kind: str, item_id: str, name: str) -> LibraryItem:
        item = self.get(kind, item_id)
        item.name = clean_name(name, item.name)
        self._save_meta(item)
        return item

    def delete(self, kind: str, item_id: str) -> None:
        self.file(kind, item_id).unlink()
        (self._dir(kind) / f"{validate_id(item_id)}.json").unlink(missing_ok=True)

    def copy_into_project(self, kind: str, item_id: str, project_dir: Path) -> Path:
        """Copy an item into a project (idempotent: same id, same file)."""
        src = self.file(kind, item_id)
        dest_dir = project_dir / "fx" / ("sounds" if kind == "sound" else "")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if not dest.exists():
            shutil.copyfile(src, dest)
        return dest


def project_sound(project_dir: Path, sound_id: str) -> Path:
    return safe_join(project_dir, "fx", "sounds", validate_id(sound_id) + ".wav")

