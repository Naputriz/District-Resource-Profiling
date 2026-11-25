"""
Integration tests for U3 Redis caching (districts list, scorecard, regions, meta/standards)
and startup cache warmer against PostgreSQL + Redis.
Marker: db.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.app.core import cache as cache_mod
from backend.app.core.config import settings
from backend.app.core.db import get_redis_client, init_db_pool
from backend.app.api.routers.regions import clear_regions_cache
from backend.app.main import app

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]


def test_districts_list_and_detail_second_call_hits_redis(monkeypatch):
    """Second districts-list and district-detail calls hit Redis without querying PostgreSQL."""
    init_db_pool()
    r_client = get_redis_client()
    if not r_client or not r_client.ping():
        pytest.skip("Redis is unavailable")

    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")
    clear_regions_cache()
    cache_mod.invalidate_compliance_cache(r_client, "31")
    cache_mod.invalidate_standards_cache(r_client, settings.POSTGRES_DB)

    client = TestClient(app)

    # 1. Districts list: first call DB -> populates Redis; second call hits Redis
    res1 = client.get("/api/v1/districts?province_code=31")
    assert res1.status_code == 200
    assert res1.headers.get("Cache-Control") == "public, max-age=300"
    body1 = res1.json()
    assert body1["source"] == "database"
    assert len(body1["districts"]) == 44
    assert r_client.exists(cache_mod.districts_cache_key("31")) == 1
    assert r_client.ttl(cache_mod.districts_cache_key("31")) > 0

    with patch(
        "backend.app.api.routers.districts.fetch_province_districts_rows",
        side_effect=AssertionError("DB must not be queried on Redis hit"),
    ):
        res2 = client.get("/api/v1/districts?province_code=31")
        assert res2.status_code == 200
        assert res2.headers.get("Cache-Control") == "public, max-age=300"
        body2 = res2.json()
        assert body2["source"] == "cache"
        assert len(body2["districts"]) == 44

    # 2. District detail scorecard: first call populates Redis; second call hits Redis
    d1 = client.get("/api/v1/districts/31.71.09")
    assert d1.status_code == 200
    assert d1.headers.get("Cache-Control") == "public, max-age=300"
    assert r_client.exists(cache_mod.scorecard_cache_key("31.71.09")) == 1

    with patch(
        "backend.app.api.routers.districts.get_db_cursor",
        side_effect=AssertionError("DB must not be queried on scorecard Redis hit"),
    ):
        d2 = client.get("/api/v1/districts/31.71.09")
        assert d2.status_code == 200
        assert d2.json()["kemendagri_code"] == "31.71.09"

    # 3. Regions & meta/standards populate Redis and return public Cache-Control
    reg1 = client.get("/api/v1/regions")
    assert reg1.status_code == 200
    assert reg1.headers.get("Cache-Control") == "public, max-age=300"
    assert r_client.exists(cache_mod.regions_list_cache_key(settings.POSTGRES_DB, ["31"])) == 1

    meta1 = client.get("/api/v1/meta/standards")
    assert meta1.status_code == 200
    assert meta1.headers.get("Cache-Control") == "public, max-age=300"
    assert r_client.exists(cache_mod.standards_cache_key(settings.POSTGRES_DB)) == 1


def test_startup_warmer_populates_dki_list_and_scored_scorecards(monkeypatch):
    """warm_startup_caches warms province list and scored kecamatan scorecards in Redis."""
    init_db_pool()
    r_client = get_redis_client()
    if not r_client or not r_client.ping():
        pytest.skip("Redis is unavailable")

    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")
    clear_regions_cache()
    cache_mod.invalidate_compliance_cache(r_client, "31")
    cache_mod.invalidate_standards_cache(r_client, settings.POSTGRES_DB)

    summary = cache_mod.warm_startup_caches()
    assert summary["status"] == "completed"
    assert summary["lists_warmed"] == 1
    assert summary["scorecards_warmed"] == 44
    assert r_client.exists(cache_mod.districts_cache_key("31")) == 1
    assert r_client.exists(cache_mod.scorecard_cache_key("31.71.09")) == 1
