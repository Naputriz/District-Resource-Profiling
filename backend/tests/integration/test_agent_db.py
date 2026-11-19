"""
Integration Tests for Cognitive Spatial Agent deterministic tool execution.
Requires PostGIS database. Marker: db.
"""

import pytest
from backend.app.agent.tools import execute_tool_call
from backend.app.core.db import init_db_pool

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]


def test_agent_tools_deterministic():
    """Validates that agent tools execute deterministically with real PostGIS database."""
    init_db_pool()

    # 1. Tebet scorecard
    res = execute_tool_call("get_district_scorecard", {"district_code": "31.71.09"})
    assert res["kemendagri_code"] == "31.71.09"
    assert "composite_livability_score" in res

    # 2. Blank spots
    res_bs = execute_tool_call("get_unserved_blank_spots", {"district_code": "31.71.09", "facility_type": "puskesmas_kelurahan"})
    assert res_bs["district_code"] == "31.71.09"
    assert "unserved_area_km2" in res_bs

    # 3. Hybrid RAG
    res_rag = execute_tool_call("search_regulations", {"query": "standar puskesmas kelurahan radius 1000m"})
    assert res_rag["total_found"] > 0

    # 4. What-if simulation
    res_sim = execute_tool_call("run_what_if_simulation", {"district_code": "31.71.09", "population_shock_count": 10000})
    assert res_sim["is_sandbox_isolated"] is True
    assert res_sim["population_delta"] == 10000
