"""
Integration tests for database pool, direct queries, and What-If Simulation Engine.
"""

import pytest
from backend.app.core.db import init_db_pool, close_db_pool, get_db_cursor, get_redis_client
from backend.app.engine.simulation import WhatIfSimulationEngine, HypotheticalAmenity

pytestmark = pytest.mark.db

def test_direct_db_queries_and_simulation():
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM kecamatan;")
        kec_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM public_facilities;")
        fac_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM district_compliance_scores;")
        score_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM regulatory_standards;")
        reg_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM regulatory_chunks;")
        chunk_count = cur.fetchone()["count"]

        assert kec_count == 44, "Expected 44 districts"
        assert fac_count >= 50, "Expected at least 50 facilities"
        assert score_count == 44, "Expected 44 scorecards"
        assert reg_count >= 16, "Expected at least 16 regulatory standards"

        cur.execute("""
            SELECT k.kemendagri_code, k.name, k.population, s.composite_livability_score,
                   s.health_score, s.education_score, s.livability_score, s.mobility_score
            FROM kecamatan k
            JOIN district_compliance_scores s ON s.district_id = k.id
            WHERE k.kemendagri_code = '31.71.09';
        """)
        tebet = cur.fetchone()
        assert tebet is not None

        staged = [
            HypotheticalAmenity(
                name="Puskesmas Hipotetis Baru",
                pillar="lifeline_health",
                facility_type="puskesmas_kelurahan",
                coordinates=[106.845, -6.230],
                capacity=50
            )
        ]

        cur.execute("""
            SELECT facility_type, COUNT(*) as cnt
            FROM public_facilities
            WHERE kecamatan_id = (SELECT id FROM kecamatan WHERE kemendagri_code = '31.71.09')
            GROUP BY facility_type;
        """)
        counts = {r["facility_type"]: r["cnt"] for r in cur.fetchall()}

        cur.execute("SELECT facility_type, pillar, population_threshold FROM regulatory_standards;")
        stds = cur.fetchall()

        sim_res = WhatIfSimulationEngine.compute_scenario_delta(
            district_code=tebet["kemendagri_code"],
            district_name=tebet["name"],
            baseline_population=tebet["population"],
            existing_facility_counts=counts,
            regulatory_standards=stds,
            pop_shock_pct=15.0,
            staged_amenities=staged
        )

        assert sim_res.baseline_population == tebet["population"]
        assert sim_res.is_sandbox_isolated is True

    r_client = get_redis_client()
    if r_client:
        pong = r_client.ping()
        assert pong is True
