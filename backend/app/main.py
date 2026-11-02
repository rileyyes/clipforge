"""Application factory + local security middleware.

Run:  python -m app.main   (from backend/)
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Optional

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from .api import Services, _ValidationWrap, build_routes, pydantic_error
from .config import Settings, ensure_workspace, load_settings
from .projects import RevisionConflict

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class LocalSecurityMiddleware:
    """CSRF / cross-site protection for a localhost app.

    * State-changing requests must carry ``X-ClipForge: 1``. Browsers cannot add
      custom headers cross-origin without a CORS preflight, which we never grant.
    * If an Origin header is present it must be one of our own origins.
    * Adds strict security headers to every response.
    """

    def __init__(self, app: ASGIApp, allowed_origins: tuple[str, ...]):
        self.app = app
        self.allowed = set(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        method = scope["method"]
        origin = headers.get("origin")
        if origin and origin not in self.allowed:
            await JSONResponse({"error": "cross-origin request blocked"}, 403)(scope, receive, send)
            return
        if method not in SAFE_METHODS and headers.get("x-clipforge") != "1":
            await JSONResponse({"error": "missing X-ClipForge header"}, 403)(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"content-security-policy", CSP.encode()),
                ]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(settings: Optional[Settings] = None) -> Starlette:
    settings = settings or load_settings()
    ensure_workspace(settings)
    svc = Services(settings)
    routes = build_routes(svc)

    async def spa(request: Request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        index = FRONTEND_DIST / "index.html"
        if not index.exists():
            return Response("Frontend not built. Run: cd frontend && node build.mjs",
                            media_type="text/plain", status_code=503)
        return FileResponse(index, headers={"cache-control": "no-cache"})

    if (FRONTEND_DIST / "assets").exists():
        routes.append(Mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets")))
    routes.append(Route("/{path:path}", spa))

    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    async def validation_error(request: Request, exc: _ValidationWrap):
        return pydantic_error(exc.exc)

    async def conflict(request: Request, exc: RevisionConflict):
        return JSONResponse({"error": str(exc)}, status_code=409)

    async def value_error(request: Request, exc: ValueError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        yield
        svc.jobs.shutdown()

    allowed_hosts = ["127.0.0.1", "localhost", "testserver"]
    if settings.host not in ("127.0.0.1", "localhost", "0.0.0.0"):
        allowed_hosts.append(settings.host)
    app = Starlette(
        routes=routes,
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts),
            Middleware(LocalSecurityMiddleware, allowed_origins=settings.allowed_origins),
        ],
        exception_handlers={HTTPException: http_error, _ValidationWrap: validation_error,
                            RevisionConflict: conflict, ValueError: value_error},
        lifespan=lifespan,
    )
    app.state.services = svc
    return app


def main() -> None:
    import uvicorn

    settings = load_settings()
    if settings.host not in ("127.0.0.1", "localhost"):
        print(f"WARNING: binding to {settings.host} exposes your media to the network.")
    print(f"ClipForge workspace: {settings.workspace}")
    print(f"Open http://{settings.host}:{settings.port}")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                log_level="info", access_log=False)


if __name__ == "__main__":
    main()
