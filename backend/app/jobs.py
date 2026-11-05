"""Background job system.

Jobs are persisted as JSON so they survive restarts. A job that was running when
the server stopped is marked ``interrupted`` on startup and can be retried.
Progress is either *measured* (fraction from FFmpeg output time) or ``None``
with a stage label — never invented.
"""
from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

from . import ffmpeg as ff
from .schema import now_iso
from .storage import atomic_write_json, new_id, read_json, safe_join, validate_id

Status = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class Job(BaseModel):
    id: str
    kind: str
    project_id: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    status: Status = "queued"
    stage: str = "Queued"
    stage_index: int = 0
    stage_count: int = 1
    progress: Optional[float] = None  # 0..1 overall, only when measurable
    error: Optional[str] = None
    error_detail: Optional[str] = None
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_s: Optional[float] = None


class JobContext:
    """Handed to job functions so they can report progress and honour cancel."""

    def __init__(self, manager: "JobManager", job: Job):
        self._m = manager
        self.job = job
        self.cancel_event = threading.Event()
        self._best = 0.0  # overall progress never goes backwards

    def stage(self, index: int, count: int, label: str) -> None:
        self._m._update(self.job.id, stage=label, stage_index=index, stage_count=count)

    def progress(self, overall: Optional[float]) -> None:
        if overall is None:
            self._m._update(self.job.id, progress=None, throttle=True)
            return
        # FFmpeg's time reports can wobble back a little between lines, so
        # keep the highest value seen: the bar must only ever move forward.
        value = round(max(self._best, 0.0, min(1.0, overall)), 4)
        self._best = value
        self._m._update(self.job.id, progress=value, throttle=True)

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise ff.Cancelled("cancelled by user")


JobFn = Callable[[JobContext], dict]


class JobManager:
    def __init__(self, jobs_dir: Path, workers: int = 1):
        self.dir = jobs_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._ctx: dict[str, JobContext] = {}
        self._handlers: dict[str, JobFn] = {}
        self._last_persist: dict[str, float] = {}
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._load()

    # -- persistence ----------------------------------------------------
    def _path(self, job_id: str) -> Path:
        return safe_join(self.dir, validate_id(job_id) + ".json")

    def _load(self) -> None:
        for p in sorted(self.dir.glob("*.json")):
            try:
                job = Job.model_validate(read_json(p))
            except Exception:
                continue
            if job.status in ("queued", "running"):
                job.status = "interrupted"
                job.error = "The application stopped while this job was running."
                job.finished_at = now_iso()
                atomic_write_json(p, job.model_dump(), keep_backup=False)
            self._jobs[job.id] = job

    def _persist(self, job: Job) -> None:
        atomic_write_json(self._path(job.id), job.model_dump(), keep_backup=False)

    def _update(self, job_id: str, throttle: bool = False, **fields: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for k, v in fields.items():
                setattr(job, k, v)
            now = time.monotonic()
            if not throttle or now - self._last_persist.get(job_id, 0) > 1.0:
                self._last_persist[job_id] = now
                self._persist(job)

    # -- API -----------------------------------------------------------
    def register(self, kind: str, fn: JobFn) -> None:
        self._handlers[kind] = fn

    def submit(self, kind: str, project_id: Optional[str], params: dict[str, Any]) -> Job:
        if kind not in self._handlers:
            raise ValueError(f"unknown job kind {kind}")
        job = Job(id=new_id(), kind=kind, project_id=project_id, params=params)
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
            ctx = JobContext(self, job)
            self._ctx[job.id] = ctx
        self._pool.submit(self._run, ctx)
        return job

    def _run(self, ctx: JobContext) -> None:
        job = ctx.job
        if ctx.cancel_event.is_set():
            self._update(job.id, status="cancelled", stage="Cancelled", finished_at=now_iso())
            return
        t0 = time.monotonic()
        self._update(job.id, status="running", started_at=now_iso(), stage="Starting")
        try:
            result = self._handlers[job.kind](ctx) or {}
            self._update(job.id, status="succeeded", stage="Done", progress=1.0,
                         result=result, finished_at=now_iso(),
                         elapsed_s=round(time.monotonic() - t0, 2))
        except ff.Cancelled:
            self._update(job.id, status="cancelled", stage="Cancelled",
                         finished_at=now_iso(), elapsed_s=round(time.monotonic() - t0, 2))
        except ff.FFmpegError as exc:
            self._update(job.id, status="failed", error=str(exc),
                         error_detail=exc.stderr or None, finished_at=now_iso(),
                         elapsed_s=round(time.monotonic() - t0, 2))
        except Exception as exc:  # noqa: BLE001 - report any failure to the UI
            self._update(job.id, status="failed", error=str(exc) or type(exc).__name__,
                         error_detail=traceback.format_exc(limit=5), finished_at=now_iso(),
                         elapsed_s=round(time.monotonic() - t0, 2))
        finally:
            with self._lock:
                self._ctx.pop(job.id, None)

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            j = self._jobs.get(job_id)
            return j.model_copy(deep=True) if j else None

    def list(self, project_id: Optional[str] = None, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = [j.model_copy(deep=True) for j in self._jobs.values()
                    if project_id is None or j.project_id == project_id]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            ctx = self._ctx.get(job_id)
            if ctx is None:
                return False
            ctx.cancel_event.set()
            return True

    def retry(self, job_id: str) -> Job:
        old = self.get(job_id)
        if old is None:
            raise KeyError(job_id)
        if old.status not in ("failed", "cancelled", "interrupted"):
            raise ValueError("only failed, cancelled or interrupted jobs can be retried")
        return self.submit(old.kind, old.project_id, old.params)

    def active_for_project(self, project_id: str) -> list[Job]:
        return [j for j in self.list(project_id, limit=1000) if j.status not in TERMINAL]

    def wait(self, job_id: str, timeout: float = 600) -> Job:
        """Test helper: block until a job finishes."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            j = self.get(job_id)
            if j and j.status in TERMINAL:
                return j
            time.sleep(0.1)
        raise TimeoutError(job_id)

    def shutdown(self) -> None:
        with self._lock:
            for ctx in self._ctx.values():
                ctx.cancel_event.set()
        self._pool.shutdown(wait=True, cancel_futures=True)
