"""
Integration Tests for FastAPI Backend Endpoints.
Uses starlette.testclient.TestClient.
"""

import json
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.db import init_db_pool, close_db_pool

pytestmark = pytest.mark.db

def test_api_endpoints():
    run_api_suite(close_pool=False)

def run_api_suite(close_pool: bool = True):
    init_db_pool()
    client = TestClient(app)

    print("\n--- 1. Testing Health Endpoint ---")
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    print("Health response:", data)
    assert data["postgis_database"] == "healthy"
    assert data["redis_cache"] == "healthy"

    print("\n--- 2. Testing Regulatory Standards Metadata ---")
    res = client.get("/api/v1/meta/standards")
    assert res.status_code == 200
    standards = res.json()
    print(f"Total regulatory standards: {len(standards)}")
    assert len(standards) >= 16

    print("\n--- 3. Testing Districts List & Detail ---")
    res = client.get("/api/v1/districts")
    assert res.status_code == 200
    districts_data = res.json()
    dist_list = districts_data.get("districts", [])
    if isinstance(dist_list, dict):
        dist_list = list(dist_list.values())
    print(f"Districts retrieved: {len(dist_list)}")
    assert len(dist_list) == 44

    # Test single district detail: Tebet (31.71.09)
    res = client.get("/api/v1/districts/31.71.09")
    assert res.status_code == 200
    tebet = res.json()
    print(f"Tebet Detail: Name={tebet['name']}, Pop={tebet['population']:,}, Score={tebet['composite_livability_score']}")
    assert tebet["kemendagri_code"] == "31.71.09"
    assert "boundary_geojson" in tebet

    print("\n--- 4. Testing 4 Pillars Facilities Filtering ---")
    res = client.get("/api/v1/facilities?pillar=lifeline_health")
    assert res.status_code == 200
    facs = res.json()
    print(f"Lifeline facilities: {facs['total']}")
    assert facs["total"] > 0
    assert "data_source" in facs
    assert "OpenStreetMap" in facs["data_source"]

    print("\n--- 5. Testing What-If Scenario Simulation ---")
    sim_payload = {
        "district_code": "31.71.09",
        "population_shock_percent": 20.0,
        "population_shock_count": 0,
        "hypothetical_facilities": [
            {
                "name": "Puskesmas Hipotetis Baru Tebet Timur",
                "pillar": "lifeline_health",
                "facility_type": "puskesmas_kelurahan",
                "coordinates": [106.850, -6.235]
            }
        ]
    }
    res = client.post("/api/v1/simulation/what-if", json=sim_payload)
    assert res.status_code == 200
    sim_res = res.json()
    print(f"What-If Simulation Delta: Pop={sim_res['baseline_population']:,} -> {sim_res['simulated_population']:,} | Delta Score={sim_res['score_delta']}")
    assert sim_res["is_sandbox_isolated"] is True
    assert sim_res["hypothetical_facilities_added"] == 1

    print("\n--- 6. Testing Superblock Simulation ---")
    superblock_payload = {
        "district_code": "31.71.09",
        "project_name": "Tebet Green Central Park",
        "residential_units": 3500,
        "occupants_per_unit": 3.0,
        "site_area_m2": 25000.0,
        "staged_amenities": []
    }
    res = client.post("/api/v1/simulation/superblock", json=superblock_payload)
    assert res.status_code == 200
    sb_res = res.json()
    print(f"Superblock Simulation: New Occupants={sb_res['estimated_new_occupants']:,} | Mandated RTH={sb_res['mandated_public_rth_m2']} m² | Verdict={sb_res['compliance_verdict']}")
    assert sb_res["mandated_public_rth_m2"] == 5000.0
    assert len(sb_res["developer_legal_obligations"]) >= 3
    for forbidden in ["DITO" + "LAK", "DISET" + "UJUI"]:
        assert forbidden not in sb_res["compliance_verdict"]
    assert "Bukan keputusan perizinan. Untuk bahan diskusi perencanaan." in sb_res["compliance_verdict"]
    assert sb_res["impact_level"] in ["Rendah", "Sedang", "Tinggi"]
    assert "assumptions" in sb_res
    assert sb_res["assumptions"]["kdb_ratio"] == 0.50
    assert sb_res["assumptions"]["rth_article_reference"] == "Asumsi RTH 20% (belum diverifikasi ke Perda 31/2022)"
    dump_sb = json.dumps(sb_res).lower()
    assert "wajib" not in dump_sb
    assert "pasal 64" not in dump_sb

    print("\n--- 7. Testing Spatial Service Buffers & Blank Spots ---")
    res = client.get("/api/v1/spatial/buffers?district_code=31.71.09&facility_type=puskesmas_kelurahan")
    assert res.status_code == 200
    buffers = res.json()
    print(f"Puskesmas Buffers for Tebet: {buffers['total_buffers']} circles")

    res = client.get("/api/v1/spatial/blank-spots?district_code=31.71.09&facility_type=puskesmas_kelurahan")
    assert res.status_code == 200
    blank_spots = res.json()
    print(f"Blank Spots Tebet: Area={blank_spots['district_area_km2']} km², Unserved={blank_spots['unserved_area_km2']} km², Coverage={blank_spots['coverage_pct']}% (Without Neighbours: {blank_spots['coverage_pct_without_neighbours']}%)")
    assert blank_spots["district_code"] == "31.71.09"
    assert blank_spots["cross_border_scope"] == "DKI Jakarta only"
    assert blank_spots["facilities_inside"] == 7
    assert blank_spots["facilities_from_neighbours"] == 23
    assert blank_spots["coverage_pct"] >= 99.0
    assert blank_spots["coverage_pct_without_neighbours"] >= 92.0
    assert blank_spots["coverage_pct"] >= blank_spots["coverage_pct_without_neighbours"]

    print("\n--- 8. Testing Regulatory Hybrid RAG (/api/v1/rag/search) ---")
    rag_payload = {
        "query": "Berapa standar penyediaan puskesmas kelurahan dan radius layanan?",
        "pillar": "lifeline_health",
        "top_k": 3
    }
    # Target endpoint (§13)
    res = client.post("/api/v1/rag/search", json=rag_payload)
    assert res.status_code == 200
    rag_res = res.json()
    print(f"Hybrid RAG Citations found: {rag_res['total_results']}")
    assert rag_res["total_results"] > 0
    print("Formatted Legal Citation Markdown:\n", rag_res["citations_markdown"][:300], "...")

    # Deprecated alias check
    res_alias = client.post("/api/v1/rag/hybrid-search", json=rag_payload)
    assert res_alias.status_code == 200
    assert res_alias.headers.get("deprecation") == "true"
    print("Deprecated alias /api/v1/rag/hybrid-search returned Deprecation header: true")

    print("\n--- 9. Testing Cognitive Spatial Chat (/api/v1/chat) ---")
    chat_payload = {
        "messages": [{"role": "user", "content": "Halo, apakah proyek ini boleh disetujui?"}],
        "district_context": "31.71.09"
    }
    # Target endpoint (§13)
    res_chat = client.post("/api/v1/chat", json=chat_payload)
    assert res_chat.status_code == 200
    chat_res = res_chat.json()
    assert "reply" in chat_res
    print("Target endpoint /api/v1/chat succeeded.")

    # Deprecated alias check
    res_chat_alias = client.post("/api/v1/chat/conversation", json=chat_payload)
    assert res_chat_alias.status_code == 200
    assert res_chat_alias.headers.get("deprecation") == "true"
    print("Deprecated alias /api/v1/chat/conversation returned Deprecation header: true")

    if close_pool:
        close_db_pool()
    print("\n=======================================================")
    print("ALL API INTEGRATION TESTS PASSED SUCCESSFULLY!")
    print("=======================================================")


