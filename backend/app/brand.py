"""Brand kit (Phase 15): your logo watermark, intro/outro clips, title colours and caption
style, saved once for every project in <workspace>/brand/.

Applying it to a project copies the logo into that project (so the project keeps working if
the kit changes later) and returns the intro/outro so the Editor can put them on the
timeline as ordinary clips (undoable).
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path
from typing import Literal, Optional

from PIL import Image
from pydantic import Field

from .schema import COLOR_HEX, Strict
from .storage import atomic_write_json

LOGO_MAX_BYTES = 10 * 1024 * 1024
LOGO_MAX_PX = 1024


class BrandCaptions(Strict):
    style: Literal["clean", "bold_pop", "highlight"] = "bold_pop"
    color: str = Field(default="#ffffff", pattern=COLOR_HEX)
    highlight: str = Field(default="#ffde00", pattern=COLOR_HEX)
    position: Literal["bottom", "middle", "top"] = "bottom"
    size: float = Field(default=0.06, ge=0.03, le=0.12)
    uppercase: bool = True


class Brand(Strict):
    name: str = Field(default="", max_length=60)
    logo: Optional[str] = Field(default=None, pattern=r"^logo-[0-9a-f]{16}\.png$")
    logo_corner: Literal["tl", "tr", "bl", "br"] = "br"
    logo_size: float = Field(default=0.12, ge=0.03, le=0.4)       # width, fraction of the video's width
    logo_opacity: float = Field(default=0.8, ge=0.1, le=1.0)
    intro: Optional[str] = Field(default=None, pattern=r"^intro-[0-9a-f]{16}\.[a-z0-9]{2,4}$")
    outro: Optional[str] = Field(default=None, pattern=r"^outro-[0-9a-f]{16}\.[a-z0-9]{2,4}$")
    title_color: str = Field(default="#ffffff", pattern=COLOR_HEX)
    title_accent: str = Field(default="#ff5a3c", pattern=COLOR_HEX)
    captions: BrandCaptions = Field(default_factory=BrandCaptions)


def brand_dir(workspace: Path) -> Path:
    d = workspace / "brand"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(workspace: Path) -> Brand:
    p = brand_dir(workspace) / "brand.json"
    if p.exists():
        try:
            return Brand.model_validate(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - a broken file falls back to the defaults
            pass
    return Brand()


def save(workspace: Path, b: Brand) -> None:
    atomic_write_json(brand_dir(workspace) / "brand.json", b.model_dump(mode="json"))


def store_logo(workspace: Path, data: bytes) -> str:
    """Validate an uploaded image and store it as a (re-encoded, size-capped) PNG."""
    if len(data) > LOGO_MAX_BYTES:
        raise ValueError("The logo must be under 10 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("That isn't an image RJClip can read (use PNG or JPG)") from exc
    if img.width * img.height > 40_000_000:
        raise ValueError("That image is too big")
    img = img.convert("RGBA")
    img.thumbnail((LOGO_MAX_PX, LOGO_MAX_PX))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    png = buf.getvalue()
    name = f"logo-{hashlib.sha256(png).hexdigest()[:16]}.png"
    (brand_dir(workspace) / name).write_bytes(png)
    return name


def store_clip(workspace: Path, kind: Literal["intro", "outro"], src: Path, ext: str) -> str:
    h = hashlib.sha256()
    with open(src, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    name = f"{kind}-{h.hexdigest()[:16]}{ext.lower()}"
    shutil.move(str(src), brand_dir(workspace) / name)
    return name


def tidy(workspace: Path, b: Brand) -> None:
    """Remove brand files the kit no longer uses."""
    keep = {b.logo, b.intro, b.outro, "brand.json"}
    for f in brand_dir(workspace).iterdir():
        if f.is_file() and f.name not in keep and not f.name.endswith(".partial"):
            f.unlink(missing_ok=True)
