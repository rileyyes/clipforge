"""Shared fixtures. All media is synthetic (FFmpeg lavfi) — no copyrighted content."""
from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.config import Settings


def make_media(path: Path, *, video: str | None = "testsrc2=s=640x360:r=30",
               audio: str | None = "sine=f=440", duration: float = 4.0,
               extra: list[str] | None = None) -> Path:
    args = ["ffmpeg", "-v", "error", "-y"]
    if video:
        args += ["-f", "lavfi", "-i", f"{video}:d={duration}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"{audio}:d={duration}"]
    if video:
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac"]
    args += (extra or []) + ["-shortest", str(path)]
    subprocess.run(args, check=True)
    return path


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("media")
    make_media(d / "av.mp4")
    make_media(d / "video_only.mp4", audio=None)
    make_media(d / "audio_only.wav", video=None)
    make_media(d / "vertical.mov", video="testsrc=s=360x640:r=25")
    # variable frame rate: drop frames irregularly then mux without CFR
    make_media(d / "vfr.mkv", video="testsrc=s=320x240:r=30", duration=3,
               extra=["-vf", "select='not(mod(n\\,3))+gt(n\\,40)'", "-fps_mode", "vfr"])
    (d / "corrupt.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"garbage" * 500)
    return d


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Client:
    def __init__(self, base: str):
        self.base = base

    def req(self, method: str, path: str, body=None, raw: bytes | None = None,
            headers: dict | None = None, csrf: bool = True):
        hd = {"X-ClipForge": "1"} if csrf else {}
        hd.update(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            hd["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=hd)
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                content = resp.read()
                return resp.status, _decode(content), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, _decode(e.read()), dict(e.headers)
        except (urllib.error.URLError, ConnectionError) as e:
            return 0, str(e), {}

    def upload(self, pid: str, path: Path, name: str | None = None):
        return self.req("POST", f"/api/projects/{pid}/media?filename={name or path.name}",
                        raw=path.read_bytes())

    def wait_job(self, jid: str, timeout: float = 180):
        end = time.time() + timeout
        while time.time() < end:
            _, j, _ = self.req("GET", f"/api/jobs/{jid}")
            if j["status"] not in ("queued", "running"):
                return j
            time.sleep(0.1)
        raise TimeoutError(jid)


def _decode(b: bytes):
    try:
        return json.loads(b)
    except (ValueError, UnicodeDecodeError):
        return b


@pytest.fixture()
def server(tmp_path):
    import uvicorn

    from app.main import create_app

    port = free_port()
    settings = Settings(workspace=tmp_path / "ws", port=port,
                        allowed_origins=(f"http://127.0.0.1:{port}",),
                        max_upload_bytes=50 * 1024 * 1024)
    app = create_app(settings)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    client = Client(f"http://127.0.0.1:{port}")
    client.settings = settings
    client.app = app
    yield client
    srv.should_exit = True
    t.join(timeout=10)
