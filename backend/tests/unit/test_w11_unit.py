"""
Unit Tests for W11-INT Integration Defect Fixes (D1 through D5, R1, R4, R5, W11-INT.2 to 4).
Runs under pytest marker: unit.
"""

import pytest
import re
from unittest.mock import patch, MagicMock

from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    ChatMessage,
    MapActionEvent,
    is_out_of_scope_request,
    OUT_OF_SCOPE_REFUSAL,
    SYSTEM_PROMPT
)
from backend.app.agent.tools import SPATIAL_AGENT_TOOLS
from backend.app.agent.guardrails import (
    validate_numeric_claims,
    validate_label_bindings,
    build_allowed_numbers,
    validate_and_sanitize_citations
)
from backend.app.engine.simulation import (
    WhatIfSimulationEngine,
    SuperblockSimulationRequest
)

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------------
# D1: Simulation Assumptions Data Shape
# -----------------------------------------------------------------------------
def test_d1_simulation_assumptions_shape():
    """
    Asserts every assumption value in simulation outputs is either a scalar
    or an object with known keys (e.g. composite_weights), avoiding [object Object].
    """
    sample_standards = [
        {
            "facility_type": "puskesmas_kelurahan",
            "pillar": "lifeline_health",
            "population_threshold": 30000,
            "service_radius_meters": 1000,
            "legal_reference": "SNI 03-1733-2004",
            "scored": True
        }
    ]
    delta = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.09",
        district_name="Tebet",
        baseline_population=228450,
        existing_facility_counts={"puskesmas_kelurahan": 5},
        regulatory_standards=sample_standards,
        pop_shock_count=5000
    )
    assumptions = delta.assumptions
    assert isinstance(assumptions, dict)
    assert len(assumptions) > 0

    known_keys = {
        "lifeline_health", "education", "urban_livability", "mobility_connectivity",
        "value", "unit", "source", "note", "description"
    }
    for key, val in assumptions.items():
        if isinstance(val, (int, float, str, bool)):
            continue
        elif isinstance(val, dict):
            for sub_k, sub_v in val.items():
                assert sub_k in known_keys, f"Unknown subkey '{sub_k}' in assumptions['{key}']"
                assert isinstance(sub_v, (int, float, str, bool)), f"Non-scalar subval in assumptions['{key}']['{sub_k}']"
        else:
            pytest.fail(f"Unexpected assumption value type for key '{key}': {type(val)}")

    sb_req = SuperblockSimulationRequest(
        district_code="31.71.09",
        project_name="Apartemen Tebet",
        residential_units=1500,
        site_area_m2=20000.0
    )
    sb_impact = WhatIfSimulationEngine.simulate_superblock_development(
        req=sb_req,
        baseline_population=228450,
        district_name="Tebet",
        existing_facility_counts={"puskesmas_kelurahan": 5},
        regulatory_standards=sample_standards
    )
    sb_assumptions = sb_impact.assumptions
    assert isinstance(sb_assumptions, dict)
    assert len(sb_assumptions) > 0
    for key, val in sb_assumptions.items():
        if isinstance(val, (int, float, str, bool)):
            continue
        elif isinstance(val, dict):
            for sub_k, sub_v in val.items():
                assert sub_k in known_keys, f"Unknown subkey '{sub_k}' in sb_assumptions['{key}']"
                assert isinstance(sub_v, (int, float, str, bool)), f"Non-scalar subval in sb_assumptions['{key}']['{sub_k}']"
        else:
            pytest.fail(f"Invalid type for {key}: {type(val)}")


def test_d1_frontend_assumptions_and_obligations_xss_prevention():
    """
    Static check verifying that:
    1. frontend/js/utils/dom.js defines formatAssumptionValue.
    2. frontend/js/panels/simulation.js imports formatAssumptionValue and uses it with textContent.
    3. Renders res-obligations-list using textContent / safe DOM nodes.
    """
    import os
    sim_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "js", "panels", "simulation.js")
    with open(sim_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    dom_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "js", "utils", "dom.js")
    with open(dom_js_path, "r", encoding="utf-8") as f:
        dom_content = f.read()

    assert "function formatAssumptionValue" in dom_content
    assert "formatAssumptionValue" in content
    assert "strong.textContent = formatAssumptionValue(v)" in content
    assert "assumpTableBody.innerHTML" not in content or "${v}" not in content
    assert "${o.regulation_code}" not in content
    assert "${o.obligation_text}" not in content
    assert "res-obligations-list" in content


