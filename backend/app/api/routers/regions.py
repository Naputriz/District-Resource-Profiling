"""
Multi-region configuration and availability endpoints.
Provides region metadata: center, zoom, bbox, UTM SRID, data sources, snapshot dates,
population source, and runtime Active/Staging/Planned status computed from ACTIVE_PROVINCES + DB.
"""

import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api.deps import get_db_cursor
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

_CACHE_TTL_SECONDS = 60.0
_DB_STATS_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "db_name": None,
    "data": None,
}


class CoverageSummary(BaseModel):
    total: int = 0
    scored: int = 0
    gated: int = 0


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
    population_source: Optional[str] = None
    coverage_summary: Optional[CoverageSummary] = None


REGIONS_CATALOG: Dict[str, Dict[str, Any]] = {
    "11": {
        "province_code": "11",
        "name": "Aceh",
        "has_data": False,
        "status": "Planned",
        "center": [4.2247, 96.9103],
        "zoom": 8,
        "bbox": [95.0108, 2.0041, 98.2872, 6.0769],
        "utm_srid": 32647,
        "total_districts": 289,
        "geojson_url": "/data/boundaries/11_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "12": {
        "province_code": "12",
        "name": "Sumatera Utara",
        "has_data": False,
        "status": "Planned",
        "center": [2.1855, 99.0569],
        "zoom": 8,
        "bbox": [97.0591, -0.6388, 100.4258, 4.3015],
        "utm_srid": 32647,
        "total_districts": 449,
        "geojson_url": "/data/boundaries/12_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "13": {
        "province_code": "13",
        "name": "Sumatera Barat",
        "has_data": False,
        "status": "Planned",
        "center": [-0.8512, 100.4668],
        "zoom": 8,
        "bbox": [98.5967, -4.0163, 101.8929, 0.9074],
        "utm_srid": 32747,
        "total_districts": 179,
        "geojson_url": "/data/boundaries/13_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "14": {
        "province_code": "14",
        "name": "Riau",
        "has_data": False,
        "status": "Planned",
        "center": [0.5127, 101.8078],
        "zoom": 8,
        "bbox": [100.0248, -1.1223, 103.8146, 2.9191],
        "utm_srid": 32647,
        "total_districts": 169,
        "geojson_url": "/data/boundaries/14_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "15": {
        "province_code": "15",
        "name": "Jambi",
        "has_data": False,
        "status": "Planned",
        "center": [-1.7038, 102.6929],
        "zoom": 8,
        "bbox": [101.1286, -2.7701, 104.498, -0.7333],
        "utm_srid": 32748,
        "total_districts": 141,
        "geojson_url": "/data/boundaries/15_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "16": {
        "province_code": "16",
        "name": "Sumatera Selatan",
        "has_data": False,
        "status": "Planned",
        "center": [-3.2117, 104.1709],
        "zoom": 8,
        "bbox": [102.0674, -4.9254, 106.1894, -1.6254],
        "utm_srid": 32748,
        "total_districts": 236,
        "geojson_url": "/data/boundaries/16_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "17": {
        "province_code": "17",
        "name": "Bengkulu",
        "has_data": False,
        "status": "Planned",
        "center": [-3.5752, 102.3555],
        "zoom": 8,
        "bbox": [101.0223, -5.5146, 103.7635, -2.2767],
        "utm_srid": 32748,
        "total_districts": 128,
        "geojson_url": "/data/boundaries/17_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "18": {
        "province_code": "18",
        "name": "Lampung",
        "has_data": False,
        "status": "Planned",
        "center": [-4.903, 105.0138],
        "zoom": 8,
        "bbox": [103.6419, -5.9729, 105.9169, -3.7774],
        "utm_srid": 32748,
        "total_districts": 228,
        "geojson_url": "/data/boundaries/18_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "19": {
        "province_code": "19",
        "name": "Kepulauan Bangka Belitung",
        "has_data": False,
        "status": "Planned",
        "center": [-2.4498, 106.5559],
        "zoom": 8,
        "bbox": [105.1084, -3.4169, 108.848, -1.5018],
        "utm_srid": 32748,
        "total_districts": 47,
        "geojson_url": "/data/boundaries/19_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Kalimantan PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "21": {
        "province_code": "21",
        "name": "Kepulauan Riau",
        "has_data": False,
        "status": "Planned",
        "center": [1.4826, 105.4078],
        "zoom": 7,
        "bbox": [103.2852, -1.2984, 109.164, 4.7978],
        "utm_srid": 32648,
        "total_districts": 70,
        "geojson_url": "/data/boundaries/21_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sumatra & Kalimantan PBFs (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
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
        "population_source": "BPS 2024",
        "data_sources": {
            "boundaries": "BPS / Kemendagri GeoJSON (SakifAbdillah/jakartaKecamatanGeoJSON)",
            "demographics": "BPS Provinsi DKI Jakarta 2024",
            "facilities": "OpenStreetMap contributors (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-10-14",
        },
    },
    "32": {
        "province_code": "32",
        "name": "Jawa Barat",
        "has_data": False,
        "status": "Planned",
        "center": [-6.921, 107.6039],
        "zoom": 9,
        "bbox": [106.3703, -7.821, 108.8469, -5.9181],
        "utm_srid": 32748,
        "total_districts": 627,
        "geojson_url": "/data/boundaries/32_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "33": {
        "province_code": "33",
        "name": "Jawa Tengah",
        "has_data": False,
        "status": "Planned",
        "center": [-7.2583, 110.1987],
        "zoom": 9,
        "bbox": [108.5559, -8.2119, 111.6914, -5.7257],
        "utm_srid": 32749,
        "total_districts": 573,
        "geojson_url": "/data/boundaries/33_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "34": {
        "province_code": "34",
        "name": "DI Yogyakarta",
        "has_data": False,
        "status": "Planned",
        "center": [-7.895, 110.4458],
        "zoom": 10,
        "bbox": [110.003, -8.204, 110.8346, -7.5419],
        "utm_srid": 32749,
        "total_districts": 78,
        "geojson_url": "/data/boundaries/34_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "35": {
        "province_code": "35",
        "name": "Jawa Timur",
        "has_data": False,
        "status": "Planned",
        "center": [-7.7197, 112.7339],
        "zoom": 8,
        "bbox": [110.8987, -8.7804, 116.2702, -5.0489],
        "utm_srid": 32749,
        "total_districts": 666,
        "geojson_url": "/data/boundaries/35_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "36": {
        "province_code": "36",
        "name": "Banten",
        "has_data": False,
        "status": "Planned",
        "center": [-6.4563, 106.1088],
        "zoom": 9,
        "bbox": [105.0998, -7.0168, 106.7799, -5.8074],
        "utm_srid": 32748,
        "total_districts": 155,
        "geojson_url": "/data/boundaries/36_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-17",
        },
    },
    "51": {
        "province_code": "51",
        "name": "Bali",
        "has_data": False,
        "status": "Planned",
        "center": [-8.3696, 115.1319],
        "zoom": 9,
        "bbox": [114.4316, -8.8492, 115.7125, -8.0614],
        "utm_srid": 32750,
        "total_districts": 57,
        "geojson_url": "/data/boundaries/51_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Nusa Tenggara PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "52": {
        "province_code": "52",
        "name": "Nusa Tenggara Barat",
        "has_data": False,
        "status": "Planned",
        "center": [-8.6067, 117.5075],
        "zoom": 8,
        "bbox": [115.821, -9.1097, 119.3358, -8.0801],
        "utm_srid": 32750,
        "total_districts": 116,
        "geojson_url": "/data/boundaries/52_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Nusa Tenggara PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "53": {
        "province_code": "53",
        "name": "Nusa Tenggara Timur",
        "has_data": False,
        "status": "Planned",
        "center": [-9.26, 122.1815],
        "zoom": 7,
        "bbox": [118.927, -11.0076, 125.1933, -8.0634],
        "utm_srid": 32751,
        "total_districts": 307,
        "geojson_url": "/data/boundaries/53_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Nusa Tenggara PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "61": {
        "province_code": "61",
        "name": "Kalimantan Barat",
        "has_data": False,
        "status": "Planned",
        "center": [-0.0844, 111.1256],
        "zoom": 7,
        "bbox": [108.6778, -3.0679, 114.2226, 2.0813],
        "utm_srid": 32749,
        "total_districts": 174,
        "geojson_url": "/data/boundaries/61_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Kalimantan PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "62": {
        "province_code": "62",
        "name": "Kalimantan Tengah",
        "has_data": False,
        "status": "Planned",
        "center": [-1.6039, 113.4248],
        "zoom": 7,
        "bbox": [110.7345, -3.5436, 115.8472, 0.7778],
        "utm_srid": 32749,
        "total_districts": 136,
        "geojson_url": "/data/boundaries/62_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Kalimantan PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "63": {
        "province_code": "63",
        "name": "Kalimantan Selatan",
        "has_data": False,
        "status": "Planned",
        "center": [-3.0122, 115.4406],
        "zoom": 8,
        "bbox": [114.3466, -4.7448, 116.5589, -1.315],
        "utm_srid": 32750,
        "total_districts": 152,
        "geojson_url": "/data/boundaries/63_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Kalimantan PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "64": {
        "province_code": "64",
        "name": "Kalimantan Timur",
        "has_data": False,
        "status": "Planned",
        "center": [0.4654, 116.4743],
        "zoom": 7,
        "bbox": [113.8359, -2.4052, 118.9891, 2.6263],
        "utm_srid": 32650,
        "total_districts": 103,
        "geojson_url": "/data/boundaries/64_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Kalimantan PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "65": {
        "province_code": "65",
        "name": "Kalimantan Utara",
        "has_data": False,
        "status": "Planned",
        "center": [2.8949, 116.2159],
        "zoom": 7,
        "bbox": [114.5895, 1.0437, 117.9859, 4.4083],
        "utm_srid": 32650,
        "total_districts": 53,
        "geojson_url": "/data/boundaries/65_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Kalimantan PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "71": {
        "province_code": "71",
        "name": "Sulawesi Utara",
        "has_data": False,
        "status": "Planned",
        "center": [1.2622, 124.5223],
        "zoom": 7,
        "bbox": [123.1109, 0.2922, 127.164, 5.5658],
        "utm_srid": 32651,
        "total_districts": 171,
        "geojson_url": "/data/boundaries/71_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sulawesi PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "72": {
        "province_code": "72",
        "name": "Sulawesi Tengah",
        "has_data": False,
        "status": "Planned",
        "center": [-0.9985, 121.2058],
        "zoom": 7,
        "bbox": [119.4469, -3.6407, 124.1815, 1.3752],
        "utm_srid": 32751,
        "total_districts": 175,
        "geojson_url": "/data/boundaries/72_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sulawesi & Maluku PBFs (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "73": {
        "province_code": "73",
        "name": "Sulawesi Selatan",
        "has_data": False,
        "status": "Planned",
        "center": [-3.7432, 120.1447],
        "zoom": 8,
        "bbox": [117.0385, -7.7589, 121.8402, -1.8952],
        "utm_srid": 32751,
        "total_districts": 307,
        "geojson_url": "/data/boundaries/73_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sulawesi PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "74": {
        "province_code": "74",
        "name": "Sulawesi Tenggara",
        "has_data": False,
        "status": "Planned",
        "center": [-4.1245, 122.0705],
        "zoom": 8,
        "bbox": [120.8647, -6.2131, 124.6122, -2.7794],
        "utm_srid": 32751,
        "total_districts": 222,
        "geojson_url": "/data/boundaries/74_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sulawesi PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "75": {
        "province_code": "75",
        "name": "Gorontalo",
        "has_data": False,
        "status": "Planned",
        "center": [0.6871, 122.3747],
        "zoom": 9,
        "bbox": [121.1612, 0.3063, 123.5523, 1.0406],
        "utm_srid": 32651,
        "total_districts": 77,
        "geojson_url": "/data/boundaries/75_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sulawesi PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "76": {
        "province_code": "76",
        "name": "Sulawesi Barat",
        "has_data": False,
        "status": "Planned",
        "center": [-2.4616, 119.3441],
        "zoom": 8,
        "bbox": [117.0695, -3.5703, 119.8755, -0.8467],
        "utm_srid": 32750,
        "total_districts": 69,
        "geojson_url": "/data/boundaries/76_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Sulawesi & Kalimantan PBFs (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "81": {
        "province_code": "81",
        "name": "Maluku",
        "has_data": False,
        "status": "Planned",
        "center": [-4.7377, 129.8413],
        "zoom": 7,
        "bbox": [125.7225, -8.3467, 134.9086, -1.3787],
        "utm_srid": 32752,
        "total_districts": 118,
        "geojson_url": "/data/boundaries/81_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Maluku PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "82": {
        "province_code": "82",
        "name": "Maluku Utara",
        "has_data": False,
        "status": "Planned",
        "center": [0.1882, 127.5366],
        "zoom": 7,
        "bbox": [124.2831, -2.4774, 129.6575, 2.6455],
        "utm_srid": 32652,
        "total_districts": 116,
        "geojson_url": "/data/boundaries/82_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Maluku PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "91": {
        "province_code": "91",
        "name": "Papua",
        "has_data": False,
        "status": "Planned",
        "center": [-2.6218, 138.5211],
        "zoom": 7,
        "bbox": [134.2957, -3.9473, 141.0, 0.9378],
        "utm_srid": 32754,
        "total_districts": 97,
        "geojson_url": "/data/boundaries/91_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Papua PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "92": {
        "province_code": "92",
        "name": "Papua Barat",
        "has_data": False,
        "status": "Planned",
        "center": [-2.6029, 133.6004],
        "zoom": 7,
        "bbox": [131.999, -4.2567, 135.258, -0.7138],
        "utm_srid": 32753,
        "total_districts": 78,
        "geojson_url": "/data/boundaries/92_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Papua PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "93": {
        "province_code": "93",
        "name": "Papua Selatan",
        "has_data": False,
        "status": "Planned",
        "center": [-6.6575, 139.5288],
        "zoom": 7,
        "bbox": [137.5504, -9.1204, 141.0194, -4.5984],
        "utm_srid": 32754,
        "total_districts": 69,
        "geojson_url": "/data/boundaries/93_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Papua PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "94": {
        "province_code": "94",
        "name": "Papua Tengah",
        "has_data": False,
        "status": "Planned",
        "center": [-3.8824, 136.5405],
        "zoom": 7,
        "bbox": [134.5988, -5.2392, 138.3046, -2.4777],
        "utm_srid": 32753,
        "total_districts": 73,
        "geojson_url": "/data/boundaries/94_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Papua PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "95": {
        "province_code": "95",
        "name": "Papua Pegunungan",
        "has_data": False,
        "status": "Planned",
        "center": [-4.2669, 139.4394],
        "zoom": 7,
        "bbox": [137.5686, -5.2947, 141.0, -3.1944],
        "utm_srid": 32754,
        "total_districts": 185,
        "geojson_url": "/data/boundaries/95_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Papua PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
    "96": {
        "province_code": "96",
        "name": "Papua Barat Daya",
        "has_data": False,
        "status": "Planned",
        "center": [-1.0802, 131.896],
        "zoom": 7,
        "bbox": [129.3077, -2.2801, 133.5167, 0.5822],
        "utm_srid": 32752,
        "total_districts": 99,
        "geojson_url": "/data/boundaries/96_kecamatan.geojson",
        "population_source": "Estimasi model WorldPop R2025A 2024",
        "data_sources": {
            "boundaries": "HDX COD-AB Indonesia (BPS/BIG)",
            "demographics": "WorldPop R2025A 2024 (model estimate)",
            "facilities": "OpenStreetMap contributors via Geofabrik Papua PBF (ODbL)",
        },
        "snapshot_dates": {
            "demographics": "2024",
            "osm": "2026-11-18",
        },
    },
}


