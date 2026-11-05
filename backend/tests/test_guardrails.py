"""
Unit tests for AI Numeric Guardrail and Citation Validator.
Guardrail compliance tests:
- Tests with MOCKED LLM (no GPU required).
- Fabricated number triggers retry; second bad answer triggers numeric_fallback.
- Only tool numbers -> guardrail == 'passed'.
- [REG:fake-id] and unbacked free-text citations are cleanly removed.
- Thousand separator (. and ,) and decimal comma variants are accepted.
"""

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import json
import pytest
from unittest.mock import patch, MagicMock
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    ChatMessage
)

pytestmark = pytest.mark.unit
from backend.app.agent.guardrails import (
    build_allowed_numbers,
    validate_numeric_claims,
    validate_and_sanitize_citations,
    parse_number_candidates
)

def test_parse_number_candidates():
    # Indonesian comma decimal
    assert 40.71 in parse_number_candidates("40,71")
    # Indonesian period thousand
    assert 228450.0 in parse_number_candidates("228.450")
    # English comma thousand
    assert 228450.0 in parse_number_candidates("228,450")
    # Percentages
    assert 87.5 in parse_number_candidates("87.5%")
    assert 87.5 in parse_number_candidates("87,5%")
    # Negative values
    assert -1.0 in parse_number_candidates("-1")
    assert -3.4 in parse_number_candidates("-3.4")

def test_numeric_guardrail_unit_pass():
    tool_outputs = [
        {
            "district_code": "31.71.09",
            "district_name": "Tebet",
            "population": 228450,
            "composite_score": 33.57,
            "pillar_scores": {
                "lifeline_health": {"score": 56.71},
                "education": {"score": 18.73}
            },
            "metrics_payload": [
                {"facility_type": "puskesmas_kecamatan", "existing": 1, "required": 2, "deficit": -1, "compliance_pct": 50.0}
            ]
        }
    ]
    allowed = build_allowed_numbers(tool_outputs)
    assert 33.57 in allowed
    assert 228450.0 in allowed
    assert 1.0 in allowed  # abs(deficit -1) and existing 1
    assert 2.0 in allowed  # required 2
    assert 50.0 in allowed  # compliance 50%

    # Answer using only valid numbers in various formats
    valid_text = (
        "1. Kecamatan Tebet memiliki penduduk 228.450 jiwa (atau 228,450 jiwa).\n"
        "2. Skor komposit tercatat 33,57.\n"
        "3. Kepatuhan puskesmas kecamatan sebesar 50% dengan defisit 1 unit."
    )
    passed, unsupported = validate_numeric_claims(valid_text, allowed)
    assert passed is True, f"Expected passed, got unsupported: {unsupported}"
    assert len(unsupported) == 0

def test_citation_validator_unit():
    returned_cits = [
        {
            "chunk_id": "c01-sni-pos-polisi",
            "regulation_code": "SNI 03-1733-2004",
            "article_number": "Bagian 7.1 Tabel 6",
            "chapter": "Sarana Pemerintahan"
        }
    ]

    input_text = (
        "Sesuai [REG:c01-sni-pos-polisi], standar pos polisi terpenuhi.\n"
        "Menurut [REG:fake-id-123], aturan fiktif berlaku.\n"
        "Berdasarkan Permenkes No. 99/2099 Pasal 999, izin rumah sakit diperlukan."
    )

    cleaned, valid_cits, removed_cits = validate_and_sanitize_citations(input_text, returned_cits)

    assert "c01-sni-pos-polisi" in valid_cits
    assert "[REG:fake-id-123]" in removed_cits
    assert any("99/2099" in r for r in removed_cits)
    assert "[REG:fake-id-123]" not in cleaned
    assert "99/2099" not in cleaned
    assert "SNI 03-1733-2004" in cleaned

