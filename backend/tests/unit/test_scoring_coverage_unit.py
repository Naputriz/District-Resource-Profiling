"""
Unit tests for Standards Availability, Coverage, and Proportional Re-weighting.
Complies with Phase 4.2 & Phase 5.1 (REBUILD_PROMPT_P5_1_P7.md). Marker: unit.
"""

import pytest
from backend.app.engine.standards_availability import (
    evaluate_availability,
    calculate_pillar_and_composite_scores,
    build_district_metrics_and_scores,
    LOCAL_GATE_REASON,
    STANDARDS_AVAILABILITY_SPEC,
    CITY_WIDE_CLASSIFIED_COUNTS,
    BASE_PILLAR_WEIGHTS
)

pytestmark = pytest.mark.unit


def test_evaluate_availability_rules():
    # Rule 1: not_available from mapping or 0 count
    flag1, reason1 = evaluate_availability("taman_rt", 0, "Low", True)
    assert flag1 == "not_available"
    assert "NOT_AVAILABLE_FROM_OSM" in reason1

    flag2, reason2 = evaluate_availability("taman_kecamatan", 0, "High", False)
    assert flag2 == "not_available"
    assert "0 classified records" in reason2

    # Rule 2: insufficient (count < 44 REGARDLESS of confidence)
    flag3, reason3 = evaluate_availability("taman_kelurahan", 2, "Low", False)
    assert flag3 == "insufficient"
    assert "<44" in reason3

    flag_rptra, reason_rptra = evaluate_availability("taman_rptra", 22, "Medium", False)
    assert flag_rptra == "insufficient"
    assert "<44" in reason_rptra

    # Rule 3: available (count >= 44)
    flag4, _ = evaluate_availability("pos_damkar", 99, "Medium", False)
    assert flag4 == "available"

    flag5, _ = evaluate_availability("rumah_sakit", 327, "High", False)
    assert flag5 == "available"


def test_pillar_single_type_excluded_from_composite_phase_5_1():
    """
    Phase 5.1 / VALID-1: A pillar with fewer than 2 scored+available types gets
    score: None, status: 'cakupan data rendah', and weight 0 (included_in_composite: False).
    The remaining pillars with types_scored >= 2 re-normalize proportionally.
    """
    availability_map = {
        "puskesmas_kelurahan": ("available", "Available"),
        "pos_damkar": ("available", "Available"),
        "sekolah_dasar": ("available", "Available"),
        "sekolah_menengah_pertama": ("available", "Available"),
        "taman_rt": ("not_available", "No data"),
        "taman_kelurahan": ("insufficient", "Insufficient"),
        "stasiun_transit": ("available", "Available"),
        "halte_transjakarta": ("available", "Available")
    }

    metrics = [
        {"pillar": "lifeline_health", "facility_type": "puskesmas_kelurahan", "compliance_pct": 80.0, "scored": True},
        {"pillar": "lifeline_health", "facility_type": "pos_damkar", "compliance_pct": 60.0, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_dasar", "compliance_pct": 50.0, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_menengah_pertama", "compliance_pct": 70.0, "scored": True},
        {"pillar": "urban_livability", "facility_type": "taman_rt", "compliance_pct": 0.0, "scored": False},
        {"pillar": "urban_livability", "facility_type": "taman_kelurahan", "compliance_pct": 0.0, "scored": False},
        {"pillar": "mobility_connectivity", "facility_type": "stasiun_transit", "compliance_pct": 90.0, "scored": False},
        {"pillar": "mobility_connectivity", "facility_type": "halte_transjakarta", "compliance_pct": 90.0, "scored": False}
    ]

    res = calculate_pillar_and_composite_scores(metrics, availability_map)
    pillars = res["pillar_scores"]

    assert pillars["lifeline_health"]["status"] == "tersedia"
    assert pillars["lifeline_health"]["included_in_composite"] is True
    assert pillars["lifeline_health"]["score"] == 70.0

    assert pillars["education"]["status"] == "tersedia"
    assert pillars["education"]["included_in_composite"] is True
    assert pillars["education"]["score"] == 60.0

    assert pillars["urban_livability"]["status"] == "cakupan data rendah"
    assert pillars["urban_livability"]["included_in_composite"] is False
    assert pillars["urban_livability"]["score"] is None

    assert pillars["mobility_connectivity"]["status"] == "cakupan data rendah"
    assert pillars["mobility_connectivity"]["included_in_composite"] is False
    assert pillars["mobility_connectivity"]["score"] is None

    assert res["composite_score"] == 65.45
    assert "Pilar ruang hidup tidak dihitung dalam skor komposit: tidak ada jenis fasilitas yang dinilai (lihat README §6.3)" in res["composite_note"]
    assert "0.55" in res["composite_note"]


