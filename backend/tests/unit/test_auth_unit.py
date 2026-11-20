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


def test_chat_log_written_with_prompt_response_latency_on_success(monkeypatch):
    from contextlib import contextmanager
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.agent.orchestrator import AgentChatResponse
    from backend.app.api.deps import get_current_user

    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_RETENTION_DAYS", 90)

    mock_cur = MagicMock()

    @contextmanager
    def fake_cursor():
        yield mock_cur

    fake_user_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    app.dependency_overrides[get_current_user] = lambda: {
        "id": fake_user_id,
        "email": "loguser@jakarta.go.id",
        "role": "user",
        "is_service": False,
    }

    mock_response = AgentChatResponse(
        reply="Skor Tebet adalah 54.61.",
        tool_calls_executed=[{"name": "get_district_scorecard", "arguments": {}}],
        guardrail="passed",
        model_used="qwen2.5:14b",
    )

    client = TestClient(app)
    try:
        with patch("backend.app.api.routers.chat.agent_orchestrator.process_chat", return_value=mock_response):
            with patch("backend.app.api.routers.chat.record_chat_audit"):
                with patch("backend.app.core.auth.get_db_cursor", side_effect=fake_cursor):
                    res = client.post(
                        "/api/v1/chat",
                        json={
                            "messages": [
                                {"role": "user", "content": "Pertanyaan lama"},
                                {"role": "assistant", "content": "Jawaban lama"},
                                {"role": "user", "content": "Berapa skor Tebet?"},
                            ],
                            "province_code": "31",
                        },
                    )
                    assert res.status_code == 200
                    assert mock_cur.execute.call_count == 2
                    insert_sql, insert_params = mock_cur.execute.call_args_list[0][0]
                    assert "INSERT INTO chat_logs" in insert_sql
                    assert insert_params[0] == str(fake_user_id)
                    assert insert_params[1] == "31"
                    assert insert_params[2] == "Berapa skor Tebet?"
                    assert insert_params[3] == "Skor Tebet adalah 54.61."
                    assert insert_params[4] == ["get_district_scorecard"]
                    assert insert_params[5] == "passed"
                    assert isinstance(insert_params[6], int) and insert_params[6] >= 0
                    assert insert_params[7] == "qwen2.5:14b"

                    delete_sql, delete_params = mock_cur.execute.call_args_list[1][0]
                    assert "DELETE FROM chat_logs" in delete_sql
                    assert delete_params == (str(fake_user_id), 90)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_chat_log_failure_never_breaks_chat_response(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.agent.orchestrator import AgentChatResponse
    from backend.app.api.deps import get_current_user

    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)

    fake_user_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    app.dependency_overrides[get_current_user] = lambda: {
        "id": fake_user_id,
        "email": "logfail@jakarta.go.id",
        "role": "user",
        "is_service": False,
    }

    mock_response = AgentChatResponse(
        reply="Respons tetap aman.",
        guardrail="passed",
    )

    client = TestClient(app)
    try:
        with patch("backend.app.api.routers.chat.agent_orchestrator.process_chat", return_value=mock_response):
            with patch("backend.app.api.routers.chat.record_chat_audit"):
                with patch("backend.app.api.routers.chat.record_chat_log", side_effect=RuntimeError("DB down")):
                    res = client.post(
                        "/api/v1/chat",
                        json={"messages": [{"role": "user", "content": "Halo"}]},
                    )
                    assert res.status_code == 200
                    assert res.json()["reply"] == "Respons tetap aman."
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_chat_log_disabled_writes_nothing(monkeypatch):
    from backend.app.core.auth import record_chat_log

    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", False)
    with patch("backend.app.core.auth.get_db_cursor") as mock_db:
        record_chat_log(
            user_id="22222222-2222-2222-2222-222222222222",
            province_code="31",
            prompt="Pertanyaan",
            response="Jawaban",
            tools_used=[],
            guardrail_status="passed",
            latency_ms=10,
            model="qwen2.5:14b",
        )
        mock_db.assert_not_called()


