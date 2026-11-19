"""
What-If urban scenario simulation endpoints: population shock and superblock projects.
"""

from fastapi import APIRouter, HTTPException, Depends
from backend.app.core.config import settings
from backend.app.api.deps import get_db_cursor, get_current_user
from backend.app.engine.spatial import resolve_district_record, resolve_district_candidates
from backend.app.engine.simulation import (
    WhatIfSimulationEngine,
    SimulationRequest,
    SimulationDeltaDTO,
    SuperblockSimulationRequest,
    SuperblockImpactDTO,
)

router = APIRouter()


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
    # 1. Resolve district baseline
    dist, err = resolve_district_record(req.district_code)
    if not dist:
        if err == "ambiguous":
            candidates = resolve_district_candidates(req.district_code)
            cand_codes = ", ".join(c["kemendagri_code"] for c in candidates)
            raise HTTPException(
                status_code=400, detail=f"Nama kecamatan '{req.district_code}' ambigu (ditemukan {len(candidates)} wilayah: {cand_codes}). Mohon tentukan kode kemendagri."
            )
        raise HTTPException(
            status_code=404, detail=f"District '{req.district_code}' not found."
        )

    dist_id = dist["id"]
    dist_name = dist["name"]
    baseline_pop = dist["population"]
    prov_code = dist.get("province_code") or settings.DEFAULT_PROVINCE_CODE

    with get_db_cursor() as cur:
        # 2. Fetch existing facility counts for this district
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

        # 3. Fetch regulatory standards scoped to province/national
        cur.execute("""
            SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference
            FROM regulatory_standards
            WHERE province_code IS NULL OR province_code = %s
            ORDER BY ARRAY_POSITION(ARRAY[
                'taman_kanak_kanak', 'sekolah_dasar', 'sekolah_menengah_pertama', 'sekolah_menengah_atas',
                'puskesmas_kelurahan', 'puskesmas_kecamatan', 'rumah_sakit', 'posyandu',
                'taman_rt', 'taman_rptra', 'taman_kelurahan', 'pos_damkar',
                'stasiun_transit', 'halte_transjakarta', 'pasar_tradisional', 'taman_kecamatan'
            ]::varchar[], facility_type);
        """, (prov_code,))
        standards = cur.fetchall()

    # 4. Compute delta via Deterministic Sandbox Engine
    delta_result = WhatIfSimulationEngine.compute_scenario_delta(
        district_code=dist["kemendagri_code"],
        district_name=dist_name,
        baseline_population=baseline_pop,
        existing_facility_counts=existing_counts,
        regulatory_standards=standards,
        pop_shock_pct=req.population_shock_percent,
        pop_shock_count=req.population_shock_count,
        staged_amenities=req.hypothetical_facilities,
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
    dist, err = resolve_district_record(req.district_code)
    if not dist:
        if err == "ambiguous":
            candidates = resolve_district_candidates(req.district_code)
            cand_codes = ", ".join(c["kemendagri_code"] for c in candidates)
            raise HTTPException(
                status_code=400, detail=f"Nama kecamatan '{req.district_code}' ambigu (ditemukan {len(candidates)} wilayah: {cand_codes}). Mohon tentukan kode kemendagri."
            )
        raise HTTPException(
            status_code=404, detail=f"District '{req.district_code}' not found."
        )

    dist_id = dist["id"]
    dist_name = dist["name"]
    baseline_pop = dist["population"]
    prov_code = dist.get("province_code") or settings.DEFAULT_PROVINCE_CODE

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

        cur.execute("""
            SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference
            FROM regulatory_standards
            WHERE province_code IS NULL OR province_code = %s;
        """, (prov_code,))
        standards = cur.fetchall()

    impact = WhatIfSimulationEngine.simulate_superblock_development(
        req=req,
        baseline_population=baseline_pop,
        district_name=dist_name,
        existing_facility_counts=existing_counts,
        regulatory_standards=standards,
    )
    return impact
