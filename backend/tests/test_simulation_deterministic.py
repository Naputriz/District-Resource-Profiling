"""
Unit tests for deterministic simulation answers:
Validates:
1. build_simulation_deterministic_block output structure.
2. CognitiveSpatialAgentOrchestrator answer_mode: "template+narrative" when LLM writes text without digits.
3. answer_mode: "template_only" when LLM text contains digits and retry still contains digits.
4. answer_mode: "template+narrative" when LLM retry succeeds with pure qualitative text (no digits).
"""

import json
import pytest
from unittest.mock import patch

from backend.app.agent.guardrails import (
    build_simulation_deterministic_block,
    build_allowed_numbers,
    validate_numeric_claims,
    validate_label_bindings,
)
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    ChatMessage
)

SAMPLE_WHAT_IF_OUTPUT = {
    "district_code": "31.71.09",
    "district_name": "Tebet",
    "baseline_population": 228450,
    "simulated_population": 262717,
    "population_delta": 34267,
    "baseline_composite_score": 51.60,
    "simulated_composite_score": 47.39,
    "score_delta": -4.21,
    "abs_score_delta": 4.21,
    "baseline_pillar_scores": {
        "lifeline_health": 56.71,
        "education": 23.41,
        "urban_livability": 0.0,
        "mobility_connectivity": 79.17
    },
    "simulated_pillar_scores": {
        "lifeline_health": 49.65,
        "education": 20.38,
        "urban_livability": 0.0,
        "mobility_connectivity": 77.78
    },
    "pillar_deltas": {
        "lifeline_health": {"baseline_score": 56.71, "simulated_score": 49.65, "delta": -7.06},
        "education": {"baseline_score": 23.41, "simulated_score": 20.38, "delta": -3.03},
        "mobility_connectivity": {"baseline_score": 79.17, "simulated_score": 77.78, "delta": -1.39}
    },
    "metrics_comparison": [
        {"facility_type": "sekolah_dasar", "baseline_deficit": 111, "simulated_deficit": 133, "new_deficit_units": 22, "deficit_delta": -22},
        {"facility_type": "puskesmas_kelurahan", "baseline_deficit": 1, "simulated_deficit": 2, "new_deficit_units": 1, "deficit_delta": -1}
    ],
    "impact_level": "Tinggi",
    "impact_rule": "delta <= -5.0 atau >= 3 unit defisit baru",
    "disclaimer": "Bukan keputusan perizinan. Untuk bahan diskusi perencanaan."
}

SAMPLE_SUPERBLOCK_OUTPUT = {
    "district_code": "31.71.01",
    "district_name": "Menteng",
    "project_name": "Kuningan Tower",
    "residential_units": 1200,
    "estimated_new_occupants": 3600,
    "mandated_public_rth_m2": 3000.0,
    "mandated_water_retention_m3": 1125.0,
    "simulation_delta": {
        "district_code": "31.71.01",
        "district_name": "Menteng",
        "baseline_population": 80940,
        "simulated_population": 84540,
        "population_delta": 3600,
        "baseline_composite_score": 61.74,
        "simulated_composite_score": 61.27,
        "score_delta": -0.47,
        "pillar_deltas": {
            "education": {"baseline_score": 28.54, "simulated_score": 27.14, "delta": -1.40}
        },
        "metrics_comparison": [
            {"facility_type": "posyandu", "baseline_deficit": 65, "simulated_deficit": 68, "new_deficit_units": 3, "deficit_delta": -3}
        ],
        "impact_level": "Tinggi",
        "impact_rule": ">= 3 unit defisit baru",
        "disclaimer": "Bukan keputusan perizinan. Untuk bahan diskusi perencanaan."
    }
}


@pytest.mark.unit
def test_build_simulation_deterministic_block_structure():
    """Verify deterministic block contents."""
    block = build_simulation_deterministic_block("run_what_if_simulation", SAMPLE_WHAT_IF_OUTPUT)

    assert "### 📈 Hasil Simulasi Perubahan Populasi (Tebet)" in block
    assert "- **Populasi:** 228,450 jiwa ➔ 262,717 jiwa (+34,267 jiwa)" in block
    assert "- **Skor Komposit:** 51.60 ➔ 47.39 (-4.21 poin)" in block
    assert "- **Perubahan per Pilar:**" in block
    assert "lifeline_health: 56.71 ➔ 49.65 (-7.06)" in block
    assert "sekolah_dasar: +22 unit" in block
    assert "- **Indikasi Dampak:** Tinggi (delta <= -5.0 atau >= 3 unit defisit baru)" in block
    assert "> *Bukan keputusan perizinan. Untuk bahan diskusi perencanaan.*" in block

    # Verify guardrail compliance of the deterministic block
    allowed = build_allowed_numbers([SAMPLE_WHAT_IF_OUTPUT])
    p_num, unsupp = validate_numeric_claims(block, allowed)
    p_lbl, mislbl = validate_label_bindings(block, [SAMPLE_WHAT_IF_OUTPUT])
    assert p_num is True, f"Unsupported numbers found: {unsupp}"
    assert p_lbl is True, f"Mislabeled numbers found: {mislbl}"