# -----------------------------------------------------------------------------
# D2: Canonical District Code Resolution & Map Actions
# -----------------------------------------------------------------------------
def test_d2_map_action_resolves_district_name_to_code():
    orchestrator = CognitiveSpatialAgentOrchestrator()
    map_actions = []
    mock_db_row = {"kemendagri_code": "31.71.09", "name": "Tebet"}

    def mock_db_cursor_ctx():
        class MockCursor:
            def execute(self, query, params=None):
                pass
            def fetchone(self):
                return mock_db_row
            def fetchall(self):
                return [mock_db_row]
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockCursor()

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_db_cursor_ctx), \
         patch("backend.app.agent.orchestrator.get_db_cursor", side_effect=mock_db_cursor_ctx):
        args = {"district_code": "Tebet"}
        output = {"composite_score": 40.71, "district_name": "Tebet"}
        orchestrator._extract_map_actions("get_district_scorecard", args, output, map_actions)

        assert len(map_actions) == 1
        assert map_actions[0].action_type == "fly_to"
        assert map_actions[0].payload["district_code"] == "31.71.09"


def test_d2_map_action_unknown_district_emits_no_action():
    orchestrator = CognitiveSpatialAgentOrchestrator()
    map_actions = []

    def mock_db_cursor_empty():
        class MockCursor:
            def execute(self, query, params=None):
                pass
            def fetchone(self):
                return None
            def fetchall(self):
                return []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockCursor()

    with patch("backend.app.engine.spatial.get_db_cursor", side_effect=mock_db_cursor_empty), \
         patch("backend.app.agent.orchestrator.get_db_cursor", side_effect=mock_db_cursor_empty):
        args = {"district_code": "KotaAtlantis"}
        output = {"error": "District not found"}
        orchestrator._extract_map_actions("get_district_scorecard", args, output, map_actions)

        assert len(map_actions) == 0


# -----------------------------------------------------------------------------
# D3: Guardrail Compliance Percentages & Invented Numbers
# -----------------------------------------------------------------------------
def test_d3_guardrail_accepts_valid_compliance_percentage():
    tool_outputs = [{
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "composite_score": 40.71,
        "metrics_payload": [
            {
                "facility_type": "pos_damkar",
                "pillar": "lifeline_health",
                "compliance_pct": 100.0,
                "existing": 1,
                "required": 1,
                "deficit": 0,
                "scored": True
            }
        ]
    }]

    allowed = build_allowed_numbers(tool_outputs)
    valid_texts = [
        "pos_damkar 100%",
        "Pos damkar telah memenuhi standar (100%).",
        "Tingkat keterpenuhan pos damkar adalah 100,0%",
        "pos_damkar memiliki kebutuhan 1 unit dengan kepatuhan 100%"
    ]

    for text in valid_texts:
        passed_num, unsupp = validate_numeric_claims(text, allowed)
        passed_lbl, mislab = validate_label_bindings(text, tool_outputs)
        assert passed_num is True, f"Failed numeric claims for '{text}': {unsupp}"
        assert passed_lbl is True, f"Failed label bindings for '{text}': {mislab}"


def test_d3_guardrail_catches_invented_percentage_and_mislabel():
    tool_outputs = [{
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "composite_score": 40.71,
        "metrics_payload": [
            {
                "facility_type": "pos_damkar",
                "pillar": "lifeline_health",
                "compliance_pct": 100.0,
                "existing": 1,
                "required": 1,
                "deficit": 0,
                "scored": True
            },
            {
                "facility_type": "sekolah_dasar",
                "pillar": "education",
                "compliance_pct": 39.44,
                "existing": 56,
                "required": 142,
                "deficit": -86,
                "scored": True
            }
        ]
    }]

    allowed = build_allowed_numbers(tool_outputs)

    text_invented = "Capaian kepatuhan pos damkar adalah 77%."
    p_num, unsupp = validate_numeric_claims(text_invented, allowed)
    assert p_num is False
    assert "77%" in unsupp

    text_mislabeled = "Capaian pos_damkar adalah 39.44%."
    p_num2, _ = validate_numeric_claims(text_mislabeled, allowed)
    assert p_num2 is True
    p_lbl2, mislab2 = validate_label_bindings(text_mislabeled, tool_outputs)
    assert p_lbl2 is False
    assert any("pos_damkar" in m["expected_label"] for m in mislab2)


# -----------------------------------------------------------------------------
# D4: Superblock Reworded Text & Permit Request Refusal
# -----------------------------------------------------------------------------
def test_d4_superblock_assumption_text_survives_sanitization():
    text = "Parameter asumsi tim (belum diverifikasi terhadap peraturan daerah): RTH 20%, retensi 150 mm/hari, KDB 50%"
    sanitized, _, removed = validate_and_sanitize_citations(text, set())
    assert "belum diverifikasi ke )" not in sanitized
    assert "belum diverifikasi terhadap peraturan daerah" in sanitized
    assert len(removed) == 0


