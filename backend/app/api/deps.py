"""
Shared dependencies and database helpers for API routers.
"""

from backend.app.core.db import get_db_cursor, get_redis_client

__all__ = ["get_db_cursor", "get_redis_client"]
