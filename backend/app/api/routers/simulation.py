"""
What-If urban scenario simulation endpoints: population shock and superblock projects.
"""

from fastapi import APIRouter, HTTPException, Depends
from backend.app.core.config import settings
from backend.app.api.deps import get_db_cursor, get_current_user
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
    with get_db_cursor() as cur:
        # 1. Fetch district baseline
        cur.execute(
            """
            SELECT id, kemendagri_code, name, population 
            FROM kecamatan
            WHERE kemendagri_code = %s OR LOWER(name) = LOWER(%s);
        """,
            (req.district_code, req.district_code),
        )
        dist = cur.fetchone()

        if not dist:
            raise HTTPException(
                status_code=404, detail=f"District '{req.district_code}' not found."
            )

        dist_id = dist["id"]
        dist_name = dist["name"]
        baseline_pop = dist["population"]

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

        # 3. Fetch regulatory standards
        cur.execute("""
            SELECT facility_type, pillar, population_threshold, service_radius_meters, legal_reference
            FROM regulatory_standards;
        """)
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
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT id, kemendagri_code, name, population 
            FROM kecamatan
            WHERE kemendagri_code = %s OR LOWER(name) = LOWER(%s);
        """,
            (req.district_code, req.district_code),
        )
        dist = cur.fetchone()

        if not dist:
            raise HTTPException(
                status_code=404, detail=f"District '{req.district_code}' not found."
            )

        dist_id = dist["id"]
        dist_name = dist["name"]
        baseline_pop = dist["population"]

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
            FROM regulatory_standards;
        """)
        standards = cur.fetchall()

    impact = WhatIfSimulationEngine.simulate_superblock_development(
        req=req,
        baseline_population=baseline_pop,
        district_name=dist_name,
        existing_facility_counts=existing_counts,
        regulatory_standards=standards,
    )
    return impact