def test_d4_permit_refusal_patterns():
    permit_phrasings = [
        "apakah proyek superblok ini boleh diberi izin?",
        "Apakah izin pembangunan proyek superblok di Tebet sah?",
        "Bagaimana rekomendasi keputusan perizinan untuk apartemen ini?",
        "Apakah proyek ini layak diberikan izin oleh dinas?",
        "Bisakah Pemprov DKI memberikan izin untuk superblock ini?"
    ]

    for q in permit_phrasings:
        assert is_out_of_scope_request(q) is True, f"Failed to refuse permit question: {q}"

    information_questions = [
        "apakah ada data izin bangunan di Tebet?",
        "apakah simulasi ini bisa dipakai sebagai bahan kajian perizinan?",
        "apakah regulasi perizinan mencakup ketentuan RTH?",
        "apakah riwayat perizinan gedung ini tersimpan di sistem?"
    ]

    for q in information_questions:
        assert is_out_of_scope_request(q) is False, f"Erroneously refused information question: {q}"

    normal_questions = [
        "Simulasikan proyek superblok 1000 unit di Tebet",
        "Berapa estimasi kebutuhan RTH untuk superblok seluas 15000 m2 di Tebet?",
        "Bagaimana dampak beban populasi dari proyek superblok terhadap fasilitas sekolah dan puskesmas?"
    ]

    for q in normal_questions:
        assert is_out_of_scope_request(q) is False, f"Erroneously refused valid superblock question: {q}"


# -----------------------------------------------------------------------------
# D5: Tool Descriptions & System Prompt Distinction for Deficit vs Coverage
# -----------------------------------------------------------------------------
def test_d5_tool_descriptions_and_system_prompt_distinction():
    tools_dict = {t["function"]["name"]: t["function"] for t in SPATIAL_AGENT_TOOLS}

    scorecard_desc = tools_dict["get_district_scorecard"]["description"]
    assert "defisit unit" in scorecard_desc.lower()
    assert "kebutuhan" in scorecard_desc.lower()

    blankspot_desc = tools_dict["get_unserved_blank_spots"]["description"]
    assert "cakupan" in blankspot_desc.lower()
    assert "bukan" in blankspot_desc.lower() or "not" in blankspot_desc.lower()

    assert "PEMBEDAAN DEFISIT UNIT VS CAKUPAN RADIUS" in SYSTEM_PROMPT
    assert "defisit unit" in SYSTEM_PROMPT.lower()
    assert "cakupan %" in SYSTEM_PROMPT.lower()


# -----------------------------------------------------------------------------
# R1: SYSTEM_PROMPT & Tool Descriptions Digits Check
# -----------------------------------------------------------------------------
def test_r1_system_prompt_and_tool_descriptions_contain_no_digits():
    cleaned_prompt = re.sub(r"\b[1-5]\.\s*(?:ATURAN\s*#[1-5]|Gaya\s+Bahasa)?", "", SYSTEM_PROMPT)
    digits_prompt = re.findall(r"\d+", cleaned_prompt)
    assert len(digits_prompt) == 0, f"Found concrete digits in SYSTEM_PROMPT: {digits_prompt}"

    for tool in SPATIAL_AGENT_TOOLS:
        fn = tool["function"]
        desc = fn.get("description", "")
        cleaned_desc = re.sub(r"SNI\s+03-1733-2004", "", desc)
        digits_desc = re.findall(r"\d+", cleaned_desc)
        assert len(digits_desc) == 0, f"Found concrete digits in tool '{fn.get('name')}' description: {digits_desc}"

        props = fn.get("parameters", {}).get("properties", {})
        for p_name, p_val in props.items():
            p_desc = p_val.get("description", "")
            cleaned_pdesc = re.sub(r"SNI\s+03-1733-2004", "", p_desc)
            p_digits = re.findall(r"\d+", cleaned_pdesc)
            assert len(p_digits) == 0, f"Found concrete digits in parameter '{p_name}' of tool '{fn.get('name')}': {p_digits}"


# -----------------------------------------------------------------------------
# R4: Superblock Simulation Map Action Payload
# -----------------------------------------------------------------------------
def test_r4_superblock_simulation_map_action_payload():
    orchestrator = CognitiveSpatialAgentOrchestrator()
    map_actions = []
    args = {"district_code": "31.71.09", "project_name": "Mega Proyek"}
    output = {
        "district_code": "31.71.09",
        "project_name": "Mega Proyek",
        "impact_level": "Tinggi",
        "simulation_delta": {
            "score_delta": -4.25,
            "simulated_composite_score": 36.46
        }
    }
    orchestrator._extract_map_actions("run_superblock_simulation", args, output, map_actions)
    assert len(map_actions) == 1
    act = map_actions[0]
    assert act.action_type == "render_simulation_layer"
    assert act.payload["district_code"] == "31.71.09"
    assert act.payload["score_delta"] == -4.25
    assert act.payload["simulated_score"] == 36.46


