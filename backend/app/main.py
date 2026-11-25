"""
FastAPI Backend Application for District Resource Profiling (DKI Jakarta).
Provides:
- Deterministic compliance scorecards for all 44 districts.
- 4 Pillars public amenities spatial queries.
- Isolated What-If urban scenario simulation sandbox (Population Shock & Superblock Projects).
- PostGIS spatial analysis: Metric UTM Buffers & Unserved Blank Spot GeoJSON polygons.
- Pencarian leksikal (trigram + hashed bag-of-words + sinonim) untuk sitasi regulasi resmi.
- Full health observability for PostGIS and Redis.
"""

import asyncio
import os
import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from backend.app.core.cache import warm_startup_caches
from backend.app.core.config import settings
from backend.app.core.db import init_db_pool, close_db_pool
from backend.app.core.auth import decode_access_token
from backend.app.api.schemas import BlankSpotSimRequest, HybridSearchRequest
from backend.app.api.routers import (
    meta,
    districts,
    spatial,
    simulation,
    rag,
    chat,
    watchdog,
    auth,
    regions,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB & Redis Pools
    init_db_pool()
    api_key = os.getenv("API_KEY")
    if not api_key:
        logger.warning(
            "SECURITY WARNING: API_KEY is not set in environment. "
            "API authentication for POST routes is disabled."
        )
    warmup_cancel = threading.Event()
    warmup_task = asyncio.create_task(asyncio.to_thread(warm_startup_caches, warmup_cancel))
    try:
        yield
    finally:
        # Shutdown: Stop background warmup cleanly before closing pools
        warmup_cancel.set()
        if not warmup_task.done():
            warmup_task.cancel()
        try:
            await warmup_task
        except (asyncio.CancelledError, Exception):
            pass
        close_db_pool()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Deterministic Spatial Compliance & What-If Scenario Simulation Engine (DKI Jakarta)",
    lifespan=lifespan,
)


# Optional API Key Authentication Middleware (§13.1C & TODO-4)
@app.middleware("http")
async def optional_api_key_middleware(request: Request, call_next):
    # Public auth endpoints do not require API_KEY
    if request.url.path.startswith(f"{settings.API_V1_STR}/auth/"):
        return await call_next(request)

    api_key = os.getenv("API_KEY")
    if api_key and request.method == "POST":
        client_key = request.headers.get("X-API-Key")
        auth_header = request.headers.get("Authorization")
        # Allow service key match
        if client_key and client_key == api_key:
            return await call_next(request)
        # Allow user bearer token (route dependencies will validate the JWT)
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            try:
                decode_access_token(token)
                return await call_next(request)
            except Exception:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized: Invalid or missing credentials"},
                )
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized: Invalid or missing X-API-Key header"},
        )
    return await call_next(request)


@app.middleware("http")
async def static_asset_cache_headers_middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/_headers", "/.assetsignore"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    response = await call_next(request)
    if request.method in ("GET", "HEAD") and response.status_code == 200:
        if path in ("/", "/index.html") or path.startswith("/js/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        elif path.startswith("/css/"):
            response.headers.setdefault("Cache-Control", "public, max-age=300")
        elif path.startswith("/data/boundaries/"):
            response.headers.setdefault(
                "Cache-Control", "public, max-age=86400, stale-while-revalidate=604800"
            )
    return response


# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(meta.router)
app.include_router(districts.router)
app.include_router(spatial.router)
app.include_router(simulation.router)
app.include_router(rag.router)
app.include_router(chat.router)
app.include_router(watchdog.router)
app.include_router(auth.router)
app.include_router(regions.router)

# Frontend UI & Static Assets Serving
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_FRONTEND_DIR = os.path.join(_BASE_DIR, "frontend")
_FRONTEND_DATA_DIR = os.path.join(_FRONTEND_DIR, "data")

if os.path.exists(_FRONTEND_DATA_DIR):
    app.mount("/data", StaticFiles(directory=_FRONTEND_DATA_DIR), name="data")

if os.path.exists(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")

__all__ = ["app", "BlankSpotSimRequest", "HybridSearchRequest"]
