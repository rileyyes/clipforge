"""HTTP API (Starlette + Pydantic).

Routes are deliberately thin: they validate input, call services, and shape
responses. See ARCHITECTURE.md for the planned FastAPI migration.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from . import brand as brand_mod
from . import fontlib, reactions
from . import derive as derive_mod
from . import ffmpeg as ff
from . import media as media_svc
from .config import Settings
from .jobs import JobContext, JobManager
from .projects import ProjectNotFound, ProjectStore, RevisionConflict
from . import analysis as analysis_svc
from .autoedit import AutoEditSettings, EDLError, edl_to_timeline, plan as plan_edit
from .render import render_project, validate_export
from .transcription import available_transcriber
from .schema import COLOR_HEX, FONT_ID, SOUNDS, AudioSettings, CaptionSettings, Effect, FaceCam, OutputSettings, Project, Timeline, now_iso
from . import rcache
from .library import Library, LibraryError, project_sound
from .history import HistoryNotFound, HistoryStore, compare as compare_docs, doc_of
from .storage import (atomic_write_json, replace_retry, PathSecurityError, dir_size, display_name, media_extension, new_id,
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
    facecam: Optional[FaceCam] = None  # sent as null: remove the face cam; left out: unchanged


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
        self.jobs.register("ai_rate", self._ai_rate)
        self.jobs.register("make_short", self._make_short)
        self.jobs.register("youtube_upload", self._youtube_upload)
        self.jobs.register("facecam_sync", self._facecam_sync)
        self.jobs.register("facecam_matte", self._facecam_matte)
        self.jobs.register("blur_track", self._blur_track)
        self.jobs.register("voice_setup", self._voice_setup)
        self.jobs.register("voiceover", self._voiceover)
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
        want_proxy = media_svc.needs_proxy(asset) or bool(ctx.job.params.get("proxy"))
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

    def _ai_rate(self, ctx: JobContext) -> dict:
        """Optional local AI: rate transcript chunks (funny / interesting / filler)."""
        from . import language
        pid, mid = ctx.job.project_id, ctx.job.params["media_id"]
        model = language.text_model()
        if model is None:
            raise RuntimeError("No local AI model found. " + language_setup_help())
        pdir = self.store.dir(pid)
        a = analysis_svc.load_analysis(pdir, mid)
        if not a or not a.get("words"):
            raise RuntimeError("This recording has no transcript yet — transcribe it first.")
        ctx.stage(1, 1, f"Rating moments with {model.model}")
        ratings = language.ai_rate(model, a["words"], on_progress=ctx.progress, cancel=ctx.cancel_event)
        if not ratings:
            raise RuntimeError("The AI model didn't return usable ratings — try again, or a different model.")
        a["ai_ratings"], a["ai_model"] = ratings, model.model
        out = analysis_svc.analysis_path(pdir, mid)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(__import__("json").dumps(a), encoding="utf-8")
        replace_retry(tmp, out)
        return {"media_id": mid, "rated": len(ratings), "model": model.model}

    def _make_short(self, ctx: JobContext) -> dict:
        """Vertical 9:16 project from one moment, following the subject."""
        from . import shorts as SH
        pid, prm = ctx.job.project_id, ctx.job.params
        src_project = self.store.load(pid)
        asset = src_project.media_by_id()[prm["media_id"]]
        pdir = self.store.dir(pid)
        start, end = float(prm["start"]), min(float(prm["end"]), asset.duration)
        W, H = 1080, 1920
        follow = {"samples": 0, "faces": 0, "motion": 0, "moves": 0}
        kfs: list[dict] = []
        scale = 1.0
        stacked = (prm.get("facecam_layout") == "stacked"
                   and SH.short_facecam(src_project.model_dump(mode="json"), asset.id, "stacked") is not None)
        if asset.has_video and asset.width and asset.height:
            scale, picture_w = SH.vertical_geometry(asset.width, asset.height, W, H)
            if prm.get("follow", True) and picture_w > W * 1.05 and not stacked:
                ctx.stage(1, 2, "Finding you in the shot")
                samples = SH.sample_track(self.settings.ffmpeg_bin, pdir / "media" / "original" / asset.stored_name,
                                          start, end, asset.width, asset.height,
                                          on_progress=ctx.progress, cancel=ctx.cancel_event)
                path = SH.camera_path(samples, view=W / picture_w)
                kfs = SH.keyframes_for(path, picture_w, W)
                follow = {"samples": len(samples), "faces": sum(s.kind == "face" for s in samples),
                          "motion": sum(s.kind == "motion" for s in samples), "moves": max(0, len(path) - 1)}
        ctx.stage(2, 2, "Creating the Short")
        words = (analysis_svc.load_analysis(pdir, asset.id) or {}).get("words")
        doc = SH.build_short_project(src_project.model_dump(mode="json"), asset.model_dump(mode="json"),
                                     start, end, kfs, scale, prm.get("title", ""),
                                     bool(prm.get("captions", True) and words), new_id,
                                     prm.get("facecam_layout", "corner"))
        existing = sum(1 for x in self.store.list() if x.get("name", "").startswith(f"{src_project.name} — Short"))
        name = (prm.get("title") or "").strip() or f"{src_project.name} — Short {existing + 1}"
        if prm.get("title"):
            name = f"{src_project.name} — Short: {name}"
        new = self.store.create_from(pid, name, doc)
        return {"project_id": new.id, "name": new.name, "follow": follow,
                "facecam": (new.facecam.corner if new.facecam else None),
                "captions": doc["captions"]["enabled"], "duration": round(end - start, 2)}

    def _facecam_sync(self, ctx: JobContext) -> dict:
        """Find how far apart the face cam and the main recording are, by their sound."""
        from . import sync
        pid, prm = ctx.job.project_id, ctx.job.params
        p = self.store.load(pid)
        media = p.media_by_id()
        main, cam = media[prm["main_media_id"]], media[prm["media_id"]]
        orig = self.store.dir(pid) / "media" / "original"
        ctx.stage(1, 2, "Listening to the main recording")
        a = sync.decode(self.settings.ffmpeg_bin, orig / main.stored_name)
        ctx.check_cancel()
        ctx.stage(2, 2, "Listening to the face cam")
        b = sync.decode(self.settings.ffmpeg_bin, orig / cam.stored_name)
        ctx.check_cancel()
        r = sync.find_offset(a, b)
        return {"offset": r.offset, "confidence": r.confidence, "media_id": cam.id, "main_media_id": main.id}

    def _facecam_matte(self, ctx: JobContext) -> dict:
        """Prepare background removal for a face cam recording ahead of exporting."""
        from . import matte
        pid, prm = ctx.job.project_id, ctx.job.params
        asset = self.store.load(pid).media_by_id()[prm["media_id"]]
        ctx.stage(1, 1, "Finding you in every frame")
        path = matte.ensure(self.settings, self.store.dir(pid), asset, ctx.cancel_event, ctx.progress)
        return {"media_id": asset.id, "bytes": path.stat().st_size}

    def _voice_setup(self, ctx: JobContext) -> dict:
        """Download the free offline voice (Piper + one voice model), once."""
        from . import voiceover as VO
        ctx.stage(1, 1, "Downloading the voice")
        return VO.setup(self.settings.workspace, ctx.progress, ctx.cancel_event)  # VoiceError messages are shown as-is

    def _voiceover(self, ctx: JobContext) -> dict:
        """Read a line of text aloud and add it to the project as a sound file."""
        from . import voiceover as VO
        pid, prm = ctx.job.project_id, ctx.job.params
        orig = media_svc.media_dir(self.store.dir(pid), "original")
        mid = new_id()
        dest = orig / f"{mid}.wav"
        ctx.stage(1, 1, "Speaking")
        try:
            VO.speak(self.settings.workspace, prm["text"], dest, prm.get("speaker", "Voice 1"), float(prm.get("speed", 1.0)))
        except VO.VoiceError:
            dest.unlink(missing_ok=True)
            raise
        words = " ".join(prm["text"].split()[:5])
        asset = media_svc.build_asset(self.settings, mid, dest, display_name(f"Voiceover - {words}.wav"))
        h = hashlib.sha256(dest.read_bytes())
        asset.sha256 = h.hexdigest()
        media_svc.mark_read_only(dest)
        self.store.update(pid, lambda d: {**d, "media": d["media"] + [asset.model_dump(mode="json")]})
        return {"media": asset.model_dump(mode="json")}

    def _blur_track(self, ctx: JobContext) -> dict:
        """Follow a blurred area through the clip(s) under it (template matching)."""
        from . import blur as BL
        pid, prm = ctx.job.project_id, ctx.job.params
        p = self.store.load(pid)
        media, out = p.media_by_id(), p.output
        orig = self.store.dir(pid) / "media" / "original"
        box_out = (prm["box"]["x"], prm["box"]["y"], prm["box"]["w"], prm["box"]["h"])
        pts: list[tuple[float, float, float, float, float]] = []   # t, x, y, w, h (output fractions)
        lost = 0
        tpl, st = None, {}
        total = sum(pc["src_end"] - pc["src_start"] for pc in prm["pieces"]) or 1.0
        done = 0.0
        for i, pc in enumerate(prm["pieces"]):
            ctx.check_cancel()
            ctx.stage(1, 1, f"Following it ({i + 1} of {len(prm['pieces'])})")
            a = media[pc["media_id"]]
            rect = BL.picture_rect(a.width, a.height, out.width, out.height, out.fit_mode,
                                   pc.get("scale", 1.0), pc.get("x", 0.0), pc.get("y", 0.0))
            frames = BL.grab(self.settings.ffmpeg_bin, orig / a.stored_name, pc["src_start"], pc["src_end"],
                             320, a.width, a.height)
            if not len(frames):
                continue
            sb = BL.to_source(box_out, rect, out.width, out.height)
            span = pc["src_end"] - pc["src_start"]
            res = BL.track(frames, sb, on_progress=lambda f, d=done, s_=span: ctx.progress(min(1.0, (d + f * s_) / total)),
                           template=tpl, state=st)
            tpl = st.get("template")
            for j, (x, y, w, h, score) in enumerate(res):
                t = pc["t_start"] + (j / BL.TRACK_FPS) / pc.get("speed", 1.0)
                ox, oy, ow, oh = BL.to_output((x, y, w, h), rect, out.width, out.height)
                pts.append((round(t, 3), ox, oy, ow, oh))
                lost += score < 0.35
            box_out = pts[-1][1:]
            done += span
        if not pts:
            raise RuntimeError("Couldn't read the video under the blur.")
        tol = 0.004
        keep = BL.simplify([(t, x + w / 2, y + h / 2) for t, x, y, w, h in pts], tol)
        while len(keep) > BL.MAX_KEYS:
            tol *= 1.6
            keep = BL.simplify([(t, x + w / 2, y + h / 2) for t, x, y, w, h in pts], tol)
        keys = [{"t": pts[i][0], "x": round(pts[i][1], 4), "y": round(pts[i][2], 4),
                 "w": round(pts[i][3], 4), "h": round(pts[i][4], 4)} for i in keep]
        return {"keys": keys, "frames": len(pts), "lost": int(lost)}

    def _youtube_upload(self, ctx: JobContext) -> dict:
        """Upload an export to YouTube with the saved publish draft (resumable)."""
        from . import youtube as YT
        pid, prm = ctx.job.project_id, ctx.job.params
        pdir = self.store.dir(pid)
        video = safe_join(pdir, "exports", prm["export_file"])
        thumb = safe_join(pdir, "thumbnails", "exports", prm["thumbnail_file"]) if prm.get("thumbnail_file") else None
        if thumb is not None and not thumb.is_file():
            thumb = None
        ctx.stage(1, 1, "Uploading to YouTube")
        yt = YT.YouTube(self.settings.workspace)
        res = yt.upload(video, YT.metadata(prm["draft"]), thumb, on_progress=ctx.progress, cancel=ctx.cancel_event)
        log = pdir / "youtube.json"
        hist = __import__("json").loads(log.read_bytes()) if log.exists() else []
        hist.append({**res, "title": prm["draft"].get("title"), "file": prm["export_file"], "at": now_iso()})
        atomic_write_json(log, hist[-50:], keep_backup=False)
        return res

    def _render(self, ctx: JobContext) -> dict:
        pid = ctx.job.project_id
        p = ctx.job.params
        project = self.store.load(pid)
        return render_project(ctx, self.settings, project, self.store.dir(pid),
                              p.get("filename", "export"), p.get("quality", "standard"),
                              p.get("encoder", "auto"))


def language_setup_help() -> str:
    return ("It's optional and free: install Ollama (https://ollama.com), run `ollama pull llama3.1`, and keep "
            "Ollama running — RJClip finds it automatically.")


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
        from . import matte as matte_svc
        d["mattes"] = [m.id for m in p.media if matte_svc.matte_path(store.dir(p.id), m).is_file()]
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
            "render_cache_bytes": rcache.size_of(S.cache_dir),
            "render_cache_limit_bytes": S.render_cache_bytes,
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
            later = pdir / "media" / ".delete-later"
            if later.is_file():  # media removed while Windows still had the file open
                keep = []
                for name in {n.strip() for n in later.read_text(encoding="utf-8").splitlines() if n.strip()}:
                    for sub in ("original", "proxy", "thumbs", "waveforms"):
                        try:
                            f = safe_join(pdir / "media", sub, name)
                        except PathSecurityError:
                            continue
                        if f.is_file():
                            try:
                                if os.name == "nt":
                                    f.chmod(0o600)
                                freed += f.stat().st_size
                                f.unlink()
                            except OSError:
                                keep.append(name)
                if keep:
                    later.write_text("".join(f"{n}\n" for n in keep), encoding="utf-8")
                else:
                    later.unlink(missing_ok=True)
        for t in S.tmp_dir.iterdir():
            freed += t.stat().st_size if t.is_file() else dir_size(t)
            shutil.rmtree(t, ignore_errors=True) if t.is_dir() else t.unlink(missing_ok=True)
        if not any(svc.jobs.active_for_project(p["id"]) for p in store.list() if not p.get("error")):
            freed += rcache.clear(S.cache_dir)  # never pull files from under a running export
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
            if "facecam" in body.model_fields_set:
                data["facecam"] = body.facecam.model_dump(mode="json") if body.facecam else None
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
                     captions=data["captions"], audio=data["audio"], facecam=data.get("facecam"),
                     edit_revision=latest.edit_revision + 1)
            saved = store.save(Project.model_validate(d), expected_revision=latest.revision)
        try:
            HistoryStore(store.dir(pid)).maybe_checkpoint(saved.model_dump(mode="json"))
        except Exception:  # noqa: BLE001 - history must never block saving
            pass
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
    async def refuse_upload(request: Request, status: int, msg: str) -> Response:
        """Turn an upload down, but read (and throw away) a small one first: answering before
        the file has been sent can make the sender see a dropped connection instead of the
        message (seen in tests; browsers can do the same)."""
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) <= 64 * 1024**2:
            try:
                async for _ in request.stream():
                    pass
            except Exception:  # noqa: BLE001 - the client went away: nothing to tell it
                pass
        return err(status, msg)

    async def upload_media(request: Request):
        pid = pid_of(request)
        load(pid)
        filename = request.query_params.get("filename", "")
        try:
            ext = media_extension(filename)
        except PathSecurityError as exc:
            return await refuse_upload(request, 415, str(exc))
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > S.max_upload_bytes:
            return err(413, f"file exceeds the {S.max_upload_bytes // 1024**2} MB upload limit")
        if dir_size(S.workspace) > S.max_workspace_bytes:
            return await refuse_upload(request, 507, "workspace storage quota reached; delete projects or run cleanup")
        du = shutil.disk_usage(S.workspace)
        if declared and declared.isdigit() and int(declared) > du.free - 2 * 1024**3:
            return await refuse_upload(request, 507, "not enough free disk space for this file")

        if not ff.tools_available(S.ffmpeg_bin, S.ffprobe_bin):
            return await refuse_upload(request, 503, ff.MISSING_FFMPEG)
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
            replace_retry(partial, final)
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

    class PreviewBody(BaseModel):
        proxy: bool = False

    class DeriveBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        kind: Literal["freeze", "reverse"]
        t: float = Field(default=0, ge=0, le=86400)                 # freeze: the frame (seconds into the recording)
        seconds: float = Field(default=2.0, ge=0.2, le=derive_mod.FREEZE_MAX)
        start: float = Field(default=0, ge=0, le=86400)             # reverse: the range
        end: float = Field(default=0, ge=0, le=86400)

    # ---------------------------------------------------------------- brand kit (Phase 15)
    def brand_payload() -> dict:
        b = brand_mod.load(S.workspace)
        return {"brand": b.model_dump(mode="json"), "has_logo": bool(b.logo), "has_intro": bool(b.intro), "has_outro": bool(b.outro)}

    async def brand_get(request: Request):
        return JSONResponse(brand_payload())

    async def brand_put(request: Request):
        try:
            data = await request.json()
            cur = brand_mod.load(S.workspace)
            # files are set by uploading them, not here
            new = brand_mod.Brand.model_validate({**data, "logo": cur.logo, "intro": cur.intro, "outro": cur.outro})
        except (ValidationError, ValueError) as exc:
            return err(422, f"invalid brand kit: {exc}")
        brand_mod.save(S.workspace, new)
        return JSONResponse(brand_payload())

    async def brand_file_put(request: Request):
        kind = request.path_params["kind"]
        if kind not in ("logo", "intro", "outro"):
            return err(404, "unknown brand file")
        declared = request.headers.get("content-length")
        limit = brand_mod.LOGO_MAX_BYTES if kind == "logo" else S.max_upload_bytes
        if declared and declared.isdigit() and int(declared) > limit:
            return err(413, "file too large")
        bdir = brand_mod.brand_dir(S.workspace)
        b = brand_mod.load(S.workspace)
        if kind == "logo":
            data = await request.body()
            if len(data) > limit:
                return err(413, "file too large")
            try:
                b.logo = brand_mod.store_logo(S.workspace, data)
            except ValueError as exc:
                return err(415, str(exc))
        else:
            try:
                ext = media_extension(request.query_params.get("filename", ""))
            except PathSecurityError as exc:
                return err(415, str(exc))
            partial = bdir / f"{kind}.upload.partial"
            size = 0
            try:
                with open(partial, "wb") as fh:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > limit:
                            raise HTTPException(413, "file too large")
                        fh.write(chunk)
                try:
                    pr = ff.probe(S.ffprobe_bin, partial)
                except ff.FFmpegError as exc:
                    return err(415, f"Could not read this file: {exc}")
                if not pr.has_video:
                    return err(415, "The intro and outro need to be videos.")
                if pr.duration > 120:
                    return err(422, "Keep the intro/outro under 2 minutes.")
                setattr(b, kind, brand_mod.store_clip(S.workspace, kind, partial, ext))
            finally:
                partial.unlink(missing_ok=True)
        brand_mod.save(S.workspace, b)
        brand_mod.tidy(S.workspace, b)
        return JSONResponse(brand_payload())

    async def brand_file_delete(request: Request):
        kind = request.path_params["kind"]
        if kind not in ("logo", "intro", "outro"):
            return err(404, "unknown brand file")
        b = brand_mod.load(S.workspace)
        setattr(b, kind, None)
        brand_mod.save(S.workspace, b)
        brand_mod.tidy(S.workspace, b)
        return JSONResponse(brand_payload())

    async def brand_logo_get(request: Request):
        b = brand_mod.load(S.workspace)
        f = brand_mod.brand_dir(S.workspace) / b.logo if b.logo else None
        if not f or not f.is_file():
            return err(404, "no logo")
        return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-store"})

    # ---------------------------------------------------------------- fonts, text styles (Phase 18)
    async def fonts_list(request: Request):
        return JSONResponse({"fonts": fontlib.list_fonts(S.workspace)})

    async def fonts_add(request: Request):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > fontlib.MAX_BYTES:
            return await refuse_upload(request, 413, "That font file is too big (20 MB at most).")
        data = b""
        async for chunk in request.stream():
            data += chunk
            if len(data) > fontlib.MAX_BYTES:
                return err(413, "That font file is too big (20 MB at most).")
        try:
            f = fontlib.add(S.workspace, data, request.query_params.get("filename", ""))
        except ValueError as exc:
            return err(415, str(exc))
        return JSONResponse({"font": f, "fonts": fontlib.list_fonts(S.workspace)})

    async def fonts_delete(request: Request):
        if not fontlib.delete(S.workspace, request.path_params["fid"]):
            return err(404, "no such font of yours")
        return JSONResponse({"fonts": fontlib.list_fonts(S.workspace)})

    async def font_file(request: Request):
        r = fontlib.resolve(S.workspace, request.path_params["fid"])
        if not r:
            return err(404, "unknown font")
        path, _ = r
        mt = "font/otf" if path.suffix.lower() == ".otf" else "font/ttf"
        return FileResponse(path, media_type=mt, headers={"Cache-Control": "max-age=3600"})

    class TextStyle(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str = Field(min_length=1, max_length=30)
        font: Optional[str] = Field(default=None, pattern=FONT_ID)
        color: str = Field(default="#ffffff", pattern=COLOR_HEX)
        accent: str = Field(default="#ff5a3c", pattern=COLOR_HEX)
        stroke: Optional[float] = Field(default=None, ge=0, le=24)
        stroke_color: str = Field(default="#000000", pattern=COLOR_HEX)
        shadow: Optional[float] = Field(default=None, ge=0, le=24)
        glow: float = Field(default=0, ge=0, le=40)
        glow_color: str = Field(default="#ffde00", pattern=COLOR_HEX)

    class TextStyles(BaseModel):
        model_config = ConfigDict(extra="forbid")
        styles: list[TextStyle] = Field(default_factory=list, max_length=40)

    def styles_path():
        return S.workspace / "text_styles.json"

    async def text_styles_get(request: Request):
        try:
            data = TextStyles.model_validate(json.loads(styles_path().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            data = TextStyles()
        return JSONResponse(data.model_dump(mode="json"))

    async def text_styles_put(request: Request):
        body = await body_model(request, TextStyles)
        atomic_write_json(styles_path(), body.model_dump(mode="json"))
        return JSONResponse(body.model_dump(mode="json"))

    # ---------------------------------------------------------------- funny moments, talking (Phase 18)
    async def funny_moments(request: Request):
        pid = pid_of(request)
        from starlette.concurrency import run_in_threadpool
        p = load(pid)
        try:
            moments = await run_in_threadpool(reactions.funny_moments, p, S, store.dir(pid))
        except ff.FFmpegError as exc:
            return err(422, f"Couldn't read the audio: {exc}")
        return JSONResponse({"moments": moments})

    async def pacing_motion(request: Request):
        """How much the footage itself moves along the edit (only where the Auto Editor has
        analysed a recording), so the pacing checker doesn't flag busy footage as still."""
        pid = pid_of(request)
        from . import hook
        from .analysis import load_analysis
        p = load(pid)
        D = p.timeline.duration
        analysed = any(load_analysis(store.dir(pid), c.media_id) for t in p.timeline.tracks if t.kind == "video" for c in t.clips)
        if not analysed or D <= 0:
            return JSONResponse({"step": hook.STEP, "motion": None})
        _, motion = hook.edit_curves(p, store.dir(pid), D)
        return JSONResponse({"step": hook.STEP, "motion": [round(float(v), 3) for v in motion]})

    async def media_talk(request: Request):
        pid = pid_of(request)
        from starlette.concurrency import run_in_threadpool
        mid = validate_id(request.path_params["mid"])
        asset = load(pid).media_by_id().get(mid)
        if not asset:
            return err(404, "unknown media")
        try:
            iv = await run_in_threadpool(reactions.talk_for_media, S, store.dir(pid), asset)
        except ff.FFmpegError as exc:
            return err(422, f"Couldn't read the audio: {exc}")
        return JSONResponse({"talk": iv})

    class WatermarkBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        on: bool

    async def project_watermark(request: Request):
        """Put the brand kit's logo on this project's video (or take it off)."""
        pid = pid_of(request)
        body = await body_model(request, WatermarkBody)
        load(pid)
        wm = None
        if body.on:
            b = brand_mod.load(S.workspace)
            src = brand_mod.brand_dir(S.workspace) / b.logo if b.logo else None
            if not src or not src.is_file():
                return err(409, "Add a logo to your brand kit first (Settings → Brand kit).")
            dest = store.dir(pid) / "media" / "brand"
            dest.mkdir(parents=True, exist_ok=True)
            if not (dest / b.logo).exists():
                shutil.copyfile(src, dest / b.logo)
            wm = {"file": b.logo, "corner": b.logo_corner, "size": b.logo_size, "opacity": b.logo_opacity}
        p = store.update(pid, lambda d: {**d, "watermark": wm})
        return JSONResponse({"watermark": p.watermark.model_dump(mode="json") if p.watermark else None})

    async def project_watermark_image(request: Request):
        pid = pid_of(request)
        p = load(pid)
        f = store.dir(pid) / "media" / "brand" / p.watermark.file if p.watermark else None
        if not f or not f.is_file():
            return err(404, "no watermark")
        return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-store"})

    class BrandImportBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        kind: Literal["intro", "outro"]

    async def project_brand_import(request: Request):
        """Copy the brand kit's intro or outro into this project's media (once)."""
        pid = pid_of(request)
        body = await body_model(request, BrandImportBody)
        b = brand_mod.load(S.workspace)
        name = getattr(b, body.kind)
        src = brand_mod.brand_dir(S.workspace) / name if name else None
        if not src or not src.is_file():
            return err(409, f"Add an {body.kind} to your brand kit first (Settings → Brand kit).")
        h = hashlib.sha256()
        with open(src, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        sha = h.hexdigest()
        p = load(pid)
        dup = next((m for m in p.media if m.sha256 == sha), None)
        if dup is not None:
            return JSONResponse({"media": dup.model_dump(mode="json"), "job_id": None})
        mid = new_id()
        orig = media_svc.media_dir(store.dir(pid), "original")
        final = orig / f"{mid}{src.suffix.lower()}"
        shutil.copyfile(src, final)
        try:
            asset = media_svc.build_asset(S, mid, final, f"{'Intro' if body.kind == 'intro' else 'Outro'}{src.suffix.lower()}")
        except ff.FFmpegError as exc:
            final.unlink(missing_ok=True)
            return err(415, str(exc))
        asset.sha256 = sha
        media_svc.mark_read_only(final)
        store.update(pid, lambda d: {**d, "media": d["media"] + [asset.model_dump(mode="json")]})
        job = svc.jobs.submit("derive_media", pid, {"media_id": mid})
        return JSONResponse({"media": asset.model_dump(mode="json"), "job_id": job.id}, status_code=201)

    # ---------------------------------------------------------------- smarter AI (Phase 16)
    async def hook_check(request: Request):
        pid = pid_of(request)
        from . import hook
        return JSONResponse(hook.check(load(pid), store.dir(pid)))

    async def music_plan(request: Request):
        """Which of your songs fits each part of the video (calm talking vs action)."""
        pid = pid_of(request)
        from . import beats as BT, hook
        from starlette.concurrency import run_in_threadpool
        p = load(pid)
        main = {c.media_id for t in p.timeline.tracks if t.role != "music" for c in t.clips}
        cands = [m for m in p.media if m.has_audio and m.id not in main]   # songs: anything with sound not used as the main video
        if not cands:
            return JSONResponse({"sections": hook.sections(p, store.dir(pid)), "songs": [], "plan": [],
                                 "note": "Import a few songs first (Music tab → Import)."})
        songs = []
        for m in cands[:12]:
            cache = store.dir(pid) / "analysis" / f"beats-{m.id}.json"
            res = json.loads(cache.read_bytes()) if cache.exists() else {}
            if "energy" not in res:
                src = store.dir(pid) / "media" / "original" / m.stored_name
                if not src.exists():
                    continue
                res = await run_in_threadpool(lambda s=src: BT.detect(BT.decode(S.ffmpeg_bin, s)))
                res["media_id"] = m.id
                cache.parent.mkdir(exist_ok=True)
                atomic_write_json(cache, res)
            songs.append({"media_id": m.id, "name": m.original_name, "duration": m.duration, "bpm": res["bpm"],
                          "energy": res["energy"], "label": res["label"], "beats": res["beats"]})
        secs = hook.sections(p, store.dir(pid))
        return JSONResponse({"sections": secs, "songs": songs, "plan": hook.music_plan(secs, songs), "note": None})

    async def broll_clips(request: Request):
        pid = pid_of(request)
        from . import brollclips
        return JSONResponse(brollclips.suggest(load(pid), store.dir(pid)))

    async def voice_status(request: Request):
        from . import voiceover as VO
        st = VO.status(S.workspace)
        st["job"] = next((j.id for j in svc.jobs.list(None) if j.kind == "voice_setup" and j.status in ("queued", "running")), None)
        return JSONResponse(st)

    async def voice_setup(request: Request):
        from . import voiceover as VO
        st = VO.status(S.workspace)
        if st["ready"]:
            return JSONResponse({**st, "job_id": None})
        if not st["supported"]:
            return err(422, "The offline voice isn't available for this kind of computer yet.")
        running = next((j for j in svc.jobs.list(None) if j.kind == "voice_setup" and j.status in ("queued", "running")), None)
        job = running or svc.jobs.submit("voice_setup", None, {})
        return JSONResponse({**st, "job_id": job.id}, status_code=202)

    class VoiceBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        text: str = Field(min_length=1, max_length=2000)
        speaker: str = Field(default="Voice 1", max_length=20)
        speed: float = Field(default=1.0, ge=0.5, le=2.0)

    async def voiceover(request: Request):
        from . import voiceover as VO
        pid = pid_of(request)
        body = await body_model(request, VoiceBody)
        load(pid)
        if not body.text.strip():
            return err(422, "Type something to say")
        if body.speaker not in VO.SPEAKERS:
            return err(422, "unknown voice")
        if not VO.status(S.workspace)["ready"]:
            return err(409, "Download the voice first (one time, about 95 MB).")
        job = svc.jobs.submit("voiceover", pid, body.model_dump())
        return JSONResponse({"job_id": job.id}, status_code=202)

    def fmt_clock(t: float) -> str:
        return f"{int(t // 60)}:{t % 60:04.1f}"

    async def derive_media(request: Request):
        """Make a freeze frame or a reversed copy of part of a recording, as a new media item."""
        pid, asset = media_asset(request)
        body = await body_model(request, DeriveBody)
        if not asset.has_video:
            return err(422, "This file has no picture.")
        orig = media_svc.media_dir(store.dir(pid), "original")
        src = orig / asset.stored_name
        if not src.exists():
            return err(409, "This recording is missing; relink it first.")
        if body.kind == "reverse":
            if not (0.2 <= body.end - body.start <= derive_mod.REVERSE_MAX + 1e-6) or body.end > asset.duration + 0.05:
                return err(422, f"Pick between 0.2 and {derive_mod.REVERSE_MAX:.0f} seconds of the recording to reverse.")
        elif body.t > asset.duration:
            return err(422, "That time is past the end of the recording.")
        if dir_size(S.workspace) > S.max_workspace_bytes:
            return err(507, "workspace storage quota reached; delete projects or run cleanup")
        new_mid = new_id()
        final = orig / f"{new_mid}.mp4"
        fps = derive_mod.output_fps(asset.fps)
        stem = Path(asset.original_name).stem[:60]
        if body.kind == "freeze":
            name = f"Freeze {fmt_clock(body.t)} of {stem}.mp4"
            work = lambda: derive_mod.freeze(S.ffmpeg_bin, src, body.t, body.seconds, fps, final)  # noqa: E731
        else:
            name = f"Reversed {fmt_clock(body.start)}-{fmt_clock(body.end)} of {stem}.mp4"
            work = lambda: derive_mod.reverse(S.ffmpeg_bin, src, body.start, body.end, fps, asset.has_audio, final)  # noqa: E731
        try:
            await asyncio.to_thread(work)
            new = media_svc.build_asset(S, new_mid, final, name)
        except ff.FFmpegError as exc:
            final.unlink(missing_ok=True)
            return err(422, f"Couldn't make it: {exc}")
        h = hashlib.sha256()
        with open(final, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        new.sha256 = h.hexdigest()
        media_svc.mark_read_only(final)
        store.update(pid, lambda d: {**d, "media": d["media"] + [new.model_dump(mode="json")]})
        job = svc.jobs.submit("derive_media", pid, {"media_id": new_mid})
        return JSONResponse({"media": new.model_dump(mode="json"), "job_id": job.id}, status_code=201)

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
        # the proxy is used when the browser can't play the original, or when the
        # editor asks for lightweight previews (?proxy=1)
        use_proxy = bool(asset.proxy) and (media_svc.needs_proxy(asset) or request.query_params.get("proxy") == "1")
        path = (d / "proxy" / asset.proxy) if use_proxy else (d / "original" / asset.stored_name)
        if not path.exists():
            return err(404, "media file is missing on disk")
        return FileResponse(path, media_type="video/mp4" if use_proxy else None)

    async def media_previews(request: Request):
        """(Re)build previews: thumbnail, detailed waveform and, if asked, a light proxy."""
        pid, asset = media_asset(request)
        body = await body_model(request, PreviewBody)
        active = [j for j in svc.jobs.active_for_project(pid)
                  if j.kind == "derive_media" and j.params.get("media_id") == asset.id]
        if active:
            return JSONResponse(active[0].model_dump(), status_code=202)
        job = svc.jobs.submit("derive_media", pid, {"media_id": asset.id, "proxy": body.proxy and asset.has_video})
        return JSONResponse(job.model_dump(), status_code=202)

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

    async def relink_media(request: Request):
        """Point a missing media file at a new copy of it (raw file body, like an upload).

        The media keeps its id, so every clip, the face cam and effects keep working. The
        new file must have what the edit uses (picture and/or sound) and be long enough
        for every clip. If it is a different file from the original (other SHA-256), the
        old analysis, transcript, beats and background-removal matte are dropped, since
        they described the old file."""
        pid, asset = media_asset(request)
        p = load(pid)
        orig = media_svc.media_dir(store.dir(pid), "original")
        if (orig / asset.stored_name).exists():
            return await refuse_upload(request, 409, "This file isn't missing, so there is nothing to relink.")
        try:
            ext = media_extension(request.query_params.get("filename", ""))
        except PathSecurityError as exc:
            return await refuse_upload(request, 415, str(exc))
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > S.max_upload_bytes:
            return err(413, f"file exceeds the {S.max_upload_bytes // 1024**2} MB upload limit")
        if dir_size(S.workspace) > S.max_workspace_bytes:
            return await refuse_upload(request, 507, "workspace storage quota reached; delete projects or run cleanup")
        if not ff.tools_available(S.ffmpeg_bin, S.ffprobe_bin):
            return await refuse_upload(request, 503, ff.MISSING_FFMPEG)
        # what the edit needs from this file
        kinds = {t.kind for t in p.timeline.tracks for c in t.clips if c.media_id == asset.id}
        need_until = max((c.source_out for t in p.timeline.tracks for c in t.clips if c.media_id == asset.id), default=0.0)
        if p.facecam and asset.id in (p.facecam.media_id, p.facecam.main_media_id):
            kinds.add("video")

        final = orig / f"{asset.id}{ext}"
        partial = orig / f"{asset.id}{ext}.relink.partial"
        if final.exists():
            return err(409, "A file with this name is already in the project folder.")
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
            replace_retry(partial, final)
            try:
                new = media_svc.build_asset(S, asset.id, final, display_name(request.query_params.get("filename", "")))
            except ff.FFmpegError as exc:
                final.unlink(missing_ok=True)
                return err(415, f"Could not read this file: {exc}")
        finally:
            partial.unlink(missing_ok=True)

        problem = None
        if "video" in kinds and not new.has_video:
            problem = "The edit uses this file's picture, but the new file has no video."
        elif "audio" in kinds and not new.has_audio:
            problem = "The edit uses this file's sound, but the new file has no audio."
        elif new.duration + 0.05 < need_until:
            problem = (f"The new file is too short: it is {new.duration:.1f} s long, but the edit uses it "
                       f"up to {need_until:.1f} s. Pick the full recording.")
        sha = h.hexdigest()
        other = next((m for m in p.media if m.sha256 == sha and m.id != asset.id), None)
        if other is not None:
            problem = f"That file is already in this project as “{other.original_name}”."
        if problem:
            final.unlink(missing_ok=True)
            return err(422, problem)

        same = bool(asset.sha256) and asset.sha256 == sha
        new.sha256 = sha
        new.imported_at = asset.imported_at
        mdir = store.dir(pid) / "media"
        if same and asset.proxy and (mdir / "proxy" / asset.proxy).exists():
            new.proxy = asset.proxy  # same picture: the light preview is still right
        if not same:
            for f in (store.dir(pid) / "analysis" / f"{asset.id}.json",
                      store.dir(pid) / "analysis" / f"beats-{asset.id}.json",
                      mdir / "matte" / f"{asset.id}.mp4"):
                f.unlink(missing_ok=True)
        media_svc.mark_read_only(final)
        data = new.model_dump(mode="json")
        store.update(pid, lambda d: {**d, "media": [data if m["id"] == asset.id else m for m in d["media"]]})
        job = svc.jobs.submit("derive_media", pid, {"media_id": asset.id})
        return JSONResponse({"media": data, "job_id": job.id, "same_file": same,
                             "note": None if same else "This is a different file from the original (or the original's "
                             "fingerprint wasn't known), so its analysis and transcript were reset. Check your cuts still line up."})

    async def delete_media(request: Request):
        pid, asset = media_asset(request)
        p = load(pid)
        if any(c.media_id == asset.id for t in p.timeline.tracks for c in t.clips):
            return err(409, "This media is used on the timeline. Remove its clips first.")
        if p.facecam and asset.id in (p.facecam.media_id, p.facecam.main_media_id):
            return err(409, "This media is used by the face cam. Remove the face cam first (Editor → Face cam).")
        # background jobs still reading this file would block deletion on Windows
        busy = [j for j in svc.jobs.active_for_project(pid)
                if j.params.get("media_id") == asset.id
                and j.kind in ("derive_media", "analyze", "transcribe", "facecam_matte", "facecam_sync")]
        for j in busy:
            svc.jobs.cancel(j.id)
        import asyncio
        for _ in range(100):
            if not any(x.id in {b.id for b in busy} for x in svc.jobs.active_for_project(pid)):
                break
            await asyncio.sleep(0.1)
        store.update(pid, lambda d: {**d, "media": [m for m in d["media"]
                                                     if m["id"] != asset.id]})
        (store.dir(pid) / "analysis" / f"{asset.id}.json").unlink(missing_ok=True)
        (store.dir(pid) / "analysis" / f"beats-{asset.id}.json").unlink(missing_ok=True)
        base = store.dir(pid) / "media"
        stuck = []
        for sub, name in (("original", asset.stored_name), ("proxy", asset.proxy),
                          ("thumbs", asset.thumbnail), ("waveforms", asset.waveform),
                          ("matte", f"{asset.id}.mp4")):
            if name:
                f = base / sub / name
                if f.exists():
                    if os.name == "nt":  # read-only files can't be deleted on Windows
                        f.chmod(0o600)   # (elsewhere it isn't needed: Shorts share these files)
                    for i in range(30):
                        try:
                            f.unlink()
                            break
                        except PermissionError:  # Windows: still open for a moment
                            await asyncio.sleep(0.1)
                    else:
                        stuck.append(f.name)
        if stuck:  # removed from the project; the file itself goes with the next cleanup
            (base / ".delete-later").open("a", encoding="utf-8").write("".join(f"{n}\n" for n in stuck))
        return Response(status_code=204)

    # -- exports ----------------------------------------------------------
    async def start_export(request: Request):
        pid = pid_of(request)
        body = await body_model(request, ExportRequest)
        p = load(pid)
        if body.output is not None and body.output != p.output:
            out = body.output.model_dump(mode="json")
            from .schema import rescale_positions
            p = store.update(pid, lambda d: {**rescale_positions(d, d["output"], out), "output": out})
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
                          "validation": __import__("json").loads(rep.read_bytes())
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
        prev = __import__("json").loads(rep_path.read_bytes()) if rep_path.exists() else {}
        expected = prev.get("duration") or p.timeline.duration
        return JSONResponse(validate_export(S, path, p.output, expected))

    # -- auto editor ------------------------------------------------------
    class AnalyzeBody(BaseModel):
        media_id: str
        transcribe: bool = True

    class PlanBody(BaseModel):
        media_id: str
        settings: AutoEditSettings = Field(default_factory=AutoEditSettings)

    class Extras(BaseModel):
        censor: bool = False
        censor_sound: Literal["beep", "boing", "scratch", "honk", "quack", "mute", "custom"] = "beep"
        censor_sound_asset: Optional[str] = None  # library sound id when censor_sound == "custom"
        fun: Literal["off", "minimal", "balanced", "chaotic"] = "off"
        captions: bool = False
        audio_polish: bool = False
        jump_cuts: Literal["off", "punch", "blend", "whip"] = "off"  # smoother jump cuts
        remove_fillers: bool = False   # "um", "uh"… (needs a transcript)
        remove_retakes: bool = False   # first tries of sentences you said again

    class ApplyBody(PlanBody):
        expected_output: Optional[float] = None  # guards against stale review screens
        extras: Extras = Field(default_factory=Extras)

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
                          "has_transcript": bool(a and a.get("words")),
                          "ai_rated": len((a or {}).get("ai_ratings") or []), "ai_model": (a or {}).get("ai_model"),
                          "transcript_error": (a or {}).get("transcript_error")})
        t = available_transcriber()
        from . import language
        lm = language.text_model()
        return JSONResponse({"media": items, "transcriber": t.name if t else None,
                             "ai": {"model": lm.model, "external": lm.external} if lm else None,
                             "ai_help": None if lm else language_setup_help()})

    # -- Publish: chapters, titles, description, tags ------------------------
    class PublishSuggestBody(BaseModel):
        use_ai: bool = False
        chapters: Literal["auto", "markers"] = "auto"

    def draft_path(pid: str) -> Path:
        return store.dir(pid) / "publish.json"

    async def publish_suggest(request: Request):
        """Chapters, title ideas, description and tags from the final edit's transcript"""
        pid = pid_of(request)
        body = await body_model(request, PublishSuggestBody)
        p = load(pid)
        from . import effects as fx, language, publish as PB
        words = fx.edit_words(p, store.dir(pid))
        if body.chapters == "markers" and not p.timeline.markers:
            return err(409, "There are no markers on the timeline. Press M in the Editor to add one.")
        markers = [m.model_dump() for m in p.timeline.markers] if body.chapters == "markers" else None
        out = PB.suggest(words, p.timeline.duration, p.name, markers)
        if body.use_ai:
            model = language.text_model()
            if model is None:
                return err(409, "No local AI model found. " + language_setup_help())
            if not words:
                return err(409, "Transcribe the video first — the AI writes from what's said.")
            import asyncio
            try:
                out = await asyncio.to_thread(PB.ai_polish, model, words, out)
            except Exception as exc:  # noqa: BLE001 - keep the rule-based result, say why
                out["warnings"].append(f"The local AI didn't answer usefully ({exc}); showing the automatic version.")
            out["ai_model"] = model.model
        out["chapter_problems"] = PB.validate_chapters(out["chapters"], p.timeline.duration)
        return JSONResponse(out)

    async def publish_get(request: Request):
        pid = pid_of(request)
        load(pid)
        from . import publish as PB
        f = draft_path(pid)
        d = PB.PublishDraft.model_validate_json(f.read_bytes()) if f.exists() else PB.PublishDraft()
        return JSONResponse({"draft": d.model_dump(), "categories": PB.CATEGORIES})

    async def publish_put(request: Request):
        pid = pid_of(request)
        p = load(pid)
        from . import publish as PB
        d = await body_model(request, PB.PublishDraft)
        atomic_write_json(draft_path(pid), d.model_dump(), keep_backup=False)
        return JSONResponse({"draft": d.model_dump(),
                             "chapter_problems": PB.validate_chapters([c.model_dump() for c in d.chapters], p.timeline.duration)})

    # -- YouTube ------------------------------------------------------------
    from . import youtube as YT
    yt = YT.YouTube(S.workspace)

    async def ai_status(request: Request):
        """Is a local AI model available (Ollama auto-detected, or configured)?"""
        from . import language
        m = language.text_model()
        return JSONResponse({"model": m.model if m else None, "external": bool(m and m.external),
                             "help": None if m else language_setup_help()})

    async def youtube_status(request: Request):
        return JSONResponse(yt.status())

    async def youtube_client(request: Request):
        """Add your Google OAuth client file (Desktop app JSON)"""
        data = await read_upload(request, 64 * 1024)
        try:
            return JSONResponse({**yt.set_client(data), **yt.status()})
        except YT.YouTubeError as exc:
            return err(422, str(exc))

    async def youtube_client_delete(request: Request):
        yt.disconnect()
        yt.client_file.unlink(missing_ok=True)
        return JSONResponse(yt.status())

    def callback_uri(request: Request) -> str:
        host = request.url.hostname if request.url.hostname in ("127.0.0.1", "localhost") else "127.0.0.1"
        return f"http://{host}:{request.url.port or S.port}/api/youtube/callback"

    async def youtube_connect(request: Request):
        """Start Google sign-in; returns the URL to open"""
        try:
            return JSONResponse({"url": yt.auth_url(callback_uri(request))})
        except YT.YouTubeError as exc:
            return err(409, str(exc))

    async def youtube_callback(request: Request):
        """Google redirects here after sign-in (one-time state check)"""
        from starlette.responses import HTMLResponse
        import html as _html
        q = request.query_params

        def page(title: str, msg: str, ok: bool) -> HTMLResponse:
            return HTMLResponse(
                "<!doctype html><meta charset=utf-8><title>RJClip</title><body style='font:16px system-ui;"
                "max-width:560px;margin:60px auto;text-align:center'>"
                f"<h2>{'✅' if ok else '⚠️'} {_html.escape(title)}</h2><p>{_html.escape(msg)}</p>"
                "<p>You can close this tab and go back to RJClip.</p>", status_code=200 if ok else 400)
        if q.get("error"):
            return page("Not connected", f"Google said: {q.get('error')}.", False)
        try:
            st = yt.finish(q.get("state", ""), q.get("code", ""))
        except YT.YouTubeError as exc:
            return page("Not connected", str(exc), False)
        ch = (st.get("channel") or {}).get("title")
        return page("YouTube connected", f"Uploads will go to {ch}." if ch else "You're connected.", True)

    async def youtube_disconnect(request: Request):
        yt.disconnect()
        return JSONResponse(yt.status())

    class UploadBody(BaseModel):
        confirm: bool = False
        export_file: Optional[str] = Field(default=None, max_length=200)

    async def youtube_upload(request: Request):
        """Upload an export with the saved publish draft (asks for explicit confirmation)"""
        pid = pid_of(request)
        body = await body_model(request, UploadBody)
        load(pid)
        if not body.confirm:
            return err(400, "Uploading publishes to your channel — confirm first (confirm: true).")
        if not yt.status()["connected"]:
            return err(409, "Connect your YouTube account first.")
        from . import publish as PB
        f = draft_path(pid)
        draft = PB.PublishDraft.model_validate_json(f.read_bytes()) if f.exists() else PB.PublishDraft()
        if not draft.title.strip():
            return err(422, "Add a title first.")
        name = body.export_file or draft.export_file
        if not name:
            return err(422, "Choose which export to upload.")
        try:
            video = export_path(pid, name)
        except HTTPException:
            return err(404, "That export doesn't exist.")
        if draft.thumbnail_file:
            try:
                safe_join(store.dir(pid), "thumbnails", "exports", draft.thumbnail_file)
            except PathSecurityError:
                return err(422, "Invalid thumbnail file.")
        active = [j for j in svc.jobs.active_for_project(pid) if j.kind == "youtube_upload"]
        if active:
            return err(409, "An upload for this project is already running.")
        job = svc.jobs.submit("youtube_upload", pid, {"export_file": video.name, "thumbnail_file": draft.thumbnail_file,
                                                      "draft": draft.model_dump()})
        return JSONResponse(job.model_dump(), status_code=202)

    async def youtube_history(request: Request):
        pid = pid_of(request)
        load(pid)
        log = store.dir(pid) / "youtube.json"
        return JSONResponse({"uploads": __import__("json").loads(log.read_bytes()) if log.exists() else []})

    # -- Shorts -------------------------------------------------------------
    class ShortSuggestBody(BaseModel):
        media_id: str
        count: int = Field(default=5, ge=1, le=20)
        min_seconds: float = Field(default=15, ge=3, le=170)
        max_seconds: float = Field(default=60, ge=5, le=180)
        style: Literal["balanced", "excitement", "information", "reactions", "action", "humor", "story"] = "balanced"

    class ShortBody(BaseModel):
        media_id: str
        start: float = Field(ge=0)
        end: float = Field(gt=0)
        title: str = Field(default="", max_length=80)
        captions: bool = True
        follow: bool = True
        facecam_layout: Literal["corner", "stacked", "none"] = "corner"

    async def shorts_suggest(request: Request):
        """Best moments for vertical Shorts (needs the recording analysed)"""
        pid = pid_of(request)
        body = await body_model(request, ShortSuggestBody)
        p = load(pid)
        if body.media_id not in p.media_by_id():
            return err(404, "media not found")
        a = analysis_svc.load_analysis(store.dir(pid), body.media_id)
        if a is None:
            return err(409, "Analyse this recording first (AI Auto Editor → Analyse).")
        from . import shorts as SH
        lo, hi = min(body.min_seconds, body.max_seconds), max(body.min_seconds, body.max_seconds)
        return JSONResponse({"suggestions": SH.suggest(a, body.count, lo, hi, body.style),
                             "transcript": bool(a.get("words")), "ai_rated": bool(a.get("ai_ratings"))})

    async def shorts_make(request: Request):
        """Make a vertical Short project from one moment (background job)"""
        pid = pid_of(request)
        body = await body_model(request, ShortBody)
        p = load(pid)
        m = p.media_by_id().get(body.media_id)
        if m is None:
            return err(404, "media not found")
        if not (0 <= body.start < body.end <= m.duration + 0.01) or not (3 <= body.end - body.start <= 180):
            return err(422, "A Short must be 3 s to 3 min long and inside the recording.")
        job = svc.jobs.submit("make_short", pid, body.model_dump())
        return JSONResponse(job.model_dump(), status_code=202)

    # -- phase 9: face cam ---------------------------------------------------
    class CamMediaBody(BaseModel):
        media_id: str
        main_media_id: Optional[str] = None
        shape: Literal["rect", "rounded", "circle"] = "rounded"

    def _cam_media(p: Project, body: "CamMediaBody"):
        m = p.media_by_id().get(body.media_id)
        if m is None:
            raise HTTPException(404, "media not found")
        return m

    async def facecam_sync(request: Request):
        """Line the face cam up with the main recording by their sound (background job)"""
        pid = pid_of(request)
        body = await body_model(request, CamMediaBody)
        p = load(pid)
        cam = _cam_media(p, body)
        main = p.media_by_id().get(body.main_media_id or "")
        if main is None:
            return err(404, "main recording not found")
        if not (cam.has_audio and main.has_audio):
            return err(409, "Both recordings need sound to be lined up automatically. Set the offset by hand instead.")
        job = svc.jobs.submit("facecam_sync", pid, {"media_id": cam.id, "main_media_id": main.id})
        return JSONResponse(job.model_dump(), status_code=202)

    async def facecam_face_crop(request: Request):
        """Suggest a crop of the face cam around your face (head and shoulders)"""
        pid = pid_of(request)
        body = await body_model(request, CamMediaBody)
        p = load(pid)
        cam = _cam_media(p, body)
        if not (cam.has_video and cam.width and cam.height):
            return err(409, "The face cam needs a video picture.")
        from . import sync
        from starlette.concurrency import run_in_threadpool
        src = store.dir(pid) / "media" / "original" / cam.stored_name
        res = await run_in_threadpool(sync.face_crop, S.ffmpeg_bin, src, cam.duration, cam.width, cam.height,
                                      1.0 if body.shape == "circle" else 4 / 3)
        if res is None:
            return err(422, "Couldn't find a face in the face cam. Crop it by hand with the sliders.")
        crop, info = res
        return JSONResponse({"crop": crop.model_dump(), **info})

    async def facecam_matte(request: Request):
        """Prepare background removal for the face cam now, so exports start faster"""
        pid = pid_of(request)
        body = await body_model(request, CamMediaBody)
        p = load(pid)
        cam = _cam_media(p, body)
        from . import matte
        if not matte.available():
            return err(409, "Background removal isn't available in this installation.")
        running = [j for j in svc.jobs.active_for_project(pid)
                   if j.kind == "facecam_matte" and j.params.get("media_id") == cam.id]
        if running:
            return JSONResponse(running[0].model_dump(), status_code=202)
        job = svc.jobs.submit("facecam_matte", pid, {"media_id": cam.id})
        return JSONResponse(job.model_dump(), status_code=202)

    # -- phase 10: privacy blur ------------------------------------------------
    class BlurPiece(BaseModel):
        media_id: str
        src_start: float = Field(ge=0)
        src_end: float = Field(gt=0)
        speed: float = Field(default=1.0, ge=0.25, le=4)
        t_start: float = Field(ge=0)
        scale: float = Field(default=1.0, gt=0.01, le=10)
        x: float = 0.0
        y: float = 0.0

    class BlurBox(BaseModel):
        x: float = Field(ge=-0.5, le=1)
        y: float = Field(ge=-0.5, le=1)
        w: float = Field(gt=0, le=1)
        h: float = Field(gt=0, le=1)

    class BlurTrackBody(BaseModel):
        pieces: list[BlurPiece] = Field(min_length=1, max_length=50)
        box: BlurBox

    async def blur_track(request: Request):
        """Follow a blurred area as it moves (background job; returns keys)"""
        pid = pid_of(request)
        body = await body_model(request, BlurTrackBody)
        p = load(pid)
        media = p.media_by_id()
        for pc in body.pieces:
            m = media.get(pc.media_id)
            if m is None or not m.has_video or not m.width:
                return err(404, "The clip under the blur has no picture to follow.")
            if pc.src_end <= pc.src_start or pc.src_end > m.duration + 0.05:
                return err(422, "That part of the clip doesn't exist.")
        if sum(pc.src_end - pc.src_start for pc in body.pieces) > 20 * 60:
            return err(422, "Track at most 20 minutes at a time.")
        job = svc.jobs.submit("blur_track", pid, body.model_dump())
        return JSONResponse(job.model_dump(), status_code=202)

    class BlurFacesBody(BaseModel):
        media_id: str
        time: float = Field(ge=0)
        scale: float = Field(default=1.0, gt=0.01, le=10)
        x: float = 0.0
        y: float = 0.0

    async def blur_faces(request: Request):
        """Faces in one frame of a clip, as boxes on the output frame (for one-click face blur)"""
        pid = pid_of(request)
        body = await body_model(request, BlurFacesBody)
        p = load(pid)
        m = p.media_by_id().get(body.media_id)
        if m is None or not m.has_video or not m.width:
            return err(404, "media not found")
        from . import blur as BL
        from .shorts import _detector
        from starlette.concurrency import run_in_threadpool
        det = _detector()
        if det is None:
            return err(409, "Face detection isn't available in this installation.")
        src = store.dir(pid) / "media" / "original" / m.stored_name
        sw = 640
        sh = max(2, int(round(m.height * sw / m.width / 2)) * 2)

        def grab():
            raw = subprocess.run([S.ffmpeg_bin, "-v", "error", *ff.untrusted_input_args(src, seek=min(body.time, m.duration - 0.05)),
                                  "-frames:v", "1", "-vf", f"scale={sw}:{sh}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                                 capture_output=True, timeout=60).stdout
            import numpy as np
            return det(np.frombuffer(raw, np.uint8).reshape(sh, sw)) if len(raw) == sw * sh else []
        faces = await run_in_threadpool(grab)
        out = p.output
        rect = BL.picture_rect(m.width, m.height, out.width, out.height, out.fit_mode, body.scale, body.x, body.y)
        boxes = []
        for (fx_, fy, fw, fh) in faces:
            pad = 0.25  # cover hair and chin too
            sx, sy, sw_, sh_ = (fx_ - fw * pad) / sw, (fy - fh * pad) / sh, fw * (1 + 2 * pad) / sw, fh * (1 + 2 * pad) / sh
            x, y, w, h = BL.to_output((sx, sy, sw_, sh_), rect, out.width, out.height)
            boxes.append({"x": round(x, 4), "y": round(y, 4), "w": round(min(w, 1), 4), "h": round(min(h, 1), 4)})
        return JSONResponse({"faces": boxes})

    # -- phase 10: music beats ------------------------------------------------
    class BeatsBody(BaseModel):
        media_id: str

    async def beats(request: Request):
        """Tempo and beat times (source seconds) of a music file, for cutting on the beat"""
        pid = pid_of(request)
        body = await body_model(request, BeatsBody)
        p = load(pid)
        m = p.media_by_id().get(body.media_id)
        if m is None or not m.has_audio:
            return err(404, "That file has no sound.")
        cache = store.dir(pid) / "analysis" / f"beats-{m.id}.json"
        if cache.exists():
            old = json.loads(cache.read_bytes())
            if "energy" in old:  # older caches lack the song's energy: work it out again
                return JSONResponse(old)
        from . import beats as BT
        from starlette.concurrency import run_in_threadpool
        src = store.dir(pid) / "media" / "original" / m.stored_name
        res = await run_in_threadpool(lambda: BT.detect(BT.decode(S.ffmpeg_bin, src)))
        res["media_id"] = m.id
        cache.parent.mkdir(exist_ok=True)
        atomic_write_json(cache, res)
        return JSONResponse(res)

    async def start_ai_rate(request: Request):
        pid = pid_of(request)
        body = await body_model(request, AnalyzeBody)
        p = load(pid)
        if body.media_id not in p.media_by_id():
            return err(404, "media not found")
        from . import language
        if language.text_model() is None:
            return err(409, "No local AI model found. " + language_setup_help())
        a = analysis_svc.load_analysis(store.dir(pid), body.media_id)
        if not a or not a.get("words"):
            return err(409, "Transcribe this recording first — the AI judges what's said.")
        job = svc.jobs.submit("ai_rate", pid, {"media_id": body.media_id})
        return JSONResponse(job.model_dump(), status_code=202)

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
        if any(t.clips for t in p.timeline.tracks):
            HistoryStore(store.dir(pid)).snapshot(p.model_dump(mode="json"), "Before AI edit", "before_ai")

        segments = result["segments"]
        clean_notes: list[dict] = []
        ex = body.extras
        if ex.remove_fillers or ex.remove_retakes:
            from . import cleanup
            words = (analysis_svc.load_analysis(store.dir(pid), asset.id) or {}).get("words") or []
            if not words:
                for on, step in ((ex.remove_fillers, "Remove filler words"), (ex.remove_retakes, "Remove retakes")):
                    if on:
                        clean_notes.append({"step": step, "ok": False, "detail": "skipped — no transcript yet"})
            else:
                found = cleanup.find(words)
                kept = [(a["source_in"], a["source_out"]) for a in segments]
                inside = lambda c: any(x <= c["start"] and c["end"] <= y for x, y in kept)  # noqa: E731
                for on, kind, step in ((ex.remove_fillers, "filler", "Remove filler words"),
                                       (ex.remove_retakes, "retake", "Remove retakes")):
                    if on:
                        cuts = [c for c in found if c["kind"] == kind and inside(c)]
                        segments = cleanup.subtract(segments, [(c["start"], c["end"]) for c in cuts])
                        clean_notes.append({"step": step, "ok": True, "detail": f"{len(cuts)} removed"})

        def apply(d: dict) -> dict:
            d = edl_to_timeline(d, asset.model_dump(mode="json"), segments, new_id)
            d["edit_revision"] = d.get("edit_revision", 0) + 1
            return d
        try:
            saved = store.update(pid, apply)
        except (EDLError, ValidationError) as exc:
            return err(422, f"Generated edit failed validation: {exc}")
        rest = body.extras.model_copy(update={"remove_fillers": False, "remove_retakes": False})
        notes = clean_notes + (apply_extras(pid, saved, rest) if rest != Extras() else [])
        if notes:
            saved = store.load(pid)
        return JSONResponse({"project": project_payload(saved), "plan": result, "extras": notes})

    def apply_extras(pid: str, project: Project, ex) -> list[dict]:
        """Run the Phase 4 tools on a fresh AI edit in one go; report what happened."""
        from . import effects as fx
        pdir = store.dir(pid)
        notes: list[dict] = []
        has_words = fx.transcript_status(project, pdir)["transcribed"] > 0
        no_words = ("skipped — no transcript yet (transcribe in Editor → Effects, then run again)"
                    if available_transcriber() else
                    "skipped — no transcript (install the free transcriber, then re-analyse)")
        # re-running replaces earlier automatic results of the same kind instead of stacking them
        drop: set[str] = set()
        if ex.censor and has_words:
            drop.add("censor")
        if ex.fun != "off":
            drop |= {"zoom", "shake", "flash", "text", "sfx"}
        effects = [e for e in project.effects if not (e.origin == "auto" and e.kind in drop)]
        if ex.censor:
            if has_words:
                asset = use_library_sound(pdir, ex.censor_sound, ex.censor_sound_asset)
                found = fx.suggest_censors(project, pdir, sound=ex.censor_sound if asset else
                                           ("beep" if ex.censor_sound == "custom" else ex.censor_sound),
                                           sound_asset=asset)
                effects += found
                notes.append({"step": "Bleep swears", "ok": True, "detail": f"{len(found)} bleep(s) added"})
            else:
                notes.append({"step": "Bleep swears", "ok": False, "detail": no_words})
        if ex.fun != "off":
            tmp = project.model_copy(update={"effects": effects})
            fun = fx.suggest_fun(tmp, pdir, ex.fun)
            effects += fun
            notes.append({"step": "Comedy edits", "ok": True, "detail": f"{len(fun)} effect(s) on reactions"})
        caps = project.captions.model_dump()
        if ex.captions:
            if has_words:
                caps["enabled"] = True
                notes.append({"step": "Captions", "ok": True, "detail": "turned on"})
            else:
                notes.append({"step": "Captions", "ok": False, "detail": no_words})
        audio = project.audio.model_dump()
        if ex.audio_polish:
            audio.update(normalize=True, enhance_voice=True)
            notes.append({"step": "Audio polish", "ok": True, "detail": "loudness to -14 LUFS + voice enhance"})
        timeline = project.timeline.model_dump(mode="json")
        if ex.jump_cuts != "off":
            from . import jumpcuts
            timeline, n = jumpcuts.smooth(timeline, ex.jump_cuts)
            how = {"punch": "zoom punch-ins", "blend": "quick blends", "whip": "whip pans"}[ex.jump_cuts]
            notes.append({"step": "Smoother jump cuts", "ok": True, "detail": f"{n} jump cut(s) smoothed with {how}"})
        eff_json = [e.model_dump(mode="json") for e in effects]
        store.update(pid, lambda d: {**d, "effects": eff_json, "captions": caps, "audio": audio,
                                     **({"timeline": timeline} if ex.jump_cuts != "off" else {}),
                                     "edit_revision": d.get("edit_revision", 0) + 1})
        return notes

    # -- phase 4: transcription, effects, captions ------------------------
    from . import effects as fx

    class TranscribeBody(BaseModel):
        media_ids: Optional[list[str]] = None

    class CensorBody(BaseModel):
        sound: Literal["beep", "boing", "scratch", "honk", "quack", "mute", "custom"] = "beep"
        sound_asset: Optional[str] = None  # library sound id when sound == "custom"
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
                            "pip install -r requirements-ai.txt  — then restart RJClip. (Free, runs on your PC.)")
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

    async def words(request: Request):
        """Transcript words of every recording in the project, by media id (source seconds)"""
        pid = pid_of(request)
        p = load(pid)
        out = {}
        for m in p.media:
            w = (analysis_svc.load_analysis(store.dir(pid), m.id) or {}).get("words")
            if w:
                out[m.id] = [{"text": x["text"], "start": x["start"], "end": x["end"], "p": x.get("p", 1.0),
                              **({"fixed": True} if x.get("fixed") else {})} for x in w]
        return JSONResponse({"media": out})

    class WordFixBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        media_id: str = Field(pattern=r"^[0-9a-f]{32}$")
        start: float = Field(ge=0, le=86400)
        text: str = Field(min_length=1, max_length=60)

        @field_validator("text")
        @classmethod
        def _one_word(cls, v: str) -> str:
            v = v.strip()
            if not v:
                raise ValueError("type the word (to remove a word, cut it in the Script tab instead)")
            if any(ch in v for ch in "\r\n\t") or any(ord(ch) < 32 for ch in v):
                raise ValueError("one line only")
            return v

    async def fix_word(request: Request):
        """Fix a misheard transcript word (its text only; timing stays)."""
        pid = pid_of(request)
        body = await body_model(request, WordFixBody)
        p = load(pid)
        if not any(m.id == body.media_id for m in p.media):
            return err(404, "media not found")
        busy = [j for j in svc.jobs.active_for_project(pid) if j.kind in ("transcribe", "analyze")]
        if busy:
            return err(409, "Wait for the transcription to finish, then fix the word.")
        try:
            w = analysis_svc.fix_word(store.dir(pid), body.media_id, body.start, body.text)
        except LookupError as exc:
            return err(404, str(exc))
        return JSONResponse({"word": w})

    async def suggest_censor(request: Request):
        pid = pid_of(request)
        body = await body_model(request, CensorBody)
        p = load(pid)
        status = fx.transcript_status(p, store.dir(pid))
        if status["transcribed"] == 0:
            return err(409, "Transcribe the video first — swears are found from the transcript.")
        asset = use_library_sound(store.dir(pid), body.sound, body.sound_asset)
        if body.sound == "custom" and asset is None:
            return err(404, "That sound isn't in your library any more.")
        effs = fx.suggest_censors(p, store.dir(pid), sound=body.sound, level=body.level, custom=body.custom,
                                  allow=body.allow, padding=body.padding, sound_asset=asset)
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

    # -- My library (your own sounds & images, shared by all projects) -----
    lib = Library(S)

    def use_library_sound(pdir: Path, sound: str, asset: Optional[str]) -> Optional[str]:
        """Copy a library sound into the project; returns its id (None if not custom/missing)."""
        if sound != "custom" or not asset:
            return None
        try:
            lib.copy_into_project("sound", asset, pdir)
        except (KeyError, PathSecurityError):
            try:  # already copied into this project earlier (library item since deleted)
                return asset if project_sound(pdir, asset).is_file() else None
            except PathSecurityError:
                return None
        return asset

    def lib_kind(request: Request) -> str:
        k = request.path_params["kind"]
        if k not in ("sounds", "images"):
            raise HTTPException(404, "not found")
        return k[:-1]

    def lib_id(request: Request) -> str:
        try:
            return validate_id(request.path_params["iid"])
        except PathSecurityError:
            raise HTTPException(404, "not found")

    async def read_upload(request: Request, limit: int) -> bytes:
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > limit:
                raise HTTPException(413, f"file is larger than {limit // (1024 * 1024)} MB")
        return bytes(data)

    async def library_list(request: Request):
        return JSONResponse(lib.list())

    async def library_add(request: Request):
        kind = lib_kind(request)
        from . import library as L
        name = request.query_params.get("name", "")
        data = await read_upload(request, L.MAX_SOUND_UPLOAD if kind == "sound" else L.MAX_IMAGE_UPLOAD)
        try:
            if kind == "sound":
                item = lib.add_sound(data, name, recorded=request.query_params.get("recorded") == "1")
            else:
                item = lib.add_image(data, name)
        except ImportError:
            return err(503, "Image support needs OpenCV: pip install -r requirements.txt")
        except ff.FFmpegError as exc:
            return err(503, str(exc))
        except LibraryError as exc:
            return err(415 if "readable" in str(exc) or "image" in str(exc).lower() else 422, str(exc))
        return JSONResponse(item.model_dump(), status_code=201)

    class LibRename(BaseModel):
        name: Optional[str] = Field(default=None, min_length=1, max_length=60)
        tags: Optional[list[str]] = Field(default=None, max_length=30)

    async def library_rename(request: Request):
        """Rename a library item and/or set its keywords"""
        kind, iid = lib_kind(request), lib_id(request)
        body = await body_model(request, LibRename)
        try:
            return JSONResponse(lib.rename(kind, iid, body.name, body.tags).model_dump())
        except KeyError:
            return err(404, "not found")

    async def library_delete(request: Request):
        kind, iid = lib_kind(request), lib_id(request)
        try:
            lib.delete(kind, iid)
        except KeyError:
            return err(404, "not found")
        return Response(status_code=204)

    async def library_file(request: Request):
        kind, iid = lib_kind(request), lib_id(request)
        try:
            path = lib.file(kind, iid)
        except KeyError:
            return err(404, "not found")
        return FileResponse(path, media_type="audio/wav" if kind == "sound" else "image/png")

    class UseBody(BaseModel):
        kind: Literal["sound", "image"]
        id: str

    async def library_use(request: Request):
        """Copy a library item into this project so effects can use it (idempotent)."""
        pid = pid_of(request)
        load(pid)
        body = await body_model(request, UseBody)
        try:
            lib.copy_into_project(body.kind, validate_id(body.id), store.dir(pid))
            item = lib.get(body.kind, body.id)
        except (KeyError, PathSecurityError):
            return err(404, "That item isn't in your library.")
        return JSONResponse(item.model_dump())

    async def broll_suggest(request: Request):
        """Where your own library sounds/images fit: words you say + big reactions"""
        pid = pid_of(request)
        p = load(pid)
        from . import broll
        items = lib.list()
        allitems = items["sounds"] + items["images"]
        if not allitems:
            return JSONResponse({"suggestions": [], "note": "Your library is empty — record or import sounds and images first."})
        return JSONResponse({"suggestions": broll.suggest(p, store.dir(pid), allitems)})

    async def project_sound_file(request: Request):
        pid = pid_of(request)
        load(pid)
        try:
            path = project_sound(store.dir(pid), request.path_params["sid"])
        except PathSecurityError:
            return err(404, "not found")
        if not path.is_file():
            return err(404, "not found")
        return FileResponse(path, media_type="audio/wav")

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

    # -- version history ----------------------------------------------------
    class SnapBody(BaseModel):
        label: str = Field(default="", max_length=80)

    def sid_of(request: Request) -> str:
        try:
            return validate_id(request.path_params["sid"])
        except PathSecurityError:
            raise HTTPException(404, "version not found")

    async def history_list(request: Request):
        pid = pid_of(request)
        load(pid)
        return JSONResponse({"versions": HistoryStore(store.dir(pid)).list()})

    async def history_create(request: Request):
        pid = pid_of(request)
        body = await body_model(request, SnapBody)
        p = load(pid)
        try:
            meta = HistoryStore(store.dir(pid)).snapshot(p.model_dump(mode="json"), body.label or "Saved version")
        except ValueError as exc:
            return err(409, str(exc))
        return JSONResponse(meta.model_dump(), status_code=201)

    async def history_rename(request: Request):
        pid = pid_of(request)
        load(pid)
        body = await body_model(request, SnapBody)
        try:
            return JSONResponse(HistoryStore(store.dir(pid)).rename(sid_of(request), body.label))
        except HistoryNotFound:
            return err(404, "version not found")

    async def history_delete(request: Request):
        pid = pid_of(request)
        load(pid)
        try:
            HistoryStore(store.dir(pid)).delete(sid_of(request))
        except HistoryNotFound:
            return err(404, "version not found")
        return Response(status_code=204)

    async def history_restore(request: Request):
        pid = pid_of(request)
        sid = sid_of(request)
        hs = HistoryStore(store.dir(pid))
        try:
            snap = hs.get(sid)
        except HistoryNotFound:
            return err(404, "version not found")
        cur = load(pid)
        media_ids = {m.id for m in cur.media}
        used = {c["media_id"] for t in snap["doc"]["timeline"]["tracks"] for c in t["clips"]} | \
            {e["media_id"] for e in snap["doc"].get("effects") or []} | \
            ({snap["doc"]["facecam"]["media_id"], snap["doc"]["facecam"]["main_media_id"]}
             if snap["doc"].get("facecam") else set())
        if used - media_ids:
            return err(409, "This version uses media that has since been removed from the project, so it "
                            "can't be restored.")
        hs.snapshot(cur.model_dump(mode="json"), f"Before restoring “{snap['label']}”"[:80], "before_restore")

        def apply(d: dict) -> dict:
            for k, v in snap["doc"].items():
                if v is not None or k == "facecam":  # versions saved with a face cam key restore "none" too
                    d[k] = v
            d["edit_revision"] = d.get("edit_revision", 0) + 1
            return d
        try:
            saved = store.update(pid, apply)
        except ValidationError as exc:
            return pydantic_error(exc)
        return JSONResponse(project_payload(saved))

    async def history_compare(request: Request):
        pid = pid_of(request)
        p = load(pid)
        hs = HistoryStore(store.dir(pid))

        def resolve(key: str):
            if key == "current":
                return doc_of(p.model_dump(mode="json")), "Current edit"
            try:
                validate_id(key)
                snap = hs.get(key)
            except (PathSecurityError, HistoryNotFound):
                raise HTTPException(404, "version not found")
            cur = doc_of(p.model_dump(mode="json"))
            doc = {k: (v if v is not None else cur[k]) for k, v in snap["doc"].items()}
            return doc, snap["label"]
        a, la = resolve(request.query_params.get("a", "current"))
        b, lb = resolve(request.query_params.get("b", "current"))
        media = {m.id: m.model_dump(mode="json") for m in p.media}
        return JSONResponse({**compare_docs(a, b, media), "a_label": la, "b_label": lb})

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
        Route(P + "/media/{mid}/previews", media_previews, methods=["POST"]),
        Route(P + "/media/{mid}/relink", relink_media, methods=["POST"]),
        Route(P + "/media/{mid}/derive", derive_media, methods=["POST"]),
        Route(P + "/brand/watermark", project_watermark, methods=["POST"]),
        Route(P + "/hook", hook_check, methods=["GET"]),
        Route(P + "/broll/clips", broll_clips, methods=["GET"]),
        Route(P + "/music/plan", music_plan, methods=["GET"]),
        Route(P + "/voiceover", voiceover, methods=["POST"]),
        Route("/api/voice", voice_status, methods=["GET"]),
        Route("/api/voice/setup", voice_setup, methods=["POST"]),
        Route(P + "/brand/watermark.png", project_watermark_image, methods=["GET"]),
        Route(P + "/brand/import", project_brand_import, methods=["POST"]),
        Route("/api/fonts", fonts_list, methods=["GET"]),
        Route("/api/fonts", fonts_add, methods=["POST"]),
        Route("/api/fonts/{fid}", fonts_delete, methods=["DELETE"]),
        Route("/api/fonts/{fid}/file", font_file, methods=["GET"]),
        Route("/api/text-styles", text_styles_get, methods=["GET"]),
        Route("/api/text-styles", text_styles_put, methods=["PUT"]),
        Route(P + "/moments", funny_moments, methods=["GET"]),
        Route(P + "/pacing/motion", pacing_motion, methods=["GET"]),
        Route(P + "/media/{mid}/talk", media_talk, methods=["GET"]),
        Route("/api/brand", brand_get, methods=["GET"]),
        Route("/api/brand", brand_put, methods=["PUT"]),
        Route("/api/brand/logo", brand_logo_get, methods=["GET"]),
        Route("/api/brand/files/{kind}", brand_file_put, methods=["POST"]),
        Route("/api/brand/files/{kind}", brand_file_delete, methods=["DELETE"]),
        Route(P + "/media/{mid}/thumbnail", media_thumb),
        Route(P + "/media/{mid}/waveform", media_waveform),
        Route(P + "/exports", list_exports),
        Route(P + "/exports", start_export, methods=["POST"]),
        Route(P + "/exports/{name}", download_export),
        Route(P + "/exports/{name}", delete_export, methods=["DELETE"]),
        Route(P + "/exports/{name}/validate", revalidate_export, methods=["POST"]),
        Route(P + "/autoedit", autoedit_status),
        Route(P + "/autoedit/analyze", start_analysis, methods=["POST"]),
        Route(P + "/autoedit/ai-rate", start_ai_rate, methods=["POST"]),
        Route(P + "/shorts/suggest", shorts_suggest, methods=["POST"]),
        Route(P + "/facecam/sync", facecam_sync, methods=["POST"]),
        Route(P + "/facecam/face-crop", facecam_face_crop, methods=["POST"]),
        Route(P + "/facecam/matte", facecam_matte, methods=["POST"]),
        Route(P + "/blur/track", blur_track, methods=["POST"]),
        Route(P + "/blur/faces", blur_faces, methods=["POST"]),
        Route(P + "/beats", beats, methods=["POST"]),
        Route(P + "/shorts", shorts_make, methods=["POST"]),
        Route(P + "/publish/suggest", publish_suggest, methods=["POST"]),
        Route(P + "/youtube/upload", youtube_upload, methods=["POST"]),
        Route(P + "/youtube/uploads", youtube_history),
        Route("/api/youtube/status", youtube_status),
        Route("/api/ai/status", ai_status),
        Route("/api/youtube/client", youtube_client, methods=["POST"]),
        Route("/api/youtube/client", youtube_client_delete, methods=["DELETE"]),
        Route("/api/youtube/connect", youtube_connect, methods=["POST"]),
        Route("/api/youtube/callback", youtube_callback),
        Route("/api/youtube/disconnect", youtube_disconnect, methods=["POST"]),
        Route(P + "/publish", publish_get),
        Route(P + "/publish", publish_put, methods=["PUT"]),
        Route(P + "/autoedit/plan", autoedit_plan, methods=["POST"]),
        Route(P + "/autoedit/apply", autoedit_apply, methods=["POST"]),
        Route("/api/library", library_list),
        Route("/api/library/{kind}", library_add, methods=["POST"]),
        Route("/api/library/{kind}/{iid}", library_file),
        Route("/api/library/{kind}/{iid}", library_rename, methods=["PUT"]),
        Route("/api/library/{kind}/{iid}", library_delete, methods=["DELETE"]),
        Route(P + "/history", history_list),
        Route(P + "/history", history_create, methods=["POST"]),
        Route(P + "/history/compare", history_compare),
        Route(P + "/history/{sid}", history_rename, methods=["PUT"]),
        Route(P + "/history/{sid}", history_delete, methods=["DELETE"]),
        Route(P + "/history/{sid}/restore", history_restore, methods=["POST"]),
        Route(P + "/fx/status", fx_status),
        Route(P + "/transcribe", start_transcribe, methods=["POST"]),
        Route(P + "/transcript", transcript),
        Route(P + "/fx/censor/suggest", suggest_censor, methods=["POST"]),
        Route(P + "/fx/fun/suggest", suggest_fun, methods=["POST"]),
        Route(P + "/captions.srt", captions_srt),
        Route(P + "/words/fix", fix_word, methods=["POST"]),
        Route(P + "/words", words),
        Route(P + "/fx/library", library_use, methods=["POST"]),
        Route(P + "/fx/broll/suggest", broll_suggest, methods=["POST"]),
        Route(P + "/fx/sounds/{sid}", project_sound_file),
        Route(P + "/fx/images", list_fx_images),
        Route(P + "/fx/images", upload_fx_image, methods=["POST"]),
        Route(P + "/fx/images/{aid}", fx_image),
        Route("/api/sounds/{name}.wav", sound_preview),
        Route("/api/jobs", list_jobs),
        Route("/api/jobs/{jid}", get_job),
        Route("/api/jobs/{jid}/cancel", cancel_job, methods=["POST"]),
        Route("/api/jobs/{jid}/retry", retry_job, methods=["POST"]),
    ]