# -----------------------------------------------------------------------------
# R5: Guardrail Bypass Prevention & Blank Spot Multi-tool Verification
# -----------------------------------------------------------------------------
def test_r5_guardrail_catches_all_bypasses_and_allows_blank_spots():
    tool_outputs = [
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "composite_score": 40.71,
            "metrics_payload": [
                {
                    "facility_type": "pos_damkar",
                    "pillar": "lifeline_health",
                    "compliance_pct": 100.0,
                    "existing": 1,
                    "required": 1,
                    "deficit": 0,
                    "scored": True
                },
                {
                    "facility_type": "sekolah_dasar",
                    "pillar": "education",
                    "compliance_pct": 39.44,
                    "existing": 56,
                    "required": 142,
                    "deficit": -86,
                    "scored": True
                },
                {
                    "facility_type": "rumah_sakit",
                    "pillar": "lifeline_health",
                    "compliance_pct": None,
                    "existing": 2,
                    "required": 0,
                    "deficit": 0,
                    "scored": False
                },
                {
                    "facility_type": "posyandu",
                    "pillar": "lifeline_health",
                    "compliance_pct": None,
                    "existing": 15,
                    "required": 0,
                    "deficit": 0,
                    "scored": False
                }
            ]
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "facility_type": "puskesmas_kelurahan",
            "coverage_percentage_val": 72.5,
            "coverage_percentage": "72.5%",
            "unserved_percentage_val": 27.5,
            "coverage_pct": 72.5
        }
    ]

    allowed = build_allowed_numbers(tool_outputs)

    p1, m1 = validate_label_bindings("Defisit sekolah dasar adalah 39.44%", tool_outputs)
    assert p1 is False

    p1b, m1b = validate_label_bindings("Defisit pos_damkar adalah 100%", tool_outputs)
    assert p1b is False

    p2, m2 = validate_label_bindings("Kepatuhan rumah sakit telah memenuhi standar (100%)", tool_outputs)
    assert p2 is False

    p2b, m2b = validate_label_bindings("Kepatuhan posyandu adalah 39.44%", tool_outputs)
    assert p2b is False

    p3, m3 = validate_label_bindings("Kepatuhan sekolah dasar adalah 100", tool_outputs)
    assert p3 is False

    text_multi = "Cakupan puskesmas kelurahan di Tebet mencapai 72.5% dengan skor kecamatan 40.71."
    p_num, unsupp = validate_numeric_claims(text_multi, allowed)
    p_lbl, mislab = validate_label_bindings(text_multi, tool_outputs)
    assert p_num is True
    assert p_lbl is True

    p_def_bad, m_def_bad = validate_label_bindings("Defisit pos_damkar adalah 2 unit", tool_outputs)
    assert p_def_bad is False

    p_req_bad, m_req_bad = validate_label_bindings("Kebutuhan pos_damkar adalah 5 unit", tool_outputs)
    assert p_req_bad is False


