"""
Unit test fixtures: forces in-memory fallback for auth and meta endpoints.
Guarantees unit tests never touch live Redis or live PostgreSQL.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True)
def force_offline_unit():
    """Forces in-memory auth fallback and mocks meta observability for all unit tests."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1,)

    @contextmanager
    def mock_db():
        yield mock_cur

    with patch("backend.app.core.auth.get_redis_client", return_value=None), \
         patch("backend.app.api.deps.get_redis_client", return_value=None), \
         patch("backend.app.api.routers.meta.get_redis_client", return_value=None), \
         patch("backend.app.api.routers.meta.get_db_cursor", side_effect=mock_db), \
         patch("backend.app.agent.guardrails.get_db_cursor", side_effect=mock_db):
        yield
