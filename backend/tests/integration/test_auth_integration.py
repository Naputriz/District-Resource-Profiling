"""
Integration & End-to-End Tests for Authentication & Route Protection.
Markers: db
Enforces:
- Registration & login flow with user teardown
- Identical responses for unknown email & wrong password with brute-force reset
- AUTH_ALLOW_REGISTER=False -> 403
- Dynamic route table iteration verifying every protected route returns 401 without token and with garbage bearer
- Public GET routes remain accessible without token (200 OK)
- Authenticated user can access /api/v1/auth/me and protected routes
- Register -> login -> POST /api/v1/chat with mocked orchestrator
- Service principal client forgery prevention
- 73-byte password rejected with 422 and Indonesian message
"""

import os
import time
import uuid
from unittest.mock import patch
import jwt
import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from backend.app.main import app
from backend.app.core.config import settings
from backend.app.core.db import init_db_pool, close_db_pool, get_db_cursor, get_redis_client
from backend.app.core.auth import reset_failed_login, decode_access_token, create_access_token
from backend.app.api.deps import AUTH_REQUIRED_MESSAGE
from backend.app.agent.orchestrator import AgentChatResponse

pytestmark = pytest.mark.db


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM app_users WHERE email LIKE 'user_%@jakarta.go.id';")
    yield
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM app_users WHERE email LIKE 'user_%@jakarta.go.id';")
    close_db_pool()


def test_auth_registration_and_login(requires_seed):
    client = TestClient(app)
    unique_suffix = uuid.uuid4().hex[:8]
    test_email = f"user_{unique_suffix}@jakarta.go.id"
    test_password = "SecurePassword123!"
    display_name = f"Test User {unique_suffix}"
    created_id = None

    try:
        # 1. Register new user
        res_reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": test_email,
                "password": test_password,
                "display_name": display_name,
            },
        )
        assert res_reg.status_code == 201, f"Register failed: {res_reg.text}"
        user_data = res_reg.json()
        assert user_data["email"] == test_email.lower()
        assert user_data["display_name"] == display_name
        assert "id" in user_data
        created_id = user_data["id"]

        # 2. Duplicate registration fails
        res_dup = client.post(
            "/api/v1/auth/register",
            json={
                "email": test_email.upper(),
                "password": test_password,
                "display_name": "Another Name",
            },
        )
        assert res_dup.status_code == 409
        assert "Email sudah terdaftar" in res_dup.json()["detail"]

        # 3. Login with registered user
        res_login = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert res_login.status_code == 200, f"Login failed: {res_login.text}"
        token_data = res_login.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "bearer"
        access_token = token_data["access_token"]

        # 4. Access /auth/me with token
        auth_header = {"Authorization": f"Bearer {access_token}"}
        res_me = client.get("/api/v1/auth/me", headers=auth_header)
        assert res_me.status_code == 200
        me_data = res_me.json()
        assert me_data["email"] == test_email.lower()
        assert me_data["display_name"] == display_name
        assert "limits" in me_data
        assert me_data["limits"]["chat_requests_limit"] == settings.AUTH_CHAT_RATE_LIMIT_REQUESTS
        assert me_data["limits"]["chat_window_minutes"] == settings.AUTH_CHAT_RATE_LIMIT_WINDOW_SECONDS // 60

        # 5. Access protected simulation route with token
        sim_payload = {
            "district_code": "31.71.09",
            "population_shock_percent": 10.0,
            "population_shock_count": 0,
            "hypothetical_facilities": [],
        }
        res_sim = client.post(
            "/api/v1/simulation/what-if", json=sim_payload, headers=auth_header
        )
        assert res_sim.status_code == 200

        # 6. Logout
        res_logout = client.post("/api/v1/auth/logout", headers=auth_header)
        assert res_logout.status_code == 200
    finally:
        if created_id:
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM app_users WHERE id = %s;", (created_id,))
        reset_failed_login(test_email, "testclient")


