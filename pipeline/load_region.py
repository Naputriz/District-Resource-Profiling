"""
Multi-region spatial ingestion and compliance scoring loader (Java provinces 32-36).
Extends the existing architecture (pipeline/boundary_loader.py, pipeline/osm_extractor.py,
backend/app/engine/standards_availability.py, backend/app/engine/spatial.py).

Usage:
    PYTHONPATH=. /mnt/data/rpl/og/.venv/bin/python pipeline/load_region.py --province 34 [--dry-run]
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import osmium
import psycopg2
from psycopg2.extras import execute_values
import pyogrio.raw
import pyproj
import rasterio
import rasterio.mask
import redis
from dotenv import load_dotenv
from shapely import STRtree, from_wkb
from shapely.geometry import Point, mapping
from shapely.ops import transform as shapely_transform, unary_union

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from backend.app.engine.spatial import calculate_utm_srid, calculate_utm_zone
from backend.app.engine.standards_availability import (
    STANDARDS_AVAILABILITY_SPEC,
    build_district_metrics_and_scores,
    calculate_pillar_and_composite_scores,
    evaluate_availability,
)
from pipeline.osm_extractor import (
    classify_osm_element_auto,
    deduplicate_facilities,
    matching_query_groups,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("load_region")

RAW_DATA_DIR = Path(os.getenv("DRP_RAW_DATA_DIR", "/mnt/data/rpl/data_raw"))
CODAB_GDB_PATH = RAW_DATA_DIR / "cod_ab_idn" / "idn_admin_boundaries.gdb"
WORLDPOP_TIF_PATH = RAW_DATA_DIR / "idn_pop_2024_CN_100m_R2025A_v1.tif"
JAVA_PBF_PATH = RAW_DATA_DIR / "java-latest.osm.pbf"
JAVA_FACILITIES_CACHE = RAW_DATA_DIR / "java_facilities_raw_classified.json"
SUMATRA_PBF_PATH = RAW_DATA_DIR / "sumatra-latest.osm.pbf"
SUMATRA_FACILITIES_CACHE = RAW_DATA_DIR / "sumatra_facilities_raw_classified.json"
KALIMANTAN_PBF_PATH = RAW_DATA_DIR / "kalimantan-latest.osm.pbf"
KALIMANTAN_FACILITIES_CACHE = RAW_DATA_DIR / "kalimantan_facilities_raw_classified.json"
SULAWESI_PBF_PATH = RAW_DATA_DIR / "sulawesi-latest.osm.pbf"
SULAWESI_FACILITIES_CACHE = RAW_DATA_DIR / "sulawesi_facilities_raw_classified.json"
MALUKU_PBF_PATH = RAW_DATA_DIR / "maluku-latest.osm.pbf"
MALUKU_FACILITIES_CACHE = RAW_DATA_DIR / "maluku_facilities_raw_classified.json"
PAPUA_PBF_PATH = RAW_DATA_DIR / "papua-latest.osm.pbf"
PAPUA_FACILITIES_CACHE = RAW_DATA_DIR / "papua_facilities_raw_classified.json"
NUSA_TENGGARA_PBF_PATH = RAW_DATA_DIR / "nusa-tenggara-latest.osm.pbf"
NUSA_TENGGARA_FACILITIES_CACHE = RAW_DATA_DIR / "nusa_tenggara_facilities_raw_classified.json"

PBF_SOURCES: Dict[str, Dict[str, Any]] = {
    "java": {
        "label": "Java",
        "path": JAVA_PBF_PATH,
        "cache": JAVA_FACILITIES_CACHE,
        "url": "https://download.geofabrik.de/asia/indonesia/java-latest.osm.pbf",
        "source": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
    },
    "sumatra": {
        "label": "Sumatra",
        "path": SUMATRA_PBF_PATH,
        "cache": SUMATRA_FACILITIES_CACHE,
        "url": "https://download.geofabrik.de/asia/indonesia/sumatra-latest.osm.pbf",
        "source": "OpenStreetMap contributors via Geofabrik Sumatra PBF (ODbL)",
    },
    "kalimantan": {
        "label": "Kalimantan",
        "path": KALIMANTAN_PBF_PATH,
        "cache": KALIMANTAN_FACILITIES_CACHE,
        "url": "https://download.geofabrik.de/asia/indonesia/kalimantan-latest.osm.pbf",
        "source": "OpenStreetMap contributors via Geofabrik Kalimantan PBF (ODbL)",
    },
    "sulawesi": {
        "label": "Sulawesi",
        "path": SULAWESI_PBF_PATH,
        "cache": SULAWESI_FACILITIES_CACHE,
        "url": "https://download.geofabrik.de/asia/indonesia/sulawesi-latest.osm.pbf",
        "source": "OpenStreetMap contributors via Geofabrik Sulawesi PBF (ODbL)",
    },
    "nusa-tenggara": {
        "label": "Nusa Tenggara",
        "path": NUSA_TENGGARA_PBF_PATH,
        "cache": NUSA_TENGGARA_FACILITIES_CACHE,
        "url": "https://download.geofabrik.de/asia/indonesia/nusa-tenggara-latest.osm.pbf",
        "source": "OpenStreetMap contributors via Geofabrik Nusa Tenggara PBF (ODbL)",
    },
    "maluku": {
        "label": "Maluku",
        "path": MALUKU_PBF_PATH,
        "cache": MALUKU_FACILITIES_CACHE,
        "url": "https://download.geofabrik.de/asia/indonesia/maluku-latest.osm.pbf",
        "source": "OpenStreetMap contributors via Geofabrik Maluku PBF (ODbL)",
    },
    "papua": {
        "label": "Papua",
        "path": PAPUA_PBF_PATH,
        "cache": PAPUA_FACILITIES_CACHE,
        "url": "https://download.geofabrik.de/asia/indonesia/papua-latest.osm.pbf",
        "source": "OpenStreetMap contributors via Geofabrik Papua PBF (ODbL)",
    },
}

REGIONS_DIR = BASE_DIR / "data" / "regions"
FRONTEND_BOUNDARIES_DIR = REPO_ROOT / "frontend" / "data" / "boundaries"

SUPPORTED_PROVINCES: Dict[str, Dict[str, Any]] = {
    # Java (32-36)
    "32": {"name": "Jawa Barat", "zoom": 9, "island": "java", "pbfs": ["java"]},
    "33": {"name": "Jawa Tengah", "zoom": 9, "island": "java", "pbfs": ["java"]},
    "34": {"name": "DI Yogyakarta", "zoom": 10, "island": "java", "pbfs": ["java"]},
    "35": {"name": "Jawa Timur", "zoom": 8, "island": "java", "pbfs": ["java"]},
    "36": {"name": "Banten", "zoom": 9, "island": "java", "pbfs": ["java"]},
    # Sumatra (11-19, 21)
    "11": {"name": "Aceh", "zoom": 8, "island": "sumatra", "pbfs": ["sumatra"]},
    "12": {"name": "Sumatera Utara", "zoom": 8, "island": "sumatra", "pbfs": ["sumatra"]},
    "13": {"name": "Sumatera Barat", "zoom": 8, "island": "sumatra", "pbfs": ["sumatra"]},
    "14": {"name": "Riau", "zoom": 8, "island": "sumatra", "pbfs": ["sumatra"]},
    "15": {"name": "Jambi", "zoom": 8, "island": "sumatra", "pbfs": ["sumatra"]},
    "16": {"name": "Sumatera Selatan", "zoom": 8, "island": "sumatra", "pbfs": ["sumatra"]},
    "17": {"name": "Bengkulu", "zoom": 8, "island": "sumatra", "pbfs": ["sumatra"]},
    "18": {"name": "Lampung", "zoom": 8, "island": "sumatra", "pbfs": ["sumatra"]},
    "19": {"name": "Kepulauan Bangka Belitung", "zoom": 8, "island": "sumatra", "pbfs": ["kalimantan"]},
    "21": {"name": "Kepulauan Riau", "zoom": 7, "island": "sumatra", "pbfs": ["sumatra", "kalimantan"]},
    # Bali & Nusa Tenggara (51-53)
    "51": {"name": "Bali", "zoom": 9, "island": "nusa-tenggara", "pbfs": ["nusa-tenggara"]},
    "52": {"name": "Nusa Tenggara Barat", "zoom": 8, "island": "nusa-tenggara", "pbfs": ["nusa-tenggara"]},
    "53": {"name": "Nusa Tenggara Timur", "zoom": 7, "island": "nusa-tenggara", "pbfs": ["nusa-tenggara"]},
    # Kalimantan (61-65)
    "61": {"name": "Kalimantan Barat", "zoom": 7, "island": "kalimantan", "pbfs": ["kalimantan"]},
    "62": {"name": "Kalimantan Tengah", "zoom": 7, "island": "kalimantan", "pbfs": ["kalimantan"]},
    "63": {"name": "Kalimantan Selatan", "zoom": 8, "island": "kalimantan", "pbfs": ["kalimantan"]},
    "64": {"name": "Kalimantan Timur", "zoom": 7, "island": "kalimantan", "pbfs": ["kalimantan"]},
    "65": {"name": "Kalimantan Utara", "zoom": 7, "island": "kalimantan", "pbfs": ["kalimantan"]},
    # Sulawesi (71-76)
    "71": {"name": "Sulawesi Utara", "zoom": 7, "island": "sulawesi", "pbfs": ["sulawesi"]},
    "72": {"name": "Sulawesi Tengah", "zoom": 7, "island": "sulawesi", "pbfs": ["sulawesi", "maluku"]},
    "73": {"name": "Sulawesi Selatan", "zoom": 8, "island": "sulawesi", "pbfs": ["sulawesi"]},
    "74": {"name": "Sulawesi Tenggara", "zoom": 8, "island": "sulawesi", "pbfs": ["sulawesi"]},
    "75": {"name": "Gorontalo", "zoom": 9, "island": "sulawesi", "pbfs": ["sulawesi"]},
    "76": {"name": "Sulawesi Barat", "zoom": 8, "island": "sulawesi", "pbfs": ["sulawesi", "kalimantan"]},
    # Maluku (81-82)
    "81": {"name": "Maluku", "zoom": 7, "island": "maluku", "pbfs": ["maluku"]},
    "82": {"name": "Maluku Utara", "zoom": 7, "island": "maluku", "pbfs": ["maluku"]},
    # Papua (91-96; post-2022 6-province layout via UU 14, 15, 16 & UU 29 of 2022)
    "91": {"name": "Papua", "zoom": 7, "island": "papua", "pbfs": ["papua"]},
    "92": {"name": "Papua Barat", "zoom": 7, "island": "papua", "pbfs": ["papua"]},
    "93": {"name": "Papua Selatan", "zoom": 7, "island": "papua", "pbfs": ["papua"]},
    "94": {"name": "Papua Tengah", "zoom": 7, "island": "papua", "pbfs": ["papua"]},
    "95": {"name": "Papua Pegunungan", "zoom": 7, "island": "papua", "pbfs": ["papua"]},
    "96": {"name": "Papua Barat Daya", "zoom": 7, "island": "papua", "pbfs": ["papua"]},
}

# COD-AB idn_admin2/admin3 still uses the pre-2022 2-province Papua layout (ID91 Papua Barat, ID94 Papua).
# Map every COD-AB adm2_pcode to (current_province_code, official_kemendagri_kab_code) per:
# - UU 14/2022 (Papua Selatan 93), UU 15/2022 (Papua Tengah 94), UU 16/2022 (Papua Pegunungan 95),
# - UU 29/2022 (Papua Barat Daya 96), and Kepmendagri 100.1.1-6117 Tahun 2022.
PAPUA_KABUPATEN_MAP: Dict[str, Tuple[str, str]] = {
    # 91 Papua (remaining 9 kab/kota)
    "ID9403": ("91", "91.03"),  # Jayapura
    "ID9408": ("91", "91.05"),  # Kepulauan Yapen
    "ID9409": ("91", "91.06"),  # Biak Numfor
    "ID9419": ("91", "91.10"),  # Sarmi
    "ID9420": ("91", "91.11"),  # Keerom
    "ID9426": ("91", "91.15"),  # Waropen
    "ID9427": ("91", "91.19"),  # Supiori
    "ID9428": ("91", "91.20"),  # Mamberamo Raya
    "ID9471": ("91", "91.71"),  # Kota Jayapura
    # 92 Papua Barat (remaining 7 kab)
    "ID9105": ("92", "92.02"),  # Manokwari
    "ID9101": ("92", "92.03"),  # Fakfak
    "ID9104": ("92", "92.06"),  # Teluk Bintuni
    "ID9103": ("92", "92.07"),  # Teluk Wondama
    "ID9102": ("92", "92.08"),  # Kaimana
    "ID9111": ("92", "92.11"),  # Manokwari Selatan
    "ID9112": ("92", "92.12"),  # Pegunungan Arfak
    # 93 Papua Selatan (UU 14 Tahun 2022)
    "ID9401": ("93", "93.01"),  # Merauke
    "ID9413": ("93", "93.02"),  # Boven Digoel
    "ID9414": ("93", "93.03"),  # Mappi
    "ID9415": ("93", "93.04"),  # Asmat
    # 94 Papua Tengah (UU 15 Tahun 2022)
    "ID9404": ("94", "94.01"),  # Nabire
    "ID9411": ("94", "94.02"),  # Puncak Jaya
    "ID9410": ("94", "94.03"),  # Paniai
    "ID9412": ("94", "94.04"),  # Mimika
    "ID9433": ("94", "94.05"),  # Puncak
    "ID9434": ("94", "94.06"),  # Dogiyai
    "ID9435": ("94", "94.07"),  # Intan Jaya
    "ID9436": ("94", "94.08"),  # Deiyai
    # 95 Papua Pegunungan (UU 16 Tahun 2022)
    "ID9402": ("95", "95.01"),  # Jayawijaya
    "ID9417": ("95", "95.02"),  # Pegunungan Bintang
    "ID9416": ("95", "95.03"),  # Yahukimo
    "ID9418": ("95", "95.04"),  # Tolikara
    "ID9431": ("95", "95.05"),  # Mamberamo Tengah
    "ID9432": ("95", "95.06"),  # Yalimo
    "ID9430": ("95", "95.07"),  # Lanny Jaya
    "ID9429": ("95", "95.08"),  # Nduga
    # 96 Papua Barat Daya (UU 29 Tahun 2022)
    "ID9107": ("96", "96.01"),  # Sorong
    "ID9106": ("96", "96.02"),  # Sorong Selatan
    "ID9108": ("96", "96.03"),  # Raja Ampat
    "ID9109": ("96", "96.04"),  # Tambrauw
    "ID9110": ("96", "96.05"),  # Maybrat
    "ID9171": ("96", "96.71"),  # Kota Sorong
}

POPULATION_SOURCE = "WorldPop R2025A 2024 (model estimate)"
POPULATION_VERIFICATION_STATUS = "model_estimate"
MAX_GEOJSON_BYTES = 3 * 1024 * 1024  # 3 MB
OSM_KEYS = ["amenity", "healthcare", "leisure", "landuse", "railway", "station", "highway", "shop"]
_GEOD = pyproj.Geod(ellps="WGS84")


def ensure_safe_database(db_name: Optional[str], allow_live: bool = False) -> None:
    """Refuses to run against live database 'district_profiling' unless --allow-live is set."""
    target = (db_name or "").strip()
    if target == "district_profiling" and not allow_live:
        raise RuntimeError(
            "Refusing to run against live database 'district_profiling'. "
            "Use POSTGRES_DB=district_profiling_stage or pass --allow-live."
        )


def is_non_district_pcode(adm3_pcode: str) -> bool:
    """Returns True for COD-AB non-district water/forest polygons (ending in 555, 888, or 999)."""
    s = str(adm3_pcode or "").strip()
    return len(s) >= 3 and s[-3:] in ("555", "888", "999")


def codab_pcode_to_dki_kemendagri(adm3_pcode: str) -> str:
    """
    Maps a COD-AB DKI Jakarta adm3_pcode (e.g. 'ID3171090') to the project's
    Kemendagri code format ('31.71.09'). Verified 44/44 against DKI Jakarta DB rows.
    """
    s = str(adm3_pcode or "").strip()
    if not s.startswith("ID") or len(s) != 9 or not s[2:].isdigit():
        raise ValueError(f"Invalid COD-AB adm3_pcode: '{adm3_pcode}'")
    digits = s[2:]
    if not digits.startswith("31"):
        raise ValueError(f"Expected DKI Jakarta (31) pcode, got '{adm3_pcode}'")
    if digits[6] != "0":
        raise ValueError(f"Non-zero 7th digit cannot map to 2-digit DKI suffix: '{adm3_pcode}'")
    return f"{digits[:2]}.{digits[2:4]}.{digits[4:6]}"


def codab_pcode_to_codes(adm3_pcode: str) -> Dict[str, str]:
    """
    Maps COD-AB adm3_pcode ('IDPPKKDDD') to deterministic project identifiers:
    - cod_ab_pcode: exact 'IDPPKKDDD'
    - bps_code: 7-digit 'PPKKDDD'
    - kab_code: 'PP.KK'
    - kab_bps_code: 'PPKK'
    - kemendagri_code: 'PP.KK.CC' for DKI ('31') where exact, or unambiguous 'PP.KK.DDD' for 32-36.
    """
    s = str(adm3_pcode or "").strip()
    if not s.startswith("ID") or len(s) != 9 or not s[2:].isdigit():
        raise ValueError(f"Invalid COD-AB adm3_pcode: '{adm3_pcode}'")
    digits = s[2:]
    pp, kk, ddd = digits[:2], digits[2:4], digits[4:7]
    if pp == "31" and ddd[2] == "0":
        kem_code = f"{pp}.{kk}.{ddd[:2]}"
    else:
        kem_code = f"{pp}.{kk}.{ddd}"
    return {
        "cod_ab_pcode": s,
        "bps_code": digits,
        "kab_code": f"{pp}.{kk}",
        "kab_bps_code": f"{pp}{kk}",
        "kemendagri_code": kem_code,
    }


def _truncate(val: Optional[str], max_len: int) -> Optional[str]:
    if val is None:
        return None
    s = str(val)
    return s[:max_len] if len(s) > max_len else s


def load_codab_province_districts(province_code: str, gdb_path: Path = CODAB_GDB_PATH) -> List[Dict[str, Any]]:
    """Reads admin level 3 (kecamatan) polygons for `province_code` from COD-AB FileGDB."""
    if not gdb_path.exists():
        raise FileNotFoundError(f"COD-AB FileGDB not found at {gdb_path}")

    is_papua_split = str(province_code) in ("91", "92", "93", "94", "95", "96")
    if is_papua_split:
        target_adm2s = sorted(k for k, (prov, _) in PAPUA_KABUPATEN_MAP.items() if prov == str(province_code))
        in_clause = ", ".join(f"'{k}'" for k in target_adm2s)
        where_clause = f"adm2_pcode IN ({in_clause})"
    else:
        adm1_pcode = f"ID{province_code}"
        where_clause = f"adm1_pcode = '{adm1_pcode}'"

    meta, _, geom_wkb, field_data = pyogrio.raw.read(
        gdb_path,
        layer="idn_admin3",
        where=where_clause,
    )
    fields = list(meta["fields"])
    n_rows = len(field_data[0]) if field_data else 0

    districts: List[Dict[str, Any]] = []
    excluded_non_district = []

    for i in range(n_rows):
        row = {fields[j]: field_data[j][i] for j in range(len(fields))}
        pcode = str(row["adm3_pcode"]).strip()
        if is_non_district_pcode(pcode):
            excluded_non_district.append((pcode, row.get("adm3_name")))
            continue

        geom = from_wkb(geom_wkb[i])
        if not geom.is_valid:
            geom = geom.buffer(0)

        codes = codab_pcode_to_codes(pcode)
        if is_papua_split:
            adm2_pcode = str(row["adm2_pcode"]).strip()
            _, official_kab_code = PAPUA_KABUPATEN_MAP[adm2_pcode]
            ddd = pcode[6:9]
            codes["kab_code"] = official_kab_code
            codes["kemendagri_code"] = f"{official_kab_code}.{ddd}"

        geod_area_m2, _ = _GEOD.geometry_area_perimeter(geom)
        area_km2 = round(abs(geod_area_m2) / 1_000_000.0, 4)

        districts.append({
            "cod_ab_pcode": codes["cod_ab_pcode"],
            "kemendagri_code": codes["kemendagri_code"],
            "bps_code": codes["bps_code"],
            "kab_code": codes["kab_code"],
            "kab_bps_code": codes["kab_bps_code"],
            "kab_name": str(row.get("adm2_name") or "").strip(),
            "name": str(row.get("adm3_name") or "").strip(),
            "area_km2": area_km2,
            "codab_area_sqkm": float(row.get("area_sqkm") or area_km2),
            "geom": geom,
            "wkb": geom.wkb,
        })

    if excluded_non_district:
        logger.info(f"Excluded {len(excluded_non_district)} non-district polygons in province {province_code}: {excluded_non_district}")
    districts.sort(key=lambda d: d["kemendagri_code"])
    return districts


def compute_worldpop_zonal_sums(districts: List[Dict[str, Any]], tif_path: Path = WORLDPOP_TIF_PATH) -> None:
    """
    Populates `population` and `density_per_km2` on each district dict using
    WorldPop Global2 constrained 100m 2024 zonal sum inside the polygon.
    Method: rasterio.mask.mask(..., crop=True, filled=False, all_touched=False),
    with fallback to all_touched=True only when 0 valid pixels fall inside a polygon.
    """
    if not tif_path.exists():
        raise FileNotFoundError(f"WorldPop GeoTIFF not found at {tif_path}")

    with rasterio.open(tif_path) as src:
        nodata = src.nodata
        for d in districts:
            geom = d["geom"]
            out_img, _ = rasterio.mask.mask(src, [geom], crop=True, filled=False, all_touched=False)
            valid = out_img[0].compressed()
            if nodata is not None:
                valid = valid[valid != nodata]
            valid = valid[np.isfinite(valid) & (valid > 0)]
            pop_val = float(valid.sum()) if len(valid) > 0 else 0.0

            if pop_val == 0.0:
                out_img2, _ = rasterio.mask.mask(src, [geom], crop=True, filled=False, all_touched=True)
                v2 = out_img2[0].compressed()
                if nodata is not None:
                    v2 = v2[v2 != nodata]
                v2 = v2[np.isfinite(v2) & (v2 > 0)]
                pop_val = float(v2.sum()) if len(v2) > 0 else 0.0

            pop_int = int(round(pop_val))
            d["population"] = pop_int
            d["density_per_km2"] = round(pop_int / d["area_km2"], 2) if d["area_km2"] > 0 else 0.0


def extract_facilities_from_pbf(
    pbf_path: Path,
    cache_path: Optional[Path] = None,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """
    Two-pass pyosmium extractor from a Geofabrik `.osm.pbf` file using
    matching_query_groups + classify_osm_element_auto from pipeline/osm_extractor.py.
    """
    if use_cache and cache_path and cache_path.exists():
        if cache_path.stat().st_mtime >= pbf_path.stat().st_mtime:
            logger.info(f"Loading cached extracted OSM facilities from {cache_path}...")
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)

    if not pbf_path.exists():
        raise FileNotFoundError(f"Geofabrik PBF not found at {pbf_path}")

    t0 = time.time()
    snap_date = time.strftime("%Y%m%d", time.gmtime(pbf_path.stat().st_mtime))
    logger.info(f"Extracting OSM facilities from {pbf_path} (snapshot {snap_date})...")

    nodes: List[Dict[str, Any]] = []
    ways: List[Tuple[int, Dict[str, str], List[int]]] = []
    tracker = osmium.IdTracker()

    fp = (
        osmium.FileProcessor(str(pbf_path))
        .with_filter(osmium.filter.EntityFilter(osmium.osm.NODE | osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter(*OSM_KEYS))
    )
    for obj in fp:
        tags = {t.k: t.v for t in obj.tags}
        if obj.is_node():
            if not obj.location.valid():
                continue
            if matching_query_groups(tags, el_type="node"):
                el = {
                    "type": "node",
                    "id": obj.id,
                    "lat": obj.location.lat,
                    "lon": obj.location.lon,
                    "tags": tags,
                }
                item = classify_osm_element_auto(el, snapshot_date=snap_date)
                if item:
                    nodes.append(item)
        elif obj.is_way():
            if matching_query_groups(tags, el_type="way"):
                nrefs = [n.ref for n in obj.nodes]
                if nrefs:
                    ways.append((obj.id, tags, nrefs))
                    tracker.add_references(obj)

    logger.info(f"Pass 1 complete in {time.time() - t0:.1f}s: {len(nodes)} nodes, {len(ways)} ways.")

    node_coords: Dict[int, Tuple[float, float]] = {}
    fp2 = (
        osmium.FileProcessor(str(pbf_path))
        .with_filter(osmium.filter.EntityFilter(osmium.osm.NODE))
        .with_filter(tracker.id_filter())
    )
    for obj in fp2:
        if obj.location.valid():
            node_coords[obj.id] = (obj.location.lon, obj.location.lat)

    way_items: List[Dict[str, Any]] = []
    for wid, tags, nrefs in ways:
        pts = [node_coords[r] for r in nrefs if r in node_coords]
        if not pts:
            continue
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        el = {
            "type": "way",
            "id": wid,
            "center": {
                "lat": (min(lats) + max(lats)) / 2.0,
                "lon": (min(lons) + max(lons)) / 2.0,
            },
            "tags": tags,
        }
        item = classify_osm_element_auto(el, snapshot_date=snap_date)
        if item:
            way_items.append(item)

    all_items = nodes + way_items
    logger.info(f"Extracted {len(all_items):,} total classified facilities from {pbf_path.name} in {time.time() - t0:.1f}s.")

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(all_items, f, ensure_ascii=False)
        logger.info(f"Cached extracted facilities to {cache_path}.")

    return all_items


def extract_all_java_facilities_from_pbf(
    pbf_path: Path = JAVA_PBF_PATH,
    cache_path: Optional[Path] = JAVA_FACILITIES_CACHE,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """Backwards-compatible wrapper for extracting Java OSM facilities."""
    return extract_facilities_from_pbf(pbf_path=pbf_path, cache_path=cache_path, use_cache=use_cache)


def filter_and_dedup_facilities_for_province(
    all_facilities: List[Dict[str, Any]],
    districts: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Filters Java facilities to those contained in the province's kecamatan polygons,
    then runs deduplicate_facilities() from pipeline/osm_extractor.py.
    """
    geoms = [d["geom"] for d in districts]
    tree = STRtree(geoms)

    # Rough bbox pre-filter for speed
    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    maxx = max(g.bounds[2] for g in geoms)
    maxy = max(g.bounds[3] for g in geoms)

    inside: List[Dict[str, Any]] = []
    seen_sids = set()
    for item in all_facilities:
        sid = item["source_id"]
        if sid in seen_sids:
            continue
        coords = item["coordinates"]["coordinates"]
        lon, lat = coords[0], coords[1]
        if lon < minx or lon > maxx or lat < miny or lat > maxy:
            continue
        pt = Point(lon, lat)
        cand_idxs = tree.query(pt)
        matched = False
        for idx in cand_idxs:
            if geoms[idx].contains(pt):
                matched = True
                break
        if matched:
            seen_sids.add(sid)
            inside.append(item)

    deduped, removed = deduplicate_facilities(inside)
    return deduped, removed


