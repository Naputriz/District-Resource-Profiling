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
import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from backend.app.core.config import settings
from backend.app.core.db import (
    init_db_pool, close_db_pool, get_db_cursor, get_redis_client
)
from backend.app.engine.simulation import (
    WhatIfSimulationEngine,
    SimulationRequest,
    SimulationDeltaDTO,
    SuperblockSimulationRequest,
    SuperblockImpactDTO
)
from backend.app.engine.spatial import (
    PostGISSpatialEngine,
    BlankSpotAnalysisResult,
    BlankSpotSimulationDelta
)
from backend.app.rag.hybrid_search import (
    HybridRegulationRetriever,
    LegalCitation
)

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
    lifespan=lifespan
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
                content={"detail": "Unauthorized: Invalid or missing X-API-Key header"}
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

# -----------------------------------------------------------------------------
# 1. Observability & Health Check
# -----------------------------------------------------------------------------
@app.get("/health", tags=["Observability"])
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
        req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"User-Agent": "FastAPI-Health"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = [m.get("name") for m in data.get("models", [])]
                if any(model_name in m for m in models) or len(models) > 0:
                    llm_model = model_name
    except Exception:
        llm_model = "LLM tidak aktif"

    overall = "healthy" if (db_status == "healthy" and redis_status == "healthy") else "degraded"

    return {
        "status": overall,
        "service": "District Resource Profiling Backend",
        "postgis_database": db_status,
        "redis_cache": redis_status,
        "llm_model": llm_model,
        "environment": settings.ENVIRONMENT
    }

# -----------------------------------------------------------------------------
# 2. Regulatory Standards Metadata
# -----------------------------------------------------------------------------
@app.get(f"{settings.API_V1_STR}/meta/standards", tags=["Regulatory Standards"])
def get_regulatory_standards():
    """Returns official standards across all 4 Pillars (SNI 03-1733-2004, SPM & Perda RDTR)."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT facility_type, pillar, category, standard_name,
                   population_threshold, service_radius_meters, min_land_area_m2,
                   legal_reference, description, scored, source
            FROM regulatory_standards
            ORDER BY pillar, facility_type;
        """)
        return cur.fetchall()

# -----------------------------------------------------------------------------
# 3. Districts & Compliance Scorecards
# -----------------------------------------------------------------------------
@app.get(f"{settings.API_V1_STR}/districts", tags=["Districts & Compliance"])
def list_districts():
    """Lists all 44 Kecamatan with demographic stats and compliance scorecards."""
    from backend.app.engine.standards_availability import get_current_availability_source
    avail_src = get_current_availability_source()

    # Check Redis cache first
    try:
        r_client = get_redis_client()
        if r_client:
            cached = r_client.get("cache:compliance:scores")
            if cached:
                dist_list = json.loads(cached)
                for d in dist_list:
                    d["population_note"] = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)"
                return {
                    "source": "cache",
                    "availability_source": avail_src,
                    "population_note": "Sumber data penduduk belum terverifikasi (TODO-VERIFY)",
                    "districts": dist_list
                }
    except Exception:
        pass

    with get_db_cursor() as cur:
        cur.execute("""
            SELECT 
                k.kemendagri_code, k.bps_code, k.name, c.name as city_name,
                k.population, k.area_km2, k.density_per_km2,
                s.health_score, s.education_score, s.livability_score,
                s.mobility_score, s.composite_livability_score,
                s.metrics_payload
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            LEFT JOIN district_compliance_scores s ON s.district_id = k.id
            ORDER BY k.kemendagri_code;
        """)
        results = [dict(r) for r in cur.fetchall()]
        for r in results:
            r["population_note"] = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)"
        return {
            "source": "database",
            "availability_source": avail_src,
            "population_note": "Sumber data penduduk belum terverifikasi (TODO-VERIFY)",
            "districts": results
        }

@app.get(f"{settings.API_V1_STR}/districts/{{district_code}}", tags=["Districts & Compliance"])
def get_district_detail(district_code: str):
    """Returns single district compliance scorecard and deficit breakdown."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT 
                k.id, k.kemendagri_code, k.bps_code, k.name, c.name as city_name,
                k.population, k.area_km2, k.density_per_km2,
                s.health_score, s.education_score, s.livability_score,
                s.mobility_score, s.composite_livability_score, s.composite_note,
                s.metrics_payload,
                ST_AsGeoJSON(k.boundary)::json as boundary_geojson
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            LEFT JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE k.kemendagri_code = %s OR LOWER(k.name) = LOWER(%s);
        """, (district_code, district_code))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Kecamatan '{district_code}' not found.")

        data = dict(row)
        data["population_note"] = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)"
        from backend.app.engine.standards_availability import get_current_availability_source
        data["availability_source"] = get_current_availability_source()

        if isinstance(data.get("metrics_payload"), str):
            try:
                data["metrics_payload"] = json.loads(data["metrics_payload"])
            except Exception:
                pass

        if isinstance(data.get("metrics_payload"), list):
            from backend.app.engine.standards_availability import calculate_pillar_and_composite_scores
            scores_breakdown = calculate_pillar_and_composite_scores(data["metrics_payload"])
            data["pillar_scores"] = scores_breakdown["pillar_scores"]
            data["composite_note"] = data.get("composite_note") or scores_breakdown["composite_note"]
            data["availability_source"] = scores_breakdown.get("availability_source", data["availability_source"])

        return data

