"""
Redis cache key builders, safe JSON get/set/invalidation helpers,
HTTP Cache-Control constants, and non-blocking startup cache warmer.
"""

import hashlib
import json
import logging
import threading
import time
from typing import Any, Optional, Sequence

from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor, get_redis_client

logger = logging.getLogger(__name__)

PUBLIC_CACHE_CONTROL = "public, max-age=300"

DISTRICTS_CACHE_KEY_PREFIX = "cache:compliance:scores"
SCORECARD_CACHE_KEY_PREFIX = "cache:compliance:scorecard"
REGIONS_STATS_CACHE_KEY_PREFIX = "cache:regions:stats"
REGIONS_LIST_CACHE_KEY_PREFIX = "cache:regions:list"
STANDARDS_CACHE_KEY_PREFIX = "cache:meta:standards"
AGENT_CACHE_KEY_PREFIX = "cache:agent"


def districts_cache_key(province_code: str) -> str:
    """Returns Redis key for a province's districts compliance list."""
    return f"{DISTRICTS_CACHE_KEY_PREFIX}:{str(province_code).strip()}"


def scorecard_cache_key(kemendagri_code: str) -> str:
    """Returns Redis key for a single kecamatan detailed scorecard."""
    return f"{SCORECARD_CACHE_KEY_PREFIX}:{str(kemendagri_code).strip()}"


def regions_stats_cache_key(db_name: str) -> str:
    """Returns Redis key for per-province DB coverage counts."""
    return f"{REGIONS_STATS_CACHE_KEY_PREFIX}:{str(db_name).strip()}"


def regions_list_cache_key(db_name: str, active_provinces: Sequence[str]) -> str:
    """Returns Redis key for /api/v1/regions scoped by DB name and active province list."""
    joined = ",".join(str(p).strip() for p in active_provinces if str(p).strip())
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    return f"{REGIONS_LIST_CACHE_KEY_PREFIX}:{str(db_name).strip()}:{digest}"


def standards_cache_key(db_name: str) -> str:
    """Returns Redis key for /api/v1/meta/standards scoped by DB name."""
    return f"{STANDARDS_CACHE_KEY_PREFIX}:{str(db_name).strip()}"


def cache_get_json(redis_client: Any, key: str) -> Optional[Any]:
    """Safely fetches and parses JSON from Redis, returning None on miss or error."""
    if not redis_client or not key:
        return None
    try:
        raw = redis_client.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.debug("Redis cache_get_json failed for %s: %s", key, exc)
        return None


def cache_set_json(
    redis_client: Any,
    key: str,
    value: Any,
    ttl: Optional[int] = None,
) -> bool:
    """Safely serializes JSON into Redis with EX TTL, returning False on error."""
    if not redis_client or not key:
        return False
    effective_ttl = int(ttl if ttl is not None else settings.REDIS_CACHE_TTL)
    try:
        redis_client.setex(key, effective_ttl, json.dumps(value, default=str))
        return True
    except Exception as exc:
        logger.debug("Redis cache_set_json failed for %s: %s", key, exc)
        return False


def _delete_by_pattern(redis_client: Any, pattern: str) -> int:
    if not redis_client:
        return 0
    try:
        keys = list(redis_client.scan_iter(match=pattern, count=200))
        if keys:
            return int(redis_client.delete(*keys) or 0)
    except Exception as exc:
        logger.debug("Redis pattern delete failed for %s: %s", pattern, exc)
    return 0


def invalidate_compliance_cache(
    redis_client: Any,
    province_code: Optional[str] = None,
) -> int:
    """Invalidates district list / scorecard caches (one province or all)."""
    if not redis_client:
        return 0
    if province_code:
        prov = str(province_code).strip()
        deleted = 0
        try:
            keys_to_del = [districts_cache_key(prov)]
            if prov == settings.DEFAULT_PROVINCE_CODE:
                keys_to_del.append(DISTRICTS_CACHE_KEY_PREFIX)
            deleted += int(redis_client.delete(*keys_to_del) or 0)
        except Exception:
            pass
        deleted += _delete_by_pattern(redis_client, f"{SCORECARD_CACHE_KEY_PREFIX}:{prov}.*")
        return deleted

    return (
        _delete_by_pattern(redis_client, f"{DISTRICTS_CACHE_KEY_PREFIX}*")
        + _delete_by_pattern(redis_client, f"{SCORECARD_CACHE_KEY_PREFIX}:*")
    )


def invalidate_regions_cache(
    redis_client: Any,
    db_name: Optional[str] = None,
) -> int:
    """Invalidates cached region stats and region catalogue entries."""
    if not redis_client:
        return 0
    if db_name:
        deleted = 0
        try:
            deleted += int(redis_client.delete(regions_stats_cache_key(db_name)) or 0)
        except Exception:
            pass
        deleted += _delete_by_pattern(
            redis_client, f"{REGIONS_LIST_CACHE_KEY_PREFIX}:{str(db_name).strip()}:*"
        )
        return deleted

    return (
        _delete_by_pattern(redis_client, f"{REGIONS_STATS_CACHE_KEY_PREFIX}:*")
        + _delete_by_pattern(redis_client, f"{REGIONS_LIST_CACHE_KEY_PREFIX}:*")
    )


def invalidate_standards_cache(
    redis_client: Any,
    db_name: Optional[str] = None,
) -> int:
    """Invalidates cached /api/v1/meta/standards entries."""
    if not redis_client:
        return 0
    if db_name:
        try:
            return int(redis_client.delete(standards_cache_key(db_name)) or 0)
        except Exception:
            return 0
    return _delete_by_pattern(redis_client, f"{STANDARDS_CACHE_KEY_PREFIX}:*")