def test_r5_realistic_multi_metric_answers_pass():
    tool_outputs = [
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "composite_score": 54.61,
            "pillar_scores": {
                "lifeline_health": {"score": 79.17},
                "education": {"score": 25.14}
            },
            "metrics_payload": [
                {
                    "facility_type": "puskesmas_kelurahan",
                    "pillar": "lifeline_health",
                    "compliance_pct": 87.5,
                    "existing": 7,
                    "required": 8,
                    "deficit": -1,
                    "scored": True
                },
                {
                    "facility_type": "pos_damkar",
                    "pillar": "lifeline_health",
                    "compliance_pct": 100.0,
                    "existing": 2,
                    "required": 2,
                    "deficit": 0,
                    "scored": True
                },
                {
                    "facility_type": "sekolah_dasar",
                    "pillar": "education",
                    "compliance_pct": 22.38,
                    "existing": 32,
                    "required": 143,
                    "deficit": -111,
                    "scored": True
                },
                {
                    "facility_type": "rumah_sakit",
                    "pillar": "lifeline_health",
                    "compliance_pct": None,
                    "existing": 3,
                    "required": 0,
                    "deficit": 0,
                    "scored": False
                },
                {
                    "facility_type": "posyandu",
                    "pillar": "lifeline_health",
                    "compliance_pct": None,
                    "existing": 15,
                    "required": 0,
                    "deficit": 0,
                    "scored": False
                }
            ]
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "facility_type": "puskesmas_kelurahan",
            "service_radius_m": 1500,
            "coverage_percentage_val": 51.32,
            "coverage_percentage": "51.32%",
            "unserved_percentage_val": 48.68,
            "unserved_area_km2": 4.3957,
            "served_area_km2": 4.6338,
            "total_area_km2": 9.0295
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "facility_type": "sekolah_dasar",
            "service_radius_m": 1000,
            "coverage_percentage_val": 92.08,
            "coverage_percentage": "92.08%",
            "unserved_percentage_val": 7.92,
            "served_area_km2": 8.3148,
            "unserved_area_km2": 0.7152,
            "total_area_km2": 9.03
        }
    ]

    allowed = build_allowed_numbers(tool_outputs)

    ans1 = "Skor komposit Kecamatan Tebet adalah 54.61, puskesmas kelurahan memiliki 7 unit eksisting, kebutuhan 8 unit, dan defisit 1 unit, cakupan 51.32%."
    num1, uns1 = validate_numeric_claims(ans1, allowed)
    lbl1, mis1 = validate_label_bindings(ans1, tool_outputs)
    assert num1 is True
    assert lbl1 is True

    ans2 = "- puskesmas_kelurahan: eksisting 7 unit, kebutuhan 8 unit, defisit 1 unit, cakupan 51.32%\n- sekolah_dasar: eksisting 32 unit, kebutuhan 143 unit, defisit 111 unit, cakupan 92.08%"
    num2, uns2 = validate_numeric_claims(ans2, allowed)
    lbl2, mis2 = validate_label_bindings(ans2, tool_outputs)
    assert num2 is True
    assert lbl2 is True

    ans3 = "puskesmas kelurahan memiliki defisit 1 unit dengan cakupan radius 51.32% dan tingkat kepatuhan 87.5%"
    num3, uns3 = validate_numeric_claims(ans3, allowed)
    lbl3, mis3 = validate_label_bindings(ans3, tool_outputs)
    assert num3 is True
    assert lbl3 is True

    ans4 = "Puskesmas kelurahan mencatat defisit 1 unit (kebutuhan 8, eksisting 7) dengan cakupan 51.32%."
    num4, uns4 = validate_numeric_claims(ans4, allowed)
    lbl4, mis4 = validate_label_bindings(ans4, tool_outputs)
    assert num4 is True
    assert lbl4 is True

    ans5 = "Pos damkar memenuhi standar 2 unit dengan kepatuhan 100% dan defisit 0 unit"
    num5, uns5 = validate_numeric_claims(ans5, allowed)
    lbl5, mis5 = validate_label_bindings(ans5, tool_outputs)
    assert num5 is True
    assert lbl5 is True


