"""
Unit tests for PostGISSpatialEngine logic (README §17).
Validates:
1. SQL query construction and parameterization (buffers, boundaries).
2. Result post-processing and GeoJSON FeatureCollection generation.
3. Area and coverage arithmetic (with/without neighbours, rounding, bounds clamping).
4. `area_note` generation rule when polygon/BPS ratio > 1.5.
5. What-if blank spot reduction arithmetic and recovery percentage.
6. Error handling for non-existent districts.
Runs 100% offline without database using mocked database cursors.
"""

import pytest
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

from backend.app.engine.spatial import (
    PostGISSpatialEngine,
    BlankSpotAnalysisResult,
    BlankSpotSimulationDelta
)

pytestmark = pytest.mark.unit


def test_get_district_boundary_geojson_unit():
    """Verifies GeoJSON boundary retrieval and None handling when district is missing."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {
        "geojson": {"type": "Polygon", "coordinates": [[[106.8, -6.2], [106.9, -6.2], [106.9, -6.3], [106.8, -6.2]]]}
    }

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        res = PostGISSpatialEngine.get_district_boundary_geojson("31.71.09")
        assert res["type"] == "Polygon"
        assert len(res["coordinates"]) == 1

        # Test district not found
        mock_cur.fetchone.return_value = None
        res_none = PostGISSpatialEngine.get_district_boundary_geojson("invalid_code")
        assert res_none is None


def test_compute_facility_buffers_unit():
    """Verifies facility buffer query construction, parameter filtering, and FeatureCollection formatting."""
    mock_cur = MagicMock()
    mock_rows = [
        {
            "id": 101,
            "name": "Puskesmas Tebet Barat",
            "facility_type": "puskesmas_kelurahan",
            "pillar": "lifeline_health",
            "service_radius_meters": 1000,
            "buffer_geojson": {"type": "Polygon", "coordinates": []},
            "lon": 106.845,
            "lat": -6.235
        },
        {
            "id": 102,
            "name": "Puskesmas Tebet Timur",
            "facility_type": "puskesmas_kelurahan",
            "pillar": "lifeline_health",
            "service_radius_meters": 1000,
            "buffer_geojson": {"type": "Polygon", "coordinates": []},
            "lon": 106.852,
            "lat": -6.239
        }
    ]
    mock_cur.fetchall.return_value = mock_rows

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        # 1. Query with facility_type and pillar
        fc = PostGISSpatialEngine.compute_facility_buffers(
            district_code="31.71.09",
            facility_type="puskesmas_kelurahan",
            pillar="lifeline_health"
        )
        assert fc["type"] == "FeatureCollection"
        assert fc["district_code"] == "31.71.09"
        assert fc["total_buffers"] == 2
        assert len(fc["features"]) == 2
        assert fc["features"][0]["properties"]["facility_id"] == "101"
        assert fc["features"][0]["properties"]["coordinates"] == [106.845, -6.235]

        # Verify query had WHERE clauses for facility_type and pillar
        called_sql = mock_cur.execute.call_args[0][0]
        called_params = mock_cur.execute.call_args[0][1]
        assert "AND f.facility_type = %s" in called_sql
        assert "AND f.pillar = %s" in called_sql
        assert called_params == ("31.71.09", "31.71.09", "puskesmas_kelurahan", "lifeline_health")


def test_calculate_blank_spots_normal_area_ratio():
    """Verifies blank spot calculation when polygon/BPS ratio <= 1.5 (area_note should be None)."""
    mock_cur = MagicMock()
    # 1. District info
    mock_dist = {
        "id": 1,
        "kemendagri_code": "31.71.09",
        "name": "Tebet",
        "area_km2": 9.03,
        "pillar": "lifeline_health",
        "radius_m": 1000
    }
    # 2. Spatial query result: geom area 9.37 km2, served 9.28 km2, unserved 0.09 km2
    mock_spatial = {
        "geom_area_km2": 9.37,
        "inside_cnt": 7,
        "neighbour_cnt": 19,
        "served_no_neigh": 8.65,
        "served_all": 9.2843,
        "unserved_all": 0.0857,
        "blank_geojson": {"type": "MultiPolygon", "coordinates": []}
    }
    mock_cur.fetchone.side_effect = [mock_dist, mock_spatial]

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        res = PostGISSpatialEngine.calculate_blank_spots("31.71.09", "puskesmas_kelurahan")
        assert res.district_code == "31.71.09"
        assert res.district_name == "Tebet"
        assert res.district_area_km2 == 9.37
        assert res.bps_area_km2 == 9.03
        assert res.area_ratio == 1.04  # 9.37 / 9.03 = 1.037... -> 1.04
        assert res.area_note is None   # <= 1.5
        assert res.facilities_inside == 7
        assert res.facilities_from_neighbours == 19
        assert res.coverage_pct == 99.09  # 9.2843 / 9.37 * 100 = 99.085... -> 99.09
        assert res.coverage_pct_without_neighbours == 92.32  # 8.65 / 9.37 * 100 = 92.315... -> 92.32
        assert res.unserved_area_km2 == 0.0857


def test_calculate_blank_spots_high_ratio_area_note():
    """
    Verifies area_note rule for anomalous geometry/BPS ratios (> 1.5x),
    (mocked values: geom 42.48 km2 vs BPS 1.13 km2).
    """
    mock_cur = MagicMock()
    mock_dist = {
        "id": 2,
        "kemendagri_code": "31.01.01",
        "name": "Kepulauan Seribu Selatan",
        "area_km2": 1.13,
        "pillar": "lifeline_health",
        "radius_m": 1000
    }
    mock_spatial = {
        "geom_area_km2": 42.48,
        "inside_cnt": 3,
        "neighbour_cnt": 0,
        "served_no_neigh": 5.21,
        "served_all": 5.21,
        "unserved_all": 37.27,
        "blank_geojson": {"type": "MultiPolygon", "coordinates": []}
    }
    mock_cur.fetchone.side_effect = [mock_dist, mock_spatial]

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        res = PostGISSpatialEngine.calculate_blank_spots("31.01.01", "puskesmas_kelurahan")
        assert res.area_ratio == 37.59  # 42.48 / 1.13 = 37.5929...
        assert res.area_note is not None
        assert "berbeda jauh" in res.area_note
        assert "42.48 km²" in res.area_note
        assert "1.13 km²" in res.area_note
        assert "37.59x" in res.area_note


def test_calculate_blank_spots_clamping_and_bounds():
    """Verifies that served area > district area is clamped to district area and coverage <= 100%."""
    mock_cur = MagicMock()
    mock_dist = {
        "id": 3,
        "kemendagri_code": "31.73.08",
        "name": "Gambir",
        "area_km2": 7.60,
        "pillar": "lifeline_health",
        "radius_m": 1000
    }
    # Raw served exceeds raw geom area due to slight floating point or multi-part intersection
    mock_spatial = {
        "geom_area_km2": 7.59,
        "inside_cnt": 5,
        "neighbour_cnt": 10,
        "served_no_neigh": 7.60,  # Exceeds 7.59
        "served_all": 7.75,       # Exceeds 7.59
        "unserved_all": -0.05,    # Negative area
        "blank_geojson": {"type": "MultiPolygon", "coordinates": []}
    }
    mock_cur.fetchone.side_effect = [mock_dist, mock_spatial]

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        res = PostGISSpatialEngine.calculate_blank_spots("31.73.08", "puskesmas_kelurahan")
        assert res.served_area_km2 == 7.59  # Clamped to geom_area_km2
        assert res.coverage_pct == 100.0    # Clamped to 100.0%
        assert res.coverage_pct_without_neighbours == 100.0


def test_calculate_blank_spots_district_not_found():
    """Verifies ValueError when district is not found."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        with pytest.raises(ValueError, match="District '99.99.99' not found"):
            PostGISSpatialEngine.calculate_blank_spots("99.99.99", "puskesmas_kelurahan")