def simplify_geojson_under_limit(
    districts: List[Dict[str, Any]],
    province_code: str,
    province_name: str,
    out_path: Path,
    max_bytes: int = MAX_GEOJSON_BYTES,
) -> Tuple[int, float]:
    """
    Writes simplified GeoJSON for `districts` under `max_bytes`, keeping all properties
    expected by the frontend (kemendagri_code, bps_code, name, city_name, population,
    area_km2, density_per_km2, plus cod_ab_pcode).
    """
    tolerances = [0.0002, 0.0004, 0.0008, 0.0012, 0.0018, 0.0025, 0.004, 0.006, 0.008, 0.012]

    def round_coords(obj: Any, precision: int = 5) -> Any:
        if isinstance(obj, list):
            if obj and isinstance(obj[0], (int, float)):
                return [round(v, precision) for v in obj]
            return [round_coords(x, precision) for x in obj]
        return obj

    def build_payload(tol: float, precision: int) -> bytes:
        features = []
        for d in districts:
            simp = d["geom"].simplify(tol, preserve_topology=True)
            if simp.is_empty:
                simp = d["geom"]
            geom_dict = mapping(simp)
            geom_dict["coordinates"] = round_coords(geom_dict["coordinates"], precision)
            features.append({
                "type": "Feature",
                "properties": {
                    "kemendagri_code": d["kemendagri_code"],
                    "bps_code": d["bps_code"],
                    "cod_ab_pcode": d["cod_ab_pcode"],
                    "name": d["name"],
                    "city_name": d["kab_name"],
                    "population": d["population"],
                    "area_km2": d["area_km2"],
                    "density_per_km2": d["density_per_km2"],
                },
                "geometry": geom_dict,
            })

        fc = {
            "type": "FeatureCollection",
            "name": f"{province_code}_kecamatan",
            "features": features,
        }
        return json.dumps(fc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    chosen_tol = tolerances[-1]
    chosen_bytes = 0
    payload = b""

    for tol in tolerances:
        payload = build_payload(tol, precision=5)
        chosen_tol = tol
        chosen_bytes = len(payload)
        if chosen_bytes <= max_bytes:
            with open(out_path, "wb") as f:
                f.write(payload)
            return chosen_bytes, chosen_tol

    # Fallback with 4-decimal coordinate precision if still above max_bytes
    for tol in tolerances[-4:]:
        payload = build_payload(tol, precision=4)
        chosen_tol = tol
        chosen_bytes = len(payload)
        if chosen_bytes <= max_bytes:
            with open(out_path, "wb") as f:
                f.write(payload)
            return chosen_bytes, chosen_tol

    with open(out_path, "wb") as f:
        f.write(payload)
    return chosen_bytes, chosen_tol


def resolve_pbf_specs_for_province(
    province_code: str,
    pbf_override: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Returns list of PBF source descriptors for `province_code` (or an explicit `--pbf` override)."""
    if pbf_override:
        key = str(pbf_override).strip().lower()
        if key in PBF_SOURCES:
            return [PBF_SOURCES[key]]
        p = Path(pbf_override)
        stem = p.name.replace(".osm.pbf", "").replace(".pbf", "")
        return [{
            "path": p,
            "cache": RAW_DATA_DIR / f"{stem}_facilities_raw_classified.json",
            "url": f"file://{p}",
            "source": f"OpenStreetMap contributors via {p.name} (ODbL)",
        }]
    pbf_keys = SUPPORTED_PROVINCES[province_code].get("pbfs", ["java"])
    return [PBF_SOURCES[k] for k in pbf_keys]


def write_region_manifest(
    province_code: str,
    province_name: str,
    districts: List[Dict[str, Any]],
    snapshot_date_iso: str,
    amenities_meta: Optional[Dict[str, Any]] = None,
) -> Path:
    """Writes pipeline/data/regions/<code>.json following the 31.json template with status='Staging'."""
    REGIONS_DIR.mkdir(parents=True, exist_ok=True)
    union_geom = unary_union([d["geom"] for d in districts])
    minx, miny, maxx, maxy = [round(v, 4) for v in union_geom.bounds]
    c = union_geom.centroid
    center = [round(c.y, 4), round(c.x, 4)]
    utm_srid = calculate_utm_srid(c.x, c.y)
    utm_zone_num = calculate_utm_zone(c.x)
    utm_zone = f"{utm_zone_num}{'S' if c.y < 0 else 'N'}"

    default_amenities = {
        "source": "OpenStreetMap contributors via Geofabrik Java PBF (ODbL)",
        "url": "https://download.geofabrik.de/asia/indonesia/java-latest.osm.pbf",
        "local_path": str(JAVA_PBF_PATH),
        "licence": "ODbL 1.0",
        "snapshot_date": snapshot_date_iso,
        "verification_status": "verified_osm_snapshot",
    }

    manifest = {
        "province_code": province_code,
        "province_name": province_name,
        "has_data": True,
        "status": "Staging",
        "center": center,
        "zoom": SUPPORTED_PROVINCES[province_code]["zoom"],
        "bbox": [minx, miny, maxx, maxy],
        "utm_srid": utm_srid,
        "utm_zone": utm_zone,
        "total_districts": len(districts),
        "boundaries": {
            "source": "HDX COD-AB Indonesia (BPS/BIG)",
            "url": "https://data.humdata.org/dataset/cod-ab-idn",
            "local_path": f"frontend/data/boundaries/{province_code}_kecamatan.geojson",
            "licence": "CC BY-IGO",
            "total_districts": len(districts),
            "verification_status": "verified",
        },
        "demographics": {
            "source": POPULATION_SOURCE,
            "url": "https://hub.worldpop.org/rest/data/pop/G2_CN_POP_R25A_100m?iso3=IDN",
            "local_path": str(WORLDPOP_TIF_PATH),
            "licence": "CC BY 4.0",
            "snapshot_date": "2024",
            "verification_status": POPULATION_VERIFICATION_STATUS,
        },
        "amenities": amenities_meta or default_amenities,
    }
    manifest_path = REGIONS_DIR / f"{province_code}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest_path


def ensure_region_columns(cur) -> None:
    """Idempotently ensures multi-region provenance and coverage columns exist."""
    cur.execute("ALTER TABLE kecamatan ADD COLUMN IF NOT EXISTS cod_ab_pcode VARCHAR(20);")
    cur.execute("ALTER TABLE kecamatan ADD COLUMN IF NOT EXISTS population_source VARCHAR(150);")
    cur.execute("ALTER TABLE kecamatan ADD COLUMN IF NOT EXISTS population_verification_status VARCHAR(50);")
    cur.execute("ALTER TABLE district_compliance_scores ADD COLUMN IF NOT EXISTS coverage JSONB DEFAULT NULL;")


def load_province_to_db(
    province_code: str,
    districts: List[Dict[str, Any]],
    facilities: List[Dict[str, Any]],
    db_config: Dict[str, Any],
    redis_host: str,
    redis_port: int,
    redis_db: int,
) -> Dict[str, Any]:
    """Idempotently loads boundaries, population, facilities, and scores for `province_code`."""
    prov_name = SUPPORTED_PROVINCES[province_code]["name"]
    conn = psycopg2.connect(**db_config)
    try:
        with conn.cursor() as cur:
            ensure_region_columns(cur)

            # 1. Province
            cur.execute(
                """
                INSERT INTO provinces (kemendagri_code, name)
                VALUES (%s, %s)
                ON CONFLICT (kemendagri_code) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
                """,
                (province_code, f"Provinsi {prov_name}"),
            )
            prov_id = cur.fetchone()[0]

            # 2. Kabupaten / Kota
            kabs: Dict[str, Tuple[str, str]] = {}
            for d in districts:
                kabs[d["kab_code"]] = (d["kab_bps_code"], d["kab_name"])

            kab_id_map: Dict[str, str] = {}
            for kab_code, (kab_bps, kab_name) in sorted(kabs.items()):
                cur.execute(
                    """
                    INSERT INTO kabupaten_kota (province_id, kemendagri_code, bps_code, name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (kemendagri_code) DO UPDATE SET
                        province_id = EXCLUDED.province_id,
                        bps_code = EXCLUDED.bps_code,
                        name = EXCLUDED.name
                    RETURNING id;
                    """,
                    (prov_id, kab_code, kab_bps, _truncate(kab_name, 100)),
                )
                kab_id_map[kab_code] = cur.fetchone()[0]

            # 3. Kecamatan (utm_srid=NULL triggers compute_utm_srid() in trg_sync_utm_geometry)
            for d in districts:
                cur.execute(
                    """
                    INSERT INTO kecamatan (
                        kabupaten_kota_id, kemendagri_code, bps_code, cod_ab_pcode,
                        name, population, area_km2, density_per_km2,
                        population_source, population_verification_status,
                        boundary, utm_srid
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromWKB(%s), 4326)), 3)),
                        NULL
                    )
                    ON CONFLICT (kemendagri_code) DO UPDATE SET
                        kabupaten_kota_id = EXCLUDED.kabupaten_kota_id,
                        bps_code = EXCLUDED.bps_code,
                        cod_ab_pcode = EXCLUDED.cod_ab_pcode,
                        name = EXCLUDED.name,
                        population = EXCLUDED.population,
                        area_km2 = EXCLUDED.area_km2,
                        density_per_km2 = EXCLUDED.density_per_km2,
                        population_source = EXCLUDED.population_source,
                        population_verification_status = EXCLUDED.population_verification_status,
                        boundary = EXCLUDED.boundary,
                        utm_srid = NULL,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        kab_id_map[d["kab_code"]],
                        d["kemendagri_code"],
                        d["bps_code"],
                        d["cod_ab_pcode"],
                        _truncate(d["name"], 100),
                        d["population"],
                        d["area_km2"],
                        d["density_per_km2"],
                        POPULATION_SOURCE,
                        POPULATION_VERIFICATION_STATUS,
                        psycopg2.Binary(d["wkb"]),
                    ),
                )

            conn.commit()
            logger.info(f"[{province_code}] Upserted {len(kabs)} kabupaten/kota and {len(districts)} kecamatan.")

            # 4. Facilities: deactivate previous facilities in THIS province only (never touch DKI '31' or other provinces)
            cur.execute(
                """
                UPDATE public_facilities f
                SET is_active = FALSE
                FROM kecamatan k
                JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                JOIN provinces p ON p.id = c.province_id
                WHERE f.kecamatan_id = k.id
                  AND p.kemendagri_code = %s
                  AND f.source = 'osm';
                """,
                (province_code,),
            )

            # Exclude any source_id already owned by an active facility in another province (especially DKI '31')
            cur.execute(
                """
                SELECT f.source_id
                FROM public_facilities f
                JOIN kecamatan k ON k.id = f.kecamatan_id
                JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                JOIN provinces p ON p.id = c.province_id
                WHERE p.kemendagri_code != %s AND f.is_active = TRUE AND f.source = 'osm';
                """,
                (province_code,),
            )
            other_province_sids = {r[0] for r in cur.fetchall()}

            filtered_facs = [f for f in facilities if f["source_id"] not in other_province_sids]
            skipped_border = len(facilities) - len(filtered_facs)
            if skipped_border:
                logger.info(f"[{province_code}] Skipped {skipped_border} border facilities already owned by another loaded province.")

            fac_tuples = []
            for item in filtered_facs:
                coords = item["coordinates"]["coordinates"]
                fac_tuples.append((
                    "osm",
                    _truncate(item["source_id"], 100),
                    item.get("osm_id"),
                    _truncate(item.get("name"), 255),
                    _truncate(item["pillar"], 50),
                    _truncate(item["category"], 50),
                    _truncate(item["facility_type"], 100),
                    item.get("address"),
                    _truncate(item.get("contact"), 100),
                    _truncate(item.get("website"), 255),
                    item.get("capacity", 0),
                    item.get("area_m2"),
                    coords[0],
                    coords[1],
                    json.dumps(item.get("metadata", {})),
                    True,
                    bool(item.get("is_verified", False)),
                ))

            if fac_tuples:
                upsert_sql = f"""
                    INSERT INTO public_facilities (
                        source, source_id, osm_id, name, pillar, category,
                        facility_type, address, contact, website, capacity,
                        area_m2, coordinates, metadata, is_active, is_verified, last_synced_at
                    )
                    VALUES %s
                    ON CONFLICT (source, source_id) DO UPDATE SET
                        osm_id = EXCLUDED.osm_id,
                        name = EXCLUDED.name,
                        pillar = EXCLUDED.pillar,
                        category = EXCLUDED.category,
                        facility_type = EXCLUDED.facility_type,
                        address = EXCLUDED.address,
                        contact = EXCLUDED.contact,
                        website = EXCLUDED.website,
                        capacity = EXCLUDED.capacity,
                        area_m2 = EXCLUDED.area_m2,
                        coordinates = EXCLUDED.coordinates,
                        utm_srid = NULL,
                        metadata = EXCLUDED.metadata,
                        is_active = EXCLUDED.is_active,
                        is_verified = EXCLUDED.is_verified,
                        last_synced_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE public_facilities.kecamatan_id IS NULL
                       OR public_facilities.kecamatan_id IN (
                           SELECT k.id FROM kecamatan k
                           JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                           JOIN provinces p ON p.id = c.province_id
                           WHERE p.kemendagri_code = '{province_code}'
                       );
                """
                execute_values(
                    cur,
                    upsert_sql,
                    fac_tuples,
                    template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s::jsonb, %s, %s, CURRENT_TIMESTAMP)",
                    page_size=1000,
                )

            # Link facilities inside THIS province's polygons to their kecamatan_id
            batch_sids = [t[1] for t in fac_tuples]
            if batch_sids:
                cur.execute(
                    """
                    UPDATE public_facilities f
                    SET kecamatan_id = k.id
                    FROM kecamatan k
                    JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                    JOIN provinces p ON p.id = c.province_id
                    WHERE p.kemendagri_code = %s
                      AND f.source = 'osm'
                      AND f.source_id = ANY(%s)
                      AND ST_Contains(k.boundary, f.coordinates);
                    """,
                    (province_code, batch_sids),
                )
                # Any facility from batch that did not match ST_Contains (e.g. exact boundary point) is deactivated
                cur.execute(
                    """
                    UPDATE public_facilities
                    SET is_active = FALSE
                    WHERE source = 'osm'
                      AND source_id = ANY(%s)
                      AND kecamatan_id IS NULL;
                    """,
                    (batch_sids,),
                )

            conn.commit()

        score_res = compute_province_compliance_scores(
            conn=conn,
            province_code=province_code,
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
        )
        score_res["districts_loaded"] = len(districts)
        return score_res
    finally:
        conn.close()


