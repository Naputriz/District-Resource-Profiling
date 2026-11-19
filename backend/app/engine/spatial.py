"""
Deterministic PostGIS Spatial Engine.
Performs 100% mathematically verified spatial calculations:
- Metric UTM buffer generation parameterized per region's UTM SRID (e.g. Zone 48S / EPSG:32748 for DKI Jakarta).
- Exact unserved blank spot polygon generation: ST_Difference(boundary, ST_Union(buffers)).
- Blank spot area reduction simulation for hypothetical amenities.
- Strict Rule #1 adherence: No spatial math done by LLM.
"""

import json
import math
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel
from backend.app.core.db import get_db_cursor
from backend.app.core.config import settings

logger = logging.getLogger(__name__)


def calculate_utm_zone(longitude: float) -> int:
    """
    Computes UTM zone number from longitude (-180.0 to 180.0).
    Formula: int(math.floor((longitude + 180.0) / 6.0)) + 1
    Valid zones: 1 to 60.
    Citation: NIMA Technical Report TR8350.2 / EPSG Geodetic Parameter Dataset.
    """
    zone = int(math.floor((float(longitude) + 180.0) / 6.0)) + 1
    if zone > 60:
        zone = 60
    if zone < 1:
        zone = 1
    return zone


def calculate_utm_srid(longitude: float, latitude: float) -> int:
    """
    Computes EPSG code for UTM zone from longitude and latitude.
    Standard:
    - Northern Hemisphere (latitude >= 0.0): EPSG = 32600 + zone
    - Southern Hemisphere (latitude < 0.0): EPSG = 32700 + zone
    Citation: NIMA Technical Report TR8350.2, "DoD World Geodetic System 1984" /
              EPSG Geodetic Parameter Dataset.
    Examples:
    - Jakarta  (106.8456, -6.2088) -> Zone 48S -> EPSG:32748
    - Surabaya (112.7508, -7.2575) -> Zone 49S -> EPSG:32749
    - Medan     (98.6722,  3.5952) -> Zone 47N -> EPSG:32647
    - Jayapura (140.7181, -2.5337) -> Zone 54S -> EPSG:32754
    """
    zone = calculate_utm_zone(longitude)
    if float(latitude) < 0.0:
        return 32700 + zone
    else:
        return 32600 + zone


