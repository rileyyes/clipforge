"""Thumbnail Maker HTTP routes (kept deliberately simple — see ROADMAP Phase 4b)."""
from __future__ import annotations

import json
from typing import Literal, Optional

import cv2
import numpy as np
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from . import thumb_analysis as ta
from . import thumb_director as director
from .jobs import JobContext
from .storage import PathSecurityError, safe_join, validate_id
from .thumb_models import (YOUTUBE_MAX_BYTES, YOUTUBE_MIN_WIDTH, Concept, Design, ThumbContext)
from .thumb_providers import SETUP_HELP, ProviderError, image_provider
from .language import text_model  # configured server, or a running local Ollama (auto)
from .thumb_store import AssetError, ThumbNotFound, ThumbStore


def validate_thumbnail(data: bytes, fmt: str) -> dict:
    """Check an exported thumbnail against YouTube's custom-thumbnail rules:
    JPG/PNG, >= 640 px wide, 16:9, <= 2 MB. Returns {ok, checks, width, height}."""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    is_png = data[:8] == b"\x89PNG\r\n\x1a\n"
    is_jpg = data[:3] == b"\xff\xd8\xff"
    add("format", (fmt == "png" and is_png) or (fmt == "jpg" and is_jpg),
        f"{'PNG' if is_png else 'JPEG' if is_jpg else 'unknown'} (requested {fmt.upper()})")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED) if (is_png or is_jpg) else None
    h, w = (img.shape[:2] if img is not None else (0, 0))
    add("decodes", img is not None, "valid image" if img is not None else "could not decode")
    add("dimensions", (w, h) == (1280, 720), f"{w}×{h} (recommended 1280×720)")
    add("minimum width", w >= YOUTUBE_MIN_WIDTH, f"{w}px (YouTube minimum {YOUTUBE_MIN_WIDTH}px)")
    add("aspect ratio 16:9", h > 0 and abs(w / h - 16 / 9) < 0.01, f"{w / h:.3f}" if h else "n/a")
    add("file size", len(data) <= YOUTUBE_MAX_BYTES, f"{len(data) / 1024:.0f} KB (YouTube limit 2 MB)")
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "width": w, "height": h,
            "bytes": len(data)}


class ConceptsBody(BaseModel):
    context: ThumbContext = Field(default_factory=ThumbContext)
    seed: int = Field(default=0, ge=0, le=1000)
    use_text_model: bool = False
    consent_external: bool = False


class GenerateBody(BaseModel):
    concept: Concept
    prompt: Optional[str] = Field(default=None, max_length=2000)
    use_references: bool = False
    consent_external: bool = False


class NewDesignBody(BaseModel):
    concept: Concept
    workflow: Literal["ai_original", "ai_with_footage", "footage_composite"]
    art_asset: Optional[str] = None
    name: str = Field(default="Thumbnail", max_length=80)


class RefineBody(BaseModel):
    design: Design
    instruction: str = Field(min_length=1, max_length=300)


class LabelBody(BaseModel):
    label: str = Field(default="", max_length=80)


def register_thumb_jobs(svc) -> None:
    def analyze(ctx: JobContext) -> dict:
        pid = ctx.job.project_id
        project = svc.store.load(pid)
        pdir = svc.store.dir(pid)
        ctx.stage(1, 1, "Extracting frames from your final edit")
        summary = ta.summarize(svc.settings, project, pdir, ThumbStore(pdir), on_progress=ctx.progress,
                               cancel=ctx.cancel_event)
        ThumbStore(pdir).save_analysis(summary["fingerprint"], summary)
        return {"fingerprint": summary["fingerprint"], "frames": len(summary["moments"])}

    def generate(ctx: JobContext) -> dict:
        pid = ctx.job.project_id
        p = ctx.job.params
        prov = image_provider()
        if prov is None:
            raise ProviderError("No image provider is configured.")
        store = ThumbStore(svc.store.dir(pid))
        refs = []
        for aid in p.get("references", []):
            img = cv2.imread(str(store.asset_path(aid)))
            ok, buf = cv2.imencode(".png", img)
            refs.append(buf.tobytes())
        ctx.stage(1, 1, f"Generating artwork with {prov.label}")
        data = prov.generate(p["prompt"], p.get("negative", ""), refs, cancel=ctx.cancel_event)
        try:
            meta = store.add_asset(data, "ai", {"label": "AI artwork (not footage)", "provider": prov.id,
                                                "model": prov.model, "prompt": p["prompt"][:2000],
                                                "external": prov.external, "references": p.get("references", [])})
        except AssetError as exc:
            raise ProviderError(f"The provider returned an unusable image: {exc}") from exc
        return {"asset_id": meta["id"], "provider": prov.id, "model": prov.model}

    svc.jobs.register("thumb_analyze", analyze)
    svc.jobs.register("thumb_generate", generate)


