"""The OpenAPI spec is generated from the routes, so it must cover all of them."""
from __future__ import annotations

from starlette.routing import Route


def _api_routes(app):
    from app.openapi import _walk
    return {(p, m) for p, r in _walk(app.routes) if p.startswith("/api") for m in (r.methods or {"GET"}) - {"HEAD"}}


def test_spec_covers_every_route_and_bodies(server):
    st, spec, _ = server.req("GET", "/api/openapi.json")
    assert st == 200 and spec["openapi"] == "3.1.0"
    documented = {(p, m.upper()) for p, ops in spec["paths"].items() for m in ops}
    assert _api_routes(server.app) <= documented
    ops = spec["paths"]
    # JSON bodies resolved from each handler's body_model(...) call
    body = ops["/api/projects/{pid}/history"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert spec["components"]["schemas"][body["$ref"].rsplit("/", 1)[1]]["properties"]["label"]["maxLength"] == 80
    apply = ops["/api/projects/{pid}/autoedit/apply"]["post"]["requestBody"]["content"]["application/json"]
    assert apply["schema"]["$ref"].endswith("/ApplyBody")
    assert "Extras" in spec["components"]["schemas"]
    # raw uploads
    assert "application/octet-stream" in ops["/api/library/{kind}"]["post"]["requestBody"]["content"]
    assert "application/octet-stream" in ops["/api/projects/{pid}/media"]["post"]["requestBody"]["content"]
    # every state-changing operation documents the CSRF header
    for path, o in ops.items():
        for m, op in o.items():
            if m in ("post", "put"):
                assert any(p["name"] == "X-RJClip" for p in op["parameters"]), (path, m)
    assert "Project" in spec["components"]["schemas"] and "Effect" in spec["components"]["schemas"]


def test_docs_page_renders_without_scripts(server):
    st, page, h = server.req("GET", "/api/docs")
    assert st == 200 and h["content-type"].startswith("text/html")
    text = page.decode() if isinstance(page, bytes) else page
    assert "<script" not in text and "/api/projects/{pid}/history" in text and "My library" in text