def test_citation_sanitizer_empty_shells_and_valid_render():
    """
    Tests edge cases:
    - broken empty shells: "... [REG:] ..."
    - malformed tag: "... [REG: & ] ..."
    - unbacked bold header: "1. **** - Rencana..."
    - valid [REG:<real id>] must stay and render formatted label
    """
    returned_cits = [
        {
            "chunk_id": "c99-perda-rth",
            "regulation_code": "Perda DKI Jakarta No. 31/2022",
            "article_number": "Pasal 64",
            "chapter": "RTH Superblok"
        }
    ]

    # 1. Broken tag: "... [REG:] ..."
    c1, _, r1 = validate_and_sanitize_citations("... [REG:] ...", returned_cits)
    assert "[REG:]" not in c1
    assert "[REG:]" in r1

    # 2. Broken tag: "... [REG: & ] ..."
    c2, _, r2 = validate_and_sanitize_citations("... [REG: & ] ...", returned_cits)
    assert "[REG: & ]" not in c2

    # 3. Stripped empty bold marker: "1. **** - Rencana..."
    c3, _, _ = validate_and_sanitize_citations("1. **** - Rencana tata ruang wilayah.", returned_cits)
    assert "****" not in c3
    assert c3 == "1. Rencana tata ruang wilayah."

    # 4. Valid citation rendering
    c4, v4, _ = validate_and_sanitize_citations("Kewajiban RTH diatur pada [REG:c99-perda-rth].", returned_cits)
    assert "c99-perda-rth" in v4
    assert "**[Perda DKI Jakarta No. 31/2022: Pasal 64]**" in c4

def test_mocked_llm_fabricated_number_triggers_fallback():
    orchestrator = CognitiveSpatialAgentOrchestrator()

    mock_tool_output = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "population": 228450,
        "composite_score": 33.57,
        "pillar_scores": {
            "lifeline_health": {"score": 56.71, "label": "Pilar 1"}
        },
        "metrics_payload": []
    }

    # Simulate LLM turns:
    # Turn 1: tool call
    # Turn 2: fabricated number "skor 28.57" (first attempt)
    # Turn 3 (retry): still fabricated number "skor 99.99"
    responses = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_district_scorecard",
                            "arguments": json.dumps({"district_code": "31.71.09"})
                        }
                    }
                ]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Skor kelayakan hidup di Tebet adalah 28.57 dengan penduduk 228450 jiwa."
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Revisi: Skor kelayakan hidup tetap 99.99."
            }
        }
    ]

    req = AgentChatRequest(messages=[ChatMessage(role="user", content="Cek skor Tebet")])

    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=mock_tool_output):
            res = orchestrator.process_chat(req)

    assert res.guardrail == "numeric_fallback"
    assert "28.57" in res.unsupported_numbers or "99.99" in res.unsupported_numbers
    assert "Fallback" in res.reply
    assert "33.57" in res.reply

def test_mocked_llm_retry_success():
    orchestrator = CognitiveSpatialAgentOrchestrator()

    mock_tool_output = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "population": 228450,
        "composite_score": 33.57,
        "pillar_scores": {
            "lifeline_health": {"score": 56.71, "label": "Pilar 1"}
        },
        "metrics_payload": []
    }

    # Turn 1: tool call
    # Turn 2: fabricated number "28.57"
    # Turn 3 (retry): corrected with real number "33.57"
    responses = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_district_scorecard",
                            "arguments": json.dumps({"district_code": "31.71.09"})
                        }
                    }
                ]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Skor kelayakan hidup di Tebet adalah 28.57."
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Koreksi: Skor kelayakan hidup di Tebet adalah 33.57 dengan penduduk 228.450 jiwa."
            }
        }
    ]

    req = AgentChatRequest(messages=[ChatMessage(role="user", content="Cek skor Tebet")])

    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=mock_tool_output):
            res = orchestrator.process_chat(req)

    assert res.guardrail == "retried"
    assert len(res.unsupported_numbers) == 0
    assert "33.57" in res.reply

def test_mocked_llm_all_numbers_valid():
    orchestrator = CognitiveSpatialAgentOrchestrator()

    mock_tool_output = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "population": 228450,
        "composite_score": 33.57,
        "pillar_scores": {
            "lifeline_health": {"score": 56.71, "label": "Pilar 1"}
        },
        "metrics_payload": []
    }

    responses = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_district_scorecard",
                            "arguments": json.dumps({"district_code": "31.71.09"})
                        }
                    }
                ]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Skor kelayakan hidup di Tebet tercatat 33,57% dengan total populasi 228.450 jiwa."
            }
        }
    ]

    req = AgentChatRequest(messages=[ChatMessage(role="user", content="Cek skor Tebet")])

    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=mock_tool_output):
            res = orchestrator.process_chat(req)

    assert res.guardrail == "passed"
    assert len(res.unsupported_numbers) == 0

