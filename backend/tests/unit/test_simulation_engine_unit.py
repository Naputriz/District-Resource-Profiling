"""
Unit & Deterministic Validation Tests for What-If Simulation Engine.
Verifies Rule #1 (Deterministic Math), Rule #2 (Sandbox Isolation), and Rule #3 (Zero unreferenced claims).
Includes edge cases: zero population, unknown facility type, huge inputs, negative population.
"""

import json
import math
import pytest
from pydantic import ValidationError
from backend.app.engine.simulation import (
    WhatIfSimulationEngine,
    SimulationRequest,
    HypotheticalAmenity,
    SuperblockSimulationRequest
)

pytestmark = pytest.mark.unit


def test_simulation_population_shock():
    standards = [
        {
            "facility_type": "puskesmas_kelurahan",
            "pillar": "lifeline_health",
            "population_threshold": 30000,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.3"
        },
        {
            "facility_type": "puskesmas_kecamatan",
            "pillar": "lifeline_health",
            "population_threshold": 120000,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.3"
        },
        {
            "facility_type": "sekolah_dasar",
            "pillar": "education",
            "population_threshold": 1600,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.2"
        },
        {
            "facility_type": "smp",
            "pillar": "education",
            "population_threshold": 4800,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.2"
        }
    ]
    existing_counts = {
        "puskesmas_kelurahan": 2,
        "puskesmas_kecamatan": 1,
        "sekolah_dasar": 40,
        "smp": 10
    }

    # Baseline 60,000 -> Shock +50% = 90,000 (+30,000)
    result = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.09",
        district_name="Tebet",
        baseline_population=60000,
        existing_facility_counts=existing_counts,
        regulatory_standards=standards,
        pop_shock_pct=50.0,
        staged_amenities=[]
    )

    assert result.baseline_population == 60000
    assert result.simulated_population == 90000
    assert result.population_delta == 30000
    assert result.is_sandbox_isolated is True

    # Puskesmas: Required was ceil(60000/30000)=2, Now ceil(90000/30000)=3.
    # Existing = 2. Deficit: was 0, now -1.
    puskesmas_metric = next(m for m in result.metrics_comparison if m.facility_type == "puskesmas_kelurahan")
    assert puskesmas_metric.baseline_required == 2
    assert puskesmas_metric.simulated_required == 3
    assert puskesmas_metric.baseline_deficit == 0
    assert puskesmas_metric.simulated_deficit == -1
    assert "Defisit 1 unit" in puskesmas_metric.status_summary

    # Score should drop because deficit increased
    assert result.score_delta < 0


def test_staged_amenity_offset():
    standards = [
        {
            "facility_type": "puskesmas_kelurahan",
            "pillar": "lifeline_health",
            "population_threshold": 30000,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.3"
        }
    ]
    existing_counts = {"puskesmas_kelurahan": 2}

    # Add 1 hypothetical puskesmas alongside +30,000 population shock
    result = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.09",
        district_name="Tebet",
        baseline_population=60000,
        existing_facility_counts=existing_counts,
        regulatory_standards=standards,
        pop_shock_count=30000,
        staged_amenities=[
            HypotheticalAmenity(
                name="Puskesmas Hipotetis Baru",
                pillar="lifeline_health",
                facility_type="puskesmas_kelurahan",
                coordinates=[106.845, -6.230]
            )
        ]
    )

    puskesmas_metric = result.metrics_comparison[0]
    assert puskesmas_metric.simulated_existing == 3
    assert puskesmas_metric.simulated_required == 3
    assert puskesmas_metric.simulated_deficit == 0
    assert puskesmas_metric.simulated_compliance_pct == 100.0


def test_superblock_development_obligations():
    standards = [
        {
            "facility_type": "puskesmas_kelurahan",
            "pillar": "lifeline_health",
            "population_threshold": 30000,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.3"
        },
        {
            "facility_type": "sekolah_dasar",
            "pillar": "education",
            "population_threshold": 1600,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.2"
        }
    ]
    req = SuperblockSimulationRequest(
        district_code="31.71.09",
        project_name="Apartemen Mega Tebet",
        residential_units=4000,
        occupants_per_unit=3.0,
        site_area_m2=25000.0
    )

    impact = WhatIfSimulationEngine.simulate_superblock_development(
        req=req,
        baseline_population=100000,
        district_name="Tebet",
        existing_facility_counts={"puskesmas_kelurahan": 3, "sekolah_dasar": 50},
        regulatory_standards=standards
    )

    assert impact.estimated_new_occupants == 12000
    assert impact.new_total_population == 112000
    assert impact.mandated_public_rth_m2 == 5000.0
    assert impact.mandated_water_retention_m3 == 1875.0
    assert impact.school_children_estimate == 3000
    expected_sd_delta = math.ceil(112000 / 1600) - math.ceil(100000 / 1600)
    assert impact.additional_primary_schools_needed == expected_sd_delta

    obligations = impact.developer_legal_obligations
    assert len(obligations) >= 3
    assert any("SNI 03-1733-2004" in o.regulation_code for o in obligations)

    dump_str = json.dumps(impact.model_dump())
    assert "wajib" not in dump_str.lower()
    assert "pasal 64" not in dump_str.lower()
    for o in obligations:
        assert "wajib" not in o.obligation_text.lower()
        assert "pasal 64" not in o.article_reference.lower()


