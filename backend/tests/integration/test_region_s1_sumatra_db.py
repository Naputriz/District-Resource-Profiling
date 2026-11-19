"""
Integration tests for Task S1 (Sumatra data load on staging DB `district_profiling_stage`).
Tests northern hemisphere province Aceh (11) and southern hemisphere province Lampung (18),
plus scored Sumatra province Sumatera Barat (13) and live-config safety.
Marker: db.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routers.regions import clear_regions_cache
from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor, init_db_pool
from backend.app.main import app

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]

ALL_16_PROVINCES = "31,32,33,34,35,36,11,12,13,14,15,16,17,18,19,21"


def _require_sumatra_stage():
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM provinces WHERE kemendagri_code IN ('11', '18');")
        if cur.fetchone()["cnt"] < 2:
            pytest.skip("Sumatra provinces (11, 18) not loaded in current database")


@pytest.mark.parametrize(
    "province_code,expected_kec,allowed_srids",
    [
        ("11", 289, (32646, 32647)),
        ("18", 228, (32748,)),
    ],
)
def test_s1_aceh_and_lampung_db_counts_utm_and_scores(
    province_code: str,
    expected_kec: int,
    allowed_srids: tuple,
):
    """Aceh (11, northern 326xx) and Lampung (18, southern 327xx): counts > 0, valid UTM SRIDs, scores 0..100 or NULL-gated."""
    _require_sumatra_stage()
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS kec_cnt,
                   COUNT(*) FILTER (WHERE k.utm_srid IS NULL) AS null_utm,
                   COUNT(*) FILTER (WHERE k.utm_srid NOT IN %s) AS bad_utm,
                   COUNT(*) FILTER (WHERE k.population IS NULL OR k.population <= 0) AS bad_pop
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = %s;
            """,
            (allowed_srids, province_code),
        )
        kstat = cur.fetchone()
        assert kstat["kec_cnt"] == expected_kec
        assert kstat["null_utm"] == 0
        assert kstat["bad_utm"] == 0
        assert kstat["bad_pop"] == 0

        cur.execute(
            """
            SELECT COUNT(*) AS fac_cnt,
                   COUNT(*) FILTER (WHERE f.utm_srid IS NULL) AS null_utm,
                   COUNT(*) FILTER (WHERE f.utm_srid NOT IN %s) AS bad_utm
            FROM public_facilities f
            JOIN kecamatan k ON k.id = f.kecamatan_id
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = %s AND f.is_active = TRUE;
            """,
            (allowed_srids, province_code),
        )
        fstat = cur.fetchone()
        assert fstat["fac_cnt"] > 0
        assert fstat["null_utm"] == 0
        assert fstat["bad_utm"] == 0

        cur.execute(
            """
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
            WHERE p.kemendagri_code = %s;
            """,
            (province_code,),
        )
        scores = cur.fetchall()
        assert len(scores) == expected_kec
        for row in scores:
            cov_status = (row.get("coverage") or {}).get("osm_coverage", {}).get("status")
            assert cov_status in ("memadai", "tidak_memadai")
            if cov_status == "tidak_memadai":
                assert row["comp"] is None
                for col in ("health", "edu", "liv", "mob"):
                    assert row[col] is None
            else:
                for col in ("comp", "health", "edu", "liv", "mob"):
                    if row[col] is not None:
                        assert 0.0 <= row[col] <= 100.0


def test_s1_detail_and_blank_spots_aceh_lampung_and_sumbar(monkeypatch):
    """Detail + blank spots endpoints work for Kuta Alam (Aceh 11), Trimurjo (Lampung 18), and Padang Barat (Sumbar 13)."""
    _require_sumatra_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", ALL_16_PROVINCES)
    client = TestClient(app)

    # 1. Aceh (11) - Kuta Alam (Kota Banda Aceh, UTM 46N = 32646)
    r_aceh = client.get("/api/v1/districts/11.71.030")
    assert r_aceh.status_code == 200
    d_aceh = r_aceh.json()
    assert d_aceh["name"] == "Kuta Alam"
    assert d_aceh["province_code"] == "11"
    assert "WorldPop" in d_aceh["population_source"]
    assert d_aceh["coverage"]["osm_coverage"]["status"] == "memadai"

    r_bs_aceh = client.get(
        "/api/v1/spatial/blank-spots?district_code=11.71.030&facility_type=sekolah_dasar"
    )
    assert r_bs_aceh.status_code == 200
    bs_aceh = r_bs_aceh.json()
    assert bs_aceh["district_code"] == "11.71.030"
    assert bs_aceh["district_area_km2"] > 0
    assert 0.0 <= bs_aceh["coverage_pct"] <= 100.0
    assert bs_aceh["facilities_inside"] > 0

    # 2. Lampung (18) - Trimurjo (Lampung Tengah, UTM 48S = 32748)
    r_lamp = client.get("/api/v1/districts/18.05.050")
    assert r_lamp.status_code == 200
    d_lamp = r_lamp.json()
    assert d_lamp["name"] == "Trimurjo"
    assert d_lamp["province_code"] == "18"
    assert "WorldPop" in d_lamp["population_source"]
    assert d_lamp["coverage"]["osm_coverage"]["status"] == "memadai"

    r_bs_lamp = client.get(
        "/api/v1/spatial/blank-spots?district_code=18.05.050&facility_type=sekolah_dasar"
    )
    assert r_bs_lamp.status_code == 200
    bs_lamp = r_bs_lamp.json()
    assert bs_lamp["district_code"] == "18.05.050"
    assert bs_lamp["district_area_km2"] > 0
    assert 0.0 <= bs_lamp["coverage_pct"] <= 100.0
    assert bs_lamp["facilities_inside"] > 0

    # 3. Sumatera Barat (13) - Padang Barat (scored numeric composite)
    r_pad = client.get("/api/v1/districts/13.71.060")
    assert r_pad.status_code == 200
    d_pad = r_pad.json()
    assert d_pad["name"] == "Padang Barat"
    assert d_pad["score_status"] == "Tersedia"
    assert d_pad["composite_livability_score"] is not None
    assert 0.0 <= float(d_pad["composite_livability_score"]) <= 100.0


def test_s1_live_config_keeps_sumatra_staging(monkeypatch):
    """With live Java ACTIVE_PROVINCES=31,32,33,34,35,36, Sumatra provinces show Staging and return 404."""
    _require_sumatra_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32,33,34,35,36")
    client = TestClient(app)

    r_reg = client.get("/api/v1/regions")
    assert r_reg.status_code == 200
    by_code = {r["province_code"]: r for r in r_reg.json()}
    for pc in ("11", "12", "13", "14", "15", "16", "17", "18", "19", "21"):
        assert by_code[pc]["status"] == "Staging"
        assert by_code[pc]["has_data"] is True
    for pc in ("31", "32", "33", "34", "35", "36"):
        assert by_code[pc]["status"] == "Active"

    assert client.get("/api/v1/districts?province_code=11").status_code == 404
    assert client.get("/api/v1/districts/11.71.030").status_code == 404
    assert client.get("/api/v1/districts?province_code=18").status_code == 404
    assert client.get("/api/v1/regions/18").status_code == 404
