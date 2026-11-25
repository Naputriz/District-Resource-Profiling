"""
National, provincial, ranking, and methodology tools for the Cognitive Spatial Agent.
Provides deterministic, read-only PostgreSQL/PostGIS aggregations cached in Redis,
province alias resolution (including the 2022 Papua split), and tool-backed methodology
constants from `regulatory_standards` and `standards_availability`.
"""

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.api import deps as api_deps
from backend.app.api.routers.regions import (
    REGIONS_CATALOG,
    get_province_population_meta,
)
from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor
from backend.app.engine.standards_availability import (
    BASE_PILLAR_WEIGHTS,
    DEFAULT_MIN_RECORDS_THRESHOLD,
    LOCAL_GATE_REASON,
    OSM_COVERAGE_RULE,
    PILLAR_LABELS,
    SD_POPULATION_THRESHOLD,
    STANDARDS_AVAILABILITY_SPEC,
)

logger = logging.getLogger(__name__)

_NATIONAL_CACHE_TTL_SECONDS = 300

ISLAND_GROUP_BY_CODE: Dict[str, str] = {
    "11": "Sumatra",
    "12": "Sumatra",
    "13": "Sumatra",
    "14": "Sumatra",
    "15": "Sumatra",
    "16": "Sumatra",
    "17": "Sumatra",
    "18": "Sumatra",
    "19": "Sumatra",
    "21": "Sumatra",
    "31": "Jawa",
    "32": "Jawa",
    "33": "Jawa",
    "34": "Jawa",
    "35": "Jawa",
    "36": "Jawa",
    "51": "Bali & Nusa Tenggara",
    "52": "Bali & Nusa Tenggara",
    "53": "Bali & Nusa Tenggara",
    "61": "Kalimantan",
    "62": "Kalimantan",
    "63": "Kalimantan",
    "64": "Kalimantan",
    "65": "Kalimantan",
    "71": "Sulawesi",
    "72": "Sulawesi",
    "73": "Sulawesi",
    "74": "Sulawesi",
    "75": "Sulawesi",
    "76": "Sulawesi",
    "81": "Maluku",
    "82": "Maluku",
    "91": "Papua",
    "92": "Papua",
    "93": "Papua",
    "94": "Papua",
    "95": "Papua",
    "96": "Papua",
}

PAPUA_GROUP_CODES: List[str] = ["91", "92", "93", "94", "95", "96"]

PROVINCE_ALIASES: Dict[str, str] = {
    "aceh": "11",
    "nad": "11",
    "nanggroe aceh darussalam": "11",
    "sumatera utara": "12",
    "sumut": "12",
    "north sumatra": "12",
    "sumatera barat": "13",
    "sumbar": "13",
    "west sumatra": "13",
    "riau": "14",
    "jambi": "15",
    "sumatera selatan": "16",
    "sumsel": "16",
    "south sumatra": "16",
    "bengkulu": "17",
    "lampung": "18",
    "kepulauan bangka belitung": "19",
    "bangka belitung": "19",
    "babel": "19",
    "kep bangka belitung": "19",
    "kepulauan riau": "21",
    "kepri": "21",
    "kep riau": "21",
    "dki jakarta": "31",
    "jakarta": "31",
    "dki": "31",
    "daerah khusus ibukota jakarta": "31",
    "jawa barat": "32",
    "jabar": "32",
    "west java": "32",
    "jawa tengah": "33",
    "jateng": "33",
    "central java": "33",
    "di yogyakarta": "34",
    "diy": "34",
    "yogyakarta": "34",
    "jogja": "34",
    "jogjakarta": "34",
    "daerah istimewa yogyakarta": "34",
    "jawa timur": "35",
    "jatim": "35",
    "east java": "35",
    "banten": "36",
    "bali": "51",
    "nusa tenggara barat": "52",
    "ntb": "52",
    "nusa tenggara timur": "53",
    "ntt": "53",
    "kalimantan barat": "61",
    "kalbar": "61",
    "west kalimantan": "61",
    "kalimantan tengah": "62",
    "kalteng": "62",
    "central kalimantan": "62",
    "kalimantan selatan": "63",
    "kalsel": "63",
    "south kalimantan": "63",
    "kalimantan timur": "64",
    "kaltim": "64",
    "east kalimantan": "64",
    "kalimantan utara": "65",
    "kaltara": "65",
    "north kalimantan": "65",
    "sulawesi utara": "71",
    "sulut": "71",
    "north sulawesi": "71",
    "sulawesi tengah": "72",
    "sulteng": "72",
    "central sulawesi": "72",
    "sulawesi selatan": "73",
    "sulsel": "73",
    "south sulawesi": "73",
    "sulawesi tenggara": "74",
    "sultra": "74",
    "southeast sulawesi": "74",
    "gorontalo": "75",
    "sulawesi barat": "76",
    "sulbar": "76",
    "west sulawesi": "76",
    "maluku": "81",
    "maluku utara": "82",
    "malut": "82",
    "north maluku": "82",
    "papua barat": "92",
    "pabar": "92",
    "west papua": "92",
    "papua selatan": "93",
    "pasel": "93",
    "south papua": "93",
    "papua tengah": "94",
    "pateng": "94",
    "central papua": "94",
    "papua pegunungan": "95",
    "highland papua": "95",
    "papua barat daya": "96",
    "pbd": "96",
    "southwest papua": "96",
}