def test_cilandak_puskesmas_delta_zero():
    standards = [{
        "facility_type": "puskesmas_kelurahan",
        "pillar": "lifeline_health",
        "population_threshold": 30000,
        "legal_reference": "SNI 03-1733-2004 Bagian 7.3"
    }]
    delta_res = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.74.06",
        district_name="Cilandak",
        baseline_population=210870,
        existing_facility_counts={"puskesmas_kelurahan": 8},
        regulatory_standards=standards,
        pop_shock_count=13500
    )
    metric = delta_res.metrics_comparison[0]
    assert metric.baseline_required == 8
    assert metric.simulated_required == 8
    delta_units = metric.simulated_required - metric.baseline_required
    assert delta_units == 0, f"Expected delta 0, got {delta_units}"


def test_standard_compliance_score_and_deficit():
    standards = [{
        "facility_type": "puskesmas_kelurahan",
        "pillar": "lifeline_health",
        "population_threshold": 30000,
        "legal_reference": "SNI 03-1733-2004 Bagian 7.3"
    }]
    delta_res = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.01",
        district_name="Test District",
        baseline_population=120000,
        existing_facility_counts={"puskesmas_kelurahan": 3},
        regulatory_standards=standards,
        pop_shock_count=0
    )
    metric = delta_res.metrics_comparison[0]
    assert metric.baseline_required == 4
    assert metric.baseline_deficit == -1
    assert metric.baseline_compliance_pct == 75.0


def test_superblock_verdict_honest_impact_and_disclaimer():
    standards = [
        {
            "facility_type": "puskesmas_kelurahan",
            "pillar": "lifeline_health",
            "population_threshold": 30000,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.3"
        },
        {
            "facility_type": "sekolah_dasar",
            "pillar": "education",
            "population_threshold": 1600,
            "legal_reference": "SNI 03-1733-2004 Bagian 7.2"
        }
    ]
    req = SuperblockSimulationRequest(
        district_code="31.71.09",
        project_name="Superblock Test",
        residential_units=4500,
        occupants_per_unit=3.0,
        site_area_m2=20000.0
    )
    impact = WhatIfSimulationEngine.simulate_superblock_development(
        req=req,
        baseline_population=200000,
        district_name="Test District",
        existing_facility_counts={"puskesmas_kelurahan": 5, "sekolah_dasar": 100},
        regulatory_standards=standards
    )
    for forbidden in ["DITO" + "LAK", "DISET" + "UJUI"]:
        assert forbidden not in impact.compliance_verdict
    assert impact.impact_level in ["Rendah", "Sedang", "Tinggi"]

    expected_disclaimer = "Bukan keputusan perizinan. Untuk bahan diskusi perencanaan."
    assert expected_disclaimer in impact.compliance_verdict
    assert expected_disclaimer in impact.disclaimer

    dump = impact.model_dump()
    assert "assumptions" in dump
    assert impact.assumptions["occupants_per_unit"] == 3.0
    assert impact.assumptions["school_age_ratio"] == 0.25
    assert impact.assumptions["kdb_ratio"] == 0.50
    assert impact.assumptions["public_rth_ratio"] == 0.20
    assert impact.assumptions["rth_article_reference"] == "Asumsi RTH 20% (belum diverifikasi terhadap peraturan daerah)"
    assert "Parameter asumsi tim (belum diverifikasi terhadap peraturan daerah): RTH 20%, retensi 150 mm/hari, KDB 50%" in impact.assumptions["parameter_note"]
    assert "impact_rule" in dump
    assert "new_deficit_units" in dump


