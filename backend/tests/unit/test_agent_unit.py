"""
Unit Tests for Cognitive Spatial Agent and Multi-Round Orchestrator.
Uses mocked LLM and tools. Marker: unit.
"""

import json
import pytest
from typing import List
from unittest.mock import patch, MagicMock

from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    ChatMessage,
    trim_conversation_history,
    is_out_of_scope_request,
    OUT_OF_SCOPE_REFUSAL
)
from backend.app.agent.guardrails import (
    validate_numeric_claims,
    build_allowed_numbers,
)

pytestmark = pytest.mark.unit


def test_guardrail_mismatch_triggers_fallback():
    """Verify that if LLM produces numbers that mismatch tool outputs, numeric_fallback MUST be reported."""
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
            "message": {"role": "assistant", "content": "Skor komposit Tebet adalah 28.57 dengan penduduk 999999 jiwa."}
        },
        {
            "model": "mock-qwen",
            "message": {"role": "assistant", "content": "Revisi: Skor komposit Tebet tetap 99.99."}
        }
    ]
    with patch.object(orchestrator, "_call_llm", side_effect=responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value={"composite_score": 40.71, "population": 228450}):
            req = AgentChatRequest(messages=[ChatMessage(role="user", content="skor")])
            res = orchestrator.process_chat(req)
            assert res.guardrail == "numeric_fallback", f"Must report numeric_fallback when numbers mismatch, got {res.guardrail}"
            assert "28.57" in res.unsupported_numbers or "99.99" in res.unsupported_numbers


def test_two_round_flow_mocked():
    """
    Two-round flow: round 1 calls scorecard, round 2 calls what-if, round 3 final answer.
    """
    orchestrator = CognitiveSpatialAgentOrchestrator()

    mock_responses = [
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
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_what_if_simulation",
                            "arguments": json.dumps({
                                "district_code": "31.71.09",
                                "population_shock_count": 10000
                            })
                        }
                    }
                ]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": (
                    "Berdasarkan analisis tata ruang, populasi eksisting Tebet tercatat 228.450 jiwa "
                    "dengan skor kelayakan hidup 38.70. Penambahan beban 10.000 jiwa menghasilkan "
                    "skor komposit baru sebesar 38.50 dengan selisih skor -0.20."
                )
            }
        }
    ]

    mock_scorecard = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "population": 228450,
        "composite_score": 38.70,
        "pillar_scores": {
            "lifeline_health": {"score": 56.71},
            "education": {"score": 23.41},
            "urban_livability": {"score": 0.00},
            "mobility_connectivity": {"score": 79.17}
        },
        "metrics_payload": []
    }

    mock_sim = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "population_delta": 10000,
        "baseline_composite_score": 38.70,
        "simulated_composite_score": 38.50,
        "score_delta": -0.20,
        "is_sandbox_isolated": True
    }

    def fake_execute(tool_name, args):
        if tool_name == "get_district_scorecard":
            return mock_scorecard
        elif tool_name == "run_what_if_simulation":
            return mock_sim
        return {}

    with patch.object(orchestrator, "_call_llm", side_effect=mock_responses):
        with patch("backend.app.agent.orchestrator.execute_tool_call", side_effect=fake_execute):
            req = AgentChatRequest(
                messages=[
                    ChatMessage(
                        role="user",
                        content="Berapa skor Tebet saat ini dan bagaimana dampaknya jika ada tambahan 10.000 jiwa?"
                    )
                ]
            )
            resp = orchestrator.process_chat(req)

            assert resp.rounds_used == 3
            assert resp.stop_reason == "final_answer"
            assert len(resp.tool_trace) == 2
            assert resp.tool_trace[0]["tool"] == "get_district_scorecard"
            assert resp.tool_trace[0]["round"] == 1
            assert resp.tool_trace[0]["ok"] is True
            assert resp.tool_trace[1]["tool"] == "run_what_if_simulation"
            assert resp.tool_trace[1]["round"] == 2
            assert resp.tool_trace[1]["ok"] is True

            action_types = [a.action_type for a in resp.map_actions]
            assert "fly_to" in action_types
            assert "render_simulation_layer" in action_types
            assert resp.guardrail == "passed"
            assert len(resp.unsupported_numbers) == 0
            assert len(resp.mislabeled_numbers) == 0


