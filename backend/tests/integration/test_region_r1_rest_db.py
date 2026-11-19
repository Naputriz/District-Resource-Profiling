"""
Integration tests for Task R1 (Kalimantan, Bali-Nusa Tenggara, Maluku on staging DB `district_profiling_stage`).
Tests Kalimantan Barat (61, both hemispheres 32649/32749), Bali (51, 32750), and
Maluku Utara (82, 32652/32751/32752), detail + blank spots endpoints, and live-config safety.
Marker: db.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routers.regions import clear_regions_cache
from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor, init_db_pool
from backend.app.main import app

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]

ALL_38_PROVINCES = (
    "31,32,33,34,35,36,11,12,13,14,15,16,17,18,19,21,"
    "71,72,73,74,75,76,91,92,93,94,95,96,61,62,63,64,65,51,52,53,81,82"
)
LIVE_28_PROVINCES = (
    "31,32,33,34,35,36,11,12,13,14,15,16,17,18,19,21,"
    "71,72,73,74,75,76,91,92,93,94,95,96"
)
REST_10_PROVINCES = ("51", "52", "53", "61", "62", "63", "64", "65", "81", "82")


def _require_rest_stage():
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM provinces WHERE kemendagri_code IN ('51', '61', '82');")
        if cur.fetchone()["cnt"] < 3:
            pytest.skip("R1 provinces (51, 61, 82) not loaded in current database")


@pytest.mark.parametrize(
    "province_code,expected_kec,allowed_srids",
    [
        ("61", 174, (32649, 32749)),
        ("51", 57, (32750,)),
        ("82", 116, (32652, 32751, 32752)),
    ],
)
def test_r1_kalbar_bali_malut_db_counts_utm_and_scores(
    province_code: str,
    expected_kec: int,
    allowed_srids: tuple,
):
    """Kalbar (61, north+south), Bali (51), and Malut (82): counts > 0, valid UTM SRIDs, scores 0..100 or NULL-gated."""
    _require_rest_stage()
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS kec_cnt,
                   COUNT(*) FILTER (WHERE k.utm_srid IS NULL) AS null_utm,
                   COUNT(*) FILTER (WHERE k.utm_srid NOT IN %s) AS bad_utm,
                   COUNT(*) FILTER (WHERE k.utm_srid >= 32600 AND k.utm_srid < 32700) AS north_cnt,
                   COUNT(*) FILTER (WHERE k.utm_srid >= 32700) AS south_cnt,
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
        if province_code in ("61", "82"):
            assert kstat["north_cnt"] > 0
            assert kstat["south_cnt"] > 0

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


def test_r1_detail_and_blank_spots_kalbar_bali_malut(monkeypatch):
    """Detail + blank spots endpoints work for Pontianak Kota (61), Putussibau Selatan (61N), Denpasar Selatan (51), and Morotai Selatan (82)."""
    _require_rest_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", ALL_38_PROVINCES)
    client = TestClient(app)

    # 1. Bali (51) - Denpasar Selatan (51.71.010, UTM 50S = 32750, scored numeric composite)
    r_bali = client.get("/api/v1/districts/51.71.010")
    assert r_bali.status_code == 200
    d_bali = r_bali.json()
    assert d_bali["name"] == "Denpasar Selatan"
    assert d_bali["province_code"] == "51"
    assert "WorldPop" in d_bali["population_source"]
    assert d_bali["coverage"]["osm_coverage"]["status"] == "memadai"
    assert d_bali["score_status"] == "Tersedia"
    assert d_bali["composite_livability_score"] is not None
    assert 0.0 <= float(d_bali["composite_livability_score"]) <= 100.0

    r_bs_bali = client.get("/api/v1/spatial/blank-spots?district_code=51.71.010&facility_type=sekolah_dasar")
    assert r_bs_bali.status_code == 200
    bs_bali = r_bs_bali.json()
    assert bs_bali["district_code"] == "51.71.010"
    assert bs_bali["district_area_km2"] > 0
    assert 0.0 <= bs_bali["coverage_pct"] <= 100.0
    assert bs_bali["facilities_inside"] > 0

    # 2. Kalimantan Barat (61) - Pontianak Kota (south 32749) & Putussibau Selatan (north 32649)
    for code, expected_name in (("61.71.031", "Pontianak Kota"), ("61.08.080", "Putussibau Selatan")):
        r_kb = client.get(f"/api/v1/districts/{code}")
        assert r_kb.status_code == 200
        d_kb = r_kb.json()
        assert d_kb["name"] == expected_name
        assert d_kb["province_code"] == "61"
        assert d_kb["coverage"]["osm_coverage"]["status"] == "memadai"

        r_bs_kb = client.get(f"/api/v1/spatial/blank-spots?district_code={code}&facility_type=sekolah_dasar")
        assert r_bs_kb.status_code == 200
        bs_kb = r_bs_kb.json()
        assert bs_kb["district_code"] == code
        assert bs_kb["district_area_km2"] > 0
        assert 0.0 <= bs_kb["coverage_pct"] <= 100.0
        assert bs_kb["facilities_inside"] > 0

    # 3. Maluku Utara (82) - Morotai Selatan (82.07.010, UTM 52N = 32652)
    r_mu = client.get("/api/v1/districts/82.07.010")
    assert r_mu.status_code == 200
    d_mu = r_mu.json()
    assert d_mu["name"] == "Morotai Selatan"
    assert d_mu["province_code"] == "82"
    assert "WorldPop" in d_mu["population_source"]
    assert d_mu["coverage"]["osm_coverage"]["status"] == "memadai"

    r_bs_mu = client.get("/api/v1/spatial/blank-spots?district_code=82.07.010&facility_type=sekolah_dasar")
    assert r_bs_mu.status_code == 200
    bs_mu = r_bs_mu.json()
    assert bs_mu["district_code"] == "82.07.010"
    assert bs_mu["district_area_km2"] > 0
    assert 0.0 <= bs_mu["coverage_pct"] <= 100.0
    assert bs_mu["facilities_inside"] > 0


def test_r1_live_config_keeps_rest_staging(monkeypatch):
    """With 28-province ACTIVE_PROVINCES, the 10 new provinces show Staging and return 404."""
    _require_rest_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", LIVE_28_PROVINCES)
    client = TestClient(app)

    r_reg = client.get("/api/v1/regions")
    assert r_reg.status_code == 200
    by_code = {r["province_code"]: r for r in r_reg.json()}
    assert len(by_code) == 38
    for pc in REST_10_PROVINCES:
        assert by_code[pc]["status"] == "Staging"
        assert by_code[pc]["has_data"] is True

    assert client.get("/api/v1/districts?province_code=61").status_code == 404
    assert client.get("/api/v1/districts/61.71.031").status_code == 404
    assert client.get("/api/v1/districts?province_code=51").status_code == 404
    assert client.get("/api/v1/regions/82").status_code == 404