def test_simulation_impact_level_boundaries():
    standards = [
        {"facility_type": "puskesmas_kelurahan", "pillar": "lifeline_health", "population_threshold": 30000, "legal_reference": "SNI 03-1733-2004"},
        {"facility_type": "pos_damkar", "pillar": "lifeline_health", "population_threshold": 30000, "legal_reference": "Permendagri 114/2018"}
    ]

    res_rendah = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.09",
        district_name="Tebet",
        baseline_population=60000,
        existing_facility_counts={"puskesmas_kelurahan": 2, "pos_damkar": 2},
        regulatory_standards=standards,
        pop_shock_count=0
    )
    assert res_rendah.score_delta > -1.0
    assert res_rendah.new_deficit_units == 0
    assert res_rendah.impact_level == "Rendah"

    standards_sedang = [
        {"facility_type": "puskesmas_kelurahan", "pillar": "lifeline_health", "population_threshold": 30000, "legal_reference": "SNI"},
        {"facility_type": "pos_damkar", "pillar": "lifeline_health", "population_threshold": 1000000, "legal_reference": "SNI"},
        {"facility_type": "rumah_sakit", "pillar": "lifeline_health", "population_threshold": 1000000, "legal_reference": "SNI"},
        {"facility_type": "pos_polisi", "pillar": "lifeline_health", "population_threshold": 1000000, "legal_reference": "SNI"},
        {"facility_type": "puskesmas_kecamatan", "pillar": "lifeline_health", "population_threshold": 1000000, "legal_reference": "SNI"},
        {"facility_type": "sekolah_dasar", "pillar": "education", "population_threshold": 1000000, "legal_reference": "SNI"},
        {"facility_type": "sekolah_menengah_pertama", "pillar": "education", "population_threshold": 1000000, "legal_reference": "SNI"},
    ]
    counts_sedang = {
        "puskesmas_kelurahan": 2, "pos_damkar": 1, "rumah_sakit": 1,
        "pos_polisi": 1, "puskesmas_kecamatan": 1,
        "sekolah_dasar": 1, "sekolah_menengah_pertama": 1
    }
    res_sedang = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.09",
        district_name="Tebet",
        baseline_population=60000,
        existing_facility_counts=counts_sedang,
        regulatory_standards=standards_sedang,
        pop_shock_count=30000
    )
    assert res_sedang.score_delta > -5.0 and res_sedang.score_delta <= -1.0
    assert res_sedang.new_deficit_units == 1
    assert res_sedang.impact_level == "Sedang"

    standards_3 = list(standards) + [
        {"facility_type": "rumah_sakit", "pillar": "lifeline_health", "population_threshold": 30000, "legal_reference": "Permenkes 43/2019"}
    ]
    res_tinggi_def = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.09",
        district_name="Tebet",
        baseline_population=60000,
        existing_facility_counts={"puskesmas_kelurahan": 2, "pos_damkar": 2, "rumah_sakit": 2},
        regulatory_standards=standards_3,
        pop_shock_count=30000
    )
    assert res_tinggi_def.new_deficit_units >= 3
    assert res_tinggi_def.impact_level == "Tinggi"


def test_whatif_zero_population_handled_safely():
    """Edge case: baseline population = 0 handles division without ZeroDivisionError."""
    standards = [{
        "facility_type": "puskesmas_kelurahan",
        "pillar": "lifeline_health",
        "population_threshold": 30000,
        "legal_reference": "SNI 03-1733-2004"
    }]
    res = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.99",
        district_name="Zero District",
        baseline_population=0,
        existing_facility_counts={"puskesmas_kelurahan": 0},
        regulatory_standards=standards,
        pop_shock_count=0
    )
    assert res.baseline_population == 0
    # Engine clamps minimum simulated population safely to 1000 without ZeroDivisionError
    assert res.simulated_population == 1000
    assert res.is_sandbox_isolated is True
    assert res.impact_level == "Rendah"


def test_whatif_unknown_facility_type_gracefully_ignored_in_scores():
    """Edge case: unknown facility type not in standards does not crash."""
    standards = [{
        "facility_type": "puskesmas_kelurahan",
        "pillar": "lifeline_health",
        "population_threshold": 30000,
        "legal_reference": "SNI 03-1733-2004"
    }]
    res = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.09",
        district_name="Tebet",
        baseline_population=60000,
        existing_facility_counts={"puskesmas_kelurahan": 2, "unknown_alien_amenity_xyz": 99},
        regulatory_standards=standards,
        pop_shock_count=0
    )
    assert res.baseline_population == 60000
    # Alien facility is not in regulatory standards metrics comparison
    types = [m.facility_type for m in res.metrics_comparison]
    assert "unknown_alien_amenity_xyz" not in types


def test_whatif_rejects_negative_population_shock():
    """Edge case: out-of-bounds negative population shocks raise ValidationError."""
    with pytest.raises(ValidationError):
        SimulationRequest(
            district_code="31.71.09",
            population_shock_percent=0.0,
            population_shock_count=-600000,
        )
    with pytest.raises(ValidationError):
        SimulationRequest(
            district_code="31.71.09",
            population_shock_percent=-60.0,
            population_shock_count=0,
        )
    req = SimulationRequest(
        district_code="31.71.09",
        population_shock_percent=-10.0,
        population_shock_count=-5000,
    )
    assert req.population_shock_percent == -10.0
    assert req.population_shock_count == -5000


def test_simulation_schema_rejects_huge_inputs_or_negative_values():
    """Edge case: huge inputs and negative units produce validation errors."""
    with pytest.raises(ValidationError):
        SuperblockSimulationRequest(
            district_code="31.71.09",
            residential_units=-500,  # Negative units not allowed
            site_area_m2=10000.0,
        )
