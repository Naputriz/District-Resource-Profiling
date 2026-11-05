"""
Unit & Deterministic Validation Tests for What-If Simulation Engine.
Verifies Rule #1 (Deterministic Math), Rule #2 (Sandbox Isolation), and Rule #3 (Zero unreferenced claims).
"""

import json
import math
import pytest
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
        site_area_m2=25000.0 # 2.5 Hectares
    )

    impact = WhatIfSimulationEngine.simulate_superblock_development(
        req=req,
        baseline_population=100000,
        district_name="Tebet",
        existing_facility_counts={"puskesmas_kelurahan": 3, "sekolah_dasar": 50},
        regulatory_standards=standards
    )

    # 4000 units * 3.0 occupants = 12,000 new residents
    assert impact.estimated_new_occupants == 12000
    assert impact.new_total_population == 112000

    # Perda RDTR Pasal 64: 20% of 25,000 m2 = 5,000 m2
    assert impact.mandated_public_rth_m2 == 5000.0

    # Perda RDTR Pasal 64: Zero delta Q (150mm rain over 50% KDB)
    # 25,000 * 0.50 = 12,500 m2 impervious * 0.150m = 1,875 m3
    assert impact.mandated_water_retention_m3 == 1875.0

    # School children ~25% of 12,000 = 3,000 children
    assert impact.school_children_estimate == 3000
    # Unified delta formula: ceil(112000 / 1600) - ceil(100000 / 1600) = 70 - 63 = 7
    expected_sd_delta = math.ceil(112000 / 1600) - math.ceil(100000 / 1600)
    assert impact.additional_primary_schools_needed == expected_sd_delta

    # Developer obligations / mitigation recommendations
    obligations = impact.developer_legal_obligations
    assert len(obligations) >= 3
    assert any("SNI 03-1733-2004" in o.regulation_code for o in obligations)

    # Unit test: superblock output contains no "wajib" and no "Pasal 64" as a citation
    dump_str = json.dumps(impact.model_dump())
    assert "wajib" not in dump_str.lower()
    assert "pasal 64" not in dump_str.lower()
    for o in obligations:
        assert "wajib" not in o.obligation_text.lower()
        assert "pasal 64" not in o.article_reference.lower()

def test_cilandak_puskesmas_delta_zero():
    """
    Validates Cilandak edge case from README.md §10:
    P_old = 210,870, +13,500 new residents -> P_new = 224,370.
    puskesmas_kelurahan threshold = 30,000.
    P_old required: ceil(210870 / 30000) = 8
    P_new required: ceil(224370 / 30000) = 8
    Delta must be 8 - 8 = 0 (NOT +1).
    """
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
    """
    Validates calculation model from README.md §8:
    120,000 people, 3 existing units, threshold 30,000:
    required = ceil(120000 / 30000) = 4
    deficit = 3 - 4 = -1
    score = min(100, 3 / 4 * 100) = 75.0
    """
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
    """
    Validates superblock response compliance with README.md §4, §8, §10:
    - Contains no old permit verdict strings
    - Contains impact_level in ['Rendah', 'Sedang', 'Tinggi']
    - Contains fixed disclaimer: 'Bukan keputusan perizinan. Untuk bahan diskusi perencanaan.'
    - Contains assumptions field with occupants_per_unit, school_age_ratio, kdb_ratio
    """
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
    # Verdict strings checks
    for forbidden in ["DITO" + "LAK", "DISET" + "UJUI"]:
        assert forbidden not in impact.compliance_verdict
    assert impact.impact_level in ["Rendah", "Sedang", "Tinggi"]

    # Disclaimer check
    expected_disclaimer = "Bukan keputusan perizinan. Untuk bahan diskusi perencanaan."
    assert expected_disclaimer in impact.compliance_verdict
    assert expected_disclaimer in impact.disclaimer

    # Assumptions check
    dump = impact.model_dump()
    assert "assumptions" in dump
    assert impact.assumptions["occupants_per_unit"] == 3.0
    assert impact.assumptions["school_age_ratio"] == 0.25
    assert impact.assumptions["kdb_ratio"] == 0.50
    assert impact.assumptions["public_rth_ratio"] == 0.20
    assert impact.assumptions["rth_article_reference"] == "Asumsi RTH 20% (belum diverifikasi ke Perda 31/2022)"
    assert "Parameter asumsi (belum diverifikasi ke Perda 31/2022): RTH 20%, retensi 150 mm/hari, KDB 50%" in impact.assumptions["parameter_note"]
    assert "impact_rule" in dump
    assert "new_deficit_units" in dump

def test_simulation_impact_level_boundaries():
    """
    Validates boundary conditions for simulation impact levels:
    - Rendah: delta > -1.0 AND 0 new deficit units
    - Tinggi: delta <= -5.0 OR >= 3 new deficit units
    - Sedang: all other cases
    """
    standards = [
        {"facility_type": "puskesmas_kelurahan", "pillar": "lifeline_health", "population_threshold": 30000, "legal_reference": "SNI 03-1733-2004"},
        {"facility_type": "pos_damkar", "pillar": "lifeline_health", "population_threshold": 30000, "legal_reference": "Permendagri 114/2018"}
    ]

    # Boundary 1: Rendah (pop_shock = 0, delta = 0.0, new_def = 0)
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
    assert "Rendah: delta > -1.0" in res_rendah.impact_rule

    # Boundary 2: Sedang (delta between -1.0 and -5.0, new deficit units < 3)
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

    # Boundary 3: Tinggi via >= 3 new deficit units
    # Add a 3rd standard so +30,000 causes 3 new deficit units
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

    # Boundary 4: Tinggi via delta <= -5.0
    # Large shock with low existing facilities
    res_tinggi_delta = WhatIfSimulationEngine.compute_scenario_delta(
        district_code="31.71.09",
        district_name="Tebet",
        baseline_population=30000,
        existing_facility_counts={"puskesmas_kelurahan": 1, "pos_damkar": 1},
        regulatory_standards=standards,
        pop_shock_count=90000 # 30,000 -> 120,000
    )
    assert res_tinggi_delta.score_delta <= -5.0 or res_tinggi_delta.new_deficit_units >= 3
    assert res_tinggi_delta.impact_level == "Tinggi"

if __name__ == "__main__":
    test_simulation_population_shock()
    test_staged_amenity_offset()
    test_superblock_development_obligations()
    test_cilandak_puskesmas_delta_zero()
    test_standard_compliance_score_and_deficit()
    test_superblock_verdict_honest_impact_and_disclaimer()
    test_simulation_impact_level_boundaries()
    print("ALL SIMULATION ENGINE UNIT TESTS PASSED DETERMINISTICALLY!")
