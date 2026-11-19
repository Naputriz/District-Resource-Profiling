"""
Districts compliance scorecards and public amenities endpoints.
"""

import json
import re
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from backend.app.core.config import settings
from backend.app.api.deps import get_db_cursor, get_redis_client
from backend.app.api.routers.regions import (
    get_province_population_meta,
    get_region_meta,
    is_province_served,
)
from backend.app.engine.spatial import (
    resolve_district_record,
    resolve_district_candidates,
    format_ambiguous_district_detail,
)

router = APIRouter()

_UNAVAILABLE_PROVINCE_DETAIL = "Data wilayah ini belum tersedia (rencana v1.1)"


def _parse_json_field(val):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


def _finalize_districts_response(
    raw_districts,
    source: str,
    avail_src: str,
    province_code: Optional[str] = None,
) -> dict:
    prov = str(province_code or settings.DEFAULT_PROVINCE_CODE).strip()
    prov_pop_note, prov_pop_src, prov_pop_verif = get_province_population_meta(prov)

    results = (
        [dict(v) for v in raw_districts.values()]
        if isinstance(raw_districts, dict)
        else [dict(r) for r in raw_districts]
    )
    for r in results:
        row_note, row_src, row_verif = get_province_population_meta(
            prov,
            r.get("population_source"),
            r.get("population_verification_status"),
        )
        r["population_note"] = row_note
        r["population_source"] = row_src
        r["population_verification_status"] = row_verif

        cov = _parse_json_field(r.get("coverage"))
        if cov is not None:
            r["coverage"] = cov
        else:
            r.pop("coverage", None)

        comp = r.get("composite_livability_score")
        if comp is None:
            r["score_status"] = "Data tidak memadai"
            r["rank"] = None
            if not r.get("composite_note"):
                r["composite_note"] = "Data tidak memadai"
        else:
            r["score_status"] = "Tersedia"

    scored = [r for r in results if r.get("composite_livability_score") is not None]
    scored_sorted = sorted(
        scored,
        key=lambda x: (-float(x["composite_livability_score"]), str(x.get("kemendagri_code") or "")),
    )
    for idx, r in enumerate(scored_sorted, start=1):
        r["rank"] = idx

    avg_score = (
        round(sum(float(r["composite_livability_score"]) for r in scored) / len(scored), 2)
        if scored
        else None
    )

    return {
        "source": source,
        "province_code": prov,
        "availability_source": avail_src,
        "population_note": prov_pop_note,
        "population_source": prov_pop_src,
        "population_verification_status": prov_pop_verif,
        "average_composite_score": avg_score,
        "scored_districts_count": len(scored),
        "insufficient_data_districts_count": len(results) - len(scored),
        "districts": results,
    }


