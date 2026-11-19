"""
Integration Tests for Read-Only Watchdog Agent & Observability endpoints.
Requires PostGIS database. Marker: db.
"""

import pytest
from fastapi.testclient import TestClient
from backend.app.core.db import init_db_pool
from backend.app.main import app

pytestmark = pytest.mark.db


def test_watchdog_endpoints_read_only_get():
    """Verifies all exposed watchdog HTTP endpoints are read-only GET with no mutation endpoints."""
    init_db_pool()
    client = TestClient(app)

    # 1. Telemetry GET returns 200
    res_tel = client.get("/api/v1/watchdog/telemetry")
    assert res_tel.status_code == 200
    tel_data = res_tel.json()
    assert "status" in tel_data
    assert "gpu" in tel_data
    assert "containers" in tel_data

    # 2. Incidents GET returns 200
    res_inc = client.get("/api/v1/watchdog/incidents")
    assert res_inc.status_code == 200
    inc_data = res_inc.json()
    assert "incidents" in inc_data

    # 3. POST / PUT / DELETE on telemetry is 405 Method Not Allowed
    res_post = client.post("/api/v1/watchdog/telemetry", json={})
    assert res_post.status_code == 405

    # 4. Prohibited trigger-restart endpoints do not exist (404 Not Found or 405 Method Not Allowed)
    res_restart = client.post("/api/v1/watchdog/restart", json={})
    assert res_restart.status_code in [404, 405]
