"""
Integration tests for J1a Java data load on staging database (`district_profiling_stage`).
Requires real database. Marker: db.
"""

import pytest
from backend.app.core.db import get_db_cursor, init_db_pool

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]


def test_java_province_34_loaded_and_valid():
    """Verifies DIY (34) counts > 0, no NULL utm_srid, and scores in 0..100."""
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM provinces WHERE kemendagri_code = '34';")
        prov = cur.fetchone()
        if not prov:
            pytest.skip("Java province 34 not loaded in current database")

        cur.execute("""
            SELECT COUNT(*) AS kec_cnt,
                   COUNT(*) FILTER (WHERE k.utm_srid IS NULL) AS null_utm,
                   COUNT(*) FILTER (WHERE k.population <= 0 OR k.population IS NULL) AS bad_pop
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = '34';
        """)
        kstat = cur.fetchone()
        assert kstat["kec_cnt"] == 78
        assert kstat["null_utm"] == 0
        assert kstat["bad_pop"] == 0

        cur.execute("""
            SELECT COUNT(*) AS fac_cnt,
                   COUNT(*) FILTER (WHERE f.utm_srid IS NULL) AS null_utm
            FROM public_facilities f
            JOIN kecamatan k ON k.id = f.kecamatan_id
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = '34' AND f.is_active = TRUE;
        """)
        fstat = cur.fetchone()
        assert fstat["fac_cnt"] > 0
        assert fstat["null_utm"] == 0

        cur.execute("""
            SELECT s.composite_livability_score::float AS comp,
                   s.health_score::float AS health,
                   s.education_score::float AS edu,
                   s.livability_score::float AS liv,
                   s.mobility_score::float AS mob,
                   s.coverage
            FROM district_compliance_scores s
            JOIN kecamatan k ON k.id = s.district_id
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = '34';
        """)
        scores = cur.fetchall()
        assert len(scores) == 78
        gated_rows = [r for r in scores if (r.get("coverage") or {}).get("osm_coverage", {}).get("status") == "tidak_memadai"]
        scored_rows = [r for r in scores if (r.get("coverage") or {}).get("osm_coverage", {}).get("status") == "memadai"]
        assert len(gated_rows) == 12
        assert len(scored_rows) == 66
        for row in gated_rows:
            assert row["comp"] is None
            for col in ("health", "edu", "liv", "mob"):
                assert row[col] is None
        for row in scored_rows:
            assert row["comp"] is not None
            assert 0.0 <= row["comp"] <= 100.0
            for col in ("health", "edu", "liv", "mob"):
                if row[col] is not None:
                    assert 0.0 <= row[col] <= 100.0


def test_dki_unchanged_after_java_load():
    """Verifies DKI Jakarta (31) keeps 44 kecamatan, 44 valid scorecards, and 16 standards."""
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) AS kec_cnt,
                   COUNT(*) FILTER (WHERE k.utm_srid != 32748 OR k.utm_srid IS NULL) AS bad_utm
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = '31';
        """)
        dki = cur.fetchone()
        assert dki["kec_cnt"] == 44
        assert dki["bad_utm"] == 0

        cur.execute("""
            SELECT s.composite_livability_score::float AS comp,
                   s.health_score::float AS health,
                   s.education_score::float AS edu,
                   s.coverage
            FROM district_compliance_scores s
            JOIN kecamatan k ON k.id = s.district_id
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = '31';
        """)
        dki_scores = cur.fetchall()
        assert len(dki_scores) == 44
        for row in dki_scores:
            assert row["comp"] is not None and 0.0 <= row["comp"] <= 100.0
            assert row["health"] is not None and 0.0 <= row["health"] <= 100.0
            assert row["edu"] is not None and 0.0 <= row["edu"] <= 100.0
            assert (row.get("coverage") or {}).get("osm_coverage", {}).get("status") == "memadai"

        cur.execute("SELECT COUNT(*) AS cnt FROM regulatory_standards;")
        assert cur.fetchone()["cnt"] == 16
