"""
Integration Tests for FastAPI Backend Endpoints.
Uses starlette.testclient.TestClient against live PostgreSQL database. Marker: db.
"""

import json
import uuid
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.db import init_db_pool, close_db_pool, get_db_cursor
from backend.app.core.auth import create_access_token, hash_password

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]


def test_api_endpoints():
    run_api_suite(close_pool=False)


def run_api_suite(close_pool: bool = True):
    init_db_pool()
    client = TestClient(app)

    test_user_id = None
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_users (email, password_hash, display_name, role)
                VALUES (%s, %s, %s, 'admin')
                RETURNING id;
                """,
                (
                    f"api_test_{uuid.uuid4().hex[:8]}@jakarta.go.id",
                    hash_password("ValidPassword123!"),
                    "API Test User",
                ),
            )
            test_user_id = str(cur.fetchone()["id"])

        token = create_access_token({
            "sub": test_user_id,
            "email": "api_test@jakarta.go.id",
            "role": "admin",
        })
        auth_headers = {"Authorization": f"Bearer {token}"}

        # 1. Health
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["postgis_database"] == "healthy"
        assert data["redis_cache"] == "healthy"

        # 2. Standards
        res = client.get("/api/v1/meta/standards")
        assert res.status_code == 200
        standards = res.json()
        assert len(standards) >= 16

        # 3. Districts
        res = client.get("/api/v1/districts")
        assert res.status_code == 200
        districts_data = res.json()
        dist_list = districts_data.get("districts", [])
        if isinstance(dist_list, dict):
            dist_list = list(dist_list.values())
        assert len(dist_list) == 44

        res = client.get("/api/v1/districts/31.71.09")
        assert res.status_code == 200
        tebet = res.json()
        assert tebet["kemendagri_code"] == "31.71.09"
        assert "boundary_geojson" in tebet

        # 4. Facilities
        res = client.get("/api/v1/facilities?pillar=lifeline_health")
        assert res.status_code == 200
        facs = res.json()
        assert facs["total"] > 0

        # 5. What-if simulation
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
        res = client.post("/api/v1/simulation/what-if", json=sim_payload, headers=auth_headers)
        assert res.status_code == 200
        sim_res = res.json()
        assert sim_res["is_sandbox_isolated"] is True
        assert sim_res["hypothetical_facilities_added"] == 1

        # 6. Superblock simulation
        superblock_payload = {
            "district_code": "31.71.09",
            "project_name": "Tebet Green Central Park",
            "residential_units": 3500,
            "occupants_per_unit": 3.0,
            "site_area_m2": 25000.0,
            "staged_amenities": []
        }
        res = client.post("/api/v1/simulation/superblock", json=superblock_payload, headers=auth_headers)
        assert res.status_code == 200
        sb_res = res.json()
        assert sb_res["mandated_public_rth_m2"] == 5000.0
        assert len(sb_res["developer_legal_obligations"]) >= 3
        for forbidden in ["DITO" + "LAK", "DISET" + "UJUI"]:
            assert forbidden not in sb_res["compliance_verdict"]
        assert "Bukan keputusan perizinan. Untuk bahan diskusi perencanaan." in sb_res["compliance_verdict"]
        assert sb_res["impact_level"] in ["Rendah", "Sedang", "Tinggi"]
        assert "assumptions" in sb_res

        # 7. Spatial buffers & blank spots
        res = client.get("/api/v1/spatial/buffers?district_code=31.71.09&facility_type=puskesmas_kelurahan")
        assert res.status_code == 200

        res = client.get("/api/v1/spatial/blank-spots?district_code=31.71.09&facility_type=puskesmas_kelurahan")
        assert res.status_code == 200
        blank_spots = res.json()
        assert blank_spots["district_code"] == "31.71.09"
        assert blank_spots["facilities_inside"] == 7
        assert blank_spots["coverage_pct"] >= 99.0

        # 8. RAG search
        rag_payload = {
            "query": "Berapa standar penyediaan puskesmas kelurahan dan radius layanan?",
            "pillar": "lifeline_health",
            "top_k": 3
        }
        res = client.post("/api/v1/rag/search", json=rag_payload, headers=auth_headers)
        assert res.status_code == 200

        # 9. Chat
        chat_payload = {
            "messages": [{"role": "user", "content": "Halo, apakah proyek ini boleh disetujui?"}],
            "district_context": "31.71.09"
        }
        res_chat = client.post("/api/v1/chat", json=chat_payload, headers=auth_headers)
        assert res_chat.status_code == 200
    finally:
        if test_user_id:
            try:
                from backend.app.core.db import get_redis_client
                with get_db_cursor() as cur:
                    cur.execute("DELETE FROM chat_audit WHERE user_id = %s;", (test_user_id,))
                    cur.execute("DELETE FROM app_users WHERE id = %s;", (test_user_id,))
                r = get_redis_client()
                if r:
                    r.delete(f"rate:chat:user:{test_user_id}")
            except Exception:
                pass
        if close_pool:
            close_db_pool()
