"""ASGI entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port 8000`"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import db
from .api.routes import routes as api_routes
from .config import FRONTEND_DIST
from .media.render import FONTS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self)")
        if request.url.scheme == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.url.path in ("/", "/index.html", "/sw.js"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


@asynccontextmanager
async def lifespan(app):
    db.init()
    if os.environ.get("RUSHLINE_INPROC_WORKERS", "1") != "0":
        from .jobs import recover_after_restart
        from .worker import start_background
        recover_after_restart()
        start_background(int(os.environ.get("RUSHLINE_INPROC_WORKERS", "1")))
    yield


async def health(request):
    return JSONResponse({"ok": True})


async def index(request):
    f = FRONTEND_DIST / "index.html"
    if f.exists():
        return FileResponse(f)
    return PlainTextResponse("Frontend not built. Run: cd frontend && npm install && npm run build", status_code=503)


routes = [Route("/healthz", health), *api_routes, Mount("/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts"),
          Route("/", index)]
if FRONTEND_DIST.exists():
    routes.append(Mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static"))

app = Starlette(routes=routes, lifespan=lifespan,
                middleware=[Middleware(SecurityHeaders)])  # compression is done by the reverse proxy (Range-safe)
