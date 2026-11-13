"""Fonts for titles, captions and counters (Phase 18).

Two kinds:
- built in: free fonts shipped in app/fonts/ (SIL Open Font License or Apache 2.0; each
  font's licence is in app/fonts/licenses/<id>.txt). Ids are short names like "anton".
- yours: .ttf/.otf files you add in Settings, kept in <workspace>/fonts/. Ids are "u-" + hex.

A title stores only the font id. When a font is missing (you deleted one of yours), the title
falls back to the default font instead of failing the export.
"""
from __future__ import annotations

import io
import json
import re
import secrets
from pathlib import Path
from typing import Optional

from .storage import atomic_write_json

BUILTIN_DIR = Path(__file__).resolve().parent / "fonts"
MAX_BYTES = 20 * 1024 * 1024
FONT_ID = r"^(?:[a-z0-9][a-z0-9-]{0,23}|u-[0-9a-f]{12})$"

# id, family name inside the file, group shown in the font picker
BUILTIN: list[tuple[str, str, str]] = [
    ("anton", "Anton", "Bold"),
    ("bebas", "Bebas Neue", "Bold"),
    ("archivo-black", "Archivo Black", "Bold"),
    ("russo", "Russo One", "Bold"),
    ("black-ops", "Black Ops One", "Bold"),
    ("poppins", "Poppins", "Clean"),
    ("bangers", "Bangers", "Fun"),
    ("luckiest-guy", "Luckiest Guy", "Fun"),
    ("titan", "Titan One", "Fun"),
    ("lilita", "Lilita One", "Fun"),
    ("creepster", "Creepster", "Horror"),
    ("nosifer", "Nosifer", "Horror"),
    ("butcherman", "Butcherman", "Horror"),
    ("eater", "Eater", "Horror"),
    ("press-start", "Press Start 2P", "Retro & gaming"),
    ("vt323", "VT323", "Retro & gaming"),
    ("monoton", "Monoton", "Retro & gaming"),
    ("bungee", "Bungee", "Retro & gaming"),
    ("rubik-glitch", "Rubik Glitch", "Retro & gaming"),
    ("permanent-marker", "Permanent Marker", "Handwritten"),
    ("rock-salt", "Rock Salt", "Handwritten"),
    ("kalam", "Kalam", "Handwritten"),
    ("emoji", "Noto Emoji", "Stickers"),
]
_BY_ID = {i: (fam, cat) for i, fam, cat in BUILTIN}
# names that can safely go inside an ASS override tag ({\fnName}) and a CSS font-family
_SAFE_FAMILY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'&+_-]{0,62}$")


def user_dir(workspace: Path) -> Path:
    d = workspace / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_meta(workspace: Path) -> list[dict]:
    """Your fonts' details (reading only: the folder is made when you add the first one)."""
    out = []
    d = workspace / "fonts"
    if not d.is_dir():
        return out
    for m in sorted(d.glob("u-*.json")):
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if re.match(FONT_ID, d.get("id", "")) and (workspace / "fonts" / d.get("file", "")).is_file():
            out.append(d)
    return out


def list_fonts(workspace: Path) -> list[dict]:
    fonts = [{"id": i, "family": fam, "category": cat, "source": "builtin"} for i, fam, cat in BUILTIN]
    fonts += [{"id": d["id"], "family": d["family"], "category": "Yours", "source": "yours", "name": d.get("name", d["family"])}
              for d in _user_meta(workspace)]
    return fonts


def resolve(workspace: Path, font_id: Optional[str]) -> Optional[tuple[Path, str]]:
    """(file, family) for a font id, or None (unknown/missing → caller uses the default font)."""
    if not font_id or not re.match(FONT_ID, font_id):
        return None
    if font_id in _BY_ID:
        p = BUILTIN_DIR / f"{font_id}.ttf"
        return (p, _BY_ID[font_id][0]) if p.is_file() else None
    for d in _user_meta(workspace):
        if d["id"] == font_id:
            return workspace / "fonts" / d["file"], d["family"]
    return None


def add(workspace: Path, data: bytes, filename: str) -> dict:
    """Check and store one of your fonts. Raises ValueError with a message for the user."""
    if len(data) > MAX_BYTES:
        raise ValueError("That font file is too big (20 MB at most).")
    head = data[:4]
    if head == b"OTTO":
        ext = ".otf"
    elif head in (b"\x00\x01\x00\x00", b"true"):
        ext = ".ttf"
    elif head == b"ttcf":
        raise ValueError("Font collections (.ttc) aren't supported; add the single .ttf or .otf instead.")
    elif head in (b"wOFF", b"wOF2"):
        raise ValueError("Web fonts (.woff/.woff2) aren't supported; add the .ttf or .otf version.")
    else:
        raise ValueError("That isn't a .ttf or .otf font file.")
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(io.BytesIO(data), 40)
        family, style = f.getname()
        if f.getlength("Ab") <= 0:
            raise ValueError
    except Exception as exc:  # noqa: BLE001
        raise ValueError("RJClip couldn't read that font file.") from exc
    family = (family or "").strip()
    if not _SAFE_FAMILY.match(family):
        raise ValueError("RJClip can't use this font: its name has characters it can't handle.")
    taken = {fam.lower() for _, fam, _ in BUILTIN} | {d["family"].lower() for d in _user_meta(workspace)}
    if family.lower() in taken:
        raise ValueError(f"You already have a font called “{family}”.")
    fid = "u-" + secrets.token_hex(6)
    (user_dir(workspace) / f"{fid}{ext}").write_bytes(data)
    name = Path(filename or "").stem[:60] or family
    meta = {"id": fid, "file": f"{fid}{ext}", "family": family, "style": style or "", "name": name}
    atomic_write_json(user_dir(workspace) / f"{fid}.json", meta)
    return {"id": fid, "family": family, "category": "Yours", "source": "yours", "name": name}


def delete(workspace: Path, font_id: str) -> bool:
    if not re.match(r"^u-[0-9a-f]{12}$", font_id or ""):
        return False
    found = False
    d = workspace / "fonts"
    for p in (d.glob(f"{font_id}.*") if d.is_dir() else []):
        p.unlink(missing_ok=True)
        found = True
    return found


def stage(workspace: Path, work: Path, font_ids: set[Optional[str]]) -> dict[str, tuple[str, str]]:
    """Copy the fonts these ids need into the render's work folder (libass reads fonts from
    there: fontsdir=.). Returns id -> (family, path in work) for the ones found."""
    import shutil
    out = {}
    for fid in sorted(i for i in font_ids if i):
        r = resolve(workspace, fid)
        if not r:
            continue
        src, family = r
        dst = work / f"font-{fid}{src.suffix.lower()}"
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, dst)
        out[fid] = (family, str(dst))
    return out
