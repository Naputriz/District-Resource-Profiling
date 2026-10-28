"""
Fetch and Normalize 44 Kecamatan DKI Jakarta GeoJSON boundaries.
Attempts multiple reliable sources (GitHub GeoJSON repositories, Overpass API),
merges with BPS demographic data, and stores normalized GeoJSON locally.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from shapely.geometry import shape, mapping, MultiPolygon, Polygon
from shapely.ops import unary_union

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
BOUNDARIES_DIR = DATA_DIR / "boundaries"
BOUNDARIES_DIR.mkdir(parents=True, exist_ok=True)

BPS_PATH = BOUNDARIES_DIR / "jakarta_demographics_bps.json"
OUTPUT_GEOJSON_PATH = BOUNDARIES_DIR / "jakarta_44_kecamatan.geojson"

# Known public GeoJSON sources on GitHub for Jakarta/Indonesia kecamatan
GITHUB_GEOJSON_URLS = [
    "https://raw.githubusercontent.com/SakifAbdillah/jakartaKecamatanGeoJSON/master/jakarta_kecamatan.json",
    "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia-kecamatan.json",
    "https://raw.githubusercontent.com/ans-4175/peta-indonesia-geojson/master/indonesia-kecamatan.json"
]

def load_bps_demographics() -> Dict[str, Dict[str, Any]]:
    """Loads BPS demographic lookup keyed by normalized name and kemendagri code."""
    with open(BPS_PATH, "r", encoding="utf-8") as f:
        bps_data = json.load(f)
    
    lookup = {}
    for city in bps_data["cities"]:
        city_name = city["name"]
        for dist in city["districts"]:
            norm_name = dist["name"].strip().lower()
            lookup[norm_name] = {
                **dist,
                "city_name": city_name,
                "parent_kemendagri_code": city["kemendagri_code"]
            }
            # Also key by code
            lookup[dist["kemendagri_code"]] = lookup[norm_name]
    return lookup

def try_fetch_github_geojson() -> Optional[Dict[str, Any]]:
    """Attempts to download GeoJSON from GitHub."""
    headers = {"User-Agent": "DistrictSpatialIntelligence/1.0"}
    for url in GITHUB_GEOJSON_URLS:
        try:
            logger.info(f"Checking GeoJSON source: {url} ...")
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                logger.info(f"Successfully downloaded GeoJSON with {len(features)} features from {url}")
                return data
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
    return None

def fetch_overpass_districts() -> Optional[Dict[str, Any]]:
    """Fetches administrative boundary relations for DKI Jakarta from Overpass API."""
    query = """
    [out:json][timeout:120];
    (
      relation["admin_level"="7"]["boundary"="administrative"](-6.3708,106.6800,-6.0800,106.9740);
    );
    out tags;
    """
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"
    ]
    for ep in endpoints:
        try:
            logger.info(f"Attempting Overpass boundary query on {ep}...")
            r = requests.post(ep, data={"data": query}, timeout=60)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.warning(f"Overpass request failed: {e}")
    return None

def main():
    bps_lookup = load_bps_demographics()
    logger.info(f"Loaded {len(bps_lookup)} BPS demographic entries.")

    geojson_data = try_fetch_github_geojson()
    if not geojson_data:
        logger.warning("Could not download external GeoJSON directly. Checking if local file exists...")
        if OUTPUT_GEOJSON_PATH.exists():
            logger.info(f"Using existing {OUTPUT_GEOJSON_PATH}")
            return
        
    logger.info("Processing and standardizing GeoJSON features for 44 Kecamatan...")
    # Standardize features
    if geojson_data and "features" in geojson_data:
        standardized_features = []
        for feat in geojson_data["features"]:
            props = feat.get("properties", {})
            # Match district name
            raw_name = (
                props.get("name") or 
                props.get("KECAMATAN") or 
                props.get("WADMKC") or 
                props.get("nm_kecamatan") or 
                ""
            ).strip()
            
            # Remove prefix "Kecamatan"
            clean_name = raw_name.replace("Kecamatan", "").replace("Kec.", "").strip()
            norm_key = clean_name.lower()
            
            bps_info = bps_lookup.get(norm_key)
            if not bps_info:
                # Try finding in keys
                for k in bps_lookup:
                    if k in norm_key or norm_key in k:
                        bps_info = bps_lookup[k]
                        break
            
            if bps_info:
                geom = feat.get("geometry")
                new_props = {
                    "kemendagri_code": bps_info["kemendagri_code"],
                    "bps_code": bps_info["bps_code"],
                    "name": bps_info["name"],
                    "city_name": bps_info["city_name"],
                    "population": bps_info["population"],
                    "area_km2": bps_info["area_km2"],
                    "density_per_km2": bps_info["density_per_km2"]
                }
                standardized_features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": new_props
                })
        
        if len(standardized_features) > 0:
            result_geojson = {
                "type": "FeatureCollection",
                "features": standardized_features
            }
            with open(OUTPUT_GEOJSON_PATH, "w", encoding="utf-8") as f:
                json.dump(result_geojson, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(standardized_features)} standardized kecamatan to {OUTPUT_GEOJSON_PATH}")
            return

    logger.info("Done fetch boundaries script.")

if __name__ == "__main__":
    main()
