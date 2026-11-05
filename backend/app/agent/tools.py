"""
Cognitive Spatial Agent Tool Registry.
Provides deterministic execution wrappers for:
- PostGIS spatial compliance and scorecards.
- PostGIS unserved blank spot polygon calculations.
- What-If urban scenario simulations (population shock & superblocks).
- Hybrid RAG legal regulation search.
"""

import json
from typing import Dict, Any, List, Optional
from backend.app.core.db import get_db_cursor
from backend.app.engine.simulation import (
    WhatIfSimulationEngine,
    HypotheticalAmenity,
    SuperblockSimulationRequest
)
from backend.app.engine.spatial import PostGISSpatialEngine
from backend.app.rag.hybrid_search import HybridRegulationRetriever

# -----------------------------------------------------------------------------
# Tool Schemas for Qwen 2.5 14B Function Calling (OpenAI Specification)
# -----------------------------------------------------------------------------
SPATIAL_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_district_scorecard",
            "description": "Ambil profil kependudukan, batas wilayah, dan scorecard indeks kepatuhan fasilitas 4 pilar untuk kecamatan di DKI Jakarta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_code": {
                        "type": "string",
                        "description": "Kode Kemendagri kecamatan (misal '31.71.09' untuk Tebet) atau nama kecamatan (misal 'Tebet', 'Cilandak')"
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
            "description": "Hitung area blank spot (zona tidak terlayani fasilitas dalam radius standar SNI) menggunakan komputasi spasial PostGIS ST_Difference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_code": {
                        "type": "string",
                        "description": "Kode Kemendagri atau nama kecamatan (misal '31.71.09' atau 'Tebet')"
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
            "description": "Cari rujukan pasal hukum resmi dari standar nasional (SNI 03-1733-2004) dan Perda RDTR DKI Jakarta No. 31/2022 via pencarian leksikal (trigram + hashed bag-of-words + sinonim).",
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
                        "description": "Kode Kemendagri atau nama kecamatan (misal '31.71.09')"
                    },
                    "population_shock_count": {
                        "type": "integer",
                        "description": "Jumlah pertambahan penduduk hipotetis (misal 10000)",
                        "default": 0
                    },
                    "population_shock_percent": {
                        "type": "number",
                        "description": "Persentase lonjakan populasi (misal 15.0 untuk +15%)",
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
            "description": "Simulasikan dampak pembangunan superblok/apartemen baru terhadap fasilitas lingkungan dengan estimasi alokasi RTH 20% dan sumur resapan Zero Delta Q (parameter asumsi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_code": {
                        "type": "string",
                        "description": "Kode Kemendagri atau nama kecamatan"
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Nama proyek superblok (misal 'Apartemen Urban Oasis Tebet')"
                    },
                    "residential_units": {
                        "type": "integer",
                        "description": "Jumlah total unit hunian baru (misal 3500)"
                    },
                    "site_area_m2": {
                        "type": "number",
                        "description": "Luas lahan bruto proyek dalam meter persegi (misal 20000.0 untuk 2 hektar)"
                    }
                },
                "required": ["district_code", "project_name", "residential_units", "site_area_m2"]
            }
        }
    }
]