_METRIC_COLUMN_MAP: Dict[str, Tuple[str, str]] = {
    "composite": ("s.composite_livability_score", "Indeks Kecukupan Fasilitas Dasar (Komposit)"),
    "komposit": ("s.composite_livability_score", "Indeks Kecukupan Fasilitas Dasar (Komposit)"),
    "overall": ("s.composite_livability_score", "Indeks Kecukupan Fasilitas Dasar (Komposit)"),
    "lifeline_health": ("s.health_score", PILLAR_LABELS["lifeline_health"]),
    "health": ("s.health_score", PILLAR_LABELS["lifeline_health"]),
    "kesehatan": ("s.health_score", PILLAR_LABELS["lifeline_health"]),
    "education": ("s.education_score", PILLAR_LABELS["education"]),
    "pendidikan": ("s.education_score", PILLAR_LABELS["education"]),
    "urban_livability": ("s.livability_score", PILLAR_LABELS["urban_livability"]),
    "livability": ("s.livability_score", PILLAR_LABELS["urban_livability"]),
    "ruang_hidup": ("s.livability_score", PILLAR_LABELS["urban_livability"]),
    "mobility_connectivity": ("s.mobility_score", PILLAR_LABELS["mobility_connectivity"]),
    "mobility": ("s.mobility_score", PILLAR_LABELS["mobility_connectivity"]),
    "mobilitas": ("s.mobility_score", PILLAR_LABELS["mobility_connectivity"]),
}


def _scope_cache_key(prefix: str, *parts: str) -> str:
    active_sig = ",".join(sorted(settings.active_provinces))
    raw_scope = f"{settings.POSTGRES_DB}:{active_sig}"
    scope_hash = hashlib.md5(raw_scope.encode("utf-8")).hexdigest()[:10]
    suffix = ":".join(str(p) for p in parts if p)
    return f"cache:agent:{prefix}:{scope_hash}:{suffix}" if suffix else f"cache:agent:{prefix}:{scope_hash}"


def _get_cached_json(key: str) -> Optional[Dict[str, Any]]:
    try:
        r_client = api_deps.get_redis_client()
        if r_client:
            raw = r_client.get(key)
            if raw:
                return json.loads(raw)
    except Exception as exc:
        logger.debug("Redis cache read skipped (%s): %s", key, exc)
    return None


def _set_cached_json(key: str, payload: Dict[str, Any], ttl: int = _NATIONAL_CACHE_TTL_SECONDS) -> None:
    try:
        r_client = api_deps.get_redis_client()
        if r_client:
            r_client.setex(key, ttl, json.dumps(payload, default=str))
    except Exception as exc:
        logger.debug("Redis cache write skipped (%s): %s", key, exc)


