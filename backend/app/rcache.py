"""Background render cache: identical segment renders are reused across exports.

A segment's key is a hash of exactly what produces it — the FFmpeg arguments (filters,
timings, encoder settings), the source files (path + size + modification time) and the
keys of any intermediate files it reads — plus the FFmpeg version. Change anything and
the key changes, so a cached file can never be stale. Per-segment renders and
final-quality video blocks are cached; the audio mix and the final copy always run. Oldest entries are evicted past the size limit.
"""
from __future__ import annotations

from .storage import replace_retry

import functools
import hashlib
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

CACHE_VERSION = "1"
SMALL_FILE = 8 * 1024 * 1024  # helper files up to this size are keyed by content


@functools.lru_cache(maxsize=4)
def ffmpeg_version(bin_: str) -> str:
    try:
        return subprocess.run([bin_, "-version"], capture_output=True, text=True, timeout=20).stdout.split("\n")[0]
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class RenderCache:
    def __init__(self, root: Path, limit_bytes: int, ffmpeg_bin: str):
        self.root = root
        self.limit = limit_bytes
        self.enabled = limit_bytes > 0
        self.version = ffmpeg_version(ffmpeg_bin) if self.enabled else ""
        self.keys: dict[str, str] = {}
        self.hits = self.misses = 0
        self.reused_seconds = 0.0
        if self.enabled:
            root.mkdir(parents=True, exist_ok=True)

    def register(self, name: str, parts: list[Optional[str]]) -> None:
        """Give a derived work file (e.g. a concat list) a key built from its members' keys."""
        if self.enabled and all(parts):
            self.keys[name] = hashlib.sha256("|".join(parts).encode()).hexdigest()[:40]  # type: ignore[arg-type]

    def key(self, args: list[str], work: Path, dest_name: str, extra: str = "") -> Optional[str]:
        """None when some input can't be identified (then the segment isn't cached).

        Small helper files in the work dir that have no key of their own (pop-up PNGs)
        are identified by their content. ``extra`` adds text the arguments only refer to
        indirectly (e.g. the subtitle file a filter reads)."""
        if not self.enabled:
            return None
        h = hashlib.sha256(f"{CACHE_VERSION}|{self.version}|{extra}".encode())
        wp = str(work) + os.sep
        for a in args:
            if a.startswith(wp):
                name = a[len(wp):]
                if name == dest_name:
                    a = "<OUT>"
                elif name in self.keys:
                    a = "<" + self.keys[name] + ">"
                else:
                    f = work / name
                    if not f.is_file() or f.stat().st_size > SMALL_FILE:
                        return None
                    a = "<#" + hashlib.sha256(f.read_bytes()).hexdigest() + ">"
            elif os.path.isabs(a) and os.path.isfile(a):
                st = os.stat(a)
                a = f"{a}|{st.st_size}|{st.st_mtime_ns}"
            h.update(a.encode() + b"\0")
        k = h.hexdigest()[:40]
        self.keys[dest_name] = k
        return k

    def _path(self, key: str, suffix: str) -> Path:
        return self.root / f"{key}{suffix}"

    def fetch(self, key: Optional[str], dest: Path) -> bool:
        if key is None:
            return False
        p = self._path(key, dest.suffix)
        if not p.exists():
            self.misses += 1
            return False
        try:
            _link_or_copy(p, dest)
            os.utime(p)  # LRU
        except OSError:
            self.misses += 1
            return False
        self.hits += 1
        return True

    def store(self, key: Optional[str], src: Path) -> None:
        if key is None or not src.exists():
            return
        p = self._path(key, src.suffix)
        tmp = p.with_name(p.name + f".{uuid.uuid4().hex[:8]}.tmp")
        try:
            _link_or_copy(src, tmp)
            replace_retry(tmp, p)
        except OSError:
            tmp.unlink(missing_ok=True)

    def evict(self) -> int:
        """Drop least-recently-used files until under 80% of the limit. Returns bytes freed."""
        if not self.enabled:
            return 0
        return evict(self.root, self.limit)


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def evict(root: Path, limit: int) -> int:
    if not root.is_dir():
        return 0
    files = []
    for p in root.iterdir():
        try:
            st = p.stat()
        except OSError:
            continue
        if p.name.endswith(".tmp") and time.time() - st.st_mtime > 3600:
            p.unlink(missing_ok=True)
            continue
        files.append((st.st_mtime, st.st_size, p))
    total = sum(f[1] for f in files)
    freed = 0
    if total <= limit:
        return 0
    for _m, size, p in sorted(files):
        if total - freed <= limit * 0.8:
            break
        p.unlink(missing_ok=True)
        freed += size
    return freed


def size_of(root: Path) -> int:
    return sum(p.stat().st_size for p in root.iterdir() if p.is_file()) if root.is_dir() else 0


def clear(root: Path) -> int:
    freed = size_of(root)
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
    return freed
