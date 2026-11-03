"""Project repository: one folder per project, JSON project file, media beside it.

    <workspace>/projects/<project_id>/
        project.json        (+ project.json.bak, previous good save)
        media/original/     imported sources, read-only, never modified
        media/proxy/        browser preview copies
        media/thumbs/       thumbnails
        media/waveforms/    audio peak data
        exports/            rendered outputs + validation reports
        work/               temporary render intermediates (safe to delete)

The JSON files are the source of truth. A relational DB isn't needed yet for a
single-user local app; see ARCHITECTURE.md for when SQLite/Postgres comes in.
"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Optional

from .schema import Project, default_timeline, migrate, now_iso
from .storage import atomic_write_json, dir_size, new_id, read_json, safe_join, validate_id


class ProjectNotFound(KeyError):
    pass


class RevisionConflict(RuntimeError):
    pass


class ProjectStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock(self, project_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def dir(self, project_id: str) -> Path:
        return safe_join(self.root, validate_id(project_id))

    def _file(self, project_id: str) -> Path:
        return self.dir(project_id) / "project.json"

    def create(self, name: str) -> Project:
        pid = new_id()
        project = Project(id=pid, name=name.strip() or "Untitled",
                          timeline=default_timeline(new_id))
        d = self.dir(pid)
        d.mkdir(parents=True)
        for sub in ("media/original", "media/proxy", "media/thumbs", "media/waveforms",
                    "exports", "work"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._file(pid), project.model_dump(mode="json"), keep_backup=False)
        return project

    def load(self, project_id: str) -> Project:
        f = self._file(project_id)
        if not f.exists():
            raise ProjectNotFound(project_id)
        return Project.model_validate(migrate(read_json(f)))

    def save(self, project: Project, expected_revision: Optional[int] = None) -> Project:
        """Validate + atomically persist. Raises RevisionConflict on stale writes."""
        with self.lock(project.id):
            current = self.load(project.id)
            if expected_revision is not None and current.revision != expected_revision:
                raise RevisionConflict(
                    f"project changed elsewhere (revision {current.revision}, "
                    f"you had {expected_revision})")
            data = project.model_dump(mode="json")
            data["revision"] = current.revision + 1
            data["updated_at"] = now_iso()
            data["created_at"] = current.created_at
            saved = Project.model_validate(data)
            atomic_write_json(self._file(project.id), saved.model_dump(mode="json"))
            return saved

    def update(self, project_id: str, fn) -> Project:
        """Server-side read-modify-write under the project lock."""
        with self.lock(project_id):
            p = self.load(project_id)
            data = fn(p.model_dump(mode="json"))
            data["revision"] = p.revision + 1
            data["updated_at"] = now_iso()
            saved = Project.model_validate(data)
            atomic_write_json(self._file(project_id), saved.model_dump(mode="json"))
            return saved

    def list(self) -> list[dict]:
        out = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            try:
                p = self.load(d.name)
            except Exception:  # unreadable/corrupt projects are reported, not hidden
                out.append({"id": d.name, "name": "(unreadable project)", "error": True})
                continue
            thumb = next((m.id for m in p.media if m.thumbnail), None)
            out.append({
                "id": p.id, "name": p.name, "updated_at": p.updated_at,
                "created_at": p.created_at, "media_count": len(p.media),
                "duration": round(p.timeline.duration, 3), "thumbnail_media_id": thumb,
                "clip_count": sum(len(t.clips) for t in p.timeline.tracks),
            })
        out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return out

    def rename(self, project_id: str, name: str) -> Project:
        name = name.strip()
        if not name:
            raise ValueError("name cannot be empty")
        return self.update(project_id, lambda d: {**d, "name": name[:120]})

    def duplicate(self, project_id: str) -> Project:
        src = self.load(project_id)
        new_pid = new_id()
        dst = self.dir(new_pid)
        # Copy media, effect assets (images, your sounds), analysis/transcripts and the
        # project file; exports, work files and version history are not copied.
        shutil.copytree(self.dir(project_id) / "media", dst / "media",
                        copy_function=shutil.copy2)
        for sub in ("fx", "analysis"):
            if (self.dir(project_id) / sub).is_dir():
                shutil.copytree(self.dir(project_id) / sub, dst / sub, copy_function=shutil.copy2)
        (dst / "exports").mkdir()
        (dst / "work").mkdir()
        data = src.model_dump(mode="json")
        data.update(id=new_pid, name=f"{src.name} (copy)"[:120], revision=0,
                    created_at=now_iso(), updated_at=now_iso())
        project = Project.model_validate(data)
        atomic_write_json(dst / "project.json", project.model_dump(mode="json"),
                          keep_backup=False)
        return project

    def delete(self, project_id: str) -> None:
        d = self.dir(project_id)
        if not (d / "project.json").exists():
            raise ProjectNotFound(project_id)
        # Originals are chmod 0400; make writable so rmtree can remove them.
        for p in d.rglob("*"):
            try:
                p.chmod(0o700 if p.is_dir() else 0o600)
            except OSError:
                pass
        shutil.rmtree(d)

    def usage(self, project_id: str) -> dict:
        d = self.dir(project_id)
        return {k: dir_size(d / k) for k in ("media", "exports", "work")}
