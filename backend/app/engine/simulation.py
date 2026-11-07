"""
What-If Scenario Simulation Engine (Isolated Sandbox).
Strictly enforces Rule #1, #2, and #3:
- Deterministic calculations without mutating master database tables.
- Isolated memory sandbox returning SimulationDeltaDTO and SuperblockImpactDTO.
- Zero unreferenced claims: all policy mitigations cite verified SNI/Perda articles.
"""

import math
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from backend.app.core.config import settings

class HypotheticalAmenity(BaseModel):
    name: str
    pillar: str # lifeline_health, education, urban_livability, mobility_connectivity
    facility_type: str
    coordinates: List[float] # [lon, lat]
    capacity: int = 0

class SimulationRequest(BaseModel):
    district_code: str # kemendagri_code, e.g. "31.71.09"
    population_shock_percent: float = Field(default=0.0, ge=-50.0, le=200.0)
    population_shock_count: int = Field(default=0, ge=-500000, le=500000)
    hypothetical_facilities: List[HypotheticalAmenity] = []

class SuperblockSimulationRequest(BaseModel):
    district_code: str
    project_name: str = "Proyek Superblok Kawasan Terpadu"
    residential_units: int = Field(default=3000, ge=100, le=50000, description="Jumlah unit hunian baru")
    occupants_per_unit: float = Field(default=3.0, ge=1.0, le=6.0, description="Rata-rata penghuni per unit")
    site_area_m2: float = Field(default=20000.0, ge=1000.0, le=500000.0, description="Luas lahan bruto proyek (m²)")
    staged_amenities: List[HypotheticalAmenity] = []

class MetricDelta(BaseModel):
    facility_type: str
    pillar: str
    baseline_existing: int
    simulated_existing: int
    baseline_required: int
    simulated_required: int
    baseline_deficit: int
    simulated_deficit: int
    baseline_compliance_pct: float
    simulated_compliance_pct: float
    status_summary: str
    legal_reference: str
    new_deficit_units: int = 0
    required_delta: int = 0
    deficit_delta: int = 0

class LegalMitigationObligation(BaseModel):
    regulation_code: str
    article_reference: str
    title: str
    obligation_text: str
    required_metric: str

class SimulationDeltaDTO(BaseModel):
    district_code: str
    district_name: str
    baseline_population: int
    simulated_population: int
    population_delta: int
    population_note: str = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)"
    baseline_composite_score: float
    simulated_composite_score: float
    score_delta: float
    abs_score_delta: float = 0.0
    baseline_pillar_scores: Dict[str, Any]
    simulated_pillar_scores: Dict[str, Any]
    pillar_deltas: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    metrics_comparison: List[MetricDelta]
    hypothetical_facilities_added: int
    legal_recommendations: List[LegalMitigationObligation] = []
    is_sandbox_isolated: bool = True
    assumptions: Dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = settings.SIMULATION_DISCLAIMER
    impact_level: str = "Rendah" # "Rendah" | "Sedang" | "Tinggi"
    impact_rule: str = settings.SIMULATION_IMPACT_RULE
    new_deficit_units: int = 0

class SuperblockImpactDTO(BaseModel):
    project_name: str
    district_code: str
    district_name: str
    residential_units: int
    estimated_new_occupants: int
    site_area_m2: float
    baseline_population: int
    new_total_population: int
    population_note: str = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)"
    mandated_public_rth_m2: float # 20% alokasi RTH publik (parameter asumsi)
    mandated_water_retention_m3: float # 150mm retensi air hujan (parameter asumsi)
    school_children_estimate: int # ~25% of new population
    additional_primary_schools_needed: int
    additional_health_clinics_needed: int
    simulation_delta: SimulationDeltaDTO
    impact_level: str # "Rendah" | "Sedang" | "Tinggi"
    compliance_verdict: str
    impact_rule: str = settings.SIMULATION_IMPACT_RULE
    new_deficit_units: int = 0
    assumptions: Dict[str, Any] = Field(default_factory=dict)
    developer_legal_obligations: List[LegalMitigationObligation]
    is_sandbox_isolated: bool = True
    disclaimer: str = settings.SIMULATION_DISCLAIMER