def compute_province_compliance_scores(
    conn,
    province_code: str,
    redis_host: str,
    redis_port: int,
    redis_db: int,
) -> Dict[str, Any]:
    """
    Computes compliance scores and OSM coverage flags for `province_code` from DB state
    (without mutating regulatory_standards) and refreshes Redis DB scorecard cache.
    """
    with conn.cursor() as cur:
        ensure_region_columns(cur)

        cur.execute(
            """
            SELECT k.id, k.name, k.kemendagri_code, k.population, k.area_km2
            FROM kecamatan k
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = %s
            ORDER BY k.kemendagri_code;
            """,
            (province_code,),
        )
        db_districts = cur.fetchall()
        province_kec_count = max(1, len(db_districts))

        cur.execute(
            """
            SELECT f.facility_type, COUNT(*)
            FROM public_facilities f
            JOIN kecamatan k ON k.id = f.kecamatan_id
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE f.is_active = TRUE AND p.kemendagri_code = %s
            GROUP BY f.facility_type;
            """,
            (province_code,),
        )
        prov_counts = dict(cur.fetchall())

        cur.execute(
            """
            SELECT facility_type, pillar, population_threshold, service_radius_meters, scored, source
            FROM regulatory_standards
            WHERE province_code IS NULL OR province_code = %s
            ORDER BY pillar, facility_type;
            """,
            (province_code,),
        )
        standards = cur.fetchall()

        availability_map: Dict[str, Tuple[str, str]] = {}
        for std in standards:
            ftype, pillar, threshold, radius, scored, source = std
            cnt = prov_counts.get(ftype, 0)
            spec = STANDARDS_AVAILABILITY_SPEC.get(ftype, {})
            conf = spec.get("confidence", "Medium")
            is_not_avail = spec.get("is_not_available_from_osm", False)
            avail, reason = evaluate_availability(
                ftype,
                cnt,
                conf,
                is_not_avail,
                min_records_threshold=province_kec_count,
            )
            availability_map[ftype] = (avail, reason)

        # Preload facility counts per district in 1 query for speed
        cur.execute(
            """
            SELECT f.kecamatan_id, f.facility_type, COUNT(*)
            FROM public_facilities f
            JOIN kecamatan k ON k.id = f.kecamatan_id
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = %s AND f.is_active = TRUE
            GROUP BY f.kecamatan_id, f.facility_type;
            """,
            (province_code,),
        )
        dist_fac_counts: Dict[str, Dict[str, int]] = {}
        for kec_id, ftype, cnt in cur.fetchall():
            dist_fac_counts.setdefault(str(kec_id), {})[ftype] = cnt

        scored_count = 0
        gated_count = 0
        for dist_id, name, code, pop, area in db_districts:
            if pop is None or pop <= 0:
                logger.warning(f"[{province_code}] Kecamatan {name} ({code}) has population={pop}; skipping scoring.")
                continue
            fac_counts = dist_fac_counts.get(str(dist_id), {})
            res = build_district_metrics_and_scores(pop, fac_counts, standards, availability_map)
            metrics_detail = res["metrics_detail"]
            scores_res = res["scores_res"]
            p_scores = scores_res["pillar_scores"]
            composite = scores_res["composite_score"]
            comp_note = scores_res["composite_note"]
            coverage_obj = res["coverage"]
            if res["local_gated"]:
                gated_count += 1

            cur.execute(
                """
                INSERT INTO district_compliance_scores (
                    district_id, health_score, education_score, livability_score,
                    mobility_score, composite_livability_score, composite_note,
                    unserved_area_km2, metrics_payload, coverage, calculated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (district_id) DO UPDATE SET
                    health_score = EXCLUDED.health_score,
                    education_score = EXCLUDED.education_score,
                    livability_score = EXCLUDED.livability_score,
                    mobility_score = EXCLUDED.mobility_score,
                    composite_livability_score = EXCLUDED.composite_livability_score,
                    composite_note = EXCLUDED.composite_note,
                    metrics_payload = EXCLUDED.metrics_payload,
                    coverage = EXCLUDED.coverage,
                    calculated_at = CURRENT_TIMESTAMP;
                """,
                (
                    dist_id,
                    p_scores["lifeline_health"]["score"],
                    p_scores["education"]["score"],
                    p_scores["urban_livability"]["score"],
                    p_scores["mobility_connectivity"]["score"],
                    composite,
                    comp_note,
                    0.0,
                    json.dumps(metrics_detail),
                    json.dumps(coverage_obj),
                ),
            )
            scored_count += 1

        conn.commit()

        # Cache province-scoped scorecards in Redis (do NOT overwrite DKI's legacy key)
        try:
            r_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
            if r_client.ping():
                cur.execute(
                    """
                    SELECT k.kemendagri_code, k.name, k.population, k.area_km2,
                           s.health_score, s.education_score, s.livability_score,
                           s.mobility_score, s.composite_livability_score, s.composite_note,
                           s.metrics_payload, s.coverage
                    FROM kecamatan k
                    JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
                    JOIN provinces p ON p.id = c.province_id
                    LEFT JOIN district_compliance_scores s ON s.district_id = k.id
                    WHERE p.kemendagri_code = %s
                    ORDER BY k.kemendagri_code;
                    """,
                    (province_code,),
                )
                scorecards = {}
                for r in cur.fetchall():
                    code, name, pop, area, h, e, l, m, comp, note, payload, cov = r
                    entry = {
                        "kemendagri_code": code,
                        "name": name,
                        "population": pop,
                        "area_km2": float(area),
                        "health_score": float(h) if h is not None else None,
                        "education_score": float(e) if e is not None else None,
                        "livability_score": float(l) if l is not None else None,
                        "mobility_score": float(m) if m is not None else None,
                        "composite_livability_score": float(comp) if comp is not None else None,
                        "composite_note": note,
                        "metrics": payload,
                    }
                    if cov is not None:
                        entry["coverage"] = cov
                    scorecards[code] = entry
                r_client.setex(f"cache:compliance:scores:{province_code}", 86400, json.dumps(scorecards))
                logger.info(
                    f"[{province_code}] Cached {len(scorecards)} scorecards to Redis db={redis_db} "
                    f"key 'cache:compliance:scores:{province_code}' (gated={gated_count})."
                )
        except Exception as e:
            logger.warning(f"[{province_code}] Redis cache warning: {e}")

        cur.execute(
            """
            SELECT COUNT(*)
            FROM public_facilities f
            JOIN kecamatan k ON k.id = f.kecamatan_id
            JOIN kabupaten_kota c ON c.id = k.kabupaten_kota_id
            JOIN provinces p ON p.id = c.province_id
            WHERE p.kemendagri_code = %s AND f.is_active = TRUE;
            """,
            (province_code,),
        )
        active_facs = cur.fetchone()[0]

    return {
        "province_code": province_code,
        "districts_count": len(db_districts),
        "active_facilities": active_facs,
        "scored_districts": scored_count,
        "gated_districts": gated_count,
        "availability_map": availability_map,
    }


