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

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from backend.app.core.config import settings
from backend.app.core.db import init_db_pool, close_db_pool
from backend.app.api.schemas import BlankSpotSimRequest, HybridSearchRequest
from backend.app.api.routers import (
    meta,
    districts,
    spatial,
    simulation,
    rag,
    chat,
    watchdog,
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
    yield
    # Shutdown: Close Pools
    close_db_pool()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Deterministic Spatial Compliance & What-If Scenario Simulation Engine (DKI Jakarta)",
    lifespan=lifespan,
)

# Optional API Key Authentication Middleware (§13.1C)
@app.middleware("http")
async def optional_api_key_middleware(request: Request, call_next):
    api_key = os.getenv("API_KEY")
    if api_key and request.method == "POST":
        client_key = request.headers.get("X-API-Key")
        if not client_key or client_key != api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized: Invalid or missing X-API-Key header"},
            )
    return await call_next(request)


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

# Frontend UI & Static Assets Serving
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_FRONTEND_DIR = os.path.join(_BASE_DIR, "frontend")
_DATA_DIR = os.path.join(_BASE_DIR, "pipeline", "data")

if os.path.exists(_DATA_DIR):
    app.mount("/data", StaticFiles(directory=_DATA_DIR), name="data")

if os.path.exists(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")

__all__ = ["app", "BlankSpotSimRequest", "HybridSearchRequest"]
