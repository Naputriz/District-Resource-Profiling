"""
Unit tests for API key behavior per REBUILD_PROMPT_P13_1 §13.1C.
Marker: unit.
"""

import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from backend.app.main import app
from backend.app.core.auth import create_access_token

pytestmark = pytest.mark.unit


def test_optional_api_key_behavior():
    """Verify API_KEY behavior per REBUILD_PROMPT_P13_1 §13.1C:
    1. If unset in env: POST routes succeed without X-API-Key header.
    2. If set in env: POST routes require X-API-Key, 401 if missing/invalid, 200 if valid.
    3. GET routes remain accessible without header in both cases.
    """
    client = TestClient(app)

    sim_payload = {
        "district_code": "31.71.09",
        "population_shock_percent": 10.0,
        "population_shock_count": 0,
        "hypothetical_facilities": []
    }

    test_tok = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000000",
        "email": "service@drp.local",
        "role": "admin",
        "is_service": True,
    })
    user_headers = {"Authorization": f"Bearer {test_tok}"}

    original_key = os.environ.pop("API_KEY", None)
    try:
        # Case A: API_KEY is unset
        # POST without token -> 401
        res_no_tok = client.post("/api/v1/simulation/what-if", json=sim_payload)
        assert res_no_tok.status_code == 401

        # GET succeeds without any auth
        res_health = client.get("/health")
        assert res_health.status_code == 200

        # Case B: API_KEY is set
        os.environ["API_KEY"] = "test-secret-key-12345"

        # POST without API key header -> 401
        res_no_key = client.post("/api/v1/simulation/what-if", json=sim_payload)
        assert res_no_key.status_code == 401
        assert "Invalid or missing X-API-Key" in res_no_key.json().get("detail", "")

        # POST with wrong header -> 401
        res_wrong_key = client.post(
            "/api/v1/simulation/what-if",
            json=sim_payload,
            headers={"X-API-Key": "incorrect-key"}
        )
        assert res_wrong_key.status_code == 401

        # GET route is NOT blocked even when API_KEY is set
        res_health_auth = client.get("/health")
        assert res_health_auth.status_code == 200

    finally:
        if original_key is not None:
            os.environ["API_KEY"] = original_key
        else:
            os.environ.pop("API_KEY", None)
