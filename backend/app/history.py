"""Project version history: named snapshots, automatic checkpoints, restore, compare.

    <project>/history/snapshots/<id>.json   {meta..., "doc": {timeline, effects, captions, audio, output, facecam}}

* **Manual** snapshots ("Save version") are kept until you delete them.
* **Automatic** checkpoints are taken while you edit (at most one every 10 minutes,
  only if something changed), and always before an AI edit or a restore — so every
  big change can be undone. The newest 30 automatic ones are kept.
* Restoring never loses work: the current state is checkpointed first.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .schema import now_iso
from .storage import atomic_write_json, new_id, safe_join, validate_id

Origin = Literal["manual", "auto", "before_ai", "before_restore", "imported"]
DOC_KEYS = ("timeline", "effects", "captions", "audio", "output", "facecam")
AUTO_KEEP = 30
MANUAL_MAX = 200
AUTO_EVERY_S = 600


class SnapshotMeta(BaseModel):
    id: str
    label: str = Field(max_length=80)
    origin: Origin
    created_at: str = Field(default_factory=now_iso)
    ts: float = 0  # precise creation time; ordering + checkpoint throttling
    edit_revision: int = 0
    fingerprint: str = ""
    duration: float = 0
    clips: int = 0
    effects: int = 0
    media_names: list[str] = Field(default_factory=list)


class HistoryNotFound(KeyError):
    pass


def doc_of(project_data: dict) -> dict:
    return {k: project_data.get(k) for k in DOC_KEYS}  # facecam: None = no face cam


def fingerprint(doc: dict) -> str:
    return hashlib.sha1(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _duration(doc: dict) -> float:
    ends = [c["start"] + (c["source_out"] - c["source_in"]) / c.get("speed", 1)
            for t in doc["timeline"]["tracks"] for c in t["clips"]]
    return round(max(ends, default=0.0), 3)


class HistoryStore:
    def __init__(self, project_dir: Path):
        self.dir = project_dir / "history" / "snapshots"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._import_legacy(project_dir / "history")

    def _path(self, sid: str) -> Path:
        return safe_join(self.dir, validate_id(sid) + ".json")

    def _import_legacy(self, root: Path) -> None:
        """Earlier versions saved bare timelines as history/timeline-<ms>.json before AI edits."""
        for f in sorted(root.glob("timeline-*.json")):
            try:
                tl = json.loads(f.read_bytes())
                ms = int(f.stem.split("-", 1)[1])
            except (ValueError, IndexError):
                continue
            created = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")
            # only the timeline was kept; on restore the other parts stay as they are now
            doc = {"timeline": tl, "effects": None, "captions": None, "audio": None, "output": None}
            self._write(doc, "Before AI edit", "before_ai", 0, [], created_at=created, ts=ms / 1000)
            f.rename(f.with_suffix(".json.imported"))

    def _write(self, doc: dict, label: str, origin: str, edit_revision: int, media_names: list[str],
               created_at: Optional[str] = None, ts: Optional[float] = None) -> SnapshotMeta:
        meta = SnapshotMeta(id=new_id(), label=label[:80] or "Version", origin=origin,
                            created_at=created_at or now_iso(), ts=ts if ts is not None else time.time(), edit_revision=edit_revision,
                            fingerprint=fingerprint(doc), duration=_duration(doc),
                            clips=sum(len(t["clips"]) for t in doc["timeline"]["tracks"]),
                            effects=len(doc.get("effects") or []), media_names=media_names[:20])
        atomic_write_json(self._path(meta.id), {**meta.model_dump(), "doc": doc}, keep_backup=False)
        return meta

    # ---------------------------------------------------------------- API
    def list(self) -> list[dict]:
        out = []
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_bytes())
            except ValueError:
                continue
            d.pop("doc", None)
            out.append(d)
        out.sort(key=lambda d: (d.get("ts", 0), d["created_at"], d["id"]), reverse=True)
        return out

    def get(self, sid: str) -> dict:
        p = self._path(sid)
        if not p.exists():
            raise HistoryNotFound(sid)
        return json.loads(p.read_bytes())

    def snapshot(self, project_data: dict, label: str, origin: str = "manual") -> SnapshotMeta:
        doc = doc_of(project_data)
        names = sorted({m["original_name"] for m in project_data.get("media", [])
                        if any(c["media_id"] == m["id"] for t in doc["timeline"]["tracks"] for c in t["clips"])})
        if origin == "manual" and sum(1 for d in self.list() if d["origin"] == "manual") >= MANUAL_MAX:
            raise ValueError(f"You have {MANUAL_MAX} saved versions — delete some first.")
        meta = self._write(doc, label, origin, project_data.get("edit_revision", 0), names)
        self._prune()
        return meta

    def maybe_checkpoint(self, project_data: dict) -> Optional[SnapshotMeta]:
        """Automatic checkpoint while editing: at most every 10 minutes, only on change."""
        autos = [d for d in self.list() if d["origin"] == "auto"]
        doc = doc_of(project_data)
        if autos:
            last = autos[0]
            age = time.time() - (last.get("ts") or datetime.fromisoformat(last["created_at"]).timestamp())
            if age < AUTO_EVERY_S or last["fingerprint"] == fingerprint(doc):
                return None
        if not any(t["clips"] for t in doc["timeline"]["tracks"]):
            return None
        return self.snapshot(project_data, "Autosave checkpoint", "auto")

    def rename(self, sid: str, label: str) -> dict:
        d = self.get(sid)
        d["label"] = (label.strip() or d["label"])[:80]
        atomic_write_json(self._path(sid), d, keep_backup=False)
        d.pop("doc", None)
        return d

    def delete(self, sid: str) -> None:
        p = self._path(sid)
        if not p.exists():
            raise HistoryNotFound(sid)
        p.unlink()

    def _prune(self) -> None:
        autos = [d for d in self.list() if d["origin"] in ("auto", "before_ai", "before_restore")]
        for d in autos[AUTO_KEEP:]:
            try:
                os.unlink(self._path(d["id"]))
            except OSError:
                pass


# ---------------------------------------------------------------- compare
def _coverage(doc: dict) -> dict[str, list[tuple[float, float]]]:
    tracks = [t for t in doc["timeline"]["tracks"] if t["kind"] == "video" and not t.get("hidden")] or \
        [t for t in doc["timeline"]["tracks"] if t["kind"] == "audio" and not t.get("muted")]
    cov: dict[str, list[tuple[float, float]]] = {}
    for t in tracks:
        for c in t["clips"]:
            cov.setdefault(c["media_id"], []).append((c["source_in"], c["source_out"]))
    for k, v in cov.items():
        v.sort()
        merged: list[list[float]] = []
        for a, b in v:
            if merged and a <= merged[-1][1] + 1e-3:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        cov[k] = [(round(a, 3), round(b, 3)) for a, b in merged]
    return cov


def _subtract(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for s, e in a:
        pieces = [(s, e)]
        for bs, be in b:
            nxt = []
            for ps, pe in pieces:
                if be <= ps or bs >= pe:
                    nxt.append((ps, pe))
                    continue
                if bs > ps:
                    nxt.append((ps, bs))
                if be < pe:
                    nxt.append((be, pe))
            pieces = nxt
        out += [(round(x, 3), round(y, 3)) for x, y in pieces if y - x > 0.01]
    return out


def compare(a: dict, b: dict, media: dict[str, dict]) -> dict:
    """What changed from version A to version B (both are snapshot docs)."""
    ca, cb = _coverage(a), _coverage(b)
    sources = []
    for mid in sorted(set(ca) | set(cb), key=lambda m: media.get(m, {}).get("original_name", m)):
        ra, rb = ca.get(mid, []), cb.get(mid, [])
        removed, added = _subtract(ra, rb), _subtract(rb, ra)
        sources.append({"media_id": mid, "name": media.get(mid, {}).get("original_name", "(deleted media)"),
                        "duration": media.get(mid, {}).get("duration"), "a": ra, "b": rb,
                        "removed": removed, "added": added,
                        "removed_s": round(sum(e - s for s, e in removed), 2),
                        "added_s": round(sum(e - s for s, e in added), 2)})
    ea = {e["id"]: e for e in a.get("effects") or []}
    eb = {e["id"]: e for e in b.get("effects") or []}

    def kinds(ids, src):
        out: dict[str, int] = {}
        for i in ids:
            out[src[i]["kind"]] = out.get(src[i]["kind"], 0) + 1
        return out
    changed_fx = [i for i in set(ea) & set(eb) if ea[i] != eb[i]]
    settings = []
    for key in ("captions", "audio", "output", "facecam"):
        va, vb = a.get(key) or {}, b.get(key) or {}
        for k in sorted(set(va) | set(vb)):
            if va.get(k) != vb.get(k):
                settings.append({"group": key, "setting": k, "a": va.get(k), "b": vb.get(k)})
    transitions = lambda d: sum(1 for t in d["timeline"]["tracks"] for c in t["clips"] if c.get("transition_in"))  # noqa: E731
    return {
        "a": {"duration": _duration(a), "clips": sum(len(t["clips"]) for t in a["timeline"]["tracks"]),
              "effects": len(ea), "transitions": transitions(a)},
        "b": {"duration": _duration(b), "clips": sum(len(t["clips"]) for t in b["timeline"]["tracks"]),
              "effects": len(eb), "transitions": transitions(b)},
        "sources": sources,
        "effects": {"added": kinds(set(eb) - set(ea), eb), "removed": kinds(set(ea) - set(eb), ea),
                    "changed": len(changed_fx)},
        "settings": settings,
        "identical": fingerprint(a) == fingerprint(b),
    }