@pytest.mark.unit
def test_orchestrator_simulation_template_plus_narrative():
    """LLM provides qualitative narrative without digits -> answer_mode: template+narrative."""
    orchestrator = CognitiveSpatialAgentOrchestrator()

    responses = [
        # Round 1: LLM calls tool
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_what_if_simulation",
                            "arguments": json.dumps({"district_code": "31.71.09", "population_shock_percent": 15.0})
                        }
                    }
                ]
            }
        },
        # Round 2: LLM provides qualitative narrative with 0 digits
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Kenaikan beban penduduk memberikan tekanan signifikan pada sarana pendidikan dan kesehatan kecamatan sehingga memerlukan penyesuaian alokasi anggaran daerah."
            }
        }
    ]

    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=SAMPLE_WHAT_IF_OUTPUT):
            req = AgentChatRequest(messages=[ChatMessage(role="user", content="simulasi tebet +15%")])
            res = orchestrator.process_chat(req)

            assert res.answer_mode == "template+narrative"
            assert res.guardrail == "passed"
            assert "### 📈 Hasil Simulasi Perubahan Populasi (Tebet)" in res.reply
            assert "### 📝 Analisis Kualitatif" in res.reply
            assert "Kenaikan beban penduduk" in res.reply
            assert len(res.unsupported_numbers) == 0


@pytest.mark.unit
def test_orchestrator_simulation_template_only_when_digits_persist():
    """LLM narrative has digits, retry still has digits -> answer_mode: template_only."""
    orchestrator = CognitiveSpatialAgentOrchestrator()

    responses = [
        # Round 1: LLM calls tool
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_what_if_simulation",
                            "arguments": json.dumps({"district_code": "31.71.09", "population_shock_percent": 15.0})
                        }
                    }
                ]
            }
        },
        # Round 2: LLM narrative contains digits
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Terjadi penurunan skor sebesar 4.21 poin dan defisit bertambah sebanyak 22 unit sekolah dasar."
            }
        },
        # Round 2 retry: LLM still includes digits
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Dampaknya cukup besar dengan tambahan 2 fasilitas baru yang defisit."
            }
        }
    ]

    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=SAMPLE_WHAT_IF_OUTPUT):
            req = AgentChatRequest(messages=[ChatMessage(role="user", content="simulasi tebet +15%")])
            res = orchestrator.process_chat(req)

            assert res.answer_mode == "template_only"
            assert res.guardrail == "passed"
            assert "### 📈 Hasil Simulasi Perubahan Populasi (Tebet)" in res.reply
            assert "### 📝 Analisis Kualitatif" not in res.reply
            assert len(res.unsupported_numbers) == 0


@pytest.mark.unit
def test_orchestrator_simulation_retry_succeeds_without_digits():
    """LLM narrative has digits, but retry succeeds without digits -> answer_mode: template+narrative."""
    orchestrator = CognitiveSpatialAgentOrchestrator()

    responses = [
        # Round 1: LLM calls superblock simulation
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_superblock_simulation",
                            "arguments": json.dumps({
                                "district_code": "31.71.01",
                                "residential_units": 1200,
                                "site_area_sqm": 45000.0,
                                "project_name": "Kuningan Tower"
                            })
                        }
                    }
                ]
            }
        },
        # Round 2: LLM narrative contains digits
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Proyek ini menambah 1200 unit hunian dan berdampak pada sarana sekitar."
            }
        },
        # Round 2 retry: LLM complies with pure qualitative text (no digits)
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Pembangunan superblok menuntut penyediaan fasilitas sosial dan ruang terbuka hijau publik agar tidak memperberat daya dukung lingkungan perkotaan setempat."
            }
        }
    ]

    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=SAMPLE_SUPERBLOCK_OUTPUT):
            req = AgentChatRequest(messages=[ChatMessage(role="user", content="simulasi superblok kuningan")])
            res = orchestrator.process_chat(req)

            assert res.answer_mode == "template+narrative"
            assert res.guardrail == "passed"
            assert "### 🏗️ Hasil Simulasi Superblok: Kuningan Tower (Menteng)" in res.reply
            assert "### 📝 Analisis Kualitatif" in res.reply
            assert "Pembangunan superblok menuntut penyediaan fasilitas sosial" in res.reply
            assert len(res.unsupported_numbers) == 0