def test_chat_log_truncation_limits(monkeypatch):
    from contextlib import contextmanager
    from backend.app.core.auth import (
        record_chat_log,
        CHAT_LOG_PROMPT_MAX_CHARS,
        CHAT_LOG_RESPONSE_MAX_CHARS,
    )

    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    mock_cur = MagicMock()

    @contextmanager
    def fake_cursor():
        yield mock_cur

    long_prompt = "P" * 5500
    long_response = "R" * 25000

    with patch("backend.app.core.auth.get_db_cursor", side_effect=fake_cursor):
        record_chat_log(
            user_id="22222222-2222-2222-2222-222222222222",
            province_code="31",
            prompt=long_prompt,
            response=long_response,
            tools_used=[],
            guardrail_status="passed",
            latency_ms=25,
            model="qwen2.5:14b",
        )

    insert_params = mock_cur.execute.call_args_list[0][0][1]
    assert len(insert_params[2]) == CHAT_LOG_PROMPT_MAX_CHARS == 4000
    assert len(insert_params[3]) == CHAT_LOG_RESPONSE_MAX_CHARS == 20000


def test_chat_log_service_principal_not_logged(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.agent.orchestrator import AgentChatResponse
    from backend.app.api.deps import get_current_user

    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "00000000-0000-0000-0000-000000000000",
        "email": "service@drp.local",
        "role": "admin",
        "is_service": True,
    }

    mock_response = AgentChatResponse(reply="Service reply.", guardrail="passed")
    client = TestClient(app)
    try:
        with patch("backend.app.api.routers.chat.agent_orchestrator.process_chat", return_value=mock_response):
            with patch("backend.app.api.routers.chat.record_chat_audit"):
                with patch("backend.app.api.routers.chat.record_chat_log") as mock_log:
                    res = client.post(
                        "/api/v1/chat",
                        json={"messages": [{"role": "user", "content": "Service query"}]},
                    )
                    assert res.status_code == 200
                    mock_log.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_chat_log_file_written_with_all_fields(monkeypatch, tmp_path):
    import json
    import os
    import stat
    from contextlib import contextmanager
    from datetime import datetime
    from backend.app.core.auth import record_chat_log

    log_path = tmp_path / "nested" / "chat_log.jsonl"
    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_MAX_MB", 20)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_BACKUPS", 10)

    fake_log_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"id": fake_log_id}

    @contextmanager
    def fake_cursor():
        yield mock_cur

    with patch("backend.app.core.auth.get_db_cursor", side_effect=fake_cursor):
        record_chat_log(
            user_id="22222222-2222-2222-2222-222222222222",
            province_code="31",
            prompt="Bagaimana indeks fasilitas Kec. Tebet? — cek café",
            response="Skor kecukupan fasilitas Tebet adalah 54.61 (SNI 03-1733-2004).",
            tools_used=["get_district_scorecard"],
            guardrail_status="passed",
            latency_ms=142,
            model="qwen2.5:14b",
        )

    assert log_path.exists()
    assert stat.S_IMODE(os.stat(log_path).st_mode) == 0o640

    raw_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 1
    assert "café" in raw_lines[0]  # ensure_ascii=False

    entry = json.loads(raw_lines[0])
    assert set(entry.keys()) == {
        "timestamp",
        "log_id",
        "user_id",
        "province_code",
        "prompt",
        "response",
        "tools_used",
        "guardrail_status",
        "latency_ms",
        "model",
        "db_logged",
    }
    parsed_ts = datetime.fromisoformat(entry["timestamp"])
    assert parsed_ts.utcoffset() is not None
    assert entry["log_id"] == fake_log_id
    assert entry["user_id"] == "22222222-2222-2222-2222-222222222222"
    assert entry["province_code"] == "31"
    assert entry["prompt"] == "Bagaimana indeks fasilitas Kec. Tebet? — cek café"
    assert entry["response"] == "Skor kecukupan fasilitas Tebet adalah 54.61 (SNI 03-1733-2004)."
    assert entry["tools_used"] == ["get_district_scorecard"]
    assert entry["guardrail_status"] == "passed"
    assert entry["latency_ms"] == 142
    assert entry["model"] == "qwen2.5:14b"
    assert entry["db_logged"] is True


def test_chat_log_file_written_when_db_insert_raises(monkeypatch, tmp_path):
    import json
    from backend.app.core.auth import record_chat_log

    log_path = tmp_path / "fallback_chat_log.jsonl"
    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_PATH", str(log_path))

    with patch("backend.app.core.auth.get_db_cursor", side_effect=RuntimeError("DB unavailable")):
        record_chat_log(
            user_id="33333333-3333-3333-3333-333333333333",
            province_code="32",
            prompt="Pertanyaan saat DB down",
            response="Jawaban tetap tersimpan di file",
            tools_used=["get_district_scorecard"],
            guardrail_status="passed",
            latency_ms=55,
            model="qwen2.5:14b",
        )

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["db_logged"] is False
    assert entry["log_id"] is None
    assert entry["user_id"] == "33333333-3333-3333-3333-333333333333"
    assert entry["province_code"] == "32"
    assert entry["prompt"] == "Pertanyaan saat DB down"
    assert entry["response"] == "Jawaban tetap tersimpan di file"


