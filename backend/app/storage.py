"""Safe filesystem helpers.

Rules enforced here:
* Every path the server touches is derived from server-generated IDs, never from
  user-supplied paths. IDs are validated against a strict pattern.
* Every derived path is re-checked to be inside its expected root (defence in
  depth against traversal and symlink tricks).
* JSON documents are written atomically (temp file + fsync + rename) so a crash
  never leaves a half-written project.
"""
from __future__ import annotations

import json
import os
import time
import shutil
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"^[a-f0-9]{32}$")

ALLOWED_MEDIA_EXTENSIONS = {
    # video containers
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi",
    # audio
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus",
}

# Demuxers allowed when probing/decoding untrusted media. Playlist-style formats
# (hls, concat, image2 sequences, etc.) are deliberately excluded so a crafted
# file cannot make FFmpeg open other local files or network URLs.
SAFE_INPUT_FORMATS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,mp3,wav,aac,flac,ogg"


class PathSecurityError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


def validate_id(value: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise PathSecurityError("invalid identifier")
    return value


def safe_join(root: Path, *parts: str) -> Path:
    """Join parts under root and guarantee the result stays inside root."""
    root_resolved = root.resolve()
    for p in parts:
        if not p or p in (".", "..") or "/" in p or "\\" in p or "\x00" in p:
            raise PathSecurityError("invalid path component")
    candidate = root_resolved.joinpath(*parts).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PathSecurityError("path escapes workspace")
    return candidate


def media_extension(filename: str) -> str:
    """Return a normalised, allow-listed extension for an uploaded filename."""
    name = (filename or "").strip()
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_MEDIA_EXTENSIONS:
        raise PathSecurityError(
            f"unsupported file type {ext or '(none)'}; allowed: "
            + ", ".join(sorted(ALLOWED_MEDIA_EXTENSIONS))
        )
    return ext


def display_name(filename: str, limit: int = 120) -> str:
    """A safe-to-display version of a user filename (never used as a path)."""
    base = Path((filename or "").replace("\\", "/")).name
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()
    return (cleaned or "untitled")[:limit]


def replace_retry(src, dst, attempts: int = 40) -> None:
    """os.replace, retried briefly on Windows "file in use" errors.

    On Windows, replacing a file fails with PermissionError (sharing violation) while
    another thread or process has it open, e.g. a background job reading project.json.
    Those opens last milliseconds, so retrying for up to ~2 s turns a random failure
    into a short wait. On Linux/macOS the first attempt always succeeds."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05)


def atomic_write_json(path: Path, data: Any, keep_backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        if keep_backup and path.exists():
            # copy (not move) so the file never disappears for a concurrent reader
            try:
                shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
            except OSError:
                pass  # a backup is best-effort; the atomic replace below is what matters
        replace_retry(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def read_json(path: Path) -> Any:
    """Read JSON, falling back to the .bak copy if the main file is corrupt."""
    try:
        for i in range(40):  # Windows: the file may be mid-replace for a moment
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except PermissionError:
                if i == 39:
                    raise
                time.sleep(0.05)
    except (json.JSONDecodeError, UnicodeDecodeError):
        bak = path.with_suffix(path.suffix + ".bak")
        with open(bak, encoding="utf-8") as fh:
            return json.load(fh)


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total
