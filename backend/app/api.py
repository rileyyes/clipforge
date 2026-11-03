"""HTTP API (Starlette + Pydantic).

Routes are deliberately thin: they validate input, call services, and shape
responses. See ARCHITECTURE.md for the planned FastAPI migration.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from . import ffmpeg as ff
from . import media as media_svc
from .config import Settings
from .jobs import JobContext, JobManager
from .projects import ProjectNotFound, ProjectStore, RevisionConflict
from . import analysis as analysis_svc
from .autoedit import AutoEditSettings, EDLError, edl_to_timeline, plan as plan_edit
from .render import render_project, validate_export
from .transcription import available_transcriber
from .schema import SOUNDS, AudioSettings, CaptionSettings, Effect, OutputSettings, Project, Timeline
from .storage import (PathSecurityError, dir_size, display_name, media_extension, new_id,
                      safe_join, validate_id)


def err(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


def pydantic_error(exc: ValidationError) -> JSONResponse:
    msgs = []
    for e in exc.errors()[:5]:
        loc = ".".join(str(x) for x in e.get("loc", ()))
        msgs.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
    return err(422, "; ".join(msgs) or "invalid data")


async def body_model(request: Request, model: type[BaseModel]):
    try:
        raw = await request.body()
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "request too large")
        return model.model_validate_json(raw or b"{}")
    except ValidationError as exc:
        raise _ValidationWrap(exc) from exc


class _ValidationWrap(Exception):
    def __init__(self, exc: ValidationError):
        self.exc = exc


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TimelineSave(BaseModel):
    base_edit_revision: int
    timeline: Timeline
    output: OutputSettings
    effects: Optional[list[Effect]] = None
    captions: Optional[CaptionSettings] = None
    audio: Optional[AudioSettings] = None


class ExportRequest(BaseModel):
    filename: str = Field(default="export", max_length=120)
    quality: Literal["draft", "standard", "high"] = "standard"
    output: Optional[OutputSettings] = None
    encoder: Literal["auto", "libx264"] = "auto"


class Services:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = ProjectStore(settings.projects_dir)
        self.jobs = JobManager(settings.jobs_dir, workers=settings.job_workers)
        self.jobs.register("derive_media", self._derive_media)
        self.jobs.register("render", self._render)
        self.jobs.register("analyze", self._analyze)
        self.jobs.register("transcribe", self._transcribe)
        try:  # the thumbnail maker is optional: never let it stop the editor starting
            from .thumb_api import register_thumb_jobs
            register_thumb_jobs(self)
            self.thumbnails_error = None
        except ImportError as exc:
            self.thumbnails_error = (f"Thumbnail Maker unavailable ({exc}). Run: "
                                     "pip install -r requirements.txt")
            print("WARNING:", self.thumbnails_error)

    # -- job handlers -----------------------------------------------------
    def _derive_media(self, ctx: JobContext) -> dict:
        pid, mid = ctx.job.project_id, ctx.job.params["media_id"]
        project = self.store.load(pid)
        asset = project.media_by_id()[mid]
        pdir = self.store.dir(pid)
        src = pdir / "media" / "original" / asset.stored_name
        updates: dict[str, Any] = {}
        want_proxy = media_svc.needs_proxy(asset)
        count = 2 + int(want_proxy)
        if asset.has_video:
            ctx.stage(1, count, "Generating thumbnail")
            thumb = media_svc.media_dir(pdir, "thumbs") / f"{mid}.jpg"
            media_svc.make_thumbnail(self.settings, asset, src, thumb)
            updates["thumbnail"] = thumb.name
        ctx.check_cancel()
        if asset.has_audio:
            ctx.stage(2, count, "Analysing audio waveform")
            wf = media_svc.media_dir(pdir, "waveforms") / f"{mid}.json"
            media_svc.make_waveform(self.settings, asset, src, wf, ctx.cancel_event)
            updates["waveform"] = wf.name
        if want_proxy:
            ctx.stage(3, count, "Creating preview proxy")
            px = media_svc.media_dir(pdir, "proxy") / f"{mid}.mp4"
            media_svc.make_proxy(self.settings, asset, src, px, on_progress=ctx.progress,
                                 cancel=ctx.cancel_event)
            updates["proxy"] = px.name

        def apply(d: dict) -> dict:
            for m in d["media"]:
                if m["id"] == mid:
                    m.update(updates)
            return d
        self.store.update(pid, apply)
        return {"media_id": mid, **updates}

    def _analyze(self, ctx: JobContext) -> dict:
        pid, mid = ctx.job.project_id, ctx.job.params["media_id"]
        asset = self.store.load(pid).media_by_id()[mid]
        transcriber = available_transcriber() if ctx.job.params.get("transcribe", True) else None
        return analysis_svc.analyze_media(ctx, self.settings, self.store.dir(pid), asset, transcriber)

    def _transcribe(self, ctx: JobContext) -> dict:
        pid = ctx.job.project_id
        transcriber = available_transcriber()
        if transcriber is None:
            raise RuntimeError("No transcriber installed (pip install -r requirements-ai.txt)")
        media = self.store.load(pid).media_by_id()
        ids = [m for m in ctx.job.params.get("media_ids", []) if m in media and media[m].has_audio]
        results = []
        for i, mid in enumerate(ids, 1):
            ctx.check_cancel()
            results.append(analysis_svc.transcribe_media(ctx, self.settings, self.store.dir(pid), media[mid],
                                                         transcriber))
        return {"media": results}

    def _render(self, ctx: JobContext) -> dict:
        pid = ctx.job.project_id
        p = ctx.job.params
        project = self.store.load(pid)
        return render_project(ctx, self.settings, project, self.store.dir(pid),
                              p.get("filename", "export"), p.get("quality", "standard"),
                              p.get("encoder", "auto"))


def build_routes(svc: Services) -> list[Route]:
    S = svc.settings
    store = svc.store

    def pid_of(request: Request) -> str:
        try:
            return validate_id(request.path_params["pid"])
        except PathSecurityError:
            raise HTTPException(404, "project not found")

    def load(pid: str) -> Project:
        try:
            return store.load(pid)
        except ProjectNotFound:
            raise HTTPException(404, "project not found")

    def project_payload(p: Project) -> dict:
        d = p.model_dump(mode="json")
        orig = store.dir(p.id) / "media" / "original"
        d["missing_media"] = [m.id for m in p.media if not (orig / m.stored_name).exists()]
        return d

    # -- system ---------------------------------------------------------
    async def health(_: Request):
        return JSONResponse({"ok": True})

    async def system(_: Request):
        du = shutil.disk_usage(S.workspace)
        return JSONResponse({
            "ffmpeg": ff.ffmpeg_version(S.ffmpeg_bin),
            "h264_encoder": ff.pick_h264_encoder(S.ffmpeg_bin),
            "workspace": str(S.workspace),
            "workspace_bytes": dir_size(S.workspace),
            "workspace_quota_bytes": S.max_workspace_bytes,
            "disk_free_bytes": du.free,
            "disk_total_bytes": du.total,
            "max_upload_bytes": S.max_upload_bytes,
            "cpu_count": os.cpu_count(),
            "allowed_extensions": sorted(media_svc.SAFE_INPUT_FORMATS.split(",")),
        })

    async def cleanup(_: Request):
        active = {j.id for p in store.list() if not p.get("error")
                  for j in svc.jobs.active_for_project(p["id"])}
        freed = 0
        for pdir in S.projects_dir.iterdir():
            work = pdir / "work"
            if work.is_dir():
                for d in work.iterdir():
                    if d.name not in active:
                        freed += dir_size(d)
                        shutil.rmtree(d, ignore_errors=True)
            for partial in pdir.rglob("*.partial*"):
                freed += partial.stat().st_size
                partial.unlink(missing_ok=True)
        for t in S.tmp_dir.iterdir():
            freed += t.stat().st_size if t.is_file() else dir_size(t)
            shutil.rmtree(t, ignore_errors=True) if t.is_dir() else t.unlink(missing_ok=True)
        return JSONResponse({"freed_bytes": freed})

    # -- projects ---------------------------------------------------------
    async def list_projects(_: Request):
        return JSONResponse({"projects": store.list()})

    async def create_project(request: Request):
        body = await body_model(request, NameBody)
        return JSONResponse(project_payload(store.create(body.name)), status_code=201)

    async def get_project(request: Request):
        return JSONResponse(project_payload(load(pid_of(request))))

    async def save_timeline(request: Request):
        pid = pid_of(request)
        body = await body_model(request, TimelineSave)
        load(pid)
        with store.lock(pid):
            cur = store.load(pid)
            if cur.edit_revision != body.base_edit_revision:
                return err(409, "This project was changed in another window. Reload to "
                                "continue.", edit_revision=cur.edit_revision)
            data = cur.model_dump(mode="json")
            data["timeline"] = body.timeline.model_dump(mode="json")
            data["output"] = body.output.model_dump(mode="json")
            if body.effects is not None:
                data["effects"] = [e.model_dump(mode="json") for e in body.effects]
            if body.captions is not None:
                data["captions"] = body.captions.model_dump(mode="json")
            if body.audio is not None:
                data["audio"] = body.audio.model_dump(mode="json")
            data["edit_revision"] = cur.edit_revision + 1
            try:
                candidate = Project.model_validate(data)
            except ValidationError as exc:
                return pydantic_error(exc)
        # save() re-takes the lock and re-validates; edit_revision already bumped
        try:
            saved = store.save(candidate, expected_revision=cur.revision)
        except RevisionConflict:
            # a background job updated media in between; merge once more
            latest = store.load(pid)
            d = latest.model_dump(mode="json")
            d.update(timeline=data["timeline"], output=data["output"], effects=data["effects"],
                     captions=data["captions"], audio=data["audio"], edit_revision=latest.edit_revision + 1)
            saved = store.save(Project.model_validate(d), expected_revision=latest.revision)
        return JSONResponse(project_payload(saved))

    async def rename_project(request: Request):
        pid = pid_of(request)
        body = await body_model(request, NameBody)
        load(pid)
        return JSONResponse(project_payload(store.rename(pid, body.name)))

    async def duplicate_project(request: Request):
        pid = pid_of(request)
        load(pid)
        return JSONResponse(project_payload(store.duplicate(pid)), status_code=201)

    async def delete_project(request: Request):
        pid = pid_of(request)
        load(pid)
        if svc.jobs.active_for_project(pid):
            return err(409, "Cancel this project's running jobs before deleting it.")
        store.delete(pid)
        return Response(status_code=204)

    # -- media ------------------------------------------------------------
    async def upload_media(request: Request):
        pid = pid_of(request)
        load(pid)
        filename = request.query_params.get("filename", "")
        try:
            ext = media_extension(filename)
        except PathSecurityError as exc:
            return err(415, str(exc))
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > S.max_upload_bytes:
            return err(413, f"file exceeds the {S.max_upload_bytes // 1024**2} MB upload limit")
        if dir_size(S.workspace) > S.max_workspace_bytes:
            return err(507, "workspace storage quota reached; delete projects or run cleanup")
        du = shutil.disk_usage(S.workspace)
        if declared and declared.isdigit() and int(declared) > du.free - 2 * 1024**3:
            return err(507, "not enough free disk space for this file")

        if not ff.tools_available(S.ffmpeg_bin, S.ffprobe_bin):
            return err(503, ff.MISSING_FFMPEG)
        mid = new_id()
        odir = media_svc.media_dir(store.dir(pid), "original")
        partial = odir / f"{mid}{ext}.partial"
        final = odir / f"{mid}{ext}"
        size = 0
        h = hashlib.sha256()
        try:
            with open(partial, "wb") as fh:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > S.max_upload_bytes:
                        raise HTTPException(413, "file exceeds the upload limit")
                    h.update(chunk)
                    fh.write(chunk)
            if size == 0:
                raise HTTPException(400, "empty upload")
            os.replace(partial, final)
            try:
                asset = media_svc.build_asset(S, mid, final, display_name(filename))
            except ff.FFmpegError as exc:
                final.unlink(missing_ok=True)
                return err(415, f"Could not import this file: {exc}")
            except Exception as exc:  # noqa: BLE001 - always give the UI a readable reason
                import traceback
                traceback.print_exc()
                final.unlink(missing_ok=True)
                return err(500, f"Import failed: {type(exc).__name__}: {exc}")
        finally:
            partial.unlink(missing_ok=True)

        asset.sha256 = h.hexdigest()
        project = load(pid)
        dup = next((m for m in project.media if m.sha256 == asset.sha256), None)
        if dup is not None:
            final.unlink(missing_ok=True)
            return JSONResponse({"media": dup.model_dump(mode="json"), "duplicate": True})
        media_svc.mark_read_only(final)
        store.update(pid, lambda d: {**d, "media": d["media"] + [asset.model_dump(mode="json")]})
        job = svc.jobs.submit("derive_media", pid, {"media_id": mid})
        return JSONResponse({"media": asset.model_dump(mode="json"), "job_id": job.id,
                             "duplicate": False}, status_code=201)

    def media_asset(request: Request):
        pid = pid_of(request)
        try:
            mid = validate_id(request.path_params["mid"])
        except PathSecurityError:
            raise HTTPException(404, "media not found")
        p = load(pid)
        asset = p.media_by_id().get(mid)
        if asset is None:
            raise HTTPException(404, "media not found")
        return pid, asset

    async def media_stream(request: Request):
        pid, asset = media_asset(request)
        d = store.dir(pid) / "media"
        path = (d / "proxy" / asset.proxy) if asset.proxy else (d / "original" / asset.stored_name)
        if not path.exists():
            return err(404, "media file is missing on disk")
        mt = "video/mp4" if asset.proxy else None
        return FileResponse(path, media_type=mt)

    async def media_thumb(request: Request):
        pid, asset = media_asset(request)
        if not asset.thumbnail:
            return err(404, "no thumbnail yet")
        return FileResponse(store.dir(pid) / "media" / "thumbs" / asset.thumbnail,
                            media_type="image/jpeg")

    async def media_waveform(request: Request):
        pid, asset = media_asset(request)
        if not asset.waveform:
            return err(404, "no waveform yet")
        return FileResponse(store.dir(pid) / "media" / "waveforms" / asset.waveform,
                            media_type="application/json")

    async def delete_media(request: Request):
        pid, asset = media_asset(request)
        p = load(pid)
        if any(c.media_id == asset.id for t in p.timeline.tracks for c in t.clips):
            return err(409, "This media is used on the timeline. Remove its clips first.")
        store.update(pid, lambda d: {**d, "media": [m for m in d["media"]
                                                     if m["id"] != asset.id]})
        (store.dir(pid) / "analysis" / f"{asset.id}.json").unlink(missing_ok=True)
        base = store.dir(pid) / "media"
        for sub, name in (("original", asset.stored_name), ("proxy", asset.proxy),
                          ("thumbs", asset.thumbnail), ("waveforms", asset.waveform)):
            if name:
                f = base / sub / name
                if f.exists():
                    f.chmod(0o600)
                    f.unlink()
        return Response(status_code=204)

    # -- exports ----------------------------------------------------------
    async def start_export(request: Request):
        pid = pid_of(request)
        body = await body_model(request, ExportRequest)
        p = load(pid)
        if body.output is not None and body.output != p.output:
            out = body.output.model_dump(mode="json")
            p = store.update(pid, lambda d: {**d, "output": out})
        if p.timeline.duration <= 0:
            return err(400, "The timeline is empty — add at least one clip before exporting.")
        missing = project_payload(p)["missing_media"]
        if missing:
            return err(400, "Some source media files are missing; relink them first.")
        job = svc.jobs.submit("render", pid, {"filename": body.filename,
                                              "quality": body.quality,
                                              "encoder": body.encoder})
        return JSONResponse(job.model_dump(), status_code=202)

    def export_path(pid: str, name: str) -> Path:
        if not name.endswith(".mp4") or name.endswith(".partial.mp4"):
            raise HTTPException(404, "export not found")
        try:
            path = safe_join(store.dir(pid), "exports", name)
        except PathSecurityError:
            raise HTTPException(404, "export not found")
        if not path.is_file():
            raise HTTPException(404, "export not found")
        return path

    async def list_exports(request: Request):
        pid = pid_of(request)
        load(pid)
        d = store.dir(pid) / "exports"
        items = []
        for f in sorted(d.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True):
            if f.name.endswith(".partial.mp4"):
                continue
            rep = d / (f.stem + ".report.json")
            items.append({"file": f.name, "size": f.stat().st_size,
                          "modified": f.stat().st_mtime,
                          "validation": __import__("json").loads(rep.read_text())
                          if rep.exists() else None})
        return JSONResponse({"exports": items})

    async def download_export(request: Request):
        pid = pid_of(request)
        load(pid)
        path = export_path(pid, request.path_params["name"])
        inline = request.query_params.get("inline") == "1"
        return FileResponse(path, media_type="video/mp4",
                            filename=None if inline else path.name)

    async def delete_export(request: Request):
        pid = pid_of(request)
        load(pid)
        path = export_path(pid, request.path_params["name"])
        path.unlink()
        (path.parent / (path.stem + ".report.json")).unlink(missing_ok=True)
        return Response(status_code=204)

    async def revalidate_export(request: Request):
        pid = pid_of(request)
        p = load(pid)
        path = export_path(pid, request.path_params["name"])
        rep_path = path.parent / (path.stem + ".report.json")
        prev = __import__("json").loads(rep_path.read_text()) if rep_path.exists() else {}
        expected = prev.get("duration") or p.timeline.duration
        return JSONResponse(validate_export(S, path, p.output, expected))

    # -- auto editor ------------------------------------------------------
    class AnalyzeBody(BaseModel):
        media_id: str
        transcribe: bool = True

    class PlanBody(BaseModel):
        media_id: str
        settings: AutoEditSettings = Field(default_factory=AutoEditSettings)

    class ApplyBody(PlanBody):
        expected_output: Optional[float] = None  # guards against stale review screens

    def _asset_for(pid: str, mid: str):
        try:
            validate_id(mid)
        except PathSecurityError:
            raise HTTPException(404, "media not found")
        p = load(pid)
        a = p.media_by_id().get(mid)
        if a is None:
            raise HTTPException(404, "media not found")
        return p, a

    async def autoedit_status(request: Request):
        pid = pid_of(request)
        p = load(pid)
        items = []
        for m in p.media:
            a = analysis_svc.load_analysis(store.dir(pid), m.id)
            items.append({"media_id": m.id, "analyzed": a is not None,
                          "has_transcript": bool(a and a.get("words"))})
        t = available_transcriber()
        return JSONResponse({"media": items, "transcriber": t.name if t else None})

    async def start_analysis(request: Request):
        pid = pid_of(request)
        body = await body_model(request, AnalyzeBody)
        _asset_for(pid, body.media_id)
        running = [j for j in svc.jobs.active_for_project(pid)
                   if j.kind == "analyze" and j.params.get("media_id") == body.media_id]
        if running:
            return JSONResponse(running[0].model_dump(), status_code=202)
        job = svc.jobs.submit("analyze", pid, {"media_id": body.media_id, "transcribe": body.transcribe})
        return JSONResponse(job.model_dump(), status_code=202)

    def _plan(pid: str, body) -> tuple[Project, Any, dict]:
        p, asset = _asset_for(pid, body.media_id)
        data = analysis_svc.load_analysis(store.dir(pid), asset.id)
        if data is None:
            raise HTTPException(409, "Analyze this media first.")
        return p, asset, plan_edit(data, body.settings)

    async def autoedit_plan(request: Request):
        pid = pid_of(request)
        body = await body_model(request, PlanBody)
        _, _, result = _plan(pid, body)
        return JSONResponse(result)

    async def autoedit_apply(request: Request):
        pid = pid_of(request)
        body = await body_model(request, ApplyBody)
        p, asset, result = _plan(pid, body)  # recomputed server-side; client EDL never trusted
        if body.expected_output is not None and abs(result["output_duration"] - body.expected_output) > 0.01:
            return err(409, "The plan changed since you reviewed it. Review it again before applying.")
        if not result["segments"]:
            return err(400, "The plan has no selected moments.")
        hist = store.dir(pid) / "history"
        hist.mkdir(exist_ok=True)
        import json as _json, time as _time
        (hist / f"timeline-{int(_time.time() * 1000)}.json").write_text(
            _json.dumps(p.timeline.model_dump(mode="json")))

        def apply(d: dict) -> dict:
            d = edl_to_timeline(d, asset.model_dump(mode="json"), result["segments"], new_id)
            d["edit_revision"] = d.get("edit_revision", 0) + 1
            return d
        try:
            saved = store.update(pid, apply)
        except (EDLError, ValidationError) as exc:
            return err(422, f"Generated edit failed validation: {exc}")
        return JSONResponse({"project": project_payload(saved), "plan": result})

    # -- phase 4: transcription, effects, captions ------------------------
    from . import effects as fx

    class TranscribeBody(BaseModel):
        media_ids: Optional[list[str]] = None

    class CensorBody(BaseModel):
        sound: Literal["beep", "boing", "scratch", "honk", "quack", "mute"] = "beep"
        level: Literal["strong", "all"] = "strong"
        custom: list[str] = Field(default_factory=list, max_length=200)
        allow: list[str] = Field(default_factory=list, max_length=200)
        padding: float = Field(default=0.06, ge=0, le=0.5)

    class FunBody(BaseModel):
        intensity: Literal["minimal", "balanced", "chaotic"] = "balanced"

    async def fx_status(request: Request):
        pid = pid_of(request)
        p = load(pid)
        t = available_transcriber()
        return JSONResponse({"transcriber": t.name if t else None,
                             "transcript": fx.transcript_status(p, store.dir(pid)),
                             "font": fx.find_font(), "sounds": list(SOUNDS),
                             "install_help": "pip install -r requirements-ai.txt (free, runs locally)"})

    async def start_transcribe(request: Request):
        pid = pid_of(request)
        body = await body_model(request, TranscribeBody)
        p = load(pid)
        if available_transcriber() is None:
            return err(409, "Speech-to-text isn't installed. In the backend folder run: "
                            "pip install -r requirements-ai.txt  — then restart ClipForge. (Free, runs on your PC.)")
        ids = body.media_ids or fx.transcript_status(p, store.dir(pid))["missing"] or \
            sorted({c.media_id for t in p.timeline.tracks if t.kind == "audio" for c in t.clips})
        if not ids:
            return err(400, "There's no audio on the timeline to transcribe.")
        running = [j for j in svc.jobs.active_for_project(pid) if j.kind == "transcribe"]
        if running:
            return JSONResponse(running[0].model_dump(), status_code=202)
        return JSONResponse(svc.jobs.submit("transcribe", pid, {"media_ids": ids}).model_dump(), status_code=202)

    async def transcript(request: Request):
        pid = pid_of(request)
        return JSONResponse({"words": fx.edit_words(load(pid), store.dir(pid))[:20000]})

    async def suggest_censor(request: Request):
        pid = pid_of(request)
        body = await body_model(request, CensorBody)
        p = load(pid)
        status = fx.transcript_status(p, store.dir(pid))
        if status["transcribed"] == 0:
            return err(409, "Transcribe the video first — swears are found from the transcript.")
        effs = fx.suggest_censors(p, store.dir(pid), sound=body.sound, level=body.level, custom=body.custom,
                                  allow=body.allow, padding=body.padding)
        return JSONResponse({"effects": [e.model_dump(mode="json") for e in effs],
                             "missing_transcripts": status["missing"]})

    async def suggest_fun(request: Request):
        pid = pid_of(request)
        body = await body_model(request, FunBody)
        p = load(pid)
        if not any(analysis_svc.load_analysis(store.dir(pid), m.id) for m in p.media):
            return err(409, "Analyse the recording first (AI Auto Editor → Analyse, or Transcribe) so reactions can be found.")
        effs = fx.suggest_fun(p, store.dir(pid), body.intensity)
        return JSONResponse({"effects": [e.model_dump(mode="json") for e in effs]})

    async def captions_srt(request: Request):
        pid = pid_of(request)
        p = load(pid)
        chunks = fx.caption_chunks(p, store.dir(pid))
        if not chunks:
            return err(409, "No transcript words in the current edit — transcribe first.")
        return Response(fx.captions_srt(chunks), media_type="application/x-subrip",
                        headers={"content-disposition": f'attachment; filename="{p.id[:8]}-captions.srt"'})

    async def upload_fx_image(request: Request):
        pid = pid_of(request)
        load(pid)
        data = b""
        async for chunk in request.stream():
            data += chunk
            if len(data) > 15 * 1024 * 1024:
                return err(413, "image is larger than 15 MB")
        try:
            from .thumb_store import AssetError, decode_image
            import cv2
            img = decode_image(data)
        except ImportError:
            return err(503, "Image support needs OpenCV: pip install -r requirements.txt")
        except AssetError as exc:
            return err(415, str(exc))
        d = store.dir(pid) / "fx"
        d.mkdir(exist_ok=True)
        aid = new_id()
        ok, buf = cv2.imencode(".png", img)
        (d / f"{aid}.png").write_bytes(buf.tobytes())
        return JSONResponse({"id": aid, "width": int(img.shape[1]), "height": int(img.shape[0])}, status_code=201)

    async def list_fx_images(request: Request):
        pid = pid_of(request)
        load(pid)
        d = store.dir(pid) / "fx"
        return JSONResponse({"images": [f.stem for f in sorted(d.glob("*.png"))] if d.exists() else []})

    async def fx_image(request: Request):
        pid = pid_of(request)
        load(pid)
        try:
            path = safe_join(store.dir(pid), "fx", validate_id(request.path_params["aid"]) + ".png")
        except PathSecurityError:
            return err(404, "not found")
        if not path.is_file():
            return err(404, "not found")
        return FileResponse(path, media_type="image/png")

    async def sound_preview(request: Request):
        name = request.path_params["name"]
        if name not in SOUNDS or name == "mute":
            return err(404, "unknown sound")
        import subprocess as _sp
        n = int(48000 * (0.5 if name in ("beep", "honk", "airhorn") else 0.8))
        proc = _sp.run([S.ffmpeg_bin, "-hide_banner", "-nostdin", "-v", "error",
                        *fx.sound_input_args(name, n, 0.8, 48000), "-f", "wav", "pipe:1"],
                       capture_output=True, timeout=20)
        if proc.returncode != 0 or not proc.stdout:
            return err(500, "could not generate sound")
        return Response(proc.stdout, media_type="audio/wav", headers={"cache-control": "max-age=86400"})

    # -- jobs -------------------------------------------------------------
    async def list_jobs(request: Request):
        pid = request.query_params.get("project_id")
        if pid:
            try:
                validate_id(pid)
            except PathSecurityError:
                return err(400, "invalid project id")
        return JSONResponse({"jobs": [j.model_dump() for j in svc.jobs.list(pid or None)]})

    def job_id(request: Request) -> str:
        try:
            return validate_id(request.path_params["jid"])
        except PathSecurityError:
            raise HTTPException(404, "job not found")

    async def get_job(request: Request):
        j = svc.jobs.get(job_id(request))
        if j is None:
            return err(404, "job not found")
        return JSONResponse(j.model_dump())

    async def cancel_job(request: Request):
        jid = job_id(request)
        if svc.jobs.get(jid) is None:
            return err(404, "job not found")
        return JSONResponse({"cancelling": svc.jobs.cancel(jid)})

    async def retry_job(request: Request):
        try:
            j = svc.jobs.retry(job_id(request))
        except KeyError:
            return err(404, "job not found")
        except ValueError as exc:
            return err(409, str(exc))
        return JSONResponse(j.model_dump(), status_code=202)

    if svc.thumbnails_error is None:
        from .thumb_api import build_thumb_routes
        thumb_routes = build_thumb_routes(svc, load, pid_of, body_model, err)
    else:
        async def thumbs_unavailable(request: Request):
            return err(503, svc.thumbnails_error)
        thumb_routes = [Route("/api/projects/{pid}/thumbnails{rest:path}", thumbs_unavailable,
                              methods=["GET", "POST", "PUT", "DELETE"])]

    P = "/api/projects/{pid}"
    return thumb_routes + [
        Route("/api/health", health),
        Route("/api/system", system),
        Route("/api/maintenance/cleanup", cleanup, methods=["POST"]),
        Route("/api/projects", list_projects),
        Route("/api/projects", create_project, methods=["POST"]),
        Route(P, get_project),
        Route(P, delete_project, methods=["DELETE"]),
        Route(P + "/timeline", save_timeline, methods=["PUT"]),
        Route(P + "/rename", rename_project, methods=["POST"]),
        Route(P + "/duplicate", duplicate_project, methods=["POST"]),
        Route(P + "/media", upload_media, methods=["POST"]),
        Route(P + "/media/{mid}", delete_media, methods=["DELETE"]),
        Route(P + "/media/{mid}/stream", media_stream),
        Route(P + "/media/{mid}/thumbnail", media_thumb),
        Route(P + "/media/{mid}/waveform", media_waveform),
        Route(P + "/exports", list_exports),
        Route(P + "/exports", start_export, methods=["POST"]),
        Route(P + "/exports/{name}", download_export),
        Route(P + "/exports/{name}", delete_export, methods=["DELETE"]),
        Route(P + "/exports/{name}/validate", revalidate_export, methods=["POST"]),
        Route(P + "/autoedit", autoedit_status),
        Route(P + "/autoedit/analyze", start_analysis, methods=["POST"]),
        Route(P + "/autoedit/plan", autoedit_plan, methods=["POST"]),
        Route(P + "/autoedit/apply", autoedit_apply, methods=["POST"]),
        Route(P + "/fx/status", fx_status),
        Route(P + "/transcribe", start_transcribe, methods=["POST"]),
        Route(P + "/transcript", transcript),
        Route(P + "/fx/censor/suggest", suggest_censor, methods=["POST"]),
        Route(P + "/fx/fun/suggest", suggest_fun, methods=["POST"]),
        Route(P + "/captions.srt", captions_srt),
        Route(P + "/fx/images", list_fx_images),
        Route(P + "/fx/images", upload_fx_image, methods=["POST"]),
        Route(P + "/fx/images/{aid}", fx_image),
        Route("/api/sounds/{name}.wav", sound_preview),
        Route("/api/jobs", list_jobs),
        Route("/api/jobs/{jid}", get_job),
        Route("/api/jobs/{jid}/cancel", cancel_job, methods=["POST"]),
        Route("/api/jobs/{jid}/retry", retry_job, methods=["POST"]),
    ]
