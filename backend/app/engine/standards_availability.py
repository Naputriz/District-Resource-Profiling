"""
Standards Availability and Proportional Pillar Scoring Engine.
Implements standards availability and composite scoring (README §8, §14):
1. Data availability flag per facility type:
   - 'not_available': mapping says NOT_AVAILABLE_FROM_OSM, or 0 records city-wide.
   - 'insufficient': fewer than 44 classified records city-wide, REGARDLESS of confidence.
   - otherwise 'available'.
2. S_pilar = mean of S_jenis over 'available' types only.
   Types that are 'insufficient' or 'not_available' are excluded and listed, never scored as 0.
3. Every scorecard includes per pillar:
   - types_scored (list of facility types)
   - types_excluded (list of {facility_type, reason, availability})
   - data_coverage (scored / total types in that pillar)
   - score: float | None (None if types_scored is empty)
   - status: "tersedia" (>1 types scored) | "cakupan data rendah" (1 type scored) | "data tidak tersedia" (0 types scored)
   - included_in_composite: bool (True only if types_scored >= 2)
4. Composite rule: A pillar enters the composite ONLY if types_scored >= 2.
   A pillar with exactly 1 scored type gets weight 0 in the composite; the remaining eligible
   pillar weights are re-normalized proportionally.
5. Unified single availability path via get_city_wide_standards_availability().
"""

import json
import logging
import math
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

_CURRENT_AVAILABILITY_SOURCE: str = "database"

# -----------------------------------------------------------------------------
# 1. Standards Availability Specification (16 Regulatory Standards per §6)
# -----------------------------------------------------------------------------

STANDARDS_AVAILABILITY_SPEC: Dict[str, Dict[str, Any]] = {
    # Pilar 1: Kesehatan & Keselamatan
    # Dinilai (§6.2)
    "puskesmas_kelurahan": {"pillar": "lifeline_health", "scored": True, "confidence": "Low", "is_not_available_from_osm": False},
    "puskesmas_kecamatan": {"pillar": "lifeline_health", "scored": True, "confidence": "Medium", "is_not_available_from_osm": False},
    "pos_damkar": {"pillar": "lifeline_health", "scored": True, "confidence": "High", "is_not_available_from_osm": False},
    # Informasi saja (§6.3)
    "rumah_sakit": {"pillar": "lifeline_health", "scored": False, "confidence": "High", "is_not_available_from_osm": False},
    "posyandu": {"pillar": "lifeline_health", "scored": False, "confidence": "Low", "is_not_available_from_osm": False},

    # Pilar 2: Pendidikan (4 standard types, semua dinilai §6.2)
    "taman_kanak_kanak": {"pillar": "education", "scored": True, "confidence": "Medium", "is_not_available_from_osm": False},
    "sekolah_dasar": {"pillar": "education", "scored": True, "confidence": "Medium", "is_not_available_from_osm": False},
    "sekolah_menengah_pertama": {"pillar": "education", "scored": True, "confidence": "Medium", "is_not_available_from_osm": False},
    "sekolah_menengah_atas": {"pillar": "education", "scored": True, "confidence": "Medium", "is_not_available_from_osm": False},

    # Pilar 3: Ruang Hidup & Rekreasi (4 standard types, semua informasi §6.3)
    "taman_rt": {"pillar": "urban_livability", "scored": False, "confidence": "Low", "is_not_available_from_osm": True},
    "taman_rptra": {"pillar": "urban_livability", "scored": False, "confidence": "Medium", "is_not_available_from_osm": False},
    "taman_kelurahan": {"pillar": "urban_livability", "scored": False, "confidence": "Low", "is_not_available_from_osm": False},
    "taman_kecamatan": {"pillar": "urban_livability", "scored": False, "confidence": "High", "is_not_available_from_osm": False},

    # Pilar 4: Mobilitas & Aksesibilitas (3 standard types, semua informasi §6.3)
    "stasiun_transit": {"pillar": "mobility_connectivity", "scored": False, "confidence": "High", "is_not_available_from_osm": False},
    "halte_transjakarta": {"pillar": "mobility_connectivity", "scored": False, "confidence": "High", "is_not_available_from_osm": False},
    "pasar_tradisional": {"pillar": "mobility_connectivity", "scored": False, "confidence": "Medium", "is_not_available_from_osm": False},
}

CITY_WIDE_CLASSIFIED_COUNTS: Dict[str, int] = {
    "halte_transjakarta": 3949,
    "pasar_tradisional": 235,
    "pos_damkar": 99,
    "posyandu": 598,
    "puskesmas_kecamatan": 57,
    "puskesmas_kelurahan": 289,
    "rumah_sakit": 327,
    "sekolah_dasar": 1483,
    "sekolah_menengah_atas": 539,
    "sekolah_menengah_pertama": 633,
    "stasiun_transit": 174,
    "taman_kanak_kanak": 2274,
    "taman_kecamatan": 0,
    "taman_kelurahan": 2,
    "taman_rptra": 22,
    "taman_rt": 0,
}