def test_identical_login_error_for_unknown_email_and_wrong_password():
    client = TestClient(app)
    unk_email = "nonexistent_9999@jakarta.go.id"
    known_email = "admin@jakarta.go.id"

    reset_failed_login(unk_email, "testclient")
    reset_failed_login(known_email, "testclient")

    try:
        res_unknown = client.post(
            "/api/v1/auth/login",
            json={"email": unk_email, "password": "wrongpassword123"},
        )
        assert res_unknown.status_code == 401

        res_wrong_pw = client.post(
            "/api/v1/auth/login",
            json={"email": known_email, "password": "definitelyWrongPassword123!"},
        )
        assert res_wrong_pw.status_code == 401

        assert res_unknown.json() == res_wrong_pw.json()
        assert res_unknown.json()["detail"] == "Email atau kata sandi salah."
    finally:
        reset_failed_login(unk_email, "testclient")
        reset_failed_login(known_email, "testclient")


def test_auth_allow_register_disabled():
    client = TestClient(app)
    original = settings.AUTH_ALLOW_REGISTER
    try:
        settings.AUTH_ALLOW_REGISTER = False
        res = client.post(
            "/api/v1/auth/register",
            json={
                "email": "disabled@jakarta.go.id",
                "password": "Password12345!",
                "display_name": "Disabled",
            },
        )
        assert res.status_code == 403
        assert "Pendaftaran pengguna baru dinonaktifkan" in res.json()["detail"]
    finally:
        settings.AUTH_ALLOW_REGISTER = original


def test_route_table_protection_and_public_routes(requires_seed):
    client = TestClient(app)

    dummy_payloads = {
        "/api/v1/chat": {"messages": [{"role": "user", "content": "halo"}]},
        "/api/v1/chat/conversation": {"messages": [{"role": "user", "content": "halo"}]},
        "/api/v1/simulation/what-if": {
            "district_code": "31.71.09",
            "population_shock_percent": 0.0,
            "population_shock_count": 0,
            "hypothetical_facilities": [],
        },
        "/api/v1/simulation/superblock": {
            "district_code": "31.71.09",
            "project_name": "Test",
            "residential_units": 100,
            "occupants_per_unit": 3.0,
            "site_area_m2": 1000.0,
            "staged_amenities": [],
        },
        "/api/v1/spatial/blank-spots/simulate-reduction": {
            "district_code": "31.71.09",
            "facility_type": "puskesmas_kelurahan",
            "hypothetical_coordinates": [106.85, -6.23],
        },
        "/api/v1/rag/search": {
            "query": "standar puskesmas",
            "pillar": "lifeline_health",
            "top_k": 2,
        },
        "/api/v1/rag/hybrid-search": {
            "query": "standar puskesmas",
            "pillar": "lifeline_health",
            "top_k": 2,
        },
    }

    def get_all_routes(routes):
        all_routes = []
        for r in routes:
            if isinstance(r, APIRoute):
                all_routes.append(r)
            elif hasattr(r, "original_router"):
                all_routes.extend(get_all_routes(r.original_router.routes))
            elif hasattr(r, "routes"):
                all_routes.extend(get_all_routes(r.routes))
        return all_routes

    all_api_routes = get_all_routes(app.routes)
    post_routes_to_test = [
        r for r in all_api_routes
        if "POST" in r.methods and not r.path.startswith("/api/v1/auth/")
    ]

    assert len(post_routes_to_test) >= 7, f"Expected at least 7 non-auth POST routes, found {len(post_routes_to_test)}"

    orig_api_key = os.environ.pop("API_KEY", None)
    try:
        for r in post_routes_to_test:
            payload = dummy_payloads.get(r.path, {})

            os.environ.pop("API_KEY", None)
            res_unset_no_tok = client.post(r.path, json=payload)
            assert res_unset_no_tok.status_code == 401, f"{r.path} expected 401 on unset+no_tok, got {res_unset_no_tok.status_code}"
            assert res_unset_no_tok.json().get("detail") == AUTH_REQUIRED_MESSAGE

            res_unset_garb = client.post(
                r.path,
                json=payload,
                headers={"Authorization": "Bearer garbage.invalid.token"},
            )
            assert res_unset_garb.status_code == 401, f"{r.path} expected 401 on unset+garbage, got {res_unset_garb.status_code}"
            assert res_unset_garb.json().get("detail") == AUTH_REQUIRED_MESSAGE

            os.environ["API_KEY"] = "integration-test-secret-key"
            res_set_no_tok = client.post(r.path, json=payload)
            assert res_set_no_tok.status_code == 401, f"{r.path} expected 401 on set+no_tok, got {res_set_no_tok.status_code}"

            res_set_garb = client.post(
                r.path,
                json=payload,
                headers={"Authorization": "Bearer garbage.invalid.token"},
            )
            assert res_set_garb.status_code == 401, f"{r.path} expected 401 on set+garbage, got {res_set_garb.status_code}"
    finally:
        if orig_api_key is not None:
            os.environ["API_KEY"] = orig_api_key
        else:
            os.environ.pop("API_KEY", None)

    res_me_no_token = client.get("/api/v1/auth/me")
    assert res_me_no_token.status_code == 401
    res_me_garb = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert res_me_garb.status_code == 401

    public_get_routes = [
        "/health",
        "/api/v1/meta/standards",
        "/api/v1/districts",
        "/api/v1/districts/31.71.09",
        "/api/v1/facilities?pillar=lifeline_health&limit=5",
        "/api/v1/spatial/buffers?district_code=31.71.09&facility_type=puskesmas_kelurahan",
        "/api/v1/spatial/blank-spots?district_code=31.71.09&facility_type=puskesmas_kelurahan",
        "/api/v1/rag/legal-chunks",
        "/api/v1/watchdog/telemetry",
        "/api/v1/watchdog/incidents",
    ]

    for p in public_get_routes:
        res = client.get(p)
        assert res.status_code == 200, f"Public GET route {p} failed with HTTP {res.status_code}: {res.text}"


