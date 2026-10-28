"""
Database and Cache Connection Manager for District Resource Profiling.
Uses psycopg2 ThreadedConnectionPool for reliable PostGIS execution and Redis 7 client.
"""

from contextlib import contextmanager
from typing import Optional
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import redis
from backend.app.core.config import settings

db_pool: Optional[pool.ThreadedConnectionPool] = None
redis_client: Optional[redis.Redis] = None

def init_db_pool():
    global db_pool, redis_client
    db_host = settings.POSTGRES_HOST
    if not db_host or db_host == "localhost":
        db_host = "127.0.0.1"

    db_pool = pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=20,
        host=db_host,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
        cursor_factory=RealDictCursor
    )

    r_host = settings.REDIS_HOST
    if not r_host or r_host == "localhost":
        r_host = "127.0.0.1"

    redis_client = redis.Redis(
        host=r_host,
        port=settings.REDIS_PORT,
        decode_responses=True
    )

def get_redis_client() -> Optional[redis.Redis]:
    global redis_client
    return redis_client

def close_db_pool():
    global db_pool, redis_client
    if db_pool:
        db_pool.closeall()
    if redis_client:
        redis_client.close()

@contextmanager
def get_db_cursor():
    """Yields a database cursor from the connection pool and returns connection upon exit."""
    global db_pool
    if db_pool is None:
        init_db_pool()
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db_pool.putconn(conn)
