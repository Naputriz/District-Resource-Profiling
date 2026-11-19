"""
Integration Tests for Multi-Region Architecture with PostgreSQL / PostGIS.
Requires real database. Marker: db.
"""

import pytest
from contextlib import contextmanager
from unittest.mock import patch
from fastapi.testclient import TestClient
from psycopg2.extras import RealDictCursor

from backend.app.engine.spatial import PostGISSpatialEngine
from backend.app.main import app

client = TestClient(app)
pytestmark = pytest.mark.db


def test_db_regions_and_districts_integration(requires_seed):
    """Verifies that DB has province 31 and districts list works unchanged."""
    res = client.get("/api/v1/districts")
    assert res.status_code == 200
    data = res.json()
    assert len(data.get("districts", [])) == 44

    # Default province param 31 gives identical result
    res_31 = client.get("/api/v1/districts?province_code=31")
    assert res_31.status_code == 200
    assert len(res_31.json().get("districts", [])) == 44


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


def test_db_zone49_facility_does_not_crash_zone48_blank_spot(requires_seed):
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
            result = PostGISSpatialEngine.calculate_blank_spots("31.71.09", "puskesmas_kelurahan")
            assert result.district_code == "31.71.09"
            assert result.unserved_area_km2 >= 0.0
    finally:
        conn.rollback()
        conn.close()