@router.get(f"{settings.API_V1_STR}/districts", tags=["Districts & Compliance"])
def list_districts(
    province_code: Optional[str] = Query(
        None, description="Kode provinsi Kemendagri, default 31 (DKI Jakarta)"
    )
):
    """Lists all Kecamatan in the specified province with demographic stats and compliance scorecards."""
    target_province = str(province_code).strip() if province_code else settings.DEFAULT_PROVINCE_CODE

    if not is_province_served(target_province):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)

    from backend.app.engine.standards_availability import get_current_availability_source

    avail_src = get_current_availability_source()

    # Check Redis cache first (province-scoped key; legacy fallback only for default province)
    try:
        r_client = get_redis_client()
        if r_client:
            cached = r_client.get(f"cache:compliance:scores:{target_province}")
            if not cached and target_province == settings.DEFAULT_PROVINCE_CODE:
                cached = r_client.get("cache:compliance:scores")
            if cached:
                dist_list = json.loads(cached)
                if dist_list:
                    return _finalize_districts_response(
                        dist_list, "cache", avail_src, province_code=target_province
                    )
    except Exception:
        pass

    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT
                k.kemendagri_code, k.bps_code, k.name, c.name as city_name,
                p.kemendagri_code as province_code, p.name as province_name,
                k.population, k.area_km2, k.density_per_km2,
                k.population_source, k.population_verification_status,
                s.health_score, s.education_score, s.livability_score,
                s.mobility_score, s.composite_livability_score, s.composite_note,
                s.metrics_payload, s.coverage
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            LEFT JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = %s
            ORDER BY k.kemendagri_code;
            """,
            (target_province,),
        )
        results = [dict(r) for r in cur.fetchall()]
        if not results:
            raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)
        return _finalize_districts_response(
            results, "database", avail_src, province_code=target_province
        )


@router.get(
    f"{settings.API_V1_STR}/districts/{{district_code}}",
    tags=["Districts & Compliance"],
)
def get_district_detail(
    district_code: str,
    province_code: Optional[str] = Query(
        None, description="Opsional: kode provinsi untuk resolusi nama kecamatan"
    ),
):
    """Returns single district compliance scorecard and deficit breakdown."""
    record, err = resolve_district_record(district_code, province_code=province_code)
    if not record:
        if err == "ambiguous":
            candidates = resolve_district_candidates(district_code, province_code=province_code)
            raise HTTPException(
                status_code=400,
                detail=format_ambiguous_district_detail(district_code, candidates),
            )
        code_clean = district_code.strip()
        if re.match(r"^\d{2}\.\d{2}", code_clean) and not is_province_served(code_clean[:2]):
            raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)
        raise HTTPException(
            status_code=404, detail=f"Kecamatan '{district_code}' not found."
        )

    rec_prov = record.get("province_code")
    if rec_prov and not is_province_served(rec_prov):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)

    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT
                k.id, k.kemendagri_code, k.bps_code, k.name, c.name as city_name,
                p.kemendagri_code as province_code, p.name as province_name,
                k.population, k.area_km2, k.density_per_km2,
                k.population_source, k.population_verification_status,
                s.health_score, s.education_score, s.livability_score,
                s.mobility_score, s.composite_livability_score, s.composite_note,
                s.metrics_payload, s.coverage,
                ST_AsGeoJSON(k.boundary)::json as boundary_geojson
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
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
        eff_prov = str(
            data.get("province_code") or rec_prov or settings.DEFAULT_PROVINCE_CODE
        )
        if not is_province_served(eff_prov):
            raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)

        pop_note, pop_src, pop_verif = get_province_population_meta(
            eff_prov,
            data.get("population_source"),
            data.get("population_verification_status"),
        )
        data["province_code"] = eff_prov
        data["population_note"] = pop_note
        data["population_source"] = pop_src
        data["population_verification_status"] = pop_verif

        from backend.app.engine.standards_availability import (
            get_current_availability_source,
        )

        data["availability_source"] = get_current_availability_source()

        cov = _parse_json_field(data.get("coverage"))
        if cov is not None:
            data["coverage"] = cov
        else:
            data.pop("coverage", None)

        data["score_status"] = (
            "Data tidak memadai"
            if data.get("composite_livability_score") is None
            else "Tersedia"
        )

        data["metrics_payload"] = _parse_json_field(data.get("metrics_payload"))

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

        if data.get("composite_livability_score") is None and not data.get("composite_note"):
            data["composite_note"] = "Data tidak memadai"

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
    if province_code is not None:
        req_prov = str(province_code).strip()
        if not is_province_served(req_prov):
            raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)

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
    eff_prov = str(province_code).strip() if province_code else settings.DEFAULT_PROVINCE_CODE

    if district_code:
        record, err = resolve_district_record(district_code, province_code=province_code)
        if not record:
            if err == "ambiguous":
                candidates = resolve_district_candidates(district_code, province_code=province_code)
                raise HTTPException(
                    status_code=400,
                    detail=format_ambiguous_district_detail(district_code, candidates),
                )
            code_clean = district_code.strip()
            if re.match(r"^\d{2}\.\d{2}", code_clean) and not is_province_served(code_clean[:2]):
                raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)
            raise HTTPException(
                status_code=404,
                detail=f"Kecamatan '{district_code}' not found.",
            )
        rec_prov = record.get("province_code")
        if rec_prov and not is_province_served(rec_prov):
            raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)
        if rec_prov:
            eff_prov = str(rec_prov)
        query += " AND f.kecamatan_id = %s"
        params.append(record["id"])
    else:
        if not is_province_served(eff_prov):
            raise HTTPException(status_code=404, detail=_UNAVAILABLE_PROVINCE_DETAIL)
        query += " AND p.kemendagri_code = %s"
        params.append(eff_prov)

    if pillar:
        query += " AND f.pillar = %s"
        params.append(pillar)

    if facility_type:
        query += " AND f.facility_type = %s"
        params.append(facility_type)

    if search:
        query += " AND f.name ILIKE %s"
        params.append(f"%{search}%")

    query += " ORDER BY f.name LIMIT %s;"
    params.append(limit)

    region_meta = get_region_meta(eff_prov)
    osm_date = (region_meta.get("snapshot_dates") or {}).get("osm", "2026-10-14")

    with get_db_cursor() as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        return {
            "total": len(rows),
            "province_code": eff_prov,
            "data_source": f"OpenStreetMap contributors (ODbL), snapshot {osm_date}",
            "facilities": rows,
        }