def test_chat_log_file_not_written_when_disabled(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from backend.app.core.auth import record_chat_log

    log_path = tmp_path / "should_not_exist.jsonl"
    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_PATH", str(log_path))

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}

    @contextmanager
    def fake_cursor():
        yield mock_cur

    with patch("backend.app.core.auth.get_db_cursor", side_effect=fake_cursor):
        record_chat_log(
            user_id="22222222-2222-2222-2222-222222222222",
            province_code="31",
            prompt="Pertanyaan",
            response="Jawaban",
            tools_used=[],
            guardrail_status="passed",
            latency_ms=12,
            model="qwen2.5:14b",
        )

    assert not log_path.exists()


def test_chat_log_file_rotation_and_no_root_propagation(monkeypatch, tmp_path, caplog):
    import logging
    from logging.handlers import RotatingFileHandler
    from backend.app.core.auth import record_chat_log, _chat_file_logger

    log_path = tmp_path / "rotated.jsonl"
    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_MAX_MB", 0.0003)  # ~314 bytes -> forces rollover
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_BACKUPS", 3)

    caplog.set_level(logging.INFO)
    with patch("backend.app.core.auth.get_db_cursor", side_effect=RuntimeError("skip db")):
        for idx in range(4):
            record_chat_log(
                user_id="44444444-4444-4444-4444-444444444444",
                province_code="31",
                prompt=f"Secret prompt #{idx} " + ("x" * 120),
                response=f"Secret response #{idx} " + ("y" * 120),
                tools_used=[],
                guardrail_status="passed",
                latency_ms=10,
                model="qwen2.5:14b",
            )

    assert _chat_file_logger.propagate is False
    assert len(_chat_file_logger.handlers) == 1
    handler = _chat_file_logger.handlers[0]
    assert isinstance(handler, RotatingFileHandler)
    assert handler.backupCount == 3
    assert handler.maxBytes == int(0.0003 * 1024 * 1024)

    # Prompt text from file logger must never appear in root logger / caplog
    for rec in caplog.records:
        if rec.name == _chat_file_logger.name:
            pytest.fail("Chat file logger must not propagate to root logger")
        assert "Secret prompt #" not in rec.getMessage()

    assert log_path.exists()
    assert (tmp_path / "rotated.jsonl.1").exists()


def test_chat_log_file_truncation_default_path_and_error_isolation(monkeypatch, tmp_path):
    import json
    import os
    from backend.app.core.config import _resolve_default_chat_log_file_path
    from backend.app.core.auth import (
        record_chat_log,
        CHAT_LOG_PROMPT_MAX_CHARS,
        CHAT_LOG_RESPONSE_MAX_CHARS,
    )

    log_path = tmp_path / "truncated.jsonl"
    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_PATH", str(log_path))

    with patch("backend.app.core.auth.get_db_cursor", side_effect=RuntimeError("skip db")):
        record_chat_log(
            user_id="55555555-5555-5555-5555-555555555555",
            province_code="31",
            prompt="P" * 5200,
            response="R" * 24000,
            tools_used=[],
            guardrail_status="passed",
            latency_ms=20,
            model="qwen2.5:14b",
        )

    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert len(entry["prompt"]) == CHAT_LOG_PROMPT_MAX_CHARS == 4000
    assert len(entry["response"]) == CHAT_LOG_RESPONSE_MAX_CHARS == 20000

    # Default path checks (/app vs local repo)
    with patch("backend.app.core.config.os.path.isdir", return_value=True):
        assert _resolve_default_chat_log_file_path() == "/app/logs/chat_log.jsonl"
    with patch("backend.app.core.config.os.path.isdir", return_value=False):
        local_default = _resolve_default_chat_log_file_path()
        assert local_default.endswith(os.path.join("logs", "chat_log.jsonl"))

    # File write failure never raises
    with patch("backend.app.core.auth._write_chat_log_file", side_effect=PermissionError("read-only")):
        with patch("backend.app.core.auth.get_db_cursor", side_effect=RuntimeError("skip db")):
            record_chat_log(
                user_id="55555555-5555-5555-5555-555555555555",
                province_code="31",
                prompt="Hi",
                response="Hello",
                tools_used=[],
                guardrail_status="passed",
                latency_ms=5,
                model="qwen2.5:14b",
            )