def _normalize_province_text(raw: str) -> str:
    cleaned = re.sub(r"[.,]+", " ", str(raw or "").strip().lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("sumatra", "sumatera")
    return cleaned


def resolve_province_target(query: str) -> Dict[str, Any]:
    """
    Resolves a province code, canonical name, or Indonesian/English alias.
    Handles the 2022 Papua split (UU 14, 15, 16, 29/2022):
    - Code '91' or explicit 'Provinsi Papua' -> single province '91'.
    - Specific split names ('Papua Barat', 'Papua Selatan', etc.) -> single province '92'-'96'.
    - Bare 'Papua' / 'Tanah Papua' / 'Pulau Papua' -> ambiguous 6-province group ['91'..'96'].
    """
    raw = str(query or "").strip()
    if not raw:
        return {"error": "Parameter provinsi kosong."}

    active_provs = settings.active_provinces

    # 1. Exact 2-digit Kemendagri province code
    if re.fullmatch(r"\d{2}", raw):
        if raw not in REGIONS_CATALOG:
            return {"error": f"Kode provinsi '{raw}' tidak dikenal."}
        if raw not in active_provs:
            return {"error": "Data wilayah ini belum tersedia (rencana v1.1)"}
        return {
            "codes": [raw],
            "is_group": False,
            "resolved_name": REGIONS_CATALOG[raw]["name"],
        }

    norm = _normalize_province_text(raw)

    # 2. Explicit 'Provinsi Papua' / 'Prov Papua' -> province 91 specifically
    if norm in ("provinsi papua", "prov papua"):
        if "91" not in active_provs:
            return {"error": "Data wilayah ini belum tersedia (rencana v1.1)"}
        return {
            "codes": ["91"],
            "is_group": False,
            "resolved_name": REGIONS_CATALOG["91"]["name"],
        }

    # 3. Bare 'Papua' / 'Wilayah Papua' / 'Pulau Papua' -> 2022 6-province group
    if norm in ("papua", "tanah papua", "pulau papua", "wilayah papua", "papua semua"):
        active_papua = [c for c in PAPUA_GROUP_CODES if c in active_provs]
        if not active_papua:
            return {"error": "Data wilayah ini belum tersedia (rencana v1.1)"}
        names = ", ".join(f"{REGIONS_CATALOG[c]['name']} ({c})" for c in active_papua)
        return {
            "codes": active_papua,
            "is_group": True,
            "group_name": "Wilayah Papua (6 Provinsi Pemekaran 2022)",
            "ambiguity_note": (
                f"Nama 'Papua' mencakup {len(active_papua)} provinsi pasca pemekaran tahun 2022: {names}. "
                "Gunakan 'Provinsi Papua' atau kode '91' jika hanya merujuk Provinsi Papua induk."
            ),
        }

    # Strip leading administrative prefix for general aliases
    stripped = re.sub(r"^(?:provinsi|prov)\s+", "", norm).strip()
    matched_code = PROVINCE_ALIASES.get(norm) or PROVINCE_ALIASES.get(stripped)

    if not matched_code:
        for code, meta in REGIONS_CATALOG.items():
            if _normalize_province_text(meta["name"]) == stripped:
                matched_code = code
                break

    if not matched_code:
        return {"error": f"Provinsi '{query}' tidak ditemukan dalam katalog 38 provinsi Indonesia."}

    if matched_code not in active_provs:
        return {"error": "Data wilayah ini belum tersedia (rencana v1.1)"}

    return {
        "codes": [matched_code],
        "is_group": False,
        "resolved_name": REGIONS_CATALOG[matched_code]["name"],
    }


def _clean_province_name(code: str, db_name: Optional[str] = None) -> str:
    meta = REGIONS_CATALOG.get(code)
    if meta and meta.get("name"):
        return str(meta["name"])
    if db_name:
        return re.sub(r"^Provinsi\s+", "", str(db_name), flags=re.IGNORECASE).strip()
    return f"Provinsi {code}"


def _format_province_row(row: Dict[str, Any], compact: bool = False) -> Dict[str, Any]:
    code = str(row["province_code"])
    _, pop_src, _ = get_province_population_meta(code)
    avg_comp = float(row["average_composite_score"]) if row.get("average_composite_score") is not None else None
    if compact:
        return {
            "code": code,
            "name": _clean_province_name(code, row.get("province_name")),
            "island": ISLAND_GROUP_BY_CODE.get(code, "Lainnya"),
            "kecamatan": int(row.get("total_kecamatan") or 0),
            "scored": int(row.get("scored_kecamatan_count") or 0),
            "insufficient": int(row.get("insufficient_data_kecamatan_count") or 0),
            "avg_score": round(avg_comp, 2) if avg_comp is not None else None,
            "population": int(row.get("total_population") or 0),
            "pop_source": "BPS 2024" if code == "31" else "WorldPop R2025A 2024",
        }
    return {
        "province_code": code,
        "province_name": _clean_province_name(code, row.get("province_name")),
        "island_group": ISLAND_GROUP_BY_CODE.get(code, "Lainnya"),
        "total_kecamatan": int(row.get("total_kecamatan") or 0),
        "scored_kecamatan_count": int(row.get("scored_kecamatan_count") or 0),
        "insufficient_data_kecamatan_count": int(row.get("insufficient_data_kecamatan_count") or 0),
        "locally_adequate_osm_count": int(row.get("locally_adequate_osm_count") or 0),
        "locally_gated_osm_count": int(row.get("locally_gated_osm_count") or 0),
        "zero_population_kecamatan_count": int(row.get("zero_population_kecamatan_count") or 0),
        "average_composite_score": round(avg_comp, 2) if avg_comp is not None else None,
        "score_status": "Tersedia" if avg_comp is not None else "Data tidak memadai",
        "total_population": int(row.get("total_population") or 0),
        "population_source": pop_src,
    }


def get_national_overview() -> Dict[str, Any]:
    """
    Returns national summary across all active provinces: active province count,
    total/scored/insufficient kecamatan counts, national average composite score
    with explicit averaging rule, and per-province rows.
    """
    cache_key = _scope_cache_key("national_overview")
    cached = _get_cached_json(cache_key)
    if cached:
        return cached

    active_provs = settings.active_provinces
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT
                p.kemendagri_code AS province_code,
                p.name AS province_name,
                COUNT(k.id)::int AS total_kecamatan,
                COUNT(s.composite_livability_score)::int AS scored_kecamatan_count,
                COUNT(k.id) FILTER (WHERE s.composite_livability_score IS NULL)::int AS insufficient_data_kecamatan_count,
                COUNT(k.id) FILTER (WHERE s.coverage->'osm_coverage'->>'status' = 'memadai')::int AS locally_adequate_osm_count,
                COUNT(k.id) FILTER (WHERE s.coverage->'osm_coverage'->>'status' = 'tidak_memadai')::int AS locally_gated_osm_count,
                COUNT(k.id) FILTER (WHERE COALESCE(k.population, 0) = 0)::int AS zero_population_kecamatan_count,
                ROUND(AVG(s.composite_livability_score)::numeric, 2) AS average_composite_score,
                COALESCE(SUM(s.composite_livability_score), 0)::float AS sum_composite_score,
                COALESCE(SUM(k.population), 0)::bigint AS total_population
            FROM provinces p
            JOIN kabupaten_kota c ON c.province_id = p.id
            JOIN kecamatan k ON k.kabupaten_kota_id = c.id
            LEFT JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = ANY(%s)
            GROUP BY p.kemendagri_code, p.name
            ORDER BY p.kemendagri_code;
            """,
            (active_provs,),
        )
        rows = cur.fetchall()

    provinces: List[Dict[str, Any]] = []
    total_kec = 0
    scored_kec = 0
    insufficient_kec = 0
    local_memadai = 0
    local_gated = 0
    zero_pop = 0
    sum_scores = 0.0
    total_pop = 0

    for r in rows:
        provinces.append(_format_province_row(r, compact=True))
        total_kec += int(r.get("total_kecamatan") or 0)
        scored_kec += int(r.get("scored_kecamatan_count") or 0)
        insufficient_kec += int(r.get("insufficient_data_kecamatan_count") or 0)
        local_memadai += int(r.get("locally_adequate_osm_count") or 0)
        local_gated += int(r.get("locally_gated_osm_count") or 0)
        zero_pop += int(r.get("zero_population_kecamatan_count") or 0)
        sum_scores += float(r.get("sum_composite_score") or 0.0)
        total_pop += int(r.get("total_population") or 0)

    scored_provinces = [p for p in provinces if p["avg_score"] is not None]
    national_avg = round(sum_scores / scored_kec, 2) if scored_kec > 0 else None
    unweighted_prov_avg = (
        round(sum(p["avg_score"] for p in scored_provinces) / len(scored_provinces), 2)
        if scored_provinces
        else None
    )

    lowest_prov = (
        min(scored_provinces, key=lambda p: (p["avg_score"], p["code"]))
        if scored_provinces
        else None
    )
    highest_prov = (
        max(scored_provinces, key=lambda p: (p["avg_score"], p["code"]))
        if scored_provinces
        else None
    )

    result: Dict[str, Any] = {
        "tool": "get_national_overview",
        "scope": "national",
        "active_provinces_count": len(provinces),
        "provinces_with_composite_score_count": len(scored_provinces),
        "provinces_without_composite_score_count": len(provinces) - len(scored_provinces),
        "total_kecamatan": total_kec,
        "scored_kecamatan_count": scored_kec,
        "insufficient_data_kecamatan_count": insufficient_kec,
        "locally_adequate_osm_count": local_memadai,
        "locally_gated_osm_count": local_gated,
        "zero_population_kecamatan_count": zero_pop,
        "national_average_composite_score": national_avg,
        "national_average_of_province_averages": unweighted_prov_avg,
        "averaging_rule": (
            f"Rata-rata nasional ({national_avg}) adalah rata-rata aritmetika tidak tertimbang dari seluruh "
            f"{scored_kec} kecamatan yang memiliki skor komposit numerik di {len(scored_provinces)} provinsi; "
            f"{insufficient_kec} kecamatan berstatus 'Data tidak memadai' (NULL) dikecualikan dari rata-rata. "
            f"Secara lokal (gerbang SD >= 1), terdapat {local_memadai} kecamatan berstatus OSM 'memadai' "
            f"dan {local_gated} kecamatan berstatus 'tidak_memadai'."
        ),
        "total_population": total_pop,
        "population_sources_summary": "DKI Jakarta (31): BPS 2024; provinsi lainnya: Estimasi model WorldPop R2025A 2024",
        "lowest_average_province": (
            {
                "province_code": lowest_prov["code"],
                "province_name": lowest_prov["name"],
                "average_composite_score": lowest_prov["avg_score"],
            }
            if lowest_prov
            else None
        ),
        "highest_average_province": (
            {
                "province_code": highest_prov["code"],
                "province_name": highest_prov["name"],
                "average_composite_score": highest_prov["avg_score"],
            }
            if highest_prov
            else None
        ),
        "provinces": provinces,
    }
    _set_cached_json(cache_key, result)
    return result


def _fetch_single_province_summary(code: str) -> Dict[str, Any]:
    cache_key = _scope_cache_key("province_summary", code)
    cached = _get_cached_json(cache_key)
    if cached:
        return cached

    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT
                p.kemendagri_code AS province_code,
                p.name AS province_name,
                COUNT(k.id)::int AS total_kecamatan,
                COUNT(s.composite_livability_score)::int AS scored_kecamatan_count,
                COUNT(k.id) FILTER (WHERE s.composite_livability_score IS NULL)::int AS insufficient_data_kecamatan_count,
                COUNT(k.id) FILTER (WHERE s.coverage->'osm_coverage'->>'status' = 'memadai')::int AS locally_adequate_osm_count,
                COUNT(k.id) FILTER (WHERE s.coverage->'osm_coverage'->>'status' = 'tidak_memadai')::int AS locally_gated_osm_count,
                COUNT(k.id) FILTER (WHERE COALESCE(k.population, 0) = 0)::int AS zero_population_kecamatan_count,
                ROUND(AVG(s.composite_livability_score)::numeric, 2) AS average_composite_score,
                ROUND(AVG(s.health_score)::numeric, 2) AS avg_health_score,
                COUNT(s.health_score)::int AS health_scored_count,
                ROUND(AVG(s.education_score)::numeric, 2) AS avg_education_score,
                COUNT(s.education_score)::int AS education_scored_count,
                ROUND(AVG(s.livability_score)::numeric, 2) AS avg_livability_score,
                COUNT(s.livability_score)::int AS livability_scored_count,
                ROUND(AVG(s.mobility_score)::numeric, 2) AS avg_mobility_score,
                COUNT(s.mobility_score)::int AS mobility_scored_count,
                COALESCE(SUM(k.population), 0)::bigint AS total_population
            FROM provinces p
            JOIN kabupaten_kota c ON c.province_id = p.id
            JOIN kecamatan k ON k.kabupaten_kota_id = c.id
            LEFT JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = %s
            GROUP BY p.kemendagri_code, p.name;
            """,
            (code,),
        )
        agg = cur.fetchone()
        if not agg:
            return {"error": f"Data provinsi '{code}' tidak ditemukan."}

        cur.execute(
            """
            SELECT k.kemendagri_code, k.name AS district_name, c.name AS city_name,
                   ROUND(s.composite_livability_score::numeric, 2) AS composite_score
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = %s
              AND s.composite_livability_score IS NOT NULL
            ORDER BY s.composite_livability_score DESC, k.kemendagri_code ASC
            LIMIT 5;
            """,
            (code,),
        )
        top_rows = cur.fetchall()

        cur.execute(
            """
            SELECT k.kemendagri_code, k.name AS district_name, c.name AS city_name,
                   ROUND(s.composite_livability_score::numeric, 2) AS composite_score
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = %s
              AND s.composite_livability_score IS NOT NULL
            ORDER BY s.composite_livability_score ASC, k.kemendagri_code ASC
            LIMIT 5;
            """,
            (code,),
        )
        bottom_rows = cur.fetchall()

    base_row = _format_province_row(agg)
    pillar_averages = {
        "lifeline_health": {
            "label": PILLAR_LABELS["lifeline_health"],
            "average_score": float(agg["avg_health_score"]) if agg.get("avg_health_score") is not None else None,
            "scored_kecamatan_count": int(agg.get("health_scored_count") or 0),
            "status": "Tersedia" if agg.get("avg_health_score") is not None else "Data tidak memadai",
        },
        "education": {
            "label": PILLAR_LABELS["education"],
            "average_score": float(agg["avg_education_score"]) if agg.get("avg_education_score") is not None else None,
            "scored_kecamatan_count": int(agg.get("education_scored_count") or 0),
            "status": "Tersedia" if agg.get("avg_education_score") is not None else "Data tidak memadai",
        },
        "urban_livability": {
            "label": PILLAR_LABELS["urban_livability"],
            "average_score": float(agg["avg_livability_score"]) if agg.get("avg_livability_score") is not None else None,
            "scored_kecamatan_count": int(agg.get("livability_scored_count") or 0),
            "status": "Tersedia" if agg.get("avg_livability_score") is not None else "Data tidak memadai",
        },
        "mobility_connectivity": {
            "label": PILLAR_LABELS["mobility_connectivity"],
            "average_score": float(agg["avg_mobility_score"]) if agg.get("avg_mobility_score") is not None else None,
            "scored_kecamatan_count": int(agg.get("mobility_scored_count") or 0),
            "status": "Tersedia" if agg.get("avg_mobility_score") is not None else "Data tidak memadai",
        },
    }

    top_5 = [
        {
            "rank": idx,
            "kemendagri_code": r["kemendagri_code"],
            "district_name": r["district_name"],
            "city_name": r["city_name"],
            "composite_score": float(r["composite_score"]),
        }
        for idx, r in enumerate(top_rows, 1)
    ]
    bottom_5 = [
        {
            "rank": idx,
            "kemendagri_code": r["kemendagri_code"],
            "district_name": r["district_name"],
            "city_name": r["city_name"],
            "composite_score": float(r["composite_score"]),
        }
        for idx, r in enumerate(bottom_rows, 1)
    ]

    meta = REGIONS_CATALOG.get(code, {})
    if base_row["scored_kecamatan_count"] == 0:
        coverage_note = (
            f"Seluruh {base_row['total_kecamatan']} kecamatan di {base_row['province_name']} berstatus "
            "'Data tidak memadai' untuk skor komposit karena < 2 jenis fasilitas dinilai memenuhi ambang "
            f"kelengkapan OSM provinsi (minimal {base_row['total_kecamatan']} unit per jenis). "
            f"Pada level lokal (gerbang SD >= 1), {base_row['locally_adequate_osm_count']} kecamatan "
            f"berstatus OSM 'memadai' dan {base_row['locally_gated_osm_count']} berstatus 'tidak_memadai'."
        )
    else:
        coverage_note = (
            f"{base_row['scored_kecamatan_count']} dari {base_row['total_kecamatan']} kecamatan memiliki skor komposit "
            f"numerik; {base_row['insufficient_data_kecamatan_count']} kecamatan berstatus 'Data tidak memadai' (dikecualikan dari rata-rata)."
        )

    result: Dict[str, Any] = {
        "tool": "get_province_summary",
        "is_province_group": False,
        **base_row,
        "pillar_averages": pillar_averages,
        "top_5_kecamatan": top_5,
        "bottom_5_kecamatan": bottom_5,
        "data_sources": meta.get("data_sources", {}),
        "snapshot_dates": meta.get("snapshot_dates", {}),
        "coverage_note": coverage_note,
    }
    _set_cached_json(cache_key, result)
    return result