def test_label_aware_guardrail_reproduces_original_bug():
    """
    Reproduces original bug exactly: LLM outputs pillar score 28.57 when reporting
    composite livability score (expected 40.71).
    Must be caught by validate_label_bindings and trigger retry/fallback.
    """
    from backend.app.agent.guardrails import validate_label_bindings

    mock_tool_output = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "composite_score": 40.71,
        "pillar_scores": {
            "urban_livability": {"score": 28.57, "label": "Ruang Hidup"},
            "lifeline_health": {"score": 56.71, "label": "Kesehatan"}
        },
        "metrics_payload": []
    }

    # Direct unit test
    passed, mislabeled = validate_label_bindings("Skor kelayakan hidup Tebet adalah 28.57.", [mock_tool_output])
    assert passed is False
    assert len(mislabeled) == 1
    assert mislabeled[0]["number"] == "28.57"
    assert "composite_score (40.71)" in mislabeled[0]["expected_label"]
    assert mislabeled[0]["found_label"] == "pillar_score:urban_livability"

    # Orchestrator flow test
    orchestrator = CognitiveSpatialAgentOrchestrator()
    responses = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_district_scorecard",
                            "arguments": json.dumps({"district_code": "31.71.09"})
                        }
                    }
                ]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Skor kelayakan hidup Tebet adalah 28.57."
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Tetap: Skor kelayakan hidup Tebet adalah 28.57."
            }
        }
    ]

    req = AgentChatRequest(messages=[ChatMessage(role="user", content="Cek skor Tebet")])
    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=mock_tool_output):
            res = orchestrator.process_chat(req)

    assert res.guardrail == "numeric_fallback"
    assert len(res.mislabeled_numbers) == 1
    assert res.mislabeled_numbers[0]["number"] == "28.57"
    assert "composite_score (40.71)" in res.mislabeled_numbers[0]["expected_label"]
    assert res.mislabeled_numbers[0]["found_label"] == "pillar_score:urban_livability"
    assert "Fallback" in res.reply

def test_label_aware_guardrail_passes_correct_labels():
    """
    Same tool output: composite 40.71, livability 28.57.
    Answer: 'Skor kelayakan hidup Tebet adalah 40.71 dan skor pilar ruang hidup 28.57' -> passes.
    """
    from backend.app.agent.guardrails import validate_label_bindings

    mock_tool_output = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "composite_score": 40.71,
        "pillar_scores": {
            "urban_livability": {"score": 28.57, "label": "Ruang Hidup"},
            "lifeline_health": {"score": 56.71, "label": "Kesehatan"}
        },
        "metrics_payload": []
    }

    # Direct unit test
    text = "Skor kelayakan hidup Tebet adalah 40.71 dan skor pilar ruang hidup 28.57."
    passed, mislabeled = validate_label_bindings(text, [mock_tool_output])
    assert passed is True, f"Expected passed, got mislabeled: {mislabeled}"
    assert len(mislabeled) == 0

    # Orchestrator flow test
    orchestrator = CognitiveSpatialAgentOrchestrator()
    responses = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_district_scorecard",
                            "arguments": json.dumps({"district_code": "31.71.09"})
                        }
                    }
                ]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Skor kelayakan hidup Tebet adalah 40.71 dan skor pilar ruang hidup 28.57."
            }
        }
    ]

    req = AgentChatRequest(messages=[ChatMessage(role="user", content="Cek skor Tebet")])
    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=mock_tool_output):
            res = orchestrator.process_chat(req)

    assert res.guardrail == "passed"
    assert len(res.mislabeled_numbers) == 0
    assert len(res.unsupported_numbers) == 0