def invalidate_agent_cache(redis_client: Any) -> int:
    """Invalidates cached agent summary entries (`cache:agent:*`)."""
    return _delete_by_pattern(redis_client, f"{AGENT_CACHE_KEY_PREFIX}:*")


def invalidate_pipeline_caches(redis_client: Any, province_code: str) -> int:
    """
    Deletes stale Redis keys after a pipeline load/rescore so the backend rebuilds
    them in its canonical payload shape.
    """
    if not redis_client:
        return 0
    prov = str(province_code).strip()
    deleted = invalidate_compliance_cache(redis_client, prov)
    deleted += _delete_by_pattern(redis_client, "cache:regions:*")
    deleted += invalidate_agent_cache(redis_client)
    return deleted


def warm_startup_caches(cancel_event: Optional[threading.Event] = None) -> dict:
    """
    Warms Redis caches at startup for meta/standards, regions, and every active province
    (district list + scorecards of scored kecamatan).
    Safe if Redis or PostgreSQL is unavailable; respects cancel_event for clean shutdown.
    """
    t0 = time.perf_counter()
    summary = {
        "status": "skipped",
        "provinces": 0,
        "lists_warmed": 0,
        "scorecards_warmed": 0,
    }

    r_client = get_redis_client()
    if not r_client:
        logger.info("Startup cache warmup skipped: Redis client not initialized.")
        return summary

    try:
        if not r_client.ping():
            logger.warning("Startup cache warmup skipped: Redis ping returned falsy.")
            return summary
    except Exception as exc:
        logger.warning("Startup cache warmup skipped: Redis unreachable (%s).", exc)
        return summary

    ttl = int(settings.REDIS_CACHE_TTL)
    db_name = settings.POSTGRES_DB
    active_provs = list(settings.active_provinces)

    try:
        from backend.app.api.routers.districts import (
            build_district_detail_payload,
            fetch_province_districts_rows,
        )
        from backend.app.api.routers.meta import fetch_regulatory_standards_rows
        from backend.app.api.routers.regions import build_regions_payload

        # 1. Warm regulatory standards
        std_key = standards_cache_key(db_name)
        if not cancel_event or not cancel_event.is_set():
            if not r_client.exists(std_key):
                stds = fetch_regulatory_standards_rows()
                if stds:
                    cache_set_json(r_client, std_key, stds, ttl=ttl)

        # 2. Warm regions catalogue
        if not cancel_event or not cancel_event.is_set():
            reg_key = regions_list_cache_key(db_name, active_provs)
            if not r_client.exists(reg_key):
                reg_payload = build_regions_payload()
                if reg_payload:
                    cache_set_json(r_client, reg_key, reg_payload, ttl=ttl)

        # 3. Warm district lists + scored kecamatan scorecards per active province
        for prov in active_provs:
            if cancel_event and cancel_event.is_set():
                summary["status"] = "cancelled"
                return summary

            summary["provinces"] += 1
            list_key = districts_cache_key(prov)
            if not r_client.exists(list_key):
                rows = fetch_province_districts_rows(prov)
                if rows:
                    if cache_set_json(r_client, list_key, rows, ttl=ttl):
                        summary["lists_warmed"] += 1
                        if prov == settings.DEFAULT_PROVINCE_CODE:
                            cache_set_json(r_client, DISTRICTS_CACHE_KEY_PREFIX, rows, ttl=ttl)

            with get_db_cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        k.id, k.kemendagri_code, k.bps_code, k.name, c.name as city_name,
                        p.kemendagri_code as province_code, p.name as province_name,
                        k.population, k.area_km2, k.density_per_km2,
                        k.population_source, k.population_verification_status,
                        s.health_score, s.education_score, s.livability_score,
                        s.mobility_score, s.composite_livability_score, s.composite_note,
                        s.metrics_payload, s.coverage,
                        ST_AsGeoJSON(k.boundary)::json as boundary_geojson
                    FROM kecamatan k
                    JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                    JOIN provinces p ON p.id = c.province_id
                    JOIN district_compliance_scores s ON s.district_id = k.id
                    WHERE p.kemendagri_code = %s
                      AND s.composite_livability_score IS NOT NULL
                    ORDER BY k.kemendagri_code;
                    """,
                    (prov,),
                )
                scored_rows = cur.fetchall()

            if scored_rows:
                codes = [str(r["kemendagri_code"]) for r in scored_rows if r.get("kemendagri_code")]
                keys = [scorecard_cache_key(c) for c in codes]
                existing = r_client.mget(keys) if keys else []
                pipe = r_client.pipeline()
                to_write = 0
                for r, ex_val in zip(scored_rows, existing):
                    if ex_val is not None:
                        continue
                    payload = build_district_detail_payload(dict(r))
                    k_code = payload.get("kemendagri_code")
                    if k_code:
                        pipe.setex(
                            scorecard_cache_key(k_code),
                            ttl,
                            json.dumps(payload, default=str),
                        )
                        to_write += 1
                if to_write > 0:
                    pipe.execute()
                    summary["scorecards_warmed"] += to_write

        summary["status"] = "completed"
        elapsed = time.perf_counter() - t0
        logger.info(
            "Startup cache warmup completed in %.2fs: provinces=%d lists_warmed=%d scorecards_warmed=%d",
            elapsed,
            summary["provinces"],
            summary["lists_warmed"],
            summary["scorecards_warmed"],
        )
    except Exception as exc:
        summary["status"] = "error"
        logger.warning("Startup cache warmup aborted safely: %s", exc)

    return summary
