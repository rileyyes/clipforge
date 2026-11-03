"""Thumbnail storage inside a project folder (no database needed).

    <project>/thumbnails/
        context.json                 creator-provided title/description/genre…
        assets/<id>.png|jpg          AI artwork, extracted frames, uploads (re-encoded)
        assets/<id>.json             asset metadata (kind, provider, timeline time…)
        frames.json                  cache index: frame key -> asset id
        analysis/<fingerprint>.json  cached video-understanding summaries
        designs/<id>.json            {"draft": Design, "versions": [Version…]}
        exports/<file>               validated exports

Rules: drafts autosave; versions are immutable snapshots created only by an
explicit "Save version"; nothing is overwritten without a user action.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from .schema import now_iso
from .storage import atomic_write_json, new_id, read_json, safe_join, validate_id
from .thumb_models import Design, ThumbContext, Version

MAX_ASSET_BYTES = 25 * 1024 * 1024
MAX_ASSET_SIDE = 4096


class ThumbNotFound(KeyError):
    pass


class AssetError(ValueError):
    pass


def decode_image(data: bytes) -> np.ndarray:
    """Decode untrusted image bytes (PNG/JPEG/WebP/GIF first frame) or raise."""
    if len(data) > MAX_ASSET_BYTES:
        raise AssetError("image is larger than 25 MB")
    if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP") or data[:6] in (b"GIF87a", b"GIF89a")):
        raise AssetError("unsupported image type (use PNG, JPEG, WebP or GIF)")
    arr = np.frombuffer(data, dtype=np.uint8)
    # refuse decompression bombs before decoding pixels
    img = cv2.imdecode(arr, cv2.IMREAD_REDUCED_COLOR_8)
    if img is None:
        raise AssetError("the image could not be decoded")
    # the 1/8-scale decode is cheap; its size tells us the real size (~x8)
    if max(img.shape[:2]) * 8 > 16384:
        raise AssetError("image dimensions are too large (max 16384 px)")
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise AssetError("the image could not be decoded")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if max(img.shape[:2]) > MAX_ASSET_SIDE:
        s = MAX_ASSET_SIDE / max(img.shape[:2])
        img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
    return img


class ThumbStore:
    def __init__(self, project_dir: Path):
        self.root = project_dir / "thumbnails"
        for sub in ("assets", "analysis", "designs", "exports"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- context
    def context(self) -> ThumbContext:
        p = self.root / "context.json"
        return ThumbContext.model_validate(read_json(p)) if p.exists() else ThumbContext()

    def save_context(self, ctx: ThumbContext) -> ThumbContext:
        atomic_write_json(self.root / "context.json", ctx.model_dump())
        return ctx

    # ---------------------------------------------------------------- assets
    def asset_path(self, asset_id: str) -> Path:
        validate_id(asset_id)
        for ext in (".png", ".jpg"):
            p = safe_join(self.root / "assets", asset_id + ext)
            if p.exists():
                return p
        raise ThumbNotFound(asset_id)

    def asset_meta(self, asset_id: str) -> dict:
        validate_id(asset_id)
        p = safe_join(self.root / "assets", asset_id + ".json")
        if not p.exists():
            raise ThumbNotFound(asset_id)
        return json.loads(p.read_bytes())

    def add_asset(self, data: bytes | np.ndarray, kind: str, meta: dict[str, Any]) -> dict:
        """Store an image re-encoded as PNG (strips metadata; validates decoding)."""
        img = data if isinstance(data, np.ndarray) else decode_image(data)
        ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        if not ok:
            raise AssetError("could not encode image")
        aid = new_id()
        (self.root / "assets" / f"{aid}.png").write_bytes(buf.tobytes())
        info = {"id": aid, "kind": kind, "width": int(img.shape[1]), "height": int(img.shape[0]),
                "created_at": now_iso(), **meta}
        atomic_write_json(self.root / "assets" / f"{aid}.json", info, keep_backup=False)
        return info

    def list_assets(self, kind: Optional[str] = None) -> list[dict]:
        out = []
        for p in sorted((self.root / "assets").glob("*.json")):
            try:
                m = json.loads(p.read_bytes())
            except ValueError:
                continue
            if kind is None or m.get("kind") == kind:
                out.append(m)
        out.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return out

    # frame cache: identical timeline moments are never extracted twice
    def cached_frame(self, key: str) -> Optional[dict]:
        idx = self._frames_index()
        aid = idx.get(key)
        if aid:
            try:
                self.asset_path(aid)
                return self.asset_meta(aid)
            except ThumbNotFound:
                return None
        return None

    def remember_frame(self, key: str, asset_id: str) -> None:
        with self._lock:
            idx = self._frames_index()
            idx[key] = asset_id
            atomic_write_json(self.root / "frames.json", idx, keep_backup=False)

    def _frames_index(self) -> dict:
        p = self.root / "frames.json"
        return json.loads(p.read_bytes()) if p.exists() else {}

    # ---------------------------------------------------------------- analysis cache
    def analysis(self, fingerprint: str) -> Optional[dict]:
        p = self.root / "analysis" / f"{_safe_key(fingerprint)}.json"
        return json.loads(p.read_bytes()) if p.exists() else None

    def save_analysis(self, fingerprint: str, data: dict) -> None:
        atomic_write_json(self.root / "analysis" / f"{_safe_key(fingerprint)}.json", data, keep_backup=False)

    def latest_analysis(self) -> Optional[dict]:
        files = sorted((self.root / "analysis").glob("*.json"), key=lambda p: p.stat().st_mtime)
        return json.loads(files[-1].read_bytes()) if files else None

    # ---------------------------------------------------------------- designs
    def _dpath(self, did: str) -> Path:
        return safe_join(self.root / "designs", validate_id(did) + ".json")

    def _load(self, did: str) -> dict:
        p = self._dpath(did)
        if not p.exists():
            raise ThumbNotFound(did)
        return read_json(p)

    def get(self, did: str) -> dict:
        doc = self._load(did)
        return {"draft": Design.model_validate(doc["draft"]).model_dump(mode="json"),
                "versions": [Version.model_validate(v).model_dump(mode="json") for v in doc["versions"]]}

    def create(self, design: Design) -> dict:
        doc = {"draft": design.model_dump(mode="json"), "versions": []}
        atomic_write_json(self._dpath(design.id), doc, keep_backup=False)
        return self.get(design.id)

    def save_draft(self, design: Design) -> dict:
        with self._lock:
            doc = self._load(design.id)
            d = design.model_dump(mode="json")
            d["updated_at"] = now_iso()
            d["created_at"] = doc["draft"].get("created_at", d["created_at"])
            doc["draft"] = Design.model_validate(d).model_dump(mode="json")
            atomic_write_json(self._dpath(design.id), doc)
        return doc["draft"]

    def save_version(self, did: str, label: str) -> dict:
        with self._lock:
            doc = self._load(did)
            draft = Design.model_validate(doc["draft"])
            v = Version(id=new_id(), label=label.strip()[:80] or f"Version {len(doc['versions']) + 1}",
                        design=draft, edit_revision=draft.edit_revision,
                        timeline_fingerprint=draft.timeline_fingerprint)
            doc["versions"].append(v.model_dump(mode="json"))
            atomic_write_json(self._dpath(did), doc)
            return v.model_dump(mode="json")

    def rename_version(self, did: str, vid: str, label: str) -> dict:
        with self._lock:
            doc = self._load(did)
            for v in doc["versions"]:
                if v["id"] == vid:
                    v["label"] = label.strip()[:80] or v["label"]
                    atomic_write_json(self._dpath(did), doc)
                    return v
        raise ThumbNotFound(vid)

    def restore_version(self, did: str, vid: str) -> dict:
        """Copy a version into the draft (the version itself stays untouched)."""
        with self._lock:
            doc = self._load(did)
            v = next((v for v in doc["versions"] if v["id"] == vid), None)
            if v is None:
                raise ThumbNotFound(vid)
            d = dict(v["design"])
            d["updated_at"] = now_iso()
            doc["draft"] = Design.model_validate(d).model_dump(mode="json")
            atomic_write_json(self._dpath(did), doc)
            return doc["draft"]

    def version_design(self, did: str, vid: Optional[str]) -> Design:
        doc = self._load(did)
        if vid is None:
            return Design.model_validate(doc["draft"])
        v = next((v for v in doc["versions"] if v["id"] == vid), None)
        if v is None:
            raise ThumbNotFound(vid)
        return Design.model_validate(v["design"])

    def duplicate(self, did: str, name: Optional[str] = None) -> dict:
        src = Design.model_validate(self._load(did)["draft"])
        d = src.model_dump(mode="json")
        d.update(id=new_id(), name=(name or f"{src.name} (copy)")[:80], created_at=now_iso(),
                 updated_at=now_iso())
        return self.create(Design.model_validate(d))

    def delete(self, did: str) -> None:
        p = self._dpath(did)
        if not p.exists():
            raise ThumbNotFound(did)
        p.unlink()
        p.with_suffix(".json.bak").unlink(missing_ok=True)

    def list(self) -> list[dict]:
        out = []
        for p in (self.root / "designs").glob("*.json"):
            try:
                doc = read_json(p)
                d = doc["draft"]
            except (ValueError, KeyError):
                continue
            img = next((layer["asset_id"] for layer in d.get("layers", []) if layer.get("type") == "image"), None)
            out.append({"id": d["id"], "name": d["name"], "updated_at": d["updated_at"],
                        "versions": len(doc.get("versions", [])), "edit_revision": d.get("edit_revision", 0),
                        "timeline_fingerprint": d.get("timeline_fingerprint", ""),
                        "preview_asset": img, "concept": (d.get("concept") or {}).get("name")})
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        return out


def _safe_key(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()