def test_w11_int_2_cases():
    mixed_tool_outputs = [
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "composite_score": 54.61,
            "pillar_scores": {
                "lifeline_health": {"score": 79.17},
                "education": {"score": 25.14},
            },
            "metrics_payload": [
                {
                    "facility_type": "puskesmas_kelurahan",
                    "pillar": "lifeline_health",
                    "compliance_pct": 87.5,
                    "existing": 7,
                    "required": 8,
                    "deficit": -1,
                    "scored": True,
                },
                {
                    "facility_type": "pos_damkar",
                    "pillar": "lifeline_health",
                    "compliance_pct": 100.0,
                    "existing": 2,
                    "required": 2,
                    "deficit": 0,
                    "scored": True,
                },
                {
                    "facility_type": "sekolah_dasar",
                    "pillar": "education",
                    "compliance_pct": 22.38,
                    "existing": 32,
                    "required": 143,
                    "deficit": -111,
                    "scored": True,
                },
            ],
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "facility_type": "puskesmas_kelurahan",
            "service_radius_m": 1500,
            "coverage_percentage_val": 51.32,
            "coverage_percentage": "51.32%",
            "unserved_percentage_val": 48.68,
            "unserved_area_km2": 4.3957,
            "served_area_km2": 4.6338,
            "total_area_km2": 9.0295,
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "facility_type": "sekolah_dasar",
            "service_radius_m": 1000,
            "coverage_percentage_val": 92.08,
            "coverage_percentage": "92.08%",
            "unserved_percentage_val": 7.92,
            "served_area_km2": 8.3148,
            "unserved_area_km2": 0.7152,
            "total_area_km2": 9.03,
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "baseline_population": 228450,
            "simulated_population": 238450,
            "population_delta": 10000,
            "baseline_composite_score": 54.61,
            "simulated_composite_score": 54.13,
            "score_delta": -0.48,
            "impact_level": "Tinggi",
            "pillar_deltas": {
                "lifeline_health": {"baseline_score": 79.17, "simulated_score": 79.17, "delta": 0.0},
                "education": {"baseline_score": 25.14, "simulated_score": 24.08, "delta": -1.06},
            },
            "metrics_comparison": [
                {
                    "facility_type": "sekolah_dasar",
                    "pillar": "education",
                    "baseline_existing": 32,
                    "simulated_existing": 32,
                    "baseline_required": 143,
                    "simulated_required": 150,
                    "required_delta": 7,
                    "baseline_deficit": -111,
                    "simulated_deficit": -118,
                    "new_deficit_units": 7,
                    "deficit_delta": -7,
                    "baseline_compliance_pct": 22.38,
                    "simulated_compliance_pct": 21.33,
                },
                {
                    "facility_type": "puskesmas_kelurahan",
                    "pillar": "lifeline_health",
                    "baseline_existing": 7,
                    "simulated_existing": 7,
                    "baseline_required": 8,
                    "simulated_required": 8,
                    "required_delta": 0,
                    "baseline_deficit": -1,
                    "simulated_deficit": -1,
                    "new_deficit_units": 0,
                    "deficit_delta": 0,
                    "baseline_compliance_pct": 87.5,
                    "simulated_compliance_pct": 87.5,
                },
            ],
        },
    ]

    allowed_mixed = build_allowed_numbers(mixed_tool_outputs)

    new1 = (
        "Di Kecamatan Tebet, penambahan 10,000 penduduk (dari 228,450 menjadi 238,450 jiwa) menurunkan skor komposit dari 54.61 menjadi 54.13 (-0.48 poin). "
        "Pada kondisi awal, sekolah dasar memiliki eksisting 32 unit, kebutuhan 143 unit, defisit 111 unit, kepatuhan 22.38%, serta cakupan radius 1000 meter sebesar 92.08% (area blank spot 0.7152 km²). "
        "Pasca simulasi, kebutuhan sekolah dasar meningkat menjadi 150 unit dengan defisit 118 unit dan kepatuhan 21.33%."
    )
    n1_num, n1_uns = validate_numeric_claims(new1, allowed_mixed)
    n1_lbl, n1_mis = validate_label_bindings(new1, mixed_tool_outputs)
    assert n1_num is True, f"New 1 numeric claims failed: {n1_uns}"
    assert n1_lbl is True, f"New 1 label bindings failed: {n1_mis}"

    new2 = (
        "- Pilar Kesehatan & Keselamatan: skor tetap 79.17; puskesmas kelurahan memiliki eksisting 7 unit dari standar 8 unit, defisit 1 unit, kepatuhan 87.5%, dan cakupan layanan 51.32% (area belum terlayani 4.3957 km²).\n"
        "- Pilar Pendidikan: skor turun dari 25.14 menjadi 24.08 (-1.06 poin); sekolah dasar memiliki eksisting 32 unit, kebutuhan simulasi 150 unit, defisit 118 unit, dan kepatuhan 21.33%."
    )
    n2_num, n2_uns = validate_numeric_claims(new2, allowed_mixed)
    n2_lbl, n2_mis = validate_label_bindings(new2, mixed_tool_outputs)
    assert n2_num is True, f"New 2 numeric claims failed: {n2_uns}"
    assert n2_lbl is True, f"New 2 label bindings failed: {n2_mis}"

    diag_cases = [
        ("Diag A", "Puskesmas kelurahan memiliki defisit 1 unit dengan kepatuhan 87,5% dan cakupan 51,32%."),
        ("Diag B", "Simulasi tambahan 10000 jiwa menyebabkan sekolah dasar mengalami tambahan defisit 7 unit (total defisit 118 unit)."),
        ("Diag C", "Simulasi tambahan 10,000 jiwa menyebabkan sekolah dasar mengalami tambahan defisit 7 unit (total defisit 118 unit)."),
        ("Diag D", "Sekolah dasar mengalami defisit 118 unit akibat tambahan 10000 jiwa."),
        ("Diag E", "Puskesmas kelurahan memiliki kebutuhan 8 unit untuk melayani 228450 penduduk."),
    ]
    for d_name, d_text in diag_cases:
        d_num, d_uns = validate_numeric_claims(d_text, allowed_mixed)
        d_lbl, d_mis = validate_label_bindings(d_text, mixed_tool_outputs)
        assert d_num is True, f"{d_name} failed numeric claims: {d_uns}"
        assert d_lbl is True, f"{d_name} failed label bindings: {d_mis}"