def test_simulate_blank_spot_reduction_unit():
    """Verifies simulation delta calculation for hypothetical amenity addition."""
    mock_cur = MagicMock()

    # Step 1: calculate_blank_spots baseline mock
    mock_dist = {
        "id": 1,
        "kemendagri_code": "31.71.09",
        "name": "Tebet",
        "area_km2": 9.03,
        "pillar": "lifeline_health",
        "radius_m": 1000
    }
    mock_spatial = {
        "geom_area_km2": 9.37,
        "inside_cnt": 7,
        "neighbour_cnt": 19,
        "served_no_neigh": 8.65,
        "served_all": 9.28,
        "unserved_all": 0.09,
        "blank_geojson": {"type": "MultiPolygon", "coordinates": []}
    }

    # Step 2: simulate query mock: unserved reduced from 0.09 to 0.02
    mock_kec_id = {"id": 1}
    mock_sim_result = {
        "sim_unserved_km2": 0.02,
        "sim_blank_geojson": {"type": "MultiPolygon", "coordinates": []}
    }

    mock_cur.fetchone.side_effect = [mock_dist, mock_spatial, mock_kec_id, mock_sim_result]

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        delta = PostGISSpatialEngine.simulate_blank_spot_reduction(
            district_code="31.71.09",
            facility_type="puskesmas_kelurahan",
            hypothetical_coords=[106.85, -6.23],
            custom_radius_meters=1000
        )
        assert delta.district_code == "31.71.09"
        assert delta.facility_type == "puskesmas_kelurahan"
        assert delta.baseline_unserved_km2 == 0.09
        assert delta.simulated_unserved_km2 == 0.02
        assert delta.area_recovered_km2 == 0.07  # 0.09 - 0.02
        assert delta.coverage_improvement_pct == 0.75  # 0.07 / 9.37 * 100 = 0.747... -> 0.75%
        assert delta.cross_border_scope == "DKI Jakarta only"
