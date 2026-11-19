"""
Cognitive Spatial Agent Tool Registry.
Provides deterministic execution wrappers for:
- PostGIS spatial compliance and scorecards.
- PostGIS unserved blank spot polygon calculations.
- What-If urban scenario simulations (population shock & superblocks).
- Hybrid RAG legal regulation search.
"""

import json
from typing import Dict, Any, Optional, Tuple
from backend.app.core.db import get_db_cursor
from backend.app.core.config import settings
from backend.app.api.routers.regions import get_province_population_meta
from backend.app.engine.simulation import (
    WhatIfSimulationEngine,
    SuperblockSimulationRequest,
)
from backend.app.engine.spatial import (
    PostGISSpatialEngine,
    resolve_district_record,
    resolve_district_candidates,
    format_ambiguous_district_detail,
)
from backend.app.engine.standards_availability import (
    LOCAL_GATE_REASON,
    get_province_standards_availability,
)
from backend.app.rag.hybrid_search import HybridRegulationRetriever

# -----------------------------------------------------------------------------
# Tool Schemas for Qwen 2.5 14B Function Calling (OpenAI Specification)
# -----------------------------------------------------------------------------
SPATIAL_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_district_scorecard",
            "description": "Ambil profil kependudukan, batas wilayah, dan scorecard indeks kepatuhan fasilitas empat pilar untuk kecamatan di provinsi aktif. Jika pengguna menyebut nama tempat tanpa kata 'kecamatan', anggap itu nama kecamatan di provinsi aktif dan langsung panggil tool ini sebelum meminta klarifikasi. Tool ini menyediakan data defisit unit fasilitas (defisit unit = kebutuhan - jumlah fasilitas eksisting pada metrics_payload).",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_code": {
                        "type": "string",
                        "description": "Kode Kemendagri kecamatan atau nama tempat/kecamatan di provinsi aktif (misal 'Tebet', 'Coblong', 'Gondokusuman', 'Wenang', 'Ujung Pandang')"
                    }
                },
                "required": ["district_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_unserved_blank_spots",
            "description": "Hitung area blank spot spasial dan persentase cakupan geografis dalam radius jangkauan fasilitas (cakupan % = luas terlayani radius dari blank spot). PERHATIAN: Tool ini mengukur cakupan radius geografis, BUKAN menghitung defisit unit fasilitas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_code": {
                        "type": "string",
                        "description": "Kode Kemendagri atau nama kecamatan (misal 'Tebet', 'Coblong')"
                    },
                    "facility_type": {
                        "type": "string",
                        "description": "Jenis fasilitas yang diaudit: 'puskesmas_kelurahan', 'sekolah_dasar', 'taman_rptra', 'pos_damkar', dsb.",
                        "default": "puskesmas_kelurahan"
                    }
                },
                "required": ["district_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_regulations",
            "description": "Cari rujukan pasal hukum resmi dari standar nasional (SNI 03-1733-2004) via pencarian leksikal (trigram + hashed bag-of-words + sinonim).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Pertanyaan atau kata kunci regulasi (misal 'standar puskesmas radius', 'kewajiban RTH pengembang superblok')"
                    },
                    "pillar": {
                        "type": "string",
                        "description": "Pilihan pilar: 'lifeline_health', 'education', 'urban_livability', 'mobility_connectivity'",
                        "default": None
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_what_if_simulation",
            "description": "Jalankan simulasi skenario perkotaan (lonjakan populasi atau penambahan fasilitas hipotetis) dalam sandbox terisolasi tanpa memutasi data dasar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_code": {
                        "type": "string",
                        "description": "Kode Kemendagri atau nama kecamatan"
                    },
                    "population_shock_count": {
                        "type": "integer",
                        "description": "Jumlah pertambahan penduduk hipotetis",
                        "default": 0
                    },
                    "population_shock_percent": {
                        "type": "number",
                        "description": "Persentase lonjakan populasi",
                        "default": 0.0
                    }
                },
                "required": ["district_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_superblock_simulation",
            "description": "Simulasikan dampak pembangunan superblok/apartemen baru terhadap fasilitas lingkungan dengan estimasi alokasi RTH dan sumur resapan Zero Delta Q (parameter asumsi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_code": {
                        "type": "string",
                        "description": "Kode Kemendagri atau nama kecamatan"
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Nama proyek superblok (misal 'Apartemen Urban Oasis')"
                    },
                    "residential_units": {
                        "type": "integer",
                        "description": "Jumlah total unit hunian baru"
                    },
                    "site_area_m2": {
                        "type": "number",
                        "description": "Luas lahan bruto proyek dalam meter persegi"
                    }
                },
                "required": ["district_code", "project_name", "residential_units", "site_area_m2"]
            }
        }
    }
]


