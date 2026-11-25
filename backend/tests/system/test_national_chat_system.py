"""
System Live Chat & LLM Tests for Task U2 (Indonesia-scale, province, ranking, and methodology queries).
Evaluates CognitiveSpatialAgentOrchestrator with live Ollama (qwen2.5:14b) on staging DB.
Markers: llm, system, db.
"""

import json
import os
import re
import urllib.request
import pytest

from backend.app.core.config import settings
from backend.app.core.db import init_db_pool, close_db_pool, get_db_cursor, get_redis_client
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    ChatMessage,
)
from backend.app.agent.guardrails import build_allowed_numbers, parse_number_candidates, is_number_matched

pytestmark = [pytest.mark.llm, pytest.mark.system, pytest.mark.db]

ALL_38_PROVS = ",".join([
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "21",
    "31", "32", "33", "34", "35", "36",
    "51", "52", "53",
    "61", "62", "63", "64", "65",
    "71", "72", "73", "74", "75", "76",
    "81", "82",
    "91", "92", "93", "94", "95", "96",
])


@pytest.fixture(scope="module", autouse=True)
def require_ollama_and_staging_38(monkeypatch_module=None):
    orig_active = settings.ACTIVE_PROVINCES
    settings.ACTIVE_PROVINCES = ALL_38_PROVS
    init_db_pool()

    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    try:
        req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            available_models = [m.get("name") for m in data.get("models", [])]
    except Exception as e:
        settings.ACTIVE_PROVINCES = orig_active
        pytest.skip(f"Ollama is not reachable at {ollama_url}: {e}")

    model_name = os.getenv("OLLAMA_MODEL_NAME", "qwen2.5:14b")
    matched = next((m for m in available_models if model_name in m or "qwen2.5" in m), None)
    if not matched:
        settings.ACTIVE_PROVINCES = orig_active
        pytest.skip(f"Model {model_name} not available in Ollama (found: {available_models})")

    r = get_redis_client()
    if r:
        for k in r.keys("cache:agent:*"):
            r.delete(k)

    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM incident_logs;")
        initial_incident_ids = {str(r_row["id"]) for r_row in cur.fetchall()}

    try:
        yield matched
    finally:
        settings.ACTIVE_PROVINCES = orig_active
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


def _assert_reply_has_tool_number(reply: str, tool_outputs: list) -> None:
    allowed = build_allowed_numbers(tool_outputs)
    found = False
    for m in re.finditer(r"-?\b\d+(?:[.,]\d+)*(?:%)?", reply):
        for cand in parse_number_candidates(m.group(0)):
            if is_number_matched(cand, allowed):
                found = True
                break
        if found:
            break
    assert found, f"Expected at least one number from tool output in reply: {reply}"


@pytest.mark.parametrize(
    "qid,question,expected_tools",
    [
        (
            "nat_lowest_province",
            "Provinsi mana yang skor rata-ratanya paling rendah?",
            {"get_national_overview"},
        ),
        (
            "nat_memadai_count",
            "Berapa kecamatan di Indonesia yang datanya memadai?",
            {"get_national_overview"},
        ),
        (
            "prov_compare_jabar_bali",
            "Bandingkan Jawa Barat dan Bali",
            {"compare_provinces", "get_province_summary"},
        ),
        (
            "nat_rank_highest_district",
            "Kecamatan dengan skor tertinggi di Indonesia?",
            {"rank_districts"},
        ),
        (
            "prov_papua_split",
            "Bagaimana kondisi fasilitas di Papua?",
            {"get_province_summary"},
        ),
        (
            "concept_scoring",
            "Bagaimana skor dihitung?",
            {"get_methodology"},
        ),
        (
            "prov_jabar_alias",
            "Bagaimana ringkasan fasilitas di Jabar?",
            {"get_province_summary"},
        ),
    ],
)
def test_national_and_province_chat_live_llm(
    require_ollama_and_staging_38, qid, question, expected_tools
):
    """Live Ollama evaluation of national, province, ranking, and methodology queries."""
    orch = CognitiveSpatialAgentOrchestrator()
    orch.model_name = require_ollama_and_staging_38

    req = AgentChatRequest(
        messages=[ChatMessage(role="user", content=question)],
        province_code="31",
    )
    resp = orch.process_chat(req)

    tools_called = {t["name"] for t in resp.tool_calls_executed}
    tool_outputs = [t["result_summary"] for t in resp.tool_calls_executed]
    print(
        f"[LLM-U2] {qid}: latency={resp.latency_seconds:.2f}s guardrail={resp.guardrail} "
        f"tools={sorted(tools_called)}"
    )

    assert resp.latency_seconds > 0
    assert len(resp.reply) > 20
    assert resp.guardrail in ("passed", "retried"), (
        f"{qid} hit guardrail={resp.guardrail}, unsupported={resp.unsupported_numbers}, "
        f"mislabeled={resp.mislabeled_numbers}, reply={resp.reply[:200]}"
    )
    assert tools_called & expected_tools, f"{qid} called {tools_called}, expected one of {expected_tools}"
    _assert_reply_has_tool_number(resp.reply, tool_outputs)
