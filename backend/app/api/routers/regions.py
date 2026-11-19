"""
Multi-region configuration and availability endpoints.
Provides region metadata: center, zoom, bbox, UTM SRID, data sources, snapshot dates,
population source, and runtime Active/Staging/Planned status computed from ACTIVE_PROVINCES + DB.
"""

import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api.deps import get_db_cursor
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

_CACHE_TTL_SECONDS = 60.0
_DB_STATS_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "db_name": None,
    "data": None,
}


class CoverageSummary(BaseModel):
    total: int = 0
    scored: int = 0
    gated: int = 0


class RegionInfo(BaseModel):
    province_code: str
    name: str
    has_data: bool
    status: str
    center: List[float]  # [lat, lon]
    zoom: int
    bbox: List[float]  # [min_lon, min_lat, max_lon, max_lat]
    utm_srid: int
    total_districts: int
    geojson_url: Optional[str] = None
    data_sources: Optional[Dict[str, str]] = None
    snapshot_dates: Optional[Dict[str, str]] = None
    population_source: Optional[str] = None
    coverage_summary: Optional[CoverageSummary] = None


REGIONS_CATALOG: Dict[str, Dict[str, Any]] = {
    "31": {
        "province_code": "31",
        "name": "DKI Jakarta",
        "has_data": True,
        "status": "Active",
        "center": [-6.2088, 106.8456],
        "zoom": 11,
        "bbox": [106.5100, -6.3800, 106.9800, -5.5400],
        "utm_srid": 32748,
        "total_districts": 44,
        "geojson_url": "/data/boundaries/jakarta_44_kecamatan.geojson",
        "population_source": "BPS 2024",
        "data_sources": {
            "boundaries": "BPS / Kemendagri GeoJSON (SakifAbdillah/jakartaKecamatanGeoJSON)",
            "demographics": "BPS Provinsi DKI Jakarta 2024",
            "facilities": "OpenStreetMap contributors (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-10-14",
        },
    },
    "32": {
        "province_code": "32",
        "name": "Jawa Barat",
        "has_data": False,
        "status": "Planned",
        "center": [-6.921, 107.6039],
        "zoom": 9,
        "bbox": [106.3703, -7.821, 108.8469, -5.9181],
        "utm_srid": 32748,
        "total_districts": 627,
        "geojson_url": "/data/boundaries/32_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "33": {
        "province_code": "33",
        "name": "Jawa Tengah",
        "has_data": False,
        "status": "Planned",
        "center": [-7.2583, 110.1987],
        "zoom": 9,
        "bbox": [108.5559, -8.2119, 111.6914, -5.7257],
        "utm_srid": 32749,
        "total_districts": 573,
        "geojson_url": "/data/boundaries/33_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "34": {
        "province_code": "34",
        "name": "DI Yogyakarta",
        "has_data": False,
        "status": "Planned",
        "center": [-7.895, 110.4458],
        "zoom": 10,
        "bbox": [110.003, -8.204, 110.8346, -7.5419],
        "utm_srid": 32749,
        "total_districts": 78,
        "geojson_url": "/data/boundaries/34_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "35": {
        "province_code": "35",
        "name": "Jawa Timur",
        "has_data": False,
        "status": "Planned",
        "center": [-7.7197, 112.7339],
        "zoom": 8,
        "bbox": [110.8987, -8.7804, 116.2702, -5.0489],
        "utm_srid": 32749,
        "total_districts": 666,
        "geojson_url": "/data/boundaries/35_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "36": {
        "province_code": "36",
        "name": "Banten",
        "has_data": False,
        "status": "Planned",
        "center": [-6.4563, 106.1088],
        "zoom": 9,
        "bbox": [105.0998, -7.0168, 106.7799, -5.8074],
        "utm_srid": 32748,
        "total_districts": 155,
        "geojson_url": "/data/boundaries/36_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
}


def clear_regions_cache() -> None:
    """Clears the in-process DB stats cache (useful in tests)."""
    _DB_STATS_CACHE["ts"] = 0.0
    _DB_STATS_CACHE["db_name"] = None
    _DB_STATS_CACHE["data"] = None


def get_region_meta(province_code: Optional[str]) -> Dict[str, Any]:
    """Returns static metadata entry for a province code, defaulting to DEFAULT_PROVINCE_CODE."""
    code = str(province_code or settings.DEFAULT_PROVINCE_CODE).strip()
    return REGIONS_CATALOG.get(code) or REGIONS_CATALOG[settings.DEFAULT_PROVINCE_CODE]


def get_province_population_meta(
    province_code: Optional[str],
    db_source: Optional[str] = None,
    db_verif: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Returns (population_note, population_source, population_verification_status)
    for the given province without hardcoding TODO-VERIFY.
    """
    code = str(province_code or settings.DEFAULT_PROVINCE_CODE).strip()
    if code == "31":
        note = "BPS 2024"
        src = db_source or "BPS 2024"
        verif = db_verif or "bps_2024"
        return (note, src, verif)
    meta = REGIONS_CATALOG.get(code, {})
    default_src = meta.get("population_source") or "Estimasi model WorldPop R2025A 2024"
    return (default_src, db_source or default_src, db_verif or "model_estimate")


def _get_db_province_stats(force_refresh: bool = False) -> Optional[Dict[str, Dict[str, int]]]:
    """
    Queries per-province kecamatan counts (total, scored, gated) from PostgreSQL,
    cached in-process for 60 seconds per database name.
    Returns None if the database is unreachable.
    """
    now = time.monotonic()
    db_name = settings.POSTGRES_DB
    if (
        not force_refresh
        and _DB_STATS_CACHE["data"] is not None
        and _DB_STATS_CACHE["db_name"] == db_name
        and (now - _DB_STATS_CACHE["ts"]) < _CACHE_TTL_SECONDS
    ):
        return _DB_STATS_CACHE["data"]

    try:
        with get_db_cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.kemendagri_code AS province_code,
                    COUNT(k.id)::int AS total_kec,
                    COUNT(s.id) FILTER (WHERE s.composite_livability_score IS NOT NULL)::int AS scored_kec,
                    COUNT(s.id) FILTER (WHERE s.composite_livability_score IS NULL AND k.id IS NOT NULL)::int AS gated_kec
                FROM provinces p
                JOIN kabupaten_kota c ON c.province_id = p.id
                JOIN kecamatan k ON k.kabupaten_kota_id = c.id
                LEFT JOIN district_compliance_scores s ON s.district_id = k.id
                GROUP BY p.kemendagri_code;
                """
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.warning("Failed to query region stats from DB: %s", exc)
        return None

    stats: Dict[str, Dict[str, int]] = {}
    for r in rows:
        pcode = r.get("province_code")
        if pcode:
            stats[str(pcode)] = {
                "total": int(r.get("total_kec") or 0),
                "scored": int(r.get("scored_kec") or 0),
                "gated": int(r.get("gated_kec") or 0),
            }

    _DB_STATS_CACHE["ts"] = now
    _DB_STATS_CACHE["db_name"] = db_name
    _DB_STATS_CACHE["data"] = stats
    return stats


def compute_region_status(
    province_code: str,
    db_stats: Optional[Dict[str, Dict[str, int]]],
    active_provinces: List[str],
) -> Tuple[bool, str, Optional[CoverageSummary]]:
    """Computes (has_data, status, coverage_summary) from DB row counts and ACTIVE_PROVINCES."""
    if db_stats is None:
        # Offline fallback (e.g. unit tests with DB unreachable)
        is_default_active = (
            province_code == settings.DEFAULT_PROVINCE_CODE
            and province_code in active_provinces
        )
        if is_default_active:
            return (True, "Active", None)
        return (False, "Planned", None)

    stats = db_stats.get(province_code)
    has_db_rows = bool(stats and stats.get("total", 0) > 0)
    if not has_db_rows:
        return (False, "Planned", None)

    summary = CoverageSummary(
        total=stats["total"],
        scored=stats["scored"],
        gated=stats["gated"],
    )
    if province_code in active_provinces:
        return (True, "Active", summary)
    return (True, "Staging", summary)


def is_province_served(province_code: str) -> bool:
    """
    Returns True iff `province_code` is in ACTIVE_PROVINCES AND has kecamatan rows in DB.
    Falls back to checking ACTIVE_PROVINCES == default when DB is unreachable in unit tests.
    """
    code = str(province_code).strip()
    active_list = settings.active_provinces
    if code not in active_list:
        return False
    db_stats = _get_db_province_stats()
    if db_stats is None:
        return code == settings.DEFAULT_PROVINCE_CODE
    stats = db_stats.get(code)
    return bool(stats and stats.get("total", 0) > 0)


def _build_region_entry(
    code: str,
    base: Dict[str, Any],
    db_stats: Optional[Dict[str, Dict[str, int]]],
    active_provinces: List[str],
) -> Dict[str, Any]:
    has_data, status, coverage_summary = compute_region_status(
        code, db_stats, active_provinces
    )
    entry = dict(base)
    entry["has_data"] = has_data
    entry["status"] = status
    entry["coverage_summary"] = coverage_summary
    if status == "Planned":
        entry["geojson_url"] = None
    return entry


@router.get(
    f"{settings.API_V1_STR}/regions",
    response_model=List[RegionInfo],
    tags=["Multi-Region Support"],
)
def list_regions():
    """
    Returns list of supported provinces with runtime availability status
    ('Active', 'Staging', or 'Planned'), map center/zoom, bounding box,
    UTM SRID, data sources, population source, and DB coverage summary.
    """
    db_stats = _get_db_province_stats()
    active_list = settings.active_provinces
    return [
        _build_region_entry(code, base, db_stats, active_list)
        for code, base in REGIONS_CATALOG.items()
    ]


@router.get(
    f"{settings.API_V1_STR}/regions/{{province_code}}",
    response_model=RegionInfo,
    tags=["Multi-Region Support"],
)
def get_region_detail(province_code: str):
    """
    Returns configuration and status for a specific active province.
    Returns 404 with explanatory message if province is not Active.
    """
    code = province_code.strip()
    base = REGIONS_CATALOG.get(code)
    if not base:
        raise HTTPException(
            status_code=404,
            detail="Data wilayah ini belum tersedia (rencana v1.1)",
        )

    db_stats = _get_db_province_stats()
    active_list = settings.active_provinces
    entry = _build_region_entry(code, base, db_stats, active_list)

    if entry["status"] != "Active":
        raise HTTPException(
            status_code=404,
            detail="Data wilayah ini belum tersedia (rencana v1.1)",
        )

    return entry