BASE_PILLAR_WEIGHTS: Dict[str, float] = {
    "lifeline_health": 0.30,
    "education": 0.25,
    "urban_livability": 0.25,
    "mobility_connectivity": 0.20,
}

PILLAR_LABELS: Dict[str, str] = {
    "lifeline_health": "Pilar 1: Kesehatan & Keselamatan",
    "education": "Pilar 2: Pendidikan",
    "urban_livability": "Pilar 3: Ruang Hidup & Rekreasi",
    "mobility_connectivity": "Pilar 4: Mobilitas & Aksesibilitas",
}

PILLAR_INDONESIAN_NAMES: Dict[str, str] = {
    "lifeline_health": "kesehatan dan keselamatan",
    "education": "pendidikan",
    "urban_livability": "ruang hidup",
    "mobility_connectivity": "mobilitas dan aksesibilitas",
}

_CACHED_AVAILABILITY_MAP: Optional[Dict[str, Tuple[str, str]]] = None


def evaluate_availability(
    facility_type: str,
    classified_count: int,
    confidence: Optional[str] = None,
    is_not_available_from_osm: Optional[bool] = None
) -> Tuple[str, str]:
    """
    Evaluates data availability for a facility type:
    - 'not_available': NOT_AVAILABLE_FROM_OSM or 0 records city-wide.
    - 'insufficient': fewer than 44 classified records city-wide, REGARDLESS of confidence.
    - otherwise 'available'.
    Returns (availability_flag, reason).
    """
    spec = STANDARDS_AVAILABILITY_SPEC.get(facility_type, {})
    conf = confidence or spec.get("confidence", "Medium")
    not_avail_mapping = (
        is_not_available_from_osm
        if is_not_available_from_osm is not None
        else spec.get("is_not_available_from_osm", False)
    )

    if not_avail_mapping or classified_count == 0:
        if not_avail_mapping:
            return ("not_available", "NOT_AVAILABLE_FROM_OSM (0 classified records city-wide)")
        return ("not_available", "0 classified records city-wide in OSM")

    # Completeness decides availability: fewer than 44 records is insufficient regardless of confidence
    if classified_count < 44:
        return ("insufficient", f"{classified_count} classified records city-wide (<44) - kelengkapan data tidak memadai")

    return ("available", f"Classified records >= 44 ({classified_count})")


def get_city_wide_standards_availability(
    force_refresh: bool = False
) -> Dict[str, Tuple[str, str]]:
    """
    Returns single unified data availability mapping for all 16 standards:
    facility_type -> (availability_flag, reason).
    
    Evaluates scoring eligibility:
    - Eliminates divergent scoring paths between baseline and simulation.
    - Tries querying `regulatory_standards` from database if available.
    - Falls back to evaluated real CITY_WIDE_CLASSIFIED_COUNTS snapshot.
    - Caches results in-memory.
    """
    global _CACHED_AVAILABILITY_MAP, _CURRENT_AVAILABILITY_SOURCE
    if _CACHED_AVAILABILITY_MAP is not None and not force_refresh:
        return _CACHED_AVAILABILITY_MAP

    avail_map: Dict[str, Tuple[str, str]] = {}
    source = "database"

    try:
        from backend.app.core.db import get_db_cursor
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT facility_type, classified_count, confidence, data_availability, availability_reason
                FROM regulatory_standards;
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    ft = r["facility_type"]
                    avail = r.get("data_availability")
                    reason = r.get("availability_reason")
                    if not avail:
                        cnt = r.get("classified_count") or CITY_WIDE_CLASSIFIED_COUNTS.get(ft, 0)
                        spec = STANDARDS_AVAILABILITY_SPEC.get(ft, {})
                        conf = r.get("confidence") or spec.get("confidence", "Medium")
                        is_not_avail = spec.get("is_not_available_from_osm", False)
                        avail, reason = evaluate_availability(ft, cnt, conf, is_not_avail)
                    avail_map[ft] = (avail, reason or "")
            else:
                source = "snapshot"
                record_availability_fallback_incident("regulatory_standards table returned 0 rows")
    except Exception as e:
        source = "snapshot"
        record_availability_fallback_incident(str(e))

    # Complete any missing standards using local snapshot
    for ft, spec in STANDARDS_AVAILABILITY_SPEC.items():
        if ft not in avail_map or not avail_map[ft][0]:
            cnt = CITY_WIDE_CLASSIFIED_COUNTS.get(ft, 0)
            conf = spec.get("confidence", "Medium")
            is_not_avail = spec.get("is_not_available_from_osm", False)
            avail, reason = evaluate_availability(ft, cnt, conf, is_not_avail)
            avail_map[ft] = (avail, reason)

    _CURRENT_AVAILABILITY_SOURCE = source
    _CACHED_AVAILABILITY_MAP = avail_map
    return _CACHED_AVAILABILITY_MAP