def get_province_summary(province: str) -> Dict[str, Any]:
    """
    Returns province-level summary (counts, population + source, pillar averages,
    top 5 / bottom 5 scored kecamatan, data sources). Handles aliases and the
    2022 Papua 6-province split.
    """
    resolved = resolve_province_target(province)
    if resolved.get("error"):
        return {"error": resolved["error"]}

    codes = resolved["codes"]
    if not resolved.get("is_group"):
        return _fetch_single_province_summary(codes[0])

    # Ambiguous Papua group summary across active Papua provinces
    cache_key = _scope_cache_key("province_group", "_".join(codes))
    cached = _get_cached_json(cache_key)
    if cached:
        return cached

    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT
                p.kemendagri_code AS province_code,
                p.name AS province_name,
                COUNT(k.id)::int AS total_kecamatan,
                COUNT(s.composite_livability_score)::int AS scored_kecamatan_count,
                COUNT(k.id) FILTER (WHERE s.composite_livability_score IS NULL)::int AS insufficient_data_kecamatan_count,
                COUNT(k.id) FILTER (WHERE s.coverage->'osm_coverage'->>'status' = 'memadai')::int AS locally_adequate_osm_count,
                COUNT(k.id) FILTER (WHERE s.coverage->'osm_coverage'->>'status' = 'tidak_memadai')::int AS locally_gated_osm_count,
                COUNT(k.id) FILTER (WHERE COALESCE(k.population, 0) = 0)::int AS zero_population_kecamatan_count,
                ROUND(AVG(s.composite_livability_score)::numeric, 2) AS average_composite_score,
                COALESCE(SUM(k.population), 0)::bigint AS total_population
            FROM provinces p
            JOIN kabupaten_kota c ON c.province_id = p.id
            JOIN kecamatan k ON k.kabupaten_kota_id = c.id
            LEFT JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = ANY(%s)
            GROUP BY p.kemendagri_code, p.name
            ORDER BY p.kemendagri_code;
            """,
            (codes,),
        )
        rows = cur.fetchall()

    matched_provs = [_format_province_row(r) for r in rows]
    total_kec = sum(p["total_kecamatan"] for p in matched_provs)
    scored_kec = sum(p["scored_kecamatan_count"] for p in matched_provs)
    insufficient_kec = sum(p["insufficient_data_kecamatan_count"] for p in matched_provs)
    local_memadai = sum(p["locally_adequate_osm_count"] for p in matched_provs)
    local_gated = sum(p["locally_gated_osm_count"] for p in matched_provs)
    total_pop = sum(p["total_population"] for p in matched_provs)
    meta_91 = REGIONS_CATALOG.get("91", {})

    result: Dict[str, Any] = {
        "tool": "get_province_summary",
        "is_province_group": True,
        "province_name": resolved["group_name"],
        "ambiguity_note": resolved["ambiguity_note"],
        "provinces_count": len(matched_provs),
        "total_kecamatan": total_kec,
        "scored_kecamatan_count": scored_kec,
        "insufficient_data_kecamatan_count": insufficient_kec,
        "locally_adequate_osm_count": local_memadai,
        "locally_gated_osm_count": local_gated,
        "average_composite_score": None,
        "score_status": "Data tidak memadai" if scored_kec == 0 else "Tersedia",
        "total_population": total_pop,
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "provinces_matched": matched_provs,
        "data_sources": meta_91.get("data_sources", {}),
        "snapshot_dates": meta_91.get("snapshot_dates", {}),
        "coverage_note": (
            f"Dari {total_kec} kecamatan di {len(matched_provs)} provinsi wilayah Papua, "
            f"{local_memadai} kecamatan memenuhi gerbang lokal SD >= 1 (memadai), "
            f"{local_gated} berstatus tidak_memadai, dan {scored_kec} memiliki skor komposit numerik "
            "(karena cakupan fasilitas terpetakan di OSM belum memenuhi ambang >= 2 jenis fasilitas per provinsi)."
        ),
    }
    _set_cached_json(cache_key, result)
    return result


def rank_districts(
    scope: str = "national",
    order: str = "highest",
    metric: str = "composite",
    limit: int = 5,
) -> Dict[str, Any]:
    """
    Ranks scored kecamatan either nationally or within a province/Papua group.
    Excludes kecamatan whose target metric is NULL ('Data tidak memadai').
    """
    eff_limit = min(max(int(limit or 5), 1), 10)

    order_norm = str(order or "highest").strip().lower()
    if order_norm in ("lowest", "asc", "bottom", "terendah", "paling rendah"):
        eff_order = "lowest"
        sql_dir = "ASC"
    else:
        eff_order = "highest"
        sql_dir = "DESC"

    metric_norm = str(metric or "composite").strip().lower().replace("-", "_").replace(" ", "_")
    col_sql, metric_label = _METRIC_COLUMN_MAP.get(
        metric_norm,
        ("s.composite_livability_score", "Indeks Kecukupan Fasilitas Dasar (Komposit)"),
    )
    eff_metric = metric_norm if metric_norm in _METRIC_COLUMN_MAP else "composite"

    scope_str = str(scope or "national").strip()
    scope_norm = scope_str.lower()
    if scope_norm in ("national", "nasional", "indonesia", "all", "semua"):
        target_codes = settings.active_provinces
        scope_label = "Indonesia (Nasional)"
        ambiguity_note = None
        cache_scope = "national"
    else:
        resolved = resolve_province_target(scope_str)
        if resolved.get("error"):
            return {"error": resolved["error"]}
        target_codes = resolved["codes"]
        scope_label = resolved.get("group_name") or resolved.get("resolved_name") or scope_str
        ambiguity_note = resolved.get("ambiguity_note")
        cache_scope = "_".join(target_codes)

    cache_key = _scope_cache_key("rank_districts", cache_scope, eff_order, eff_metric, str(eff_limit))
    cached = _get_cached_json(cache_key)
    if cached:
        return cached

    with get_db_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)::int AS total_matching_scored
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = ANY(%s)
              AND {col_sql} IS NOT NULL;
            """,
            (target_codes,),
        )
        cnt_row = cur.fetchone()
        total_matching = int((cnt_row or {}).get("total_matching_scored") or 0)

        cur.execute(
            f"""
            SELECT k.kemendagri_code, k.name AS district_name, c.name AS city_name,
                   p.kemendagri_code AS province_code, p.name AS province_name,
                   ROUND({col_sql}::numeric, 2) AS score
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE p.kemendagri_code = ANY(%s)
              AND {col_sql} IS NOT NULL
            ORDER BY {col_sql} {sql_dir}, k.kemendagri_code ASC
            LIMIT %s;
            """,
            (target_codes, eff_limit),
        )
        rows = cur.fetchall()

    results = [
        {
            "rank": idx,
            "kemendagri_code": r["kemendagri_code"],
            "district_name": r["district_name"],
            "city_name": r["city_name"],
            "province_code": r["province_code"],
            "province_name": _clean_province_name(str(r["province_code"]), r.get("province_name")),
            "score": float(r["score"]),
        }
        for idx, r in enumerate(rows, 1)
    ]

    note = None
    if not results:
        note = (
            f"Tidak ada kecamatan dengan skor numerik pada metrik '{metric_label}' di {scope_label} "
            "(seluruh kecamatan berstatus 'Data tidak memadai')."
        )
    elif ambiguity_note:
        note = ambiguity_note

    payload: Dict[str, Any] = {
        "tool": "rank_districts",
        "scope": scope_label,
        "order": eff_order,
        "metric": eff_metric,
        "metric_label": metric_label,
        "limit": eff_limit,
        "total_matching_scored": total_matching,
        "results": results,
    }
    if note:
        payload["note"] = note

    _set_cached_json(cache_key, payload)
    return payload


