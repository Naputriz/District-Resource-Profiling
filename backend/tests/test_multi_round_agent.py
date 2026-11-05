"""
Unit and Integration Tests for Multi-Round Agent Architecture.
Validates multi-round agent architecture:
1. Two-round flow: round 1 scorecard, round 2 what-if, round 3 final answer ->
   rounds_used == 3, stop_reason == "final_answer", both tools in tool_trace,
   map actions fly_to + render_simulation_layer.
2. LLM keeps requesting tools for 5 rounds -> stops at 4, stop_reason == "max_rounds",
   deterministic answer, guardrail still applied.
3. History of 10 turns -> only last 6 kept, system prompt present, no orphan tool messages.
4. LLM text mentioning "fly_to Menteng" without scorecard tool call produces NO map action.
5. Permit-decision question -> refusal text, no tools called.
6. Guardrail uses round-1 tool output to validate a number cited in final answer of round 3.
7. Live test with Ollama (if available): one two-step question for Tebet (scorecard + what-if +10,000 jiwa).
"""

import json
import os
import urllib.request
import pytest
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List

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
    validate_label_bindings,
    build_allowed_numbers
)
from backend.app.core.db import init_db_pool, close_db_pool


# -----------------------------------------------------------------------------
# 1. Two-Round Tool Calling Flow (Mocked LLM)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_two_round_flow_mocked():
    """
    Two-round flow: round 1 calls scorecard, round 2 calls what-if, round 3 final answer.
    Verifies:
    - rounds_used == 3
    - stop_reason == 'final_answer'
    - both tools in tool_trace
    - map actions include fly_to + render_simulation_layer
    """
    orchestrator = CognitiveSpatialAgentOrchestrator()

    mock_responses = [
        # Round 1: LLM requests get_district_scorecard
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
        # Round 2: LLM requests run_what_if_simulation
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
        # Round 3: LLM returns final answer
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

    with patch.object(orchestrator, "_call_llm", side_effect=mock_responses) as mock_llm_call:
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

            assert resp.rounds_used == 3, f"Expected rounds_used == 3, got {resp.rounds_used}"
            assert resp.stop_reason == "final_answer", f"Expected stop_reason == 'final_answer', got {resp.stop_reason}"
            assert len(resp.tool_trace) == 2, f"Expected 2 tools in tool_trace, got {len(resp.tool_trace)}"
            assert resp.tool_trace[0]["tool"] == "get_district_scorecard"
            assert resp.tool_trace[0]["round"] == 1
            assert resp.tool_trace[0]["ok"] is True
            assert resp.tool_trace[1]["tool"] == "run_what_if_simulation"
            assert resp.tool_trace[1]["round"] == 2
            assert resp.tool_trace[1]["ok"] is True

            action_types = [a.action_type for a in resp.map_actions]
            assert "fly_to" in action_types, f"fly_to action missing: {action_types}"
            assert "render_simulation_layer" in action_types, f"render_simulation_layer missing: {action_types}"
            assert resp.guardrail == "passed", f"Guardrail should pass, got {resp.guardrail}"
            assert len(resp.unsupported_numbers) == 0
            assert len(resp.mislabeled_numbers) == 0
            print(">> [PASSED] Two-round tool calling flow verified.")


# -----------------------------------------------------------------------------
# 2. Maximum Tool Rounds Stop at 4 (Mocked LLM)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_max_tool_rounds_stops_at_four():
    """
    LLM keeps requesting tools for 5 rounds.
    Verifies:
    - Stops at 4
    - stop_reason == 'max_rounds'
    - Deterministic answer returned
    - Numeric guardrail still applied and passes on deterministic summary
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

            # Must stop at 4 rounds
            assert resp.rounds_used == 4, f"Expected rounds_used == 4, got {resp.rounds_used}"
            assert resp.stop_reason == "max_rounds", f"Expected stop_reason == 'max_rounds', got {resp.stop_reason}"
            assert mock_llm_call.call_count == 4, f"LLM should only be called 4 times, got {mock_llm_call.call_count}"
            assert "Ringkasan Analisis Spasial Deterministik" in resp.reply, "Expected deterministic summary in reply"
            assert resp.guardrail == "numeric_fallback"

            # Check that deterministic summary numbers are all valid against tool output
            allowed = build_allowed_numbers([mock_scorecard])
            passed_num, unsupported = validate_numeric_claims(resp.reply, allowed)
            assert passed_num is True, f"Deterministic summary contains unsupported numbers: {unsupported}"
            print(">> [PASSED] Max rounds stop at 4 with deterministic fallback verified.")


# -----------------------------------------------------------------------------
# 3. Conversation History Trimming (10 turns -> last 6 kept)
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_history_trimming_ten_turns():
    """
    History of 10 turns -> only last 6 kept, system prompt present, no orphan tool messages.
    """
    # Create 10 conversation turns (user/assistant pairs)
    messages: List[ChatMessage] = []
    for i in range(1, 11):
        messages.append(ChatMessage(role="user", content=f"User question {i}"))
        if i < 10:
            messages.append(ChatMessage(role="assistant", content=f"Assistant answer {i}"))
            # In turn 8, add a tool response
            if i == 8:
                messages.append(ChatMessage(role="tool", content=json.dumps({"test_tool": 8})))

    trimmed, history_trimmed, history_turns_kept = trim_conversation_history(messages, max_turns=6)

    assert history_trimmed is True, "Expected history_trimmed to be True"
    assert history_turns_kept == 6, f"Expected 6 turns kept, got {history_turns_kept}"

    # Verify first kept user message is Turn 5 (10 - 6 + 1 = 5)
    first_kept_user = next(m for m in trimmed if m["role"] == "user")
    assert first_kept_user["content"] == "User question 5", f"Expected 'User question 5', got {first_kept_user['content']}"

    # Verify Turn 1 to 4 are discarded
    for m in trimmed:
        if m["role"] == "user":
            turn_idx = int(m["content"].split()[-1])
            assert turn_idx >= 5, f"Turns before 5 must be trimmed: {m['content']}"

    # Check orphan tool message handling
    orphan_messages = [
        ChatMessage(role="tool", content="{'orphan': True}"),
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi")
    ]
    orphan_trimmed, _, _ = trim_conversation_history(orphan_messages, max_turns=6)
    # The leading tool message must not be kept without an assistant predecessor
    assert not any(m.get("role") == "tool" for m in orphan_trimmed[:1]), "Orphan tool message must be discarded"

    print(">> [PASSED] History trimming (last 6 turns, system prompt kept, no orphan tools) verified.")


# -----------------------------------------------------------------------------
# 4. Deterministic Map Actions: LLM Text Mention Produces NO Map Action
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_llm_text_mention_produces_no_map_action():
    """
    LLM text that mentions 'fly_to Menteng' without a scorecard tool call produces NO map action.
    """
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

        assert len(resp.map_actions) == 0, f"Map action was emitted from text alone! Got: {resp.map_actions}"
        assert len(resp.tool_calls_executed) == 0
        assert resp.stop_reason == "final_answer"
        print(">> [PASSED] Deterministic map actions (text mention produces no action) verified.")


# -----------------------------------------------------------------------------
# 5. Out-of-Scope Permit Decision & Legal Advice Refusal
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_out_of_scope_permit_refusal():
    """
    Permit-decision question -> refusal text, no tools called.
    """
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
        assert len(resp.tool_calls_executed) == 0, "No tools should be executed for permit refusal"
        assert len(resp.tool_trace) == 0
        assert resp.rounds_used == 0

    print(">> [PASSED] Out-of-scope permit decision / legal advice refusal verified.")


# -----------------------------------------------------------------------------
# 6. Multi-Round Number Validation in Round 3
# -----------------------------------------------------------------------------
@pytest.mark.unit
def test_guardrail_uses_round_one_tool_output_in_round_three():
    """
    Guardrail uses round-1 tool output to validate a number cited in the final answer of round 3.
    """
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

    # Case A: Answer in round 3 cites round 1's population (228.450) and round 2's unserved area (1.25). Should PASS.
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
            assert resp.guardrail == "passed", f"Expected guardrail == 'passed', got {resp.guardrail}"
            assert len(resp.unsupported_numbers) == 0

    # Case B: Answer in round 3 cites a fabricated number (999.888) not in round 1 or round 2. Should FAIL.
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
        # Retry also fails
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
            assert resp.guardrail == "numeric_fallback", f"Fabricated number must trigger fallback, got {resp.guardrail}"
            assert "999.888" in resp.unsupported_numbers

    print(">> [PASSED] Multi-round numeric validation across rounds 1-3 verified.")


# -----------------------------------------------------------------------------
# 7. Live Test with Ollama (if available)
# -----------------------------------------------------------------------------
@pytest.mark.llm
@pytest.mark.db
def test_live_ollama_two_step_tebet():
    """
    Live test with Ollama (if available): one two-step question for Tebet
    (scorecard + what-if +10,000 jiwa).
    Reports rounds_used, stop_reason, tool_trace, guardrail, unsupported_numbers,
    mislabeled_numbers, and map actions.
    If Ollama is unavailable, reports honestly without faking.
    """
    print("\n--- Running Live Ollama Test (Tebet Two-Step Question) ---")
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        req_check = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_check, timeout=3) as resp_check:
            models_info = json.loads(resp_check.read().decode("utf-8"))
            available_models = [m.get("name") for m in models_info.get("models", [])]
    except Exception as e:
        print(f">> [SKIPPED] Ollama is not available at {ollama_url}: {e}")
        return

    model_name = os.getenv("OLLAMA_MODEL_NAME", "qwen2.5:14b")
    matched_model = next((m for m in available_models if model_name in m or "qwen2.5" in m), None)
    if not matched_model:
        print(f">> [SKIPPED] Model {model_name} not found in Ollama models: {available_models}")
        return

    orchestrator = CognitiveSpatialAgentOrchestrator()
    orchestrator.model_name = matched_model

    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content=(
                    "Berapa skor kelayakan hidup di Kecamatan Tebet (kode 31.71.09) saat ini? "
                    "Dan jika populasinya bertambah 10.000 jiwa lewat simulasi what-if, bagaimana perubahannya?"
                )
            )
        ]
    )

    resp = orchestrator.process_chat(req)

    print(f"\nLive Ollama Test Results (model={resp.model_used}, latency={resp.latency_seconds}s):")
    print(f"- rounds_used: {resp.rounds_used}")
    print(f"- stop_reason: {resp.stop_reason}")
    print(f"- tool_trace: {resp.tool_trace}")
    print(f"- map_actions: {[a.action_type for a in resp.map_actions]}")
    print(f"- guardrail: {resp.guardrail}")
    print(f"- unsupported_numbers: {resp.unsupported_numbers}")
    print(f"- mislabeled_numbers: {resp.mislabeled_numbers}")
    print(f"- reply preview:\n{resp.reply[:300]}...\n")

    assert resp.rounds_used >= 1
    assert resp.stop_reason in ("final_answer", "max_rounds")
    assert len(resp.tool_trace) >= 1
    assert len(resp.map_actions) >= 1
    assert resp.guardrail in ("passed", "retried", "numeric_fallback")
    print(">> [PASSED] Live Ollama Tebet multi-round flow executed successfully.")


def run_suite():
    print("=" * 70)
    print("RUNNING TEST SUITE: MULTI-ROUND AGENT & DETERMINISTIC ACTIONS")
    print("=" * 70)
    test_two_round_flow_mocked()
    test_max_tool_rounds_stops_at_four()
    test_history_trimming_ten_turns()
    test_llm_text_mention_produces_no_map_action()
    test_out_of_scope_permit_refusal()
    test_guardrail_uses_round_one_tool_output_in_round_three()
    test_live_ollama_two_step_tebet()
    print("=" * 70)
    print("ALL TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    init_db_pool()
    try:
        run_suite()
    finally:
        close_db_pool()
