"""
Unit Tests for Multi-Region Architecture (TODO-3).
Validates:
1. Deterministic UTM zone and SRID calculation:
   - Jakarta  (106.8456, -6.2088) -> Zone 48S -> 32748
   - Surabaya (112.7508, -7.2575) -> Zone 49S -> 32749
   - Medan     (98.6722,  3.5952) -> Zone 47N -> 32647
   - Jayapura (140.7181, -2.5337) -> Zone 54S -> 32754
2. Name lookup ambiguity handling:
   - Unique match returns the district.
   - Ambiguous match (>1 records) returns None / 'ambiguous' (no guessing).
   - Province-scoped lookup resolves duplicate names.
3. GET /api/v1/regions catalog response.
4. 404 response for unsupported or no-data provinces across endpoints.
"""

import pytest
from unittest.mock import patch, MagicMock
from contextlib import contextmanager
from fastapi.testclient import TestClient

from backend.app.engine.spatial import (
    calculate_utm_zone,
    calculate_utm_srid,
    resolve_district_record,
    resolve_district_candidates,
    PostGISSpatialEngine
)
from backend.app.agent.tools import execute_tool_call
from backend.app.main import app

client = TestClient(app)
pytestmark = pytest.mark.unit


def test_utm_zone_calculation():
    """Verifies UTM zone number calculation across Indonesia longitudes."""
    # Jakarta (106.85°E) -> Zone 48
    assert calculate_utm_zone(106.8456) == 48

    # Surabaya (112.75°E) -> Zone 49
    assert calculate_utm_zone(112.7508) == 49

    # Medan (98.67°E) -> Zone 47
    assert calculate_utm_zone(98.6722) == 47

    # Jayapura (140.72°E) -> Zone 54
    assert calculate_utm_zone(140.7181) == 54

    # Boundary edge cases
    assert calculate_utm_zone(-180.0) == 1
    assert calculate_utm_zone(179.99) == 60


def test_utm_srid_calculation_four_cities():
    """
    Verifies UTM SRID calculation per standard geodetic formula for 4 cities:
    Jakarta (32748), Surabaya (32749), Medan (32647), Jayapura (32754).
    Citation: NIMA Technical Report TR8350.2 (DoD WGS84) / EPSG Geodetic Dataset.
    """
    srid_jakarta = calculate_utm_srid(106.8456, -6.2088)
    assert srid_jakarta == 32748

    srid_surabaya = calculate_utm_srid(112.7508, -7.2575)
    assert srid_surabaya == 32749

    srid_medan = calculate_utm_srid(98.6722, 3.5952)
    assert srid_medan == 32647

    srid_jayapura = calculate_utm_srid(140.7181, -2.5337)
    assert srid_jayapura == 32754