def test_authenticated_chat_with_mocked_orchestrator():
    client = TestClient(app)
    uid = uuid.uuid4().hex[:8]
    email = f"chat_user_{uid}@jakarta.go.id"
    password = "ChatUserSecret123!"
    display_name = f"Chat User {uid}"
    user_id = None
    try:
        res_reg = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "display_name": display_name},
        )
        assert res_reg.status_code == 201
        user_id = res_reg.json()["id"]

        res_login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert res_login.status_code == 200
        token = res_login.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        with patch(
            "backend.app.api.routers.chat.agent_orchestrator.process_chat",
            return_value=AgentChatResponse(
                reply="Halo! Saya asisten tata ruang DKI Jakarta.",
                model_used="mock-qwen",
                guardrail="passed",
                tool_calls_executed=[
                    {
                        "name": "get_district_scorecard",
                        "arguments": {"district_code": "31.71.09"},
                        "result_summary": {"ok": True},
                    }
                ],
            ),
        ):
            res_chat = client.post(
                "/api/v1/chat",
                json={"messages": [{"role": "user", "content": "Halo asisten"}]},
                headers=auth_headers,
            )
            assert res_chat.status_code == 200
            data = res_chat.json()
            assert data["reply"] == "Halo! Saya asisten tata ruang DKI Jakarta."
            assert data["guardrail"] == "passed"
            assert len(data["tool_calls_executed"]) == 1
            assert data["tool_calls_executed"][0]["name"] == "get_district_scorecard"

        with get_db_cursor() as cur:
            cur.execute(
                "SELECT tools_used, guardrail_status, question_length FROM chat_audit WHERE user_id = %s;",
                (user_id,),
            )
            audit_row = cur.fetchone()
            assert audit_row is not None
            assert audit_row["tools_used"] == ["get_district_scorecard"]
            assert audit_row["guardrail_status"] == "passed"
            assert audit_row["question_length"] == len("Halo asisten")
    finally:
        if user_id:
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM chat_audit WHERE user_id = %s;", (user_id,))
                cur.execute("DELETE FROM app_users WHERE id = %s;", (user_id,))
            r = get_redis_client()
            if r:
                r.delete(f"rate:chat:user:{user_id}")
        reset_failed_login(email, "testclient")


