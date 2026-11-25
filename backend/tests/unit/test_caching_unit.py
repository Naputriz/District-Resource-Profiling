"""
Unit tests for U3 caching helpers, Cache-Control headers, startup warmer resilience,
and static asset configuration (_headers, .assetsignore, modulepreload, APP_VERSION).
Marker: unit.
"""

import json
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core import cache as cache_mod
from backend.app.core.config import settings
from backend.app.main import app

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_cache_key_builders_and_safe_json_helpers():
    """Key builders include scope and cache_get/set/invalidate handle errors gracefully."""
    assert cache_mod.districts_cache_key(" 32 ") == "cache:compliance:scores:32"
    assert cache_mod.scorecard_cache_key("31.71.09") == "cache:compliance:scorecard:31.71.09"
    assert cache_mod.regions_stats_cache_key("district_profiling_stage") == "cache:regions:stats:district_profiling_stage"
    assert cache_mod.standards_cache_key("district_profiling_stage") == "cache:meta:standards:district_profiling_stage"

    k1 = cache_mod.regions_list_cache_key("db_a", ["31", "32"])
    k2 = cache_mod.regions_list_cache_key("db_a", ["31"])
    assert k1 != k2 and k1.startswith("cache:regions:list:db_a:")

    # None client is safe
    assert cache_mod.cache_get_json(None, "x") is None
    assert cache_mod.cache_set_json(None, "x", {"a": 1}) is False
    assert cache_mod.invalidate_compliance_cache(None, "31") == 0
    assert cache_mod.invalidate_regions_cache(None, "db_a") == 0
    assert cache_mod.invalidate_standards_cache(None, "db_a") == 0

    # Mock client roundtrip and exception resilience
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"ok": True})
    assert cache_mod.cache_get_json(fake_redis, "k") == {"ok": True}
    assert cache_mod.cache_set_json(fake_redis, "k", {"ok": True}, ttl=600) is True
    fake_redis.setex.assert_called_once()
    assert fake_redis.setex.call_args[0][1] == 600

    fake_redis.get.side_effect = RuntimeError("Redis down")
    fake_redis.setex.side_effect = RuntimeError("Redis down")
    assert cache_mod.cache_get_json(fake_redis, "k") is None
    assert cache_mod.cache_set_json(fake_redis, "k", {"a": 1}) is False


def test_warm_startup_caches_safe_when_redis_down():
    """warm_startup_caches exits safely without raising when Redis is unreachable."""
    with patch("backend.app.core.cache.get_redis_client", return_value=None):
        res = cache_mod.warm_startup_caches()
        assert res["status"] == "skipped"

    broken_redis = MagicMock()
    broken_redis.ping.side_effect = ConnectionError("Redis refused")
    with patch("backend.app.core.cache.get_redis_client", return_value=broken_redis):
        res = cache_mod.warm_startup_caches()
        assert res["status"] == "skipped"


