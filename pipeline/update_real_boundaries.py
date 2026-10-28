"""
Download real Jakarta Kecamatan GeoJSON, standardize properties with BPS metadata,
update PostGIS database and save to frontend and pipeline datasets.
"""

import os
import json
import logging
import urllib.request
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "boundaries"
BPS_PATH = DATA_DIR / "jakarta_demographics_bps.json"
TARGET_GEOJSON = DATA_DIR / "jakarta_44_kecamatan.geojson"
FRONTEND_GEOJSON = Path(__file__).resolve().parent.parent / "frontend" / "data" / "boundaries" / "jakarta_44_kecamatan.geojson"

RAW_GEOJSON_URL = "https://raw.githubusercontent.com/SakifAbdillah/jakartaKecamatanGeoJSON/master/kecamatan.geojson"

def download_and_process():
    logger.info(f"Downloading real GeoJSON from {RAW_GEOJSON_URL}...")
    req = urllib.request.Request(RAW_GEOJSON_URL, headers={"User-Agent": "DistrictSpatialIntelligence/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw_data = json.loads(resp.read().decode("utf-8"))

    logger.info(f"Loaded {len(raw_data.get('features', []))} features from source.")

    # Load BPS metadata
    with open(BPS_PATH, "r", encoding="utf-8") as f:
        bps_data = json.load(f)

    # Build lookup
    lookup = {}
    for city in bps_data["cities"]:
        city_name = city["name"]
        for dist in city["districts"]:
            key = dist["name"].strip().lower()
            lookup[key] = {
                **dist,
                "city_name": city_name
            }
            # Add variations
            lookup[key.replace(" ", "")] = lookup[key]

    matched_features = []
    unmatched_names = []

    for feat in raw_data.get("features", []):
        props = feat.get("properties", {})
        raw_name = props.get("name") or props.get("KECAMATAN") or props.get("WADMKC") or ""
        clean_name = raw_name.replace("Kecamatan", "").replace("Kec.", "").strip().lower()
        
        info = lookup.get(clean_name) or lookup.get(clean_name.replace(" ", ""))
        if not info:
            # Fuzzy substring match
            for k, val in lookup.items():
                if k in clean_name or clean_name in k:
                    info = val
                    break

        if info:
            new_props = {
                "kemendagri_code": info["kemendagri_code"],
                "bps_code": info["bps_code"],
                "name": info["name"],
                "city_name": info["city_name"],
                "population": info["population"],
                "area_km2": info["area_km2"],
                "density_per_km2": info["density_per_km2"]
            }
            matched_features.append({
                "type": "Feature",
                "properties": new_props,
                "geometry": feat["geometry"]
            })
        else:
            unmatched_names.append(raw_name)

    logger.info(f"Matched {len(matched_features)} districts with real polygons. Unmatched: {unmatched_names}")

    if matched_features:
        final_geojson = {
            "type": "FeatureCollection",
            "name": "jakarta_44_kecamatan",
            "features": matched_features
        }

        # Save to pipeline data
        with open(TARGET_GEOJSON, "w", encoding="utf-8") as f:
            json.dump(final_geojson, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved real GeoJSON to {TARGET_GEOJSON}")

        # Save to frontend data
        FRONTEND_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
        with open(FRONTEND_GEOJSON, "w", encoding="utf-8") as f:
            json.dump(final_geojson, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved real GeoJSON to {FRONTEND_GEOJSON}")

        # Update PostGIS
        update_postgis(matched_features)

def update_postgis(features):
    conn_params = {
        "dbname": os.getenv("POSTGRES_DB", "district_profiling"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres_spatial_dev"),
        "host": "127.0.0.1",
        "port": int(os.getenv("POSTGRES_PORT", 5432))
    }
    logger.info("Updating PostGIS kecamatan boundaries with real polygons...")
    conn = psycopg2.connect(**conn_params)
    with conn.cursor() as cur:
        updated = 0
        for feat in features:
            code = feat["properties"]["kemendagri_code"]
            geom_json = json.dumps(feat["geometry"])
            cur.execute("""
                UPDATE kecamatan 
                SET boundary = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                WHERE kemendagri_code = %s;
            """, (geom_json, code))
            updated += cur.rowcount
        conn.commit()
        logger.info(f"Successfully updated {updated} kecamatan in PostGIS with real boundaries!")
    conn.close()

if __name__ == "__main__":
    download_and_process()
