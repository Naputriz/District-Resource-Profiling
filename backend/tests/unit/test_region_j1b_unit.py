"""
Unit tests for Task J1b: multi-province configuration, region status computation,
name resolution order across active provinces, and chat province_code support.
Marker: unit.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import parse_active_provinces, settings
from backend.app.api.routers.regions import (
    compute_region_status,
    clear_regions_cache,
)
from backend.app.engine.spatial import (
    resolve_district_record,
    resolve_district_candidates,
    format_ambiguous_district_detail,
)
from backend.app.agent.orchestrator import (
    AgentChatRequest,
    ChatMessage,
    CognitiveSpatialAgentOrchestrator,
    build_system_prompt,
)
from backend.app.agent.guardrails import build_deterministic_fallback_summary
from backend.app.main import app

client = TestClient(app)
pytestmark = pytest.mark.unit


def test_parse_active_provinces():
    """Parses comma-separated province codes cleanly with deduplication."""
    assert parse_active_provinces("31") == ["31"]
    assert parse_active_provinces("31, 32,33, 31 , 34") == ["31", "32", "33", "34"]
    assert parse_active_provinces("") == []
    assert parse_active_provinces(None) == []


def test_settings_active_provinces_override(monkeypatch):
    """Settings.active_provinces parses self.ACTIVE_PROVINCES directly regardless of os.environ."""
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32,34")
    monkeypatch.setenv("ACTIVE_PROVINCES", "31")
    assert settings.active_provinces == ["31", "32", "34"]

    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")
    monkeypatch.setenv("ACTIVE_PROVINCES", "31,32,33,34,35,36")
    assert settings.active_provinces == ["31"]


def test_region_status_computation_active_staging_planned():
    """Computes Active (DB + env), Staging (DB only), and Planned (no DB)."""
    db_stats = {
        "31": {"total": 44, "scored": 44, "gated": 0},
        "32": {"total": 627, "scored": 321, "gated": 306},
    }

    has_31, st_31, cov_31 = compute_region_status("31", db_stats, ["31"])
    assert has_31 is True
    assert st_31 == "Active"
    assert cov_31.total == 44 and cov_31.scored == 44 and cov_31.gated == 0

    has_32, st_32, cov_32 = compute_region_status("32", db_stats, ["31"])
    assert has_32 is True
    assert st_32 == "Staging"
    assert cov_32.total == 627 and cov_32.scored == 321 and cov_32.gated == 306

    has_33, st_33, cov_33 = compute_region_status("33", db_stats, ["31"])
    assert has_33 is False
    assert st_33 == "Planned"
    assert cov_33 is None

    has_32_act, st_32_act, _ = compute_region_status("32", db_stats, ["31", "32"])
    assert has_32_act is True
    assert st_32_act == "Active"


def test_regions_endpoint_staging_vs_active(monkeypatch):
    """GET /api/v1/regions computes status dynamically and includes population_source + coverage_summary."""
    clear_regions_cache()
    db_stats = {
        "31": {"total": 44, "scored": 44, "gated": 0},
        "32": {"total": 627, "scored": 321, "gated": 306},
    }
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")
    with patch("backend.app.api.routers.regions._get_db_province_stats", return_value=db_stats):
        res = client.get("/api/v1/regions")
        assert res.status_code == 200
        by_code = {r["province_code"]: r for r in res.json()}
        assert by_code["31"]["status"] == "Active"
        assert by_code["31"]["population_source"] == "BPS 2024"
        assert by_code["31"]["coverage_summary"] == {"total": 44, "scored": 44, "gated": 0}

        assert by_code["32"]["status"] == "Staging"
        assert by_code["32"]["has_data"] is True
        assert by_code["32"]["population_source"] == "Estimasi model WorldPop R2025A 2024"
        assert by_code["32"]["coverage_summary"] == {"total": 627, "scored": 321, "gated": 306}

        assert by_code["33"]["status"] == "Planned"
        assert by_code["33"]["has_data"] is False

        # Staging province must return 404 when not in ACTIVE_PROVINCES
        res_32 = client.get("/api/v1/regions/32")
        assert res_32.status_code == 404

    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32")
    with patch("backend.app.api.routers.regions._get_db_province_stats", return_value=db_stats):
        res_32_active = client.get("/api/v1/regions/32")
        assert res_32_active.status_code == 200
        data_32 = res_32_active.json()
        assert data_32["status"] == "Active"
        assert data_32["geojson_url"] == "/data/boundaries/32_kecamatan.geojson"


def test_name_resolution_order_and_ambiguity(monkeypatch):
    """
    Name lookup searches requested province first, then falls back to all active provinces.
    Ambiguous candidates include kemendagri_code, city_name, and province_name.
    """
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,33,34,35")

    wonosari_diy = {
        "id": "uuid-diy",
        "kemendagri_code": "34.03.010",
        "name": "Wonosari",
        "city_name": "Gunung Kidul",
        "province_name": "Provinsi DI Yogyakarta",
        "province_code": "34",
        "utm_srid": 32749,
    }
    wonosari_jateng = {
        "id": "uuid-jateng",
        "kemendagri_code": "33.10.220",
        "name": "Wonosari",
        "city_name": "Klaten",
        "province_name": "Provinsi Jawa Tengah",
        "province_code": "33",
        "utm_srid": 32749,
    }
    tebet_dki = {
        "id": "uuid-tebet",
        "kemendagri_code": "31.71.09",
        "name": "Tebet",
        "city_name": "Jakarta Selatan",
        "province_name": "Provinsi DKI Jakarta",
        "province_code": "31",
        "utm_srid": 32748,
    }

    calls = []

    class OrderMockCursor:
        def execute(self, query, params=None):
            calls.append((str(query), params))

        def fetchone(self):
            return None

        def fetchall(self):
            _, params = calls[-1]
            name_q = str(params[0]).lower()
            scope = params[2]
            if name_q == "wonosari":
                if scope == "34":
                    return [wonosari_diy]
                if isinstance(scope, list):
                    return [wonosari_jateng, wonosari_diy]
            if name_q == "tebet":
                if scope == "34":
                    return []
                if isinstance(scope, list) and "31" in scope:
                    return [tebet_dki]
            return []

    @contextmanager
    def mock_ctx():
        yield OrderMockCursor()

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_ctx):
        # 1. Requested province '34' matches DIY Wonosari first -> unique
        rec, err = resolve_district_record("Wonosari", province_code="34")
        assert err is None
        assert rec["kemendagri_code"] == "34.03.010"

        # 2. Without province_code, Wonosari across active provinces is ambiguous
        rec_amb, err_amb = resolve_district_record("Wonosari", province_code=None)
        assert rec_amb is None
        assert err_amb == "ambiguous"
        cands = resolve_district_candidates("Wonosari", province_code=None)
        msg = format_ambiguous_district_detail("Wonosari", cands)
        assert "33.10.220" in msg and "Klaten" in msg and "Jawa Tengah" in msg
        assert "34.03.010" in msg and "Gunung Kidul" in msg and "DI Yogyakarta" in msg

        # 3. Name not in requested province '34' falls back to all active provinces ('31')
        rec_tebet, err_tebet = resolve_district_record("Tebet", province_code="34")
        assert err_tebet is None
        assert rec_tebet["kemendagri_code"] == "31.71.09"


def test_chat_request_accepts_province_code_and_passes_to_tools(monkeypatch):
    """AgentChatRequest accepts active province_code and forwards it to tool execution and system prompt."""
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,34")
    req = AgentChatRequest(
        messages=[ChatMessage(role="user", content="Bagaimana skor Gondokusuman?")],
        province_code="34",
    )
    assert req.province_code == "34"

    prompt_34 = build_system_prompt("34")
    assert "DI Yogyakarta" in prompt_34
    assert "WorldPop" in prompt_34

    orchestrator = CognitiveSpatialAgentOrchestrator()
    captured = {}

    def fake_execute(tool_name, args, province_code=None):
        captured["tool_name"] = tool_name
        captured["province_code"] = province_code
        return {
            "kemendagri_code": "34.71.060",
            "district_code": "34.71.060",
            "district_name": "Gondokusuman",
            "population": 48275,
            "population_source": "Estimasi model WorldPop R2025A 2024",
            "composite_score": 54.54,
            "score_status": "Tersedia",
            "metrics_payload": [],
        }

    llm_resps = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_district_scorecard",
                            "arguments": {"district_code": "Gondokusuman"},
                        }
                    }
                ],
            },
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": (
                    "Skor komposit Kecamatan Gondokusuman di DI Yogyakarta adalah 54.54 "
                    "dengan populasi 48.275 jiwa (Estimasi model WorldPop R2025A 2024)."
                ),
            },
        },
    ]

    with patch.object(orchestrator, "_call_llm", side_effect=llm_resps), \
         patch("backend.app.agent.orchestrator.execute_tool_call", side_effect=fake_execute):
        resp = orchestrator.process_chat(req)
        assert captured["province_code"] == "34"
        assert resp.guardrail == "passed"
        assert resp.map_actions[0].payload["district_code"] == "34.71.060"


def test_gated_kecamatan_deterministic_fallback_output():
    """Gated kecamatan output includes 'Data tidak memadai' and coverage reason."""
    summary = build_deterministic_fallback_summary(
        [
            {
                "district_code": "32.02.010",
                "district_name": "Ciemas",
                "population": 66672,
                "population_source": "Estimasi model WorldPop R2025A 2024",
                "composite_score": None,
                "score_status": "Data tidak memadai",
                "coverage_reason": "Tidak ada SD terpetakan di OSM untuk kecamatan berpenduduk >= 1.600 jiwa",
                "metrics_payload": [
                    {
                        "facility_type": "sekolah_dasar",
                        "existing": 0,
                        "required": 42,
                        "compliance_pct": None,
                        "deficit": None,
                        "data_availability": "insufficient_local",
                        "scored": True,
                    }
                ],
            }
        ]
    )
    assert "Data tidak memadai" in summary
    assert "WorldPop" in summary
    assert "Tidak ada SD terpetakan" in summary


def test_districts_endpoints_require_db_data_even_when_env_active(monkeypatch):
    """If ACTIVE_PROVINCES includes '32' but DB has 0 rows for '32', districts/facilities return 404."""
    clear_regions_cache()
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,32")
    assert client.get("/api/v1/districts?province_code=32").status_code == 404
    assert client.get("/api/v1/facilities?province_code=32").status_code == 404
    with patch(
        "backend.app.api.routers.districts.resolve_district_record",
        return_value=({"id": "x", "kemendagri_code": "32.73.230", "province_code": "32"}, None),
    ):
        assert client.get("/api/v1/districts/32.73.230").status_code == 404


def test_chat_rejects_inactive_or_unknown_province_code(monkeypatch):
    """Inactive ('32') or unknown ('99') province_code is not injected into prompt or passed as active_prov."""
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")

    prompt_inactive = build_system_prompt("32")
    assert "Jawa Barat" not in prompt_inactive
    assert "WorldPop" not in prompt_inactive
    assert "DKI Jakarta" in prompt_inactive

    prompt_unknown = build_system_prompt("99")
    assert "kode 99" not in prompt_unknown
    assert "WorldPop" not in prompt_unknown
    assert "DKI Jakarta" in prompt_unknown

    orchestrator = CognitiveSpatialAgentOrchestrator()
    captured = {}

    def fake_execute(tool_name, args, province_code=None):
        captured["province_code"] = province_code
        return {"error": "Data wilayah ini belum tersedia (rencana v1.1)"}

    llm_resps = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_district_scorecard",
                            "arguments": {"district_code": "32.73.230"},
                        }
                    }
                ],
            },
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Data wilayah ini belum tersedia.",
            },
        },
    ]

    req = AgentChatRequest(
        messages=[ChatMessage(role="user", content="Skor Coblong?")],
        province_code="32",
    )
    with patch.object(orchestrator, "_call_llm", side_effect=llm_resps), \
         patch("backend.app.agent.orchestrator.execute_tool_call", side_effect=fake_execute):
        resp = orchestrator.process_chat(req)
        assert captured["province_code"] is None
        assert len(resp.tool_trace) == 1
        assert resp.tool_trace[0]["ok"] is False
        assert resp.map_actions == []


def test_resolve_district_code_blocks_error_and_inactive_province(monkeypatch):
    """_resolve_district_code returns None on tool error or inactive province record."""
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")
    orchestrator = CognitiveSpatialAgentOrchestrator()

    assert orchestrator._resolve_district_code("32.73.230", {"error": "unavailable"}) is None

    inactive_rec = {"kemendagri_code": "32.73.230", "province_code": "32"}
    with patch("backend.app.engine.spatial.resolve_district_record", return_value=(inactive_rec, None)):
        assert orchestrator._resolve_district_code("Coblong", {}) is None