def get_current_availability_source() -> str:
    """Returns 'database' or 'snapshot' indicating the source of standards availability."""
    global _CURRENT_AVAILABILITY_SOURCE
    return _CURRENT_AVAILABILITY_SOURCE


def record_availability_fallback_incident(error_msg: str):
    """
    Logs a WARNING and records an incident_logs row when availability cannot be
    loaded from regulatory_standards in the database and falls back to snapshot.
    """
    logger.warning(
        f"[WATCHDOG] Failed to load standards availability from database: {error_msg}. "
        f"Falling back to CITY_WIDE_CLASSIFIED_COUNTS snapshot."
    )
    try:
        from backend.app.core.db import get_db_cursor
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO incident_logs (
                    incident_type, severity, target_service, action_taken, status, error_payload
                ) VALUES (%s, %s, %s, %s, %s, %s);
            """, (
                "availability_snapshot_fallback",
                "WARNING",
                "standards_availability",
                "Fell back to CITY_WIDE_CLASSIFIED_COUNTS snapshot due to database exception",
                "FALLBACK_ACTIVE",
                json.dumps({"error": error_msg})
            ))
    except Exception as e:
        logger.error(f"[WATCHDOG] Failed to record availability fallback incident: {e}")


def calculate_pillar_and_composite_scores(
    metrics_detail: List[Dict[str, Any]],
    availability_map: Optional[Dict[str, Tuple[str, str]]] = None
) -> Dict[str, Any]:
    """
    Calculates deterministic pillar scores and proportional composite score.
    
    COMPOSITE COVERAGE RULE:
    -----------------------------------------------------------------------
    1. S_pilar = arithmetic mean of S_jenis over 'available' facility types in that pillar.
       - Types marked 'insufficient' or 'not_available' are EXCLUDED from the mean, never scored as 0.
       - If types_scored == 0: score is None, status is 'data tidak tersedia', included_in_composite = False.
       - If types_scored == 1: score is calculated, status is 'cakupan data rendah', included_in_composite = False (WEIGHT 0 IN COMPOSITE).
       - If types_scored >= 2: score is calculated, status is 'tersedia', included_in_composite = True.
    2. A pillar enters the composite ONLY if types_scored >= 2.
       - Thin pillars with only 1 scored type are excluded from driving 25% of the composite.
       - The remaining eligible pillar weights are re-normalized proportionally:
         W'_p = BaseWeight_p / sum(BaseWeight_q for q in EligiblePillars).
    3. Composite Note explicitly states which pillars were excluded and why.
    """
    if availability_map is None:
        availability_map = get_city_wide_standards_availability()

    # Group metrics by pillar
    pillar_metrics: Dict[str, List[Dict[str, Any]]] = {
        "lifeline_health": [],
        "education": [],
        "urban_livability": [],
        "mobility_connectivity": []
    }

    for m in metrics_detail:
        p = m.get("pillar")
        if p in pillar_metrics:
            pillar_metrics[p].append(m)

    pillar_scores_res: Dict[str, Any] = {}

    for pillar, p_metrics in pillar_metrics.items():
        types_scored: List[str] = []
        types_excluded: List[Dict[str, Any]] = []
        scored_values: List[float] = []

        total_scored_types = sum(
            1 for m in p_metrics
            if (
                m.get("scored")
                if m.get("scored") is not None
                else STANDARDS_AVAILABILITY_SPEC.get(m.get("facility_type", ""), {}).get("scored", False)
            )
        )

        for m in p_metrics:
            ftype = m.get("facility_type", "")
            is_scored = m.get("scored")
            if is_scored is None:
                is_scored = STANDARDS_AVAILABILITY_SPEC.get(ftype, {}).get("scored", False)

            if availability_map and ftype in availability_map:
                avail, reason = availability_map[ftype]
            else:
                avail = m.get("data_availability", "available")
                reason = m.get("availability_reason", "")

            # Informational types (§6.3) are never scored and never produce deficit
            if not is_scored:
                types_excluded.append({
                    "facility_type": ftype,
                    "availability": "informational",
                    "reason": "Fasilitas informasi saja (§6.3) - tidak dinilai"
                })
                continue

            if avail == "available" and m.get("compliance_pct") is not None:
                types_scored.append(ftype)
                scored_values.append(float(m.get("compliance_pct", 0.0)))
            else:
                types_excluded.append({
                    "facility_type": ftype,
                    "availability": avail,
                    "reason": reason
                })

        coverage = round(len(types_scored) / max(1, total_scored_types), 4) if total_scored_types > 0 else 0.0

        # README §8: A pillar enters the composite ONLY if types_scored >= 2.
        # Fewer than 2 scored+available types: no score number at all (null), status 'cakupan data rendah', weight 0.
        if len(types_scored) >= 2:
            p_score = round(sum(scored_values) / len(scored_values), 2)
            pillar_scores_res[pillar] = {
                "score": p_score,
                "status": "tersedia",
                "included_in_composite": True,
                "label": PILLAR_LABELS.get(pillar, pillar),
                "types_scored": types_scored,
                "types_excluded": types_excluded,
                "data_coverage": coverage
            }
        else:
            pillar_scores_res[pillar] = {
                "score": None,
                "status": "cakupan data rendah",
                "included_in_composite": False,
                "label": PILLAR_LABELS.get(pillar, pillar),
                "types_scored": types_scored,
                "types_excluded": types_excluded,
                "data_coverage": coverage
            }

    # Filter eligible pillars for composite calculation: must have included_in_composite == True and score is not None
    eligible_pillars = {
        p: pillar_scores_res[p]["score"]
        for p in BASE_PILLAR_WEIGHTS
        if pillar_scores_res[p]["included_in_composite"] and pillar_scores_res[p]["score"] is not None
    }

    low_cov_pillars = [
        p for p in BASE_PILLAR_WEIGHTS
        if pillar_scores_res[p]["status"] == "cakupan data rendah"
    ]
    missing_pillars = [
        p for p in BASE_PILLAR_WEIGHTS
        if pillar_scores_res[p]["status"] == "data tidak tersedia"
    ]

    if len(eligible_pillars) == len(BASE_PILLAR_WEIGHTS):
        # All 4 pillars are eligible (types_scored >= 2)
        composite = round(
            sum(eligible_pillars[p] * BASE_PILLAR_WEIGHTS[p] for p in eligible_pillars),
            2
        )
        composite_note = "Semua 4 pilar memiliki data fasilitas yang memadai (cakupan penuh)."
    elif len(eligible_pillars) == 1:
        # Exactly 1 pillar is active
        single_p = list(eligible_pillars.keys())[0]
        composite = round(eligible_pillars[single_p], 2)
        p_name = PILLAR_INDONESIAN_NAMES.get(single_p, single_p).title()
        composite_note = f"Indeks saat ini hanya dari pilar {p_name} (pilar lain belum memenuhi batas minimal 2 jenis fasilitas dinilai)."
    elif eligible_pillars:
        # Re-normalize remaining eligible pillar weights
        active_weight_sum = sum(BASE_PILLAR_WEIGHTS[p] for p in eligible_pillars)
        composite = 0.0
        for p, score in eligible_pillars.items():
            scaled_w = BASE_PILLAR_WEIGHTS[p] / active_weight_sum
            composite += scaled_w * score
        composite = round(composite, 2)

        note_parts = []
        if low_cov_pillars:
            for lp in low_cov_pillars:
                lp_name = PILLAR_INDONESIAN_NAMES.get(lp, lp)
                lp_scored = len(pillar_scores_res[lp]["types_scored"])
                total_std = sum(
                    1 for m in pillar_metrics[lp]
                    if (
                        m.get("scored")
                        if m.get("scored") is not None
                        else STANDARDS_AVAILABILITY_SPEC.get(m.get("facility_type", ""), {}).get("scored", False)
                    )
                )
                if total_std == 0:
                    note_parts.append(
                        f"Pilar {lp_name} tidak dihitung dalam skor komposit: tidak ada jenis fasilitas yang dinilai (lihat README §6.3)"
                    )
                else:
                    note_parts.append(
                        f"Pilar {lp_name} tidak dihitung dalam skor komposit: cakupan data rendah ({lp_scored} dari {total_std} standar dinilai)"
                    )
        if missing_pillars:
            for mp in missing_pillars:
                mp_name = PILLAR_INDONESIAN_NAMES.get(mp, mp)
                note_parts.append(f"Pilar {mp_name} tidak memiliki data ketersediaan (status: data tidak tersedia)")

        note_parts.append(
            f"Bobot pilar yang memenuhi syarat diskalakan secara proporsional (total bobot dasar aktif = {active_weight_sum:.2f})."
        )
        composite_note = ". ".join(note_parts)
    else:
        composite = None
        composite_note = "Tidak ada pilar dengan cakupan data memadai (minimal 2 jenis) untuk menghitung skor komposit."

    return {
        "composite_score": composite,
        "composite_livability_score": composite,
        "composite_note": composite_note,
        "pillar_scores": pillar_scores_res,
        "availability_source": get_current_availability_source()
    }