def test_resolve_district_by_canonical_code():
    """Kemendagri canonical code resolves directly without ambiguity."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {
        "id": "11111111-1111-1111-1111-111111111111",
        "kemendagri_code": "31.71.09",
        "bps_code": "3171090",
        "name": "Tebet",
        "population": 220000,
        "area_km2": 9.53,
        "density_per_km2": 23084.99,
        "utm_srid": 32748,
        "city_name": "Kota Administrasi Jakarta Selatan",
        "province_name": "Provinsi DKI Jakarta",
        "province_code": "31"
    }

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        record, err = resolve_district_record("31.71.09")
        assert err is None
        assert record is not None
        assert record["kemendagri_code"] == "31.71.09"
        assert record["name"] == "Tebet"


def test_resolve_district_name_ambiguity_two_provinces():
    """
    Simulates duplicate kecamatan name across two provinces (e.g. Cilandak in DKI vs Jawa Barat).
    Without province scoping or if scope matches multiple rows, must return None (no guessing).
    """
    dki_record = {
        "id": "11111111-1111-1111-1111-111111111111",
        "kemendagri_code": "31.71.03",
        "name": "Cilandak",
        "population": 200000,
        "area_km2": 18.2,
        "utm_srid": 32748,
        "province_code": "31",
        "province_name": "DKI Jakarta"
    }
    jabar_record = {
        "id": "22222222-2222-2222-2222-222222222222",
        "kemendagri_code": "32.01.99",
        "name": "Cilandak",
        "population": 80000,
        "area_km2": 25.0,
        "utm_srid": 32748,
        "province_code": "32",
        "province_name": "Jawa Barat"
    }

    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [dki_record, jabar_record]

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        record, err = resolve_district_record("Cilandak", province_code=None)
        assert record is None
        assert err == "ambiguous"

    mock_cur.fetchall.return_value = [dki_record]
    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        record, err = resolve_district_record("Cilandak", province_code="31")
        assert err is None
        assert record is not None
        assert record["kemendagri_code"] == "31.71.03"
        assert record["province_code"] == "31"


def test_get_regions_catalog():
    """Verifies GET /api/v1/regions catalog response."""
    res = client.get("/api/v1/regions")
    assert res.status_code == 200
    regions = res.json()
    assert isinstance(regions, list)
    assert len(regions) >= 6

    dki = next((r for r in regions if r["province_code"] == "31"), None)
    assert dki is not None
    assert dki["has_data"] is True
    assert dki["status"] == "Active"
    assert dki["utm_srid"] == 32748
    assert dki["center"] == [-6.2088, 106.8456]
    assert dki["zoom"] == 11
    assert dki["geojson_url"] == "/data/boundaries/jakarta_44_kecamatan.geojson"
    assert dki["data_sources"] is not None
    assert dki["snapshot_dates"] is not None

    jabar = next((r for r in regions if r["province_code"] == "32"), None)
    assert jabar is not None
    assert jabar["has_data"] is False
    assert "Planned" in jabar["status"]


def test_get_region_detail_active():
    """Verifies GET /api/v1/regions/31 returns DKI Jakarta configuration."""
    res = client.get("/api/v1/regions/31")
    assert res.status_code == 200
    data = res.json()
    assert data["province_code"] == "31"
    assert data["name"] == "DKI Jakarta"
    assert data["has_data"] is True


def test_get_region_detail_no_data_404():
    """Verifies GET /api/v1/regions/32 returns 404 with clear message."""
    res = client.get("/api/v1/regions/32")
    assert res.status_code == 404
    data = res.json()
    assert "Data wilayah ini belum tersedia (rencana v1.1)" in data["detail"]


def test_districts_list_no_data_province_404():
    """Verifies GET /api/v1/districts?province_code=32 returns 404."""
    res = client.get("/api/v1/districts?province_code=32")
    assert res.status_code == 404
    data = res.json()
    assert "Data wilayah ini belum tersedia (rencana v1.1)" in data["detail"]


def test_facilities_list_no_data_province_404():
    """Verifies GET /api/v1/facilities?province_code=32 returns 404."""
    res = client.get("/api/v1/facilities?province_code=32")
    assert res.status_code == 404
    data = res.json()
    assert "Data wilayah ini belum tersedia (rencana v1.1)" in data["detail"]


def test_unknown_district_endpoints_404():
    """Verifies that unknown or no-data districts return HTTP 404 across spatial and facilities endpoints."""
    with patch("backend.app.engine.spatial.resolve_district_record", return_value=(None, "not_found")), \
         patch("backend.app.api.routers.districts.resolve_district_record", return_value=(None, "not_found")):
        res_buf = client.get("/api/v1/spatial/buffers?district_code=32.73.01")
        assert res_buf.status_code == 404

        res_fac = client.get("/api/v1/facilities?district_code=32.73.01")
        assert res_fac.status_code == 404

        res_bs = client.get("/api/v1/spatial/blank-spots?district_code=32.73.01")
        assert res_bs.status_code == 404

        res_dist = client.get("/api/v1/districts/32.73.01")
        assert res_dist.status_code == 404


def test_known_district_zero_facilities_200():
    """A known district with a filter returning zero facilities still returns HTTP 200."""
    tebet_record = {
        "id": "11111111-1111-1111-1111-111111111111",
        "kemendagri_code": "31.71.09",
        "name": "Tebet",
    }
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.api.routers.districts.resolve_district_record", return_value=(tebet_record, None)), \
         patch("backend.app.api.routers.districts.get_db_cursor", side_effect=mock_cursor_ctx):
        res = client.get("/api/v1/facilities?district_code=31.71.09&pillar=non_existent_pillar")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 0
        assert data["facilities"] == []


def test_jakarta_names_unchanged():
    """Jakarta district names (e.g. 'Tebet') resolve unchanged across endpoints."""
    tebet_record = {
        "id": "11111111-1111-1111-1111-111111111111",
        "kemendagri_code": "31.71.09",
        "bps_code": "3171090",
        "name": "Tebet",
        "population": 220000,
        "area_km2": 9.53,
        "density_per_km2": 23084.99,
        "utm_srid": 32748,
        "city_name": "Jakarta Selatan",
        "province_name": "DKI Jakarta",
        "province_code": "31",
    }
    mock_facility = {
        "id": "22222222-2222-2222-2222-222222222222",
        "source": "osm",
        "source_id": "node/123",
        "name": "Puskesmas Tebet",
        "pillar": "lifeline_health",
        "category": "health",
        "facility_type": "puskesmas_kelurahan",
        "address": "Jl. Tebet",
        "capacity": None,
        "kecamatan_name": "Tebet",
        "district_code": "31.71.09",
        "longitude": 106.85,
        "latitude": -6.23,
        "metadata": {},
    }
    mock_buffer_row = {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "Puskesmas Tebet",
        "facility_type": "puskesmas_kelurahan",
        "pillar": "lifeline_health",
        "service_radius_meters": 1000,
        "buffer_geojson": {
            "type": "Polygon",
            "coordinates": [[[106.85, -6.23], [106.86, -6.23], [106.86, -6.24], [106.85, -6.23]]]
        },
        "lon": 106.85,
        "lat": -6.23,
    }

    class MockCursor:
        def __init__(self):
            self.last_query = ""
            self.last_params = ()

        def execute(self, query, params=None):
            self.last_query = str(query)
            self.last_params = params or ()

        def fetchone(self):
            q = self.last_query.lower()
            if "count(" in q or "count (*)" in q:
                return {"total": 1, "count": 1}
            if "from kecamatan" in q:
                if self.last_params and self.last_params[0] == "31.71.09":
                    return tebet_record
                return tebet_record
            return None

        def fetchall(self):
            q = self.last_query.lower()
            if "from kecamatan" in q:
                if self.last_params and (
                    str(self.last_params[0]).lower() == "tebet"
                    or str(self.last_params[1]).lower() == "tebet"
                ):
                    return [tebet_record]
                return []
            if "from public_facilities" in q and "st_asgeojson" in q:
                return [mock_buffer_row]
            if "from public_facilities" in q:
                return [mock_facility]
            return []

    mock_cur = MockCursor()

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx), \
         patch("backend.app.api.routers.districts.get_db_cursor", side_effect=mock_cursor_ctx):
        res_dist = client.get("/api/v1/districts/Tebet")
        assert res_dist.status_code == 200
        assert res_dist.json()["kemendagri_code"] == "31.71.09"
        assert res_dist.json()["name"] == "Tebet"

        res_fac = client.get("/api/v1/facilities?district_code=Tebet")
        assert res_fac.status_code == 200
        assert res_fac.json()["total"] > 0
        assert res_fac.json()["facilities"][0]["district_code"] == "31.71.09"

        res_buf = client.get("/api/v1/spatial/buffers?district_code=Tebet")
        assert res_buf.status_code == 200
        assert res_buf.json()["district_code"] == "31.71.09"
        assert res_buf.json()["total_buffers"] == 1


def test_ambiguous_name_all_public_paths():
    """Ambiguous district names return 400 error listing candidate codes across all public paths."""
    from backend.app.api.deps import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "1", "email": "test@jakarta.go.id", "role": "admin"}
    try:
        cand1 = {"id": "11111111-1111-1111-1111-111111111111", "kemendagri_code": "31.71.03", "name": "Cilandak"}
        cand2 = {"id": "22222222-2222-2222-2222-222222222222", "kemendagri_code": "31.72.99", "name": "Cilandak"}

        with patch("backend.app.engine.spatial.resolve_district_record", return_value=(None, "ambiguous")), \
             patch("backend.app.engine.spatial.resolve_district_candidates", return_value=[cand1, cand2]), \
             patch("backend.app.api.routers.districts.resolve_district_record", return_value=(None, "ambiguous")), \
             patch("backend.app.api.routers.districts.resolve_district_candidates", return_value=[cand1, cand2]), \
             patch("backend.app.api.routers.simulation.resolve_district_record", return_value=(None, "ambiguous")), \
             patch("backend.app.api.routers.simulation.resolve_district_candidates", return_value=[cand1, cand2]), \
             patch("backend.app.agent.tools.resolve_district_record", return_value=(None, "ambiguous")), \
             patch("backend.app.agent.tools.resolve_district_candidates", return_value=[cand1, cand2]):

            # 1. GET /api/v1/districts/{name}
            res1 = client.get("/api/v1/districts/Cilandak")
            assert res1.status_code == 400
            assert "ambigu" in res1.json()["detail"].lower()
            assert "31.71.03" in res1.json()["detail"]

            # 2. GET /api/v1/facilities?district_code={name}
            res2 = client.get("/api/v1/facilities?district_code=Cilandak")
            assert res2.status_code == 400
            assert "ambigu" in res2.json()["detail"].lower()
            assert "31.71.03" in res2.json()["detail"]

            # 3. GET /api/v1/spatial/buffers?district_code={name}
            res3 = client.get("/api/v1/spatial/buffers?district_code=Cilandak")
            assert res3.status_code == 400
            assert "ambigu" in res3.json()["detail"].lower()
            assert "31.71.03" in res3.json()["detail"]

            # 4. GET /api/v1/spatial/blank-spots?district_code={name}
            res4 = client.get("/api/v1/spatial/blank-spots?district_code=Cilandak")
            assert res4.status_code == 400
            assert "ambigu" in res4.json()["detail"].lower()
            assert "31.71.03" in res4.json()["detail"]

            # 5. POST /api/v1/simulation/what-if
            res5 = client.post("/api/v1/simulation/what-if", json={"district_code": "Cilandak"})
            assert res5.status_code == 400
            assert "ambigu" in res5.json()["detail"].lower()

            # 6. Tool calls
            tool_score = execute_tool_call("get_district_scorecard", {"district_code": "Cilandak"})
            assert "error" in tool_score
            assert "ambigu" in tool_score["error"].lower()
            assert "31.71.03" in tool_score["error"]

            tool_blank = execute_tool_call("get_unserved_blank_spots", {"district_code": "Cilandak"})
            assert "error" in tool_blank
            assert "ambigu" in tool_blank["error"].lower()
            assert "31.71.03" in tool_blank["error"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
