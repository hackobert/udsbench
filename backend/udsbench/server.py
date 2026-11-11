"""App-Fabrik: FastAPI-App mit API, WebSockets, OpenAPI und statischer Auslieferung des Frontends."""

from __future__ import annotations

import ipaddress
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api.routes import router
from .api.routes_ext import router as router_ext
from .api.routes_setup import router as router_setup
from .api.ws import ws_router
from .config.schema import AppConfig
from .core.errors import UdsBenchError
from .core.platform import Platform

log = logging.getLogger("udsbench.app.server")

STATIC_DIR = Path(__file__).resolve().parent / "static"

_FALLBACK_HTML = """<!doctype html><html lang="de"><meta charset="utf-8"><title>udsbench</title>
<body style="font-family:system-ui;max-width:720px;margin:3rem auto;line-height:1.5">
<h1>udsbench</h1><p>Der Server läuft, aber das Frontend fehlt in dieser Installation.</p>
<p>Das gebaute Frontend liegt im Repository unter <code>backend/udsbench/static/</code>. Installieren
Sie udsbench aus einem vollständigen Checkout neu (<code>pip install .</code>) oder bauen Sie es selbst:</p>
<pre>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</pre>
<p>API-Dokumentation: <a href="/docs">/docs</a> (OpenAPI: <a href="/openapi.json">/openapi.json</a>)</p></body></html>"""


def is_loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve_token(cfg: AppConfig) -> str | None:
    """Ohne Token ist nur Loopback-Bindung erlaubt; sonst wird ein zufälliges Token erzeugt."""
    if cfg.server.token:
        return cfg.server.token
    if not is_loopback(cfg.server.host):
        token = secrets.token_urlsafe(24)
        log.warning("Server ist nicht an Loopback gebunden – zufälliges API-Token erzeugt: %s", token)
        return token
    return None


def create_app(config: AppConfig, base_dir: Path, *, platform: Platform | None = None) -> FastAPI:
    plat = platform or Platform(config, base_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        await plat.start()
        try:
            yield
        finally:
            await plat.stop()

    app = FastAPI(
        title="udsbench API",
        version=__version__,
        description=(
            "Generische UDS-/CAN-Diagnose- und Testplattform. Die API deckt den gesamten Funktionsumfang ab "
            "(die Browser-UI ist ein reiner Client). Authentifizierung: `Authorization: Bearer <token>` bzw. "
            "`X-API-Token`, für WebSockets/SSE `?token=`."
        ),
        lifespan=lifespan,
    )
    app.state.platform = plat
    app.state.token = resolve_token(config)

    if config.server.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=config.server.cors_origins, allow_methods=["*"], allow_headers=["*"]
        )

    @app.exception_handler(UdsBenchError)
    async def _uds_err(_: Request, exc: UdsBenchError) -> JSONResponse:
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _val_err(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": ".".join(str(x) for x in e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "Ungültige Anfrage", "details": details}},
            status_code=422,
        )

    @app.exception_handler(PydanticValidationError)
    async def _pyd_err(_: Request, exc: PydanticValidationError) -> JSONResponse:
        details = [
            {"loc": ".".join(str(x) for x in e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "Ungültige Daten", "details": details}},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_err(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            {"error": {"code": code, "message": str(exc.detail)}},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _any_err(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        log.exception("Unbehandelter Fehler")
        return JSONResponse(
            {"error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}}, status_code=500
        )

    @app.get("/api/health", tags=["system"], summary="Lebenszeichen (ohne Authentifizierung)")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "auth_required": app.state.token is not None}

    app.include_router(router)
    app.include_router(router_ext)
    app.include_router(router_setup)
    app.include_router(ws_router)

    if (STATIC_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Any:
            if path.startswith(("api/", "ws/")):
                return JSONResponse(
                    {"error": {"code": "not_found", "message": "Nicht gefunden"}}, status_code=404
                )
            candidate = (STATIC_DIR / path).resolve()
            if path and candidate.is_file() and STATIC_DIR in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        async def index() -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)

    return app
