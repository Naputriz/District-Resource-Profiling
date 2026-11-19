"""
Integration tests for Task J1b multi-province API against staging PostGIS DB
(POSTGRES_DB=district_profiling_stage, REDIS_DB=1, ACTIVE_PROVINCES=31,32,33,34,35,36).
Marker: db.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor, init_db_pool
from backend.app.api.routers.regions import clear_regions_cache
from backend.app.main import app

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]


def _require_java_stage():
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT 1 FROM provinces WHERE kemendagri_code = '32';")
        if not cur.fetchone():
            pytest.skip("Java provinces not loaded in current database")


def test_j1b_list_districts_32_and_35(monkeypatch):
    """List districts for 32 (627) and 35 (666); gated rows have NULL composite and rank None."""
    _require_java_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32,33,34,35,36")
    client = TestClient(app)

    res_32 = client.get("/api/v1/districts?province_code=32")
    assert res_32.status_code == 200
    d32 = res_32.json()
    assert len(d32["districts"]) == 627
    assert "WorldPop" in d32["population_note"]
    gated_32 = [d for d in d32["districts"] if d["composite_livability_score"] is None]
    scored_32 = [d for d in d32["districts"] if d["composite_livability_score"] is not None]
    assert len(gated_32) == 306
    assert len(scored_32) == 321
    assert all(d["rank"] is None and d["score_status"] == "Data tidak memadai" for d in gated_32)
    assert all(isinstance(d["rank"], int) and d["rank"] >= 1 for d in scored_32)

    res_35 = client.get("/api/v1/districts?province_code=35")
    assert res_35.status_code == 200
    d35 = res_35.json()
    assert len(d35["districts"]) == 666
    assert "WorldPop" in d35["population_note"]
    gated_35 = [d for d in d35["districts"] if d["composite_livability_score"] is None]
    assert len(gated_35) == 339
    assert all(d["rank"] is None for d in gated_35)


def test_j1b_district_details_coblong_tegalsari_ciemas_tebet(monkeypatch):
    """Detail endpoints work for Coblong (32), Tegalsari (35), Ciemas (gated 32), and Tebet (31)."""
    _require_java_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32,33,34,35,36")
    client = TestClient(app)

    # Coblong (UTM 48S)
    r_cob = client.get("/api/v1/districts/32.73.230")
    assert r_cob.status_code == 200
    cob = r_cob.json()
    assert cob["name"] == "Coblong"
    assert cob["score_status"] == "Tersedia"
    assert cob["composite_livability_score"] is not None
    assert "WorldPop" in cob["population_source"]
    assert cob["coverage"]["osm_coverage"]["status"] == "memadai"

    # Tegalsari (UTM 49S)
    r_teg = client.get("/api/v1/districts/35.78.180")
    assert r_teg.status_code == 200
    teg = r_teg.json()
    assert teg["name"] == "Tegalsari"
    assert teg["score_status"] == "Tersedia"
    assert "WorldPop" in teg["population_source"]

    # Ciemas (gated kecamatan in Sukabumi, Jawa Barat)
    r_cie = client.get("/api/v1/districts/32.02.010")
    assert r_cie.status_code == 200
    cie = r_cie.json()
    assert cie["name"] == "Ciemas"
    assert cie["composite_livability_score"] is None
    assert cie["score_status"] == "Data tidak memadai"
    assert cie["coverage"]["osm_coverage"]["status"] == "tidak_memadai"
    assert cie["coverage"]["osm_coverage"]["mapped_sd"] == 0

    # Tebet (DKI Jakarta)
    r_teb = client.get("/api/v1/districts/31.71.09")
    assert r_teb.status_code == 200
    teb = r_teb.json()
    assert teb["name"] == "Tebet"
    assert teb["population_note"] == "BPS 2024"
    assert teb["composite_livability_score"] is not None


def test_j1b_facilities_and_blank_spots_coblong_and_tegalsari(monkeypatch):
    """Facilities + blank spots work for Coblong (32748) and Tegalsari (32749)."""
    _require_java_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32,33,34,35,36")
    client = TestClient(app)

    for code, expected_name in [("32.73.230", "Coblong"), ("35.78.180", "Tegalsari")]:
        r_fac = client.get(f"/api/v1/facilities?district_code={code}&limit=50")
        assert r_fac.status_code == 200
        fac = r_fac.json()
        assert fac["total"] > 0

        r_bs = client.get(
            f"/api/v1/spatial/blank-spots?district_code={code}&facility_type=sekolah_dasar"
        )
        assert r_bs.status_code == 200
        bs = r_bs.json()
        assert bs["district_code"] == code
        assert bs["district_name"] == expected_name
        assert bs["district_area_km2"] > 0
        assert 0.0 <= bs["coverage_pct"] <= 100.0
        assert bs["facilities_inside"] > 0

        r_buf = client.get(
            f"/api/v1/spatial/buffers?district_code={code}&facility_type=sekolah_dasar"
        )
        assert r_buf.status_code == 200
        assert r_buf.json()["total_buffers"] > 0


def test_j1b_whatif_tegalsari_readonly(monkeypatch, service_auth_headers):
    """What-if simulation on Tegalsari (35.78.180) runs read-only and matches baseline."""
    _require_java_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32,33,34,35,36")
    client = TestClient(app)

    with get_db_cursor() as cur:
        cur.execute("SELECT population FROM kecamatan WHERE kemendagri_code = '35.78.180';")
        orig_pop = cur.fetchone()["population"]

    res = client.post(
        "/api/v1/simulation/what-if",
        json={
            "district_code": "35.78.180",
            "population_shock_count": 20000,
            "population_shock_percent": 0.0,
        },
        headers=service_auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["district_code"] == "35.78.180"
    assert data["is_sandbox_isolated"] is True
    assert data["population_delta"] == 20000
    assert data["baseline_population"] == orig_pop
    assert data["simulated_population"] == orig_pop + 20000
    assert "WorldPop" in data["population_note"]
    assert data["impact_level"] in ("Rendah", "Sedang", "Tinggi")

    with get_db_cursor() as cur:
        cur.execute("SELECT population FROM kecamatan WHERE kemendagri_code = '35.78.180';")
        after_pop = cur.fetchone()["population"]
    assert after_pop == orig_pop


def test_j1b_province_51_404_and_live_safety(monkeypatch):
    """Province 51 returns 404; with ACTIVE_PROVINCES=31 only, province 32 returns 404."""
    _require_java_stage()
    clear_regions_cache()
    client = TestClient(app)

    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32,33,34,35,36")
    r_51 = client.get("/api/v1/districts?province_code=51")
    assert r_51.status_code == 404

    # Live safety: only ACTIVE_PROVINCES=31
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")
    clear_regions_cache()

    assert client.get("/api/v1/districts?province_code=32").status_code == 404
    assert client.get("/api/v1/districts/32.73.230").status_code == 404
    assert client.get("/api/v1/facilities?province_code=32").status_code == 404
    assert client.get("/api/v1/regions/32").status_code == 404

    regions_res = client.get("/api/v1/regions")
    assert regions_res.status_code == 200
    by_code = {r["province_code"]: r for r in regions_res.json()}
    assert by_code["31"]["status"] == "Active"
    assert by_code["32"]["status"] == "Staging"

    # DKI 31 still works
    assert client.get("/api/v1/districts").status_code == 200
    assert len(client.get("/api/v1/districts").json()["districts"]) == 44


def test_j1b_straddling_utm_zone_cipatujah(monkeypatch):
    """
    Cipatujah (32.06.010, kec_srid=32749) straddles 108E and contains sekolah_dasar
    facilities in both 32749 (2) and 32748 (3). Fix 6 must include all 5 inside facilities
    and simulate blank-spot reduction without dropping cross-zone facilities.
    """
    from backend.app.engine.spatial import PostGISSpatialEngine

    _require_java_stage()
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32,33,34,35,36")

    res = PostGISSpatialEngine.calculate_blank_spots("32.06.010", "sekolah_dasar")
    assert res.district_code == "32.06.010"
    assert res.district_name == "Cipatujah"
    assert res.facilities_inside == 5
    assert res.served_area_km2 > 0.0
    assert res.coverage_pct > 0.0

    # Place a hypothetical SD inside Cipatujah away from existing ones (~108.05, -7.73)
    delta = PostGISSpatialEngine.simulate_blank_spot_reduction(
        district_code="32.06.010",
        facility_type="sekolah_dasar",
        hypothetical_coords=[108.05, -7.73],
    )
    assert delta.district_code == "32.06.010"
    assert delta.simulated_unserved_km2 <= delta.baseline_unserved_km2
    assert delta.area_recovered_km2 >= 0.0
