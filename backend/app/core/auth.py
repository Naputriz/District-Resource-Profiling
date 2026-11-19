"""
Authentication, Password Hashing, JWT Tokens, Brute-Force & Rate Limiting.
Enforces TODO-4 requirements:
- bcrypt password hashing with min length 10
- PyJWT HS256 token creation and verification
- Per-email & per-IP failed login brute-force tracking (Redis with in-memory fallback)
- Per-user chat rate limiter (Redis with in-memory fallback)
- Chat audit logging (privacy preserving: no raw question text)
"""

import hmac
import ipaddress
import json
import os
import threading
import time
import logging
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from typing import Optional, Tuple, Dict, List
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt

from backend.app.core.config import settings, _resolve_default_chat_log_file_path
from backend.app.core.db import get_redis_client, get_db_cursor

logger = logging.getLogger(__name__)

# In-memory fallbacks when Redis is not available
_in_memory_failed_attempts: Dict[str, List[float]] = {}
_in_memory_rate_limits: Dict[str, List[float]] = {}

# Dummy bcrypt hash to equalize timing for non-existent users
_DUMMY_BCRYPT_HASH = bcrypt.hashpw(
    b"dummy-timing-equalizer-password", bcrypt.gensalt()
).decode("utf-8")


def _get_header(request, name: str) -> Optional[str]:
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    val = headers.get(name)
    if isinstance(val, str):
        return val
    if isinstance(headers, dict):
        target = name.lower()
        for k, v in headers.items():
            if isinstance(k, str) and k.lower() == target and isinstance(v, str):
                return v
    return None


def _parse_ip(raw: Optional[str]) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except (ValueError, TypeError):
        return None


def get_client_ip(request) -> str:
    """
    Resolve the real client IP behind Cloudflare Worker + Tunnel.

    Precedence:
    1. Validated edge header: X-DRP-Edge-Secret matches non-empty
       settings.EDGE_SHARED_SECRET (constant-time) and X-DRP-Client-IP is a valid IP.
    2. Cloudflare edge header: CF-Connecting-IP is a valid IP.
    3. Direct peer address: request.client.host, falling back to "127.0.0.1".

    X-Forwarded-For is never trusted. Invalid header values fall through safely.
    """
    secret = getattr(settings, "EDGE_SHARED_SECRET", "")
    if isinstance(secret, str) and secret:
        provided = _get_header(request, "X-DRP-Edge-Secret")
        if provided and hmac.compare_digest(provided.encode("utf-8"), secret.encode("utf-8")):
            edge_ip = _parse_ip(_get_header(request, "X-DRP-Client-IP"))
            if edge_ip:
                return edge_ip

    cf_ip = _parse_ip(_get_header(request, "CF-Connecting-IP"))
    if cf_ip:
        return cf_ip

    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    if isinstance(host, str) and host.strip():
        return host.strip()
    return "127.0.0.1"


