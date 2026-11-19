"""
Unit tests for Authentication: Password Hashing, JWT Tokens, Rate Limiting, Brute Force.
Markers: unit
"""

import time
import pytest
from datetime import timedelta
import jwt

import uuid
from backend.app.core.config import settings
from backend.app.core.db import get_redis_client
from backend.app.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    is_brute_force_locked,
    record_failed_login,
    reset_failed_login,
    check_chat_rate_limit,
    get_client_ip,
    _in_memory_failed_attempts,
    _in_memory_rate_limits,
    _DUMMY_BCRYPT_HASH,
)
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def test_password_hashing_and_verification():
    raw_pass = "ValidPassword123!"
    hashed = hash_password(raw_pass)

    assert hashed != raw_pass
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password(raw_pass, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False


def test_password_minimum_length_enforcement():
    with pytest.raises(ValueError, match="minimal 10 karakter"):
        hash_password("short9ch")


def test_jwt_token_lifecycle():
    data = {"sub": "user-uuid-1234", "email": "test@jakarta.go.id", "role": "user"}
    token = create_access_token(data, expires_delta=timedelta(minutes=15))

    decoded = decode_access_token(token)
    assert decoded["sub"] == "user-uuid-1234"
    assert decoded["email"] == "test@jakarta.go.id"
    assert decoded["role"] == "user"
    assert "exp" in decoded
    assert "iat" in decoded


def test_jwt_expired_token():
    data = {"sub": "expired-user"}
    # Token expired 1 minute ago
    token = create_access_token(data, expires_delta=timedelta(seconds=-60))

    with pytest.raises(ValueError, match="telah kedaluwarsa"):
        decode_access_token(token)


def test_jwt_tampered_token():
    data = {"sub": "tampered-user"}
    token = create_access_token(data)
    # Alter token string
    tampered = token[:-4] + "abcd"

    with pytest.raises(ValueError, match="tidak valid"):
        decode_access_token(tampered)


def test_jwt_wrong_secret():
    payload = {"sub": "bad-secret-user", "exp": int(time.time()) + 3600}
    bad_token = jwt.encode(payload, "completely-wrong-secret", algorithm="HS256")

    with pytest.raises(ValueError, match="tidak valid"):
        decode_access_token(bad_token)


def test_brute_force_counter_and_lockout():
    test_email = "victim@jakarta.go.id"
    test_ip = "192.168.1.100"

    reset_failed_login(test_email, test_ip)
    assert is_brute_force_locked(test_email, test_ip) is False

    # Simulate failed attempts up to threshold (5)
    for _ in range(settings.AUTH_BRUTE_FORCE_MAX_ATTEMPTS - 1):
        record_failed_login(test_email, test_ip)
        assert is_brute_force_locked(test_email, test_ip) is False

    # 5th failed attempt triggers lockout
    record_failed_login(test_email, test_ip)
    assert is_brute_force_locked(test_email, test_ip) is True

    # Reset clears lockout
    reset_failed_login(test_email, test_ip)
    assert is_brute_force_locked(test_email, test_ip) is False


def test_chat_rate_limiter():
    test_user_id = f"test-user-{uuid.uuid4().hex}"
    key = f"rate:chat:user:{test_user_id}"
    _in_memory_rate_limits.pop(key, None)
    r = get_redis_client()
    if r:
        try:
            r.delete(key)
        except Exception:
            pass

    limit = settings.AUTH_CHAT_RATE_LIMIT_REQUESTS
    for i in range(limit):
        allowed, remaining = check_chat_rate_limit(test_user_id)
        assert allowed is True

    # Next attempt must be blocked
    allowed, remaining = check_chat_rate_limit(test_user_id)
    assert allowed is False
    assert remaining == 0


def test_jwt_missing_required_claims_and_bad_algorithms():
    now = int(time.time())
    secret = settings.AUTH_JWT_SECRET

    # Missing exp
    tok_no_exp = jwt.encode({"sub": "user1", "iat": now}, secret, algorithm="HS256")
    with pytest.raises(ValueError, match="tidak valid"):
        decode_access_token(tok_no_exp)

    # Missing sub
    tok_no_sub = jwt.encode({"exp": now + 3600, "iat": now}, secret, algorithm="HS256")
    with pytest.raises(ValueError, match="tidak valid"):
        decode_access_token(tok_no_sub)

    # Missing iat
    tok_no_iat = jwt.encode({"sub": "user1", "exp": now + 3600}, secret, algorithm="HS256")
    with pytest.raises(ValueError, match="tidak valid"):
        decode_access_token(tok_no_iat)

    # alg=none
    tok_none = jwt.encode({"sub": "user1", "exp": now + 3600, "iat": now}, "", algorithm="none")
    with pytest.raises(ValueError, match="tidak valid"):
        decode_access_token(tok_none)

    # Wrong algorithm HS384
    tok_hs384 = jwt.encode({"sub": "user1", "exp": now + 3600, "iat": now}, secret, algorithm="HS384")
    with pytest.raises(ValueError, match="tidak valid"):
        decode_access_token(tok_hs384)


def test_password_length_limits_and_72_bytes():
    # Min length 10
    with pytest.raises(ValueError, match="minimal 10 karakter"):
        hash_password("short")

    # Max length 72 bytes
    pw_72 = "a" * 72
    h_72 = hash_password(pw_72)
    assert verify_password(pw_72, h_72) is True

    pw_73 = "a" * 73
    with pytest.raises(ValueError, match="maksimal 72 byte UTF-8"):
        hash_password(pw_73)

    assert verify_password(pw_73, h_72) is False


def test_dummy_bcrypt_hash_called_for_unknown_user():
    from backend.app.api.routers.auth import login_user
    from backend.app.api.schemas import UserLoginRequest
    from fastapi import HTTPException

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_cur
    mock_ctx.__exit__.return_value = None

    test_email = "unknown@jakarta.go.id"
    test_ip = "127.0.0.1"
    req = UserLoginRequest(email=test_email, password="WrongPassword123!")
    mock_req = MagicMock()
    mock_req.client.host = test_ip

    reset_failed_login(test_email, test_ip)
    try:
        with patch("backend.app.api.routers.auth.get_db_cursor", return_value=mock_ctx):
            with patch("backend.app.api.routers.auth.verify_password", wraps=verify_password) as mock_vp:
                with pytest.raises(HTTPException) as exc:
                    login_user(req, mock_req)
                assert exc.value.status_code == 401
                assert mock_vp.call_count == 1
                # Verified called with dummy hash
                args = mock_vp.call_args[0]
                assert args[0] == "WrongPassword123!"
                assert args[1] == _DUMMY_BCRYPT_HASH
    finally:
        reset_failed_login(test_email, test_ip)


def test_chat_audit_with_mocked_orchestrator_tool_calls_dict():
    """
    Verifies /api/v1/chat extracts tool names from tool_calls_executed dicts,
    records chat audit, and returns HTTP 200.
    """
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.agent.orchestrator import AgentChatResponse
    from backend.app.api.deps import get_current_user

    client = TestClient(app)
    fake_user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    app.dependency_overrides[get_current_user] = lambda: {
        "id": fake_user_id,
        "email": "test@jakarta.go.id",
        "role": "user",
        "is_service": False,
    }

    mock_response = AgentChatResponse(
        reply="Skor kecukupan fasilitas Kecamatan Tebet adalah 78.5.",
        tool_calls_executed=[
            {
                "name": "get_district_scorecard",
                "arguments": {"district_code": "31.71.09"},
                "result_summary": {"ok": True, "score": 78.5},
            }
        ],
        guardrail="passed",
    )

    try:
        with patch("backend.app.api.routers.chat.agent_orchestrator.process_chat", return_value=mock_response):
            with patch("backend.app.api.routers.chat.record_chat_audit") as mock_audit:
                res = client.post(
                    "/api/v1/chat",
                    json={"messages": [{"role": "user", "content": "Bagaimana skor Tebet?"}]},
                )
                assert res.status_code == 200
                data = res.json()
                assert data["reply"] == "Skor kecukupan fasilitas Kecamatan Tebet adalah 78.5."
                assert len(data["tool_calls_executed"]) == 1
                assert data["tool_calls_executed"][0]["name"] == "get_district_scorecard"

                mock_audit.assert_called_once()
                call_args = mock_audit.call_args[0]
                # user_audit_id, q_len, tools_used, guardrail_status
                assert call_args[0] == fake_user_id
                assert call_args[1] == len("Bagaimana skor Tebet?")
                assert call_args[2] == ["get_district_scorecard"]
                assert call_args[3] == "passed"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_chat_audit_failure_never_breaks_chat_response():
    """
    Verifies that audit logging errors are caught and never break /api/v1/chat.
    """
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.agent.orchestrator import AgentChatResponse
    from backend.app.api.deps import get_current_user

    client = TestClient(app)
    fake_user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    app.dependency_overrides[get_current_user] = lambda: {
        "id": fake_user_id,
        "email": "test@jakarta.go.id",
        "role": "user",
        "is_service": False,
    }

    mock_response = AgentChatResponse(
        reply="Jawaban asisten tata ruang.",
        tool_calls_executed=[{"name": "test_tool", "arguments": {}}],
        guardrail="passed",
    )

    try:
        with patch("backend.app.api.routers.chat.agent_orchestrator.process_chat", return_value=mock_response):
            with patch("backend.app.api.routers.chat.record_chat_audit", side_effect=RuntimeError("Database audit failed")):
                res = client.post(
                    "/api/v1/chat",
                    json={"messages": [{"role": "user", "content": "Halo"}]},
                )
                assert res.status_code == 200
                assert res.json()["reply"] == "Jawaban asisten tata ruang."
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _make_request(headers=None, client=("172.18.0.1", 12345)):
    from starlette.requests import Request

    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": raw_headers,
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


def test_get_client_ip_rule_a_valid_secret(monkeypatch):
    monkeypatch.setattr(settings, "EDGE_SHARED_SECRET", "edge-secret-123")
    req = _make_request(
        headers={
            "X-DRP-Edge-Secret": "edge-secret-123",
            "X-DRP-Client-IP": "203.0.113.42",
            "CF-Connecting-IP": "198.51.100.9",
        }
    )
    assert get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_wrong_secret_falls_to_cf_or_client(monkeypatch):
    monkeypatch.setattr(settings, "EDGE_SHARED_SECRET", "edge-secret-123")
    req_cf = _make_request(
        headers={
            "X-DRP-Edge-Secret": "wrong-secret",
            "X-DRP-Client-IP": "203.0.113.42",
            "CF-Connecting-IP": "198.51.100.9",
        }
    )
    assert get_client_ip(req_cf) == "198.51.100.9"

    req_no_cf = _make_request(
        headers={
            "X-DRP-Edge-Secret": "wrong-secret",
            "X-DRP-Client-IP": "203.0.113.42",
        },
        client=("172.18.0.1", 4321),
    )
    assert get_client_ip(req_no_cf) == "172.18.0.1"


def test_get_client_ip_empty_secret_disables_rule_a(monkeypatch):
    monkeypatch.setattr(settings, "EDGE_SHARED_SECRET", "")
    req = _make_request(
        headers={
            "X-DRP-Edge-Secret": "",
            "X-DRP-Client-IP": "203.0.113.42",
            "CF-Connecting-IP": "198.51.100.9",
        }
    )
    assert get_client_ip(req) == "198.51.100.9"

    req_no_cf = _make_request(
        headers={
            "X-DRP-Edge-Secret": "",
            "X-DRP-Client-IP": "203.0.113.42",
        },
        client=("172.18.0.1", 4321),
    )
    assert get_client_ip(req_no_cf) == "172.18.0.1"


def test_get_client_ip_invalid_ip_ignored(monkeypatch):
    monkeypatch.setattr(settings, "EDGE_SHARED_SECRET", "edge-secret-123")
    req_bad_edge = _make_request(
        headers={
            "X-DRP-Edge-Secret": "edge-secret-123",
            "X-DRP-Client-IP": "not-an-ip",
            "CF-Connecting-IP": "198.51.100.10",
        }
    )
    assert get_client_ip(req_bad_edge) == "198.51.100.10"

    req_all_bad = _make_request(
        headers={
            "X-DRP-Edge-Secret": "edge-secret-123",
            "X-DRP-Client-IP": "203.0.113.1, 10.0.0.1",
            "CF-Connecting-IP": "999.999.999.999",
        },
        client=("172.18.0.1", 4321),
    )
    assert get_client_ip(req_all_bad) == "172.18.0.1"


def test_get_client_ip_ipv6_accepted(monkeypatch):
    monkeypatch.setattr(settings, "EDGE_SHARED_SECRET", "edge-secret-123")
    req_edge_v6 = _make_request(
        headers={
            "X-DRP-Edge-Secret": "edge-secret-123",
            "X-DRP-Client-IP": "2001:0db8::1",
        }
    )
    assert get_client_ip(req_edge_v6) == "2001:db8::1"

    req_cf_v6 = _make_request(
        headers={"CF-Connecting-IP": "2001:db8:85a3::8a2e:370:7334"}
    )
    assert get_client_ip(req_cf_v6) == "2001:db8:85a3::8a2e:370:7334"


def test_get_client_ip_x_forwarded_for_ignored(monkeypatch):
    monkeypatch.setattr(settings, "EDGE_SHARED_SECRET", "")
    req = _make_request(
        headers={"X-Forwarded-For": "203.0.113.99"},
        client=("172.18.0.1", 4321),
    )
    assert get_client_ip(req) == "172.18.0.1"


def test_get_client_ip_no_headers_and_no_client(monkeypatch):
    monkeypatch.setattr(settings, "EDGE_SHARED_SECRET", "")
    req_client = _make_request(client=("10.20.30.40", 5555))
    assert get_client_ip(req_client) == "10.20.30.40"

    req_none = _make_request(client=None)
    assert get_client_ip(req_none) == "127.0.0.1"
