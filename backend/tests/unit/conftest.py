"""
Unit test fixtures: forces in-memory fallback for auth and meta endpoints.
Guarantees unit tests never touch live Redis or live PostgreSQL.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True)
def force_offline_unit(monkeypatch):
    """Forces in-memory auth fallback and mocks meta/regions DB access for all unit tests."""
    from backend.app.core.config import settings
    from backend.app.api.routers.regions import clear_regions_cache
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")
    clear_regions_cache()

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1,)

    regions_cur = MagicMock()
    regions_cur.fetchall.return_value = [
        {"province_code": "31", "total_kec": 44, "scored_kec": 44, "gated_kec": 0}
    ]

    @contextmanager
    def mock_db():
        yield mock_cur

    @contextmanager
    def mock_regions_db():
        yield regions_cur

    with patch("backend.app.core.auth.get_redis_client", return_value=None), \
         patch("backend.app.api.deps.get_redis_client", return_value=None), \
         patch("backend.app.core.cache.get_redis_client", return_value=None), \
         patch("backend.app.api.routers.districts.get_redis_client", return_value=None), \
         patch("backend.app.api.routers.regions.get_redis_client", return_value=None), \
         patch("backend.app.api.routers.meta.get_redis_client", return_value=None), \
         patch("backend.app.api.routers.meta.get_db_cursor", side_effect=mock_db), \
         patch("backend.app.api.routers.regions.get_db_cursor", side_effect=mock_regions_db), \
         patch("backend.app.agent.guardrails.get_db_cursor", side_effect=mock_db):
        yield
    clear_regions_cache()
