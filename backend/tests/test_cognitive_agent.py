"""
End-to-End Tests for Cognitive Spatial Agent.
Validates:
1. Deterministic tool execution (scorecard, simulation, blank spots, RAG).
2. Cognitive Agent loop with local Qwen 2.5 14B.
3. Dual-View Sync Map Action Events generation.
"""

import time
import pytest
from backend.app.agent.tools import execute_tool_call
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    ChatMessage
)
from backend.app.core.db import init_db_pool, close_db_pool

@pytest.mark.db
def test_agent_tools_deterministic():
    print("Testing Tool: get_district_scorecard (Tebet)...")
    res = execute_tool_call("get_district_scorecard", {"district_code": "31.71.09"})
    assert res["kemendagri_code"] == "31.71.09"
    assert "composite_livability_score" in res
    print(f" -> Scorecard Tebet: Score={res['composite_livability_score']}, Pop={res['population']:,}")

    print("Testing Tool: get_unserved_blank_spots...")
    res_bs = execute_tool_call("get_unserved_blank_spots", {"district_code": "31.71.09", "facility_type": "puskesmas_kelurahan"})
    assert res_bs["district_code"] == "31.71.09"
    assert "unserved_area_km2" in res_bs
    print(f" -> Blank spots: Unserved={res_bs['unserved_area_km2']} km², Coverage={res_bs['coverage_percentage']}")

    print("Testing Tool: search_regulations (Hybrid RAG)...")
    res_rag = execute_tool_call("search_regulations", {"query": "standar puskesmas kelurahan radius 1000m"})
    assert res_rag["total_found"] > 0
    print(f" -> Hybrid RAG found {res_rag['total_found']} citations.")

    print("Testing Tool: run_what_if_simulation...")
    res_sim = execute_tool_call("run_what_if_simulation", {"district_code": "31.71.09", "population_shock_count": 10000})
    assert res_sim["is_sandbox_isolated"] is True
    assert res_sim["population_delta"] == 10000
    print(f" -> Simulation Delta: Pop Delta=+10,000, Score Delta={res_sim['score_delta']}")

@pytest.mark.unit
def test_guardrail_mismatch_triggers_fallback():
    """Verify that if LLM produces numbers that mismatch tool outputs, numeric_fallback MUST be reported."""
    from unittest.mock import patch
    import json
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
            print(" -> Guardrail mismatch fallback verified successfully.")

@pytest.mark.llm
@pytest.mark.db
def test_agent_conversation_with_qwen():
    orchestrator = CognitiveSpatialAgentOrchestrator()
    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Berapa skor kelayakan hidup di Kecamatan Tebet (kode 31.71.09) dan bagaimana kecukupan fasilitas kesehatannya?"
            )
        ]
    )

    print("\nSending user query to Cognitive Spatial Agent (Qwen 2.5 14B)...")
    t0 = time.time()
    resp = orchestrator.process_chat(req)
    elapsed = time.time() - t0

    print(f"\nAgent Response ({elapsed:.2f}s):\n{resp.reply}\n")
    print(f"Tools Executed: {[t['name'] for t in resp.tool_calls_executed]}")
    print(f"Map Action Events: {[a.action_type for a in resp.map_actions]}")
    print(f"Model: {resp.model_used}")
    print(f"Guardrail Status: {resp.guardrail}")
    print(f"Unsupported Numbers: {resp.unsupported_numbers}")
    print(f"Mislabeled Numbers: {resp.mislabeled_numbers}")
    print(f"Validated Citations: {resp.citations}")
    print(f"Removed Citations: {resp.removed_citations}")

    assert len(resp.reply) > 50
    assert resp.latency_seconds > 0

    # Cognitive agent response verification:
    # Do not print PASSED for the agent suite unless the response's numbers are verified or safe fallback activated.
    assert resp.guardrail in ("passed", "retried", "numeric_fallback"), (
        f"Agent test failed guardrail validation: guardrail={resp.guardrail}, "
        f"unsupported_numbers={resp.unsupported_numbers}, mislabeled_numbers={resp.mislabeled_numbers}"
    )
    if resp.guardrail in ("passed", "retried"):
        assert len(resp.unsupported_numbers) == 0, f"Unsupported numbers detected: {resp.unsupported_numbers}"
        assert len(resp.mislabeled_numbers) == 0, f"Mislabeled numbers detected: {resp.mislabeled_numbers}"

if __name__ == "__main__":
    init_db_pool()
    try:
        print("=== 1. TESTING AGENT TOOLS DETERMINISTICALLY ===")
        test_agent_tools_deterministic()
        print("\n=== 2. TESTING GUARDRAIL MISMATCH FALLBACK ===")
        test_guardrail_mismatch_triggers_fallback()
        print("\n=== 3. TESTING FULL AGENT LOOP WITH QWEN 2.5 14B ===")
        test_agent_conversation_with_qwen()
        print("\nALL COGNITIVE SPATIAL AGENT TESTS COMPLETED SUCCESSFULLY!")
    finally:
        close_db_pool()