def test_service_principal_client_forgery_fails():
    client = TestClient(app)

    # 1. Valid service principal token succeeds on protected endpoint without DB app_users row
    valid_service_token = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000000",
        "email": "service@drp.local",
        "role": "admin",
        "is_service": True,
    })
    with get_db_cursor() as cur:
        cur.execute("SELECT 1 FROM app_users WHERE id = '00000000-0000-0000-0000-000000000000';")
        assert cur.fetchone() is None
    res_valid = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {valid_service_token}"})
    assert res_valid.status_code == 200
    data_valid = res_valid.json()
    assert data_valid["email"] == "service@drp.local"
    assert data_valid["role"] == "admin"
    assert data_valid["display_name"] == "Service Principal"

    # 2. Client forgery attempts fail with 401
    orig_key = os.environ.pop("API_KEY", None)
    try:
        forged_jwt_wrong_secret = jwt.encode(
            {
                "sub": "00000000-0000-0000-0000-000000000000",
                "email": "service@drp.local",
                "role": "admin",
                "is_service": True,
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            "attacker-guessed-secret",
            algorithm="HS256",
        )
        r1 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_jwt_wrong_secret}"})
        assert r1.status_code == 401

        forged_jwt_none = jwt.encode(
            {
                "sub": "00000000-0000-0000-0000-000000000000",
                "is_service": True,
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            "",
            algorithm="none",
        )
        r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_jwt_none}"})
        assert r2.status_code == 401

        forge_email = f"attacker_{uuid.uuid4().hex[:8]}@jakarta.go.id"
        created_id = None
        try:
            r3 = client.post(
                "/api/v1/auth/register",
                json={
                    "email": forge_email,
                    "password": "ValidPassword123!",
                    "display_name": "Attacker",
                    "is_service": True,
                    "role": "admin",
                    "id": "00000000-0000-0000-0000-000000000000",
                },
            )
            assert r3.status_code == 201
            data = r3.json()
            created_id = data["id"]
            assert data["role"] == "user"
            assert data["id"] != "00000000-0000-0000-0000-000000000000"

            r3_login = client.post(
                "/api/v1/auth/login",
                json={"email": forge_email, "password": "ValidPassword123!"},
            )
            tok = r3_login.json()["access_token"]
            decoded = decode_access_token(tok)
            assert "is_service" not in decoded
        finally:
            if created_id:
                with get_db_cursor() as cur:
                    cur.execute("DELETE FROM app_users WHERE id = %s;", (created_id,))
            reset_failed_login(forge_email, "testclient")

        r4 = client.get("/api/v1/auth/me", headers={"X-API-Key": "attacker-forged-api-key"})
        assert r4.status_code == 401
    finally:
        if orig_key is not None:
            os.environ["API_KEY"] = orig_key
        else:
            os.environ.pop("API_KEY", None)


def test_password_73_bytes_rejected_with_422():
    client = TestClient(app)
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"pw73_{uuid.uuid4().hex[:6]}@jakarta.go.id",
            "password": "a" * 73,
            "display_name": "Password 73 Bytes",
        },
    )
    assert res.status_code == 422
    assert "72 byte" in res.text


