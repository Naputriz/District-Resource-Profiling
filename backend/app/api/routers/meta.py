"""
Meta endpoints: health check and regulatory standards metadata.
"""

import json
from fastapi import APIRouter, Response
from backend.app.core.cache import (
    PUBLIC_CACHE_CONTROL,
    cache_get_json,
    cache_set_json,
    standards_cache_key,
)
from backend.app.core.config import settings
from backend.app.api.deps import get_db_cursor, get_redis_client

router = APIRouter()


@router.get("/health", tags=["Observability"])
def health_check():
    """Health check for Backend, PostGIS 3.4, and Redis 7."""
    db_status = "unhealthy"
    redis_status = "unhealthy"

    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT 1;")
            if cur.fetchone():
                db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"

    try:
        r_client = get_redis_client()
        if r_client and r_client.ping():
            redis_status = "healthy"
    except Exception as e:
        redis_status = f"error: {str(e)}"

    import os
    import urllib.request

    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model_name = os.getenv("OLLAMA_MODEL_NAME", "qwen2.5:14b")
    llm_model = "LLM tidak aktif"

    try:
        req = urllib.request.Request(
            f"{ollama_url}/api/tags", headers={"User-Agent": "FastAPI-Health"}
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = [m.get("name") for m in data.get("models", [])]
                if any(model_name in m for m in models) or len(models) > 0:
                    llm_model = model_name
    except Exception:
        llm_model = "LLM tidak aktif"

    overall = (
        "healthy"
        if (db_status == "healthy" and redis_status == "healthy")
        else "degraded"
    )

    return {
        "status": overall,
        "service": "District Resource Profiling Backend",
        "postgis_database": db_status,
        "redis_cache": redis_status,
        "llm_model": llm_model,
        "environment": settings.ENVIRONMENT,
    }


def fetch_regulatory_standards_rows():
    """Queries regulatory standards rows from PostgreSQL."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT facility_type, pillar, category, standard_name,
                   population_threshold, service_radius_meters, min_land_area_m2,
                   legal_reference, description, scored, source
            FROM regulatory_standards
            ORDER BY pillar, facility_type;
        """)
        return [dict(r) for r in cur.fetchall()]


@router.get(f"{settings.API_V1_STR}/meta/standards", tags=["Regulatory Standards"])
def get_regulatory_standards(response: Response):
    """Returns official standards across all 4 Pillars (SNI 03-1733-2004, SPM & Perda RDTR)."""
    cache_key = standards_cache_key(settings.POSTGRES_DB)
    r_client = None
    try:
        r_client = get_redis_client()
        if r_client:
            cached = cache_get_json(r_client, cache_key)
            if cached is not None:
                response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
                return cached
    except Exception:
        r_client = None

    rows = fetch_regulatory_standards_rows()
    if r_client and rows:
        cache_set_json(r_client, cache_key, rows, ttl=settings.REDIS_CACHE_TTL)
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
    return rows
