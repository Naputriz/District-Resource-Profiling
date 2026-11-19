"""
Unit and Integration Tests for Multi-Region Architecture (TODO-3).
Validates:
1. Deterministic UTM zone and SRID calculation:
   - Jakarta  (106.8456, -6.2088) -> Zone 48S -> 32748
   - Surabaya (112.7508, -7.2575) -> Zone 49S -> 32749
   - Medan     (98.6722,  3.5952) -> Zone 47N -> 32647
   - Jayapura (140.7181, -2.5337) -> Zone 54S -> 32754
   Standard Formula: Zone = floor((lon + 180)/6) + 1; EPSG = 32700 + Zone (South) / 32600 + Zone (North).
   Citation: NIMA Technical Report TR8350.2 / EPSG Geodetic Parameter Dataset.
2. Name lookup ambiguity handling:
   - Unique match returns the district.
   - Ambiguous match (>1 records) returns None / 'ambiguous' (no guessing).
   - Province-scoped lookup resolves duplicate names.
3. GET /api/v1/regions catalog response:
   - Province 31 (DKI Jakarta) has has_data=True, status="Active", center, zoom, bbox, geojson_url.
   - Planned provinces (Jawa Barat, Jawa Tengah, etc.) have has_data=False, status="Planned (v1.1)".
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
from psycopg2.extras import RealDictCursor
from backend.app.main import app

client = TestClient(app)


# =============================================================================
# 1. UTM Zone & SRID Calculation Unit Tests
# =============================================================================
@pytest.mark.unit
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


@pytest.mark.unit
def test_utm_srid_calculation_four_cities():
    """
    Verifies UTM SRID calculation per standard geodetic formula for 4 cities:
    Jakarta (32748), Surabaya (32749), Medan (32647), Jayapura (32754).
    Citation: NIMA Technical Report TR8350.2 (DoD WGS84) / EPSG Geodetic Dataset.
    """
    # 1. Jakarta: lon ~106.8456, lat ~ -6.2088 (Southern Hemisphere) -> EPSG:32748
    srid_jakarta = calculate_utm_srid(106.8456, -6.2088)
    assert srid_jakarta == 32748

    # 2. Surabaya: lon ~112.7508, lat ~ -7.2575 (Southern Hemisphere) -> EPSG:32749
    srid_surabaya = calculate_utm_srid(112.7508, -7.2575)
    assert srid_surabaya == 32749

    # 3. Medan: lon ~98.6722, lat ~ +3.5952 (Northern Hemisphere) -> EPSG:32647
    srid_medan = calculate_utm_srid(98.6722, 3.5952)
    assert srid_medan == 32647

    # 4. Jayapura: lon ~140.7181, lat ~ -2.5337 (Southern Hemisphere) -> EPSG:32754
    srid_jayapura = calculate_utm_srid(140.7181, -2.5337)
    assert srid_jayapura == 32754


# =============================================================================
# 2. District Name Resolution & Ambiguity Unit Tests
# =============================================================================
@pytest.mark.unit
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


@pytest.mark.unit
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

    # 1. Ambiguous match: returns multiple rows -> rejected
    mock_cur.fetchall.return_value = [dki_record, jabar_record]

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        record, err = resolve_district_record("Cilandak", province_code=None)
        assert record is None
        assert err == "ambiguous"

    # 2. Scoped to DKI Jakarta (31): returns single row -> accepted
    mock_cur.fetchall.return_value = [dki_record]
    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_cursor_ctx):
        record, err = resolve_district_record("Cilandak", province_code="31")
        assert err is None
        assert record is not None
        assert record["kemendagri_code"] == "31.71.03"
        assert record["province_code"] == "31"


# =============================================================================
# 3. Regions Catalog API Tests
# =============================================================================
@pytest.mark.unit
def test_get_regions_catalog():
    """Verifies GET /api/v1/regions catalog response."""
    res = client.get("/api/v1/regions")
    assert res.status_code == 200
    regions = res.json()
    assert isinstance(regions, list)
    assert len(regions) >= 6

    # Verify DKI Jakarta active config
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

    # Verify planned regions have has_data=False
    jabar = next((r for r in regions if r["province_code"] == "32"), None)
    assert jabar is not None
    assert jabar["has_data"] is False
    assert "Planned" in jabar["status"]


@pytest.mark.unit
def test_get_region_detail_active():
    """Verifies GET /api/v1/regions/31 returns DKI Jakarta configuration."""
    res = client.get("/api/v1/regions/31")
    assert res.status_code == 200
    data = res.json()
    assert data["province_code"] == "31"
    assert data["name"] == "DKI Jakarta"
    assert data["has_data"] is True


@pytest.mark.unit
def test_get_region_detail_no_data_404():
    """Verifies GET /api/v1/regions/32 returns 404 with clear message."""
    res = client.get("/api/v1/regions/32")
    assert res.status_code == 404
    data = res.json()
    assert "Data wilayah ini belum tersedia (rencana v1.1)" in data["detail"]


@pytest.mark.unit
def test_districts_list_no_data_province_404():
    """Verifies GET /api/v1/districts?province_code=32 returns 404."""
    res = client.get("/api/v1/districts?province_code=32")
    assert res.status_code == 404
    data = res.json()
    assert "Data wilayah ini belum tersedia (rencana v1.1)" in data["detail"]


@pytest.mark.unit
def test_facilities_list_no_data_province_404():
    """Verifies GET /api/v1/facilities?province_code=32 returns 404."""
    res = client.get("/api/v1/facilities?province_code=32")
    assert res.status_code == 404
    data = res.json()
    assert "Data wilayah ini belum tersedia (rencana v1.1)" in data["detail"]


# =============================================================================
# 4. Integration Test with Database (Marked DB)
# =============================================================================
@pytest.mark.db
def test_db_regions_and_districts_integration():
    """Verifies that DB has province 31 and districts list works unchanged."""
    res = client.get("/api/v1/districts")
    assert res.status_code == 200
    data = res.json()
    assert len(data.get("districts", [])) == 44

    # Default province param 31 gives identical result
    res_31 = client.get("/api/v1/districts?province_code=31")
    assert res_31.status_code == 200
    assert len(res_31.json().get("districts", [])) == 44


@pytest.mark.db
def test_unknown_district_endpoints_404():
    """Verifies that unknown or no-data districts return HTTP 404 across spatial and facilities endpoints."""
    res_buf = client.get("/api/v1/spatial/buffers?district_code=32.73.01")
    assert res_buf.status_code == 404

    res_fac = client.get("/api/v1/facilities?district_code=32.73.01")
    assert res_fac.status_code == 404

    res_bs = client.get("/api/v1/spatial/blank-spots?district_code=32.73.01")
    assert res_bs.status_code == 404

    res_dist = client.get("/api/v1/districts/32.73.01")
    assert res_dist.status_code == 404


@pytest.mark.db
def test_known_district_zero_facilities_200():
    """A known district with a filter returning zero facilities still returns HTTP 200."""
    res = client.get("/api/v1/facilities?district_code=31.71.09&pillar=non_existent_pillar")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["facilities"] == []


@pytest.mark.db
def test_jakarta_names_unchanged():
    """Jakarta district names (e.g. 'Tebet') resolve unchanged across endpoints."""
    res_dist = client.get("/api/v1/districts/Tebet")
    assert res_dist.status_code == 200
    assert res_dist.json()["kemendagri_code"] == "31.71.09"

    res_fac = client.get("/api/v1/facilities?district_code=Tebet")
    assert res_fac.status_code == 200
    assert res_fac.json()["total"] > 0

    res_buf = client.get("/api/v1/spatial/buffers?district_code=Tebet")
    assert res_buf.status_code == 200
    assert res_buf.json()["district_code"] == "31.71.09"


@pytest.mark.unit
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


@pytest.mark.db
def test_db_insert_without_utm_srid_computes_zone():
    """INSERT without utm_srid triggers compute_utm_srid to assign dynamic UTM SRID."""
    import psycopg2
    from backend.app.core.config import settings

    conn = psycopg2.connect(
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT
    )
    try:
        with conn.cursor() as cur:
            # Surabaya coordinate: lon=112.7508, lat=-7.2575 -> UTM Zone 49S (32749)
            cur.execute("""
                INSERT INTO public_facilities (
                    source, source_id, name, pillar, category, facility_type,
                    coordinates, is_active
                ) VALUES (
                    'test', 'test/surabaya_trigger_test', 'RS Surabaya Test', 'lifeline_health', 'health', 'puskesmas_kelurahan',
                    ST_SetSRID(ST_MakePoint(112.7508, -7.2575), 4326), TRUE
                ) RETURNING utm_srid, ST_SRID(coordinates_utm);
            """)
            row = cur.fetchone()
            assert row[0] == 32749
            assert row[1] == 32749
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.db
def test_db_zone49_facility_does_not_crash_zone48_blank_spot():
    """A facility in UTM Zone 49S does not crash blank-spot calculation for a Zone 48S district."""
    import psycopg2
    from backend.app.core.config import settings

    conn = psycopg2.connect(
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT
    )
    try:
        @contextmanager
        def tx_cursor():
            cur = conn.cursor(cursor_factory=RealDictCursor)
            try:
                yield cur
            finally:
                cur.close()

        with tx_cursor() as cur:
            # Point in Zone 49S at overlapping planar bounding box coordinates
            cur.execute("""
                INSERT INTO public_facilities (
                    source, source_id, name, pillar, category, facility_type,
                    coordinates, is_active
                ) VALUES (
                    'test', 'test/zone49_overlap_unit', 'Puskesmas Zone 49 Overlap', 'lifeline_health', 'health', 'puskesmas_kelurahan',
                    ST_SetSRID(ST_MakePoint(112.85, -6.225), 4326), TRUE
                );
            """)

        with patch("backend.app.engine.spatial.get_db_cursor", side_effect=tx_cursor):
            # Must compute successfully for Tebet (Zone 48S) without mixed SRID error
            result = PostGISSpatialEngine.calculate_blank_spots("31.71.09", "puskesmas_kelurahan")
            assert result.district_code == "31.71.09"
            assert result.unserved_area_km2 >= 0.0
    finally:
        conn.rollback()
        conn.close()