def test_exact_reweighting_edge_cases():
    """Verifies proportional re-weighting with multiple excluded pillars."""
    availability_map = {
        "puskesmas_kelurahan": ("available", "Available"),
        "pos_damkar": ("available", "Available"),
        "sekolah_dasar": ("not_available", "Excluded"),
        "taman_rt": ("not_available", "Excluded"),
        "stasiun_transit": ("not_available", "Excluded")
    }

    metrics = [
        {"pillar": "lifeline_health", "facility_type": "puskesmas_kelurahan", "compliance_pct": 80.0, "existing": 4, "required": 5, "scored": True},
        {"pillar": "lifeline_health", "facility_type": "pos_damkar", "compliance_pct": 70.0, "existing": 3, "required": 4, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_dasar", "compliance_pct": 0.0, "existing": 0, "required": 5, "scored": True},
        {"pillar": "urban_livability", "facility_type": "taman_rt", "compliance_pct": 0.0, "existing": 0, "required": 5, "scored": False},
        {"pillar": "mobility_connectivity", "facility_type": "stasiun_transit", "compliance_pct": 0.0, "existing": 0, "required": 2, "scored": False}
    ]

    res = calculate_pillar_and_composite_scores(metrics, availability_map)
    assert res["composite_score"] == 75.0
    assert res["pillar_scores"]["lifeline_health"]["included_in_composite"] is True
    assert res["pillar_scores"]["education"]["included_in_composite"] is False
    assert res["pillar_scores"]["urban_livability"]["included_in_composite"] is False
    assert res["pillar_scores"]["mobility_connectivity"]["included_in_composite"] is False


def test_valid1_removed_types_absent():
    """Step E.1: Verify 6 removed types from §6.4 are absent from standards and city counts."""
    removed_types = [
        "tps_3r", "hutan_kota", "gelanggang_olahraga",
        "perpustakaan_wilayah", "sentra_niaga_umkm", "pos_polisi"
    ]
    for r_type in removed_types:
        assert r_type not in CITY_WIDE_CLASSIFIED_COUNTS, f"{r_type} still in snapshot"
        assert r_type not in STANDARDS_AVAILABILITY_SPEC, f"{r_type} still in spec"


def test_valid1_informational_types_produce_no_deficit():
    """Step E.1: Informational types produce no deficit and no score."""
    informational_types = [k for k, v in STANDARDS_AVAILABILITY_SPEC.items() if not v.get("scored")]
    assert len(informational_types) == 9

    sample_metrics = [
        {"pillar": "urban_livability", "facility_type": "taman_rt", "existing": 0, "required": None, "deficit": None, "compliance_pct": None, "scored": False},
        {"pillar": "lifeline_health", "facility_type": "rumah_sakit", "existing": 2, "required": None, "deficit": None, "compliance_pct": None, "scored": False}
    ]
    for m in sample_metrics:
        assert m["deficit"] is None
        assert m["required"] is None


def test_valid1_pillar_with_less_than_two_types_has_null_score():
    """Step E.1: Pillar with <2 scored types gets score: None, status: 'cakupan data rendah', weight 0."""
    metrics = [
        {"pillar": "lifeline_health", "facility_type": "pos_damkar", "compliance_pct": 100.0, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_dasar", "compliance_pct": 80.0, "scored": True},
        {"pillar": "education", "facility_type": "sekolah_menengah_pertama", "compliance_pct": 60.0, "scored": True}
    ]
    res = calculate_pillar_and_composite_scores(metrics)
    health = res["pillar_scores"]["lifeline_health"]
    assert health["score"] is None
    assert health["status"] == "cakupan data rendah"
    assert health["included_in_composite"] is False


def test_province_scaled_threshold_reason_and_status():
    """J1a2 Rule 1: Threshold scales with number of kecamatan in province (e.g., 627 for Jabar)."""
    flag_low, reason_low = evaluate_availability(
        "puskesmas_kelurahan", 414, "Low", False, min_records_threshold=627
    )
    assert flag_low == "insufficient"
    assert "(<627)" in reason_low

    flag_ok, reason_ok = evaluate_availability(
        "sekolah_dasar", 3404, "Medium", False, min_records_threshold=627
    )
    assert flag_ok == "available"
    assert reason_ok == "Classified records >= 627 (3404)"


def test_local_coverage_gate_and_dki_like_unchanged():
    """J1a2 Rules 2 & 3: Pop >= 1600 with 0 mapped SD gates count-based scores to NULL; DKI-like stays unchanged."""
    standards = [
        ("taman_kanak_kanak", "education", 1250, 500, True, "SNI"),
        ("sekolah_dasar", "education", 1600, 1000, True, "SNI"),
        ("sekolah_menengah_pertama", "education", 4800, 1000, True, "SNI"),
        ("sekolah_menengah_atas", "education", 4800, 3000, True, "SNI"),
        ("puskesmas_kelurahan", "lifeline_health", 30000, 1500, True, "SNI"),
        ("puskesmas_kecamatan", "lifeline_health", 120000, 3000, True, "SNI"),
        ("pos_damkar", "lifeline_health", 120000, None, True, "SNI"),
        ("taman_rt", "urban_livability", None, None, False, "SNI"),
    ]
    avail_map = {
        "taman_kanak_kanak": ("available", "Classified records >= 44 (2274)"),
        "sekolah_dasar": ("available", "Classified records >= 44 (1483)"),
        "sekolah_menengah_pertama": ("available", "Classified records >= 44 (633)"),
        "sekolah_menengah_atas": ("available", "Classified records >= 44 (539)"),
        "puskesmas_kelurahan": ("available", "Classified records >= 44 (289)"),
        "puskesmas_kecamatan": ("available", "Classified records >= 44 (57)"),
        "pos_damkar": ("available", "Classified records >= 44 (99)"),
        "taman_rt": ("not_available", "NOT_AVAILABLE_FROM_OSM (0 classified records city-wide)"),
    }

    # Gated kecamatan: pop = 50,000 (>= 1,600) and sekolah_dasar = 0
    gated = build_district_metrics_and_scores(
        pop=50000,
        fac_counts={"taman_kanak_kanak": 2, "sekolah_dasar": 0, "puskesmas_kelurahan": 1},
        standards=standards,
        availability_map=avail_map,
    )
    assert gated["local_gated"] is True
    assert gated["coverage"]["osm_coverage"]["status"] == "tidak_memadai"
    assert gated["coverage"]["osm_coverage"]["mapped_sd"] == 0
    assert gated["coverage"]["osm_coverage"]["required_sd"] == 32
    assert gated["scores_res"]["composite_score"] is None
    for p_data in gated["scores_res"]["pillar_scores"].values():
        assert p_data["score"] is None
    assert "1.600" in gated["scores_res"]["composite_note"]

    for m in gated["metrics_detail"]:
        if m["scored"]:
            assert m["data_availability"] == "insufficient_local"
            assert m["compliance_pct"] is None
            assert m["deficit"] is None
            assert m["availability_reason"] == LOCAL_GATE_REASON
            assert m["required"] is not None and m["required"] >= 1
        else:
            assert m["data_availability"] == "not_available"
            assert m["required"] is None

    # DKI-like input: pop = 50,000 and sekolah_dasar = 10 -> unchanged normal scoring
    dki_like = build_district_metrics_and_scores(
        pop=50000,
        fac_counts={
            "taman_kanak_kanak": 20,
            "sekolah_dasar": 10,
            "sekolah_menengah_pertama": 5,
            "sekolah_menengah_atas": 5,
            "puskesmas_kelurahan": 1,
            "puskesmas_kecamatan": 1,
            "pos_damkar": 1,
        },
        standards=standards,
        availability_map=avail_map,
    )
    assert dki_like["local_gated"] is False
    assert dki_like["coverage"]["osm_coverage"]["status"] == "memadai"
    assert dki_like["coverage"]["osm_coverage"]["mapped_sd"] == 10
    assert dki_like["scores_res"]["composite_score"] is not None
    assert dki_like["scores_res"]["pillar_scores"]["education"]["score"] is not None
    assert dki_like["scores_res"]["pillar_scores"]["lifeline_health"]["score"] is not None


def test_api_null_composite_returns_data_tidak_memadai_and_excluded_from_ranking():
    """J1a2 Rule 4: API handles NULL composite cleanly, returns 'Data tidak memadai', and excludes from ranking."""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from backend.app.main import app

    cov_memadai = {"osm_coverage": {"status": "memadai", "mapped_sd": 5, "required_sd": 10, "rule": "rule"}}
    cov_gated = {"osm_coverage": {"status": "tidak_memadai", "mapped_sd": 0, "required_sd": 10, "rule": "rule"}}
    rows = [
        {
            "kemendagri_code": "31.71.01",
            "bps_code": "3171010",
            "name": "Scored A",
            "city_name": "Jakarta Selatan",
            "population": 16000,
            "area_km2": 5.0,
            "density_per_km2": 3200.0,
            "health_score": 50.0,
            "education_score": 60.0,
            "livability_score": None,
            "mobility_score": None,
            "composite_livability_score": 54.55,
            "composite_note": "Note A",
            "metrics_payload": [],
            "coverage": cov_memadai,
        },
        {
            "kemendagri_code": "31.71.02",
            "bps_code": "3171020",
            "name": "Gated B",
            "city_name": "Jakarta Selatan",
            "population": 16000,
            "area_km2": 5.0,
            "density_per_km2": 3200.0,
            "health_score": None,
            "education_score": None,
            "livability_score": None,
            "mobility_score": None,
            "composite_livability_score": None,
            "composite_note": "Data tidak memadai",
            "metrics_payload": [
                {
                    "facility_type": "sekolah_dasar",
                    "pillar": "education",
                    "existing": 0,
                    "required": 10,
                    "compliance_pct": None,
                    "deficit": None,
                    "data_availability": "insufficient_local",
                    "availability_reason": LOCAL_GATE_REASON,
                    "scored": True,
                }
            ],
            "coverage": cov_gated,
        },
    ]

    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = rows
    mock_cur.fetchone.return_value = {
        **rows[1],
        "id": "00000000-0000-0000-0000-000000000002",
        "boundary_geojson": None,
    }

    @contextmanager
    def mock_cursor_ctx():
        yield mock_cur

    client = TestClient(app)
    with patch("backend.app.api.routers.districts.get_redis_client", return_value=None), \
         patch("backend.app.api.routers.districts.get_db_cursor", side_effect=mock_cursor_ctx), \
         patch("backend.app.api.routers.districts.resolve_district_record", return_value=({"id": "00000000-0000-0000-0000-000000000002"}, None)):
        res_list = client.get("/api/v1/districts")
        assert res_list.status_code == 200
        body = res_list.json()
        assert body["average_composite_score"] == 54.55
        assert body["scored_districts_count"] == 1
        assert body["insufficient_data_districts_count"] == 1

        by_code = {d["kemendagri_code"]: d for d in body["districts"]}
        assert by_code["31.71.01"]["rank"] == 1
        assert by_code["31.71.01"]["score_status"] == "Tersedia"
        assert by_code["31.71.02"]["composite_livability_score"] is None
        assert by_code["31.71.02"]["score_status"] == "Data tidak memadai"
        assert by_code["31.71.02"]["rank"] is None
        assert by_code["31.71.02"]["coverage"] == cov_gated

        res_detail = client.get("/api/v1/districts/31.71.02")
        assert res_detail.status_code == 200
        detail = res_detail.json()
        assert detail["composite_livability_score"] is None
        assert detail["score_status"] == "Data tidak memadai"
        assert detail["coverage"] == cov_gated
        assert detail["pillar_scores"]["education"]["score"] is None