def _get_runtime_db_redis_config(allow_live: bool = False) -> Tuple[str, Dict[str, Any], str, int, int]:
    db_name = os.getenv("POSTGRES_DB", "district_profiling")
    ensure_safe_database(db_name, allow_live=allow_live)

    db_host = os.getenv("POSTGRES_HOST") or "127.0.0.1"
    if db_host == "localhost":
        db_host = "127.0.0.1"
    db_config = {
        "dbname": db_name,
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres_spatial_dev"),
        "host": db_host,
        "port": int(os.getenv("POSTGRES_PORT", 5432)),
    }
    redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
    if redis_host == "localhost":
        redis_host = "127.0.0.1"
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_db = int(os.getenv("REDIS_DB", "0"))
    return db_name, db_config, redis_host, redis_port, redis_db


def rescore_province(province_code: str, allow_live: bool = False) -> Dict[str, Any]:
    """Re-computes compliance scores and OSM coverage flags from existing DB rows for `province_code`."""
    province_code = str(province_code).strip()
    if province_code not in SUPPORTED_PROVINCES:
        raise ValueError(
            f"Unsupported province '{province_code}'. Supported Java staging provinces: {sorted(SUPPORTED_PROVINCES.keys())}"
        )
    db_name, db_config, redis_host, redis_port, redis_db = _get_runtime_db_redis_config(allow_live=allow_live)
    logger.info(f"=== Re-scoring province {province_code} | db={db_name} | redis_db={redis_db} ===")
    conn = psycopg2.connect(**db_config)
    try:
        return compute_province_compliance_scores(
            conn=conn,
            province_code=province_code,
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
        )
    finally:
        conn.close()