def hash_password(password: str) -> str:
    """Hashes a password with bcrypt after validating minimum and maximum length."""
    if not password or len(password) < settings.AUTH_PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Kata sandi minimal {settings.AUTH_PASSWORD_MIN_LENGTH} karakter."
        )
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Kata sandi maksimal 72 byte UTF-8.")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against a bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    if len(plain_password.encode("utf-8")) > 72:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(
    data: dict, expires_delta: Optional[timedelta] = None
) -> str:
    """Encodes JWT access token with expiration and issue timestamp."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.AUTH_JWT_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(
        to_encode,
        settings.AUTH_JWT_SECRET,
        algorithm=settings.AUTH_JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    """Decodes and validates a JWT token. Raises ValueError on failure."""
    try:
        return jwt.decode(
            token,
            settings.AUTH_JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("Token telah kedaluwarsa.")
    except jwt.InvalidTokenError:
        raise ValueError("Token tidak valid.")


def _clean_in_memory_window(key: str, store: Dict[str, List[float]], window_seconds: int) -> List[float]:
    now = time.time()
    cutoff = now - window_seconds
    timestamps = [t for t in store.get(key, []) if t > cutoff]
    store[key] = timestamps
    return timestamps


def is_brute_force_locked(email: str, client_ip: str) -> bool:
    """
    Checks if email or client IP has exceeded failed login threshold.
    Returns True if locked out, False otherwise.
    """
    email_key = f"auth:failed:email:{email.lower().strip()}"
    ip_key = f"auth:failed:ip:{client_ip}"
    lockout_sec = settings.AUTH_BRUTE_FORCE_LOCKOUT_SECONDS
    max_attempts = settings.AUTH_BRUTE_FORCE_MAX_ATTEMPTS

    r = get_redis_client()
    if r:
        try:
            e_count = int(r.get(email_key) or 0)
            ip_count = int(r.get(ip_key) or 0)
            if e_count >= max_attempts or ip_count >= max_attempts:
                return True
            return False
        except Exception as e:
            logger.warning(
                "Redis error checking brute force counter: %s. Falling back to memory.", e
            )

    # In-memory fallback
    e_attempts = len(_clean_in_memory_window(email_key, _in_memory_failed_attempts, lockout_sec))
    ip_attempts = len(_clean_in_memory_window(ip_key, _in_memory_failed_attempts, lockout_sec))
    return e_attempts >= max_attempts or ip_attempts >= max_attempts


def record_failed_login(email: str, client_ip: str) -> None:
    """Increments failed login counter for email and IP."""
    email_key = f"auth:failed:email:{email.lower().strip()}"
    ip_key = f"auth:failed:ip:{client_ip}"
    lockout_sec = settings.AUTH_BRUTE_FORCE_LOCKOUT_SECONDS

    r = get_redis_client()
    if r:
        try:
            pipe = r.pipeline()
            pipe.incr(email_key)
            pipe.expire(email_key, lockout_sec)
            pipe.incr(ip_key)
            pipe.expire(ip_key, lockout_sec)
            pipe.execute()
            return
        except Exception as e:
            logger.warning(
                "Redis error recording failed login: %s. Falling back to memory.", e
            )

    now = time.time()
    for k in (email_key, ip_key):
        if k not in _in_memory_failed_attempts:
            _in_memory_failed_attempts[k] = []
        _in_memory_failed_attempts[k].append(now)


def reset_failed_login(email: str, client_ip: str) -> None:
    """Resets failed login counters upon successful authentication."""
    email_key = f"auth:failed:email:{email.lower().strip()}"
    ip_key = f"auth:failed:ip:{client_ip}"

    r = get_redis_client()
    if r:
        try:
            r.delete(email_key, ip_key)
        except Exception as e:
            logger.warning("Redis error resetting failed login counter: %s", e)

    _in_memory_failed_attempts.pop(email_key, None)
    _in_memory_failed_attempts.pop(ip_key, None)


def check_chat_rate_limit(user_id: str) -> Tuple[bool, int]:
    """
    Checks per-user rate limit for chat requests.
    Returns (is_allowed, remaining_requests).
    """
    limit_req = settings.AUTH_CHAT_RATE_LIMIT_REQUESTS
    window_sec = settings.AUTH_CHAT_RATE_LIMIT_WINDOW_SECONDS
    key = f"rate:chat:user:{user_id}"

    r = get_redis_client()
    if r:
        try:
            current = r.get(key)
            if current is None:
                pipe = r.pipeline()
                pipe.set(key, 1, ex=window_sec)
                pipe.execute()
                return True, limit_req - 1
            current_int = int(current)
            if current_int >= limit_req:
                return False, 0
            new_val = r.incr(key)
            return True, max(0, limit_req - new_val)
        except Exception as e:
            logger.warning(
                "Redis error checking rate limit: %s. Falling back to memory.", e
            )

    # In-memory fallback
    now = time.time()
    attempts = _clean_in_memory_window(key, _in_memory_rate_limits, window_sec)
    if len(attempts) >= limit_req:
        return False, 0
    _in_memory_rate_limits[key].append(now)
    return True, limit_req - len(_in_memory_rate_limits[key])


def record_chat_audit(
    user_id: Optional[str],
    question_length: int,
    tools_used: List[str],
    guardrail_status: Optional[str],
) -> None:
    """
    Records privacy-preserving chat telemetry into chat_audit.
    No question or prompt text is ever stored.
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_audit (user_id, question_length, tools_used, guardrail_status)
                VALUES (%s, %s, %s, %s);
                """,
                (user_id, question_length, tools_used, guardrail_status),
            )
    except Exception as e:
        logger.warning("Failed to record chat audit: %s", e)


CHAT_LOG_PROMPT_MAX_CHARS = 4000
CHAT_LOG_RESPONSE_MAX_CHARS = 20000

_chat_file_logger = logging.getLogger("drp.chat_log_file")
_chat_file_logger.setLevel(logging.INFO)
_chat_file_logger.propagate = False
_chat_file_logger_lock = threading.Lock()
_chat_file_handler_config: Optional[Tuple[str, int, int]] = None


class _ChatLogRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that ensures 0640 file permissions when supported."""

    def _open(self):
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, 0o640)
        except OSError:
            pass
        return stream


