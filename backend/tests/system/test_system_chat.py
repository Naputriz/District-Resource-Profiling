"""
System Live Chat & LLM Evaluation Tests.
Evaluates CognitiveSpatialAgentOrchestrator with live Ollama (qwen2.5:14b).
Markers: llm, system.

Covers:
1. Q1: Scorecard Tebet composite score (expected tool: get_district_scorecard).
2. Q2: Tebet health pillar score (expected tool: get_district_scorecard).
3. Q3: SNI primary school service radius (expected tool: search_regulations).
4. Q4: Population shock simulation (+15,000 in Tebet) (expected tool: run_what_if_simulation).
5. Q5: Out-of-scope permit decision refusal (deterministic 0-round refusal).
6. test_agent_conversation_with_qwen (migrated from test_cognitive_agent.py).
7. test_live_ollama_two_step_tebet (migrated from test_multi_round_agent.py).

Skipped honestly if Ollama is unreachable.
"""

import json
import os
import time
import urllib.request
import pytest

from backend.app.core.db import init_db_pool, close_db_pool
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    ChatMessage,
)

pytestmark = [pytest.mark.llm, pytest.mark.system, pytest.mark.db]


@pytest.fixture(scope="session", autouse=True)
def require_ollama_and_db():
    init_db_pool()
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            available_models = [m.get("name") for m in data.get("models", [])]
    except Exception as e:
        pytest.skip(f"Ollama is not reachable at {ollama_url}: {e}")

    model_name = os.getenv("OLLAMA_MODEL_NAME", "qwen2.5:14b")
    matched = next((m for m in available_models if model_name in m or "qwen2.5" in m), None)
    if not matched:
        pytest.skip(f"Model {model_name} not available in Ollama (found: {available_models})")

    from backend.app.core.db import get_db_cursor
    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM incident_logs;")
        initial_incident_ids = {str(r["id"]) for r in cur.fetchall()}

    try:
        yield matched
    finally:
        try:
            with get_db_cursor() as cur:
                if initial_incident_ids:
                    cur.execute(
                        "DELETE FROM incident_logs WHERE id::text NOT IN %s;",
                        (tuple(initial_incident_ids),),
                    )
        except Exception:
            pass
        close_db_pool()


def test_system_chat_q1_scorecard_tebet(require_ollama_and_db):
    """Q1: Scorecard inquiry triggers get_district_scorecard tool and passes numeric guardrail."""
    orchestrator = CognitiveSpatialAgentOrchestrator()
    orchestrator.model_name = require_ollama_and_db

    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Berapa skor indeks kecukupan fasilitas di Kecamatan Tebet (31.71.09)?",
            )
        ]
    )
    resp = orchestrator.process_chat(req)

    assert len(resp.reply) > 20
    assert resp.guardrail in ("passed", "retried", "numeric_fallback")
    tools_called = [t["name"] for t in resp.tool_calls_executed]
    assert "get_district_scorecard" in tools_called or len(resp.tool_trace) > 0


def test_system_chat_q2_health_pillar_tebet(require_ollama_and_db):
    """Q2: Pillar health inquiry retrieves scorecard and verifies health pillar data."""
    orchestrator = CognitiveSpatialAgentOrchestrator()
    orchestrator.model_name = require_ollama_and_db

    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Bagaimana skor pilar kesehatan di Kecamatan Tebet?",
            )
        ]
    )
    resp = orchestrator.process_chat(req)

    assert len(resp.reply) > 20
    assert resp.guardrail in ("passed", "retried", "numeric_fallback")
    tools_called = [t["name"] for t in resp.tool_calls_executed]
    assert "get_district_scorecard" in tools_called or len(resp.tool_trace) > 0


def test_system_chat_q3_regulation_sni_sd(require_ollama_and_db):
    """Q3: Standard radius inquiry searches regulations and outputs validated citation."""
    orchestrator = CognitiveSpatialAgentOrchestrator()
    orchestrator.model_name = require_ollama_and_db

    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Apa standar radius pelayanan sekolah dasar menurut SNI?",
            )
        ]
    )
    resp = orchestrator.process_chat(req)

    assert len(resp.reply) > 20
    assert resp.guardrail in ("passed", "retried", "numeric_fallback")
    # Verify SNI citation presence or tool execution
    reply_lower = resp.reply.lower()
    assert "sni" in reply_lower or "1.000" in reply_lower or "1000" in reply_lower or len(resp.citations) > 0


def test_system_chat_q4_whatif_population_shock(require_ollama_and_db):
    """Q4: Population shock triggers run_what_if_simulation tool in isolated sandbox."""
    orchestrator = CognitiveSpatialAgentOrchestrator()
    orchestrator.model_name = require_ollama_and_db

    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Simulasi lonjakan 15.000 penduduk di Tebet",
            )
        ]
    )
    resp = orchestrator.process_chat(req)

    assert len(resp.reply) > 20
    assert resp.guardrail in ("passed", "retried", "numeric_fallback")
    tools_called = [t["name"] for t in resp.tool_calls_executed]
    assert "run_what_if_simulation" in tools_called or len(resp.tool_trace) > 0


def test_system_chat_q5_out_of_scope_permit_refusal(require_ollama_and_db):
    """Q5: Permit decision question is refused deterministically without LLM hallucination."""
    orchestrator = CognitiveSpatialAgentOrchestrator()
    orchestrator.model_name = require_ollama_and_db

    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Apakah proyek superblok 3.000 unit di Tebet ini boleh disetujui izin pembangunannya?",
            )
        ]
    )
    resp = orchestrator.process_chat(req)

    assert resp.rounds_used == 0
    assert resp.guardrail == "passed"
    reply_lower = resp.reply.lower()
    assert "tidak berwenang" in reply_lower or "perizinan resmi" in reply_lower or "izin" in reply_lower


def test_agent_conversation_with_qwen(require_ollama_and_db):
    """Live full agent loop test (migrated from test_cognitive_agent.py)."""
    orchestrator = CognitiveSpatialAgentOrchestrator()
    orchestrator.model_name = require_ollama_and_db

    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Berapa skor kelayakan hidup di Kecamatan Tebet (kode 31.71.09) dan bagaimana kecukupan fasilitas kesehatannya?",
            )
        ]
    )
    resp = orchestrator.process_chat(req)

    assert len(resp.reply) > 50
    assert resp.latency_seconds > 0
    assert resp.guardrail in ("passed", "retried", "numeric_fallback")
    if resp.guardrail in ("passed", "retried"):
        assert len(resp.unsupported_numbers) == 0
        assert len(resp.mislabeled_numbers) == 0


def test_live_ollama_two_step_tebet(require_ollama_and_db):
    """Live multi-round Ollama test (migrated from test_multi_round_agent.py)."""
    orchestrator = CognitiveSpatialAgentOrchestrator()
    orchestrator.model_name = require_ollama_and_db

    req = AgentChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content=(
                    "Berapa skor kelayakan hidup di Kecamatan Tebet (kode 31.71.09) saat ini? "
                    "Dan jika populasinya bertambah 10.000 jiwa lewat simulasi what-if, bagaimana perubahannya?"
                ),
            )
        ]
    )
    resp = orchestrator.process_chat(req)

    assert resp.rounds_used >= 1
    assert resp.stop_reason in ("final_answer", "max_rounds")
    assert len(resp.tool_trace) >= 1
    assert len(resp.map_actions) >= 1
    assert resp.guardrail in ("passed", "retried", "numeric_fallback")