def test_label_aware_guardrail_wrong_facility_deficit():
    """
    Deficit of wrong facility type in a sentence is flagged as mislabeled.
    """
    from backend.app.agent.guardrails import validate_label_bindings

    mock_tool_output = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "composite_score": 40.71,
        "pillar_scores": {
            "urban_livability": {"score": 28.57, "label": "Ruang Hidup"}
        },
        "metrics_payload": [
            {"facility_type": "rumah_sakit", "deficit": -2, "required": 3, "existing": 1},
            {"facility_type": "puskesmas_kecamatan", "deficit": 0, "required": 1, "existing": 1}
        ]
    }

    # Direct unit test
    passed, mislabeled = validate_label_bindings("Defisit rumah sakit di Tebet adalah 0 unit.", [mock_tool_output])
    assert passed is False
    assert len(mislabeled) == 1
    assert mislabeled[0]["number"] == "0"
    assert "defisit:rumah_sakit (2.0)" in mislabeled[0]["expected_label"]
    assert mislabeled[0]["found_label"] == "deficit:puskesmas_kecamatan"

    # Correct sentence passes
    passed_ok, mislabeled_ok = validate_label_bindings("Defisit rumah sakit di Tebet adalah 2 unit.", [mock_tool_output])
    assert passed_ok is True
    assert len(mislabeled_ok) == 0

def test_fallback_scorecard_null_safe_rendering():
    """
    Scorecard tool output with excluded pillars (score: None) and composite None
    must render without error and must not print numbers for excluded pillars.
    """
    from backend.app.agent.guardrails import build_deterministic_fallback_summary

    mock_tool_output = {
        "district_code": "31.75.05",
        "district_name": "Kelapa Gading",
        "population": 145890,
        "composite_score": None,
        "composite_note": "cakupan data rendah (0 dari 0 standar dinilai)",
        "pillar_scores": {
            "lifeline_health": {
                "score": 66.67,
                "label": "Pilar 1: Kesehatan & Keselamatan",
                "status": "tersedia"
            },
            "urban_livability": {
                "score": None,
                "label": "Pilar 3: Ruang Hidup & Rekreasi",
                "status": "cakupan data rendah",
                "types_excluded": [
                    {"facility_type": "taman_kecamatan", "reason": "Fasilitas informasi saja (§6.3) - tidak dinilai"}
                ]
            },
            "mobility_connectivity": {
                "score": None,
                "label": "Pilar 4: Mobilitas & Aksesibilitas",
                "status": "cakupan data rendah"
            }
        },
        "metrics_payload": [
            {
                "facility_type": "rumah_sakit",
                "existing": 12,
                "required": None,
                "compliance_pct": None,
                "deficit": None,
                "scored": False
            },
            {
                "facility_type": "puskesmas_kecamatan",
                "existing": 0,
                "required": 2,
                "compliance_pct": 0.0,
                "deficit": -2,
                "scored": True
            }
        ]
    }

    text = build_deterministic_fallback_summary([mock_tool_output])
    assert text is not None
    assert "**Indeks Kecukupan Fasilitas Dasar:** tidak dinilai" in text
    assert "Pilar 1: Kesehatan & Keselamatan: 66.67%" in text
    assert "Pilar 3: Ruang Hidup & Rekreasi: tidak dinilai" in text
    assert "Pilar 4: Mobilitas & Aksesibilitas: tidak dinilai" in text
    # Ensure no number or None is printed for excluded pillars
    assert "Pilar 3: Ruang Hidup & Rekreasi: None" not in text
    assert "Pilar 4: Mobilitas & Aksesibilitas: None" not in text
    assert "Pilar 3: Ruang Hidup & Rekreasi: 0" not in text
    assert "rumah_sakit`: Ada 12 unit (Fasilitas informasi - tidak dinilai)" in text

if __name__ == "__main__":
    from backend.app.core.db import init_db_pool, close_db_pool
    try:
        init_db_pool()
    except Exception:
        pass

    try:
        test_parse_number_candidates()
        test_numeric_guardrail_unit_pass()
        test_citation_validator_unit()
        test_mocked_llm_fabricated_number_triggers_fallback()
        test_mocked_llm_retry_success()
        test_mocked_llm_all_numbers_valid()
        test_label_aware_guardrail_reproduces_original_bug()
        test_label_aware_guardrail_passes_correct_labels()
        test_label_aware_guardrail_wrong_facility_deficit()
        test_fallback_scorecard_null_safe_rendering()
        print(">> [PASSED] All AI Guardrail & Citation Validator Unit Tests Passed!")
    finally:
        try:
            close_db_pool()
        except Exception:
            pass

