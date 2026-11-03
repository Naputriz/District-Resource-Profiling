"""
Unit & Integration Tests for Cross-Border Blank Spots.
Verifies that facilities across district borders are included when their service buffer
intersects the target district (ST_DWithin), while facilities beyond radius are excluded.
"""

import pytest
from backend.app.core.db import get_db_cursor, init_db_pool, close_db_pool
from backend.app.engine.spatial import PostGISSpatialEngine, BlankSpotAnalysisResult

pytestmark = pytest.mark.db


def test_synthetic_adjacent_squares_cross_border():
    """
    Test cross-border blank spot calculation:
    Synthetic geometry: Two adjacent squares.
    Square 1 (Target District): [0, 1000] x [0, 1000] (area 1 km2).
    Square 2 (Neighbour District): [1000, 2000] x [0, 1000].
    Radius: 500m.
    - Facility A at (1200, 500) is 200m across the border (distance 200 <= 500) -> COUNTED & COVERS part of Square 1.
    - Facility B at (1800, 500) is 800m across the border (distance 800 > 500) -> EXCLUDED (does not reach Square 1).
    """
    init_db_pool()
    with get_db_cursor() as cur:
        # 1. Test Facility A (within radius: 200m from border)
        cur.execute("""
            WITH target_district AS (
                SELECT ST_SetSRID(ST_GeomFromText('POLYGON((0 0, 1000 0, 1000 1000, 0 1000, 0 0))'), 32748) as geom
            ),
            facility_a AS (
                SELECT ST_SetSRID(ST_MakePoint(1200, 500), 32748) as geom
            ),
            eval_a AS (
                SELECT 
                    ST_DWithin(fa.geom, td.geom, 500) as in_radius,
                    ST_Distance(fa.geom, td.geom) as dist_meters,
                    ST_Area(td.geom) as target_area,
                    ST_Area(ST_Difference(td.geom, ST_Buffer(fa.geom, 500))) as unserved_area
                FROM target_district td, facility_a fa
            )
            SELECT * FROM eval_a;
        """)
        row_a = cur.fetchone()
        assert row_a["in_radius"] is True
        assert row_a["dist_meters"] == 200.0
        assert row_a["unserved_area"] < row_a["target_area"]  # Overlaps Square 1, reducing unserved area

        # 2. Test Facility B (beyond radius: 800m from border)
        cur.execute("""
            WITH target_district AS (
                SELECT ST_SetSRID(ST_GeomFromText('POLYGON((0 0, 1000 0, 1000 1000, 0 1000, 0 0))'), 32748) as geom
            ),
            facility_b AS (
                SELECT ST_SetSRID(ST_MakePoint(1800, 500), 32748) as geom
            ),
            eval_b AS (
                SELECT 
                    ST_DWithin(fb.geom, td.geom, 500) as in_radius,
                    ST_Distance(fb.geom, td.geom) as dist_meters,
                    ST_Area(td.geom) as target_area,
                    ST_Area(ST_Difference(td.geom, ST_Buffer(fb.geom, 500))) as unserved_area
                FROM target_district td, facility_b fb
            )
            SELECT * FROM eval_b;
        """)
        row_b = cur.fetchone()
        assert row_b["in_radius"] is False
        assert row_b["dist_meters"] == 800.0
        assert row_b["unserved_area"] == row_b["target_area"]  # Zero overlap, unserved area unaffected


def test_tebet_puskesmas_cross_border_blank_spot():
    """
    Verifies that Tebet's puskesmas blank-spot includes neighbour facilities from
    Setiabudi, Pancoran, Jatinegara, etc., raising coverage from 92.08% to 99.05%.
    """
    init_db_pool()
    res = PostGISSpatialEngine.calculate_blank_spots("31.71.09", "puskesmas_kelurahan")

    assert res.district_code == "31.71.09"
    assert res.district_name == "Tebet"
    assert res.facility_type == "puskesmas_kelurahan"
    assert res.service_radius_meters == 1500
    assert res.cross_border_scope == "DKI Jakarta only"
    assert res.facilities_inside == 7
    assert res.facilities_from_neighbours == 23
    assert res.coverage_pct_without_neighbours >= 92.0
    assert res.coverage_pct >= 99.0
    assert res.coverage_pct >= res.coverage_pct_without_neighbours
    assert res.unserved_area_km2 <= 0.10
    assert bool(res.blank_spot_geojson) is True


def test_isolated_district_kepulauan_seribu_selatan():
    """
    For an island district without land borders within 1000m,
    facilities_from_neighbours is 0 and coverage_pct equals coverage_pct_without_neighbours.
    """
    init_db_pool()
    res = PostGISSpatialEngine.calculate_blank_spots("31.01.01", "puskesmas_kelurahan")

    assert res.district_code == "31.01.01"
    assert res.facilities_from_neighbours == 0
    assert res.coverage_pct == res.coverage_pct_without_neighbours
    assert res.cross_border_scope == "DKI Jakarta only"


def test_kepulauan_seribu_selatan_sekolah_dasar_anomaly_regression():
    """
    Regression Test:
    Verifies that Kepulauan Seribu Selatan sekolah_dasar (1 facility inside)
    does NOT report artificial 0.00% coverage caused by clamping against BPS land area.
    With true geometric area (42.48 km2), coverage is ~3.25%, served area is ~1.38 km2.
    """
    init_db_pool()
    res = PostGISSpatialEngine.calculate_blank_spots("31.01.01", "sekolah_dasar")

    assert res.district_code == "31.01.01"
    assert res.district_name == "Kepulauan Seribu Selatan"
    assert res.facility_type == "sekolah_dasar"
    assert res.facilities_inside == 1
    assert res.facilities_from_neighbours == 0
    assert res.district_area_km2 == 42.48
    assert res.served_area_km2 >= 1.30
    assert res.coverage_pct > 0.0
    assert 3.20 <= res.coverage_pct <= 3.30
    assert res.coverage_pct == res.coverage_pct_without_neighbours
    assert res.cross_border_scope == "DKI Jakarta only"
    assert bool(res.blank_spot_geojson) is True


def test_simulate_blank_spot_reduction_with_neighbours():
    """
    Simulates placing a hypothetical puskesmas in Tebet's remaining unserved pocket.
    """
    init_db_pool()
    delta = PostGISSpatialEngine.simulate_blank_spot_reduction(
        district_code="31.71.09",
        facility_type="puskesmas_kelurahan",
        hypothetical_coords=[106.845, -6.230]
    )
    assert delta.baseline_unserved_km2 <= 0.10
    assert delta.simulated_unserved_km2 <= delta.baseline_unserved_km2
    assert delta.area_recovered_km2 >= 0.0
    assert delta.cross_border_scope == "DKI Jakarta only"


if __name__ == "__main__":
    init_db_pool()
    try:
        test_synthetic_adjacent_squares_cross_border()
        test_tebet_puskesmas_cross_border_blank_spot()
        test_isolated_district_kepulauan_seribu_selatan()
        test_kepulauan_seribu_selatan_sekolah_dasar_anomaly_regression()
        test_simulate_blank_spot_reduction_with_neighbours()
        print(">> [PASSED] All Cross-Border Blank Spot Tests Passed Successfully!")
    finally:
        close_db_pool()
