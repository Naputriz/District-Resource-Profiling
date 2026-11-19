"""
Integration tests for Task P1 (Papua data load on staging DB `district_profiling_stage`).
Tests Papua (91), Papua Barat Daya (96, crosses equator -> 326xx north & 327xx south),
Papua Pegunungan (95, highlands with 4 WorldPop zero-pop districts), detail + blank spots,
and live-config safety.
Marker: db.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routers.regions import clear_regions_cache
from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor, init_db_pool
from backend.app.main import app

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]

ALL_28_PROVINCES = (
    "31,32,33,34,35,36,11,12,13,14,15,16,17,18,19,21,71,72,73,74,75,76,91,92,93,94,95,96"
)
LIVE_22_PROVINCES = "31,32,33,34,35,36,11,12,13,14,15,16,17,18,19,21,71,72,73,74,75,76"


def _require_papua_stage():
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM provinces WHERE kemendagri_code IN ('91', '95', '96');")
        if cur.fetchone()["cnt"] < 3:
            pytest.skip("Papua provinces (91, 95, 96) not loaded in current database")


@pytest.mark.parametrize(
    "province_code,expected_kec,expected_zero_pop,allowed_srids",
    [
        ("91", 97, 0, (32753, 32754)),
        ("95", 185, 4, (32753, 32754)),
        ("96", 99, 0, (32652, 32752, 32753)),
    ],
)
def test_p1_papua_db_counts_utm_and_scores(
    province_code: str,
    expected_kec: int,
    expected_zero_pop: int,
    allowed_srids: tuple,
):
    """Papua (91), Papua Pegunungan (95), and Papua Barat Daya (96): counts > 0, valid UTM SRIDs, scores 0..100 or NULL-gated."""
    _require_papua_stage()
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS kec_cnt,
                   COUNT(*) FILTER (WHERE k.utm_srid IS NULL) AS null_utm,
                   COUNT(*) FILTER (WHERE k.utm_srid NOT IN %s) AS bad_utm,
                   COUNT(*) FILTER (WHERE k.population IS NULL OR k.population <= 0) AS zero_pop
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
        assert kstat["zero_pop"] == expected_zero_pop

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
        assert len(scores) == expected_kec - expected_zero_pop
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


def test_p1_detail_and_blank_spots_papua_and_pegunungan(monkeypatch):
    """Detail + blank spots endpoints work for Biak Kota (91, 32753), Jayapura Utara (91, 32754), and Wamena (95, 32754)."""
    _require_papua_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", ALL_28_PROVINCES)
    client = TestClient(app)

    # 1. Papua (91) - Biak Kota (91.06.050, UTM 53S = 32753, has mapped SD) & Jayapura Utara (91.71.040)
    r_ju = client.get("/api/v1/districts/91.71.040")
    assert r_ju.status_code == 200
    d_ju = r_ju.json()
    assert d_ju["name"] == "Jayapura Utara"
    assert d_ju["province_code"] == "91"
    assert "WorldPop" in d_ju["population_source"]
    assert d_ju["score_status"] == "Data tidak memadai"

    r_bs_biak = client.get(
        "/api/v1/spatial/blank-spots?district_code=91.06.050&facility_type=sekolah_dasar"
    )
    assert r_bs_biak.status_code == 200
    bs_biak = r_bs_biak.json()
    assert bs_biak["district_code"] == "91.06.050"
    assert bs_biak["district_area_km2"] > 0
    assert 0.0 <= bs_biak["coverage_pct"] <= 100.0
    assert bs_biak["facilities_inside"] > 0

    # 2. Papua Pegunungan (95) - Wamena (95.01.110, UTM 54S = 32754, has 6 SD) + 185 districts total incl. 4 zero-pop
    r_wam = client.get("/api/v1/districts/95.01.110")
    assert r_wam.status_code == 200
    d_wam = r_wam.json()
    assert d_wam["name"] == "Wamena"
    assert d_wam["province_code"] == "95"
    assert d_wam["coverage"]["osm_coverage"]["status"] == "memadai"
    assert d_wam["score_status"] == "Data tidak memadai"

    r_bs_wam = client.get(
        "/api/v1/spatial/blank-spots?district_code=95.01.110&facility_type=sekolah_dasar"
    )
    assert r_bs_wam.status_code == 200
    bs_wam = r_bs_wam.json()
    assert bs_wam["district_code"] == "95.01.110"
    assert bs_wam["district_area_km2"] > 0
    assert 0.0 <= bs_wam["coverage_pct"] <= 100.0
    assert bs_wam["facilities_inside"] > 0

    r_peg = client.get("/api/v1/districts?province_code=95")
    assert r_peg.status_code == 200
    peg_list = r_peg.json()["districts"]
    assert len(peg_list) == 185
    solo = next(d for d in peg_list if d["kemendagri_code"] == "95.03.052")
    assert solo["name"] == "Soloikma"
    assert solo["score_status"] == "Data tidak memadai"


def test_p1_live_config_keeps_papua_staging(monkeypatch):
    """With live 22-province ACTIVE_PROVINCES, Papua provinces show Staging and return 404."""
    _require_papua_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", LIVE_22_PROVINCES)
    client = TestClient(app)

    r_reg = client.get("/api/v1/regions")
    assert r_reg.status_code == 200
    by_code = {r["province_code"]: r for r in r_reg.json()}
    for pc in ("91", "92", "93", "94", "95", "96"):
        assert by_code[pc]["status"] == "Staging"
        assert by_code[pc]["has_data"] is True

    assert client.get("/api/v1/districts?province_code=91").status_code == 404
    assert client.get("/api/v1/districts/91.71.040").status_code == 404
    assert client.get("/api/v1/districts?province_code=95").status_code == 404
    assert client.get("/api/v1/regions/96").status_code == 404