def resolve_district_candidates(
    identifier: str,
    province_code: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Returns all matching districts for identifier (by Kemendagri code or name)."""
    if not identifier:
        return []

    target = str(identifier).strip()
    clean_name = re.sub(r"^(kecamatan|kec\.)\s+", "", target, flags=re.IGNORECASE).strip()
    is_code = bool(re.match(r"^\d{2}(\.\d{2})+(\.\d{2,4})?$", target))

    with get_db_cursor() as cur:
        if is_code:
            cur.execute("""
                SELECT k.id, k.kemendagri_code, k.bps_code, k.name, k.population,
                       k.area_km2, k.density_per_km2, COALESCE(k.utm_srid, 32748) as utm_srid,
                       c.name as city_name, p.name as province_name, p.kemendagri_code as province_code
                FROM kecamatan k
                JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                JOIN provinces p ON p.id = c.province_id
                WHERE k.kemendagri_code = %s;
            """, (target,))
            row = cur.fetchone()
            return [dict(row)] if row else []

        # Search by name scoped to province
        prov = province_code or settings.DEFAULT_PROVINCE_CODE
        cur.execute("""
            SELECT k.id, k.kemendagri_code, k.bps_code, k.name, k.population,
                   k.area_km2, k.density_per_km2, COALESCE(k.utm_srid, 32748) as utm_srid,
                   c.name as city_name, p.name as province_name, p.kemendagri_code as province_code
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE (LOWER(k.name) = LOWER(%s) OR LOWER(k.name) = LOWER(%s))
              AND (%s IS NULL OR p.kemendagri_code = %s);
        """, (target, clean_name, prov, prov))
        return [dict(r) for r in cur.fetchall()]


def resolve_district_record(
    identifier: str,
    province_code: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Resolves district record deterministically per TODO-3:
    1. If identifier matches Kemendagri code format, looks up by canonical kemendagri_code.
    2. If identifier is a name, scopes by province_code (default settings.DEFAULT_PROVINCE_CODE).
    3. If multiple records match (>1), returns (None, 'ambiguous') (no guessing).
    4. If no records match, returns (None, 'not_found').
    """
    if not identifier:
        return None, "not_found"

    target = str(identifier).strip()
    clean_name = re.sub(r"^(kecamatan|kec\.)\s+", "", target, flags=re.IGNORECASE).strip()
    is_code = bool(re.match(r"^\d{2}(\.\d{2})+(\.\d{2,4})?$", target))

    with get_db_cursor() as cur:
        if is_code:
            cur.execute("""
                SELECT k.id, k.kemendagri_code, k.bps_code, k.name, k.population,
                       k.area_km2, k.density_per_km2, COALESCE(k.utm_srid, 32748) as utm_srid,
                       c.name as city_name, p.name as province_name, p.kemendagri_code as province_code
                FROM kecamatan k
                JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                JOIN provinces p ON p.id = c.province_id
                WHERE k.kemendagri_code = %s;
            """, (target,))
            row = cur.fetchone()
            if row:
                return dict(row), None
            return None, "not_found"

        # Search by name scoped to province
        prov = province_code or settings.DEFAULT_PROVINCE_CODE
        cur.execute("""
            SELECT k.id, k.kemendagri_code, k.bps_code, k.name, k.population,
                   k.area_km2, k.density_per_km2, COALESCE(k.utm_srid, 32748) as utm_srid,
                   c.name as city_name, p.name as province_name, p.kemendagri_code as province_code
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE (LOWER(k.name) = LOWER(%s) OR LOWER(k.name) = LOWER(%s))
              AND (%s IS NULL OR p.kemendagri_code = %s);
        """, (target, clean_name, prov, prov))
        rows = [dict(r) for r in cur.fetchall()]

        if len(rows) == 1:
            return rows[0], None
        elif len(rows) > 1:
            logger.warning(f"Ambiguous district name '{identifier}': found {len(rows)} matching districts in province '{prov}'.")
            return None, "ambiguous"
        else:
            return None, "not_found"

class BlankSpotAnalysisResult(BaseModel):
    district_code: str
    district_name: str
    facility_type: str
    pillar: str
    service_radius_meters: int
    district_area_km2: float
    served_area_km2: float
    unserved_area_km2: float
    coverage_percentage: float
    coverage_pct: float
    coverage_pct_without_neighbours: float
    facilities_inside: int
    facilities_from_neighbours: int
    cross_border_scope: str = "DKI Jakarta only"
    blank_spot_geojson: Dict[str, Any] # GeoJSON Feature or MultiPolygon
    bps_area_km2: Optional[float] = None
    area_ratio: Optional[float] = None
    area_note: Optional[str] = None

class BlankSpotSimulationDelta(BaseModel):
    district_code: str
    facility_type: str
    baseline_unserved_km2: float
    simulated_unserved_km2: float
    area_recovered_km2: float
    coverage_improvement_pct: float
    cross_border_scope: str = "DKI Jakarta only"
    simulated_blank_spot_geojson: Dict[str, Any]

class PostGISSpatialEngine:
    @staticmethod
    def get_district_boundary_geojson(district_code: str) -> Optional[Dict[str, Any]]:
        """Returns standard GeoJSON geometry for a given district."""
        record, err = resolve_district_record(district_code)
        if not record:
            if err == "ambiguous":
                candidates = resolve_district_candidates(district_code)
                cand_codes = ", ".join(c["kemendagri_code"] for c in candidates)
                raise ValueError(
                    f"Nama kecamatan '{district_code}' ambigu (ditemukan {len(candidates)} wilayah: {cand_codes}). Mohon tentukan kode kecamatan spesifik."
                )
            return None

        with get_db_cursor() as cur:
            cur.execute("""
                SELECT ST_AsGeoJSON(boundary)::json as geojson
                FROM kecamatan
                WHERE id = %s;
            """, (record["id"],))
            row = cur.fetchone()
            return row["geojson"] if row else None

    @staticmethod
    def compute_facility_buffers(
        district_code: str,
        facility_type: Optional[str] = None,
        pillar: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Computes service buffers in regional UTM projection and projects back to WGS 84 GeoJSON.
        Uses exact regulatory standard radius per facility type.
        """
        record, err = resolve_district_record(district_code)
        if not record:
            if err == "ambiguous":
                candidates = resolve_district_candidates(district_code)
                cand_codes = ", ".join(c["kemendagri_code"] for c in candidates)
                raise ValueError(
                    f"Nama kecamatan '{district_code}' ambigu (ditemukan {len(candidates)} wilayah: {cand_codes}). Mohon tentukan kode kecamatan spesifik."
                )
            raise ValueError(f"District '{district_code}' not found.")

        sql = """
            SELECT 
                f.id, f.name, f.facility_type, f.pillar,
                s.service_radius_meters,
                ST_AsGeoJSON(
                    ST_Transform(
                        ST_Buffer(f.coordinates_utm, s.service_radius_meters),
                        4326
                    )
                )::json as buffer_geojson,
                ST_X(f.coordinates) as lon, ST_Y(f.coordinates) as lat
            FROM public_facilities f
            JOIN regulatory_standards s ON s.facility_type = f.facility_type
            WHERE f.kecamatan_id = %s
              AND f.is_active = TRUE
              AND s.service_radius_meters IS NOT NULL
        """
        params = [record["id"]]

        if facility_type:
            sql += " AND f.facility_type = %s"
            params.append(facility_type)

        if pillar:
            sql += " AND f.pillar = %s"
            params.append(pillar)

        features = []
        with get_db_cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

            for r in rows:
                features.append({
                    "type": "Feature",
                    "geometry": r["buffer_geojson"],
                    "properties": {
                        "facility_id": str(r["id"]),
                        "name": r["name"],
                        "facility_type": r["facility_type"],
                        "pillar": r["pillar"],
                        "radius_meters": r["service_radius_meters"],
                        "coordinates": [r["lon"], r["lat"]]
                    }
                })

        return {
            "type": "FeatureCollection",
            "district_code": record["kemendagri_code"],
            "total_buffers": len(features),
            "features": features
        }

    @staticmethod
    def calculate_blank_spots(
        district_code: str,
        facility_type: str = "puskesmas_kelurahan"
    ) -> BlankSpotAnalysisResult:
        """
        Calculates exact unserved polygons (blank spots) using PostGIS ST_Difference.
        ST_Difference(district_utm, ST_Union(amenity_buffer_utm)) -> Blank Spot MultiPolygon.
        """
        record, err = resolve_district_record(district_code)
        if not record:
            if err == "ambiguous":
                candidates = resolve_district_candidates(district_code)
                cand_codes = ", ".join(c["kemendagri_code"] for c in candidates)
                raise ValueError(
                    f"Nama kecamatan '{district_code}' ambigu (ditemukan {len(candidates)} wilayah: {cand_codes}). Mohon tentukan kode kecamatan spesifik."
                )
            raise ValueError(f"District '{district_code}' not found.")

        dist_id = record["id"]
        code = record["kemendagri_code"]
        name = record["name"]
        area_km2 = float(record["area_km2"])
        prov_code = record.get("province_code") or settings.DEFAULT_PROVINCE_CODE

        with get_db_cursor() as cur:
            # 1. Fetch regulatory radius
            cur.execute("""
                SELECT pillar, service_radius_meters as radius_m, scored
                FROM regulatory_standards
                WHERE facility_type = %s
                  AND (province_code IS NULL OR province_code = %s);
            """, (facility_type, prov_code))
            dist = cur.fetchone()
            if not dist:
                cur.execute("""
                    SELECT pillar, service_radius_meters as radius_m, scored
                    FROM regulatory_standards
                    WHERE facility_type = %s;
                """, (facility_type,))
                dist = cur.fetchone()

            radius_m = dist["radius_m"] if dist else None
            pillar = (dist["pillar"] if dist else None) or "lifeline_health"

            if radius_m is None or radius_m <= 0:
                raise ValueError(
                    f"Fasilitas '{facility_type}' tidak memiliki standar radius jangkauan layanan (tanpa blank spot)."
                )

            # 2. Compute spatial difference in metric UTM including cross-border reaching facilities
            spatial_query = """
                WITH district_geom AS (
                    SELECT id, boundary_utm, utm_srid, ST_Area(boundary_utm) / 1000000.0 as geom_area_km2
                    FROM kecamatan 
                    WHERE id = %s
                ),
                facilities_in_reach AS (
                    SELECT 
                        f.id,
                        f.kecamatan_id,
                        f.coordinates_utm,
                        (f.kecamatan_id = dg.id) as is_inside
                    FROM district_geom dg
                    CROSS JOIN public_facilities f
                    WHERE f.facility_type = %s
                      AND f.is_active = TRUE
                      AND f.utm_srid = dg.utm_srid
                      AND ST_DWithin(f.coordinates_utm, dg.boundary_utm, %s)
                ),
                counts AS (
                    SELECT 
                        COALESCE(COUNT(*) FILTER (WHERE is_inside), 0) as inside_cnt,
                        COALESCE(COUNT(*) FILTER (WHERE NOT is_inside), 0) as neighbour_cnt
                    FROM facilities_in_reach
                ),
                inside_buffer AS (
                    SELECT ST_Union(ST_Buffer(coordinates_utm, %s)) as ubuf
                    FROM facilities_in_reach WHERE is_inside
                ),
                all_buffer AS (
                    SELECT ST_Union(ST_Buffer(coordinates_utm, %s)) as ubuf
                    FROM facilities_in_reach
                ),
                diffs AS (
                    SELECT 
                        dg.geom_area_km2,
                        c.inside_cnt,
                        c.neighbour_cnt,
                        CASE 
                            WHEN ib.ubuf IS NULL THEN 0.0
                            ELSE ST_Area(ST_Intersection(dg.boundary_utm, ib.ubuf)) / 1000000.0
                        END as served_no_neigh,
                        CASE 
                            WHEN ab.ubuf IS NULL THEN 0.0
                            ELSE ST_Area(ST_Intersection(dg.boundary_utm, ab.ubuf)) / 1000000.0
                        END as served_all,
                        CASE 
                            WHEN ab.ubuf IS NULL THEN dg.boundary_utm 
                            ELSE ST_Difference(dg.boundary_utm, ab.ubuf) 
                        END as blank_all
                    FROM district_geom dg
                    CROSS JOIN counts c
                    LEFT JOIN inside_buffer ib ON TRUE
                    LEFT JOIN all_buffer ab ON TRUE
                )
                SELECT 
                    geom_area_km2,
                    inside_cnt,
                    neighbour_cnt,
                    served_no_neigh,
                    served_all,
                    COALESCE(ST_Area(blank_all), 0) / 1000000.0 as unserved_all,
                    ST_AsGeoJSON(ST_Transform(blank_all, 4326))::json as blank_geojson
                FROM diffs;
            """
            cur.execute(spatial_query, (dist_id, facility_type, radius_m, radius_m, radius_m))
            res = cur.fetchone()

            raw_geom_area = float(res["geom_area_km2"]) if res else 0.0
            inside_cnt = int(res["inside_cnt"]) if res and res["inside_cnt"] is not None else 0
            neighbour_cnt = int(res["neighbour_cnt"]) if res and res["neighbour_cnt"] is not None else 0

            # With cross-border neighbours included
            raw_served = float(res["served_all"]) if res and res["served_all"] is not None else 0.0
            raw_unserved = float(res["unserved_all"]) if res and res["unserved_all"] is not None else raw_geom_area
            geom_area_km2 = round(raw_geom_area, 2)
            served_km2 = round(min(raw_served, raw_geom_area), 4)
            unserved_km2 = round(min(raw_unserved, raw_geom_area), 4)
            coverage_pct = round((raw_served / max(0.001, raw_geom_area)) * 100.0, 2)
            coverage_pct = min(100.0, max(0.0, coverage_pct))

            # Without neighbours (internal facilities only)
            raw_served_no_neigh = float(res["served_no_neigh"]) if res and res["served_no_neigh"] is not None else 0.0
            served_no_neigh_km2 = round(min(raw_served_no_neigh, raw_geom_area), 4)
            coverage_pct_without_neighbours = round((raw_served_no_neigh / max(0.001, raw_geom_area)) * 100.0, 2)
            coverage_pct_without_neighbours = min(100.0, max(0.0, coverage_pct_without_neighbours))

            geojson_geom = res["blank_geojson"] if res else {}

            ratio = round(raw_geom_area / max(0.001, area_km2), 2)
            area_note = None
            if ratio > 1.5:
                area_note = (
                    f"Perhatian: Luas poligon geometri ({geom_area_km2} km²) berbeda jauh dari luas administratif BPS "
                    f"({area_km2} km², rasio {ratio}x). "
                    f"Persentase cakupan dihitung terhadap luas poligon geometri, bukan luas BPS."
                )

            return BlankSpotAnalysisResult(
                district_code=code,
                district_name=name,
                facility_type=facility_type,
                pillar=pillar,
                service_radius_meters=radius_m,
                district_area_km2=geom_area_km2,
                served_area_km2=served_km2,
                unserved_area_km2=unserved_km2,
                coverage_percentage=coverage_pct,
                coverage_pct=coverage_pct,
                coverage_pct_without_neighbours=coverage_pct_without_neighbours,
                facilities_inside=inside_cnt,
                facilities_from_neighbours=neighbour_cnt,
                cross_border_scope="DKI Jakarta only",
                blank_spot_geojson=geojson_geom or {},
                bps_area_km2=area_km2,
                area_ratio=ratio,
                area_note=area_note
            )

    @staticmethod
    def simulate_blank_spot_reduction(
        district_code: str,
        facility_type: str,
        hypothetical_coords: List[float], # [lon, lat]
        custom_radius_meters: Optional[int] = None
    ) -> BlankSpotSimulationDelta:
        """
        Simulates how adding a hypothetical amenity at [lon, lat] reduces the unserved blank spot area.
        Runs entirely in transient memory context without saving to database.
        Includes cross-border active facilities within service radius.
        """
        baseline = PostGISSpatialEngine.calculate_blank_spots(district_code, facility_type)
        radius_m = custom_radius_meters or baseline.service_radius_meters

        lon, lat = hypothetical_coords[0], hypothetical_coords[1]

        record, err = resolve_district_record(baseline.district_code)
        if not record:
            raise ValueError(f"District '{baseline.district_code}' not found.")
        dist_id = record["id"]
        utm_srid = record.get("utm_srid") or 32748

        with get_db_cursor() as cur:
            sim_query = """
                WITH district_geom AS (
                    SELECT boundary_utm, utm_srid, ST_Area(boundary_utm) / 1000000.0 as geom_area_km2 FROM kecamatan WHERE id = %s
                ),
                facilities_in_reach AS (
                    SELECT f.coordinates_utm
                    FROM district_geom dg
                    CROSS JOIN public_facilities f
                    WHERE f.facility_type = %s
                      AND f.is_active = TRUE
                      AND f.utm_srid = dg.utm_srid
                      AND ST_DWithin(f.coordinates_utm, dg.boundary_utm, %s)
                ),
                existing_buffers AS (
                    SELECT ST_Union(ST_Buffer(coordinates_utm, %s)) as unioned_buffer
                    FROM facilities_in_reach
                ),
                hypothetical_point AS (
                    SELECT ST_Buffer(
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s),
                        %s
                    ) as hypo_buffer
                ),
                all_buffers AS (
                    SELECT 
                        CASE 
                            WHEN eb.unioned_buffer IS NULL THEN hp.hypo_buffer
                            ELSE ST_Union(eb.unioned_buffer, hp.hypo_buffer)
                        END as combined_buffer
                    FROM hypothetical_point hp
                    LEFT JOIN existing_buffers eb ON TRUE
                ),
                sim_diff AS (
                    SELECT ST_Difference(dg.boundary_utm, ab.combined_buffer) as sim_blank_utm
                    FROM district_geom dg, all_buffers ab
                )
                SELECT 
                    COALESCE(ST_Area(sim_blank_utm), 0) / 1000000.0 as sim_unserved_km2,
                    ST_AsGeoJSON(ST_Transform(sim_blank_utm, 4326))::json as sim_blank_geojson
                FROM sim_diff;
            """
            cur.execute(sim_query, (dist_id, facility_type, radius_m, radius_m, lon, lat, utm_srid, radius_m))
            res = cur.fetchone()

            sim_unserved = float(res["sim_unserved_km2"]) if res and res["sim_unserved_km2"] is not None else 0.0
            sim_unserved = round(max(0.0, min(sim_unserved, baseline.district_area_km2)), 4)

            area_recovered = round(max(0.0, baseline.unserved_area_km2 - sim_unserved), 4)
            improvement_pct = round((area_recovered / max(0.001, baseline.district_area_km2)) * 100.0, 2)

            return BlankSpotSimulationDelta(
                district_code=baseline.district_code,
                facility_type=facility_type,
                baseline_unserved_km2=baseline.unserved_area_km2,
                simulated_unserved_km2=sim_unserved,
                area_recovered_km2=area_recovered,
                coverage_improvement_pct=improvement_pct,
                cross_border_scope="DKI Jakarta only",
                simulated_blank_spot_geojson=res["sim_blank_geojson"] if res else {}
            )
