"""
Unit tests for Task U2: Indonesia-scale agent tools, province alias resolution,
2022 Papua split handling, numeric guardrails, fallback summaries, and out-of-scope checks.
Marker: unit.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch
import pytest

from backend.app.core.config import settings
from backend.app.agent.national import (
    resolve_province_target,
    get_methodology,
)
from backend.app.agent.guardrails import (
    build_allowed_numbers,
    validate_numeric_claims,
    validate_label_bindings,
    build_deterministic_fallback_summary,
)
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    ChatMessage,
    is_out_of_scope_request,
    build_system_prompt,
)
from backend.app.agent.tools import SPATIAL_AGENT_TOOLS, execute_tool_call

pytestmark = pytest.mark.unit

ALL_38_PROVS = ",".join([
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "21",
    "31", "32", "33", "34", "35", "36",
    "51", "52", "53",
    "61", "62", "63", "64", "65",
    "71", "72", "73", "74", "75", "76",
    "81", "82",
    "91", "92", "93", "94", "95", "96",
])


def test_province_alias_resolution_and_papua_split(monkeypatch):
    """Resolves common province names/aliases/codes and handles the 2022 Papua 6-province split."""
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", ALL_38_PROVS)

    cases = [
        ("Jabar", "32"),
        ("Jawa Barat", "32"),
        ("DIY", "34"),
        ("DI Yogyakarta", "34"),
        ("Jogja", "34"),
        ("DKI", "31"),
        ("Jakarta", "31"),
        ("31", "31"),
        ("Jateng", "33"),
        ("Jatim", "35"),
        ("Sumut", "12"),
        ("Sumatra Barat", "13"),
        ("Babel", "19"),
        ("Kepri", "21"),
        ("NTB", "52"),
        ("NTT", "53"),
        ("Kaltim", "64"),
        ("Sulsel", "73"),
        ("Malut", "82"),
        ("Bali", "51"),
        ("Papua Barat", "92"),
        ("Papua Selatan", "93"),
        ("Papua Tengah", "94"),
        ("Papua Pegunungan", "95"),
        ("Papua Barat Daya", "96"),
        ("Provinsi Papua", "91"),
        ("91", "91"),
    ]
    for query, expected_code in cases:
        res = resolve_province_target(query)
        assert "error" not in res, f"Unexpected error for '{query}': {res}"
        assert res["is_group"] is False
        assert res["codes"] == [expected_code]

    # Bare "Papua" returns the 2022 6-province group with explicit ambiguity note
    papua_group = resolve_province_target("Papua")
    assert papua_group["is_group"] is True
    assert papua_group["codes"] == ["91", "92", "93", "94", "95", "96"]
    assert "2022" in papua_group["ambiguity_note"]

    # Unknown province returns error
    unknown = resolve_province_target("Atlantis")
    assert "error" in unknown

    # Inactive province enforces ACTIVE_PROVINCES
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", "31")
    inactive = resolve_province_target("Jawa Barat")
    assert "belum tersedia" in inactive["error"]


def test_build_allowed_numbers_and_guardrail_for_national_outputs():
    """
    build_allowed_numbers extracts nested lists/dicts and supports 1-decimal rounding (13.3 vs 13.27),
    safe constants (38, 2004, 2024, 2026, SNI digits), and rank numbers 1-10 in ranked lists.
    """
    national_out = {
        "tool": "get_national_overview",
        "active_provinces_count": 38,
        "total_kecamatan": 7033,
        "scored_kecamatan_count": 1878,
        "insufficient_data_kecamatan_count": 5155,
        "national_average_composite_score": 19.90,
        "provinces": [
            {
                "province_code": "32",
                "province_name": "Jawa Barat",
                "total_kecamatan": 627,
                "scored_kecamatan_count": 321,
                "average_composite_score": 13.27,
                "total_population": 50352580,
            },
            {
                "province_code": "51",
                "province_name": "Bali",
                "total_kecamatan": 57,
                "scored_kecamatan_count": 37,
                "average_composite_score": 8.03,
                "total_population": 4517203,
            },
        ],
    }
    rank_out = {
        "tool": "rank_districts",
        "scope": "Indonesia (Nasional)",
        "order": "highest",
        "metric": "composite",
        "results": [
            {"rank": 1, "district_name": "Batang Merangin", "province_name": "Jambi", "score": 100.0},
            {"rank": 2, "district_name": "Maro Sebo Ilir", "province_name": "Jambi", "score": 100.0},
            {"rank": 10, "district_name": "Contoh", "province_name": "DKI Jakarta", "score": 84.86},
        ],
    }

    allowed = build_allowed_numbers([national_out, rank_out])
    assert 13.27 in allowed
    assert 13.3 in allowed
    assert 8.03 in allowed
    assert 8.0 in allowed
    assert 50352580.0 in allowed
    assert 38.0 in allowed
    assert 2004.0 in allowed
    assert 2024.0 in allowed
    assert 2026.0 in allowed

    valid_reply = (
        "Indonesia memiliki 38 provinsi aktif dan 7.033 kecamatan "
        "(1.878 terukur dan 5.155 berstatus Data tidak memadai). "
        "Rata-rata nasional adalah 19,9 berdasarkan SNI 03-1733-2004 (dibandingkan rencana SNI 1733:2026). "
        "Jawa Barat mencatat rata-rata 13,3 (13.27) dari 321 kecamatan terukur, sedangkan Bali 8,03.\n"
        "| Peringkat | Kecamatan | Skor |\n"
        "| 1 | Batang Merangin | 100.0 |\n"
        "| 2 | Maro Sebo Ilir | 100.0 |\n"
        "Peringkat ke-3 hingga ke-5 dan top 10 teratas dapat dilihat pada data 2024."
    )
    ok_num, unsup = validate_numeric_claims(valid_reply, allowed)
    assert ok_num is True, f"Unexpected unsupported numbers: {unsup}"
    ok_lbl, mislab = validate_label_bindings(valid_reply, [national_out, rank_out])
    assert ok_lbl is True, f"Unexpected mislabeled numbers: {mislab}"

    # Millions abbreviation ("juta") allowed only when backed by tool population
    juta_ok, juta_unsup = validate_numeric_claims(
        "Populasi Jawa Barat sekitar 50,35 juta jiwa sedangkan Bali sekitar 4,51 juta jiwa.",
        allowed,
    )
    assert juta_ok is True, f"Expected juta abbreviation to pass: {juta_unsup}"

    juta_bad, juta_unsup_bad = validate_numeric_claims(
        "Populasi Jawa Barat adalah 50,35 dan Bali 99,9 juta.",
        allowed,
    )
    assert juta_bad is False
    assert "50,35" in juta_unsup_bad
    assert "99,9" in juta_unsup_bad

    # Fabricated numbers must still be caught
    bad_reply = "Rata-rata skor Bali adalah 99.75 dengan 999 kecamatan."
    ok_bad, unsup_bad = validate_numeric_claims(bad_reply, allowed)
    assert ok_bad is False
    assert "99.75" in unsup_bad
    assert "999" in unsup_bad


def test_label_bindings_unchanged_for_kecamatan_and_multi_tool():
    """Kecamatan label bindings still catch swaps while allowing province averages in multi-tool turns."""
    kec_out = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "composite_score": 54.61,
        "pillar_scores": {"lifeline_health": {"score": 79.17}},
        "metrics_payload": [
            {"facility_type": "puskesmas_kelurahan", "existing": 7, "required": 8, "deficit": -1, "compliance_pct": 87.5}
        ],
    }
    prov_out = {
        "tool": "get_province_summary",
        "province_code": "31",
        "province_name": "DKI Jakarta",
        "average_composite_score": 47.29,
    }

    # Wrong kecamatan composite still caught
    ok_bad, mislab = validate_label_bindings("Skor komposit Tebet adalah 79.17.", [kec_out])
    assert ok_bad is False
    assert mislab[0]["found_label"] == "pillar_score:lifeline_health"

    # Multi-tool turn mentioning province average passes
    ok_multi, mislab_multi = validate_label_bindings(
        "Skor komposit Tebet adalah 54.61, sedangkan rata-rata skor komposit provinsi DKI Jakarta adalah 47.29.",
        [kec_out, prov_out],
    )
    assert ok_multi is True, f"Multi-tool mislabeled: {mislab_multi}"


def test_deterministic_fallback_summaries_for_national_and_province_tools():
    """Fallback builder renders national/province/rank/compare/methodology outputs without 'Kecamatan' header."""
    nat_text = build_deterministic_fallback_summary([{
        "tool": "get_national_overview",
        "active_provinces_count": 38,
        "provinces_with_composite_score_count": 15,
        "provinces_without_composite_score_count": 23,
        "total_kecamatan": 7033,
        "scored_kecamatan_count": 1878,
        "insufficient_data_kecamatan_count": 5155,
        "locally_adequate_osm_count": 2942,
        "locally_gated_osm_count": 4086,
        "national_average_composite_score": 19.90,
        "averaging_rule": "Unweighted mean of 1878 scored kecamatan.",
        "total_population": 281883235,
        "population_sources_summary": "BPS 2024 / WorldPop R2025A 2024",
        "highest_average_province": {"province_code": "31", "province_name": "DKI Jakarta", "average_composite_score": 47.29},
        "lowest_average_province": {"province_code": "51", "province_name": "Bali", "average_composite_score": 8.03},
        "provinces": [],
    }])
    assert "Ringkasan Nasional (Indonesia)" in nat_text
    assert "Profil Wilayah Kecamatan" not in nat_text
    assert "19.90" in nat_text
    assert "Bali" in nat_text

    papua_text = build_deterministic_fallback_summary([{
        "tool": "get_province_summary",
        "is_province_group": True,
        "province_name": "Wilayah Papua (6 Provinsi Pemekaran 2022)",
        "ambiguity_note": "Nama 'Papua' mencakup 6 provinsi pasca pemekaran tahun 2022.",
        "total_kecamatan": 601,
        "scored_kecamatan_count": 0,
        "insufficient_data_kecamatan_count": 601,
        "locally_adequate_osm_count": 241,
        "locally_gated_osm_count": 356,
        "total_population": 5607092,
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "provinces_matched": [
            {"province_code": "91", "province_name": "Papua", "total_kecamatan": 97, "locally_adequate_osm_count": 31, "locally_gated_osm_count": 66, "scored_kecamatan_count": 0, "total_population": 1055660}
        ],
    }])
    assert "Wilayah Papua" in papua_text
    assert "Profil Wilayah Kecamatan" not in papua_text
    assert "601" in papua_text

    rank_text = build_deterministic_fallback_summary([{
        "tool": "rank_districts",
        "scope": "Indonesia (Nasional)",
        "order": "highest",
        "metric": "composite",
        "metric_label": "Indeks Kecukupan Fasilitas Dasar (Komposit)",
        "results": [
            {"rank": 1, "district_name": "Batang Merangin", "city_name": "Kerinci", "province_name": "Jambi", "score": 100.0}
        ],
    }])
    assert "Peringkat Kecamatan Tertinggi" in rank_text
    assert "Batang Merangin" in rank_text

    cmp_text = build_deterministic_fallback_summary([{
        "tool": "compare_provinces",
        "compared_count": 2,
        "provinces": [
            {"province_code": "32", "province_name": "Jawa Barat", "average_composite_score": 13.32, "scored_kecamatan_count": 321, "total_kecamatan": 627, "insufficient_data_kecamatan_count": 306, "total_population": 50352580, "population_source": "WorldPop"},
            {"province_code": "51", "province_name": "Bali", "average_composite_score": 8.03, "scored_kecamatan_count": 37, "total_kecamatan": 57, "insufficient_data_kecamatan_count": 20, "total_population": 4517203, "population_source": "WorldPop"},
        ],
        "note": "Kedua provinsi memiliki skor komposit.",
    }])
    assert "Perbandingan Provinsi" in cmp_text
    assert "Jawa Barat" in cmp_text and "Bali" in cmp_text

    meth_text = build_deterministic_fallback_summary([{
        "tool": "get_methodology",
        "standard_reference": "SNI 03-1733-2004",
        "total_standards_catalog": 16,
        "scored_standards_count": 7,
        "informational_standards_count": 9,
        "scoring_rules": {"facility_compliance": "ceil(pop/threshold)", "composite_reweighting": "proporsional"},
        "data_tidak_memadai_rule": {"local_sd_gate_rule": "SD >= 1", "null_handling": "NULL"},
        "standards_table": [],
    }])
    assert "Metodologi & Standar" in meth_text
    assert "SNI 03-1733-2004" in meth_text


def test_out_of_scope_refuses_permits_and_allows_7_example_and_data_izin_questions():
    """Out-of-scope still refuses permit decisions/legal advice, never the 7 national/concept questions or data queries mentioning 'izin'."""
    must_refuse = [
        "Apakah izin proyek apartemen X boleh disetujui?",
        "Apakah proyek superblok 3.000 unit di Tebet ini boleh disetujui izin pembangunannya?",
        "Apakah izin pembangunan gedung ini sah secara hukum?",
        "Tolong berikan rekomendasi izin untuk mal baru di Bandung.",
        "Apakah proyek ini boleh diberikan izin oleh dinas?",
    ]
    for q in must_refuse:
        assert is_out_of_scope_request(q) is True, f"Should refuse: {q}"

    must_allow = [
        "Provinsi mana yang skor rata-ratanya paling rendah?",
        "Berapa kecamatan di Indonesia yang datanya memadai?",
        "Bandingkan Jawa Barat dan Bali",
        "Kecamatan dengan skor tertinggi di Indonesia?",
        "Bagaimana kondisi fasilitas di Papua?",
        "Apa itu SNI 03-1733-2004?",
        "Bagaimana skor dihitung?",
        "Data fasilitas apa yang perlu diperiksa sebelum pengajuan izin di Jawa Barat?",
        "Apakah data perizinan atau fasilitas keluar dalam ringkasan nasional?",
        "Berapa skor wilayah yang memiliki banyak pengajuan izin bangunan?",
    ]
    for q in must_allow:
        assert is_out_of_scope_request(q) is False, f"Must not refuse: {q}"


def test_national_tools_registered_and_work_from_any_active_province(monkeypatch):
    """All new tools are registered in SPATIAL_AGENT_TOOLS and execute regardless of active province_code."""
    tool_names = {t["function"]["name"] for t in SPATIAL_AGENT_TOOLS}
    for expected in (
        "get_national_overview",
        "get_province_summary",
        "rank_districts",
        "compare_provinces",
        "get_methodology",
    ):
        assert expected in tool_names

    prompt_31 = build_system_prompt("31")
    assert "get_national_overview" in prompt_31
    assert "get_province_summary" in prompt_31
    assert "get_methodology" in prompt_31

    # Methodology tool works offline via fallback even if DB cursor raises
    @contextmanager
    def failing_db():
        raise RuntimeError("offline")
        yield

    with patch("backend.app.agent.national.get_db_cursor", side_effect=failing_db):
        res = execute_tool_call("get_methodology", {}, province_code="31")
        assert res["total_standards_catalog"] == 16
        assert res["scored_standards_count"] == 7

    # Orchestrator executes national tool with active province_code="31" without forcing kecamatan lookup
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", ALL_38_PROVS)
    orch = CognitiveSpatialAgentOrchestrator()
    mock_nat = {
        "tool": "get_national_overview",
        "active_provinces_count": 38,
        "total_kecamatan": 7033,
        "scored_kecamatan_count": 1878,
        "insufficient_data_kecamatan_count": 5155,
        "national_average_composite_score": 19.90,
        "lowest_average_province": {"province_code": "51", "province_name": "Bali", "average_composite_score": 8.03},
        "provinces": [],
    }
    llm_resps = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "get_national_overview", "arguments": {}}}],
            },
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Provinsi dengan rata-rata skor terendah di Indonesia adalah Bali dengan skor 8,03.",
            },
        },
    ]
    req = AgentChatRequest(
        messages=[ChatMessage(role="user", content="Provinsi mana yang skor rata-ratanya paling rendah?")],
        province_code="31",
    )
    with patch.object(orch, "_call_llm", side_effect=llm_resps), \
         patch("backend.app.agent.orchestrator.execute_tool_call", return_value=mock_nat):
        resp = orch.process_chat(req)
        assert resp.guardrail == "passed"
        assert resp.map_actions == []
        assert [t["name"] for t in resp.tool_calls_executed] == ["get_national_overview"]