def test_chat_logs_history_delete_and_retention(monkeypatch):
    """
    Integration tests for chat_logs:
    - Guest gets 401 on GET/DELETE /api/v1/chat/history
    - Authenticated chat (mocked orchestrator) inserts one chat_logs row
    - GET /api/v1/chat/history returns only caller's rows, newest first, limit capped at 100
    - Retention deletes rows older than CHAT_LOG_RETENTION_DAYS on insert
    - DELETE /api/v1/chat/history deletes only caller's rows
    """
    client = TestClient(app)

    # 1. Guest 401
    assert client.get("/api/v1/chat/history").status_code == 401
    assert client.delete("/api/v1/chat/history").status_code == 401

    uid_a = uuid.uuid4().hex[:8]
    uid_b = uuid.uuid4().hex[:8]
    email_a = f"user_hist_a_{uid_a}@jakarta.go.id"
    email_b = f"user_hist_b_{uid_b}@jakarta.go.id"
    password = "HistPassword123!"
    user_a_id = None
    user_b_id = None

    try:
        reg_a = client.post(
            "/api/v1/auth/register",
            json={"email": email_a, "password": password, "display_name": "Hist User A"},
        )
        assert reg_a.status_code == 201
        user_a_id = reg_a.json()["id"]

        reg_b = client.post(
            "/api/v1/auth/register",
            json={"email": email_b, "password": password, "display_name": "Hist User B"},
        )
        assert reg_b.status_code == 201
        user_b_id = reg_b.json()["id"]

        tok_a = client.post("/api/v1/auth/login", json={"email": email_a, "password": password}).json()["access_token"]
        tok_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": password}).json()["access_token"]
        headers_a = {"Authorization": f"Bearer {tok_a}"}
        headers_b = {"Authorization": f"Bearer {tok_b}"}

        # 2. Chat turns for A and B (mock orchestrator)
        with patch(
            "backend.app.api.routers.chat.agent_orchestrator.process_chat",
            side_effect=[
                AgentChatResponse(reply="Jawaban A1", model_used="mock-qwen", guardrail="passed"),
                AgentChatResponse(reply="Jawaban A2", model_used="mock-qwen", guardrail="passed"),
                AgentChatResponse(reply="Jawaban B1", model_used="mock-qwen", guardrail="passed"),
            ],
        ):
            r_a1 = client.post(
                "/api/v1/chat",
                json={"messages": [{"role": "user", "content": "Pertanyaan A1"}], "province_code": "31"},
                headers=headers_a,
            )
            assert r_a1.status_code == 200

            r_a2 = client.post(
                "/api/v1/chat",
                json={"messages": [{"role": "user", "content": "Pertanyaan A2"}], "province_code": "32"},
                headers=headers_a,
            )
            assert r_a2.status_code == 200

            r_b1 = client.post(
                "/api/v1/chat",
                json={"messages": [{"role": "user", "content": "Pertanyaan B1"}], "province_code": "34"},
                headers=headers_b,
            )
            assert r_b1.status_code == 200

        # 3. Verify DB row count for A and retention backdate test
        with get_db_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM chat_logs WHERE user_id = %s;", (user_a_id,))
            assert cur.fetchone()["cnt"] == 2

            # Insert an expired row (20 days old) for user A
            cur.execute(
                """
                INSERT INTO chat_logs (user_id, created_at, province_code, prompt, response)
                VALUES (%s, NOW() - INTERVAL '20 days', '31', 'Pertanyaan kedaluwarsa', 'Jawaban lama');
                """,
                (user_a_id,),
            )

        # Trigger another chat for A with retention=7 days -> expired row deleted
        monkeypatch.setattr(settings, "CHAT_LOG_RETENTION_DAYS", 7)
        with patch(
            "backend.app.api.routers.chat.agent_orchestrator.process_chat",
            return_value=AgentChatResponse(reply="Jawaban A3", model_used="mock-qwen", guardrail="passed"),
        ):
            r_a3 = client.post(
                "/api/v1/chat",
                json={"messages": [{"role": "user", "content": "Pertanyaan A3"}], "province_code": "31"},
                headers=headers_a,
            )
            assert r_a3.status_code == 200

        # 4. GET /api/v1/chat/history returns only A's rows, newest first, retention pruned old row
        res_hist_a = client.get("/api/v1/chat/history?limit=500", headers=headers_a)
        assert res_hist_a.status_code == 200
        hist_a = res_hist_a.json()
        prompts_a = [item["prompt"] for item in hist_a["items"]]
        assert "Pertanyaan kedaluwarsa" not in prompts_a
        assert "Pertanyaan B1" not in prompts_a
        assert prompts_a == ["Pertanyaan A3", "Pertanyaan A2", "Pertanyaan A1"]
        assert hist_a["items"][0]["response"] == "Jawaban A3"
        assert hist_a["items"][0]["latency_ms"] is not None

        # Verify limit parameter works and limit > 100 is capped at 100
        res_hist_1 = client.get("/api/v1/chat/history?limit=1", headers=headers_a)
        assert res_hist_1.status_code == 200
        assert len(res_hist_1.json()["items"]) == 1
        assert res_hist_1.json()["items"][0]["prompt"] == "Pertanyaan A3"

        with get_db_cursor() as cur:
            # Insert 105 rows for user B to verify cap at 100
            for idx in range(105):
                cur.execute(
                    """
                    INSERT INTO chat_logs (user_id, province_code, prompt, response)
                    VALUES (%s, '34', %s, %s);
                    """,
                    (user_b_id, f"Bulk Q {idx}", f"Bulk A {idx}"),
                )
        res_hist_b_cap = client.get("/api/v1/chat/history?limit=500", headers=headers_b)
        assert res_hist_b_cap.status_code == 200
        assert len(res_hist_b_cap.json()["items"]) == 100

        # 5. DELETE removes only caller's rows
        res_del_a = client.delete("/api/v1/chat/history", headers=headers_a)
        assert res_del_a.status_code == 200
        assert res_del_a.json()["deleted_count"] == 3

        res_hist_a_after = client.get("/api/v1/chat/history", headers=headers_a)
        assert res_hist_a_after.status_code == 200
        assert res_hist_a_after.json()["items"] == []

        # B's rows untouched
        res_hist_b_after = client.get("/api/v1/chat/history?limit=20", headers=headers_b)
        assert res_hist_b_after.status_code == 200
        assert len(res_hist_b_after.json()["items"]) == 20
    finally:
        with get_db_cursor() as cur:
            for uid in (user_a_id, user_b_id):
                if uid:
                    cur.execute("DELETE FROM chat_logs WHERE user_id = %s;", (uid,))
                    cur.execute("DELETE FROM chat_audit WHERE user_id = %s;", (uid,))
                    cur.execute("DELETE FROM app_users WHERE id = %s;", (uid,))
        r = get_redis_client()
        if r:
            for uid in (user_a_id, user_b_id):
                if uid:
                    r.delete(f"rate:chat:user:{uid}")
        reset_failed_login(email_a, "testclient")
        reset_failed_login(email_b, "testclient")