# -----------------------------------------------------------------------------
# 4. Deterministic PostGIS Spatial Calculations (Buffers & Blank Spots)
# -----------------------------------------------------------------------------
@app.get(f"{settings.API_V1_STR}/spatial/buffers", tags=["Spatial Calculations"])
def get_district_facility_buffers(
    district_code: str = Query(..., description="kemendagri_code, e.g. 31.71.09 (Tebet)"),
    facility_type: Optional[str] = Query(None, description="e.g. puskesmas_kelurahan, sekolah_dasar"),
    pillar: Optional[str] = None
):
    """
    Returns exact service coverage buffers (FeatureCollection) projected to WGS 84 GeoJSON.
    Calculated via PostGIS metric UTM Zone 48S.
    """
    try:
        buffers = PostGISSpatialEngine.compute_facility_buffers(
            district_code=district_code,
            facility_type=facility_type,
            pillar=pillar
        )
        return buffers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get(f"{settings.API_V1_STR}/spatial/blank-spots", response_model=BlankSpotAnalysisResult, tags=["Spatial Calculations"])
def get_district_blank_spots(
    district_code: str = Query(..., description="kemendagri_code, e.g. 31.71.09 (Tebet)"),
    facility_type: str = Query("puskesmas_kelurahan", description="facility_type to analyze")
):
    """
    Calculates unserved areas ('blank spots') using PostGIS ST_Difference.
    Returns exact unserved area in km2, percentage coverage, and blank spot MultiPolygon GeoJSON.
    """
    try:
        result = PostGISSpatialEngine.calculate_blank_spots(district_code, facility_type)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class BlankSpotSimRequest(BaseModel):
    district_code: str
    facility_type: str
    hypothetical_coordinates: List[float] = Field(..., min_items=2, max_items=2, description="[longitude, latitude]")
    custom_radius_meters: Optional[int] = None

@app.post(f"{settings.API_V1_STR}/spatial/blank-spots/simulate-reduction", response_model=BlankSpotSimulationDelta, tags=["Spatial Calculations"])
def simulate_blank_spot_reduction(req: BlankSpotSimRequest):
    """
    Simulates how placing a new hypothetical amenity reduces the unserved blank spot polygon.
    Runs transiently in PostGIS memory without persisting to master database.
    """
    try:
        delta = PostGISSpatialEngine.simulate_blank_spot_reduction(
            district_code=req.district_code,
            facility_type=req.facility_type,
            hypothetical_coords=req.hypothetical_coordinates,
            custom_radius_meters=req.custom_radius_meters
        )
        return delta
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# 5. 4 Pillars Public Amenities
# -----------------------------------------------------------------------------
@app.get(f"{settings.API_V1_STR}/facilities", tags=["4 Pillars Public Amenities"])
def list_facilities(
    pillar: Optional[str] = Query(None, description="lifeline_health, education, urban_livability, mobility_connectivity"),
    facility_type: Optional[str] = None,
    district_code: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, le=500)
):
    """Lists public facilities with flexible filtering across all 4 Pillars."""
    query = """
        SELECT 
            f.source, f.source_id, f.name, f.pillar, f.category, f.facility_type,
            f.address, f.capacity, k.name as kecamatan_name, k.kemendagri_code as district_code,
            ST_X(f.coordinates) as longitude, ST_Y(f.coordinates) as latitude,
            f.metadata
        FROM public_facilities f
        LEFT JOIN kecamatan k ON k.id = f.kecamatan_id
        WHERE f.is_active = TRUE
    """
    params = []

    if pillar:
        query += " AND f.pillar = %s"
        params.append(pillar)

    if facility_type:
        query += " AND f.facility_type = %s"
        params.append(facility_type)

    if district_code:
        query += " AND (k.kemendagri_code = %s OR LOWER(k.name) = LOWER(%s))"
        params.extend([district_code, district_code])

    if search:
        query += " AND f.name ILIKE %s"
        params.append(f"%{search}%")

    query += " ORDER BY f.name LIMIT %s;"
    params.append(limit)

    with get_db_cursor() as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        return {
            "total": len(rows),
            "data_source": "OpenStreetMap contributors (ODbL), snapshot 2026-10-14",
            "facilities": rows
        }

