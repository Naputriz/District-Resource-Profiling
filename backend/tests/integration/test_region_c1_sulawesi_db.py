"""
Integration tests for Task C1 (Sulawesi data load on staging DB `district_profiling_stage`).
Tests northern hemisphere province Sulawesi Utara (71) and southern hemisphere province
Sulawesi Selatan (73), plus Sulawesi Barat (76) zero-pop Balabalakang and live-config safety.
Marker: db.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routers.regions import clear_regions_cache
from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor, init_db_pool
from backend.app.main import app

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]

ALL_22_PROVINCES = "31,32,33,34,35,36,11,12,13,14,15,16,17,18,19,21,71,72,73,74,75,76"
LIVE_16_PROVINCES = "31,32,33,34,35,36,11,12,13,14,15,16,17,18,19,21"


def _require_sulawesi_stage():
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM provinces WHERE kemendagri_code IN ('71', '73');")
        if cur.fetchone()["cnt"] < 2:
            pytest.skip("Sulawesi provinces (71, 73) not loaded in current database")


@pytest.mark.parametrize(
    "province_code,expected_kec,allowed_srids",
    [
        ("71", 171, (32651, 32652)),
        ("73", 307, (32750, 32751)),
    ],
)
def test_c1_sulut_and_sulsel_db_counts_utm_and_scores(
    province_code: str,
    expected_kec: int,
    allowed_srids: tuple,
):
    """Sulawesi Utara (71, northern 326xx) and Sulawesi Selatan (73, southern 327xx): counts > 0, valid UTM SRIDs, scores 0..100 or NULL-gated."""
    _require_sulawesi_stage()
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


def test_c1_detail_and_blank_spots_sulut_and_sulsel(monkeypatch):
    """Detail + blank spots endpoints work for Wenang (Sulut 71, 32651) and Ujung Pandang (Sulsel 73, 32750)."""
    _require_sulawesi_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", ALL_22_PROVINCES)
    client = TestClient(app)

    # 1. Sulawesi Utara (71) - Wenang (Kota Manado, UTM 51N = 32651)
    r_wenang = client.get("/api/v1/districts/71.71.030")
    assert r_wenang.status_code == 200
    d_wenang = r_wenang.json()
    assert d_wenang["name"] == "Wenang"
    assert d_wenang["province_code"] == "71"
    assert "WorldPop" in d_wenang["population_source"]
    assert d_wenang["coverage"]["osm_coverage"]["status"] == "memadai"
    assert d_wenang["score_status"] == "Tersedia"
    assert d_wenang["composite_livability_score"] is not None
    assert 0.0 <= float(d_wenang["composite_livability_score"]) <= 100.0

    r_bs_wenang = client.get(
        "/api/v1/spatial/blank-spots?district_code=71.71.030&facility_type=sekolah_dasar"
    )
    assert r_bs_wenang.status_code == 200
    bs_wenang = r_bs_wenang.json()
    assert bs_wenang["district_code"] == "71.71.030"
    assert bs_wenang["district_area_km2"] > 0
    assert 0.0 <= bs_wenang["coverage_pct"] <= 100.0
    assert bs_wenang["facilities_inside"] > 0

    # 2. Sulawesi Selatan (73) - Ujung Pandang (Kota Makassar, UTM 50S = 32750)
    r_up = client.get("/api/v1/districts/73.71.050")
    assert r_up.status_code == 200
    d_up = r_up.json()
    assert d_up["name"] == "Ujung Pandang"
    assert d_up["province_code"] == "73"
    assert "WorldPop" in d_up["population_source"]
    assert d_up["coverage"]["osm_coverage"]["status"] == "memadai"
    assert d_up["score_status"] == "Tersedia"
    assert d_up["composite_livability_score"] is not None
    assert 0.0 <= float(d_up["composite_livability_score"]) <= 100.0

    r_bs_up = client.get(
        "/api/v1/spatial/blank-spots?district_code=73.71.050&facility_type=sekolah_dasar"
    )
    assert r_bs_up.status_code == 200
    bs_up = r_bs_up.json()
    assert bs_up["district_code"] == "73.71.050"
    assert bs_up["district_area_km2"] > 0
    assert 0.0 <= bs_up["coverage_pct"] <= 100.0
    assert bs_up["facilities_inside"] > 0

    # 3. Sulawesi Barat (76) - all 69 districts returned including zero-pop Balabalakang (76.04.023)
    r_sulbar = client.get("/api/v1/districts?province_code=76")
    assert r_sulbar.status_code == 200
    sulbar_list = r_sulbar.json()["districts"]
    assert len(sulbar_list) == 69
    bala = next(d for d in sulbar_list if d["kemendagri_code"] == "76.04.023")
    assert bala["name"] == "Balabalakang"
    assert bala["score_status"] == "Data tidak memadai"


def test_c1_live_config_keeps_sulawesi_staging(monkeypatch):
    """With live 16-province ACTIVE_PROVINCES, Sulawesi provinces show Staging and return 404."""
    _require_sulawesi_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", LIVE_16_PROVINCES)
    client = TestClient(app)

    r_reg = client.get("/api/v1/regions")
    assert r_reg.status_code == 200
    by_code = {r["province_code"]: r for r in r_reg.json()}
    for pc in ("71", "72", "73", "74", "75", "76"):
        assert by_code[pc]["status"] == "Staging"
        assert by_code[pc]["has_data"] is True
    for pc in ("31", "32", "33", "34", "35", "36", "11", "12", "13", "14", "15", "16", "17", "18", "19", "21"):
        assert by_code[pc]["status"] == "Active"

    assert client.get("/api/v1/districts?province_code=71").status_code == 404
    assert client.get("/api/v1/districts/71.71.030").status_code == 404
    assert client.get("/api/v1/districts?province_code=73").status_code == 404
    assert client.get("/api/v1/regions/73").status_code == 404