def run_province(
    province_code: str,
    dry_run: bool = False,
    allow_live: bool = False,
    use_pbf_cache: bool = True,
    pbf_override: Optional[str] = None,
) -> Dict[str, Any]:
    province_code = str(province_code).strip()
    if province_code not in SUPPORTED_PROVINCES:
        raise ValueError(
            f"Unsupported province '{province_code}'. Supported staging provinces: {sorted(SUPPORTED_PROVINCES.keys())}"
        )

    db_name, db_config, redis_host, redis_port, redis_db = _get_runtime_db_redis_config(allow_live=allow_live)

    prov_name = SUPPORTED_PROVINCES[province_code]["name"]
    logger.info(f"=== Loading province {province_code} ({prov_name}) | dry_run={dry_run} | db={db_name} | redis_db={redis_db} ===")

    districts = load_codab_province_districts(province_code)
    compute_worldpop_zonal_sums(districts)
    total_pop = sum(d["population"] for d in districts)
    logger.info(f"[{province_code}] Loaded {len(districts)} districts, WorldPop 2024 total={total_pop:,}")

    pbf_specs = resolve_pbf_specs_for_province(province_code, pbf_override=pbf_override)
    all_facilities: List[Dict[str, Any]] = []
    for spec in pbf_specs:
        all_facilities.extend(
            extract_facilities_from_pbf(
                pbf_path=spec["path"],
                cache_path=spec["cache"],
                use_cache=use_pbf_cache,
            )
        )
    prov_facilities, dedup_removed = filter_and_dedup_facilities_for_province(all_facilities, districts)
    logger.info(
        f"[{province_code}] Filtered {len(prov_facilities):,} deduplicated facilities "
        f"(removed {sum(dedup_removed.values()):,} duplicates)."
    )

    if dry_run:
        return {
            "province_code": province_code,
            "province_name": prov_name,
            "dry_run": True,
            "districts": len(districts),
            "population_total": total_pop,
            "facilities": len(prov_facilities),
            "pbfs": [str(s["path"]) for s in pbf_specs],
        }

    db_res = load_province_to_db(
        province_code=province_code,
        districts=districts,
        facilities=prov_facilities,
        db_config=db_config,
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
    )

    geojson_path = FRONTEND_BOUNDARIES_DIR / f"{province_code}_kecamatan.geojson"
    gj_bytes, gj_tol = simplify_geojson_under_limit(
        districts=districts,
        province_code=province_code,
        province_name=prov_name,
        out_path=geojson_path,
    )
    logger.info(f"[{province_code}] Wrote {geojson_path} ({gj_bytes:,} bytes, tol={gj_tol}).")

    primary_pbf = pbf_specs[0]
    snap_iso = time.strftime("%Y-%m-%d", time.gmtime(primary_pbf["path"].stat().st_mtime))
    if len(pbf_specs) == 1:
        amenities_meta = {
            "source": primary_pbf["source"],
            "url": primary_pbf["url"],
            "local_path": str(primary_pbf["path"]),
            "licence": "ODbL 1.0",
            "snapshot_date": snap_iso,
            "verification_status": "verified_osm_snapshot",
        }
    else:
        labels = " & ".join(s.get("label", s["path"].name) for s in pbf_specs)
        amenities_meta = {
            "source": f"OpenStreetMap contributors via Geofabrik {labels} PBFs (ODbL)",
            "url": primary_pbf["url"],
            "local_path": ", ".join(str(s["path"]) for s in pbf_specs),
            "licence": "ODbL 1.0",
            "snapshot_date": snap_iso,
            "verification_status": "verified_osm_snapshot",
        }

    manifest_path = write_region_manifest(
        province_code=province_code,
        province_name=prov_name,
        districts=districts,
        snapshot_date_iso=snap_iso,
        amenities_meta=amenities_meta,
    )
    logger.info(f"[{province_code}] Wrote region manifest {manifest_path}.")

    return {
        **db_res,
        "province_name": prov_name,
        "population_total": total_pop,
        "geojson_bytes": gj_bytes,
        "geojson_tol": gj_tol,
        "manifest_path": str(manifest_path),
    }