def compare_provinces(provinces: Any) -> Dict[str, Any]:
    """
    Compares 2 to 4 provinces side-by-side (kecamatan counts, scored counts,
    average composite score, pillar averages, population + source).
    """
    if isinstance(provinces, str):
        items = [p.strip() for p in re.split(r"[,;]|\bdan\b", provinces) if p.strip()]
    elif isinstance(provinces, list):
        items = [str(p).strip() for p in provinces if str(p).strip()]
    else:
        items = []

    if len(items) < 2 or len(items) > 4:
        return {"error": "Berikan dua hingga empat provinsi untuk dibandingkan."}

    summaries: List[Dict[str, Any]] = []
    for item in items:
        s = get_province_summary(item)
        if s.get("error"):
            return s
        summaries.append(s)

    scored = [s for s in summaries if s.get("average_composite_score") is not None]
    highest = (
        max(scored, key=lambda x: x["average_composite_score"])
        if scored
        else None
    )
    lowest = (
        min(scored, key=lambda x: x["average_composite_score"])
        if scored
        else None
    )

    compact_rows = []
    for s in summaries:
        p_avgs = s.get("pillar_averages") or {}
        scored_pillars = {
            pk: pv["average_score"]
            for pk, pv in p_avgs.items()
            if isinstance(pv, dict) and pv.get("average_score") is not None
        }
        compact_rows.append({
            "province_code": s.get("province_code"),
            "province_name": s.get("province_name"),
            "island_group": s.get("island_group"),
            "total_kecamatan": s.get("total_kecamatan"),
            "scored_kecamatan_count": s.get("scored_kecamatan_count"),
            "insufficient_data_kecamatan_count": s.get("insufficient_data_kecamatan_count"),
            "average_composite_score": s.get("average_composite_score"),
            "score_status": s.get("score_status"),
            "total_population": s.get("total_population"),
            "population_source": s.get("population_source"),
            "scored_pillar_averages": scored_pillars,
        })

    unscored_names = [s.get("province_name") for s in summaries if s.get("average_composite_score") is None]
    note = (
        f"Provinsi berstatus 'Data tidak memadai' ({', '.join(unscored_names)}) belum memiliki rata-rata skor komposit numerik."
        if unscored_names
        else "Semua provinsi yang dibandingkan memiliki rata-rata skor komposit numerik."
    )

    return {
        "tool": "compare_provinces",
        "compared_count": len(compact_rows),
        "provinces": compact_rows,
        "highest_average_province": (
            {
                "province_name": highest["province_name"],
                "average_composite_score": highest["average_composite_score"],
            }
            if highest
            else None
        ),
        "lowest_average_province": (
            {
                "province_name": lowest["province_name"],
                "average_composite_score": lowest["average_composite_score"],
            }
            if lowest
            else None
        ),
        "note": note,
    }


