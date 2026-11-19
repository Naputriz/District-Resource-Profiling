"""
Districts compliance scorecards and public amenities endpoints.
"""

import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from backend.app.core.config import settings
from backend.app.api.deps import get_db_cursor, get_redis_client
from backend.app.engine.spatial import resolve_district_record, resolve_district_candidates

router = APIRouter()


@router.get(f"{settings.API_V1_STR}/districts", tags=["Districts & Compliance"])
def list_districts(
    province_code: Optional[str] = Query(
        None, description="Kode provinsi Kemendagri, default 31 (DKI Jakarta)"
    )
):
    """Lists all Kecamatan in the specified province with demographic stats and compliance scorecards."""
    target_province = str(province_code).strip() if province_code else settings.DEFAULT_PROVINCE_CODE

    # Multi-region: this week only province 31 has data loaded
    if target_province != settings.DEFAULT_PROVINCE_CODE:
        raise HTTPException(
            status_code=404,
            detail="Data wilayah ini belum tersedia (rencana v1.1)"
        )

    from backend.app.engine.standards_availability import get_current_availability_source

    avail_src = get_current_availability_source()

    # Check Redis cache first (province-scoped key, fallback to legacy)
    try:
        r_client = get_redis_client()
        if r_client:
            cached = r_client.get(f"cache:compliance:scores:{target_province}") or r_client.get("cache:compliance:scores")
            if cached:
                dist_list = json.loads(cached)
                for d in dist_list:
                    d["population_note"] = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)"
                return {
                    "source": "cache",
                    "availability_source": avail_src,
                    "population_note": "Sumber data penduduk belum terverifikasi (TODO-VERIFY)",
                    "districts": dist_list,
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
            JOIN provinces p ON p.id = c.province_id
            LEFT JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = %s
            ORDER BY k.kemendagri_code;
        """, (target_province,))
        results = [dict(r) for r in cur.fetchall()]
        for r in results:
            r["population_note"] = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)"
        return {
            "source": "database",
            "availability_source": avail_src,
            "population_note": "Sumber data penduduk belum terverifikasi (TODO-VERIFY)",
            "districts": results,
        }


@router.get(
    f"{settings.API_V1_STR}/districts/{{district_code}}",
    tags=["Districts & Compliance"],
)
def get_district_detail(district_code: str):
    """Returns single district compliance scorecard and deficit breakdown."""
    record, err = resolve_district_record(district_code)
    if not record:
        if err == "ambiguous":
            candidates = resolve_district_candidates(district_code)
            cand_codes = ", ".join(c["kemendagri_code"] for c in candidates)
            raise HTTPException(
                status_code=400,
                detail=f"Nama kecamatan '{district_code}' ambigu (ditemukan {len(candidates)} wilayah: {cand_codes}). Mohon tentukan kode kecamatan spesifik."
            )
        raise HTTPException(
            status_code=404, detail=f"Kecamatan '{district_code}' not found."
        )

    with get_db_cursor() as cur:
        cur.execute(
            """
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
            WHERE k.id = %s;
        """,
            (record["id"],),
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=404, detail=f"Kecamatan '{district_code}' not found."
            )

        data = dict(row)
        data["population_note"] = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)"
        from backend.app.engine.standards_availability import (
            get_current_availability_source,
        )

        data["availability_source"] = get_current_availability_source()

        if isinstance(data.get("metrics_payload"), str):
            try:
                data["metrics_payload"] = json.loads(data["metrics_payload"])
            except Exception:
                pass

        if isinstance(data.get("metrics_payload"), list):
            from backend.app.engine.standards_availability import (
                calculate_pillar_and_composite_scores,
            )

            scores_breakdown = calculate_pillar_and_composite_scores(
                data["metrics_payload"]
            )
            data["pillar_scores"] = scores_breakdown["pillar_scores"]
            data["composite_note"] = (
                data.get("composite_note") or scores_breakdown["composite_note"]
            )
            data["availability_source"] = scores_breakdown.get(
                "availability_source", data["availability_source"]
            )

        return data


@router.get(f"{settings.API_V1_STR}/facilities", tags=["4 Pillars Public Amenities"])
def list_facilities(
    pillar: Optional[str] = Query(
        None,
        description="lifeline_health, education, urban_livability, mobility_connectivity",
    ),
    facility_type: Optional[str] = None,
    district_code: Optional[str] = None,
    province_code: Optional[str] = Query(
        None, description="Kode provinsi, default 31 (DKI Jakarta)"
    ),
    search: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    """Lists public facilities with flexible filtering across all 4 Pillars."""
    target_province = str(province_code).strip() if province_code else settings.DEFAULT_PROVINCE_CODE
    if target_province != settings.DEFAULT_PROVINCE_CODE:
        raise HTTPException(
            status_code=404,
            detail="Data wilayah ini belum tersedia (rencana v1.1)"
        )

    query = """
        SELECT 
            f.source, f.source_id, f.name, f.pillar, f.category, f.facility_type,
            f.address, f.capacity, k.name as kecamatan_name, k.kemendagri_code as district_code,
            ST_X(f.coordinates) as longitude, ST_Y(f.coordinates) as latitude,
            f.metadata
        FROM public_facilities f
        LEFT JOIN kecamatan k ON k.id = f.kecamatan_id
        LEFT JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
        LEFT JOIN provinces p ON p.id = c.province_id
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
        record, err = resolve_district_record(district_code, province_code=province_code)
        if not record:
            if err == "ambiguous":
                candidates = resolve_district_candidates(district_code, province_code=province_code)
                cand_codes = ", ".join(c["kemendagri_code"] for c in candidates)
                raise HTTPException(
                    status_code=400,
                    detail=f"Nama kecamatan '{district_code}' ambigu (ditemukan {len(candidates)} wilayah: {cand_codes}). Mohon tentukan kode kecamatan spesifik."
                )
            raise HTTPException(
                status_code=404,
                detail=f"Kecamatan '{district_code}' not found."
            )
        query += " AND f.kecamatan_id = %s"
        params.append(record["id"])

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
            "facilities": rows,
        }
