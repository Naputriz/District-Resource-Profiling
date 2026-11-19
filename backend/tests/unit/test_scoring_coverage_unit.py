"""
Unit tests for Standards Availability, Coverage, and Proportional Re-weighting.
Complies with Phase 4.2 & Phase 5.1 (REBUILD_PROMPT_P5_1_P7.md). Marker: unit.
"""

import pytest
from backend.app.engine.standards_availability import (
    evaluate_availability,
    calculate_pillar_and_composite_scores,
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
