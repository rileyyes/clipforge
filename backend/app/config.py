"""Application configuration.

All settings come from environment variables (prefix ``CLIPFORGE_``) so nothing
user-controlled from the HTTP layer can change where files are read or written.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:  # fail loudly on misconfiguration
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    workspace: Path
    host: str = "127.0.0.1"
    port: int = 8765
    max_upload_bytes: int = 20 * 1024**3  # 20 GiB
    max_workspace_bytes: int = 200 * 1024**3  # 200 GiB soft quota
    ffprobe_timeout_s: int = 60
    render_timeout_s: int = 6 * 3600
    job_workers: int = 1
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)

    @property
    def projects_dir(self) -> Path:
        return self.workspace / "projects"

    @property
    def jobs_dir(self) -> Path:
        return self.workspace / "jobs"

    @property
    def tmp_dir(self) -> Path:
        return self.workspace / "tmp"


def load_settings() -> Settings:
    workspace = Path(
        os.environ.get("CLIPFORGE_WORKSPACE", str(Path.home() / "ClipForgeWorkspace"))
    ).expanduser().resolve()
    port = _env_int("CLIPFORGE_PORT", 8765)
    host = os.environ.get("CLIPFORGE_HOST", "127.0.0.1")
    origins = tuple(
        o.strip()
        for o in os.environ.get("CLIPFORGE_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    ) or (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
    return Settings(
        workspace=workspace,
        host=host,
        port=port,
        max_upload_bytes=_env_int("CLIPFORGE_MAX_UPLOAD_MB", 20 * 1024) * 1024**2,
        max_workspace_bytes=_env_int("CLIPFORGE_MAX_WORKSPACE_GB", 200) * 1024**3,
        render_timeout_s=_env_int("CLIPFORGE_RENDER_TIMEOUT_S", 6 * 3600),
        job_workers=max(1, _env_int("CLIPFORGE_JOB_WORKERS", 1)),
        ffmpeg_bin=os.environ.get("CLIPFORGE_FFMPEG", shutil.which("ffmpeg") or "ffmpeg"),
        ffprobe_bin=os.environ.get("CLIPFORGE_FFPROBE", shutil.which("ffprobe") or "ffprobe"),
        allowed_origins=origins,
    )


def ensure_workspace(settings: Settings) -> None:
    for d in (settings.workspace, settings.projects_dir, settings.jobs_dir, settings.tmp_dir):
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