def get_methodology(topic: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns deterministic methodology, SNI 03-1733-2004 catalog constants (from DB
    regulatory_standards / meta endpoint), pillar weights, reweighting rules, and
    the 'Data tidak memadai' coverage gate definition.
    """
    cache_key = _scope_cache_key("methodology")
    cached = _get_cached_json(cache_key)
    if cached:
        if topic:
            out = dict(cached)
            out["requested_topic"] = topic
            return out
        return cached

    standards_rows: List[Dict[str, Any]] = []
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """
                SELECT facility_type, pillar, population_threshold,
                       service_radius_meters, min_land_area_m2,
                       legal_reference, scored
                FROM regulatory_standards
                ORDER BY pillar, facility_type;
                """
            )
            standards_rows = [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("Falling back to static STANDARDS_AVAILABILITY_SPEC in get_methodology: %s", exc)
        standards_rows = [
            {
                "facility_type": ft,
                "pillar": spec["pillar"],
                "standard_name": "SNI 03-1733-2004",
                "scored": spec["scored"],
            }
            for ft, spec in sorted(STANDARDS_AVAILABILITY_SPEC.items())
        ]

    scored_count = sum(1 for r in standards_rows if r.get("scored"))
    info_count = len(standards_rows) - scored_count

    pillars_info = []
    for p_key, weight in BASE_PILLAR_WEIGHTS.items():
        p_rows = [r for r in standards_rows if r.get("pillar") == p_key]
        p_scored = [r["facility_type"] for r in p_rows if r.get("scored")]
        p_info = [r["facility_type"] for r in p_rows if not r.get("scored")]
        pillars_info.append({
            "pillar": p_key,
            "label": PILLAR_LABELS.get(p_key, p_key),
            "base_weight": weight,
            "base_weight_pct": round(weight * 100.0, 2),
            "scored_types_count": len(p_scored),
            "informational_types_count": len(p_info),
            "scored_facility_types": p_scored,
            "informational_facility_types": p_info,
        })

    result: Dict[str, Any] = {
        "tool": "get_methodology",
        "standard_reference": (
            "SNI 03-1733-2004 (Tata Cara Perencanaan Lingkungan Perumahan di Perkotaan, Badan Standardisasi Nasional). "
            "SNI 1733:2026 diterbitkan BSN pada Mei 2026, namun sistem saat ini masih mengacu pada SNI 03-1733-2004."
        ),
        "total_standards_catalog": len(standards_rows) or 16,
        "scored_standards_count": scored_count or 7,
        "informational_standards_count": info_count or 9,
        "pillars": pillars_info,
        "scoring_rules": {
            "facility_compliance": (
                "Kebutuhan unit = ceil(populasi / ambang_penduduk_SNI), minimal 1. "
                "Persentase kepatuhan = min(100, (eksisting / kebutuhan) * 100). "
                "Defisit unit = eksisting - kebutuhan."
            ),
            "pillar_score": (
                "Skor pilar = rata-rata aritmetika kepatuhan (%) dari jenis fasilitas berstatus 'available' "
                "pada pilar tersebut. Jenis dengan data 'insufficient' atau 'not_available' dikecualikan, tidak diberi nilai 0."
            ),
            "composite_inclusion_min_types": 2,
            "composite_reweighting": (
                "Pilar masuk skor komposit hanya jika minimal 2 jenis fasilitasnya dinilai ('available'). "
                "Bobot dasar (Kesehatan 30%, Pendidikan 25%, Ruang Hidup 25%, Mobilitas 20%) diskalakan "
                "proporsional terhadap total bobot pilar yang memenuhi syarat (misalnya DKI Jakarta memakai "
                "Kesehatan 0.30 + Pendidikan 0.25 = 0.55 sehingga bobot efektif 54.55% dan 45.45%; "
                "14 provinsi luar DKI yang hanya memiliki Pilar Pendidikan memakai bobot 100% Pendidikan)."
            ),
        },
        "data_tidak_memadai_rule": {
            "province_threshold_rule": (
                f"Setiap jenis fasilitas harus memiliki minimal N rekaman OSM terklasifikasi di provinsi "
                f"(N = jumlah kecamatan provinsi, contoh {DEFAULT_MIN_RECORDS_THRESHOLD} untuk DKI Jakarta) agar berstatus 'available'."
            ),
            "local_sd_gate_rule": OSM_COVERAGE_RULE,
            "local_sd_population_threshold": SD_POPULATION_THRESHOLD,
            "local_gate_reason": LOCAL_GATE_REASON,
            "null_handling": (
                "Kecamatan dengan cakupan tidak memadai atau kurang dari 2 jenis fasilitas tersedia memiliki "
                "skor komposit NULL (ditampilkan sebagai 'Data tidak memadai', tidak pernah 0) dan dikecualikan "
                "dari peringkat maupun rata-rata."
            ),
        },
        "simulation_assumptions": {
            "impact_rule": settings.SIMULATION_IMPACT_RULE,
            "occupants_per_unit": settings.SUPERBLOCK_OCCUPANTS_PER_UNIT,
            "school_age_ratio": settings.SUPERBLOCK_SCHOOL_AGE_RATIO,
            "kdb_ratio_pct": round(settings.SUPERBLOCK_KDB_RATIO * 100.0, 2),
            "rth_ratio_pct": round(settings.SUPERBLOCK_RTH_RATIO * 100.0, 2),
            "stormwater_depth_mm_per_day": round(settings.SUPERBLOCK_STORMWATER_DEPTH_M * 1000.0, 2),
        },
        "standards_table": standards_rows,
    }
    _set_cached_json(cache_key, result)
    if topic:
        out = dict(result)
        out["requested_topic"] = topic
        return out
    return result