def test_max_tool_rounds_stops_at_four():
    """
    LLM keeps requesting tools for 5 rounds -> stops at 4, returns deterministic summary.
    """
    orchestrator = CognitiveSpatialAgentOrchestrator()

    def make_tool_call_response(round_idx):
        return {
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
        }

    mock_responses = [make_tool_call_response(i) for i in range(1, 6)]
    mock_scorecard = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "population": 228450,
        "composite_score": 38.70,
        "pillar_scores": {
            "lifeline_health": {"score": 56.71},
            "education": {"score": 23.41}
        },
        "metrics_payload": []
    }

    with patch.object(orchestrator, "_call_llm", side_effect=mock_responses) as mock_llm_call:
        with patch("backend.app.agent.orchestrator.execute_tool_call", return_value=mock_scorecard):
            req = AgentChatRequest(
                messages=[ChatMessage(role="user", content="Analisis terus Tebet secara mendalam")]
            )
            resp = orchestrator.process_chat(req)

            assert resp.rounds_used == 4
            assert resp.stop_reason == "max_rounds"
            assert mock_llm_call.call_count == 4
            assert "Ringkasan Analisis Spasial Deterministik" in resp.reply
            assert resp.guardrail == "numeric_fallback"

            allowed = build_allowed_numbers([mock_scorecard])
            passed_num, unsupported = validate_numeric_claims(resp.reply, allowed)
            assert passed_num is True, f"Deterministic summary contains unsupported numbers: {unsupported}"


def test_history_trimming_ten_turns():
    """History of 10 turns -> only last 6 kept, no orphan tool messages."""
    messages: List[ChatMessage] = []
    for i in range(1, 11):
        messages.append(ChatMessage(role="user", content=f"User question {i}"))
        if i < 10:
            messages.append(ChatMessage(role="assistant", content=f"Assistant answer {i}"))
            if i == 8:
                messages.append(ChatMessage(role="tool", content=json.dumps({"test_tool": 8})))

    trimmed, history_trimmed, history_turns_kept = trim_conversation_history(messages, max_turns=6)

    assert history_trimmed is True
    assert history_turns_kept == 6

    first_kept_user = next(m for m in trimmed if m["role"] == "user")
    assert first_kept_user["content"] == "User question 5"

    for m in trimmed:
        if m["role"] == "user":
            turn_idx = int(m["content"].split()[-1])
            assert turn_idx >= 5

    orphan_messages = [
        ChatMessage(role="tool", content="{'orphan': True}"),
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi")
    ]
    orphan_trimmed, _, _ = trim_conversation_history(orphan_messages, max_turns=6)
    assert not any(m.get("role") == "tool" for m in orphan_trimmed[:1])


def test_llm_text_mention_produces_no_map_action():
    """LLM text mentioning 'fly_to Menteng' without a scorecard tool call produces NO map action."""
    orchestrator = CognitiveSpatialAgentOrchestrator()

    mock_llm_response = {
        "model": "mock-qwen",
        "message": {
            "role": "assistant",
            "content": "Mari kita lihat wilayah Menteng. Silakan jalankan fly_to Menteng (31.73.01) untuk melihat fasilitasnya."
        }
    }

    with patch.object(orchestrator, "_call_llm", return_value=mock_llm_response):
        req = AgentChatRequest(
            messages=[ChatMessage(role="user", content="Bagaimana dengan Menteng?")]
        )
        resp = orchestrator.process_chat(req)

        assert len(resp.map_actions) == 0
        assert len(resp.tool_calls_executed) == 0
        assert resp.stop_reason == "final_answer"