def test_w11_int_3_cases():
    mixed_tool_outputs = [
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "composite_score": 54.61,
            "pillar_scores": {
                "lifeline_health": {"score": 79.17},
                "education": {"score": 25.14},
            },
            "metrics_payload": [
                {
                    "facility_type": "puskesmas_kelurahan",
                    "pillar": "lifeline_health",
                    "compliance_pct": 87.5,
                    "existing": 7,
                    "required": 8,
                    "deficit": -1,
                    "scored": True,
                },
                {
                    "facility_type": "pos_damkar",
                    "pillar": "lifeline_health",
                    "compliance_pct": 100.0,
                    "existing": 2,
                    "required": 2,
                    "deficit": 0,
                    "scored": True,
                },
                {
                    "facility_type": "sekolah_dasar",
                    "pillar": "education",
                    "compliance_pct": 22.38,
                    "existing": 32,
                    "required": 143,
                    "deficit": -111,
                    "scored": True,
                },
            ],
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "facility_type": "puskesmas_kelurahan",
            "service_radius_m": 1500,
            "coverage_percentage_val": 51.32,
            "coverage_percentage": "51.32%",
            "unserved_percentage_val": 48.68,
            "unserved_area_km2": 4.3957,
            "served_area_km2": 4.6338,
            "total_area_km2": 9.0295,
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "facility_type": "sekolah_dasar",
            "service_radius_m": 1000,
            "coverage_percentage_val": 92.08,
            "coverage_percentage": "92.08%",
            "unserved_percentage_val": 7.92,
            "served_area_km2": 8.3148,
            "unserved_area_km2": 0.7152,
            "total_area_km2": 9.03,
        },
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "baseline_population": 228450,
            "simulated_population": 238450,
            "population_delta": 10000,
            "baseline_composite_score": 54.61,
            "simulated_composite_score": 54.13,
            "score_delta": -0.48,
            "impact_level": "Tinggi",
            "pillar_deltas": {
                "lifeline_health": {"baseline_score": 79.17, "simulated_score": 79.17, "delta": 0.0},
                "education": {"baseline_score": 25.14, "simulated_score": 24.08, "delta": -1.06},
            },
            "metrics_comparison": [
                {
                    "facility_type": "sekolah_dasar",
                    "pillar": "education",
                    "baseline_existing": 32,
                    "simulated_existing": 32,
                    "baseline_required": 143,
                    "simulated_required": 150,
                    "required_delta": 7,
                    "baseline_deficit": -111,
                    "simulated_deficit": -118,
                    "new_deficit_units": 7,
                    "deficit_delta": -7,
                    "baseline_compliance_pct": 22.38,
                    "simulated_compliance_pct": 21.33,
                },
                {
                    "facility_type": "puskesmas_kelurahan",
                    "pillar": "lifeline_health",
                    "baseline_existing": 7,
                    "simulated_existing": 7,
                    "baseline_required": 8,
                    "simulated_required": 8,
                    "required_delta": 0,
                    "baseline_deficit": -1,
                    "simulated_deficit": -1,
                    "new_deficit_units": 0,
                    "deficit_delta": 0,
                    "baseline_compliance_pct": 87.5,
                    "simulated_compliance_pct": 87.5,
                },
            ],
        },
    ]

    allowed_mixed = build_allowed_numbers(mixed_tool_outputs)

    c1 = (
        "Untuk melayani populasi 228,450 jiwa yang bertambah 10,000 jiwa menjadi 238,450 penduduk di Tebet, "
        "sekolah dasar membutuhkan 150 unit dengan eksisting 32 unit sehingga mengalami defisit 118 unit dan cakupan 92.08%."
    )
    c1_num, c1_uns = validate_numeric_claims(c1, allowed_mixed)
    c1_lbl, c1_mis = validate_label_bindings(c1, mixed_tool_outputs)
    assert c1_num is True, f"Pass4-Correct-1 numeric claims failed: {c1_uns}"
    assert c1_lbl is True, f"Pass4-Correct-1 label bindings failed: {c1_mis}"

    c2 = (
        "Puskesmas kelurahan di Kecamatan Tebet memiliki eksisting 7 unit dan defisit 1 unit dari kebutuhan 8 unit "
        "untuk melayani 228450 penduduk dengan cakupan layanan 51.32%."
    )
    c2_num, c2_uns = validate_numeric_claims(c2, allowed_mixed)
    c2_lbl, c2_mis = validate_label_bindings(c2, mixed_tool_outputs)
    assert c2_num is True, f"Pass4-Correct-2 numeric claims failed: {c2_uns}"
    assert c2_lbl is True, f"Pass4-Correct-2 label bindings failed: {c2_mis}"

    inv1 = "Penambahan 10,000 jiwa menjadi 238,450 penduduk di Tebet memicu defisit 45 unit sekolah dasar dari 32 unit yang tersedia."
    inv1_num, inv1_uns = validate_numeric_claims(inv1, allowed_mixed)
    inv1_lbl, inv1_mis = validate_label_bindings(inv1, mixed_tool_outputs)
    assert inv1_num is False, f"Pass4-Invented-1 should fail numeric claims: {inv1_uns}"
    assert inv1_lbl is False, f"Pass4-Invented-1 should fail label binding: {inv1_mis}"


