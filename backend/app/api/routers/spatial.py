"""
Deterministic PostGIS spatial calculations: facility buffers and blank spots.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from backend.app.core.config import settings
from backend.app.api.deps import get_current_user
from backend.app.engine.spatial import (
    PostGISSpatialEngine,
    BlankSpotAnalysisResult,
    BlankSpotSimulationDelta,
)
from backend.app.api.schemas import BlankSpotSimRequest

router = APIRouter()


@router.get(f"{settings.API_V1_STR}/spatial/buffers", tags=["Spatial Calculations"])
def get_district_facility_buffers(
    district_code: str = Query(
        ..., description="kemendagri_code, e.g. 31.71.09 (Tebet) or 35.78.180 (Tegalsari)"
    ),
    facility_type: Optional[str] = Query(
        None, description="e.g. puskesmas_kelurahan, sekolah_dasar"
    ),
    pillar: Optional[str] = None,
    province_code: Optional[str] = Query(
        None, description="Opsional: kode provinsi untuk resolusi nama kecamatan"
    ),
):
    """
    Returns exact service coverage buffers (FeatureCollection) projected to WGS 84 GeoJSON.
    Calculated via PostGIS per-district metric UTM SRID.
    """
    try:
        buffers = PostGISSpatialEngine.compute_facility_buffers(
            district_code=district_code,
            facility_type=facility_type,
            pillar=pillar,
            province_code=province_code,
        )
        return buffers
    except ValueError as ve:
        err_msg = str(ve)
        if "ambigu" in err_msg.lower():
            raise HTTPException(status_code=400, detail=err_msg)
        raise HTTPException(status_code=404, detail=err_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    f"{settings.API_V1_STR}/spatial/blank-spots",
    response_model=BlankSpotAnalysisResult,
    tags=["Spatial Calculations"],
)
def get_district_blank_spots(
    district_code: str = Query(
        ..., description="kemendagri_code, e.g. 31.71.09 (Tebet) or 35.78.180 (Tegalsari)"
    ),
    facility_type: str = Query(
        "puskesmas_kelurahan", description="facility_type to analyze"
    ),
    province_code: Optional[str] = Query(
        None, description="Opsional: kode provinsi untuk resolusi nama kecamatan"
    ),
):
    """
    Calculates unserved areas ('blank spots') using PostGIS ST_Difference.
    Returns exact unserved area in km2, percentage coverage, and blank spot MultiPolygon GeoJSON.
    """
    try:
        result = PostGISSpatialEngine.calculate_blank_spots(
            district_code, facility_type, province_code=province_code
        )
        return result
    except ValueError as ve:
        err_msg = str(ve)
        if "ambigu" in err_msg.lower():
            raise HTTPException(status_code=400, detail=err_msg)
        raise HTTPException(status_code=404, detail=err_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    f"{settings.API_V1_STR}/spatial/blank-spots/simulate-reduction",
    response_model=BlankSpotSimulationDelta,
    tags=["Spatial Calculations"],
)
def simulate_blank_spot_reduction(
    req: BlankSpotSimRequest, current_user: dict = Depends(get_current_user)
):
    """
    Simulates how placing a new hypothetical amenity reduces the unserved blank spot polygon.
    Runs transiently in PostGIS memory without persisting to master database.
    """
    try:
        delta = PostGISSpatialEngine.simulate_blank_spot_reduction(
            district_code=req.district_code,
            facility_type=req.facility_type,
            hypothetical_coords=req.hypothetical_coordinates,
            custom_radius_meters=req.custom_radius_meters,
        )
        return delta
    except ValueError as ve:
        err_msg = str(ve)
        if "ambigu" in err_msg.lower():
            raise HTTPException(status_code=400, detail=err_msg)
        raise HTTPException(status_code=404, detail=err_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