def test_out_of_scope_permit_refusal():
    """Permit-decision question -> refusal text, no tools called."""
    orchestrator = CognitiveSpatialAgentOrchestrator()

    queries = [
        "Apakah proyek superblok ini boleh disetujui izinnya?",
        "Apakah izin pembangunan gedung ini sah secara hukum?",
        "Tolong berikan rekomendasi izin untuk pembangunan mal di Tebet.",
        "Apakah proyek ini layak diberikan persetujuan izin?"
    ]

    for q in queries:
        assert is_out_of_scope_request(q) is True, f"Failed to detect out of scope: {q}"
        req = AgentChatRequest(messages=[ChatMessage(role="user", content=q)])
        resp = orchestrator.process_chat(req)

        assert "tidak berwenang memberikan keputusan perizinan resmi" in resp.reply
        assert "simulasi dampak beban penduduk" in resp.reply
        assert len(resp.tool_calls_executed) == 0
        assert len(resp.tool_trace) == 0
        assert resp.rounds_used == 0


def test_guardrail_uses_round_one_tool_output_in_round_three():
    """Guardrail uses round-1 tool output to validate a number cited in final answer of round 3."""
    orchestrator = CognitiveSpatialAgentOrchestrator()

    mock_scorecard = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "population": 228450,
        "composite_score": 38.70,
        "pillar_scores": {
            "lifeline_health": {"score": 56.71},
            "education": {"score": 23.41}
        },
        "metrics_payload": []
    }

    mock_blank_spots = {
        "district_code": "31.71.09",
        "district_name": "Tebet",
        "facility_type": "puskesmas_kelurahan",
        "unserved_area_km2": 1.25,
        "coverage_percentage": 86.5
    }

    def fake_execute(tool_name, args):
        if tool_name == "get_district_scorecard":
            return mock_scorecard
        elif tool_name == "get_unserved_blank_spots":
            return mock_blank_spots
        return {}

    mock_responses_valid = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "get_district_scorecard", "arguments": json.dumps({"district_code": "31.71.09"})}}]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "get_unserved_blank_spots", "arguments": json.dumps({"district_code": "31.71.09", "facility_type": "puskesmas_kelurahan"})}}]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Populasi awal Tebet adalah 228.450 jiwa dengan skor komposit 38.70. Luas area belum terlayani adalah 1.25 km²."
            }
        }
    ]

    with patch.object(orchestrator, "_call_llm", side_effect=mock_responses_valid):
        with patch("backend.app.agent.orchestrator.execute_tool_call", side_effect=fake_execute):
            req = AgentChatRequest(messages=[ChatMessage(role="user", content="Berapa penduduk awal dan blank spotnya?")])
            resp = orchestrator.process_chat(req)
            assert resp.guardrail == "passed"
            assert len(resp.unsupported_numbers) == 0

    mock_responses_fabricated = [
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "get_district_scorecard", "arguments": json.dumps({"district_code": "31.71.09"})}}]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "get_unserved_blank_spots", "arguments": json.dumps({"district_code": "31.71.09", "facility_type": "puskesmas_kelurahan"})}}]
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Populasi awal Tebet adalah 999.888 jiwa dengan skor komposit 38.70."
            }
        },
        {
            "model": "mock-qwen",
            "message": {
                "role": "assistant",
                "content": "Revisi: Populasi Tebet tetap 999.888 jiwa."
            }
        }
    ]

    with patch.object(orchestrator, "_call_llm", side_effect=mock_responses_fabricated):
        with patch("backend.app.agent.orchestrator.execute_tool_call", side_effect=fake_execute):
            req = AgentChatRequest(messages=[ChatMessage(role="user", content="Cek populasi")])
            resp = orchestrator.process_chat(req)
            assert resp.guardrail == "numeric_fallback"
            assert "999.888" in resp.unsupported_numbers