def test_w11_int_4_validate_numeric_claims_list_enumeration():
    empty_allowed = set()

    assert validate_numeric_claims("1. Rekomendasi teknis penataan ruang.", empty_allowed)[0] is True
    assert validate_numeric_claims("2) Kajian kebutuhan sarana permukiman.", empty_allowed)[0] is True
    assert validate_numeric_claims("- 1. Evaluasi berkala penyediaan puskesmas.", empty_allowed)[0] is True
    assert validate_numeric_claims("* 3. Pemantauan berkala sarana pendidikan.", empty_allowed)[0] is True
    assert validate_numeric_claims("**1.** Prioritas utama pembangunan fasilitas.", empty_allowed)[0] is True
    assert validate_numeric_claims("1.\nKesehatan adalah pilar utama pelayanan masyarakat.", empty_allowed)[0] is True

    assert validate_numeric_claims("### 1. Profil Wilayah Kecamatan", empty_allowed)[0] is True
    assert validate_numeric_claims("## 2 Analisis Kebutuhan Fasilitas", empty_allowed)[0] is True
    assert validate_numeric_claims("# 1 Ringkasan Eksekutif Perencanaan", empty_allowed)[0] is True
    assert validate_numeric_claims("### 4 Evaluasi Kinerja Layanan", empty_allowed)[0] is True

    assert validate_numeric_claims("Pilar 1 dan Pilar 2 menjadi prioritas utama pembangunan.", empty_allowed)[0] is True
    assert validate_numeric_claims("Wilayah terbagi menjadi (1) zona utara dan (2) zona selatan.", empty_allowed)[0] is True

    ok_inv1, uns_inv1 = validate_numeric_claims("Terdapat 99 unit fasilitas sekolah baru.", empty_allowed)
    assert ok_inv1 is False and "99" in uns_inv1


def test_w11_int_4_validate_label_bindings_list_enumeration():
    mock_scorecard_outputs = [
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "composite_score": 54.61,
            "pillar_scores": {
                "lifeline_health": {"score": 79.17},
                "education": {"score": 25.14},
            },
            "metrics_payload": [
                {
                    "facility_type": "puskesmas_kelurahan",
                    "pillar": "lifeline_health",
                    "compliance_pct": 87.5,
                    "existing": 7,
                    "required": 8,
                    "deficit": -1,
                    "scored": True,
                },
                {
                    "facility_type": "pos_damkar",
                    "pillar": "lifeline_health",
                    "compliance_pct": 100.0,
                    "existing": 2,
                    "required": 2,
                    "deficit": 0,
                    "scored": True,
                },
                {
                    "facility_type": "sekolah_dasar",
                    "pillar": "education",
                    "compliance_pct": 22.38,
                    "existing": 32,
                    "required": 143,
                    "deficit": -111,
                    "scored": True,
                },
            ],
        }
    ]

    text_numbered_list = (
        "Skor per pilar di Kecamatan Tebet:\n"
        "1. Layanan Kesehatan dan Keselamatan memiliki skor 79.17\n"
        "2. Sektor Pendidikan memiliki skor 25.14"
    )
    ok_nl, mis_nl = validate_label_bindings(text_numbered_list, mock_scorecard_outputs)
    assert ok_nl is True, f"Numbered list failed label binding: {mis_nl}"

    text_headings = (
        "### 1. Skor Kesehatan & Keselamatan: 79.17\n"
        "### 2. Skor Pendidikan: 25.14"
    )
    ok_hd, mis_hd = validate_label_bindings(text_headings, mock_scorecard_outputs)
    assert ok_hd is True, f"Markdown heading list failed label binding: {mis_hd}"

    text_paren = (
        "1) Kesehatan dan Keselamatan mencatat skor 79.17\n"
        "2) Pendidikan mencatat skor 25.14"
    )
    ok_pr, mis_pr = validate_label_bindings(text_paren, mock_scorecard_outputs)
    assert ok_pr is True, f"Parenthesis list failed label binding: {mis_pr}"

    text_pilar_paren = (
        "Skor Kesehatan & Keselamatan (Pilar 1): 79.17\n"
        "Skor Pendidikan (Pilar 2): 25.14"
    )
    ok_pp, mis_pp = validate_label_bindings(text_pilar_paren, mock_scorecard_outputs)
    assert ok_pp is True, f"Pilar parenthesized labels failed label binding: {mis_pp}"

    claim_wrong_health_1 = "skor pilar kesehatan 1"
    ok_w1, mis_w1 = validate_label_bindings(claim_wrong_health_1, mock_scorecard_outputs)
    assert ok_w1 is False
    assert any(m["number"] == "1" and m["expected_label"] == "pillar_score:lifeline_health" for m in mis_w1)
