"""
Unit tests for Task P1: Papua regions catalogue ordering/metadata,
PBF routing + 2-to-6 province reassignment map in load_region.py,
and chat bare place-name robustness.
Marker: unit.
"""

from contextlib import contextmanager
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.app.agent.orchestrator import (
    AgentChatRequest,
    ChatMessage,
    CognitiveSpatialAgentOrchestrator,
    build_system_prompt,
)
from backend.app.api.routers.regions import REGIONS_CATALOG, clear_regions_cache
from backend.app.core.config import settings
from backend.app.main import app
from pipeline.load_region import (
    PAPUA_KABUPATEN_MAP,
    SUPPORTED_PROVINCES,
    resolve_pbf_specs_for_province,
)

pytestmark = pytest.mark.unit
client = TestClient(app)

PAPUA_CODES = ["91", "92", "93", "94", "95", "96"]


def test_regions_catalog_includes_papua_ordered_by_code():
    """All 6 Papua provinces exist in REGIONS_CATALOG and /api/v1/regions returns codes sorted."""
    clear_regions_cache()
    for code in PAPUA_CODES:
        assert code in REGIONS_CATALOG
        entry = REGIONS_CATALOG[code]
        assert entry["geojson_url"] == f"/data/boundaries/{code}_kecamatan.geojson"
        assert entry["total_districts"] > 0
        assert len(entry["bbox"]) == 4
        assert len(entry["center"]) == 2
        assert 32752 <= entry["utm_srid"] <= 32754

    res = client.get("/api/v1/regions")
    assert res.status_code == 200
    codes = [r["province_code"] for r in res.json()]
    assert codes == sorted(codes)
    assert set(PAPUA_CODES).issubset(set(codes))


def test_load_region_papua_pbf_routing_and_2to6_kab_map():
    """Papua PBF routing maps 91-96 -> papua-latest.osm.pbf and maps all 42 kab/kota cleanly."""
    for code in PAPUA_CODES:
        assert SUPPORTED_PROVINCES[code]["island"] == "papua"
        specs = resolve_pbf_specs_for_province(code)
        assert [s["path"].name for s in specs] == ["papua-latest.osm.pbf"]

    override_specs = resolve_pbf_specs_for_province("34", pbf_override="papua")
    assert [s["path"].name for s in override_specs] == ["papua-latest.osm.pbf"]

    assert len(PAPUA_KABUPATEN_MAP) == 42
    kab_codes = [kab for _, kab in PAPUA_KABUPATEN_MAP.values()]
    assert len(set(kab_codes)) == 42
    for adm2, (prov, kab) in PAPUA_KABUPATEN_MAP.items():
        assert adm2.startswith(("ID91", "ID94"))
        assert prov in PAPUA_CODES
        assert kab.startswith(f"{prov}.")


def test_chat_bare_place_name_prompt_rule_and_deterministic_fallback(monkeypatch):
    """System prompt instructs place-name lookup and round-1 fallback resolves bare district in active province."""
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31,73")
    prompt_73 = build_system_prompt("73")
    assert "nama tempat" in prompt_73.lower()
    assert "get_district_scorecard" in prompt_73

    orchestrator = CognitiveSpatialAgentOrchestrator()

    class MockCursor:
        def execute(self, query, params=None):
            self.params = params

        def fetchall(self):
            return [
                {"kemendagri_code": "73.71.050", "name": "Ujung Pandang"},
                {"kemendagri_code": "73.71.030", "name": "Tamalate"},
            ]

    @contextmanager
    def mock_ctx():
        yield MockCursor()

    def fake_execute(tool_name, args, province_code=None):
        assert tool_name == "get_district_scorecard"
        assert args == {"district_code": "73.71.050"}
        assert province_code == "73"
        return {
            "kemendagri_code": "73.71.050",
            "district_code": "73.71.050",
            "district_name": "Ujung Pandang",
            "population": 38025,
            "population_source": "Estimasi model WorldPop R2025A 2024",
            "composite_score": 65.28,
            "score_status": "Tersedia",
            "metrics_payload": [],
        }

    llm_resps = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Apakah Ujung Pandang yang Anda maksud adalah kecamatan di Makassar?",
            },
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": (
                    "Skor Kecamatan Ujung Pandang adalah 65.28 dengan populasi 38.025 jiwa "
                    "(Estimasi model WorldPop R2025A 2024)."
                ),
            },
        },
    ]

    req = AgentChatRequest(
        messages=[ChatMessage(role="user", content="Bagaimana skor Ujung Pandang?")],
        province_code="73",
    )
    with patch("backend.app.agent.orchestrator.get_db_cursor", side_effect=mock_ctx), \
         patch.object(orchestrator, "_call_llm", side_effect=llm_resps), \
         patch("backend.app.agent.orchestrator.execute_tool_call", side_effect=fake_execute):
        resp = orchestrator.process_chat(req)
        assert [t["name"] for t in resp.tool_calls_executed] == ["get_district_scorecard"]
        assert resp.map_actions[0].payload["district_code"] == "73.71.050"
        assert resp.guardrail == "passed"
