import pytest
from backend.app.core.config import settings
from backend.app.core.db import init_db_pool, close_db_pool, get_db_cursor, get_redis_client
from backend.app.engine.simulation import WhatIfSimulationEngine, HypotheticalAmenity

pytestmark = pytest.mark.db

def test_standalone_integration():
    init_db_pool()

    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM kecamatan;")
        res = cur.fetchone()
        assert res["count"] == 44

        cur.execute("SELECT COUNT(*) as count FROM public_facilities;")
        res = cur.fetchone()
        assert res["count"] >= 50

        cur.execute("SELECT COUNT(*) as count FROM district_compliance_scores;")
        res = cur.fetchone()
        assert res["count"] == 44

    r_client = get_redis_client()
    if r_client:
        pong = r_client.ping()
        assert pong is True

    with get_db_cursor() as cur:
        cur.execute("SELECT kemendagri_code, name, population FROM kecamatan WHERE kemendagri_code = '31.71.09';")
        tebet = cur.fetchone()

        cur.execute("SELECT facility_type, COUNT(*) as cnt FROM public_facilities WHERE kecamatan_id = (SELECT id FROM kecamatan WHERE kemendagri_code = '31.71.09') GROUP BY facility_type;")
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
        staged_amenities=[
            HypotheticalAmenity(
                name="Puskesmas Hipotetis Tebet",
                pillar="lifeline_health",
                facility_type="puskesmas_kelurahan",
                coordinates=[106.845, -6.230]
            )
        ]
    )

    assert sim_res.baseline_population == tebet["population"]
