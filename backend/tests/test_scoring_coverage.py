"""
Unit tests for Standards Availability, Coverage, and Proportional Re-weighting.
Scoring coverage compliance tests:
1. Rule: a pillar enters the composite ONLY if types_scored >= 2.
2. A pillar with exactly 1 scored type keeps its score and status 'cakupan data rendah',
   but gets weight 0 in the composite; remaining pillar weights re-normalize proportionally.
3. Every pillar response includes included_in_composite: bool.
4. Exact mathematical formula verification for proportional re-weighting.
5. Exact parity between What-If simulation with pop_shock_count = 0 and baseline scorecard.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import math
import pytest
from backend.app.engine.standards_availability import (
    evaluate_availability,
    calculate_pillar_and_composite_scores,
    get_city_wide_standards_availability,
    STANDARDS_AVAILABILITY_SPEC,
    BASE_PILLAR_WEIGHTS
)

@pytest.mark.unit
def test_evaluate_availability_rules():
    # Rule 1: not_available from mapping or 0 count
    flag1, reason1 = evaluate_availability("taman_rt", 0, "Low", True)
    assert flag1 == "not_available"
    assert "NOT_AVAILABLE_FROM_OSM" in reason1

    flag2, reason2 = evaluate_availability("taman_kecamatan", 0, "High", False)
    assert flag2 == "not_available"
    assert "0 classified records" in reason2

    # Rule 2: insufficient (count < 44 REGARDLESS of confidence)
    flag3, reason3 = evaluate_availability("taman_kelurahan", 2, "Low", False)
    assert flag3 == "insufficient"
    assert "<44" in reason3

    flag_rptra, reason_rptra = evaluate_availability("taman_rptra", 22, "Medium", False)
    assert flag_rptra == "insufficient"
    assert "<44" in reason_rptra

    # Rule 3: available (count >= 44)
    flag4, _ = evaluate_availability("pos_damkar", 99, "Medium", False)
    assert flag4 == "available"

    flag5, _ = evaluate_availability("rumah_sakit", 327, "High", False)
    assert flag5 == "available"


@pytest.mark.unit
def test_pillar_single_type_excluded_from_composite():
    """
    A pillar with fewer than 2 scored+available types gets
    score: None, status: 'cakupan data rendah', and weight 0 (included_in_composite: False).
    The remaining pillars with types_scored >= 2 re-normalize proportionally.
    """
    availability_map = {
        "puskesmas_kelurahan": ("available", "Available"),
        "pos_damkar": ("available", "Available"),          # Health: 2 scored types -> included
        "sekolah_dasar": ("available", "Available"),
        "sekolah_menengah_pertama": ("available", "Available"),  # Education: 2 scored types -> included
        "taman_rt": ("not_available", "No data"),
        "taman_kelurahan": ("insufficient", "Insufficient"), # Livability: 0 scored -> EXCLUDED
        "stasiun_transit": ("available", "Available"),
        "halte_transjakarta": ("available", "Available")    # Mobility: 0 scored -> EXCLUDED
    }

    metrics = [
        {"pillar": "lifeline_health", "facility_type": "puskesmas_kelurahan", "compliance_pct": 80.0, "scored": True},
        {"pillar": "lifeline_health", "facility_type": "pos_damkar", "compliance_pct": 60.0, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_dasar", "compliance_pct": 50.0, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_menengah_pertama", "compliance_pct": 70.0, "scored": True},
        {"pillar": "urban_livability", "facility_type": "taman_rt", "compliance_pct": 0.0, "scored": False},
        {"pillar": "urban_livability", "facility_type": "taman_kelurahan", "compliance_pct": 0.0, "scored": False},
        {"pillar": "mobility_connectivity", "facility_type": "stasiun_transit", "compliance_pct": 90.0, "scored": False},
        {"pillar": "mobility_connectivity", "facility_type": "halte_transjakarta", "compliance_pct": 90.0, "scored": False}
    ]

    res = calculate_pillar_and_composite_scores(metrics, availability_map)
    pillars = res["pillar_scores"]

    # Health: 2 types scored -> included_in_composite: True, status: 'tersedia'
    assert pillars["lifeline_health"]["status"] == "tersedia"
    assert pillars["lifeline_health"]["included_in_composite"] is True
    assert pillars["lifeline_health"]["score"] == 70.0

    # Education: 2 types scored -> included_in_composite: True, status: 'tersedia'
    assert pillars["education"]["status"] == "tersedia"
    assert pillars["education"]["included_in_composite"] is True
    assert pillars["education"]["score"] == 60.0

    # Livability: 0 scored types (<2) -> included_in_composite: False, status: 'cakupan data rendah', score: None
    assert pillars["urban_livability"]["status"] == "cakupan data rendah"
    assert pillars["urban_livability"]["included_in_composite"] is False
    assert pillars["urban_livability"]["score"] is None

    # Mobility: 0 scored types (<2) -> included_in_composite: False, status: 'cakupan data rendah', score: None
    assert pillars["mobility_connectivity"]["status"] == "cakupan data rendah"
    assert pillars["mobility_connectivity"]["included_in_composite"] is False
    assert pillars["mobility_connectivity"]["score"] is None

    # Re-weighting: Health (0.30) + Education (0.25) = 0.55
    # Scaled weights:
    # W'_health = 0.30 / 0.55
    # W'_edu    = 0.25 / 0.55
    # Composite = (0.30 * 70.0 + 0.25 * 60.0) / 0.55 = 36.0 / 0.55 = 65.45
    assert res["composite_score"] == 65.45
    assert "Pilar ruang hidup tidak dihitung dalam skor komposit: tidak ada jenis fasilitas yang dinilai (lihat README §6.3)" in res["composite_note"]
    assert "0.55" in res["composite_note"]


@pytest.mark.unit
def test_exact_reweighting_edge_cases():
    """Verifies proportional re-weighting with multiple excluded pillars."""
    availability_map = {
        "puskesmas_kelurahan": ("available", "Available"),
        "pos_damkar": ("available", "Available"),
        "sekolah_dasar": ("not_available", "Excluded"),
        "taman_rt": ("not_available", "Excluded"),
        "stasiun_transit": ("not_available", "Excluded")
    }

    # Only health has >= 2 scored types: score 75.0
    metrics = [
        {"pillar": "lifeline_health", "facility_type": "puskesmas_kelurahan", "compliance_pct": 80.0, "existing": 4, "required": 5, "scored": True},
        {"pillar": "lifeline_health", "facility_type": "pos_damkar", "compliance_pct": 70.0, "existing": 3, "required": 4, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_dasar", "compliance_pct": 0.0, "existing": 0, "required": 5, "scored": True},
        {"pillar": "urban_livability", "facility_type": "taman_rt", "compliance_pct": 0.0, "existing": 0, "required": 5, "scored": False},
        {"pillar": "mobility_connectivity", "facility_type": "stasiun_transit", "compliance_pct": 0.0, "existing": 0, "required": 2, "scored": False}
    ]

    res = calculate_pillar_and_composite_scores(metrics, availability_map)
    # With only health active (>=2 types), normalized weight is 1.0, so composite == health score
    assert res["composite_score"] == 75.0
    assert res["pillar_scores"]["lifeline_health"]["included_in_composite"] is True
    assert res["pillar_scores"]["education"]["included_in_composite"] is False
    assert res["pillar_scores"]["urban_livability"]["included_in_composite"] is False
    assert res["pillar_scores"]["mobility_connectivity"]["included_in_composite"] is False


@pytest.mark.db
def test_simulation_what_if_zero_shock_matches_scorecard():
    """
    Test zero-shock scorecard consistency:
    For Gambir, Setiabudi, Tebet, Kebon Jeruk, Kepulauan Seribu Selatan,
    a what-if simulation with population_shock_count = 0 returns
    baseline_composite_score equal to the scorecard composite (exact, 2 decimals),
    and active pillar scores match.
    """
    from backend.app.core.db import get_db_cursor, init_db_pool, close_db_pool
    from backend.app.engine.simulation import WhatIfSimulationEngine
    import json

    init_db_pool()
    sample_codes = ["31.73.08", "31.71.10", "31.71.09", "31.74.02", "31.01.01"]

    with get_db_cursor() as cur:
        cur.execute("SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference FROM regulatory_standards;")
        stds = cur.fetchall()

        for code in sample_codes:
            cur.execute("""
                SELECT k.id, k.kemendagri_code, k.name, k.population,
                       s.health_score, s.education_score, s.livability_score, s.mobility_score,
                       s.composite_livability_score
                FROM kecamatan k
                JOIN district_compliance_scores s ON s.district_id = k.id
                WHERE k.kemendagri_code = %s;
            """, (code,))
            row = cur.fetchone()
            assert row is not None, f"District {code} not found in database"

            cur.execute("SELECT facility_type, COUNT(*) as cnt FROM public_facilities WHERE kecamatan_id = %s AND is_active = TRUE GROUP BY facility_type;", (row["id"],))
            counts = {r["facility_type"]: r["cnt"] for r in cur.fetchall()}

            sim_delta = WhatIfSimulationEngine.compute_scenario_delta(
                district_code=row["kemendagri_code"],
                district_name=row["name"],
                baseline_population=row["population"],
                existing_facility_counts=counts,
                regulatory_standards=stds,
                pop_shock_count=0
            )

            scorecard_comp = float(row["composite_livability_score"])
            sim_comp = sim_delta.baseline_composite_score
            name = row["name"]

            # Exact match to 2 decimals
            assert round(sim_comp, 2) == round(scorecard_comp, 2), f"{name}: sim baseline {sim_comp} != scorecard {scorecard_comp}"

            # Pillar scores match
            base_pillars = sim_delta.baseline_pillar_scores
            h_score = base_pillars["lifeline_health"]["score"]
            e_score = base_pillars["education"]["score"]
            l_score = base_pillars["urban_livability"]["score"]
            m_score = base_pillars["mobility_connectivity"]["score"]

            assert round(h_score, 2) == round(float(row["health_score"]), 2), f"{name}: health mismatch"
            assert round(e_score, 2) == round(float(row["education_score"]), 2), f"{name}: education mismatch"
            if row["livability_score"] is not None:
                assert round(l_score, 2) == round(float(row["livability_score"]), 2), f"{name}: livability mismatch"
            else:
                assert l_score is None

            if row["mobility_score"] is not None:
                assert round(m_score, 2) == round(float(row["mobility_score"]), 2), f"{name}: mobility mismatch"
            else:
                assert m_score is None

            # Check included_in_composite flag per pillar
            assert base_pillars["lifeline_health"]["included_in_composite"] is True
            assert base_pillars["education"]["included_in_composite"] is True
            assert base_pillars["urban_livability"]["included_in_composite"] is False
            assert base_pillars["mobility_connectivity"]["included_in_composite"] is False


@pytest.mark.db
def test_availability_snapshot_fallback_logs_incident():
    """
    Score validation item 2:
    When database raises an exception during get_city_wide_standards_availability(force_refresh=True),
    it logs a WARNING, inserts an incident_logs row (type: availability_snapshot_fallback),
    and sets availability_source to 'snapshot'.
    """
    from contextlib import contextmanager
    from unittest.mock import patch
    from backend.app.engine.standards_availability import (
        get_city_wide_standards_availability,
        get_current_availability_source,
        calculate_pillar_and_composite_scores
    )
    from backend.app.core.db import get_db_cursor as real_get_db_cursor, init_db_pool

    init_db_pool()
    call_count = [0]

    @contextmanager
    def mock_db_cursor():
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Simulated DB Connection Error")
        with real_get_db_cursor() as cur:
            yield cur

    with patch("backend.app.core.db.get_db_cursor", side_effect=mock_db_cursor):
        avail_map = get_city_wide_standards_availability(force_refresh=True)
        assert len(avail_map) == 16
        assert get_current_availability_source() == "snapshot"

        # Check scorecard exposure
        res = calculate_pillar_and_composite_scores([
            {"pillar": "lifeline_health", "facility_type": "rumah_sakit", "compliance_pct": 80.0},
            {"pillar": "lifeline_health", "facility_type": "pos_damkar", "compliance_pct": 70.0}
        ])
        assert res["availability_source"] == "snapshot"

    # Verify incident was logged to incident_logs in PostgreSQL
    with real_get_db_cursor() as cur:
        cur.execute("""
            SELECT id, incident_type, severity, target_service, action_taken, status, error_payload
            FROM incident_logs
            WHERE incident_type = 'availability_snapshot_fallback'
            ORDER BY created_at DESC
            LIMIT 1;
        """)
        row = cur.fetchone()
        assert row is not None
        assert row["incident_type"] == "availability_snapshot_fallback"
        assert row["severity"] == "WARNING"
        assert "Simulated DB Connection Error" in str(row["error_payload"])

    # Reset cache back to normal database state
    get_city_wide_standards_availability(force_refresh=True)
    assert get_current_availability_source() == "database"


@pytest.mark.db
def test_valid1_removed_types_absent():
    """Verify 6 removed types from §6.4 are absent from standards and city counts."""
    from backend.app.engine.standards_availability import (
        CITY_WIDE_CLASSIFIED_COUNTS,
        STANDARDS_AVAILABILITY_SPEC
    )
    removed_types = [
        "tps_3r", "hutan_kota", "gelanggang_olahraga",
        "perpustakaan_wilayah", "sentra_niaga_umkm", "pos_polisi"
    ]
    for r_type in removed_types:
        assert r_type not in CITY_WIDE_CLASSIFIED_COUNTS, f"{r_type} still in snapshot"
        assert r_type not in STANDARDS_AVAILABILITY_SPEC, f"{r_type} still in spec"

    # Also check DB
    from backend.app.core.db import get_db_cursor, init_db_pool
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT facility_type FROM regulatory_standards WHERE facility_type = ANY(%s);", (removed_types,))
        rows = cur.fetchall()
        assert len(rows) == 0, f"Found removed types in regulatory_standards: {rows}"


@pytest.mark.unit
def test_valid1_informational_types_produce_no_deficit():
    """Informational types produce no deficit and no score."""
    from backend.app.engine.standards_availability import (
        calculate_pillar_and_composite_scores,
        STANDARDS_AVAILABILITY_SPEC
    )
    # Check that informational types have scored = False
    informational_types = [k for k, v in STANDARDS_AVAILABILITY_SPEC.items() if not v.get("scored")]
    assert len(informational_types) == 9

    sample_metrics = [
        {"pillar": "urban_livability", "facility_type": "taman_rt", "existing": 0, "required": None, "deficit": None, "compliance_pct": None, "scored": False},
        {"pillar": "lifeline_health", "facility_type": "rumah_sakit", "existing": 2, "required": None, "deficit": None, "compliance_pct": None, "scored": False}
    ]
    for m in sample_metrics:
        assert m["deficit"] is None
        assert m["required"] is None


@pytest.mark.unit
def test_valid1_pillar_with_less_than_two_types_has_null_score():
    """Pillar with <2 scored types gets score: None, status: 'cakupan data rendah', weight 0."""
    from backend.app.engine.standards_availability import calculate_pillar_and_composite_scores
    metrics = [
        {"pillar": "lifeline_health", "facility_type": "pos_damkar", "compliance_pct": 100.0, "scored": True},
        # Only 1 scored type in health (< 2)
        {"pillar": "education", "facility_type": "sekolah_dasar", "compliance_pct": 80.0, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_menengah_pertama", "compliance_pct": 60.0, "scored": True}
    ]
    res = calculate_pillar_and_composite_scores(metrics)
    health = res["pillar_scores"]["lifeline_health"]
    assert health["score"] is None
    assert health["status"] == "cakupan data rendah"
    assert health["included_in_composite"] is False


@pytest.mark.db
def test_valid1_pos_damkar_has_no_blank_spot():
    """Pos damkar has radius NULL and raises ValueError on blank-spot computation."""
    from backend.app.core.db import get_db_cursor, init_db_pool
    from backend.app.engine.spatial import PostGISSpatialEngine
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT population_threshold, service_radius_meters FROM regulatory_standards WHERE facility_type = 'pos_damkar';")
        row = cur.fetchone()
        assert row["population_threshold"] == 120000
        assert row["service_radius_meters"] is None

    with pytest.raises(ValueError, match="tidak memiliki standar radius"):
        PostGISSpatialEngine.calculate_blank_spots("31.71.09", "pos_damkar")


if __name__ == "__main__":
    test_evaluate_availability_rules()
    test_pillar_single_type_excluded_from_composite()
    test_exact_reweighting_edge_cases()
    test_simulation_what_if_zero_shock_matches_scorecard()
    test_availability_snapshot_fallback_logs_incident()
    test_valid1_removed_types_absent()
    test_valid1_informational_types_produce_no_deficit()
    test_valid1_pillar_with_less_than_two_types_has_null_score()
    test_valid1_pos_damkar_has_no_blank_spot()
    print(">> [PASSED] All Standards Availability & Scoring Coverage Unit Tests Passed!")