def build_thumb_routes(svc, load, pid_of, body_model, err) -> list[Route]:
    def store_for(pid: str) -> ThumbStore:
        return ThumbStore(svc.store.dir(pid))

    def did_of(request: Request) -> str:
        try:
            return validate_id(request.path_params["did"])
        except PathSecurityError:
            raise HTTPException(404, "design not found")

    def current_analysis(pid: str):
        project = load(pid)
        st = store_for(pid)
        fp = ta.fingerprint(project) if project.timeline.duration > 0 else ""
        return project, st, (st.analysis(fp) if fp else None), fp

    async def status(request: Request):
        pid = pid_of(request)
        project, st, analysis, fp = current_analysis(pid)
        prov, tm = image_provider(), text_model()
        return JSONResponse({
            "image_provider": prov.info() if prov else None,
            "text_model": tm.info() if tm else None,
            "setup_help": SETUP_HELP,
            "context": st.context().model_dump(),
            "analysis": analysis,
            "fingerprint": fp,
            "timeline_empty": project.timeline.duration <= 0,
            "designs": st.list(),
            "publish_title": _publish_title(pid),
        })

    def _publish_title(pid: str) -> str:
        f = svc.store.dir(pid) / "publish.json"
        try:
            return json.loads(f.read_bytes()).get("title", "") if f.exists() else ""
        except ValueError:
            return ""

    async def start_analysis(request: Request):
        pid = pid_of(request)
        project = load(pid)
        if project.timeline.duration <= 0:
            return err(400, "The timeline is empty — edit the video first (or use the AI Auto Editor).")
        if not any(t.clips for t in ta.visible_video_tracks(project)):
            return err(400, "The edit has no visible video, so there are no frames to work from.")
        running = [j for j in svc.jobs.active_for_project(pid) if j.kind == "thumb_analyze"]
        if running:
            return JSONResponse(running[0].model_dump(), status_code=202)
        return JSONResponse(svc.jobs.submit("thumb_analyze", pid, {}).model_dump(), status_code=202)

    async def concepts(request: Request):
        pid = pid_of(request)
        body = await body_model(request, ConceptsBody)
        project, st, analysis, _ = current_analysis(pid)
        if analysis is None:
            return err(409, "Analyse the current edit first.")
        st.save_context(body.context)
        need = director.needs_context(body.context, analysis)
        if need:
            return JSONResponse({"needs_context": need}, status_code=200)
        prov = image_provider()
        genre = director.genre_of(body.context, analysis)
        notice = None
        tm = text_model() if body.use_text_model else None
        if tm and tm.external and not body.consent_external:
            return err(428, "The text model is an external service. Confirm you're OK sending a text summary "
                            "of this video (no images) before using it.")
        if tm:
            try:
                cs, hls = director.llm_concepts(tm, body.context, analysis,
                                                any(m.get("frame_asset") for m in analysis["moments"]))
            except (ProviderError, ValueError, ValidationError) as exc:
                notice = f"The text model failed ({exc}); showing the built-in director's concepts instead."
                cs, hls = director.build_concepts(body.context, analysis, has_image_provider=prov is not None,
                                                  seed=body.seed), []
        else:
            cs = director.build_concepts(body.context, analysis, has_image_provider=prov is not None, seed=body.seed)
            hls = []
        hls = hls or director.headlines(body.context, analysis, genre)
        return JSONResponse({"concepts": [c.model_dump() for c in cs], "headlines": hls, "genre": genre,
                             "notice": notice})

    async def generate(request: Request):
        pid = pid_of(request)
        body = await body_model(request, GenerateBody)
        prov = image_provider()
        if prov is None:
            return err(409, "No image provider is configured, so AI artwork can't be generated. Build the "
                            "thumbnail from your footage instead, or set up free local Stable Diffusion: "
                            + SETUP_HELP["sdwebui"])
        refs = body.concept.reference_frames if body.use_references else []
        if refs and "reference" not in prov.caps:
            return err(400, f"{prov.label} can't use reference images.")
        if prov.external and refs and not body.consent_external:
            return err(428, f"This will send {len(refs)} frame(s) from your video to {prov.label}. "
                            "Tick the consent box to continue.")
        if prov.external and not body.consent_external:
            return err(428, f"This will send the text prompt to {prov.label} (an external, paid service). "
                            "Tick the consent box to continue.")
        st = store_for(pid)
        for aid in refs:
            try:
                st.asset_path(aid)
            except (ThumbNotFound, PathSecurityError):
                return err(400, "reference frame not found")
        prompt = body.prompt or body.concept.image_prompt
        if not prompt:
            return err(400, "This concept has no image prompt (it's footage-based).")
        job = svc.jobs.submit("thumb_generate", pid, {"prompt": prompt, "negative": body.concept.negative_prompt,
                                                      "references": refs})
        return JSONResponse(job.model_dump(), status_code=202)

    async def new_design(request: Request):
        pid = pid_of(request)
        body = await body_model(request, NewDesignBody)
        project, st, analysis, fp = current_analysis(pid)
        frames = [a for a in body.concept.reference_frames]
        if not frames and analysis:
            frames = [m["frame_asset"] for m in analysis["moments"] if m.get("frame_asset")][:2]
        for aid in frames + ([body.art_asset] if body.art_asset else []):
            try:
                st.asset_path(aid)
            except (ThumbNotFound, PathSecurityError):
                return err(400, "image asset not found")
        if body.workflow != "footage_composite" and not body.art_asset:
            return err(400, "Generate the artwork first (or choose the footage workflow).")
        if body.workflow == "footage_composite" and not frames:
            return err(400, "No frames from the edit are available — analyse the edit first.")
        update = {"workflow": body.workflow}
        if body.workflow == "footage_composite":  # real footage: not a dramatization
            update.update(departs_from_footage=False, review_note="")
        concept = body.concept.model_copy(update=update)
        bg = body.art_asset if body.workflow != "footage_composite" else frames[0]
        genre = director.genre_of(st.context(), analysis or {})
        d = director.build_design(concept, background_asset=bg, frame_assets=frames, genre=genre, name=body.name)
        d.edit_revision = project.edit_revision
        d.timeline_fingerprint = fp
        d.timeline_coverage = ta.timeline_coverage(project)
        if body.art_asset:
            meta = st.asset_meta(body.art_asset)
            from .thumb_models import GenerationRecord
            d.generations.append(GenerationRecord(asset_id=body.art_asset, provider=meta.get("provider", "?"),
                                                  model=meta.get("model", ""), workflow=body.workflow,
                                                  prompt=meta.get("prompt", "")[:4000], external=meta.get("external", False),
                                                  consented=True, references=meta.get("references", [])))
        return JSONResponse(st.create(d), status_code=201)

    async def get_design(request: Request):
        pid = pid_of(request)
        project = load(pid)
        try:
            doc = store_for(pid).get(did_of(request))
        except ThumbNotFound:
            return err(404, "design not found")
        dr = doc["draft"]
        doc["staleness"] = ta.staleness(project, dr.get("timeline_fingerprint", ""), dr.get("timeline_coverage", []))
        return JSONResponse(doc)

    async def save_draft(request: Request):
        pid = pid_of(request)
        did = did_of(request)
        body = await body_model(request, Design)
        if body.id != did:
            return err(400, "design id mismatch")
        try:
            return JSONResponse(store_for(pid).save_draft(body))
        except ThumbNotFound:
            return err(404, "design not found")

    async def save_version(request: Request):
        pid = pid_of(request)
        body = await body_model(request, LabelBody)
        try:
            return JSONResponse(store_for(pid).save_version(did_of(request), body.label), status_code=201)
        except ThumbNotFound:
            return err(404, "design not found")

    async def rename_version(request: Request):
        pid = pid_of(request)
        body = await body_model(request, LabelBody)
        try:
            return JSONResponse(store_for(pid).rename_version(did_of(request), request.path_params["vid"], body.label))
        except ThumbNotFound:
            return err(404, "version not found")

    async def restore_version(request: Request):
        pid = pid_of(request)
        try:
            return JSONResponse(store_for(pid).restore_version(did_of(request), request.path_params["vid"]))
        except ThumbNotFound:
            return err(404, "version not found")

    async def duplicate(request: Request):
        pid = pid_of(request)
        try:
            return JSONResponse(store_for(pid).duplicate(did_of(request)), status_code=201)
        except ThumbNotFound:
            return err(404, "design not found")

    async def delete_design(request: Request):
        pid = pid_of(request)
        try:
            store_for(pid).delete(did_of(request))
        except ThumbNotFound:
            return err(404, "design not found")
        return Response(status_code=204)

    async def refine(request: Request):
        pid = pid_of(request)
        load(pid)
        body = await body_model(request, RefineBody)
        prov = image_provider()
        return JSONResponse(director.refine(body.design, body.instruction, prov is not None,
                                            bool(prov and "reference" in prov.caps)))

    async def asset(request: Request):
        pid = pid_of(request)
        load(pid)
        try:
            path = store_for(pid).asset_path(request.path_params["aid"])
        except (ThumbNotFound, PathSecurityError):
            return err(404, "asset not found")
        return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg",
                            headers={"cache-control": "private, max-age=31536000, immutable"})

    async def upload_asset(request: Request):
        pid = pid_of(request)
        load(pid)
        data = b""
        async for chunk in request.stream():
            data += chunk
            if len(data) > 25 * 1024 * 1024:
                return err(413, "image is larger than 25 MB")
        try:
            meta = store_for(pid).add_asset(data, "upload", {"label": "Your image"})
        except AssetError as exc:
            return err(415, str(exc))
        return JSONResponse(meta, status_code=201)

    async def cutout(request: Request):
        """Cut the subject out of an image asset (quick, local; rough edges possible)"""
        pid = pid_of(request)
        load(pid)
        st = store_for(pid)
        try:
            path = st.asset_path(request.path_params["aid"])
        except (ThumbNotFound, PathSecurityError):
            return err(404, "asset not found")
        from .cutout import cut_out
        import asyncio
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            return err(415, "the image could not be read")
        try:
            out, info = await asyncio.to_thread(cut_out, img)
        except ValueError as exc:
            return err(422, str(exc))
        meta = st.add_asset(out, "cutout", {"label": "Cut-out", "source_asset": path.stem, **info})
        return JSONResponse(meta, status_code=201)

    class FromLibrary(BaseModel):
        id: str

    async def asset_from_library(request: Request):
        """Use an image from My library in a thumbnail"""
        pid = pid_of(request)
        load(pid)
        body = await body_model(request, FromLibrary)
        from .library import Library
        try:
            item = Library(svc.settings).get("image", validate_id(body.id))
            data = Library(svc.settings).file("image", body.id).read_bytes()
        except (KeyError, PathSecurityError):
            return err(404, "That image isn't in your library.")
        meta = store_for(pid).add_asset(data, "upload", {"label": item.name})
        return JSONResponse(meta, status_code=201)

    async def frame_at(request: Request):
        pid = pid_of(request)
        project = load(pid)
        try:
            t = float(request.query_params.get("t", "0"))
        except ValueError:
            return err(400, "t must be a number")
        if not 0 <= t < project.timeline.duration:
            return err(400, "time is outside the edit")
        try:
            meta = ta.get_frame(svc.settings, project, svc.store.dir(pid), store_for(pid), t)
        except ValueError as exc:
            return err(400, str(exc))
        return JSONResponse(meta, status_code=201)

    async def export(request: Request):
        pid = pid_of(request)
        did = did_of(request)
        load(pid)
        fmt = request.query_params.get("format", "jpg")
        if fmt not in ("png", "jpg"):
            return err(400, "format must be png or jpg")
        data = b""
        async for chunk in request.stream():
            data += chunk
            if len(data) > 20 * 1024 * 1024:
                return err(413, "export too large")
        report = validate_thumbnail(data, fmt)
        if not report["ok"]:
            return JSONResponse({"error": "The thumbnail doesn't meet YouTube's requirements.", "validation": report},
                                status_code=422)
        st = store_for(pid)
        try:
            design = st.version_design(did, request.query_params.get("version") or None)
        except ThumbNotFound:
            return err(404, "design not found")
        import re as _re
        base = _re.sub(r"[^A-Za-z0-9 _-]+", "", design.name).strip()[:60] or "thumbnail"
        n, name = 1, f"{base}.{fmt}"
        while (st.root / "exports" / name).exists():
            name = f"{base}-{n}.{fmt}"
            n += 1
        (st.root / "exports" / name).write_bytes(data)
        return JSONResponse({"file": name, "validation": report}, status_code=201)

    async def list_exports(request: Request):
        pid = pid_of(request)
        load(pid)
        d = store_for(pid).root / "exports"
        items = sorted(d.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        return JSONResponse({"exports": [{"file": p.name, "size": p.stat().st_size} for p in items
                                         if p.suffix in (".png", ".jpg")]})

    async def download_export(request: Request):
        pid = pid_of(request)
        load(pid)
        try:
            p = safe_join(store_for(pid).root / "exports", request.path_params["name"])
        except PathSecurityError:
            return err(404, "not found")
        if not p.is_file() or p.suffix not in (".png", ".jpg"):
            return err(404, "not found")
        return FileResponse(p, filename=p.name)

    T = "/api/projects/{pid}/thumbnails"
    return [
        Route(T, status),
        Route(T + "/analyze", start_analysis, methods=["POST"]),
        Route(T + "/concepts", concepts, methods=["POST"]),
        Route(T + "/generate", generate, methods=["POST"]),
        Route(T + "/refine", refine, methods=["POST"]),
        Route(T + "/frame", frame_at, methods=["POST"]),
        Route(T + "/assets", upload_asset, methods=["POST"]),
        Route(T + "/assets/{aid}", asset),
        Route(T + "/assets/{aid}/cutout", cutout, methods=["POST"]),
        Route(T + "/assets/from-library", asset_from_library, methods=["POST"]),
        Route(T + "/exports", list_exports),
        Route(T + "/exports/{name}", download_export),
        Route(T + "/designs", new_design, methods=["POST"]),
        Route(T + "/designs/{did}", get_design),
        Route(T + "/designs/{did}", save_draft, methods=["PUT"]),
        Route(T + "/designs/{did}", delete_design, methods=["DELETE"]),
        Route(T + "/designs/{did}/duplicate", duplicate, methods=["POST"]),
        Route(T + "/designs/{did}/versions", save_version, methods=["POST"]),
        Route(T + "/designs/{did}/versions/{vid}", rename_version, methods=["PUT"]),
        Route(T + "/designs/{did}/versions/{vid}/restore", restore_version, methods=["POST"]),
        Route(T + "/designs/{did}/export", export, methods=["POST"]),
    ]
