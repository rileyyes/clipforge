"""OpenAPI 3.1 description of the API, generated from the live route table.

Nothing is maintained by hand, so the docs can't drift from the code:

* every ``Route`` under ``/api`` becomes an operation (summary = the handler's docstring,
  or its name made readable; tag = the area of the API);
* JSON request bodies come from the Pydantic model each handler validates with
  ``body_model(request, Model)`` — found in the handler's source and resolved through its
  closure, then turned into JSON Schema by Pydantic;
* handlers that stream the raw request (uploads) get an ``application/octet-stream`` body.

Served at ``/api/openapi.json`` and as a readable page at ``/api/docs``.
"""
from __future__ import annotations

import html
import inspect
import json
import re
from typing import Any, Optional

from pydantic import BaseModel
from starlette.routing import Mount, Route

from .schema import Project

TAGS = [("system", "System"), ("projects", "Projects"), ("media", "Media"), ("timeline", "Timeline"),
        ("exports", "Exports"), ("autoedit", "AI Auto Editor"), ("effects", "Effects & captions"),
        ("library", "My library"), ("shorts", "Shorts"), ("publish", "Publish & YouTube"), ("history", "Version history"), ("thumbnails", "Thumbnail Maker"),
        ("jobs", "Jobs")]


def _tag(path: str) -> str:
    p = path.removeprefix("/api/")
    if p.startswith("library"):
        return "library"
    if p.startswith("jobs"):
        return "jobs"
    if p.startswith(("system", "health", "maintenance", "sounds", "openapi", "docs")):
        return "system"
    if not p.startswith("projects"):
        return "system"
    rest = re.sub(r"^projects(/\{pid\})?/?", "", p)
    head = rest.split("/", 1)[0]
    return {"": "projects", "rename": "projects", "duplicate": "projects", "media": "media", "timeline": "timeline",
            "exports": "exports", "autoedit": "autoedit", "fx": "effects", "transcribe": "effects",
            "transcript": "effects", "captions.srt": "effects", "history": "history",
            "thumbnails": "thumbnails", "shorts": "shorts", "publish": "publish", "youtube": "publish"}.get(head, "projects")


def _summary(fn) -> str:
    doc = inspect.getdoc(fn)
    if doc:
        return doc.split("\n", 1)[0].rstrip(".")
    return fn.__name__.replace("_", " ").strip().capitalize()


def _body_model(fn) -> Optional[type[BaseModel]]:
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return None
    m = re.search(r"body_model\(request,\s*(\w+)\)", src)
    if not m:
        return None
    name = m.group(1)
    code = fn.__code__
    if fn.__closure__ and name in code.co_freevars:
        obj = fn.__closure__[code.co_freevars.index(name)].cell_contents
    else:
        obj = fn.__globals__.get(name)
    return obj if isinstance(obj, type) and issubclass(obj, BaseModel) else None


def _streams_upload(fn) -> bool:
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return False
    return "request.stream()" in src or "read_upload(request" in src


def _walk(routes, prefix=""):
    for r in routes:
        if isinstance(r, Mount):
            yield from _walk(r.routes or [], prefix + r.path)
        elif isinstance(r, Route):
            yield prefix + r.path, r


def build_spec(app_routes, version: str = "0.7.0") -> dict:
    components: dict[str, Any] = {}

    def schema_ref(model: type[BaseModel]) -> dict:
        s = model.model_json_schema(ref_template="#/components/schemas/{model}")
        for k, v in (s.pop("$defs", {}) or {}).items():
            components.setdefault(k, v)
        components.setdefault(model.__name__, s)
        return {"$ref": f"#/components/schemas/{model.__name__}"}

    schema_ref(Project)
    paths: dict[str, dict] = {}
    for path, route in _walk(app_routes):
        if not path.startswith("/api"):
            continue
        fn = route.endpoint
        params = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"},
                   **({"description": "32-character hex id"} if n in ("pid", "mid", "sid", "iid", "jid", "aid") else {})}
                  for n in re.findall(r"\{(\w+)\}", path)]
        for method in sorted((route.methods or {"GET"}) - {"HEAD"}):
            op: dict[str, Any] = {"summary": _summary(fn), "operationId": f"{fn.__name__}_{method.lower()}",
                                  "tags": [_tag(path)],
                                  "responses": {"200": {"description": "OK (JSON unless noted)"},
                                                "4XX": {"description": "Error: `{\"error\": \"message\"}`"}}}
            if params:
                op["parameters"] = params
            if method not in ("GET", "DELETE"):
                op["parameters"] = op.get("parameters", []) + [
                    {"name": "X-ClipForge", "in": "header", "required": True, "schema": {"const": "1"},
                     "description": "CSRF guard: required on every state-changing request"}]
                model = _body_model(fn)
                if model is not None:
                    op["requestBody"] = {"required": True, "content": {"application/json": {"schema": schema_ref(model)}}}
                elif _streams_upload(fn):
                    op["requestBody"] = {"required": True, "content": {"application/octet-stream": {
                        "schema": {"type": "string", "format": "binary"}}}}
            paths.setdefault(path, {})[method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": "ClipForge local API", "version": version,
                 "description": "Local-only API of the ClipForge editor (http://127.0.0.1). "
                                "Generated from the server's routes; see docs/API.md for behaviour notes."},
        "servers": [{"url": "/"}],
        "tags": [{"name": k, "description": v} for k, v in TAGS],
        "paths": dict(sorted(paths.items())),
        "components": {"schemas": dict(sorted(components.items()))},
    }


def docs_html(spec: dict) -> str:
    """A plain, script-free reference page (works under the app's strict CSP)."""
    e = html.escape
    tag_name = dict(TAGS)
    by_tag: dict[str, list] = {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            by_tag.setdefault(op["tags"][0], []).append((path, method, op))
    out = ["<!doctype html><html><head><meta charset='utf-8'><title>ClipForge API</title><style>",
           "body{font:14px system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#222}",
           "h2{margin-top:28px;border-bottom:1px solid #ddd}code,pre{font:12px ui-monospace,monospace}",
           ".m{display:inline-block;width:58px;font-weight:700}.get{color:#1a7f37}.post{color:#0969da}",
           ".put{color:#9a6700}.delete{color:#cf222e}details{margin:2px 0 6px 64px}pre{background:#f6f8fa;padding:8px;overflow:auto}",
           "</style></head><body>", f"<h1>{e(spec['info']['title'])} <small>v{e(spec['info']['version'])}</small></h1>",
           f"<p>{e(spec['info']['description'])} Machine-readable: <a href='/api/openapi.json'>/api/openapi.json</a>.</p>"]
    for tag, _label in TAGS:
        if tag not in by_tag:
            continue
        out.append(f"<h2>{e(tag_name[tag])}</h2>")
        for path, method, op in sorted(by_tag[tag]):
            out.append(f"<div><span class='m {method}'>{method.upper()}</span><code>{e(path)}</code> — {e(op['summary'])}</div>")
            body = op.get("requestBody", {}).get("content", {})
            if "application/json" in body:
                ref = body["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
                schema = spec["components"]["schemas"].get(ref, {})
                out.append(f"<details><summary>JSON body: {e(ref)}</summary><pre>{e(json.dumps(schema, indent=2))}</pre></details>")
            elif body:
                out.append("<details><summary>Body: raw file bytes</summary></details>")
    out.append("</body></html>")
    return "".join(out)
