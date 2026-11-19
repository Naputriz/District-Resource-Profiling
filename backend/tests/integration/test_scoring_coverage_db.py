"""
Integration tests for Standards Availability, Coverage, and Proportional Re-weighting.
Requires PostGIS database. Marker: db.
"""

import pytest
from backend.app.core.db import get_db_cursor, init_db_pool
from backend.app.engine.simulation import WhatIfSimulationEngine
from backend.app.engine.spatial import PostGISSpatialEngine
from backend.app.engine.standards_availability import (
    get_city_wide_standards_availability,
    get_current_availability_source,
    calculate_pillar_and_composite_scores
)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]


def test_simulation_what_if_zero_shock_matches_scorecard_phase_5_1():
    """
    Composite coverage rule:
    For Gambir, Setiabudi, Tebet, Kebon Jeruk, Kepulauan Seribu Selatan,
    a what-if simulation with population_shock_count = 0 returns
    baseline_composite_score equal to the scorecard composite (exact, 2 decimals),
    and active pillar scores match.
    """
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

            assert base_pillars["lifeline_health"]["included_in_composite"] is True
            assert base_pillars["education"]["included_in_composite"] is True
            assert base_pillars["urban_livability"]["included_in_composite"] is False
            assert base_pillars["mobility_connectivity"]["included_in_composite"] is False


def test_availability_snapshot_fallback_logs_incident():
    """
    Phase 7.1 Item 2:
    When database raises an exception during get_city_wide_standards_availability(force_refresh=True),
    it logs a WARNING, inserts an incident_logs row (type: availability_snapshot_fallback),
    and sets availability_source to 'snapshot'.
    """
    from contextlib import contextmanager
    from unittest.mock import patch
    from backend.app.core.db import get_db_cursor as real_get_db_cursor

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

        res = calculate_pillar_and_composite_scores([
            {"pillar": "lifeline_health", "facility_type": "rumah_sakit", "compliance_pct": 80.0},
            {"pillar": "lifeline_health", "facility_type": "pos_damkar", "compliance_pct": 70.0}
        ])
        assert res["availability_source"] == "snapshot"

    try:
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
            incident_id = row["id"]
    finally:
        with real_get_db_cursor() as cur:
            cur.execute("DELETE FROM incident_logs WHERE incident_type = 'availability_snapshot_fallback';")

    get_city_wide_standards_availability(force_refresh=True)
    assert get_current_availability_source() == "database"


def test_valid1_pos_damkar_has_no_blank_spot():
    """Step E.1: Pos damkar has radius NULL and raises ValueError on blank-spot computation."""
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT population_threshold, service_radius_meters FROM regulatory_standards WHERE facility_type = 'pos_damkar';")
        row = cur.fetchone()
        assert row["population_threshold"] == 120000
        assert row["service_radius_meters"] is None

    with pytest.raises(ValueError, match="tidak memiliki standar radius"):
        PostGISSpatialEngine.calculate_blank_spots("31.71.09", "pos_damkar")
