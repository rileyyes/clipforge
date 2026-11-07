"""Offline voiceover (Phase 16): type a line, a free local voice reads it.

Uses Piper (MIT licence, github.com/rhasspy/piper): a small program plus a voice model,
downloaded once into <workspace>/tools (about 20 MB + 75 MB) and then used fully offline.

Default voice: en_US-libritts_r-medium — trained from scratch on LibriTTS-R (CC BY 4.0), so it
can be used in any video, including ones you make money from, with this credit:
"Voice: Piper, LibriTTS-R (CC BY 4.0)". (Many older Piper voices come from a research-only
dataset, which is why this one is the default.) It has many speakers; RJClip offers a few.

The program's downloads are pinned by SHA-256 (they can't be swapped). Test/air-gapped setups
can point at other copies with RJCLIP_PIPER_URL / RJCLIP_VOICE_URL (file:// URLs work).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

PIPER_RELEASE = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/"
PIPER_BUILDS = {  # (system, machine) -> (file, sha256)
    ("Windows", "AMD64"): ("piper_windows_amd64.zip", "f3c58906402b24f3a96d92145f58acba6d86c9b5db896d207f78dc80811efcea"),
    ("Linux", "x86_64"): ("piper_linux_x86_64.tar.gz", "a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992"),
    ("Linux", "aarch64"): ("piper_linux_aarch64.tar.gz", "fea0fd2d87c54dbc7078d0f878289f404bd4d6eea6e7444a77835d1537ab88eb"),
    ("Darwin", "x86_64"): ("piper_macos_x64.tar.gz", "ced85c0a3df13945b1e623b878a48fdc2854d5c485b4b67f62857cf551deaf8b"),
    ("Darwin", "arm64"): ("piper_macos_aarch64.tar.gz", "6b1eb03b3735946cb35216e063e7eebcc33a6bbf5dd96ec0217959bf1cdcb0cc"),
}
VOICE = "en_US-libritts_r-medium"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/libritts_r/medium/"
CREDIT = "Voice: Piper, LibriTTS-R (CC BY 4.0)"
# a spread of speakers from the multi-speaker model (any 0..903 works; not hand-picked by ear)
SPEAKERS = {"Voice 1": 0, "Voice 2": 12, "Voice 3": 30, "Voice 4": 91, "Voice 5": 170, "Voice 6": 410}
MAX_CHARS = 2000


class VoiceError(Exception):
    pass


def tools_dir(workspace: Path) -> Path:
    d = workspace / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def piper_exe(workspace: Path) -> Path:
    return tools_dir(workspace) / "piper" / ("piper.exe" if os.name == "nt" else "piper")


def voice_files(workspace: Path) -> tuple[Path, Path]:
    d = tools_dir(workspace) / "voices"
    return d / f"{VOICE}.onnx", d / f"{VOICE}.onnx.json"


def status(workspace: Path) -> dict:
    exe = piper_exe(workspace)
    onnx, cfg = voice_files(workspace)
    return {"ready": exe.is_file() and onnx.is_file() and cfg.is_file(), "engine": exe.is_file(), "voice": onnx.is_file() and cfg.is_file(),
            "speakers": list(SPEAKERS), "credit": CREDIT, "download_mb": 95,
            "supported": (platform.system(), platform.machine()) in PIPER_BUILDS or bool(os.environ.get("RJCLIP_PIPER_URL"))}


def _download(url: str, dest: Path, sha256: Optional[str], progress: Callable[[float], None], cancel=None) -> None:
    if not (url.startswith("https://") or url.startswith("file://")):
        raise VoiceError("downloads must be https")
    tmp = dest.with_suffix(dest.suffix + ".partial")
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as fh:  # noqa: S310 (https/file only, checked above)
        total = int(r.headers.get("content-length") or 0)
        got = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise VoiceError("cancelled")
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if total:
                progress(min(1.0, got / total))
    if sha256 and h.hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        raise VoiceError("the download didn't match its fingerprint (SHA-256); try again later")
    os.replace(tmp, dest)


def _safe_extract(archive: Path, into: Path) -> None:
    """Unpack without letting any entry escape `into` (no absolute paths, no '..', no links)."""
    root = into.resolve()
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if not (root / n).resolve().is_relative_to(root):
                    raise VoiceError("unsafe archive")
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            for mem in t.getmembers():
                if mem.issym() or mem.islnk():
                    if not (root / Path(mem.name).parent / mem.linkname).resolve().is_relative_to(root):
                        raise VoiceError("unsafe archive")
                elif not (root / mem.name).resolve().is_relative_to(root):
                    raise VoiceError("unsafe archive")
            t.extractall(into, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(into)  # noqa: S202


def setup(workspace: Path, progress: Callable[[float], None], cancel=None) -> dict:
    """Download the Piper program and the default voice (once)."""
    d = tools_dir(workspace)
    if not piper_exe(workspace).is_file():
        override = os.environ.get("RJCLIP_PIPER_URL")
        if override:
            url, sha = override, None
        else:
            key = (platform.system(), platform.machine())
            if key not in PIPER_BUILDS:
                raise VoiceError(f"No voice engine is available for {key[0]} {key[1]} yet.")
            name, sha = PIPER_BUILDS[key]
            url = PIPER_RELEASE + name
        with tempfile.TemporaryDirectory(dir=d) as td:
            arc = Path(td) / Path(url).name
            _download(url, arc, sha, lambda f: progress(f * 0.2), cancel)
            out = Path(td) / "x"
            out.mkdir()
            _safe_extract(arc, out)
            src = out / "piper"
            if not src.is_dir():
                raise VoiceError("unexpected engine download")
            shutil.rmtree(d / "piper", ignore_errors=True)
            shutil.move(str(src), d / "piper")
        if os.name != "nt":
            piper_exe(workspace).chmod(0o755)
    onnx, cfg = voice_files(workspace)
    if not (onnx.is_file() and cfg.is_file()):
        onnx.parent.mkdir(parents=True, exist_ok=True)
        base = os.environ.get("RJCLIP_VOICE_URL", VOICE_URL)
        name = os.environ.get("RJCLIP_VOICE_NAME", VOICE)
        _download(base + f"{name}.onnx.json", cfg, None, lambda f: None, cancel)
        _download(base + f"{name}.onnx", onnx, None, lambda f: progress(0.2 + 0.8 * f), cancel)
        try:
            json.loads(cfg.read_text(encoding="utf-8"))
        except ValueError as exc:
            onnx.unlink(missing_ok=True)
            cfg.unlink(missing_ok=True)
            raise VoiceError("the voice download was damaged; try again") from exc
    progress(1.0)
    return status(workspace)


def speak(workspace: Path, text: str, dest_wav: Path, speaker: str = "Voice 1", speed: float = 1.0, timeout: int = 300) -> None:
    """Read `text` aloud into a WAV file. `speed` > 1 is faster."""
    text = " ".join(text.split())
    if not text:
        raise VoiceError("Type something to say")
    if len(text) > MAX_CHARS:
        raise VoiceError(f"Keep it under {MAX_CHARS} characters (split long voiceovers into parts)")
    st = status(workspace)
    if not st["ready"]:
        raise VoiceError("Download the voice first")
    onnx, _cfg = voice_files(workspace)
    exe = piper_exe(workspace)
    n_speakers = int(json.loads(_cfg.read_text(encoding="utf-8")).get("num_speakers", 1) or 1)
    args = [str(exe), "--model", str(onnx), "--output_file", str(dest_wav),
            "--length_scale", f"{1.0 / min(2.0, max(0.5, speed)):.3f}", "--sentence_silence", "0.25"]
    if n_speakers > 1:
        args += ["--speaker", str(min(n_speakers - 1, SPEAKERS.get(speaker, 0)))]
    env = {**os.environ}
    if os.name != "nt":  # the Linux/macOS builds keep their libraries next to the program
        env["LD_LIBRARY_PATH"] = str(exe.parent) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        env["DYLD_LIBRARY_PATH"] = str(exe.parent) + os.pathsep + env.get("DYLD_LIBRARY_PATH", "")
    try:
        r = subprocess.run(args, input=text.encode("utf-8"), capture_output=True, timeout=timeout, cwd=str(exe.parent), env=env)
    except subprocess.TimeoutExpired as exc:
        raise VoiceError("The voice took too long") from exc
    if r.returncode != 0 or not dest_wav.is_file() or dest_wav.stat().st_size < 1000:
        raise VoiceError("The voice engine failed: " + r.stderr.decode("utf-8", "replace").strip().splitlines()[-1:][0]
                         if r.stderr.strip() else "The voice engine failed")
