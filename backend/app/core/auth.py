"""
Authentication, Password Hashing, JWT Tokens, Brute-Force & Rate Limiting.
Enforces TODO-4 requirements:
- bcrypt password hashing with min length 10
- PyJWT HS256 token creation and verification
- Per-email & per-IP failed login brute-force tracking (Redis with in-memory fallback)
- Per-user chat rate limiter (Redis with in-memory fallback)
- Chat audit logging (privacy preserving: no raw question text)
"""

import time
import logging
from typing import Optional, Tuple, Dict, List
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt

from backend.app.core.config import settings
from backend.app.core.db import get_redis_client, get_db_cursor

logger = logging.getLogger(__name__)

# In-memory fallbacks when Redis is not available
_in_memory_failed_attempts: Dict[str, List[float]] = {}
_in_memory_rate_limits: Dict[str, List[float]] = {}

# Dummy bcrypt hash to equalize timing for non-existent users
_DUMMY_BCRYPT_HASH = bcrypt.hashpw(
    b"dummy-timing-equalizer-password", bcrypt.gensalt()
).decode("utf-8")


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