def test_warm_startup_caches_warms_lists_and_scored_scorecards(monkeypatch):
    """warm_startup_caches caches lists + scored kecamatan scorecards and honors cancel_event."""
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")

    store = {}
    fake_pipe = MagicMock()
    fake_pipe.setex.side_effect = lambda k, ttl, val: store.__setitem__(k, val)
    fake_pipe.execute.return_value = [True]

    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    fake_redis.exists.side_effect = lambda k: 1 if k in store else 0
    fake_redis.setex.side_effect = lambda k, ttl, val: store.__setitem__(k, val)
    fake_redis.mget.side_effect = lambda keys: [store.get(k) for k in keys]
    fake_redis.pipeline.return_value = fake_pipe

    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        {
            "id": "uuid-1",
            "kemendagri_code": "31.71.09",
            "bps_code": "3171090",
            "name": "Tebet",
            "city_name": "Jakarta Selatan",
            "province_code": "31",
            "province_name": "DKI Jakarta",
            "population": 225000,
            "area_km2": 9.0,
            "density_per_km2": 25000.0,
            "population_source": "BPS 2024",
            "population_verification_status": "bps_2024",
            "health_score": 70.0,
            "education_score": 60.0,
            "livability_score": None,
            "mobility_score": None,
            "composite_livability_score": 65.45,
            "composite_note": "Note",
            "metrics_payload": [],
            "coverage": {"osm_coverage": {"status": "memadai", "mapped_sd": 10, "required_sd": 10}},
            "boundary_geojson": {"type": "Polygon", "coordinates": []},
        }
    ]

    @contextmanager
    def fake_db():
        yield mock_cur

    with patch("backend.app.core.cache.get_redis_client", return_value=fake_redis), \
         patch("backend.app.core.cache.get_db_cursor", side_effect=fake_db), \
         patch("backend.app.api.routers.meta.fetch_regulatory_standards_rows", return_value=[{"facility_type": "sd"}]), \
         patch("backend.app.api.routers.regions.build_regions_payload", return_value=[{"province_code": "31"}]), \
         patch("backend.app.api.routers.districts.fetch_province_districts_rows", return_value=[{"kemendagri_code": "31.71.09"}]):
        summary = cache_mod.warm_startup_caches(threading.Event())

    assert summary["status"] == "completed"
    assert summary["lists_warmed"] == 1
    assert summary["scorecards_warmed"] == 1
    assert cache_mod.districts_cache_key("31") in store
    assert cache_mod.scorecard_cache_key("31.71.09") in store

    # Pre-cancelled event exits early
    cancel = threading.Event()
    cancel.set()
    with patch("backend.app.core.cache.get_redis_client", return_value=fake_redis):
        cancelled = cache_mod.warm_startup_caches(cancel)
        assert cancelled["status"] == "cancelled"


