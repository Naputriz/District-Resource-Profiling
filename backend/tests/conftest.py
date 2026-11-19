"""
Shared pytest fixtures for District Resource Profiling test suite.
Provides TestClient, DB cursor, auth tokens, and conditional skips for services.
"""

import os
import sys
import uuid
import pytest
from typing import Generator, Dict, Any

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor, init_db_pool, close_db_pool
from backend.app.core.auth import create_access_token, hash_password


@pytest.fixture(scope="session", autouse=True)
def isolate_chat_log_file(tmp_path_factory):
    """Ensure tests never create chat_log.jsonl inside the repository."""
    log_dir = tmp_path_factory.mktemp("drp_test_chat_logs")
    log_path = str(log_dir / "chat_log.jsonl")
    orig_setting = settings.CHAT_LOG_FILE_PATH
    orig_env = os.environ.get("CHAT_LOG_FILE_PATH")
    settings.CHAT_LOG_FILE_PATH = log_path
    os.environ["CHAT_LOG_FILE_PATH"] = log_path
    try:
        yield log_path
    finally:
        settings.CHAT_LOG_FILE_PATH = orig_setting
        if orig_env is None:
            os.environ.pop("CHAT_LOG_FILE_PATH", None)
        else:
            os.environ["CHAT_LOG_FILE_PATH"] = orig_env


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """Shared FastAPI TestClient."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def db_available() -> bool:
    """Checks whether PostGIS database is reachable."""
    try:
        init_db_pool()
        with get_db_cursor() as cur:
            cur.execute("SELECT 1;")
            row = cur.fetchone()
            return row is not None
    except Exception:
        return False


@pytest.fixture
def db_cursor(db_available: bool) -> Generator[Any, None, None]:
    """Yields a database cursor, skipping the test if DB is unavailable."""
    if not db_available:
        pytest.skip("PostGIS database service is unavailable (localhost:5432)")
    with get_db_cursor() as cur:
        yield cur


@pytest.fixture
def requires_seed(db_available: bool) -> None:
    """
    Skips test if master data tables (public_facilities) are unseeded.
    Allows data-dependent tests to skip gracefully in minimal CI environments.
    """
    if not db_available:
        pytest.skip("PostGIS database service is unavailable (localhost:5432)")
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM public_facilities WHERE is_active = TRUE;")
        row = cur.fetchone()
        if not row or row["count"] == 0:
            pytest.skip("Test requires seeded master data (public_facilities is empty; local-only)")


@pytest.fixture(scope="session")
def auth_headers(db_available: bool) -> Generator[Dict[str, str], None, None]:
    """Generates a valid Bearer token for an authenticated user with cleanup in teardown."""
    test_user_id = str(uuid.uuid4())
    test_email = f"test_fixture_{test_user_id[:8]}@drp.local"
    if db_available:
        try:
            with get_db_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_users (id, email, password_hash, display_name, role)
                    VALUES (%s, %s, %s, %s, 'user')
                    ON CONFLICT (email) DO UPDATE SET display_name = EXCLUDED.display_name;
                    """,
                    (
                        test_user_id,
                        test_email,
                        hash_password("FixturePass123!"),
                        "Fixture User",
                    ),
                )
        except Exception:
            pass

    token = create_access_token({
        "sub": test_user_id,
        "email": test_email,
        "role": "user",
    })
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        if db_available:
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


@pytest.fixture(scope="session")
def service_auth_headers() -> Dict[str, str]:
    """Generates a service principal Bearer token."""
    token = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000000",
        "email": "service@drp.local",
        "role": "admin",
        "is_service": True,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def redis_available() -> bool:
    """Checks whether Redis cache is reachable."""
    try:
        from backend.app.core.db import get_redis_client
        r = get_redis_client()
        return bool(r and r.ping())
    except Exception:
        return False


@pytest.fixture(scope="session")
def ollama_available() -> bool:
    """Checks whether Ollama LLM endpoint is reachable."""
    import urllib.request
    try:
        url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False