def _get_chat_file_logger(
    target_path: str, max_bytes: int, backup_count: int
) -> logging.Logger:
    global _chat_file_handler_config
    abs_path = os.path.abspath(target_path)
    desired_config = (abs_path, max_bytes, backup_count)

    with _chat_file_logger_lock:
        current_handler = (
            _chat_file_logger.handlers[0] if _chat_file_logger.handlers else None
        )
        needs_recreate = (
            current_handler is None
            or _chat_file_handler_config != desired_config
            or not os.path.exists(abs_path)
        )
        if needs_recreate:
            for h in list(_chat_file_logger.handlers):
                _chat_file_logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass

            parent_dir = os.path.dirname(abs_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            handler = _ChatLogRotatingFileHandler(
                abs_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            _chat_file_logger.addHandler(handler)
            _chat_file_handler_config = desired_config

    return _chat_file_logger


def _write_chat_log_file(entry: dict) -> None:
    if not settings.CHAT_LOG_FILE_ENABLED:
        return
    raw_path = (settings.CHAT_LOG_FILE_PATH or "").strip()
    if not raw_path:
        raw_path = _resolve_default_chat_log_file_path()
    max_bytes = max(1, int(float(settings.CHAT_LOG_FILE_MAX_MB) * 1024 * 1024))
    backup_count = max(0, int(settings.CHAT_LOG_FILE_BACKUPS))
    file_logger = _get_chat_file_logger(raw_path, max_bytes, backup_count)
    line = json.dumps(entry, ensure_ascii=False)
    with _chat_file_logger_lock:
        file_logger.info("%s", line)


def record_chat_log(
    user_id: Optional[str],
    province_code: Optional[str],
    prompt: str,
    response: str,
    tools_used: List[str],
    guardrail_status: Optional[str],
    latency_ms: Optional[int],
    model: Optional[str],
) -> None:
    """
    Records full chat turn (prompt + response) into chat_logs for authenticated users
    (pruning rows older than CHAT_LOG_RETENTION_DAYS) and appends one JSON line to
    CHAT_LOG_FILE_PATH when CHAT_LOG_FILE_ENABLED is true. Never raises on DB or file errors.
    """
    if not settings.CHAT_LOG_ENABLED:
        return
    if not user_id:
        return

    safe_prompt = (prompt or "")[:CHAT_LOG_PROMPT_MAX_CHARS]
    safe_response = (response or "")[:CHAT_LOG_RESPONSE_MAX_CHARS]
    raw_prov = str(province_code).strip() if province_code else ""
    safe_prov = raw_prov[:2] if raw_prov else None
    safe_guardrail = str(guardrail_status)[:50] if guardrail_status else None
    safe_model = str(model)[:100] if model else None
    safe_tools = [str(t) for t in (tools_used or []) if t]
    retention_days = max(0, int(settings.CHAT_LOG_RETENTION_DAYS))

    log_id: Optional[str] = None
    db_logged = False
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_logs (
                    user_id, province_code, prompt, response,
                    tools_used, guardrail_status, latency_ms, model
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    str(user_id),
                    safe_prov,
                    safe_prompt,
                    safe_response,
                    safe_tools,
                    safe_guardrail,
                    latency_ms,
                    safe_model,
                ),
            )
            inserted = cur.fetchone()
            if isinstance(inserted, Mapping):
                raw_id = inserted.get("id")
            elif isinstance(inserted, (tuple, list)) and inserted:
                raw_id = inserted[0]
            else:
                raw_id = None
            if raw_id is not None:
                log_id = str(raw_id)

            cur.execute(
                """
                DELETE FROM chat_logs
                WHERE user_id = %s
                  AND created_at < NOW() - make_interval(days => %s);
                """,
                (str(user_id), retention_days),
            )
        db_logged = True
    except Exception as e:
        db_logged = False
        log_id = None
        logger.warning("Failed to record chat log: %s", e)

    if settings.CHAT_LOG_FILE_ENABLED:
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "log_id": log_id,
                "user_id": str(user_id),
                "province_code": safe_prov,
                "prompt": safe_prompt,
                "response": safe_response,
                "tools_used": safe_tools,
                "guardrail_status": safe_guardrail,
                "latency_ms": latency_ms,
                "model": safe_model,
                "db_logged": db_logged,
            }
            _write_chat_log_file(entry)
        except Exception as e:
            logger.warning("Failed to write chat log file: %s", e)