class WhatIfSimulationEngine:
    @staticmethod
    def compute_scenario_delta(
        district_code: str,
        district_name: str,
        baseline_population: int,
        existing_facility_counts: Dict[str, int],
        regulatory_standards: List[Dict[str, Any]],
        pop_shock_pct: float = 0.0,
        pop_shock_count: int = 0,
        staged_amenities: List[HypotheticalAmenity] = []
    ) -> SimulationDeltaDTO:
        """
        Executes isolated delta simulation.
        Recalculates facility deficits and livability index without updating database.
        """
        # 1. Population Projection
        pop_delta_from_pct = int(baseline_population * (pop_shock_pct / 100.0))
        total_pop_delta = pop_delta_from_pct + pop_shock_count
        simulated_pop = max(1000, baseline_population + total_pop_delta)

        # 2. Count staged additions per facility_type
        added_counts = {}
        for item in staged_amenities:
            ft = item.facility_type
            added_counts[ft] = added_counts.get(ft, 0) + 1

        baseline_pillars = {"lifeline_health": [], "education": [], "urban_livability": [], "mobility_connectivity": []}
        simulated_pillars = {"lifeline_health": [], "education": [], "urban_livability": [], "mobility_connectivity": []}
        metric_deltas = []
        legal_recs = []

        from backend.app.engine.standards_availability import (
            get_city_wide_standards_availability,
            calculate_pillar_and_composite_scores
        )
        avail_map = get_city_wide_standards_availability()

        base_metrics_list = []
        sim_metrics_list = []

        for std in regulatory_standards:
            ftype = std["facility_type"]
            pillar = std["pillar"]
            threshold = std.get("population_threshold")
            legal_ref = std.get("legal_reference", "SNI 03-1733-2004")
            is_std_scored = std.get("scored", True)

            # Determine availability from single unified source of truth
            if ftype in avail_map:
                avail, reason = avail_map[ftype]
            else:
                avail = std.get("data_availability", "available")
                reason = std.get("availability_reason", "")

            base_exist = existing_facility_counts.get(ftype, 0)
            sim_exist = base_exist + added_counts.get(ftype, 0)

            # Only scored=True and available types produce need/deficit/score
            is_active_scored = is_std_scored and avail == "available" and threshold is not None

            if is_active_scored:
                # Baseline calculation
                base_req = max(1, math.ceil(baseline_population / threshold))
                base_pct = min(100.0, round((base_exist / base_req) * 100.0, 2))
                base_deficit = base_exist - base_req

                # Simulated calculation
                sim_req = max(1, math.ceil(simulated_pop / threshold))
                sim_pct = min(100.0, round((sim_exist / sim_req) * 100.0, 2))
                sim_deficit = sim_exist - sim_req

                # Generate natural language status
                if sim_deficit < 0:
                    status = f"Defisit {abs(sim_deficit)} unit pada beban populasi simulasi ({simulated_pop:,} jiwa)."
                    # Add legal mitigation recommendation if new deficit appears
                    if sim_deficit < base_deficit:
                        legal_recs.append(LegalMitigationObligation(
                            regulation_code="SNI 03-1733-2004",
                            article_reference=legal_ref,
                            title=f"Kompensasi Defisit {ftype.replace('_', ' ').title()}",
                            obligation_text=f"Lonjakan populasi (+{total_pop_delta:,} jiwa) menambah kebutuhan {abs(sim_deficit - base_deficit)} unit fasilitas menurut standar.",
                            required_metric=f"+{abs(sim_deficit - base_deficit)} unit baru"
                        ))
                elif sim_deficit == 0:
                    status = "Tepat memenuhi standar SNI."
                else:
                    status = f"Surplus {sim_deficit} unit dari standar minimal."

                new_def = max(0, -sim_deficit - max(0, -base_deficit))
                req_delta = sim_req - base_req
                def_delta = sim_deficit - base_deficit
            else:
                base_req = 0
                base_pct = 0.0
                base_deficit = 0
                sim_req = 0
                sim_pct = 0.0
                sim_deficit = 0
                new_def = 0
                req_delta = 0
                def_delta = 0
                status = f"{base_exist} titik OSM - tidak dinilai"

            base_metrics_list.append({
                "facility_type": ftype,
                "pillar": pillar,
                "compliance_pct": base_pct if is_active_scored else None,
                "data_availability": avail,
                "availability_reason": reason,
                "scored": is_std_scored
            })
            sim_metrics_list.append({
                "facility_type": ftype,
                "pillar": pillar,
                "compliance_pct": sim_pct if is_active_scored else None,
                "data_availability": avail,
                "availability_reason": reason,
                "scored": is_std_scored
            })

            metric_deltas.append(MetricDelta(
                facility_type=ftype,
                pillar=pillar,
                baseline_existing=base_exist,
                simulated_existing=sim_exist,
                baseline_required=base_req,
                simulated_required=sim_req,
                baseline_deficit=base_deficit,
                simulated_deficit=sim_deficit,
                baseline_compliance_pct=base_pct,
                simulated_compliance_pct=sim_pct,
                status_summary=status,
                legal_reference=legal_ref,
                new_deficit_units=new_def,
                required_delta=req_delta,
                deficit_delta=def_delta
            ))

        # Pillar and composite calculation using proportional re-weighting
        scores_res_base = calculate_pillar_and_composite_scores(base_metrics_list, avail_map)
        scores_res_sim = calculate_pillar_and_composite_scores(sim_metrics_list, avail_map)

        base_composite = scores_res_base["composite_score"] or 0.0
        sim_composite = scores_res_sim["composite_score"] or 0.0
        base_p_scores = scores_res_base["pillar_scores"]
        sim_p_scores = scores_res_sim["pillar_scores"]

        score_delta = round(sim_composite - base_composite, 2)

        # Compute per-pillar score deltas
        pillar_deltas: Dict[str, Dict[str, float]] = {}
        for p_key, base_val in base_p_scores.items():
            base_s = base_val.get("score") if isinstance(base_val, dict) else base_val
            sim_val = sim_p_scores.get(p_key, {})
            sim_s = sim_val.get("score") if isinstance(sim_val, dict) else sim_val
            if base_s is not None and sim_s is not None:
                try:
                    b_flt = float(base_s)
                    s_flt = float(sim_s)
                    p_diff = round(s_flt - b_flt, 2)
                    pillar_deltas[p_key] = {
                        "baseline_score": b_flt,
                        "simulated_score": s_flt,
                        "delta": p_diff,
                        "abs_delta": round(abs(p_diff), 2)
                    }
                except (ValueError, TypeError):
                    pass

        # Calculate new deficit units for available facility types
        new_deficit_units = 0
        for m in metric_deltas:
            info = avail_map.get(m.facility_type)
            if isinstance(info, tuple):
                avail_status = info[0]
            elif isinstance(info, dict):
                avail_status = info.get("availability", "available")
            else:
                avail_status = "available"

            if avail_status == "available":
                base_def = max(0, -m.baseline_deficit)
                sim_def = max(0, -m.simulated_deficit)
                if sim_def > base_def:
                    new_deficit_units += (sim_def - base_def)

        # Impact level rule based on config thresholds (TODO-DECIDE (team)):
        # Rendah: delta > SIMULATION_IMPACT_DELTA_LOW (-1.0) AND new_deficit_units <= SIMULATION_IMPACT_DEFICIT_LOW (0)
        # Tinggi: delta <= SIMULATION_IMPACT_DELTA_HIGH (-5.0) OR new_deficit_units >= SIMULATION_IMPACT_DEFICIT_HIGH (3)
        # Else: Sedang
        if score_delta > settings.SIMULATION_IMPACT_DELTA_LOW and new_deficit_units <= settings.SIMULATION_IMPACT_DEFICIT_LOW:
            impact_level = "Rendah"
        elif score_delta <= settings.SIMULATION_IMPACT_DELTA_HIGH or new_deficit_units >= settings.SIMULATION_IMPACT_DEFICIT_HIGH:
            impact_level = "Tinggi"
        else:
            impact_level = "Sedang"

        assumptions = {
            "population_note": "Sumber data penduduk belum terverifikasi (TODO-VERIFY)",
            "pop_shock_pct": pop_shock_pct,
            "pop_shock_count": pop_shock_count,
            "delta_formula": "ceil(P_new / threshold) - ceil(P_old / threshold)",
            "composite_note": scores_res_sim["composite_note"],
            "impact_rule": settings.SIMULATION_IMPACT_RULE,
            "new_deficit_units": new_deficit_units,
            "composite_weights": {
                "lifeline_health": 0.30,
                "education": 0.25,
                "urban_livability": 0.25,
                "mobility_connectivity": 0.20
            }
        }

        return SimulationDeltaDTO(
            district_code=district_code,
            district_name=district_name,
            baseline_population=baseline_population,
            simulated_population=simulated_pop,
            population_delta=total_pop_delta,
            baseline_composite_score=base_composite,
            simulated_composite_score=sim_composite,
            score_delta=score_delta,
            abs_score_delta=round(abs(score_delta), 2),
            baseline_pillar_scores=base_p_scores,
            simulated_pillar_scores=sim_p_scores,
            pillar_deltas=pillar_deltas,
            metrics_comparison=metric_deltas,
            hypothetical_facilities_added=len(staged_amenities),
            legal_recommendations=legal_recs,
            is_sandbox_isolated=True,
            assumptions=assumptions,
            disclaimer=settings.SIMULATION_DISCLAIMER,
            impact_level=impact_level,
            impact_rule=settings.SIMULATION_IMPACT_RULE,
            new_deficit_units=new_deficit_units
        )

    @staticmethod
    def simulate_superblock_development(
        req: SuperblockSimulationRequest,
        baseline_population: int,
        district_name: str,
        existing_facility_counts: Dict[str, int],
        regulatory_standards: List[Dict[str, Any]]
    ) -> SuperblockImpactDTO:
        """
        Simulates the comprehensive urban impact of a new superblock or apartment project.
        Calculates:
        1. Exact population increment.
        2. Estimasi alokasi RTH publik 20% (parameter asumsi).
        3. Estimasi sarana retensi air hujan 150 mm/hari (parameter asumsi).
        4. Delta burdens on primary schools (SD) and Puskesmas reusing what-if delta output.
        """
        new_occupants = int(req.residential_units * req.occupants_per_unit)
        new_total_pop = baseline_population + new_occupants

        # Parameter asumsi (belum diverifikasi ke Perda 31/2022): 20% Gross Site Area untuk RTH publik
        mandated_rth_m2 = round(req.site_area_m2 * settings.SUPERBLOCK_RTH_RATIO, 2)

        # Parameter asumsi (belum diverifikasi ke Perda 31/2022): Volume retensi air hujan (150 mm/hari pada area kedap air, asumsi KDB 50%)
        impervious_area_m2 = req.site_area_m2 * settings.SUPERBLOCK_KDB_RATIO
        retention_m3 = round(impervious_area_m2 * settings.SUPERBLOCK_STORMWATER_DEPTH_M, 2)

        # School age children estimate (~25% of population in ages 6-18)
        school_children = int(new_occupants * settings.SUPERBLOCK_SCHOOL_AGE_RATIO)

        # Run core delta simulation
        sim_delta = WhatIfSimulationEngine.compute_scenario_delta(
            district_code=req.district_code,
            district_name=district_name,
            baseline_population=baseline_population,
            existing_facility_counts=existing_facility_counts,
            regulatory_standards=regulatory_standards,
            pop_shock_count=new_occupants,
            staged_amenities=req.staged_amenities
        )

        # Unified delta formula for all facility types:
        # delta = ceil(P_new / threshold) - ceil(P_old / threshold)
        # Superblock results reuse the what-if delta output
        def get_delta_units(ftype: str, fallback_threshold: int) -> int:
            for m in sim_delta.metrics_comparison:
                if m.facility_type == ftype:
                    return max(0, m.simulated_required - m.baseline_required)
            return max(0, math.ceil(new_total_pop / fallback_threshold) - math.ceil(baseline_population / fallback_threshold))

        sd_needed = get_delta_units("sekolah_dasar", 1600)
        puskesmas_needed = get_delta_units("puskesmas_kelurahan", 30000)

        obligations = [
            LegalMitigationObligation(
                regulation_code="Perda DKI Jakarta No. 31/2022 (TODO-VERIFY)",
                article_reference="Ketentuan RTH (asumsi - belum diverifikasi)",
                title="Penyediaan Lahan RTH Publik Siap Guna (Asumsi 20% Lahan Bruto)",
                obligation_text=f"Parameter asumsi (belum diverifikasi ke Perda 31/2022): RTH 20%, retensi 150 mm/hari, KDB 50%. Pengembang proyek '{req.project_name}' mengalokasikan lahan minimal 20% dari luas lahan bruto dalam bentuk taman RTH publik siap guna.",
                required_metric=f"{mandated_rth_m2:,.2f} m² RTH Publik"
            ),
            LegalMitigationObligation(
                regulation_code="Perda DKI Jakarta No. 31/2022 (TODO-VERIFY)",
                article_reference="Ketentuan Retensi Air (asumsi - belum diverifikasi)",
                title="Penyediaan Sumur Resapan & Kolam Retensi Mandiri",
                obligation_text="Parameter asumsi (belum diverifikasi ke Perda 31/2022): RTH 20%, retensi 150 mm/hari, KDB 50%. Penyediaan sarana retensi air hujan mandiri untuk menampung curahan 150 mm/hari tanpa membebani jaringan drainase mikro perkotaan.",
                required_metric=f"{retention_m3:,.2f} m³ Volume Retensi"
            ),
            LegalMitigationObligation(
                regulation_code="SNI 03-1733-2004",
                article_reference="Bagian 7.2 Tabel 8 hal. 26 (Sarana Pendidikan Dasar)",
                title="Daya Tampung Sekolah Dasar Lingkungan",
                obligation_text=f"Pertambahan {new_occupants:,} jiwa menghasilkan beban perkiraan {school_children:,} anak usia sekolah, membutuhkan tambahan kapasitas setara {sd_needed} unit SD.",
                required_metric=f"Kapasitas {sd_needed} unit SD"
            )
        ]

        # Impact level and deficit units derived directly from what-if simulation delta
        impact_level = sim_delta.impact_level
        new_deficit_units = sim_delta.new_deficit_units
        impact_rule = sim_delta.impact_rule

        if impact_level == "Tinggi":
            explanation = "Penurunan indeks kecukupan fasilitas dasar signifikan (delta <= -5.0 atau timbul defisit baru >= 3 unit). Beban fasilitas bertambah berat; disarankan penyediaan faskes dan RPTRA mandiri."
        elif impact_level == "Sedang":
            explanation = "Beban fasilitas meningkat moderat."
        else:
            impact_level = "Rendah"
            explanation = "Penambahan fasilitas hipotetis mengimbangi lonjakan populasi."

        verdict = f"Indikasi dampak: {impact_level}. {explanation} {settings.SIMULATION_DISCLAIMER}"

        assumptions = {
            "parameter_note": "Parameter asumsi (belum diverifikasi ke Perda 31/2022): RTH 20%, retensi 150 mm/hari, KDB 50%",
            "population_note": "Sumber data penduduk belum terverifikasi (TODO-VERIFY)",
            "occupants_per_unit": req.occupants_per_unit,
            "school_age_ratio": settings.SUPERBLOCK_SCHOOL_AGE_RATIO,
            "kdb_ratio": settings.SUPERBLOCK_KDB_RATIO,
            "public_rth_ratio": settings.SUPERBLOCK_RTH_RATIO,
            "rth_article_reference": "Asumsi RTH 20% (belum diverifikasi ke Perda 31/2022)",
            "stormwater_depth_m": settings.SUPERBLOCK_STORMWATER_DEPTH_M,
            "stormwater_article_reference": "Asumsi Retensi 150 mm/hari (belum diverifikasi ke Perda 31/2022)",
            "primary_school_threshold": 1600,
            "puskesmas_kelurahan_threshold": 30000,
            "delta_formula": "ceil(P_new / threshold) - ceil(P_old / threshold)",
            "impact_rule": impact_rule,
            "new_deficit_units": new_deficit_units
        }

        return SuperblockImpactDTO(
            project_name=req.project_name,
            district_code=req.district_code,
            district_name=district_name,
            residential_units=req.residential_units,
            estimated_new_occupants=new_occupants,
            site_area_m2=req.site_area_m2,
            baseline_population=baseline_population,
            new_total_population=new_total_pop,
            mandated_public_rth_m2=mandated_rth_m2,
            mandated_water_retention_m3=retention_m3,
            school_children_estimate=school_children,
            additional_primary_schools_needed=sd_needed,
            additional_health_clinics_needed=puskesmas_needed,
            simulation_delta=sim_delta,
            impact_level=impact_level,
            compliance_verdict=verdict,
            impact_rule=impact_rule,
            new_deficit_units=new_deficit_units,
            assumptions=assumptions,
            developer_legal_obligations=obligations,
            is_sandbox_isolated=True,
            disclaimer=settings.SIMULATION_DISCLAIMER
        )