def test_chat_logs_db_and_file_matching_log_id(monkeypatch, tmp_path):
    """
    F2-B Integration:
    One chat turn (mocked orchestrator) inserts one chat_logs row AND appends
    one JSON line to CHAT_LOG_FILE_PATH (tmp path) with matching log_id and db_logged=True.
    """
    import json

    log_file = tmp_path / "integration_chat_log.jsonl"
    monkeypatch.setattr(settings, "CHAT_LOG_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LOG_FILE_PATH", str(log_file))

    client = TestClient(app)
    uid = uuid.uuid4().hex[:8]
    email = f"user_filelog_{uid}@jakarta.go.id"
    password = "FileLogPass123!"
    user_id = None

    try:
        reg = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "display_name": "File Log User"},
        )
        assert reg.status_code == 201
        user_id = reg.json()["id"]

        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with patch(
            "backend.app.api.routers.chat.agent_orchestrator.process_chat",
            return_value=AgentChatResponse(
                reply="Skor Tebet tercatat 54.61.",
                model_used="mock-qwen",
                guardrail="passed",
                tool_calls_executed=[{"name": "get_district_scorecard", "arguments": {}}],
            ),
        ):
            res = client.post(
                "/api/v1/chat",
                json={
                    "messages": [{"role": "user", "content": "Cek skor Tebet untuk log file"}],
                    "province_code": "31",
                },
                headers=headers,
            )
            assert res.status_code == 200

        with get_db_cursor() as cur:
            cur.execute(
                "SELECT id, province_code, prompt, response, tools_used, guardrail_status, latency_ms, model "
                "FROM chat_logs WHERE user_id = %s;",
                (user_id,),
            )
            rows = cur.fetchall()
            assert len(rows) == 1
            row = rows[0]

        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["log_id"] == str(row["id"])
        assert entry["db_logged"] is True
        assert entry["user_id"] == str(user_id)
        assert entry["province_code"] == "31"
        assert entry["prompt"] == "Cek skor Tebet untuk log file"
        assert entry["response"] == "Skor Tebet tercatat 54.61."
        assert entry["tools_used"] == ["get_district_scorecard"]
        assert entry["guardrail_status"] == "passed"
        assert entry["model"] == "mock-qwen"
        assert entry["latency_ms"] == row["latency_ms"]
    finally:
        if user_id:
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM chat_logs WHERE user_id = %s;", (user_id,))
                cur.execute("DELETE FROM chat_audit WHERE user_id = %s;", (user_id,))
                cur.execute("DELETE FROM app_users WHERE id = %s;", (user_id,))
            r = get_redis_client()
            if r:
                r.delete(f"rate:chat:user:{user_id}")
        reset_failed_login(email, "testclient")
