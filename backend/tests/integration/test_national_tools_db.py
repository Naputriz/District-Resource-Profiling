"""
Integration DB Tests for Task U2 national, province, ranking, comparison, and methodology tools.
Runs against staging database (38 provinces) + Redis. Marker: db.
"""

import time
import pytest

from backend.app.agent.tools import execute_tool_call
from backend.app.core.config import settings
from backend.app.core.db import init_db_pool, get_redis_client

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("requires_seed")]

ALL_38_PROVS = ",".join([
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "21",
    "31", "32", "33", "34", "35", "36",
    "51", "52", "53",
    "61", "62", "63", "64", "65",
    "71", "72", "73", "74", "75", "76",
    "81", "82",
    "91", "92", "93", "94", "95", "96",
])


@pytest.fixture(autouse=True)
def enable_all_38_provinces(monkeypatch):
    monkeypatch.setattr(settings, "ACTIVE_PROVINCES", ALL_38_PROVS)
    init_db_pool()
    r = get_redis_client()
    if r:
        for k in r.keys("cache:agent:*"):
            r.delete(k)


def test_national_overview_tool_db_and_warm_cache():
    ov = execute_tool_call("get_national_overview", {})
    assert "error" not in ov
    assert ov["active_provinces_count"] == 38
    assert ov["total_kecamatan"] == 7033
    assert ov["scored_kecamatan_count"] == 1878
    assert ov["insufficient_data_kecamatan_count"] == 5155
    assert ov["locally_adequate_osm_count"] == 2942
    assert ov["national_average_composite_score"] == 19.9
    assert ov["lowest_average_province"]["province_code"] == "51"
    assert ov["highest_average_province"]["province_code"] == "31"
    assert len(ov["provinces"]) == 38

    t0 = time.perf_counter()
    ov_warm = execute_tool_call("get_national_overview", {})
    warm_ms = (time.perf_counter() - t0) * 1000.0
    assert warm_ms < 300.0
    assert ov_warm["total_kecamatan"] == 7033


def test_province_summary_aliases_and_papua_split_db():
    jabar = execute_tool_call("get_province_summary", {"province": "Jabar"})
    assert jabar["province_code"] == "32"
    assert jabar["total_kecamatan"] == 627
    assert jabar["scored_kecamatan_count"] == 321
    assert jabar["insufficient_data_kecamatan_count"] == 306
    assert len(jabar["top_5_kecamatan"]) == 5
    assert len(jabar["bottom_5_kecamatan"]) == 5
    assert jabar["pillar_averages"]["education"]["average_score"] is not None

    diy = execute_tool_call("get_province_summary", {"province": "DIY"})
    assert diy["province_code"] == "34"
    assert diy["total_kecamatan"] == 78
    assert diy["scored_kecamatan_count"] == 66

    papua_group = execute_tool_call("get_province_summary", {"province": "Papua"})
    assert papua_group["is_province_group"] is True
    assert papua_group["provinces_count"] == 6
    assert papua_group["total_kecamatan"] == 601
    assert papua_group["locally_adequate_osm_count"] == 241
    assert "2022" in papua_group["ambiguity_note"]

    papua_91 = execute_tool_call("get_province_summary", {"province": "91"})
    assert papua_91["is_province_group"] is False
    assert papua_91["province_code"] == "91"
    assert papua_91["total_kecamatan"] == 97

    t0 = time.perf_counter()
    _ = execute_tool_call("get_province_summary", {"province": "Jabar"})
    warm_ms = (time.perf_counter() - t0) * 1000.0
    assert warm_ms < 300.0


def test_rank_districts_and_compare_provinces_and_methodology_db():
    top_nat = execute_tool_call(
        "rank_districts",
        {"scope": "national", "order": "highest", "metric": "composite", "limit": 5},
    )
    assert len(top_nat["results"]) == 5
    assert all(r["score"] is not None for r in top_nat["results"])
    assert top_nat["results"][0]["score"] >= top_nat["results"][-1]["score"]

    low_bali = execute_tool_call(
        "rank_districts",
        {"scope": "Bali", "order": "lowest", "metric": "composite", "limit": 15},
    )
    assert low_bali["limit"] == 10
    assert len(low_bali["results"]) == 10
    assert all(r["province_code"] == "51" for r in low_bali["results"])
    assert low_bali["results"][0]["score"] <= low_bali["results"][-1]["score"]

    cmp_res = execute_tool_call(
        "compare_provinces",
        {"provinces": ["Jawa Barat", "Bali"]},
    )
    assert cmp_res["compared_count"] == 2
    assert cmp_res["highest_average_province"]["province_name"] == "Jawa Barat"
    assert cmp_res["lowest_average_province"]["province_name"] == "Bali"

    meth = execute_tool_call("get_methodology", {})
    assert meth["total_standards_catalog"] == 16
    assert meth["scored_standards_count"] == 7
    assert meth["informational_standards_count"] == 9
    assert meth["data_tidak_memadai_rule"]["local_sd_population_threshold"] == 1600
    assert len(meth["standards_table"]) == 16

    # Cross-province kecamatan lookup works even when active province is '31'
    coblong = execute_tool_call(
        "get_district_scorecard",
        {"district_code": "Coblong"},
        province_code="31",
    )
    assert coblong["kemendagri_code"] == "32.73.230"
    assert coblong["province_code"] == "32"