def clear_regions_cache() -> None:
    """Clears the in-process DB stats cache (useful in tests)."""
    _DB_STATS_CACHE["ts"] = 0.0
    _DB_STATS_CACHE["db_name"] = None
    _DB_STATS_CACHE["data"] = None


def get_region_meta(province_code: Optional[str]) -> Dict[str, Any]:
    """Returns static metadata entry for a province code, defaulting to DEFAULT_PROVINCE_CODE."""
    code = str(province_code or settings.DEFAULT_PROVINCE_CODE).strip()
    return REGIONS_CATALOG.get(code) or REGIONS_CATALOG[settings.DEFAULT_PROVINCE_CODE]


def get_province_population_meta(
    province_code: Optional[str],
    db_source: Optional[str] = None,
    db_verif: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Returns (population_note, population_source, population_verification_status)
    for the given province without hardcoding TODO-VERIFY.
    """
    code = str(province_code or settings.DEFAULT_PROVINCE_CODE).strip()
    if code == "31":
        note = "BPS 2024"
        src = db_source or "BPS 2024"
        verif = db_verif or "bps_2024"
        return (note, src, verif)
    meta = REGIONS_CATALOG.get(code, {})
    default_src = meta.get("population_source") or "Estimasi model WorldPop R2025A 2024"
    return (default_src, db_source or default_src, db_verif or "model_estimate")


def _get_db_province_stats(force_refresh: bool = False) -> Optional[Dict[str, Dict[str, int]]]:
    """
    Queries per-province kecamatan counts (total, scored, gated) from PostgreSQL,
    cached in-process for 60 seconds per database name.
    Returns None if the database is unreachable.
    """
    now = time.monotonic()
    db_name = settings.POSTGRES_DB
    if (
        not force_refresh
        and _DB_STATS_CACHE["data"] is not None
        and _DB_STATS_CACHE["db_name"] == db_name
        and (now - _DB_STATS_CACHE["ts"]) < _CACHE_TTL_SECONDS
    ):
        return _DB_STATS_CACHE["data"]

    try:
        with get_db_cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.kemendagri_code AS province_code,
                    COUNT(k.id)::int AS total_kec,
                    COUNT(s.id) FILTER (WHERE s.composite_livability_score IS NOT NULL)::int AS scored_kec,
                    COUNT(s.id) FILTER (WHERE s.composite_livability_score IS NULL AND k.id IS NOT NULL)::int AS gated_kec
                FROM provinces p
                JOIN kabupaten_kota c ON c.province_id = p.id
                JOIN kecamatan k ON k.kabupaten_kota_id = c.id
                LEFT JOIN district_compliance_scores s ON s.district_id = k.id
                GROUP BY p.kemendagri_code;
                """
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.warning("Failed to query region stats from DB: %s", exc)
        return None

    stats: Dict[str, Dict[str, int]] = {}
    for r in rows:
        pcode = r.get("province_code")
        if pcode:
            stats[str(pcode)] = {
                "total": int(r.get("total_kec") or 0),
                "scored": int(r.get("scored_kec") or 0),
                "gated": int(r.get("gated_kec") or 0),
            }

    _DB_STATS_CACHE["ts"] = now
    _DB_STATS_CACHE["db_name"] = db_name
    _DB_STATS_CACHE["data"] = stats
    return stats


def compute_region_status(
    province_code: str,
    db_stats: Optional[Dict[str, Dict[str, int]]],
    active_provinces: List[str],
) -> Tuple[bool, str, Optional[CoverageSummary]]:
    """Computes (has_data, status, coverage_summary) from DB row counts and ACTIVE_PROVINCES."""
    if db_stats is None:
        # Offline fallback (e.g. unit tests with DB unreachable)
        is_default_active = (
            province_code == settings.DEFAULT_PROVINCE_CODE
            and province_code in active_provinces
        )
        if is_default_active:
            return (True, "Active", None)
        return (False, "Planned", None)

    stats = db_stats.get(province_code)
    has_db_rows = bool(stats and stats.get("total", 0) > 0)
    if not has_db_rows:
        return (False, "Planned", None)

    summary = CoverageSummary(
        total=stats["total"],
        scored=stats["scored"],
        gated=stats["gated"],
    )
    if province_code in active_provinces:
        return (True, "Active", summary)
    return (True, "Staging", summary)


def is_province_served(province_code: str) -> bool:
    """
    Returns True iff `province_code` is in ACTIVE_PROVINCES AND has kecamatan rows in DB.
    Falls back to checking ACTIVE_PROVINCES == default when DB is unreachable in unit tests.
    """
    code = str(province_code).strip()
    active_list = settings.active_provinces
    if code not in active_list:
        return False
    db_stats = _get_db_province_stats()
    if db_stats is None:
        return code == settings.DEFAULT_PROVINCE_CODE
    stats = db_stats.get(code)
    return bool(stats and stats.get("total", 0) > 0)


def _build_region_entry(
    code: str,
    base: Dict[str, Any],
    db_stats: Optional[Dict[str, Dict[str, int]]],
    active_provinces: List[str],
) -> Dict[str, Any]:
    has_data, status, coverage_summary = compute_region_status(
        code, db_stats, active_provinces
    )
    entry = dict(base)
    entry["has_data"] = has_data
    entry["status"] = status
    entry["coverage_summary"] = coverage_summary
    if status == "Planned":
        entry["geojson_url"] = None
    return entry


@router.get(
    f"{settings.API_V1_STR}/regions",
    response_model=List[RegionInfo],
    tags=["Multi-Region Support"],
)
def list_regions():
    """
    Returns list of supported provinces with runtime availability status
    ('Active', 'Staging', or 'Planned'), map center/zoom, bounding box,
    UTM SRID, data sources, population source, and DB coverage summary.
    """
    db_stats = _get_db_province_stats()
    active_list = settings.active_provinces
    return [
        _build_region_entry(code, base, db_stats, active_list)
        for code, base in REGIONS_CATALOG.items()
    ]


@router.get(
    f"{settings.API_V1_STR}/regions/{{province_code}}",
    response_model=RegionInfo,
    tags=["Multi-Region Support"],
)
def get_region_detail(province_code: str):
    """
    Returns configuration and status for a specific active province.
    Returns 404 with explanatory message if province is not Active.
    """
    code = province_code.strip()
    base = REGIONS_CATALOG.get(code)
    if not base:
        raise HTTPException(
            status_code=404,
            detail="Data wilayah ini belum tersedia (rencana v1.1)",
        )

    db_stats = _get_db_province_stats()
    active_list = settings.active_provinces
    entry = _build_region_entry(code, base, db_stats, active_list)

    if entry["status"] != "Active":
        raise HTTPException(
            status_code=404,
            detail="Data wilayah ini belum tersedia (rencana v1.1)",
        )

    return entry
