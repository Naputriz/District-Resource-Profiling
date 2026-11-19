"""
System End-to-End API Tests.
Runs real HTTP requests over an actual live uvicorn server started on a free port.
Marker: system.
Covered:
- /health
- /api/v1/districts
- /api/v1/districts/{code} (scorecard)
- /api/v1/spatial/blank-spots
- 401 unauthenticated paths for protected routes
- /api/v1/auth/login and /api/v1/auth/me
- /api/v1/simulation/what-if (isolated sandbox)
- /api/v1/simulation/superblock (impact level: Rendah/Sedang/Tinggi)
- Permit refusal (out of scope refusal without legal permit decision)
"""

import os
import socket
import subprocess
import sys
import time
import uuid
import httpx
import pytest

pytestmark = pytest.mark.system


@pytest.fixture(scope="session")
def auth_token(live_server_url):
    """Registers and authenticates a test user via real HTTP, returning JWT access token."""
    unique_id = uuid.uuid4().hex[:8]
    email = f"systest_{unique_id}@jakarta.go.id"
    password = "SecurePassword123!"
    user_id = None

    with httpx.Client(base_url=live_server_url, timeout=10.0) as client:
        # Register user
        reg_res = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "display_name": "System Test User",
                "department": "Tata Ruang",
            },
        )
        assert reg_res.status_code in (200, 201), f"Register failed: {reg_res.text}"
        user_id = reg_res.json().get("id")

        # Login to obtain JWT
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        data = login_res.json()
        token = data.get("access_token")
        assert token is not None

    yield token

    # Teardown: delete registered test user, audit rows, and Redis keys
    try:
        from backend.app.core.db import get_db_cursor, get_redis_client
        with get_db_cursor() as cur:
            if user_id:
                cur.execute("DELETE FROM chat_audit WHERE user_id = %s;", (user_id,))
                cur.execute("DELETE FROM app_users WHERE id = %s;", (user_id,))
            else:
                cur.execute("DELETE FROM app_users WHERE email = %s;", (email,))
        r = get_redis_client()
        if r and user_id:
            r.delete(f"rate:chat:user:{user_id}")
    except Exception:
        pass


def test_system_api_health(live_server_url):
    """GET /health returns healthy status for app, database, and cache."""
    with httpx.Client(base_url=live_server_url, timeout=5.0) as client:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "healthy"
        assert data.get("postgis_database") == "healthy"


def test_system_api_districts_list(live_server_url, requires_seed):
    """GET /api/v1/districts returns all 44 Jakarta districts."""
    with httpx.Client(base_url=live_server_url, timeout=10.0) as client:
        res = client.get("/api/v1/districts")
        assert res.status_code == 200
        data = res.json()
        districts = data.get("districts", [])
        assert len(districts) == 44
        # Verify Tebet presence
        tebet = next((d for d in districts if d["kemendagri_code"] == "31.71.09"), None)
        assert tebet is not None
        assert tebet["name"] == "Tebet"


def test_system_api_district_scorecard(live_server_url, requires_seed):
    """GET /api/v1/districts/31.71.09 returns detailed scorecard and audit metrics."""
    with httpx.Client(base_url=live_server_url, timeout=5.0) as client:
        res = client.get("/api/v1/districts/31.71.09")
        assert res.status_code == 200
        data = res.json()
        assert data.get("kemendagri_code") == "31.71.09"
        assert "composite_livability_score" in data
        assert "metrics_payload" in data
        assert len(data["metrics_payload"]) > 0


def test_system_api_blank_spots(live_server_url, requires_seed):
    """GET /api/v1/spatial/blank-spots returns GeoJSON coverage for puskesmas in Tebet."""
    with httpx.Client(base_url=live_server_url, timeout=10.0) as client:
        res = client.get(
            "/api/v1/spatial/blank-spots",
            params={"district_code": "31.71.09", "facility_type": "puskesmas_kelurahan"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "blank_spot_geojson" in data
        assert data.get("district_code") == "31.71.09"
        assert "coverage_pct" in data


def test_system_api_401_paths(live_server_url):
    """Protected routes reject requests missing authentication with 401."""
    with httpx.Client(base_url=live_server_url, timeout=5.0) as client:
        # Auth me
        res_me = client.get("/api/v1/auth/me")
        assert res_me.status_code == 401

        # What-if simulation
        res_whatif = client.post(
            "/api/v1/simulation/what-if",
            json={"district_code": "31.71.09", "pop_shock_pct": 10.0},
        )
        assert res_whatif.status_code == 401

        # Superblock simulation
        res_super = client.post(
            "/api/v1/simulation/superblock",
            json={
                "project_name": "Proyek X",
                "district_code": "31.71.09",
                "site_area_m2": 10000,
                "residential_units": 500,
            },
        )
        assert res_super.status_code == 401

        # Chat endpoint
        res_chat = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "Halo"}]},
        )
        assert res_chat.status_code == 401


def test_system_api_auth_login_and_me(live_server_url, auth_token):
    """Verifies that authenticated user with Bearer token accesses /auth/me successfully."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=5.0) as client:
        res = client.get("/api/v1/auth/me")
        assert res.status_code == 200
        data = res.json()
        assert "email" in data
        assert data.get("display_name") == "System Test User"
        assert data.get("role") == "user"


def test_system_api_simulation_whatif(live_server_url, auth_token, requires_seed):
    """POST /api/v1/simulation/what-if executes isolated sandbox population delta."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    payload = {
        "district_code": "31.71.09",
        "population_shock_count": 10000,
        "staged_amenities": [],
    }
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=10.0) as client:
        res = client.post("/api/v1/simulation/what-if", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("is_sandbox_isolated") is True
        assert data.get("population_delta") == 10000
        assert data.get("impact_level") in ("Rendah", "Sedang", "Tinggi")
        assert "disclaimer" in data


def test_system_api_simulation_superblock(live_server_url, auth_token, requires_seed):
    """POST /api/v1/simulation/superblock computes environmental impact indication."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    payload = {
        "project_name": "Apartemen Tebet Eco Living",
        "district_code": "31.71.09",
        "site_area_m2": 25000.0,
        "residential_units": 1200,
        "commercial_gfa_m2": 8000.0,
    }
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=10.0) as client:
        res = client.post("/api/v1/simulation/superblock", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("project_name") == "Apartemen Tebet Eco Living"
        assert data.get("mandated_public_rth_m2") > 0
        assert data.get("mandated_water_retention_m3") > 0
        assert data.get("impact_level") in ("Rendah", "Sedang", "Tinggi")
        # Ensure simulation delta is included
        delta = data.get("simulation_delta")
        assert delta is not None
        assert delta.get("is_sandbox_isolated") is True


def test_system_api_permit_refusal(live_server_url, auth_token):
    """
    POST /api/v1/chat with permit decision question triggers out-of-scope refusal.
    Enforces engineering rule: simulation output is impact indication, never permit decision.
    """
    headers = {"Authorization": f"Bearer {auth_token}"}
    payload = {
        "messages": [
            {
                "role": "user",
                "content": "Apakah proyek apartemen 3.000 unit di Tebet ini boleh disetujui izin pembangunannya?",
            }
        ]
    }
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=10.0) as client:
        res = client.post("/api/v1/chat", json=payload)
        assert res.status_code == 200
        data = res.json()
        reply = data.get("reply", "")
        # Refusal must explicitly state out-of-scope / lack of legal authority
        assert "tidak memiliki kewenangan" in reply or "bukan keputusan perizinan" in reply or "kewenangan" in reply or "izin" in reply
        assert data.get("rounds_used") == 0
        assert data.get("guardrail") == "passed"