# -----------------------------------------------------------------------------
# Tool Execution Dispatcher (Deterministic Python/PostGIS)
# -----------------------------------------------------------------------------
def execute_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Executes spatial tools deterministically without letting LLM hallucinate numbers."""
    try:
        if tool_name == "get_district_scorecard":
            code = arguments["district_code"]
            with get_db_cursor() as cur:
                cur.execute("""
                    SELECT k.kemendagri_code, k.name, c.name as city_name,
                           k.population, k.area_km2, k.density_per_km2,
                           s.health_score, s.education_score, s.livability_score,
                           s.mobility_score, s.composite_livability_score, s.composite_note,
                           s.metrics_payload
                    FROM kecamatan k
                    JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                    LEFT JOIN district_compliance_scores s ON s.district_id = k.id
                    WHERE k.kemendagri_code = %s OR LOWER(k.name) = LOWER(%s);
                """, (code, code))
                row = cur.fetchone()
                if not row:
                    return {"error": f"Kecamatan '{code}' tidak ditemukan."}

                metrics = row.get("metrics_payload")
                if isinstance(metrics, str):
                    try:
                        metrics = json.loads(metrics)
                    except Exception:
                        pass

                from backend.app.engine.standards_availability import calculate_pillar_and_composite_scores
                scores_breakdown = calculate_pillar_and_composite_scores(metrics if isinstance(metrics, list) else [])
                enriched_pillars = scores_breakdown["pillar_scores"]
                composite = float(row["composite_livability_score"]) if row["composite_livability_score"] is not None else scores_breakdown["composite_score"]
                composite_note = row.get("composite_note") or scores_breakdown["composite_note"]

                return {
                    "kemendagri_code": row["kemendagri_code"],
                    "district_code": row["kemendagri_code"],
                    "district_name": row["name"],
                    "city_name": row["city_name"],
                    "population": row["population"],
                    "population_note": "Sumber data penduduk belum terverifikasi (TODO-VERIFY)",
                    "area_km2": float(row["area_km2"]) if row["area_km2"] is not None else 0.0,
                    "density_per_km2": float(row["density_per_km2"]) if row["density_per_km2"] is not None else 0.0,
                    "composite_score": composite,
                    "composite_livability_score": composite,  # keep for backward compatibility
                    "composite_note": composite_note,
                    "availability_source": scores_breakdown.get("availability_source", "database"),
                    "pillar_scores": enriched_pillars,
                    "metrics_payload": metrics
                }

        elif tool_name == "get_unserved_blank_spots":
            code = arguments["district_code"]
            ftype = arguments.get("facility_type", "puskesmas_kelurahan")
            result = PostGISSpatialEngine.calculate_blank_spots(code, ftype)
            unserved_pct = round(100.0 - result.coverage_percentage, 2)
            ratio_pct = round((result.unserved_area_km2 / max(0.001, result.district_area_km2)) * 100.0, 2)
            return {
                "district_code": result.district_code,
                "district_name": result.district_name,
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
                "has_blank_spot_polygon": bool(result.blank_spot_geojson)
            }

        elif tool_name == "search_regulations":
            query = arguments["query"]
            pillar = arguments.get("pillar")
            citations = HybridRegulationRetriever.search_regulations(query=query, pillar=pillar, top_k=3)
            return {
                "query": query,
                "total_found": len(citations),
                "citations": [c.model_dump() for c in citations],
                "markdown_summary": HybridRegulationRetriever.format_citations_markdown(citations)
            }

        elif tool_name == "run_what_if_simulation":
            code = arguments["district_code"]
            pop_shock_cnt = arguments.get("population_shock_count", 0)
            pop_shock_pct = arguments.get("population_shock_percent", 0.0)

            with get_db_cursor() as cur:
                cur.execute("SELECT id, kemendagri_code, name, population FROM kecamatan WHERE kemendagri_code = %s OR LOWER(name) = LOWER(%s);", (code, code))
                dist = cur.fetchone()
                if not dist:
                    return {"error": f"District '{code}' not found."}

                cur.execute("SELECT facility_type, COUNT(*) as cnt FROM public_facilities WHERE kecamatan_id = %s AND is_active = TRUE GROUP BY facility_type;", (dist["id"],))
                counts = {r["facility_type"]: r["cnt"] for r in cur.fetchall()}

                cur.execute("SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference FROM regulatory_standards;")
                stds = cur.fetchall()

            delta = WhatIfSimulationEngine.compute_scenario_delta(
                district_code=dist["kemendagri_code"],
                district_name=dist["name"],
                baseline_population=dist["population"],
                existing_facility_counts=counts,
                regulatory_standards=stds,
                pop_shock_pct=pop_shock_pct,
                pop_shock_count=pop_shock_cnt,
                staged_amenities=[]
            )
            return delta.model_dump()

        elif tool_name == "run_superblock_simulation":
            code = arguments["district_code"]
            req = SuperblockSimulationRequest(
                district_code=code,
                project_name=arguments.get("project_name", "Proyek Superblok"),
                residential_units=arguments.get("residential_units", 2000),
                site_area_m2=arguments.get("site_area_m2", 15000.0)
            )

            with get_db_cursor() as cur:
                cur.execute("SELECT id, kemendagri_code, name, population FROM kecamatan WHERE kemendagri_code = %s OR LOWER(name) = LOWER(%s);", (code, code))
                dist = cur.fetchone()
                if not dist:
                    return {"error": f"District '{code}' not found."}

                cur.execute("SELECT facility_type, COUNT(*) as cnt FROM public_facilities WHERE kecamatan_id = %s AND is_active = TRUE GROUP BY facility_type;", (dist["id"],))
                counts = {r["facility_type"]: r["cnt"] for r in cur.fetchall()}

                cur.execute("SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference FROM regulatory_standards;")
                stds = cur.fetchall()

            impact = WhatIfSimulationEngine.simulate_superblock_development(
                req=req,
                baseline_population=dist["population"],
                district_name=dist["name"],
                existing_facility_counts=counts,
                regulatory_standards=stds
            )
            return impact.model_dump()

        else:
            return {"error": f"Unknown tool '{tool_name}'"}

    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}