def main():
    parser = argparse.ArgumentParser(description="Load province data into staging DB")
    parser.add_argument(
        "--province",
        required=True,
        help="Province code(s): e.g. 11, 34, 51, 61, 71, 81, 91, 'sumatra', 'java', 'nusa-tenggara', 'kalimantan', 'sulawesi', 'maluku', 'papua', 'all', or comma-separated",
    )
    parser.add_argument(
        "--pbf",
        default=None,
        help="Optional Geofabrik PBF path or key ('java', 'sumatra', 'kalimantan', 'sulawesi', 'nusa-tenggara', 'maluku', 'papua') overriding province default",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute and log counts without writing to DB or files")
    parser.add_argument("--rescore-only", action="store_true", help="Re-compute compliance scores from existing DB records only")
    parser.add_argument("--allow-live", action="store_true", help="Allow running against live district_profiling DB")
    parser.add_argument("--no-pbf-cache", action="store_true", help="Force re-reading PBF instead of cache")
    args = parser.parse_args()

    raw_prov = str(args.province).strip().lower()
    if raw_prov == "all":
        codes = sorted(SUPPORTED_PROVINCES.keys())
    elif raw_prov in ("java", "sumatra", "nusa-tenggara", "kalimantan", "sulawesi", "maluku", "papua"):
        codes = sorted(k for k, v in SUPPORTED_PROVINCES.items() if v.get("island") == raw_prov)
    else:
        codes = [c.strip() for c in str(args.province).split(",") if c.strip()]

    for code in codes:
        if args.rescore_only:
            res = rescore_province(province_code=code, allow_live=args.allow_live)
        else:
            res = run_province(
                province_code=code,
                dry_run=args.dry_run,
                allow_live=args.allow_live,
                use_pbf_cache=not args.no_pbf_cache,
                pbf_override=args.pbf,
            )
        logger.info(f"SUMMARY {code}: {res}")


if __name__ == "__main__":
    main()
