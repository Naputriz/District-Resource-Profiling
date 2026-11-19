"""
What-If urban scenario simulation endpoints: population shock and superblock projects.
"""

from fastapi import APIRouter, HTTPException, Depends
from backend.app.core.config import settings
from backend.app.api.deps import get_db_cursor, get_current_user
from backend.app.api.routers.regions import get_province_population_meta
from backend.app.engine.spatial import (
    resolve_district_record,
    resolve_district_candidates,
    format_ambiguous_district_detail,
)
from backend.app.engine.standards_availability import get_province_standards_availability
from backend.app.engine.simulation import (
    WhatIfSimulationEngine,
    SimulationRequest,
    SimulationDeltaDTO,
    SuperblockSimulationRequest,
    SuperblockImpactDTO,
)

router = APIRouter()


def _load_district_simulation_inputs(district_code: str):
    dist, err = resolve_district_record(district_code)
    if not dist:
        if err == "ambiguous":
            candidates = resolve_district_candidates(district_code)
            raise HTTPException(
                status_code=400,
                detail=format_ambiguous_district_detail(district_code, candidates),
            )
        raise HTTPException(
            status_code=404, detail=f"District '{district_code}' not found."
        )

    prov_code = dist.get("province_code") or settings.DEFAULT_PROVINCE_CODE
    if dist.get("province_code") and prov_code not in settings.active_provinces:
        raise HTTPException(
            status_code=404, detail="Data wilayah ini belum tersedia (rencana v1.1)"
        )

    dist_id = dist["id"]
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT facility_type, COUNT(*) as cnt
            FROM public_facilities
            WHERE kecamatan_id = %s AND is_active = TRUE
            GROUP BY facility_type;
            """,
            (dist_id,),
        )
        count_rows = cur.fetchall()
        existing_counts = {r["facility_type"]: r["cnt"] for r in count_rows}

        cur.execute(
            """
            SELECT facility_type, pillar, population_threshold, service_radius_meters,
                   legal_reference, scored
            FROM regulatory_standards
            WHERE province_code IS NULL OR province_code = %s
            ORDER BY ARRAY_POSITION(ARRAY[
                'taman_kanak_kanak', 'sekolah_dasar', 'sekolah_menengah_pertama', 'sekolah_menengah_atas',
                'puskesmas_kelurahan', 'puskesmas_kecamatan', 'rumah_sakit', 'posyandu',
                'taman_rt', 'taman_rptra', 'taman_kelurahan', 'pos_damkar',
                'stasiun_transit', 'halte_transjakarta', 'pasar_tradisional', 'taman_kecamatan'
            ]::varchar[], facility_type);
            """,
            (prov_code,),
        )
        standards = cur.fetchall()

    avail_map = get_province_standards_availability(prov_code)
    pop_note, _, _ = get_province_population_meta(prov_code)
    return dist, prov_code, existing_counts, standards, avail_map, pop_note


@router.post(
    f"{settings.API_V1_STR}/simulation/what-if",
    response_model=SimulationDeltaDTO,
    tags=["What-If Urban Simulation"],
)
def run_what_if_simulation(
    req: SimulationRequest, current_user: dict = Depends(get_current_user)
):
    """
    Simulates hypothetical urban changes (population shock + hypothetical amenities)
    in an isolated memory sandbox without mutating master data.
    """
    dist, prov_code, existing_counts, standards, avail_map, pop_note = (
        _load_district_simulation_inputs(req.district_code)
    )

    delta_result = WhatIfSimulationEngine.compute_scenario_delta(
        district_code=dist["kemendagri_code"],
        district_name=dist["name"],
        baseline_population=dist["population"],
        existing_facility_counts=existing_counts,
        regulatory_standards=standards,
        pop_shock_pct=req.population_shock_percent,
        pop_shock_count=req.population_shock_count,
        staged_amenities=req.hypothetical_facilities,
        province_code=prov_code,
        availability_map=avail_map,
        population_note=pop_note,
    )
    return delta_result


@router.post(
    f"{settings.API_V1_STR}/simulation/superblock",
    response_model=SuperblockImpactDTO,
    tags=["What-If Urban Simulation"],
)
def run_superblock_simulation(
    req: SuperblockSimulationRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Simulates high-density superblock / apartment complex development.
    Parameter asumsi tim (belum diverifikasi terhadap peraturan daerah): RTH 20%, retensi 150 mm/hari, KDB 50%.
    - Estimasi alokasi 20% luas lahan bruto untuk RTH publik (parameter asumsi)
    - Estimasi volume retensi 150 mm/hari Zero Delta Q (parameter asumsi)
    - Beban fasilitas pada sekolah dasar dan puskesmas kelurahan.
    """
    dist, prov_code, existing_counts, standards, avail_map, pop_note = (
        _load_district_simulation_inputs(req.district_code)
    )

    impact = WhatIfSimulationEngine.simulate_superblock_development(
        req=req,
        baseline_population=dist["population"],
        district_name=dist["name"],
        existing_facility_counts=existing_counts,
        regulatory_standards=standards,
        province_code=prov_code,
        availability_map=avail_map,
        population_note=pop_note,
    )
    return impact