def test_optional_api_key_behavior():
    """Verify API_KEY behavior :
    1. If unset in env: POST routes succeed without X-API-Key header.
    2. If set in env: POST routes require X-API-Key, 401 if missing/invalid, 200 if valid.
    3. GET routes remain accessible without header in both cases.
    """
    import os
    client = TestClient(app)

    sim_payload = {
        "district_code": "31.71.09",
        "population_shock_percent": 10.0,
        "population_shock_count": 0,
        "hypothetical_facilities": []
    }

    # Case A: API_KEY is unset
    original_key = os.environ.pop("API_KEY", None)
    try:
        # POST succeeds without header
        res = client.post("/api/v1/simulation/what-if", json=sim_payload)
        assert res.status_code == 200, f"Expected 200 when API_KEY is unset, got {res.status_code}"

        # GET succeeds
        res_get = client.get("/api/v1/districts")
        assert res_get.status_code == 200

        # Case B: API_KEY is set
        os.environ["API_KEY"] = "test-secret-key-12345"

        # POST without header -> 401
        res_no_key = client.post("/api/v1/simulation/what-if", json=sim_payload)
        assert res_no_key.status_code == 401, f"Expected 401 without header, got {res_no_key.status_code}"
        assert "Invalid or missing X-API-Key" in res_no_key.json().get("detail", "")

        # POST with wrong header -> 401
        res_wrong_key = client.post(
            "/api/v1/simulation/what-if",
            json=sim_payload,
            headers={"X-API-Key": "incorrect-key"}
        )
        assert res_wrong_key.status_code == 401

        # POST with valid header -> 200
        res_valid = client.post(
            "/api/v1/simulation/what-if",
            json=sim_payload,
            headers={"X-API-Key": "test-secret-key-12345"}
        )
        assert res_valid.status_code == 200

        # GET route is NOT blocked even when API_KEY is set
        res_get_auth = client.get("/api/v1/districts")
        assert res_get_auth.status_code == 200

    finally:
        if original_key is not None:
            os.environ["API_KEY"] = original_key
        else:
            os.environ.pop("API_KEY", None)


if __name__ == "__main__":
    run_api_suite()