def _resolve_tool_district(
    code: str, province_code: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Resolves district record for agent tools, enforcing active-province scope and ambiguity error."""
    record, err = resolve_district_record(code, province_code=province_code)
    if not record:
        if err == "ambiguous":
            candidates = resolve_district_candidates(code, province_code=province_code)
            return None, format_ambiguous_district_detail(code, candidates)
        return None, f"Kecamatan '{code}' tidak ditemukan."

    rec_prov = record.get("province_code")
    if rec_prov and rec_prov not in settings.active_provinces:
        return None, "Data wilayah ini belum tersedia (rencana v1.1)"
    return record, None


# -----------------------------------------------------------------------------
# Tool Execution Dispatcher (Deterministic Python/PostGIS)
# -----------------------------------------------------------------------------
def execute_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    province_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Executes spatial tools deterministically without letting LLM hallucinate numbers."""
    try:
        if tool_name == "get_district_scorecard":
            code = arguments["district_code"]
            record, err_msg = _resolve_tool_district(code, province_code=province_code)
            if not record:
                return {"error": err_msg}

            with get_db_cursor() as cur:
                cur.execute(
                    """
                    SELECT k.kemendagri_code, k.name, c.name as city_name,
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
                    WHERE k.id = %s;
                    """,
                    (record["id"],),
                )
                row = cur.fetchone()
                if not row:
                    return {"error": f"Kecamatan '{code}' tidak ditemukan."}

                metrics = row.get("metrics_payload")
                if isinstance(metrics, str):
                    try:
                        metrics = json.loads(metrics)
                    except Exception:
                        pass

                cov = row.get("coverage")
                if isinstance(cov, str):
                    try:
                        cov = json.loads(cov)
                    except Exception:
                        pass

                from backend.app.engine.standards_availability import (
                    calculate_pillar_and_composite_scores,
                )

                scores_breakdown = calculate_pillar_and_composite_scores(
                    metrics if isinstance(metrics, list) else []
                )
                enriched_pillars = scores_breakdown["pillar_scores"]
                composite = (
                    float(row["composite_livability_score"])
                    if row["composite_livability_score"] is not None
                    else scores_breakdown["composite_score"]
                )
                composite_note = row.get("composite_note") or scores_breakdown["composite_note"]
                if composite is None and not composite_note:
                    composite_note = "Data tidak memadai"

                eff_prov = str(
                    row.get("province_code")
                    or record.get("province_code")
                    or settings.DEFAULT_PROVINCE_CODE
                )
                pop_note, pop_src, pop_verif = get_province_population_meta(
                    eff_prov,
                    row.get("population_source"),
                    row.get("population_verification_status"),
                )

                is_gated = composite is None and (
                    (isinstance(cov, dict) and cov.get("osm_coverage", {}).get("status") == "tidak_memadai")
                    or (
                        isinstance(metrics, list)
                        and any(
                            isinstance(m, dict) and m.get("data_availability") == "insufficient_local"
                            for m in metrics
                        )
                    )
                )

                result_payload = {
                    "kemendagri_code": row["kemendagri_code"],
                    "district_code": row["kemendagri_code"],
                    "district_name": row["name"],
                    "city_name": row["city_name"],
                    "province_code": eff_prov,
                    "province_name": row.get("province_name"),
                    "population": row["population"],
                    "population_note": pop_note,
                    "population_source": pop_src,
                    "population_verification_status": pop_verif,
                    "area_km2": float(row["area_km2"]) if row["area_km2"] is not None else 0.0,
                    "density_per_km2": float(row["density_per_km2"]) if row["density_per_km2"] is not None else 0.0,
                    "composite_score": composite,
                    "composite_livability_score": composite,  # keep for backward compatibility
                    "score_status": "Data tidak memadai" if composite is None else "Tersedia",
                    "composite_note": composite_note,
                    "availability_source": scores_breakdown.get("availability_source", "database"),
                    "pillar_scores": enriched_pillars,
                    "metrics_payload": metrics,
                }
                if cov is not None:
                    result_payload["coverage"] = cov
                if is_gated:
                    cov_reason = None
                    if isinstance(metrics, list):
                        for m in metrics:
                            if isinstance(m, dict) and m.get("data_availability") == "insufficient_local":
                                cov_reason = m.get("availability_reason")
                                break
                    result_payload["coverage_reason"] = cov_reason or LOCAL_GATE_REASON
                return result_payload

        elif tool_name == "get_unserved_blank_spots":
            code = arguments["district_code"]
            ftype = arguments.get("facility_type", "puskesmas_kelurahan")
            record, err_msg = _resolve_tool_district(code, province_code=province_code)
            if not record:
                return {"error": err_msg}
            result = PostGISSpatialEngine.calculate_blank_spots(
                record["kemendagri_code"], ftype, province_code=province_code
            )
            unserved_pct = round(100.0 - result.coverage_percentage, 2)
            ratio_pct = round(
                (result.unserved_area_km2 / max(0.001, result.district_area_km2)) * 100.0,
                2,
            )
            return {
                "district_code": result.district_code,
                "district_name": result.district_name,
                "province_code": record.get("province_code") or settings.DEFAULT_PROVINCE_CODE,
                "province_name": record.get("province_name"),
                "facility_type": result.facility_type,
                "service_radius_meters": result.service_radius_meters,
                "total_area_km2": result.district_area_km2,
                "served_area_km2": result.served_area_km2,
                "unserved_area_km2": result.unserved_area_km2,
                "coverage_pct": result.coverage_pct,
                "coverage_pct_without_neighbours": result.coverage_pct_without_neighbours,
                "facilities_inside": result.facilities_inside,
                "facilities_from_neighbours": result.facilities_from_neighbours,
                "cross_border_scope": result.cross_border_scope,
                "coverage_percentage": f"{result.coverage_percentage}%",
                "coverage_percentage_val": result.coverage_percentage,
                "unserved_percentage": f"{unserved_pct}%",
                "unserved_percentage_val": unserved_pct,
                "unserved_ratio_percentage": f"{ratio_pct}%",
                "unserved_ratio_percentage_val": ratio_pct,
                "has_blank_spot_polygon": bool(result.blank_spot_geojson),
            }

        elif tool_name == "search_regulations":
            query = arguments["query"]
            pillar = arguments.get("pillar")
            citations = HybridRegulationRetriever.search_regulations(
                query=query, pillar=pillar, top_k=3
            )
            return {
                "query": query,
                "total_found": len(citations),
                "citations": [c.model_dump() for c in citations],
                "markdown_summary": HybridRegulationRetriever.format_citations_markdown(
                    citations
                ),
            }

        elif tool_name == "run_what_if_simulation":
            code = arguments["district_code"]
            pop_shock_cnt = arguments.get("population_shock_count", 0)
            pop_shock_pct = arguments.get("population_shock_percent", 0.0)

            record, err_msg = _resolve_tool_district(code, province_code=province_code)
            if not record:
                return {"error": err_msg}

            prov_code = record.get("province_code") or settings.DEFAULT_PROVINCE_CODE
            with get_db_cursor() as cur:
                cur.execute(
                    "SELECT facility_type, COUNT(*) as cnt FROM public_facilities WHERE kecamatan_id = %s AND is_active = TRUE GROUP BY facility_type;",
                    (record["id"],),
                )
                counts = {r["facility_type"]: r["cnt"] for r in cur.fetchall()}

                cur.execute(
                    "SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference, scored FROM regulatory_standards WHERE province_code IS NULL OR province_code = %s;",
                    (prov_code,),
                )
                stds = cur.fetchall()

            avail_map = get_province_standards_availability(prov_code)
            pop_note, _, _ = get_province_population_meta(prov_code)

            delta = WhatIfSimulationEngine.compute_scenario_delta(
                district_code=record["kemendagri_code"],
                district_name=record["name"],
                baseline_population=record["population"],
                existing_facility_counts=counts,
                regulatory_standards=stds,
                pop_shock_pct=pop_shock_pct,
                pop_shock_count=pop_shock_cnt,
                staged_amenities=[],
                province_code=prov_code,
                availability_map=avail_map,
                population_note=pop_note,
            )
            return delta.model_dump()

        elif tool_name == "run_superblock_simulation":
            code = arguments["district_code"]
            record, err_msg = _resolve_tool_district(code, province_code=province_code)
            if not record:
                return {"error": err_msg}

            prov_code = record.get("province_code") or settings.DEFAULT_PROVINCE_CODE
            with get_db_cursor() as cur:
                cur.execute(
                    "SELECT facility_type, COUNT(*) as cnt FROM public_facilities WHERE kecamatan_id = %s AND is_active = TRUE GROUP BY facility_type;",
                    (record["id"],),
                )
                counts = {r["facility_type"]: r["cnt"] for r in cur.fetchall()}

                cur.execute(
                    "SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference, scored FROM regulatory_standards WHERE province_code IS NULL OR province_code = %s;",
                    (prov_code,),
                )
                stds = cur.fetchall()

            avail_map = get_province_standards_availability(prov_code)
            pop_note, _, _ = get_province_population_meta(prov_code)

            req = SuperblockSimulationRequest(
                district_code=record["kemendagri_code"],
                project_name=arguments.get("project_name", "Proyek Superblok"),
                residential_units=arguments.get("residential_units", 2000),
                site_area_m2=arguments.get("site_area_m2", 15000.0),
            )

            impact = WhatIfSimulationEngine.simulate_superblock_development(
                req=req,
                baseline_population=record["population"],
                district_name=record["name"],
                existing_facility_counts=counts,
                regulatory_standards=stds,
                province_code=prov_code,
                availability_map=avail_map,
                population_note=pop_note,
            )
            return impact.model_dump()

        else:
            return {"error": f"Unknown tool '{tool_name}'"}

    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}