def test_public_get_cache_control_headers_and_static_asset_files():
    """Public GETs emit Cache-Control: public, max-age=300 while health/auth/static rules match spec."""
    client = TestClient(app)

    res_regions = client.get("/api/v1/regions")
    assert res_regions.status_code == 200
    assert res_regions.headers.get("Cache-Control") == "public, max-age=300"

    res_meta = client.get("/api/v1/meta/standards")
    assert res_meta.status_code == 200
    assert res_meta.headers.get("Cache-Control") == "public, max-age=300"

    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert "max-age=300" not in (res_health.headers.get("Cache-Control") or "")

    res_auth = client.get("/api/v1/auth/me")
    assert res_auth.status_code == 401
    assert "max-age=300" not in (res_auth.headers.get("Cache-Control") or "")

    # Static assets served with proper Cache-Control and _headers hidden
    assert client.get("/_headers").status_code == 404
    assert client.get("/.assetsignore").status_code == 404
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert res_index.headers.get("Cache-Control") == "no-cache"

    res_js = client.get("/js/config.js")
    assert res_js.status_code == 200
    assert res_js.headers.get("Cache-Control") == "no-cache"

    res_css = client.get("/css/style.css")
    assert res_css.status_code == 200
    assert res_css.headers.get("Cache-Control") == "public, max-age=300"

    # Verify frontend/_headers and .assetsignore
    headers_text = (REPO_ROOT / "frontend" / "_headers").read_text(encoding="utf-8")
    assert "/\n  Cache-Control: no-cache" in headers_text
    assert "/index.html\n  Cache-Control: no-cache" in headers_text
    assert "/js/*\n  Cache-Control: no-cache" in headers_text
    assert "/css/*\n  Cache-Control: public, max-age=300" in headers_text
    assert "/data/boundaries/*\n  Cache-Control: public, max-age=86400, stale-while-revalidate=604800" in headers_text

    ignore_lines = {
        line.strip()
        for line in (REPO_ROOT / "frontend" / ".assetsignore").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "_headers" in ignore_lines
    assert "js/README.md" in ignore_lines

    # Verify modulepreload covers the entire frontend/js module graph & APP_VERSION matches index.html
    config_text = (REPO_ROOT / "frontend" / "js" / "config.js").read_text(encoding="utf-8")
    m_ver = re.search(r'export const APP_VERSION = "([^"]+)"', config_text)
    assert m_ver, "APP_VERSION missing in frontend/js/config.js"
    app_ver = m_ver.group(1)

    index_html = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert f'/css/style.css?v={app_ver}' in index_html
    assert f'/css/regions.css?v={app_ver}' in index_html
    assert f'/js/main.js?v={app_ver}' in index_html

    preloads = set(re.findall(r'<link rel="modulepreload" href="([^"?]+)', index_html))
    js_root = REPO_ROOT / "frontend" / "js"
    actual_modules = {
        "/js/" + str(p.relative_to(js_root)).replace(os.sep, "/")
        for p in js_root.rglob("*.js")
    }
    assert actual_modules.issubset(preloads), f"Missing modulepreload for: {actual_modules - preloads}"


def test_pipeline_cache_invalidation_deletes_stale_keys_without_writing():
    """Pipeline cache invalidation deletes stale compliance/regions/agent keys and never writes old dicts."""
    import fnmatch
    from pipeline.boundary_loader import DistrictDataIngestionPipeline
    from pipeline.load_region import invalidate_redis_cache_for_province

    class FakeRedis:
        def __init__(self, initial_keys):
            self.store = {k: "cached" for k in initial_keys}
            self.writes = []

        def ping(self):
            return True

        def scan_iter(self, match=None, count=None):
            pat = match or "*"
            return [k for k in list(self.store.keys()) if fnmatch.fnmatchcase(k, pat)]

        def delete(self, *keys):
            removed = 0
            for k in keys:
                if k in self.store:
                    del self.store[k]
                    removed += 1
            return removed

        def set(self, *args, **kwargs):
            self.writes.append(("set", args, kwargs))
            return True

        def setex(self, *args, **kwargs):
            self.writes.append(("setex", args, kwargs))
            return True

    # 1. load_region invalidation for province 32 keeps province 31 + legacy + meta intact
    fake_load = FakeRedis([
        "cache:compliance:scores:32",
        "cache:compliance:scores:31",
        "cache:compliance:scores",
        "cache:compliance:scorecard:32.73.230",
        "cache:compliance:scorecard:31.71.09",
        "cache:regions:stats:district_profiling_stage",
        "cache:regions:list:district_profiling_stage:abc123",
        "cache:agent:national:overview",
        "cache:meta:standards:district_profiling_stage",
    ])
    deleted_32 = invalidate_redis_cache_for_province(fake_load, "32", redis_db=1)
    assert deleted_32 == 5
    assert fake_load.writes == []
    assert set(fake_load.store.keys()) == {
        "cache:compliance:scores:31",
        "cache:compliance:scores",
        "cache:compliance:scorecard:31.71.09",
        "cache:meta:standards:district_profiling_stage",
    }

    # 2. boundary_loader invalidation for default province 31 also removes legacy cache:compliance:scores
    fake_boundary = FakeRedis([
        "cache:compliance:scores:31",
        "cache:compliance:scores",
        "cache:compliance:scorecard:31.71.09",
        "cache:compliance:scorecard:32.73.230",
        "cache:regions:stats:district_profiling",
        "cache:regions:list:district_profiling:xyz",
        "cache:agent:summary:31",
    ])
    with patch.object(DistrictDataIngestionPipeline, "_init_redis", return_value=None):
        pipeline_obj = DistrictDataIngestionPipeline(province_code="31")
    pipeline_obj.redis_client = fake_boundary
    deleted_31 = pipeline_obj.sync_to_redis_cache()
    assert deleted_31 == 6
    assert fake_boundary.writes == []
    assert set(fake_boundary.store.keys()) == {"cache:compliance:scorecard:32.73.230"}
