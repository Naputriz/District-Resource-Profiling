"""
Multi-region configuration and availability endpoints.
Provides region metadata: center, zoom, bbox, UTM SRID, data sources, and snapshot dates.
Strictly adheres to TODO-3: only DKI Jakarta (code 31) has loaded data; other regions are Planned (v1.1).
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from backend.app.core.config import settings

router = APIRouter()


class RegionInfo(BaseModel):
    province_code: str
    name: str
    has_data: bool
    status: str
    center: List[float]  # [lat, lon]
    zoom: int
    bbox: List[float]  # [min_lon, min_lat, max_lon, max_lat]
    utm_srid: int
    total_districts: int
    geojson_url: Optional[str] = None
    data_sources: Optional[Dict[str, str]] = None
    snapshot_dates: Optional[Dict[str, str]] = None


REGIONS_CATALOG: Dict[str, Dict[str, Any]] = {
    "31": {
        "province_code": "31",
        "name": "DKI Jakarta",
        "has_data": True,
        "status": "Active",
        "center": [-6.2088, 106.8456],
        "zoom": 11,
        "bbox": [106.5100, -6.3800, 106.9800, -5.5400],
        "utm_srid": 32748,
        "total_districts": 44,
        "geojson_url": "/data/boundaries/jakarta_44_kecamatan.geojson",
        "data_sources": {
            "boundaries": "BPS / Kemendagri GeoJSON (SakifAbdillah/jakartaKecamatanGeoJSON)",
            "demographics": "BPS Provinsi DKI Jakarta 2024",
            "facilities": "OpenStreetMap contributors (ODbL)"
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-10-14"
        }
    },
    "32": {
        "province_code": "32",
        "name": "Jawa Barat",
        "has_data": False,
        "status": "Planned (v1.1)",
        "center": [-6.9175, 107.6191],
        "zoom": 9,
        "bbox": [106.37, -7.82, 108.83, -5.91],
        "utm_srid": 32748,
        "total_districts": 627,
        "geojson_url": None,
        "data_sources": None,
        "snapshot_dates": None
    },
    "33": {
        "province_code": "33",
        "name": "Jawa Tengah",
        "has_data": False,
        "status": "Planned (v1.1)",
        "center": [-7.1510, 110.1403],
        "zoom": 9,
        "bbox": [108.55, -8.21, 111.69, -6.42],
        "utm_srid": 32749,
        "total_districts": 576,
        "geojson_url": None,
        "data_sources": None,
        "snapshot_dates": None
    },
    "34": {
        "province_code": "34",
        "name": "DI Yogyakarta",
        "has_data": False,
        "status": "Planned (v1.1)",
        "center": [-7.7956, 110.3695],
        "zoom": 10,
        "bbox": [110.00, -8.20, 110.84, -7.54],
        "utm_srid": 32749,
        "total_districts": 78,
        "geojson_url": None,
        "data_sources": None,
        "snapshot_dates": None
    },
    "35": {
        "province_code": "35",
        "name": "Jawa Timur",
        "has_data": False,
        "status": "Planned (v1.1)",
        "center": [-7.5361, 112.2384],
        "zoom": 8,
        "bbox": [110.89, -8.78, 114.61, -6.75],
        "utm_srid": 32749,
        "total_districts": 666,
        "geojson_url": None,
        "data_sources": None,
        "snapshot_dates": None
    },
    "36": {
        "province_code": "36",
        "name": "Banten",
        "has_data": False,
        "status": "Planned (v1.1)",
        "center": [-6.4058, 106.0640],
        "zoom": 9,
        "bbox": [105.10, -7.01, 106.77, -5.85],
        "utm_srid": 32748,
        "total_districts": 155,
        "geojson_url": None,
        "data_sources": None,
        "snapshot_dates": None
    }
}


@router.get(
    f"{settings.API_V1_STR}/regions",
    response_model=List[RegionInfo],
    tags=["Multi-Region Support"]
)
def list_regions():
    """
    Returns list of supported provinces with data availability flags,
    map center/zoom, bounding box, UTM SRID, and data sources.
    """
    return list(REGIONS_CATALOG.values())


@router.get(
    f"{settings.API_V1_STR}/regions/{{province_code}}",
    response_model=RegionInfo,
    tags=["Multi-Region Support"]
)
def get_region_detail(province_code: str):
    """
    Returns configuration and status for a specific province.
    Returns 404 with explanatory message if province data is not yet loaded.
    """
    region = REGIONS_CATALOG.get(province_code.strip())
    if not region:
        raise HTTPException(
            status_code=404,
            detail="Data wilayah ini belum tersedia (rencana v1.1)"
        )

    if not region["has_data"]:
        raise HTTPException(
            status_code=404,
            detail="Data wilayah ini belum tersedia (rencana v1.1)"
        )

    return region