# -----------------------------------------------------------------------------
# 6. What-If Scenario Simulation Engine
# -----------------------------------------------------------------------------
@app.post(f"{settings.API_V1_STR}/simulation/what-if", response_model=SimulationDeltaDTO, tags=["What-If Urban Simulation"])
def run_what_if_simulation(req: SimulationRequest):
    """
    Simulates hypothetical urban changes (population shock + hypothetical amenities)
    in an isolated memory sandbox without mutating master data.
    """
    with get_db_cursor() as cur:
        # 1. Fetch district baseline
        cur.execute("""
            SELECT id, kemendagri_code, name, population 
            FROM kecamatan
            WHERE kemendagri_code = %s OR LOWER(name) = LOWER(%s);
        """, (req.district_code, req.district_code))
        dist = cur.fetchone()

        if not dist:
            raise HTTPException(status_code=404, detail=f"District '{req.district_code}' not found.")

        dist_id = dist["id"]
        dist_name = dist["name"]
        baseline_pop = dist["population"]

        # 2. Fetch existing facility counts for this district
        cur.execute("""
            SELECT facility_type, COUNT(*) as cnt
            FROM public_facilities
            WHERE kecamatan_id = %s AND is_active = TRUE
            GROUP BY facility_type;
        """, (dist_id,))
        count_rows = cur.fetchall()
        existing_counts = {r["facility_type"]: r["cnt"] for r in count_rows}

        # 3. Fetch regulatory standards
        cur.execute("""
            SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference
            FROM regulatory_standards;
        """)
        standards = cur.fetchall()

    # 4. Compute delta via Deterministic Sandbox Engine
    delta_result = WhatIfSimulationEngine.compute_scenario_delta(
        district_code=dist["kemendagri_code"],
        district_name=dist_name,
        baseline_population=baseline_pop,
        existing_facility_counts=existing_counts,
        regulatory_standards=standards,
        pop_shock_pct=req.population_shock_percent,
        pop_shock_count=req.population_shock_count,
        staged_amenities=req.hypothetical_facilities
    )

    return delta_result

