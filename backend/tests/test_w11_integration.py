"""
Unit Tests for W11-INT Integration Defect Fixes (D1 through D5).
Tests run under `pytest -m unit`.
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


# -----------------------------------------------------------------------------
# D1: Simulation Assumptions Data Shape
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_d1_simulation_assumptions_shape():
    """
    Asserts every assumption value in simulation outputs is either a scalar
    or an object with known keys (e.g. composite_weights), avoiding [object Object].
    """
    # 1. Test What-If simulation assumptions shape
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
            # If nested object, assert all keys are known keys and values are scalars
            for sub_k, sub_v in val.items():
                assert sub_k in known_keys, f"Unknown subkey '{sub_k}' in assumptions['{key}']"
                assert isinstance(sub_v, (int, float, str, bool)), f"Non-scalar subval in assumptions['{key}']['{sub_k}']"
        else:
            pytest.fail(f"Unexpected assumption value type for key '{key}': {type(val)}")

    # 2. Test Superblock simulation assumptions shape
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


@pytest.mark.unit
def test_d1_frontend_assumptions_and_obligations_xss_prevention():
    """
    Static check verifying that:
    1. frontend/js/utils/dom.js defines formatAssumptionValue.
    2. frontend/js/panels/simulation.js imports formatAssumptionValue and uses it with textContent (no raw ${v} innerHTML).
    3. Renders res-obligations-list using textContent / safe DOM nodes (no innerHTML with API strings).
    """
    import os
    sim_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "js", "panels", "simulation.js")
    with open(sim_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    dom_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "js", "utils", "dom.js")
    with open(dom_js_path, "r", encoding="utf-8") as f:
        dom_content = f.read()

    # 1. formatAssumptionValue exists in utils/dom.js and is imported/used in simulation.js
    assert "function formatAssumptionValue" in dom_content
    assert "formatAssumptionValue" in content
    assert "strong.textContent = formatAssumptionValue(v)" in content

    # 2. No raw ${v} interpolation in assumption table innerHTML
    assert "assumpTableBody.innerHTML" not in content or "${v}" not in content

    # 3. Obligations list uses textContent, not innerHTML with API strings
    assert "${o.regulation_code}" not in content
    assert "${o.obligation_text}" not in content
    assert "res-obligations-list" in content


# -----------------------------------------------------------------------------
# D2: Canonical District Code Resolution & Map Actions
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_d2_map_action_resolves_district_name_to_code():
    """
    When tool args provide a district name like 'Tebet', orchestrator deterministically
    resolves the canonical Kemendagri code ('31.71.09') for map actions.
    """
    orchestrator = CognitiveSpatialAgentOrchestrator()
    map_actions = []

    mock_db_row = {"kemendagri_code": "31.71.09", "name": "Tebet"}

    def mock_db_cursor_ctx():
        class MockCursor:
            def execute(self, query, params=None):
                pass
            def fetchone(self):
                return mock_db_row
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockCursor()

    with patch("backend.app.agent.orchestrator.get_db_cursor", side_effect=mock_db_cursor_ctx):
        # Tool args pass name 'Tebet' instead of code
        args = {"district_code": "Tebet"}
        output = {"composite_score": 40.71, "district_name": "Tebet"}

        orchestrator._extract_map_actions("get_district_scorecard", args, output, map_actions)

        assert len(map_actions) == 1
        assert map_actions[0].action_type == "fly_to"
        assert map_actions[0].payload["district_code"] == "31.71.09"


@pytest.mark.unit
def test_d2_map_action_unknown_district_emits_no_action():
    """
    When district name cannot be resolved in the database, no map action is emitted.
    """
    orchestrator = CognitiveSpatialAgentOrchestrator()
    map_actions = []

    def mock_db_cursor_empty():
        class MockCursor:
            def execute(self, query, params=None):
                pass
            def fetchone(self):
                return None
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockCursor()

    with patch("backend.app.agent.orchestrator.get_db_cursor", side_effect=mock_db_cursor_empty):
        args = {"district_code": "KotaAtlantis"}
        output = {"error": "District not found"}

        orchestrator._extract_map_actions("get_district_scorecard", args, output, map_actions)

        assert len(map_actions) == 0


# -----------------------------------------------------------------------------
# D3: Guardrail Compliance Percentages & Invented Numbers
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_d3_guardrail_accepts_valid_compliance_percentage():
    """
    Checks that quoting compliance percentages like 'pos_damkar 100%' or '100,0%'
    is accepted without false-positive trigger.
    """
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


@pytest.mark.unit
def test_d3_guardrail_catches_invented_percentage_and_mislabel():
    """
    Asserts invented percentages (not in tool output) and mislabeled percentages
    (attributing one facility's percentage to another) are strictly caught.
    """
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

    # 1. Invented percentage: 77% does not exist in tool output
    text_invented = "Capaian kepatuhan pos damkar adalah 77%."
    p_num, unsupp = validate_numeric_claims(text_invented, allowed)
    assert p_num is False
    assert "77%" in unsupp

    # 2. Mislabeled percentage: 39.44% belongs to SD, falsely claimed for pos_damkar
    text_mislabeled = "Capaian pos_damkar adalah 39.44%."
    p_num2, _ = validate_numeric_claims(text_mislabeled, allowed)
    assert p_num2 is True  # 39.44 is in tool output
    p_lbl2, mislab2 = validate_label_bindings(text_mislabeled, tool_outputs)
    assert p_lbl2 is False
    assert any("pos_damkar" in m["expected_label"] for m in mislab2)


# -----------------------------------------------------------------------------
# D4: Superblock Reworded Text & Permit Request Refusal
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_d4_superblock_assumption_text_survives_sanitization():
    """
    Ensures assumption note reworded from 'belum diverifikasi ke Perda 31/2022'
    to 'belum diverifikasi terhadap peraturan daerah' survives citation sanitizing
    without leaving dangling parentheses 'belum diverifikasi ke )'.
    """
    text = "Parameter asumsi tim (belum diverifikasi terhadap peraturan daerah): RTH 20%, retensi 150 mm/hari, KDB 50%"
    sanitized, _, removed = validate_and_sanitize_citations(text, set())
    assert "belum diverifikasi ke )" not in sanitized
    assert "belum diverifikasi terhadap peraturan daerah" in sanitized
    assert len(removed) == 0


@pytest.mark.unit
def test_d4_permit_refusal_patterns():
    """
    Asserts 5 permit request phrasings are refused as out-of-scope,
    while 3 normal superblock simulation inquiries are NOT refused.
    """
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
@pytest.mark.unit
def test_d5_tool_descriptions_and_system_prompt_distinction():
    """
    Asserts tool schemas and system prompt explicitly distinguish unit deficit
    (from scorecard metrics_payload) vs radius coverage % (from blank spots).
    """
    tools_dict = {t["function"]["name"]: t["function"] for t in SPATIAL_AGENT_TOOLS}

    # 1. get_district_scorecard must mention unit deficit formula/scorecard
    scorecard_desc = tools_dict["get_district_scorecard"]["description"]
    assert "defisit unit" in scorecard_desc.lower()
    assert "kebutuhan" in scorecard_desc.lower()

    # 2. get_unserved_blank_spots must warn it's radius coverage, not unit deficit
    blankspot_desc = tools_dict["get_unserved_blank_spots"]["description"]
    assert "cakupan" in blankspot_desc.lower()
    assert "bukan" in blankspot_desc.lower() or "not" in blankspot_desc.lower()

    # 3. System prompt must define distinction
    assert "PEMBEDAAN DEFISIT UNIT VS CAKUPAN RADIUS" in SYSTEM_PROMPT
    assert "defisit unit" in SYSTEM_PROMPT.lower()
    assert "cakupan %" in SYSTEM_PROMPT.lower()


# -----------------------------------------------------------------------------
# R1: SYSTEM_PROMPT & Tool Descriptions Digits Check
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_r1_system_prompt_and_tool_descriptions_contain_no_digits():
    """
    Asserts SYSTEM_PROMPT and tool descriptions contain no concrete digits
    other than structural rule numbers (1-5 / #1-#4) and official regulation
    codes (SNI 03-1733-2004).
    """
    # 1. Check SYSTEM_PROMPT
    cleaned_prompt = re.sub(r"\b[1-5]\.\s*(?:ATURAN\s*#[1-5]|Gaya\s+Bahasa)?", "", SYSTEM_PROMPT)
    digits_prompt = re.findall(r"\d+", cleaned_prompt)
    assert len(digits_prompt) == 0, f"Found concrete digits in SYSTEM_PROMPT: {digits_prompt}"

    # 2. Check Tool Descriptions
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
@pytest.mark.unit
def test_r4_superblock_simulation_map_action_payload():
    """
    Asserts map action extracts score_delta and simulated_score from
    nested output['simulation_delta'] when handling run_superblock_simulation.
    """
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
@pytest.mark.unit
def test_r5_guardrail_catches_all_bypasses_and_allows_blank_spots():
    """
    Tests all bypass vulnerabilities from VERIFY_W11_INT.md:
    1. Deficit with % is rejected.
    2. % attributed to unscored facility is rejected.
    3. Non-% number in 'kepatuhan' clause is validated against compliance values.
    4. Multi-tool output (scorecard + blank spot coverage) is accepted.
    """
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

    # Bypass 1: Compliance % mislabeled as unit deficit
    p1, m1 = validate_label_bindings("Defisit sekolah dasar adalah 39.44%", tool_outputs)
    assert p1 is False, f"Bypass 1 failed: deficit with % was not caught: {m1}"

    p1b, m1b = validate_label_bindings("Defisit pos_damkar adalah 100%", tool_outputs)
    assert p1b is False, f"Bypass 1b failed: deficit with % was not caught: {m1b}"

    # Bypass 2: Allowed % attributed to an unscored facility
    p2, m2 = validate_label_bindings("Kepatuhan rumah sakit telah memenuhi standar (100%)", tool_outputs)
    assert p2 is False, f"Bypass 2 failed: % on unscored facility was not caught: {m2}"

    p2b, m2b = validate_label_bindings("Kepatuhan posyandu adalah 39.44%", tool_outputs)
    assert p2b is False, f"Bypass 2b failed: % on unscored facility was not caught: {m2b}"

    # Bypass 3: Non-% number with 'kepatuhan'
    p3, m3 = validate_label_bindings("Kepatuhan sekolah dasar adalah 100", tool_outputs)
    assert p3 is False, f"Bypass 3 failed: non-% compliance mismatch was not caught: {m3}"

    # Bypass 4 (Multi-tool valid check): Quoting blank-spot coverage together with scorecard
    text_multi = "Cakupan puskesmas kelurahan di Tebet mencapai 72.5% dengan skor kecamatan 40.71."
    p_num, unsupp = validate_numeric_claims(text_multi, allowed)
    p_lbl, mislab = validate_label_bindings(text_multi, tool_outputs)
    assert p_num is True, f"Failed numeric claims on valid multi-tool text: {unsupp}"
    assert p_lbl is True, f"Failed label bindings on valid multi-tool text: {mislab}"

    # Additional mismatch catches: wrong deficit or required unit number
    p_def_bad, m_def_bad = validate_label_bindings("Defisit pos_damkar adalah 2 unit", tool_outputs)
    assert p_def_bad is False, f"Deficit mismatch not caught: {m_def_bad}"

    p_req_bad, m_req_bad = validate_label_bindings("Kebutuhan pos_damkar adalah 5 unit", tool_outputs)
    assert p_req_bad is False, f"Required mismatch not caught: {m_req_bad}"


@pytest.mark.unit
def test_r5_realistic_multi_metric_answers_pass():
    """
    Unit test for W11-INT.2 verifying the 5 realistic multi-metric answers
    from VERIFY_W11_INT_1.md row R5 against matching Tebet tool outputs.
    All 5 realistic answers must pass label binding and numeric claims validation.
    """
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

    # 1. Comma-separated clauses quoting scorecard + blank-spot
    ans1 = "Skor komposit Kecamatan Tebet adalah 54.61, puskesmas kelurahan memiliki 7 unit eksisting, kebutuhan 8 unit, dan defisit 1 unit, cakupan 51.32%."
    num1, uns1 = validate_numeric_claims(ans1, allowed)
    lbl1, mis1 = validate_label_bindings(ans1, tool_outputs)
    assert num1 is True, f"Answer 1 failed numeric claims: {uns1}"
    assert lbl1 is True, f"Answer 1 failed label bindings: {mis1}"

    # 2. Bullet list scorecard + blank spot
    ans2 = "- puskesmas_kelurahan: eksisting 7 unit, kebutuhan 8 unit, defisit 1 unit, cakupan 51.32%\n- sekolah_dasar: eksisting 32 unit, kebutuhan 143 unit, defisit 111 unit, cakupan 92.08%"
    num2, uns2 = validate_numeric_claims(ans2, allowed)
    lbl2, mis2 = validate_label_bindings(ans2, tool_outputs)
    assert num2 is True, f"Answer 2 failed numeric claims: {uns2}"
    assert lbl2 is True, f"Answer 2 failed label bindings: {mis2}"

    # 3. 'dengan'/'dan' joining deficit + blank-spot coverage % & compliance %
    ans3 = "puskesmas kelurahan memiliki defisit 1 unit dengan cakupan radius 51.32% dan tingkat kepatuhan 87.5%"
    num3, uns3 = validate_numeric_claims(ans3, allowed)
    lbl3, mis3 = validate_label_bindings(ans3, tool_outputs)
    assert num3 is True, f"Answer 3 failed numeric claims: {uns3}"
    assert lbl3 is True, f"Answer 3 failed label bindings: {mis3}"

    # 4. 'Defisit N unit (kebutuhan M, eksisting K)' + blank-spot coverage %
    ans4 = "Puskesmas kelurahan mencatat defisit 1 unit (kebutuhan 8, eksisting 7) dengan cakupan 51.32%."
    num4, uns4 = validate_numeric_claims(ans4, allowed)
    lbl4, mis4 = validate_label_bindings(ans4, tool_outputs)
    assert num4 is True, f"Answer 4 failed numeric claims: {uns4}"
    assert lbl4 is True, f"Answer 4 failed label bindings: {mis4}"

    # 5. 'standar N unit dengan kepatuhan 100% dan defisit 0 unit' + blank-spot coverage %
    ans5 = "Pos damkar memenuhi standar 2 unit dengan kepatuhan 100% dan defisit 0 unit"
    num5, uns5 = validate_numeric_claims(ans5, allowed)
    lbl5, mis5 = validate_label_bindings(ans5, tool_outputs)
    assert num5 is True, f"Answer 5 failed numeric claims: {uns5}"
    assert lbl5 is True, f"Answer 5 failed label bindings: {mis5}"

    # Additional realistic patterns from eval benchmark:
    # Bullet points with 'Ada X unit / Standar Y unit (Kepatuhan: Z%, Defisit: W unit)'
    ans_eval_bullet = (
        "- pos_damkar: Ada 2 unit / Standar 2 unit (Kepatuhan: 100.0%, Defisit: 0 unit)\n"
        "- puskesmas_kelurahan: Ada 7 unit / Standar 8 unit (Kepatuhan: 87.5%, Defisit: -1 unit)"
    )
    num_eb, uns_eb = validate_numeric_claims(ans_eval_bullet, allowed)
    lbl_eb, mis_eb = validate_label_bindings(ans_eval_bullet, tool_outputs)
    assert num_eb is True, f"Eval bullet failed numeric claims: {uns_eb}"
    assert lbl_eb is True, f"Eval bullet failed label bindings: {mis_eb}"

    # Post-token qualifier syntax: '<N> unit yang tersedia dari <M> unit yang dibutuhkan'
    ans_post = "puskesmas kelurahan memiliki 7 unit yang tersedia dari 8 unit yang dibutuhkan"
    num_post, uns_post = validate_numeric_claims(ans_post, allowed)
    lbl_post, mis_post = validate_label_bindings(ans_post, tool_outputs)
    assert num_post is True, f"Post-qualifier failed numeric claims: {uns_post}"
    assert lbl_post is True, f"Post-qualifier failed label bindings: {mis_post}"


@pytest.mark.unit
def test_w11_int_2_cases():
    """
    Cases from _PROMPT/scratch/verify_w11_int_2.py:
    New 1..New 3 (correct answers mixing scorecard + blank-spot + what-if) must pass.
    New 4..New 6 (wrong label / invented numbers) must be caught.
    Diag A..Diag E (Indonesian decimal comma and population in facility clauses) must pass.
    """
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
                {
                    "facility_type": "rumah_sakit",
                    "pillar": "lifeline_health",
                    "compliance_pct": None,
                    "existing": 3,
                    "required": 0,
                    "deficit": 0,
                    "scored": False,
                },
                {
                    "facility_type": "posyandu",
                    "pillar": "lifeline_health",
                    "compliance_pct": None,
                    "existing": 15,
                    "required": 0,
                    "deficit": 0,
                    "scored": False,
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
                "lifeline_health": {
                    "baseline_score": 79.17,
                    "simulated_score": 79.17,
                    "delta": 0.0,
                },
                "education": {
                    "baseline_score": 25.14,
                    "simulated_score": 24.08,
                    "delta": -1.06,
                },
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
                    "facility_type": "taman_kanak_kanak",
                    "pillar": "education",
                    "baseline_existing": 63,
                    "simulated_existing": 63,
                    "baseline_required": 183,
                    "simulated_required": 191,
                    "required_delta": 8,
                    "baseline_deficit": -120,
                    "simulated_deficit": -128,
                    "new_deficit_units": 8,
                    "deficit_delta": -8,
                    "baseline_compliance_pct": 34.43,
                    "simulated_compliance_pct": 32.98,
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
                {
                    "facility_type": "pos_damkar",
                    "pillar": "lifeline_health",
                    "baseline_existing": 2,
                    "simulated_existing": 2,
                    "baseline_required": 2,
                    "simulated_required": 2,
                    "required_delta": 0,
                    "baseline_deficit": 0,
                    "simulated_deficit": 0,
                    "new_deficit_units": 0,
                    "deficit_delta": 0,
                    "baseline_compliance_pct": 100.0,
                    "simulated_compliance_pct": 100.0,
                },
            ],
        },
    ]

    allowed_mixed = build_allowed_numbers(mixed_tool_outputs)

    # New 1: Correct narrative
    new1 = (
        "Di Kecamatan Tebet, penambahan 10,000 penduduk (dari 228,450 menjadi 238,450 jiwa) menurunkan skor komposit dari 54.61 menjadi 54.13 (-0.48 poin). "
        "Pada kondisi awal, sekolah dasar memiliki eksisting 32 unit, kebutuhan 143 unit, defisit 111 unit, kepatuhan 22.38%, serta cakupan radius 1000 meter sebesar 92.08% (area blank spot 0.7152 km²). "
        "Pasca simulasi, kebutuhan sekolah dasar meningkat menjadi 150 unit dengan defisit 118 unit dan kepatuhan 21.33%."
    )
    n1_num, n1_uns = validate_numeric_claims(new1, allowed_mixed)
    n1_lbl, n1_mis = validate_label_bindings(new1, mixed_tool_outputs)
    assert n1_num is True, f"New 1 numeric claims failed: {n1_uns}"
    assert n1_lbl is True, f"New 1 label bindings failed: {n1_mis}"

    # New 2: Correct bullet summary
    new2 = (
        "- Pilar Kesehatan & Keselamatan: skor tetap 79.17; puskesmas kelurahan memiliki eksisting 7 unit dari standar 8 unit, defisit 1 unit, kepatuhan 87.5%, dan cakupan layanan 51.32% (area belum terlayani 4.3957 km²).\n"
        "- Pilar Pendidikan: skor turun dari 25.14 menjadi 24.08 (-1.06 poin); taman kanak-kanak memiliki eksisting 63 unit, kebutuhan simulasi 191 unit, defisit 128 unit, dan kepatuhan 32.98%."
    )
    n2_num, n2_uns = validate_numeric_claims(new2, allowed_mixed)
    n2_lbl, n2_mis = validate_label_bindings(new2, mixed_tool_outputs)
    assert n2_num is True, f"New 2 numeric claims failed: {n2_uns}"
    assert n2_lbl is True, f"New 2 label bindings failed: {n2_mis}"

    # New 3: Correct post-token qualifiers
    new3 = (
        "Pos damkar di Tebet memiliki 2 unit yang tersedia dari 2 unit yang dibutuhkan (kepatuhan 100% dan defisit 0 unit), "
        "puskesmas kelurahan mencatat defisit 1 unit (kebutuhan 8, eksisting 7) dengan cakupan radius 1500 meter sebesar 51.32%, "
        "sedangkan simulasi tambahan 10000 jiwa menambah defisit sekolah dasar sebanyak 7 unit sehingga total defisit 118 unit dengan cakupan eksisting 92.08%."
    )
    n3_num, n3_uns = validate_numeric_claims(new3, allowed_mixed)
    n3_lbl, n3_mis = validate_label_bindings(new3, mixed_tool_outputs)
    assert n3_num is True, f"New 3 numeric claims failed: {n3_uns}"
    assert n3_lbl is True, f"New 3 label bindings failed: {n3_mis}"

    # New 4: Wrong label
    new4 = (
        "Pada simulasi penambahan 10,000 penduduk di Tebet (skor komposit 54.13), "
        "puskesmas kelurahan memiliki defisit 51.32% dan sekolah dasar memiliki eksisting 143 unit dengan cakupan 92.08%."
    )
    n4_num, _ = validate_numeric_claims(new4, allowed_mixed)
    n4_lbl, n4_mis = validate_label_bindings(new4, mixed_tool_outputs)
    assert n4_num is True
    assert n4_lbl is False, f"New 4 should fail label binding: {n4_mis}"

    # New 5: Wrong label
    new5 = (
        "Skor komposit Kecamatan Tebet pasca simulasi adalah 79.17, "
        "sedangkan puskesmas kelurahan memiliki cakupan 51.32% dan rumah sakit memiliki kepatuhan 22.38%."
    )
    n5_num, _ = validate_numeric_claims(new5, allowed_mixed)
    n5_lbl, n5_mis = validate_label_bindings(new5, mixed_tool_outputs)
    assert n5_num is True
    assert n5_lbl is False, f"New 5 should fail label binding: {n5_mis}"

    # New 6: Invented number + wrong label
    new6 = (
        "Setelah simulasi 238,450 penduduk di Tebet (skor komposit turun dari 54.61 menjadi 54.13), "
        "cakupan puskesmas kelurahan naik dari 51.32% menjadi 64.85% dan defisit sekolah dasar menjadi 95 unit."
    )
    n6_num, n6_uns = validate_numeric_claims(new6, allowed_mixed)
    n6_lbl, n6_mis = validate_label_bindings(new6, mixed_tool_outputs)
    assert n6_num is False, f"New 6 should fail numeric claims: {n6_uns}"
    assert n6_lbl is False, f"New 6 should fail label binding: {n6_mis}"

    # Diagnostic cases: Indonesian comma decimal and population in clause
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


@pytest.mark.unit
def test_w11_int_3_cases():
    """
    Cases from _PROMPT/scratch/verify_w11_int_3.py:
    Pass4-Correct-1 & Pass4-Correct-2 (population + facility numbers in one sentence) must pass.
    Pass4-Invented-1 & Pass4-Invented-2 (invented facility number next to population) must be caught.
    """
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
                {
                    "facility_type": "rumah_sakit",
                    "pillar": "lifeline_health",
                    "compliance_pct": None,
                    "existing": 3,
                    "required": 0,
                    "deficit": 0,
                    "scored": False,
                },
                {
                    "facility_type": "posyandu",
                    "pillar": "lifeline_health",
                    "compliance_pct": None,
                    "existing": 15,
                    "required": 0,
                    "deficit": 0,
                    "scored": False,
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
                "lifeline_health": {
                    "baseline_score": 79.17,
                    "simulated_score": 79.17,
                    "delta": 0.0,
                },
                "education": {
                    "baseline_score": 25.14,
                    "simulated_score": 24.08,
                    "delta": -1.06,
                },
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
                    "facility_type": "taman_kanak_kanak",
                    "pillar": "education",
                    "baseline_existing": 63,
                    "simulated_existing": 63,
                    "baseline_required": 183,
                    "simulated_required": 191,
                    "required_delta": 8,
                    "baseline_deficit": -120,
                    "simulated_deficit": -128,
                    "new_deficit_units": 8,
                    "deficit_delta": -8,
                    "baseline_compliance_pct": 34.43,
                    "simulated_compliance_pct": 32.98,
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
                {
                    "facility_type": "pos_damkar",
                    "pillar": "lifeline_health",
                    "baseline_existing": 2,
                    "simulated_existing": 2,
                    "baseline_required": 2,
                    "simulated_required": 2,
                    "required_delta": 0,
                    "baseline_deficit": 0,
                    "simulated_deficit": 0,
                    "new_deficit_units": 0,
                    "deficit_delta": 0,
                    "baseline_compliance_pct": 100.0,
                    "simulated_compliance_pct": 100.0,
                },
            ],
        },
    ]

    allowed_mixed = build_allowed_numbers(mixed_tool_outputs)

    # Pass4-Correct-1: Population (with commas) + facility required/existing/deficit in one sentence
    c1 = (
        "Untuk melayani populasi 228,450 jiwa yang bertambah 10,000 jiwa menjadi 238,450 penduduk di Tebet, "
        "sekolah dasar membutuhkan 150 unit dengan eksisting 32 unit sehingga mengalami defisit 118 unit dan cakupan 92.08%."
    )
    c1_num, c1_uns = validate_numeric_claims(c1, allowed_mixed)
    c1_lbl, c1_mis = validate_label_bindings(c1, mixed_tool_outputs)
    assert c1_num is True, f"Pass4-Correct-1 numeric claims failed: {c1_uns}"
    assert c1_lbl is True, f"Pass4-Correct-1 label bindings failed: {c1_mis}"

    # Pass4-Correct-2: Facility existing/deficit/required + population in one sentence
    c2 = (
        "Puskesmas kelurahan di Kecamatan Tebet memiliki eksisting 7 unit dan defisit 1 unit dari kebutuhan 8 unit "
        "untuk melayani 228450 penduduk dengan cakupan layanan 51.32%."
    )
    c2_num, c2_uns = validate_numeric_claims(c2, allowed_mixed)
    c2_lbl, c2_mis = validate_label_bindings(c2, mixed_tool_outputs)
    assert c2_num is True, f"Pass4-Correct-2 numeric claims failed: {c2_uns}"
    assert c2_lbl is True, f"Pass4-Correct-2 label bindings failed: {c2_mis}"

    # Pass4-Invented-1: Invented SD deficit 45 unit next to population tokens
    inv1 = "Penambahan 10,000 jiwa menjadi 238,450 penduduk di Tebet memicu defisit 45 unit sekolah dasar dari 32 unit yang tersedia."
    inv1_num, inv1_uns = validate_numeric_claims(inv1, allowed_mixed)
    inv1_lbl, inv1_mis = validate_label_bindings(inv1, mixed_tool_outputs)
    assert inv1_num is False, f"Pass4-Invented-1 should fail numeric claims: {inv1_uns}"
    assert inv1_lbl is False, f"Pass4-Invented-1 should fail label binding: {inv1_mis}"

    # Pass4-Invented-2: Invented puskesmas required 19 unit next to population token
    inv2 = "Bagi 228450 jiwa penduduk di Tebet diperlukan kebutuhan 19 unit puskesmas kelurahan karena saat ini baru tersedia 7 unit dengan cakupan 51.32%."
    inv2_num, inv2_uns = validate_numeric_claims(inv2, allowed_mixed)
    inv2_lbl, inv2_mis = validate_label_bindings(inv2, mixed_tool_outputs)
    assert inv2_num is False, f"Pass4-Invented-2 should fail numeric claims: {inv2_uns}"
    assert inv2_lbl is False, f"Pass4-Invented-2 should fail label binding: {inv2_mis}"


# -----------------------------------------------------------------------------
# W11-INT.4: List Enumeration Tokens vs Real Number Claims
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_w11_int_4_validate_numeric_claims_list_enumeration():
    """
    Verifies that validate_numeric_claims ignores list-enumeration tokens
    (line-start ordinal followed by '.' or ')' and space, markdown headings, Pilar 1..4),
    while arbitrary unsupported numbers (even small integers like 1 or 2 when used as claims)
    are strictly caught.
    """
    empty_allowed = set()

    # 1. Line-start ordinals must be ignored as structural list markers
    assert validate_numeric_claims("1. Rekomendasi teknis penataan ruang.", empty_allowed)[0] is True
    assert validate_numeric_claims("2) Kajian kebutuhan sarana permukiman.", empty_allowed)[0] is True
    assert validate_numeric_claims("- 1. Evaluasi berkala penyediaan puskesmas.", empty_allowed)[0] is True
    assert validate_numeric_claims("* 3. Pemantauan berkala sarana pendidikan.", empty_allowed)[0] is True
    assert validate_numeric_claims("**1.** Prioritas utama pembangunan fasilitas.", empty_allowed)[0] is True
    assert validate_numeric_claims("1.\nKesehatan adalah pilar utama pelayanan masyarakat.", empty_allowed)[0] is True

    # 2. Markdown headings must be ignored
    assert validate_numeric_claims("### 1. Profil Wilayah Kecamatan", empty_allowed)[0] is True
    assert validate_numeric_claims("## 2 Analisis Kebutuhan Fasilitas", empty_allowed)[0] is True
    assert validate_numeric_claims("# 1 Ringkasan Eksekutif Perencanaan", empty_allowed)[0] is True
    assert validate_numeric_claims("### 4 Evaluasi Kinerja Layanan", empty_allowed)[0] is True

    # 3. Category labels and parenthesized markers
    assert validate_numeric_claims("Pilar 1 dan Pilar 2 menjadi prioritas utama pembangunan.", empty_allowed)[0] is True
    assert validate_numeric_claims("Wilayah terbagi menjadi (1) zona utara dan (2) zona selatan.", empty_allowed)[0] is True

    # 4. Non-enumeration numbers must NOT be ignored (must be caught as unsupported claims)
    ok_inv1, uns_inv1 = validate_numeric_claims("Terdapat 99 unit fasilitas sekolah baru.", empty_allowed)
    assert ok_inv1 is False and "99" in uns_inv1

    ok_inv2, uns_inv2 = validate_numeric_claims("Skor pilar kesehatan adalah 99.", empty_allowed)
    assert ok_inv2 is False and "99" in uns_inv2

    # A real number claim "skor pilar kesehatan 1" without list marker context is caught when 1 is not allowed
    ok_claim1, uns_claim1 = validate_numeric_claims("skor pilar kesehatan 1", empty_allowed)
    assert ok_claim1 is False and "1" in uns_claim1


@pytest.mark.unit
def test_w11_int_4_validate_label_bindings_list_enumeration():
    """
    Verifies that validate_label_bindings correctly ignores list-enumeration tokens
    (line-start ordinal followed by '.' or ')' and space, markdown headings, 'Pilar 1', '(Pilar 1)'),
    while real number claims like 'skor pilar kesehatan 1' are strictly caught as mislabeled.
    """
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

    # --- PART A: CORRECT USES OF LIST ENUMERATION & NUMBERING (MUST PASS) ---
    # 1. Markdown numbered list with dot and health/education scores
    text_numbered_list = (
        "Skor per pilar di Kecamatan Tebet:\n"
        "1. Layanan Kesehatan dan Keselamatan memiliki skor 79.17\n"
        "2. Sektor Pendidikan memiliki skor 25.14"
    )
    ok_nl, mis_nl = validate_label_bindings(text_numbered_list, mock_scorecard_outputs)
    assert ok_nl is True, f"Numbered list failed label binding: {mis_nl}"

    # 2. Markdown headings with numbering
    text_headings = (
        "### 1. Skor Kesehatan & Keselamatan: 79.17\n"
        "### 2. Skor Pendidikan: 25.14"
    )
    ok_hd, mis_hd = validate_label_bindings(text_headings, mock_scorecard_outputs)
    assert ok_hd is True, f"Markdown heading list failed label binding: {mis_hd}"

    # 3. Parenthesis numbering
    text_paren = (
        "1) Kesehatan dan Keselamatan mencatat skor 79.17\n"
        "2) Pendidikan mencatat skor 25.14"
    )
    ok_pr, mis_pr = validate_label_bindings(text_paren, mock_scorecard_outputs)
    assert ok_pr is True, f"Parenthesis list failed label binding: {mis_pr}"

    # 4. Pillar label with (Pilar 1) and (Pilar 2) in parentheses next to scores
    text_pilar_paren = (
        "Skor Kesehatan & Keselamatan (Pilar 1): 79.17\n"
        "Skor Pendidikan (Pilar 2): 25.14"
    )
    ok_pp, mis_pp = validate_label_bindings(text_pilar_paren, mock_scorecard_outputs)
    assert ok_pp is True, f"Pilar parenthesized labels failed label binding: {mis_pp}"

    # 5. Pilar prefix syntax
    text_pilar_prefix = (
        "Pilar 1 (Kesehatan & Keselamatan): Skor 79.17\n"
        "Pilar 2 (Pendidikan): Skor 25.14"
    )
    ok_px, mis_px = validate_label_bindings(text_pilar_prefix, mock_scorecard_outputs)
    assert ok_px is True, f"Pilar prefix syntax failed label binding: {mis_px}"

    # 6. Bullet list format matching actual LLM draft
    text_bullet = (
        "- **Kesehatan & Keselamatan (Pilar 1):** Skor: 79.17\n"
        "- **Pendidikan (Pilar 2):** Skor: 25.14"
    )
    ok_bl, mis_bl = validate_label_bindings(text_bullet, mock_scorecard_outputs)
    assert ok_bl is True, f"Bullet format failed label binding: {mis_bl}"

    # 7. Facility list enumeration before facility unit metrics
    text_fac_enum = (
        "1. Sekolah dasar: eksisting 32 unit, kebutuhan 143 unit, defisit 111 unit\n"
        "2. Puskesmas kelurahan: eksisting 7 unit, kebutuhan 8 unit, defisit 1 unit"
    )
    ok_fe, mis_fe = validate_label_bindings(text_fac_enum, mock_scorecard_outputs)
    assert ok_fe is True, f"Facility enumeration failed label binding: {mis_fe}"

    # --- PART B: REAL NUMBER CLAIMS (MUST BE CAUGHT) ---
    # 1. Real number claim: "skor pilar kesehatan 1" (1 is claimed as the score, not enumeration)
    claim_wrong_health_1 = "skor pilar kesehatan 1"
    ok_w1, mis_w1 = validate_label_bindings(claim_wrong_health_1, mock_scorecard_outputs)
    assert ok_w1 is False, "Expected 'skor pilar kesehatan 1' to fail label binding"
    assert any(m["number"] == "1" and m["expected_label"] == "pillar_score:lifeline_health" for m in mis_w1)

    # 2. Real number claim: "skor pilar pendidikan 2"
    claim_wrong_edu_2 = "skor pilar pendidikan 2"
    ok_w2, mis_w2 = validate_label_bindings(claim_wrong_edu_2, mock_scorecard_outputs)
    assert ok_w2 is False, "Expected 'skor pilar pendidikan 2' to fail label binding"
    assert any(m["number"] == "2" and m["expected_label"] == "pillar_score:education" for m in mis_w2)

    # 3. Real number claim inside ordinal list: "1. Skor pilar kesehatan adalah 1"
    claim_in_list = "1. Skor pilar kesehatan adalah 1"
    ok_cl, mis_cl = validate_label_bindings(claim_in_list, mock_scorecard_outputs)
    assert ok_cl is False, "Expected '1. Skor pilar kesehatan adalah 1' to fail label binding"
    assert any(m["number"] == "1" and m["expected_label"] == "pillar_score:lifeline_health" for m in mis_cl)

    # 4. Real number claim in heading: "### 1. Skor Kesehatan: 1"
    claim_in_hd = "### 1. Skor Kesehatan: 1"
    ok_ch, mis_ch = validate_label_bindings(claim_in_hd, mock_scorecard_outputs)
    assert ok_ch is False, "Expected '### 1. Skor Kesehatan: 1' to fail label binding"
    assert any(m["number"] == "1" and m["expected_label"] == "pillar_score:lifeline_health" for m in mis_ch)

    # 5. Swapped pillar scores in numbered list
    swapped_scores = (
        "1. Skor kesehatan: 25.14\n"
        "2. Skor pendidikan: 79.17"
    )
    ok_sw, mis_sw = validate_label_bindings(swapped_scores, mock_scorecard_outputs)
    assert ok_sw is False, "Expected swapped pillar scores in numbered list to fail"
    assert len(mis_sw) >= 2