@app.post(f"{settings.API_V1_STR}/simulation/superblock", response_model=SuperblockImpactDTO, tags=["What-If Urban Simulation"])
def run_superblock_simulation(req: SuperblockSimulationRequest):
    """
    Simulates high-density superblock / apartment complex development.
    Parameter asumsi (belum diverifikasi ke Perda 31/2022): RTH 20%, retensi 150 mm/hari, KDB 50%.
    - Estimasi alokasi 20% luas lahan bruto untuk RTH publik (parameter asumsi)
    - Estimasi volume retensi 150 mm/hari Zero Delta Q (parameter asumsi)
    - Beban fasilitas pada sekolah dasar dan puskesmas kelurahan.
    """
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, kemendagri_code, name, population 
            FROM kecamatan
            WHERE kemendagri_code = %s OR LOWER(name) = LOWER(%s);
        """, (req.district_code, req.district_code))
        dist = cur.fetchone()

        if not dist:
            raise HTTPException(status_code=404, detail=f"District '{req.district_code}' not found.")

        dist_id = dist["id"]
        dist_name = dist["name"]
        baseline_pop = dist["population"]

        cur.execute("""
            SELECT facility_type, COUNT(*) as cnt
            FROM public_facilities
            WHERE kecamatan_id = %s AND is_active = TRUE
            GROUP BY facility_type;
        """, (dist_id,))
        count_rows = cur.fetchall()
        existing_counts = {r["facility_type"]: r["cnt"] for r in count_rows}

        cur.execute("""
            SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference
            FROM regulatory_standards;
        """)
        standards = cur.fetchall()

    impact = WhatIfSimulationEngine.simulate_superblock_development(
        req=req,
        baseline_population=baseline_pop,
        district_name=dist_name,
        existing_facility_counts=existing_counts,
        regulatory_standards=standards
    )
    return impact

# -----------------------------------------------------------------------------
# 7. Regulatory Hybrid RAG (For Cognitive AI)
# -----------------------------------------------------------------------------
class HybridSearchRequest(BaseModel):
    query: str
    pillar: Optional[str] = None
    facility_type: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)

@app.post(
    f"{settings.API_V1_STR}/rag/search",
    tags=["Regulatory RAG"],
    summary="Pencarian leksikal (trigram + hashed bag-of-words + sinonim)"
)
def search_regulations(req: HybridSearchRequest):
    """
    Pencarian leksikal (trigram + hashed bag-of-words + sinonim) pada standar nasional dan regulasi tata ruang.
    Menggabungkan vektor fitur leksikal ter-hash via pgvector dan kemiripan trigram via Reciprocal Rank Fusion (RRF).
    Target endpoint aligned with README.md §13.
    """
    citations = HybridRegulationRetriever.search_regulations(
        query=req.query,
        pillar=req.pillar,
        facility_type=req.facility_type,
        top_k=req.top_k
    )
    markdown_summary = HybridRegulationRetriever.format_citations_markdown(citations)

    return {
        "query": req.query,
        "total_results": len(citations),
        "citations": [c.model_dump() for c in citations],
        "citations_markdown": markdown_summary
    }

@app.post(
    f"{settings.API_V1_STR}/rag/hybrid-search",
    tags=["Regulatory RAG"],
    summary="Pencarian leksikal (alias deprecated)",
    deprecated=True
)
def hybrid_search_regulations_alias(req: HybridSearchRequest, response: Response):
    """
    Deprecated alias for /api/v1/rag/search (README.md §13).
    """
    response.headers["Deprecation"] = "true"
    return search_regulations(req)

@app.get(f"{settings.API_V1_STR}/rag/legal-chunks", tags=["Regulatory RAG"])
def search_regulatory_chunks(
    query: Optional[str] = Query(None, description="Keywords to match legal provisions"),
    pillar: Optional[str] = None
):
    """Retrieves legal regulation chunks (SNI 03-1733-2004 & Perda RDTR) for verified legal grounds."""
    sql = """
        SELECT document_title, regulation_code, chapter, article_number,
               pillar, facility_type, content_text, metadata
        FROM regulatory_chunks
        WHERE 1=1
    """
    params = []

    if pillar:
        sql += " AND pillar = %s"
        params.append(pillar)

    if query:
        sql += " AND content_text ILIKE %s"
        params.append(f"%{query}%")

    sql += " LIMIT 20;"

    with get_db_cursor() as cur:
        cur.execute(sql, tuple(params) if params else None)
        rows = cur.fetchall()
        return {"total": len(rows), "chunks": rows}

# -----------------------------------------------------------------------------
# 8. Cognitive Spatial AI Assistant (Qwen 2.5 14B)
# -----------------------------------------------------------------------------
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    AgentChatResponse
)

agent_orchestrator = CognitiveSpatialAgentOrchestrator()

@app.post(f"{settings.API_V1_STR}/chat", response_model=AgentChatResponse, tags=["Cognitive Spatial AI"])
def chat_with_spatial_agent(req: AgentChatRequest):
    """
    Interactive conversation with Cognitive Spatial AI Assistant.
    Powered by local LLM (Qwen 2.5 14B).
    Performs deterministic text-to-spatial tool calling, regulation citations,
    and returns Map Action events for dual-view sync.
    Target endpoint aligned with README.md §13.
    """
    response = agent_orchestrator.process_chat(req)
    return response

@app.post(
    f"{settings.API_V1_STR}/chat/conversation",
    response_model=AgentChatResponse,
    tags=["Cognitive Spatial AI"],
    deprecated=True
)
def chat_with_spatial_agent_alias(req: AgentChatRequest, response: Response):
    """
    Deprecated alias for /api/v1/chat (README.md §13).
    """
    response.headers["Deprecation"] = "true"
    return chat_with_spatial_agent(req)

# -----------------------------------------------------------------------------
# 9. Observability & Watchdog
# -----------------------------------------------------------------------------
from watchdog.agent import get_watchdog_telemetry

@app.get(f"{settings.API_V1_STR}/watchdog/telemetry", tags=["Observability & Watchdog"])
def get_system_telemetry():
    """Returns live hardware (GPU VRAM, Temp, Power), container status & AI status."""
    return get_watchdog_telemetry()

@app.get(f"{settings.API_V1_STR}/watchdog/incidents", tags=["Observability & Watchdog"])
def get_incident_audit_trail(limit: int = Query(20, le=100)):
    """Returns historical incident audit ledger from incident_logs table."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, incident_type, severity, target_service, action_taken,
                   status, gpu_temperature_celsius, vram_used_mb, error_payload, created_at
            FROM incident_logs
            ORDER BY created_at DESC
            LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()
        return {"total": len(rows), "incidents": rows}

# -----------------------------------------------------------------------------
# 10. Frontend UI & Static Assets Serving
# -----------------------------------------------------------------------------
import os
from fastapi.staticfiles import StaticFiles

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_FRONTEND_DIR = os.path.join(_BASE_DIR, "frontend")
_DATA_DIR = os.path.join(_BASE_DIR, "pipeline", "data")

if os.path.exists(_DATA_DIR):
    app.mount("/data", StaticFiles(directory=_DATA_DIR), name="data")

if os.path.exists(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")



